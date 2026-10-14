from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Identity, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.access_events import AccessEvent
    from app.models.credentials import Credential


class NodeTimeState(StrEnum):
    UNTRUSTED = "untrusted"
    RTC_VALIDATED = "rtc_validated"
    SERVER_ANCHORED = "server_anchored"


class Node(Base):
    """
    Nodes table tracking physical access terminal devices (ESP32 controllers).
    Default prototype device code is 'node-01'.
    """
    __tablename__ = "nodes"
    __table_args__ = (
        CheckConstraint(
            "time_state IS NULL OR time_state IN ('untrusted', 'rtc_validated', 'server_anchored')",
            name="ck_nodes_time_state",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(start=1, always=False),
        primary_key=True,
    )
    node_code: Mapped[str] = mapped_column(
        Text,
        unique=True,
        nullable=False,
        index=True,
    )
    firmware_version: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    time_state: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    last_acked_seq: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    consumed_credentials: Mapped[list["Credential"]] = relationship(
        "Credential",
        back_populates="consumed_node",
        foreign_keys="Credential.consumed_node_id",
    )
    access_events: Mapped[list["AccessEvent"]] = relationship(
        "AccessEvent",
        back_populates="node",
        foreign_keys="AccessEvent.node_id",
    )

    def __repr__(self) -> str:
        return f"<Node id={self.id} node_code='{self.node_code}' time_state='{self.time_state}'>"
