from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.access_events import AccessEvent
    from app.models.credentials import Credential
    from app.models.resources import Resource
    from app.models.users import User


class RequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class AccessRequest(Base):
    """
    Access requests submitted by users for physical/simulated resources during bounded UTC time windows.
    Admins approve (spawning a Credential) or reject requests.
    """
    __tablename__ = "access_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'revoked')",
            name="ck_access_requests_status",
        ),
        CheckConstraint("end_at > start_at", name="ck_access_requests_end_after_start"),
        CheckConstraint(
            "end_at - start_at <= INTERVAL '24 hours'",
            name="ck_access_requests_max_24h",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(start=1, always=False),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    resource_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("resources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    purpose: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=RequestStatus.PENDING.value,
        server_default=text("'pending'"),
        index=True,
    )
    decided_by: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    decision_note: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="access_requests",
        foreign_keys=[user_id],
    )
    resource: Mapped["Resource"] = relationship(
        "Resource",
        back_populates="access_requests",
        foreign_keys=[resource_id],
    )
    decided_by_user: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="decided_requests",
        foreign_keys=[decided_by],
    )
    credential: Mapped[Optional["Credential"]] = relationship(
        "Credential",
        back_populates="access_request",
        uselist=False,
    )
    access_events: Mapped[list["AccessEvent"]] = relationship(
        "AccessEvent",
        back_populates="access_request",
        foreign_keys="AccessEvent.request_id",
    )

    def __repr__(self) -> str:
        return f"<AccessRequest id={self.id} user_id={self.user_id} resource_id={self.resource_id} status='{self.status}'>"
