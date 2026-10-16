"""
backend/app/services/sequence.py -- Monotonic change sequence allocation service.

Provides allocate_next_change_seq() helper for atomic, gap-free change sequence numbers.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.sync_state import SyncState


def allocate_next_change_seq(db: Session) -> int:
    """
    Allocates the next atomic, monotonic change sequence number.

    On PostgreSQL, executes the stored procedure next_change_seq().
    On SQLite and test environments where next_change_seq() is not defined,
    atomically increments and returns sync_state.current_seq.
    """
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        result = db.execute(text("SELECT next_change_seq()")).scalar()
        if result is None:
            raise RuntimeError("next_change_seq() returned NULL")
        return int(result)

    # Fallback for SQLite and test environments
    state = db.query(SyncState).filter(SyncState.id == 1).first()
    if state is None:
        raise RuntimeError("sync_state singleton row missing (id=1)")
    state.current_seq += 1
    db.flush()
    return int(state.current_seq)
