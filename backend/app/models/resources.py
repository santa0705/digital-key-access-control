from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Identity, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.access_events import AccessEvent
    from app.models.access_requests import AccessRequest
    from app.models.credentials import Credential


class ResourceKind(StrEnum):
    PHYSICAL = "physical"
    SIMULATED = "simulated"


class Resource(Base):
    """
    Resources table representing physical or simulated access points (e.g., Locker A, Locker B).
    In the prototype: Resource A is physical (servo-actuated), Resource B is simulated (LED/log only).
    """
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint("code IN ('A', 'B')", name="ck_resources_code"),
        CheckConstraint("kind IN ('physical', 'simulated')", name="ck_resources_kind"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(start=1, always=False),
        primary_key=True,
    )
    code: Mapped[str] = mapped_column(
        Text,
        unique=True,
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        Text,
        nullable=False,
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
        back_populates="resource",
        foreign_keys="AccessRequest.resource_id",
    )
    credentials: Mapped[list["Credential"]] = relationship(
        "Credential",
        back_populates="resource",
        foreign_keys="Credential.resource_id",
    )
    access_events: Mapped[list["AccessEvent"]] = relationship(
        "AccessEvent",
        back_populates="resource",
        foreign_keys="AccessEvent.resource_id",
    )

    def __repr__(self) -> str:
        return f"<Resource id={self.id} code='{self.code}' name='{self.name}' kind='{self.kind}'>"
