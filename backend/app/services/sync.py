"""
services/sync.py -- Access terminal synchronization service (Person B).

Authoritative contracts:
  - docs/api-contract.md §5.4 (Device Synchronization Protocol)
  - docs/credential-policy.md §2.3 (Cryptographic Test Vector 2: X-Server-Signature)
  - docs/credential-policy.md §4 (Transaction Boundaries & Lock Ordering)
  - docs/credential-policy.md §5 (Synchronization Contract & Device Rules DR-1 to DR-8)
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.errors import AppError, SyncStateInconsistentError, UnknownNodeError
from app.models.access_events import AccessEvent, EventReason, EventSource, EventType
from app.models.credentials import Credential, CredentialStatus
from app.models.nodes import Node
from app.models.resources import Resource
from app.models.sync_state import SyncState
from app.schemas.device import CredentialSyncOut, DeviceSyncIn, DeviceSyncOut
from app.services.credentials import sweep_expired_credentials
from app.services.events import record_server_event
from app.services.sequence import allocate_next_change_seq
from app.services.time_utils import format_utc_timestamp, now_utc, parse_utc_timestamp


def sign_sync_response(response_body_bytes: bytes, device_api_key: str | None = None) -> str:
    """
    Computes the HMAC-SHA256 signature for X-Server-Signature response header.
    Follows docs/credential-policy.md §2.3 (Test Vector 2):
      X-Server-Signature = hex(HMAC-SHA256(DEVICE_API_KEY.encode('utf-8'), response_body_bytes))
    Returns 64-character lowercase hexadecimal digest.
    """
    key = device_api_key if device_api_key is not None else get_settings().DEVICE_API_KEY
    if not key:
        raise ValueError("DEVICE_API_KEY is not configured.")

    key_bytes = key.encode("utf-8")
    return hmac.new(key_bytes, response_body_bytes, hashlib.sha256).hexdigest().lower()


def verify_sync_response_signature(
    response_body_bytes: bytes,
    signature: str,
    device_api_key: str | None = None,
) -> bool:
    """
    Constant-time comparison verifying an X-Server-Signature header against the response body bytes.
    """
    if not signature:
        return False
    try:
        expected = sign_sync_response(response_body_bytes, device_api_key)
        return hmac.compare_digest(expected, signature.strip().lower())
    except ValueError:
        return False


def _safe_format_utc(dt: datetime) -> str:
    """Ensure timezone-awareness before formatting to strict ISO-8601 UTC with 'Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_utc_timestamp(dt)


def process_device_sync(
    db: Session,
    payload: DeviceSyncIn,
    current_time: datetime | None = None,
    device_api_key: str | None = None,
) -> tuple[DeviceSyncOut, bytes, str]:
    """
    Core device sync execution handler.

    Enforces:
      1. Node existence check (404 unknown_node if unrecognized).
      2. Sync state consistency check (503 sync_state_inconsistent if current_seq < max(credentials.change_seq)).
      3. Pre-sync expiry sweep (ensuring expired active rows transition to expired and advance change_seq).
      4. Single write transaction for event ingestion, credential status transition, and node tracking:
         - Idempotent insertion (ON CONFLICT DO NOTHING semantics).
         - Stale-epoch handling: unknown credential_id inserted as NULL with note="unknown_credential".
         - 'credential_accepted' transitions active credential to 'consumed' with allocate_next_change_seq.
         - Node heartbeat tracking (last_seen_at, last_acked_seq, firmware_version, time_state).
         - Fail-closed transaction boundary: event acknowledgement occurs ONLY after commit.
      5. Full resync vs Delta sync calculation:
         - Epoch mismatch or last_seq > server_seq -> full_resync=True (active credentials snapshot).
         - Otherwise -> full_resync=False (monotonic delta records where change_seq > last_seq).
      6. Strict change_seq ordering: ascending within (from_seq, to_seq].
      7. Echoes request_nonce and serializes canonical response bytes signed with X-Server-Signature.

    Returns:
      tuple of (DeviceSyncOut, response_body_bytes, x_server_signature_hex)
    """
    settings = get_settings()
    server_time_dt = current_time if current_time is not None else now_utc()
    server_time_str = _safe_format_utc(server_time_dt)

    # 1. Node validation
    node = db.query(Node).filter(Node.node_code == payload.node_code).first()
    if node is None:
        raise UnknownNodeError(f"Terminal node '{payload.node_code}' unrecognized by server.")

    # 2. Database sync_state counter consistency check
    sync_state = db.query(SyncState).filter(SyncState.id == 1).first()
    if sync_state is None:
        raise SyncStateInconsistentError("Database sync_state singleton row (id=1) is missing.")

    max_cred_seq = db.query(func.coalesce(func.max(Credential.change_seq), 0)).scalar() or 0
    if sync_state.current_seq < max_cred_seq:
        raise SyncStateInconsistentError(
            f"Database sync_state.current_seq ({sync_state.current_seq}) is less than "
            f"max(credentials.change_seq) ({max_cred_seq})."
        )

    # 3. Policy sweep: sweep expired active credentials before calculating delta
    sweep_expired_credentials(db, now=server_time_dt)

    # 4. Ingest telemetry events inside guarded transaction
    committed_event_ids: list[str] = []
    try:
        # Pre-load resource mapping by code for fast lookup
        resources_by_code: dict[str, Resource] = {
            r.code.upper(): r for r in db.query(Resource).all()
        }

        for ev in payload.events:
            # Check for duplicate event (idempotent ON CONFLICT DO NOTHING semantics)
            existing_ev = (
                db.query(AccessEvent).filter(AccessEvent.event_id == ev.event_id).first()
            )
            if existing_ev is not None:
                # Already committed previously; safely ack without re-inserting
                committed_event_ids.append(ev.event_id)
                continue

            # Resolve resource ID
            res_id: Optional[int] = None
            if ev.resource_code:
                res = resources_by_code.get(ev.resource_code.upper())
                if res:
                    res_id = res.id

            # Parse event device_time
            ev_dt: Optional[datetime] = None
            if ev.device_time:
                try:
                    ev_dt = parse_utc_timestamp(ev.device_time)
                except (ValueError, TypeError):
                    ev_dt = None

            # Handle credential reference and stale-epoch detection
            actual_cred_id: Optional[int] = None
            actual_note: Optional[str] = None
            cred: Optional[Credential] = None

            if ev.credential_id is not None:
                cred = db.get(Credential, ev.credential_id)
                if cred is None:
                    # Stale epoch / reset DB: store NULL and note unknown_credential
                    actual_cred_id = None
                    actual_note = "unknown_credential"
                else:
                    actual_cred_id = cred.id

            # Credential consumption transition on credential_accepted
            if ev.event_type == EventType.CREDENTIAL_ACCEPTED.value and cred is not None:
                if cred.status == CredentialStatus.ACTIVE.value:
                    next_seq = allocate_next_change_seq(db)
                    cred.status = CredentialStatus.CONSUMED.value
                    cred.consumed_at = ev_dt or server_time_dt
                    cred.consumed_node_id = node.id
                    cred.change_seq = next_seq

                    record_server_event(
                        db=db,
                        event_type=EventType.CREDENTIAL_CONSUMED.value,
                        resource_id=cred.resource_id,
                        request_id=cred.request_id,
                        credential_id=cred.id,
                        note="Credential consumed at terminal",
                    )

            # Insert device telemetry event
            access_event = AccessEvent(
                event_id=ev.event_id,
                source=EventSource.DEVICE.value,
                event_type=ev.event_type,
                reason=ev.reason,
                node_id=node.id,
                resource_id=res_id,
                credential_id=actual_cred_id,
                note=actual_note,
                device_time=ev_dt,
                time_trusted=ev.time_trusted,
                occurred_at=server_time_dt,
            )
            db.add(access_event)
            committed_event_ids.append(ev.event_id)

        # Update node connectivity and sequence pointers
        node.firmware_version = payload.firmware_version
        node.last_seen_at = server_time_dt
        node.time_state = payload.time_state
        node.last_acked_seq = payload.last_seq

        db.commit()
    except Exception:
        db.rollback()
        raise

    # Refresh sync_state to observe any sequence increments from consumption/sweep
    db.refresh(sync_state)
    current_server_seq = sync_state.current_seq

    # 5. Determine sync mode (Full Resync vs Delta Sync)
    is_epoch_mismatch = payload.epoch != sync_state.epoch
    is_sequence_ahead = payload.last_seq > current_server_seq
    full_resync = is_epoch_mismatch or is_sequence_ahead

    page_size = settings.SYNC_PAGE_SIZE

    if full_resync:
        # Full resync: send active credentials snapshot
        query = (
            db.query(Credential)
            .options(joinedload(Credential.resource))
            .filter(
                Credential.status == CredentialStatus.ACTIVE.value,
                Credential.valid_until > server_time_dt,
            )
            .order_by(Credential.change_seq.asc())
        )
        creds = query.limit(page_size).all()
        total_active = query.count()
        has_more = total_active > len(creds)
        from_seq = 0
        if not has_more:
            to_seq = current_server_seq
        else:
            to_seq = creds[-1].change_seq if creds else 0
    else:
        # Delta sync: monotonic changes strictly > last_seq
        query = (
            db.query(Credential)
            .options(joinedload(Credential.resource))
            .filter(Credential.change_seq > payload.last_seq)
            .order_by(Credential.change_seq.asc())
        )
        creds = query.limit(page_size).all()
        if creds:
            max_returned_seq = creds[-1].change_seq
            has_more = (
                db.query(Credential)
                .filter(Credential.change_seq > max_returned_seq)
                .count()
                > 0
            )
            from_seq = payload.last_seq
            to_seq = max_returned_seq
        else:
            has_more = False
            from_seq = payload.last_seq
            to_seq = payload.last_seq

    # 6. Format credentials for response payload
    creds_out: list[CredentialSyncOut] = []
    for c in creds:
        res_code = c.resource.code if c.resource else "A"
        creds_out.append(
            CredentialSyncOut(
                id=c.id,
                change_seq=c.change_seq,
                resource_code=res_code,
                status=c.status,
                valid_from=_safe_format_utc(c.valid_from),
                valid_until=_safe_format_utc(c.valid_until),
                pin_hmac=c.pin_hmac,
            )
        )

    # 7. Build and serialize sync response
    sync_out = DeviceSyncOut(
        server_time=server_time_str,
        epoch=sync_state.epoch,
        request_nonce=payload.request_nonce,
        full_resync=full_resync,
        from_seq=from_seq,
        to_seq=to_seq,
        server_seq=current_server_seq,
        has_more=has_more,
        credentials=creds_out,
        acked_event_ids=committed_event_ids,
    )

    response_bytes = sync_out.model_dump_json().encode("utf-8")
    signature = sign_sync_response(response_bytes, device_api_key=device_api_key)

    return sync_out, response_bytes, signature
