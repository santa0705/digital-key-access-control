from datetime import datetime, timedelta, timezone
import pytest

from app.config import get_settings
from app.services.time_utils import (
    format_utc_timestamp,
    is_credential_window_active,
    is_time_anchor_fresh,
    now_utc,
    now_utc_string,
    parse_utc_timestamp,
)


def test_now_utc_format_and_properties():
    """Verify that now_utc returns timezone-aware UTC datetime without fractional seconds."""
    dt = now_utc()
    assert dt.tzinfo == timezone.utc
    assert dt.microsecond == 0

    ts_str = now_utc_string()
    assert ts_str.endswith("Z")
    assert len(ts_str) == 20  # YYYY-MM-DDTHH:MM:SSZ


def test_format_utc_timestamp():
    """Verify UTC formatting and rejection of naive datetimes."""
    # UTC datetime
    dt_utc = datetime(2026, 10, 12, 9, 15, 2, tzinfo=timezone.utc)
    assert format_utc_timestamp(dt_utc) == "2026-10-12T09:15:02Z"

    # Non-UTC timezone is converted to UTC
    offset_ist = timezone(timedelta(hours=5, minutes=30))
    dt_ist = datetime(2026, 10, 12, 14, 45, 2, tzinfo=offset_ist)
    assert format_utc_timestamp(dt_ist) == "2026-10-12T09:15:02Z"

    # Microseconds dropped in formatting
    dt_micro = datetime(2026, 10, 12, 9, 15, 2, 987654, tzinfo=timezone.utc)
    assert format_utc_timestamp(dt_micro) == "2026-10-12T09:15:02Z"

    # Naive datetime rejected
    dt_naive = datetime(2026, 10, 12, 9, 15, 2)
    with pytest.raises(ValueError, match="timezone-aware"):
        format_utc_timestamp(dt_naive)

    # Non-datetime type rejected
    with pytest.raises(TypeError):
        format_utc_timestamp("2026-10-12T09:15:02Z")  # type: ignore


def test_parse_utc_timestamp_valid():
    """Verify that valid ISO-8601 UTC strings parse into timezone-aware datetimes."""
    ts = "2026-10-12T09:15:02Z"
    dt = parse_utc_timestamp(ts)
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 12
    assert dt.hour == 9
    assert dt.minute == 15
    assert dt.second == 2
    assert dt.tzinfo == timezone.utc


def test_parse_utc_timestamp_rejects_fractions_and_offsets():
    """Verify strict rejection of fractional seconds and non-Z timezone offsets."""
    # Fractional seconds
    with pytest.raises(ValueError, match="Must strictly match"):
        parse_utc_timestamp("2026-10-12T09:15:02.123Z")

    # +00:00 offset instead of literal Z
    with pytest.raises(ValueError, match="Must strictly match"):
        parse_utc_timestamp("2026-10-12T09:15:02+00:00")

    # Non-UTC timezone offset
    with pytest.raises(ValueError, match="Must strictly match"):
        parse_utc_timestamp("2026-10-12T14:45:02+05:30")

    # Lowercase z
    with pytest.raises(ValueError, match="Must strictly match"):
        parse_utc_timestamp("2026-10-12T09:15:02z")

    # Missing timezone indicator
    with pytest.raises(ValueError, match="Must strictly match"):
        parse_utc_timestamp("2026-10-12T09:15:02")


def test_parse_utc_timestamp_rejects_malformed_dates():
    """Verify rejection of invalid dates and malformed strings."""
    # Invalid month 13
    with pytest.raises(ValueError):
        parse_utc_timestamp("2026-13-12T09:15:02Z")

    # Invalid day 32
    with pytest.raises(ValueError):
        parse_utc_timestamp("2026-10-32T09:15:02Z")

    # Invalid leap year day
    with pytest.raises(ValueError, match="Invalid calendar date"):
        parse_utc_timestamp("2026-02-29T09:15:02Z")

    # Gibberish string
    with pytest.raises(ValueError):
        parse_utc_timestamp("not-a-timestamp")

    # Non-string input
    with pytest.raises(TypeError):
        parse_utc_timestamp(123456789)  # type: ignore


def test_credential_validity_boundaries():
    """Verify half-open interval valid_from <= now < valid_until exact boundary checks."""
    v_from = "2026-10-12T09:00:00Z"
    v_until = "2026-10-12T10:00:00Z"

    # Exact start boundary: valid_from <= check_time (MUST BE TRUE)
    assert is_credential_window_active(v_from, v_until, check_time="2026-10-12T09:00:00Z") is True

    # Inside window
    assert is_credential_window_active(v_from, v_until, check_time="2026-10-12T09:30:00Z") is True

    # One second before valid_until
    assert is_credential_window_active(v_from, v_until, check_time="2026-10-12T09:59:59Z") is True

    # Exact end boundary: check_time < valid_until (MUST BE FALSE)
    assert is_credential_window_active(v_from, v_until, check_time="2026-10-12T10:00:00Z") is False

    # After valid_until
    assert is_credential_window_active(v_from, v_until, check_time="2026-10-12T10:00:01Z") is False

    # Before valid_from
    assert is_credential_window_active(v_from, v_until, check_time="2026-10-12T08:59:59Z") is False


def test_credential_validity_datetime_objects():
    """Verify credential validity with datetime object parameters."""
    t_from = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)
    t_until = datetime(2026, 10, 12, 10, 0, 0, tzinfo=timezone.utc)
    t_inside = datetime(2026, 10, 12, 9, 30, 0, tzinfo=timezone.utc)

    assert is_credential_window_active(t_from, t_until, check_time=t_inside) is True


def test_credential_validity_fail_closed_on_malformed_data():
    """Verify fail-closed return False on malformed, reversed, or invalid intervals."""
    v_from = "2026-10-12T09:00:00Z"
    v_until = "2026-10-12T10:00:00Z"

    # Reversed interval (until <= from)
    assert is_credential_window_active(v_until, v_from, check_time="2026-10-12T09:30:00Z") is False

    # Equal start and end
    assert is_credential_window_active(v_from, v_from, check_time="2026-10-12T09:00:00Z") is False

    # Malformed timestamp string
    assert is_credential_window_active("malformed-time", v_until) is False
    assert is_credential_window_active(v_from, "malformed-time") is False

    # Naive datetime passed
    naive_dt = datetime(2026, 10, 12, 9, 0, 0)
    assert is_credential_window_active(naive_dt, v_until) is False


def test_time_anchor_freshness_default_90s():
    """Verify anchor freshness checking with default TIME_ANCHOR_MAX_AGE_S = 90s."""
    now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)

    # Fresh anchor: 30 seconds old
    anchor_fresh = now - timedelta(seconds=30)
    assert is_time_anchor_fresh(anchor_fresh, current_time=now) is True

    # Exact boundary: 90 seconds old
    anchor_boundary = now - timedelta(seconds=90)
    assert is_time_anchor_fresh(anchor_boundary, current_time=now) is True

    # Expired anchor: 91 seconds old (fails closed)
    anchor_stale = now - timedelta(seconds=91)
    assert is_time_anchor_fresh(anchor_stale, current_time=now) is False

    # Significantly expired: 300 seconds old
    anchor_expired = now - timedelta(seconds=300)
    assert is_time_anchor_fresh(anchor_expired, current_time=now) is False


def test_time_anchor_freshness_string_inputs_and_custom_max_age():
    """Verify string timestamps and custom max_age_seconds parameter."""
    now_str = "2026-10-12T12:00:00Z"

    # 45-second-old anchor with custom max_age of 60s
    anchor_str = "2026-10-12T11:59:15Z"
    assert is_time_anchor_fresh(anchor_str, current_time=now_str, max_age_seconds=60) is True

    # 65-second-old anchor with custom max_age of 60s
    anchor_older = "2026-10-12T11:58:55Z"
    assert is_time_anchor_fresh(anchor_older, current_time=now_str, max_age_seconds=60) is False


def test_time_anchor_future_and_malformed_fail_closed():
    """Verify fail-closed behavior for future anchors and malformed data."""
    now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)

    # Tolerable future clock skew (3 seconds ahead within 5s tolerance)
    anchor_slight_future = now + timedelta(seconds=3)
    assert is_time_anchor_fresh(anchor_slight_future, current_time=now, max_future_skew_seconds=5) is True

    # Future-inconsistent anchor (10 seconds ahead beyond 5s tolerance) -> fails closed
    anchor_excessive_future = now + timedelta(seconds=10)
    assert is_time_anchor_fresh(anchor_excessive_future, current_time=now, max_future_skew_seconds=5) is False

    # Missing anchor (None) -> fails closed
    assert is_time_anchor_fresh(None, current_time=now) is False

    # Malformed anchor string -> fails closed
    assert is_time_anchor_fresh("invalid-anchor-string", current_time=now) is False

    # Naive anchor datetime -> fails closed
    naive_anchor = datetime(2026, 10, 12, 11, 59, 30)
    assert is_time_anchor_fresh(naive_anchor, current_time=now) is False
