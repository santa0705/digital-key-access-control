"""
routers/admin.py -- Administrative read-only endpoints (Person A).

Implements:
  - GET /admin/logs  (Contract 5.3)
  - GET /admin/nodes (Contract 5.3)

Security:
  - Requires Bearer token with 'admin' role. Non-admin users receive 403 forbidden.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db import get_db
from app.deps import require_admin
from app.models.access_events import AccessEvent
from app.models.nodes import Node
from app.models.sync_state import SyncState
from app.models.users import User
from app.schemas.admin import AdminLogEntryOut, AdminNodeOut

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
    _admin_user: User = Depends(require_admin),
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
    _admin_user: User = Depends(require_admin),
) -> list[AdminNodeOut]:
    """
    GET /admin/nodes

    Returns status and connectivity of all registered terminal nodes.
    """
    sync_state = db.query(SyncState).filter(SyncState.id == 1).first()
    server_seq = sync_state.current_seq if sync_state else 0

    nodes = db.query(Node).order_by(Node.id.asc()).all()
    now_utc = datetime.now(timezone.utc)

    results: list[AdminNodeOut] = []
    for node in nodes:
        is_online = False
        if node.last_seen_at:
            ls = node.last_seen_at
            if ls.tzinfo is None:
                ls = ls.replace(tzinfo=timezone.utc)
            else:
                ls = ls.astimezone(timezone.utc)
            is_online = (now_utc - ls).total_seconds() <= _settings.ONLINE_WINDOW_S

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
