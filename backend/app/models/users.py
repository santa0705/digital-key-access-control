from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Identity, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.access_events import AccessEvent
    from app.models.access_requests import AccessRequest
    from app.models.credentials import Credential


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class User(Base):
    """
    Users table storing credentials and roles for authentication and authorization.
    Seeded users match contract examples: admin@demo.local (admin) and user@demo.local (user).
    """
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(start=1, always=False),
        primary_key=True,
    )
    email: Mapped[str] = mapped_column(
        Text,
        unique=True,
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=UserRole.USER.value,
        server_default=text("'user'"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    access_requests: Mapped[list["AccessRequest"]] = relationship(
        "AccessRequest",
        back_populates="user",
        foreign_keys="AccessRequest.user_id",
    )
    decided_requests: Mapped[list["AccessRequest"]] = relationship(
        "AccessRequest",
        back_populates="decided_by_user",
        foreign_keys="AccessRequest.decided_by",
    )
    revoked_credentials: Mapped[list["Credential"]] = relationship(
        "Credential",
        back_populates="revoked_by_user",
        foreign_keys="Credential.revoked_by",
    )
    access_events: Mapped[list["AccessEvent"]] = relationship(
        "AccessEvent",
        back_populates="actor_user",
        foreign_keys="AccessEvent.actor_user_id",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email='{self.email}' role='{self.role}'>"
