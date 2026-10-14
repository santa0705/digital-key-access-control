from datetime import datetime, timezone
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Shared SQLAlchemy 2.0 Declarative Base for Digital Key Access Control.
    All models inherit from this base class.
    """
    pass


def utc_now() -> datetime:
    """Return current timestamp in UTC with timezone awareness."""
    return datetime.now(timezone.utc)
