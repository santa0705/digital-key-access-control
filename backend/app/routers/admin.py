"""
routers/admin.py -- Administrative endpoints for Person A and Person B.

Implements:
  - GET /admin/logs  (Contract 5.3)
  - GET /admin/nodes (Contract 5.3)
  - GET /admin/access-requests (Contract 5.3)
  - POST /admin/access-requests/{id}/approve (Contract 5.3)
  - POST /admin/access-requests/{id}/reject (Contract 5.3)
  - POST /admin/credentials/{id}/revoke (Contract 5.3)

Security:
  - All routes require Bearer token with 'admin' role. Non-admin users receive 403 forbidden.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db import get_db
from app.deps import AuthenticatedUser, require_admin
from app.errors import (
    AppError,
    err_active_credential_exists,
    err_invalid_state,
    err_not_found,
    err_window_expired,
)
from app.models.access_events import AccessEvent, EventReason, EventSource, EventType
from app.models.access_requests import AccessRequest, RequestStatus
from app.models.credentials import Credential, CredentialStatus, RevokeReason
from app.models.nodes import Node
from app.models.sync_state import SyncState
from app.schemas.access_requests import AccessRequestOut
from app.schemas.admin import (
    AdminApprovePayload,
    AdminLogEntryOut,
    AdminNodeOut,
    AdminRejectPayload,
    AdminRevokePayload,
    CredentialRevokeOut,
)
from app.services.credentials import (
    compute_pin_hmac,
    encrypt_pin,
    generate_pin,
    sweep_expired_credentials,
)
from app.services.events import record_server_event
from app.services.sequence import allocate_next_change_seq

router = APIRouter(prefix="/admin", tags=["Admin Operations"])
_settings = get_settings()


def _format_utc_z(dt: Optional[datetime]) -> Optional[str]:
    """Format a datetime as strict ISO-8601 UTC with trailing 'Z'."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Admin Access Requests & Credential Lifecycle (Person B)
# ---------------------------------------------------------------------------

@router.get(
    "/access-requests",
    response_model=list[AccessRequestOut],
    summary="List access requests filtered by status",
    description="List access requests filtered by status (defaults to 'pending').",
)
def list_admin_access_requests(
    status_filter: Literal["pending", "approved", "rejected", "revoked", "all"] = Query(
        default="pending",
        alias="status",
        description="Filter by request status: 'pending', 'approved', 'rejected', 'revoked', or 'all'",
    ),
    db: Session = Depends(get_db),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> list[AccessRequestOut]:
    """
    GET /admin/access-requests?status={pending|approved|rejected|revoked|all}
    """
    query = (
        db.query(AccessRequest)
        .options(
            joinedload(AccessRequest.resource),
            joinedload(AccessRequest.user),
            joinedload(AccessRequest.credential),
        )
    )

    if status_filter != "all":
        query = query.filter(AccessRequest.status == status_filter)

    requests = (
        query.order_by(AccessRequest.created_at.desc(), AccessRequest.id.desc())
        .all()
    )
    return [AccessRequestOut.from_orm_obj(r) for r in requests]


@router.post(
    "/access-requests/{id}/approve",
    response_model=AccessRequestOut,
    summary="Atomically approve request and generate active credential",
    description="Atomically approve access request and issue active credential. Enforces Rule R1.",
)
def approve_access_request(
    id: int,
    payload: AdminApprovePayload,
    db: Session = Depends(get_db),
    admin: AuthenticatedUser = Depends(require_admin),
) -> AccessRequestOut:
    """
    POST /admin/access-requests/{id}/approve
    """
    target = (
        db.query(AccessRequest)
        .options(
            joinedload(AccessRequest.resource),
            joinedload(AccessRequest.user),
            joinedload(AccessRequest.credential),
        )
        .filter(AccessRequest.id == id)
        .first()
    )
    if target is None:
        raise err_not_found(f"Access request #{id} not found.")

    if target.status != RequestStatus.PENDING.value:
        raise err_invalid_state(
            f"Request #{id} is already {target.status}; only pending requests can be approved."
        )

    now = datetime.now(timezone.utc)
    target_end = target.end_at if target.end_at.tzinfo else target.end_at.replace(tzinfo=timezone.utc)
    if target_end <= now:
        raise err_window_expired("Access request validity window has already passed.")

    # Sweep expired credentials for this resource before checking Rule R1 (docs/credential-policy.md Section 4.1)
    sweep_expired_credentials(db, resource_id=target.resource_id, now=now)

    # Rule R1 Check: At most one active credential per resource
    existing_active = (
        db.query(Credential)
        .filter(
            Credential.resource_id == target.resource_id,
            Credential.status == CredentialStatus.ACTIVE.value,
        )
        .first()
    )

    if existing_active is not None and not payload.replace_existing:
        resource_code = target.resource.code if target.resource else "A"
        raise err_active_credential_exists(
            f"Resource {resource_code} has active credential {existing_active.id} "
            f"(request {existing_active.request_id}). Revoke it or approve with replace_existing."
        )

    try:
        # Replacement scenario: revoke existing active credential atomically
        if existing_active is not None and payload.replace_existing:
            rev_seq = allocate_next_change_seq(db)
            existing_active.status = CredentialStatus.REVOKED.value
            existing_active.revoke_reason = RevokeReason.SUPERSEDED.value
            existing_active.revoked_at = now
            existing_active.revoked_by = admin.id
            existing_active.change_seq = rev_seq

            # Update parent request of the superseded credential
            parent_req = db.get(AccessRequest, existing_active.request_id)
            if parent_req and parent_req.status != RequestStatus.REVOKED.value:
                parent_req.status = RequestStatus.REVOKED.value

            record_server_event(
                db=db,
                event_type=EventType.CREDENTIAL_REVOKED.value,
                reason=EventReason.REVOKED.value,
                resource_id=target.resource_id,
                request_id=existing_active.request_id,
                credential_id=existing_active.id,
                actor_user_id=admin.id,
                note="Superseded by replacement credential",
            )

        # Issue new active credential
        pin = generate_pin()
        res_code = target.resource.code if target.resource else "A"
        pin_hmac = compute_pin_hmac(res_code, pin, _settings.PIN_HMAC_KEY)
        pin_enc = encrypt_pin(pin, _settings.PIN_ENC_KEY)
        new_seq = allocate_next_change_seq(db)

        new_cred = Credential(
            request_id=target.id,
            resource_id=target.resource_id,
            pin_hmac=pin_hmac,
            pin_encrypted=pin_enc,
            valid_from=target.start_at,
            valid_until=target.end_at,
            status=CredentialStatus.ACTIVE.value,
            change_seq=new_seq,
        )
        db.add(new_cred)
        db.flush()

        # Update target request
        target.status = RequestStatus.APPROVED.value
        target.decided_by = admin.id
        target.decided_at = now
        target.decision_note = payload.note.strip() if payload.note and payload.note.strip() else "Approved by administrator"

        record_server_event(
            db=db,
            event_type=EventType.REQUEST_APPROVED.value,
            resource_id=target.resource_id,
            request_id=target.id,
            actor_user_id=admin.id,
            note=target.decision_note,
        )
        record_server_event(
            db=db,
            event_type=EventType.CREDENTIAL_ISSUED.value,
            resource_id=target.resource_id,
            request_id=target.id,
            credential_id=new_cred.id,
            actor_user_id=admin.id,
        )

        db.commit()
    except ValueError as exc:
        db.rollback()
        raise AppError(
            code="internal_error",
            message="Credential encryption failed due to key configuration error.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(target)
    return AccessRequestOut.from_orm_obj(target)


@router.post(
    "/access-requests/{id}/reject",
    response_model=AccessRequestOut,
    summary="Reject pending access request",
    description="Reject a pending access request.",
)
def reject_access_request(
    id: int,
    payload: AdminRejectPayload,
    db: Session = Depends(get_db),
    admin: AuthenticatedUser = Depends(require_admin),
) -> AccessRequestOut:
    """
    POST /admin/access-requests/{id}/reject
    """
    target = (
        db.query(AccessRequest)
        .options(
            joinedload(AccessRequest.resource),
            joinedload(AccessRequest.user),
            joinedload(AccessRequest.credential),
        )
        .filter(AccessRequest.id == id)
        .first()
    )
    if target is None:
        raise err_not_found(f"Access request #{id} not found.")

    if target.status != RequestStatus.PENDING.value:
        raise err_invalid_state(
            f"Request #{id} is already {target.status}; only pending requests can be rejected."
        )

    now = datetime.now(timezone.utc)
    target.status = RequestStatus.REJECTED.value
    target.decided_by = admin.id
    target.decided_at = now
    target.decision_note = payload.note.strip() if payload.note and payload.note.strip() else "Rejected by administrator"

    try:
        record_server_event(
            db=db,
            event_type=EventType.REQUEST_REJECTED.value,
            resource_id=target.resource_id,
            request_id=target.id,
            actor_user_id=admin.id,
            note=target.decision_note,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(target)
    return AccessRequestOut.from_orm_obj(target)


@router.post(
    "/credentials/{id}/revoke",
    response_model=CredentialRevokeOut,
    summary="Manually revoke active credential",
    description="Manually revoke an active credential.",
)
def revoke_credential(
    id: int,
    payload: AdminRevokePayload,
    db: Session = Depends(get_db),
    admin: AuthenticatedUser = Depends(require_admin),
) -> CredentialRevokeOut:
    """
    POST /admin/credentials/{id}/revoke
    """
    target = db.get(Credential, id)
    if target is None:
        raise err_not_found(f"Credential #{id} not found.")

    now = datetime.now(timezone.utc)
    target_until = target.valid_until if target.valid_until.tzinfo else target.valid_until.replace(tzinfo=timezone.utc)
    if target.status == CredentialStatus.ACTIVE.value and now >= target_until:
        sweep_expired_credentials(db, resource_id=target.resource_id, now=now)
        db.commit()

    if target.status != CredentialStatus.ACTIVE.value:
        raise err_invalid_state(
            f"Credential #{id} is already in terminal status '{target.status}'."
        )
    try:
        rev_seq = allocate_next_change_seq(db)
        target.status = CredentialStatus.REVOKED.value
        target.revoke_reason = RevokeReason.ADMIN.value
        target.revoked_at = now
        target.revoked_by = admin.id
        target.change_seq = rev_seq

        # Update corresponding access request if present
        parent_req = db.get(AccessRequest, target.request_id)
        if parent_req and parent_req.status != RequestStatus.REVOKED.value:
            parent_req.status = RequestStatus.REVOKED.value

        note_text = payload.note.strip() if payload.note and payload.note.strip() else "Admin manual revocation"
        record_server_event(
            db=db,
            event_type=EventType.CREDENTIAL_REVOKED.value,
            reason=EventReason.REVOKED.value,
            resource_id=target.resource_id,
            request_id=target.request_id,
            credential_id=target.id,
            actor_user_id=admin.id,
            note=note_text,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(target)
    return CredentialRevokeOut(
        id=target.id,
        status=target.status,
        revoke_reason=target.revoke_reason,
        revoked_at=_format_utc_z(target.revoked_at) or "",
        change_seq=target.change_seq,
    )


# ---------------------------------------------------------------------------
# Admin Audit Logs & Nodes (Person A)
# ---------------------------------------------------------------------------

@router.get(
    "/logs",
    response_model=list[AdminLogEntryOut],
    summary="Get audit logs",
    description=(
        "Retrieve unified audit and telemetry log entries sorted newest first. "
        "Filterable by source ('all', 'device', 'server'). "
        "Requires admin privileges."
    ),
)
def get_admin_logs(
    limit: int = Query(default=100, ge=1, le=500, description="Max logs to return (1-500)"),
    source: str = Query(
        default="all",
        pattern="^(all|device|server)$",
        description="Filter by source: 'all', 'device', or 'server'",
    ),
    db: Session = Depends(get_db),
    _admin_user: AuthenticatedUser = Depends(require_admin),
) -> list[AdminLogEntryOut]:
    """
    GET /admin/logs?limit=100&source=all

    Returns newest-first audit and telemetry logs with actor and resource mappings.
    """
    query = (
        db.query(AccessEvent)
        .options(
            joinedload(AccessEvent.resource),
            joinedload(AccessEvent.actor_user),
            joinedload(AccessEvent.node),
        )
    )

    if source == "device":
        query = query.filter(AccessEvent.source == "device")
    elif source == "server":
        query = query.filter(AccessEvent.source == "server")

    events = (
        query.order_by(AccessEvent.occurred_at.desc(), AccessEvent.id.desc())
        .limit(limit)
        .all()
    )

    results: list[AdminLogEntryOut] = []
    for event in events:
        actor: Optional[str] = None
        if event.source == "device":
            actor = event.node.node_code if event.node else "device"
        elif event.source == "server":
            actor = event.actor_user.email if event.actor_user else "server"

        resource_code = event.resource.code if event.resource else None

        results.append(
            AdminLogEntryOut(
                id=event.id,
                source=event.source,
                event_id=event.event_id,
                event_type=event.event_type,
                reason=event.reason,
                resource_code=resource_code,
                request_id=event.request_id,
                credential_id=event.credential_id,
                actor=actor,
                note=event.note,
                device_time=_format_utc_z(event.device_time),
                time_trusted=event.time_trusted,
                occurred_at=_format_utc_z(event.occurred_at) or "",
            )
        )

    return results


@router.get(
    "/nodes",
    response_model=list[AdminNodeOut],
    summary="Get access terminal nodes",
    description=(
        "Retrieve registered access terminal nodes, connectivity status, and sequence pointers. "
        "A node is considered online if last_seen_at is within ONLINE_WINDOW_S (45s). "
        "Requires admin privileges."
    ),
)
def get_admin_nodes(
    db: Session = Depends(get_db),
    _admin_user: AuthenticatedUser = Depends(require_admin),
) -> list[AdminNodeOut]:
    """
    GET /admin/nodes

    Returns status and connectivity of all registered terminal nodes.
    """
    sync_state = db.query(SyncState).filter(SyncState.id == 1).first()
    server_seq = sync_state.current_seq if sync_state else 0

    nodes = db.query(Node).order_by(Node.id.asc()).all()
    now_utc_time = datetime.now(timezone.utc)

    results: list[AdminNodeOut] = []
    for node in nodes:
        is_online = False
        if node.last_seen_at:
            ls = node.last_seen_at
            if ls.tzinfo is None:
                ls = ls.replace(tzinfo=timezone.utc)
            else:
                ls = ls.astimezone(timezone.utc)
            is_online = (now_utc_time - ls).total_seconds() <= _settings.ONLINE_WINDOW_S

        results.append(
            AdminNodeOut(
                id=node.id,
                node_code=node.node_code,
                firmware_version=node.firmware_version,
                last_seen_at=_format_utc_z(node.last_seen_at),
                online=is_online,
                time_state=node.time_state,
                last_acked_seq=node.last_acked_seq,
                server_seq=server_seq,
            )
        )

    return results
