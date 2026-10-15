from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.access_requests import AccessRequest
    from app.models.credentials import Credential
    from app.models.nodes import Node
    from app.models.resources import Resource
    from app.models.users import User


class EventSource(StrEnum):
    DEVICE = "device"
    SERVER = "server"


class EventType(StrEnum):
    # Device telemetry events
    PIN_REJECTED = "pin_rejected"
    CREDENTIAL_ACCEPTED = "credential_accepted"
    UNLOCK_COMMAND_ISSUED = "unlock_command_issued"
    LOCKOUT_STARTED = "lockout_started"

    # Server audit events
    REQUEST_CREATED = "request_created"
    REQUEST_APPROVED = "request_approved"
    REQUEST_REJECTED = "request_rejected"
    CREDENTIAL_ISSUED = "credential_issued"
    CREDENTIAL_REPLACED = "credential_replaced"
    CREDENTIAL_REVOKED = "credential_revoked"
    CREDENTIAL_EXPIRED = "credential_expired"
    CREDENTIAL_CONSUMED = "credential_consumed"
    PIN_REVEALED = "pin_revealed"


class EventReason(StrEnum):
    WRONG_PIN = "wrong_pin"
    WRONG_RESOURCE = "wrong_resource"
    EXPIRED = "expired"
    NOT_YET_VALID = "not_yet_valid"
    CONSUMED = "consumed"
    REVOKED = "revoked"
    TIME_UNTRUSTED = "time_untrusted"


class AccessEvent(Base):
    """
    Unified telemetry and audit log table for both device access events and server operations.
    Enforces check constraints on event types, sources, reasons, and device time trust.
    Indexed descending by occurred_at for rapid newest-first administrative querying.
    """
    __tablename__ = "access_events"
    __table_args__ = (
        CheckConstraint(
            "source IN ('device', 'server')",
            name="ck_access_events_source",
        ),
        CheckConstraint(
            "event_type IN ("
            "'pin_rejected', 'credential_accepted', 'unlock_command_issued', 'lockout_started', "
            "'request_created', 'request_approved', 'request_rejected', "
            "'credential_issued', 'credential_replaced', 'credential_revoked', "
            "'credential_expired', 'credential_consumed', 'pin_revealed')",
            name="ck_access_events_event_type",
        ),
        CheckConstraint(
            "reason IS NULL OR reason IN ("
            "'wrong_pin', 'wrong_resource', 'expired', 'not_yet_valid', "
            "'consumed', 'revoked', 'time_untrusted')",
            name="ck_access_events_reason",
        ),
        CheckConstraint(
            "source != 'device' OR time_trusted IS NOT NULL",
            name="ck_access_events_device_time_trusted",
        ),
        Index("ix_access_events_occurred_at_desc", text("occurred_at DESC")),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(start=1, always=False),
        primary_key=True,
    )
    event_id: Mapped[str] = mapped_column(
        Text,
        unique=True,
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    node_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("access_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    resource_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("resources.id", ondelete="SET NULL"),
        nullable=True,
    )
    credential_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("credentials.id", ondelete="SET NULL"),
        nullable=True,
    )
    note: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    device_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    time_trusted: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    node: Mapped[Optional["Node"]] = relationship(
        "Node",
        back_populates="access_events",
        foreign_keys=[node_id],
    )
    actor_user: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="access_events",
        foreign_keys=[actor_user_id],
    )
    access_request: Mapped[Optional["AccessRequest"]] = relationship(
        "AccessRequest",
        back_populates="access_events",
        foreign_keys=[request_id],
    )
    resource: Mapped[Optional["Resource"]] = relationship(
        "Resource",
        back_populates="access_events",
        foreign_keys=[resource_id],
    )
    credential: Mapped[Optional["Credential"]] = relationship(
        "Credential",
        back_populates="access_events",
        foreign_keys=[credential_id],
    )

    def __repr__(self) -> str:
        return f"<AccessEvent id={self.id} event_id='{self.event_id}' event_type='{self.event_type}' source='{self.source}'>"
