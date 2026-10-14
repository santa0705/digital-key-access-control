from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.access_events import AccessEvent
    from app.models.access_requests import AccessRequest
    from app.models.nodes import Node
    from app.models.resources import Resource
    from app.models.users import User


class CredentialStatus(StrEnum):
    ACTIVE = "active"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    REVOKED = "revoked"


class RevokeReason(StrEnum):
    ADMIN = "admin"
    SUPERSEDED = "superseded"


class Credential(Base):
    """
    Credentials table storing active and terminal PIN credentials.
    Enforces Rule R1: At most one credential per resource may be active (partial unique index).
    Stores keyed HMAC-SHA256 digest for verification and Fernet ciphertext for repeatable owner reveal.
    Plaintext PIN is NEVER persisted.
    """
    __tablename__ = "credentials"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'consumed', 'expired', 'revoked')",
            name="ck_credentials_status",
        ),
        CheckConstraint(
            "(status = 'revoked' AND revoke_reason IS NOT NULL AND revoke_reason IN ('admin', 'superseded')) OR (status != 'revoked' AND revoke_reason IS NULL)",
            name="ck_credentials_revoke_reason",
        ),
        CheckConstraint("valid_until > valid_from", name="ck_credentials_valid_window"),
        UniqueConstraint("resource_id", "pin_hmac", name="uq_credentials_resource_pin_hmac"),
        # Rule R1: Partial unique index enforcing at most one active credential per resource
        Index(
            "uq_credentials_resource_active",
            "resource_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(start=1, always=False),
        primary_key=True,
    )
    request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("access_requests.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    resource_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("resources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pin_hmac: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    pin_encrypted: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    valid_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=CredentialStatus.ACTIVE.value,
        server_default=text("'active'"),
        index=True,
    )
    change_seq: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
        index=True,
    )
    revoke_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    consumed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    consumed_node_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_by: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    access_request: Mapped["AccessRequest"] = relationship(
        "AccessRequest",
        back_populates="credential",
        foreign_keys=[request_id],
    )
    resource: Mapped["Resource"] = relationship(
        "Resource",
        back_populates="credentials",
        foreign_keys=[resource_id],
    )
    consumed_node: Mapped[Optional["Node"]] = relationship(
        "Node",
        back_populates="consumed_credentials",
        foreign_keys=[consumed_node_id],
    )
    revoked_by_user: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="revoked_credentials",
        foreign_keys=[revoked_by],
    )
    access_events: Mapped[list["AccessEvent"]] = relationship(
        "AccessEvent",
        back_populates="credential",
        foreign_keys="AccessEvent.credential_id",
    )

    def __repr__(self) -> str:
        return f"<Credential id={self.id} resource_id={self.resource_id} status='{self.status}' change_seq={self.change_seq}>"
