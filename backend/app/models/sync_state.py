from sqlalchemy import BigInteger, CheckConstraint, SmallInteger, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SyncState(Base):
    """
    Singleton table (id = 1) maintaining global synchronization epoch and monotonic change sequence.
    Replaces free-running sequences to guarantee strictly gap-free, atomic sequence allocation.
    """
    __tablename__ = "sync_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_sync_state_single_row"),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
        default=1,
    )
    epoch: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("gen_random_uuid()::text"),
    )
    current_seq: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    def __repr__(self) -> str:
        return f"<SyncState id={self.id} epoch='{self.epoch}' current_seq={self.current_seq}>"
