"""
backend/app/services/events.py -- Telemetry and audit event service.

Implements Person A's event-related responsibilities:
  - Policy 4: Atomic audit event emission during server state transitions.
  - Policy 4.1 & Contract 5.4: Durable ingestion & stale/unknown credential handling.
  - Model constraint compliance (EventSource, EventType, EventReason, time_trusted checks).

Guarantees & Invariants:
-------------------------
1. Server Audit Event Emission:
   - Server events (source='server') must have time_trusted=None.
   - Event IDs are generated in the canonical server format: 'srv-<8-hex-random>'.
   - Mandatory events:
       * 'request_created' upon POST /access-requests.
       * 'pin_revealed' upon GET /access-requests/{id}/pin.
       * Admin events ('request_approved', 'credential_issued', etc.) owned by Person B.

2. Stale / Unknown Credential Handling (Contract 5.4 & Policy 4.1):
   - Access terminals can queue and sync events after a database epoch reset.
   - If an event carries a credential_id that does not exist in the database,
     it MUST be inserted with credential_id = NULL and note = 'unknown_credential'
     (or appending to an existing note).
   - This prevents foreign key violations (RESTRICT/SET NULL) and guarantees
     audit logs are never lost due to epoch shifts.

3. Idempotent Ingestion:
   - Devices resend queued events until acknowledged.
   - Insertion is guarded by event_id uniqueness (ON CONFLICT DO NOTHING semantics).
   - Duplicate event_id submissions are safely discarded without error.

4. Integration Points with Person B:
   - Person B owns POST /device/v1/sync (endpoint and crypto verification).
   - Person B will invoke ingest_device_event() in a batch for incoming device telemetry.
   - Person B will guarded-update credentials to 'consumed' on 'credential_accepted'
     using allocate_next_change_seq(db) from services.sequence.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.models.access_events import AccessEvent, EventReason, EventSource, EventType
from app.models.access_requests import AccessRequest
from app.models.credentials import Credential, CredentialStatus
from app.models.resources import Resource


def generate_server_event_id() -> str:
    """Generate a canonical server audit event_id: 'srv-<8-hex-random>'."""
    return f"srv-{secrets.token_hex(4)}"


# ---------------------------------------------------------------------------
# Validation Helpers
# ---------------------------------------------------------------------------

def validate_event_fields(
    *,
    source: str,
    event_type: str,
    reason: Optional[str] = None,
    time_trusted: Optional[bool] = None,
) -> None:
    """
    Validate event fields against accepted models and check constraints.

    Raises:
      ValueError if any value violates database check constraints.
    """
    valid_sources = {s.value for s in EventSource}
    if source not in valid_sources:
        raise ValueError(f"Invalid event source '{source}'. Must be one of {valid_sources}.")

    valid_event_types = {t.value for t in EventType}
    if event_type not in valid_event_types:
        raise ValueError(f"Invalid event_type '{event_type}'. Must be one of {valid_event_types}.")

    if reason is not None:
        valid_reasons = {r.value for r in EventReason}
        if reason not in valid_reasons:
            raise ValueError(f"Invalid event reason '{reason}'. Must be one of {valid_reasons}.")

    # Check constraint: ck_access_events_device_time_trusted
    # source != 'device' OR time_trusted IS NOT NULL
    if source == EventSource.DEVICE.value and time_trusted is None:
        raise ValueError("Device events (source='device') must provide a non-null boolean time_trusted.")


# ---------------------------------------------------------------------------
# Server Audit Events (Person A Responsibilities)
# ---------------------------------------------------------------------------

def record_server_event(
    db: Session,
    *,
    event_type: str,
    resource_id: Optional[int] = None,
    request_id: Optional[int] = None,
    credential_id: Optional[int] = None,
    actor_user_id: Optional[int] = None,
    reason: Optional[str] = None,
    note: Optional[str] = None,
    event_id: Optional[str] = None,
) -> AccessEvent:
    """
    Create and record a server audit event.

    Server events always set source='server' and time_trusted=None.
    """
    validate_event_fields(
        source=EventSource.SERVER.value,
        event_type=event_type,
        reason=reason,
        time_trusted=None,
    )

    eid = event_id or generate_server_event_id()

    # Stale/unknown credential check:
    actual_cred_id = credential_id
    actual_note = note
    if credential_id is not None:
        cred = db.get(Credential, credential_id)
        if cred is None:
            actual_cred_id = None
            actual_note = f"{note}; unknown_credential" if note else "unknown_credential"

    event = AccessEvent(
        event_id=eid,
        source=EventSource.SERVER.value,
        event_type=event_type,
        reason=reason,
        actor_user_id=actor_user_id,
        request_id=request_id,
        resource_id=resource_id,
        credential_id=actual_cred_id,
        note=actual_note,
        device_time=None,
        time_trusted=None,
    )
    db.add(event)
    return event


def record_request_created(
    db: Session,
    request: AccessRequest,
    actor_user_id: int,
) -> AccessEvent:
    """
    Atomically record a 'request_created' audit event for a newly submitted request.
    """
    return record_server_event(
        db=db,
        event_type=EventType.REQUEST_CREATED.value,
        request_id=request.id,
        resource_id=request.resource_id,
        actor_user_id=actor_user_id,
    )


def record_pin_revealed(
    db: Session,
    request: AccessRequest,
    credential_id: int,
    actor_user_id: int,
) -> AccessEvent:
    """
    Atomically record a 'pin_revealed' audit event when an owner inspects their PIN.
    """
    return record_server_event(
        db=db,
        event_type=EventType.PIN_REVEALED.value,
        request_id=request.id,
        resource_id=request.resource_id,
        credential_id=credential_id,
        actor_user_id=actor_user_id,
    )


# ---------------------------------------------------------------------------
# Device Event Ingestion Helper (Interface for Person B's Sync Service)
# ---------------------------------------------------------------------------

def ingest_device_event(
    db: Session,
    *,
    event_id: str,
    event_type: str,
    device_time: Optional[datetime] = None,
    time_trusted: bool,
    resource_id: Optional[int] = None,
    credential_id: Optional[int] = None,
    node_id: Optional[int] = None,
    reason: Optional[str] = None,
    note: Optional[str] = None,
) -> Optional[AccessEvent]:
    """
    Ingest a telemetry event received from an ESP32 access terminal.

    Contract 5.4 / Policy 4.1 Invariants:
      1. Idempotency: Checks if event_id already exists. If yes, returns None (no duplicate).
      2. Stale/Unknown Credential Handling: If credential_id does not exist in DB,
         inserts with credential_id = NULL and note = 'unknown_credential'.
      3. Validates check constraints (source='device', time_trusted not null).

    Returns:
      Created AccessEvent row, or None if the event was already ingested (duplicate).
    """
    validate_event_fields(
        source=EventSource.DEVICE.value,
        event_type=event_type,
        reason=reason,
        time_trusted=time_trusted,
    )

    # 1. Idempotency check: ON CONFLICT DO NOTHING semantics
    existing = db.query(AccessEvent).filter(AccessEvent.event_id == event_id).first()
    if existing is not None:
        return None

    # 2. Stale/Unknown credential check:
    actual_cred_id = credential_id
    actual_note = note
    cred = None
    if credential_id is not None:
        cred = db.get(Credential, credential_id)
        if cred is None:
            actual_cred_id = None
            actual_note = f"{note}; unknown_credential" if note else "unknown_credential"

    # 3. Credential consumption transition:
    # If credential_accepted is received for an active credential, transition it to consumed
    if event_type == EventType.CREDENTIAL_ACCEPTED.value and cred is not None:
        if cred.status == CredentialStatus.ACTIVE.value:
            from app.services.sequence import allocate_next_change_seq

            cred.status = CredentialStatus.CONSUMED.value
            cred.consumed_at = device_time or datetime.now(timezone.utc)
            if node_id is not None:
                cred.consumed_node_id = node_id
            cred.change_seq = allocate_next_change_seq(db)

    event = AccessEvent(
        event_id=event_id,
        source=EventSource.DEVICE.value,
        event_type=event_type,
        reason=reason,
        node_id=node_id,
        resource_id=resource_id,
        credential_id=actual_cred_id,
        note=actual_note,
        device_time=device_time,
        time_trusted=time_trusted,
    )
    db.add(event)
    return event
