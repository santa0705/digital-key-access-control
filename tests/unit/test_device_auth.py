"""
tests/unit/test_device_auth.py

Focused unit tests for device authentication dependency:
- require_device
- validate_device_timestamp

Verifies:
1. Valid device authentication with X-Device-Key and fresh X-Device-Timestamp.
2. Missing or empty X-Device-Key returns 401 invalid_device_key.
3. Incorrect X-Device-Key returns 401 invalid_device_key via constant-time comparison.
4. Missing X-Device-Timestamp returns 401 invalid_device_timestamp.
5. Malformed X-Device-Timestamp (fractions, non-Z offsets, invalid dates) returns 422 validation_error.
6. Exact ±30-second boundaries are valid (|diff| == 30s).
7. Timestamps outside ±30-second window (|diff| >= 31s) return 401 invalid_device_timestamp.
8. Strict separation from ESP32 90s anchor (e.g. 45s-old request is rejected).
9. Deterministic controllable UTC clock testing without real hardware or network calls.
"""

from datetime import datetime, timedelta, timezone
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from app.config import get_settings
from app.deps import AuthenticatedDevice, require_device, validate_device_timestamp
from app.errors import AppError, UnauthorizedError, register_error_handlers
from app.services.time_utils import format_utc_timestamp

settings = get_settings()

# Fixed deterministic server reference time for controllable boundary tests
FIXED_SERVER_TIME = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test App for Dependency Isolation
# ---------------------------------------------------------------------------

@pytest.fixture
def device_test_client():
    """TestClient wired with a dedicated protected endpoint using require_device."""
    test_app = FastAPI()
    register_error_handlers(test_app)

    @test_app.post("/test-device-auth")
    def protected_device_endpoint(device: AuthenticatedDevice = Depends(require_device)):
        return {
            "status": "authenticated",
            "device_time": format_utc_timestamp(device.timestamp),
        }

    return TestClient(test_app)


# ---------------------------------------------------------------------------
# 1. Direct validate_device_timestamp Unit Tests (Deterministic Boundaries)
# ---------------------------------------------------------------------------


def test_validate_device_timestamp_exact_match():
    """Verify that a timestamp exactly matching server time is valid."""
    ts_str = format_utc_timestamp(FIXED_SERVER_TIME)
    validated_dt = validate_device_timestamp(ts_str, current_time=FIXED_SERVER_TIME)
    assert validated_dt == FIXED_SERVER_TIME


def test_validate_device_timestamp_exact_past_boundary():
    """Verify that a timestamp exactly 30 seconds in the past is valid (diff == -30s)."""
    past_30s = FIXED_SERVER_TIME - timedelta(seconds=30)
    ts_str = format_utc_timestamp(past_30s)
    validated_dt = validate_device_timestamp(ts_str, current_time=FIXED_SERVER_TIME)
    assert validated_dt == past_30s


def test_validate_device_timestamp_exact_future_boundary():
    """Verify that a timestamp exactly 30 seconds in the future is valid (diff == +30s)."""
    future_30s = FIXED_SERVER_TIME + timedelta(seconds=30)
    ts_str = format_utc_timestamp(future_30s)
    validated_dt = validate_device_timestamp(ts_str, current_time=FIXED_SERVER_TIME)
    assert validated_dt == future_30s


def test_validate_device_timestamp_outside_past_boundary_31s():
    """Verify that a timestamp 31 seconds in the past is rejected with 401 invalid_device_timestamp."""
    past_31s = FIXED_SERVER_TIME - timedelta(seconds=31)
    ts_str = format_utc_timestamp(past_31s)
    with pytest.raises(UnauthorizedError) as exc_info:
        validate_device_timestamp(ts_str, current_time=FIXED_SERVER_TIME)
    assert exc_info.value.code == "invalid_device_timestamp"
    assert exc_info.value.status_code == 401
    assert "exceeds maximum allowed" in exc_info.value.message


def test_validate_device_timestamp_outside_future_boundary_31s():
    """Verify that a timestamp 31 seconds in the future is rejected with 401 invalid_device_timestamp."""
    future_31s = FIXED_SERVER_TIME + timedelta(seconds=31)
    ts_str = format_utc_timestamp(future_31s)
    with pytest.raises(UnauthorizedError) as exc_info:
        validate_device_timestamp(ts_str, current_time=FIXED_SERVER_TIME)
    assert exc_info.value.code == "invalid_device_timestamp"
    assert exc_info.value.status_code == 401
    assert "exceeds maximum allowed" in exc_info.value.message


def test_validate_device_timestamp_significantly_skewed():
    """Verify that large skew (e.g. 5 minutes) is rejected with 401 invalid_device_timestamp."""
    old_ts = FIXED_SERVER_TIME - timedelta(minutes=5)
    ts_str = format_utc_timestamp(old_ts)
    with pytest.raises(UnauthorizedError) as exc_info:
        validate_device_timestamp(ts_str, current_time=FIXED_SERVER_TIME)
    assert exc_info.value.code == "invalid_device_timestamp"


def test_validate_device_timestamp_separate_from_esp32_90s_anchor():
    """
    Verify policy separation: an anchor that would be fresh under Tier 3 (e.g. 45s old)
    is strictly rejected for request authentication because request skew limit is ±30s.
    """
    past_45s = FIXED_SERVER_TIME - timedelta(seconds=45)
    ts_str = format_utc_timestamp(past_45s)
    with pytest.raises(UnauthorizedError) as exc_info:
        validate_device_timestamp(ts_str, current_time=FIXED_SERVER_TIME)
    assert exc_info.value.code == "invalid_device_timestamp"


def test_validate_device_timestamp_missing_or_empty():
    """Verify that None or empty timestamp string raises 401 invalid_device_timestamp."""
    with pytest.raises(UnauthorizedError) as exc_info_none:
        validate_device_timestamp(None, current_time=FIXED_SERVER_TIME)
    assert exc_info_none.value.code == "invalid_device_timestamp"

    with pytest.raises(UnauthorizedError) as exc_info_empty:
        validate_device_timestamp("   ", current_time=FIXED_SERVER_TIME)
    assert exc_info_empty.value.code == "invalid_device_timestamp"


def test_validate_device_timestamp_malformed_returns_422():
    """Verify that malformed timestamp formats raise 422 validation_error per contract §3.1."""
    # Fractional seconds
    with pytest.raises(AppError) as exc_frac:
        validate_device_timestamp("2026-10-12T12:00:00.123Z", current_time=FIXED_SERVER_TIME)
    assert exc_frac.value.code == "validation_error"
    assert exc_frac.value.status_code == 422

    # Non-Z offset
    with pytest.raises(AppError) as exc_offset:
        validate_device_timestamp("2026-10-12T12:00:00+00:00", current_time=FIXED_SERVER_TIME)
    assert exc_offset.value.code == "validation_error"
    assert exc_offset.value.status_code == 422

    # Lowercase z
    with pytest.raises(AppError) as exc_lower:
        validate_device_timestamp("2026-10-12T12:00:00z", current_time=FIXED_SERVER_TIME)
    assert exc_lower.value.code == "validation_error"
    assert exc_lower.value.status_code == 422

    # Gibberish
    with pytest.raises(AppError) as exc_gibberish:
        validate_device_timestamp("not-a-timestamp", current_time=FIXED_SERVER_TIME)
    assert exc_gibberish.value.code == "validation_error"
    assert exc_gibberish.value.status_code == 422

    # Invalid calendar date (month 13)
    with pytest.raises(AppError) as exc_bad_date:
        validate_device_timestamp("2026-13-12T12:00:00Z", current_time=FIXED_SERVER_TIME)
    assert exc_bad_date.value.code == "validation_error"
    assert exc_bad_date.value.status_code == 422


# ---------------------------------------------------------------------------
# 2. HTTP Endpoint Integration Tests via TestClient
# ---------------------------------------------------------------------------


def test_require_device_valid_authentication(device_test_client: TestClient, monkeypatch):
    """Verify valid request with correct device key and fresh timestamp succeeds."""
    monkeypatch.setattr("app.deps.now_utc", lambda: FIXED_SERVER_TIME)

    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": format_utc_timestamp(FIXED_SERVER_TIME),
    }
    res = device_test_client.post("/test-device-auth", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "authenticated"
    assert data["device_time"] == "2026-10-12T12:00:00Z"


def test_require_device_missing_key_returns_401(device_test_client: TestClient, monkeypatch):
    """Verify missing X-Device-Key returns 401 invalid_device_key."""
    monkeypatch.setattr("app.deps.now_utc", lambda: FIXED_SERVER_TIME)

    headers = {
        "X-Device-Timestamp": format_utc_timestamp(FIXED_SERVER_TIME),
    }
    res = device_test_client.post("/test-device-auth", headers=headers)
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "invalid_device_key"
    assert "Missing or invalid device key" in data["error"]["message"]


def test_require_device_empty_key_returns_401(device_test_client: TestClient, monkeypatch):
    """Verify empty X-Device-Key returns 401 invalid_device_key."""
    monkeypatch.setattr("app.deps.now_utc", lambda: FIXED_SERVER_TIME)

    headers = {
        "X-Device-Key": "",
        "X-Device-Timestamp": format_utc_timestamp(FIXED_SERVER_TIME),
    }
    res = device_test_client.post("/test-device-auth", headers=headers)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_device_key"


def test_require_device_incorrect_key_returns_401(device_test_client: TestClient, monkeypatch):
    """Verify incorrect X-Device-Key returns 401 invalid_device_key."""
    monkeypatch.setattr("app.deps.now_utc", lambda: FIXED_SERVER_TIME)

    headers = {
        "X-Device-Key": "wrong_device_key_abcdef123456",
        "X-Device-Timestamp": format_utc_timestamp(FIXED_SERVER_TIME),
    }
    res = device_test_client.post("/test-device-auth", headers=headers)
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "invalid_device_key"
    # Never leak the actual secret or sensitive config in the response
    assert settings.DEVICE_API_KEY not in res.text


def test_require_device_missing_timestamp_returns_401(device_test_client: TestClient):
    """Verify missing X-Device-Timestamp returns 401 invalid_device_timestamp."""
    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
    }
    res = device_test_client.post("/test-device-auth", headers=headers)
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "invalid_device_timestamp"


def test_require_device_malformed_timestamp_returns_422(device_test_client: TestClient):
    """Verify malformed X-Device-Timestamp returns 422 validation_error."""
    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": "invalid-timestamp-format",
    }
    res = device_test_client.post("/test-device-auth", headers=headers)
    assert res.status_code == 422
    data = res.json()
    assert data["error"]["code"] == "validation_error"


def test_require_device_exact_boundaries_via_client(device_test_client: TestClient, monkeypatch):
    """Verify HTTP client requests at exact -30s and +30s boundaries succeed."""
    monkeypatch.setattr("app.deps.now_utc", lambda: FIXED_SERVER_TIME)

    # -30s boundary
    past_30s = FIXED_SERVER_TIME - timedelta(seconds=30)
    headers_past = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": format_utc_timestamp(past_30s),
    }
    res_past = device_test_client.post("/test-device-auth", headers=headers_past)
    assert res_past.status_code == 200

    # +30s boundary
    future_30s = FIXED_SERVER_TIME + timedelta(seconds=30)
    headers_future = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": format_utc_timestamp(future_30s),
    }
    res_future = device_test_client.post("/test-device-auth", headers=headers_future)
    assert res_future.status_code == 200


def test_require_device_out_of_window_via_client(device_test_client: TestClient, monkeypatch):
    """Verify HTTP client requests at -31s and +31s fail with 401 invalid_device_timestamp."""
    monkeypatch.setattr("app.deps.now_utc", lambda: FIXED_SERVER_TIME)

    # -31s (outside window)
    past_31s = FIXED_SERVER_TIME - timedelta(seconds=31)
    headers_past = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": format_utc_timestamp(past_31s),
    }
    res_past = device_test_client.post("/test-device-auth", headers=headers_past)
    assert res_past.status_code == 401
    assert res_past.json()["error"]["code"] == "invalid_device_timestamp"

    # +31s (outside window)
    future_31s = FIXED_SERVER_TIME + timedelta(seconds=31)
    headers_future = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": format_utc_timestamp(future_31s),
    }
    res_future = device_test_client.post("/test-device-auth", headers=headers_future)
    assert res_future.status_code == 401
    assert res_future.json()["error"]["code"] == "invalid_device_timestamp"
