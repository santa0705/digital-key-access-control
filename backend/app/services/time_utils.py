import re
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings

# Strict ISO-8601 UTC regex: YYYY-MM-DDTHH:MM:SSZ (no fractions, literal uppercase Z)
STRICT_UTC_ISO_REGEX = re.compile(
    r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\dZ$"
)


def now_utc() -> datetime:
    """
    Returns the current timezone-aware UTC datetime.
    Microseconds are truncated to match second-level precision.
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


def format_utc_timestamp(dt: datetime) -> str:
    """
    Formats a datetime object to strict ISO-8601 UTC representation: 'YYYY-MM-DDTHH:MM:SSZ'.
    Requires a timezone-aware datetime (converts to UTC). Drops fractional seconds.
    """
    if not isinstance(dt, datetime):
        raise TypeError("Expected a datetime instance.")
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware (expected UTC).")

    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc_string() -> str:
    """
    Convenience helper returning the current UTC time formatted as 'YYYY-MM-DDTHH:MM:SSZ'.
    """
    return format_utc_timestamp(now_utc())


def parse_utc_timestamp(ts: str) -> datetime:
    """
    Strictly parses an ISO-8601 UTC timestamp string in the format 'YYYY-MM-DDTHH:MM:SSZ'.
    Rejects:
      - Fractional seconds (e.g. '.123')
      - Non-Z offsets (e.g. '+00:00', '-05:00', '+05:30')
      - Lowercase 'z'
      - Malformed or invalid calendar dates (e.g. month 13, day 32, leap year mismatches)
    Returns a timezone-aware datetime in UTC.
    """
    if not isinstance(ts, str):
        raise TypeError("Timestamp must be a string.")

    ts_stripped = ts.strip()
    if not STRICT_UTC_ISO_REGEX.match(ts_stripped):
        raise ValueError(
            f"Invalid timestamp format: '{ts}'. Must strictly match 'YYYY-MM-DDTHH:MM:SSZ' with uppercase Z and no fractional seconds."
        )

    try:
        dt = datetime.strptime(ts_stripped, "%Y-%m-%dT%H:%M:%SZ")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(f"Invalid calendar date or time in timestamp: '{ts}'.") from exc


def _coerce_to_utc_datetime(val: Any) -> datetime | None:
    """
    Internal helper that safely coerces string or datetime to timezone-aware UTC datetime.
    Returns None if missing, malformed, naive, or invalid (enabling fail-closed operations).
    """
    if val is None:
        return None
    if isinstance(val, str):
        try:
            return parse_utc_timestamp(val)
        except (ValueError, TypeError):
            return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return None
        return val.astimezone(timezone.utc)
    return None


def is_credential_window_active(
    valid_from: datetime | str,
    valid_until: datetime | str,
    check_time: datetime | str | None = None,
) -> bool:
    """
    Determines whether a credential window is active at check_time.
    Enforces the half-open interval: valid_from <= check_time < valid_until.
    Returns False fail-closed if:
      - check_time < valid_from
      - check_time >= valid_until
      - valid_until <= valid_from
      - any time parameter is missing, naive, or malformed
    """
    dt_from = _coerce_to_utc_datetime(valid_from)
    dt_until = _coerce_to_utc_datetime(valid_until)
    dt_check = now_utc() if check_time is None else _coerce_to_utc_datetime(check_time)

    if dt_from is None or dt_until is None or dt_check is None:
        return False

    if dt_until <= dt_from:
        return False

    return dt_from <= dt_check < dt_until


def is_time_anchor_fresh(
    anchor_time: datetime | str | None,
    current_time: datetime | str | None = None,
    max_age_seconds: int | None = None,
    max_future_skew_seconds: int = 5,
) -> bool:
    """
    Determines whether a server-time anchor is fresh and trustworthy.
    Rules:
      - Age is calculated as (current_time - anchor_time).
      - Fresh if: -max_future_skew_seconds <= age <= max_age_seconds.
      - Default max_age_seconds is controlled by Settings.TIME_ANCHOR_MAX_AGE_S (default 90s).
      - Returns False fail-closed if:
          - anchor_time is missing, naive, or malformed.
          - anchor is expired (age > max_age_seconds).
          - anchor is in the future beyond allowed skew (age < -max_future_skew_seconds).
    """
    dt_anchor = _coerce_to_utc_datetime(anchor_time)
    dt_current = now_utc() if current_time is None else _coerce_to_utc_datetime(current_time)

    if dt_anchor is None or dt_current is None:
        return False

    settings = get_settings()
    configured_max_age = getattr(settings, "TIME_ANCHOR_MAX_AGE_S", 90)
    effective_max_age = max_age_seconds if max_age_seconds is not None else configured_max_age

    if effective_max_age <= 0:
        return False

    age_seconds = (dt_current - dt_anchor).total_seconds()

    # Reject future-inconsistent timestamps beyond clock skew threshold
    if age_seconds < -max_future_skew_seconds:
        return False

    # Check expiration threshold
    if age_seconds > effective_max_age:
        return False

    return True
