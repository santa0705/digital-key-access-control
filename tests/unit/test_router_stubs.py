"""
tests/unit/test_router_stubs.py

Focused unit tests for Person B contract router stubs:
- POST /auth/login
- /admin/* endpoints (access-requests, approve, reject, revoke, logs, nodes)
- POST /device/v1/sync

Verifies route registration, authentication gating, error envelopes, and placeholder behavior.
Never returns fake successes. Independent of database models and real hardware.
"""

import time
from fastapi.testclient import TestClient
import jwt
import pytest

from app.config import get_settings
from app.main import app

client = TestClient(app)
settings = get_settings()


def create_test_token(user_id: int = 1, role: str = "user", email: str = "test@demo.local") -> str:
    """Helper creating signed test JWT for dependency testing."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": role,
        "email": email,
        "exp": now + 3600,
        "iat": now,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


# ---------------------------------------------------------------------------
# Auth Router Tests (POST /auth/login)
# ---------------------------------------------------------------------------


def test_login_invalid_payload_returns_422():
    """Verify that malformed or invalid login payloads fail with contract 422 validation_error."""
    # Invalid email format
    res_bad_email = client.post("/auth/login", json={"email": "not-an-email", "password": "secret"})
    assert res_bad_email.status_code == 422
    assert res_bad_email.json()["error"]["code"] == "validation_error"

    # Empty password
    res_empty_pw = client.post("/auth/login", json={"email": "user@demo.local", "password": ""})
    assert res_empty_pw.status_code == 422
    assert res_empty_pw.json()["error"]["code"] == "validation_error"

    # Missing fields
    res_missing = client.post("/auth/login", json={})
    assert res_missing.status_code == 422
    assert res_missing.json()["error"]["code"] == "validation_error"


def test_login_invalid_credentials_returns_401():
    """Verify that incorrect credentials return contract 401 invalid_credentials."""
    payload = {"email": "admin@demo.local", "password": "wrong-password-123"}
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 401
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "invalid_credentials"


def test_login_valid_credentials_returns_token():
    """Verify that valid demo credentials return 200 OK with session token."""
    from unittest.mock import MagicMock
    import bcrypt
    from app.db import get_db
    from app.models.users import User

    hashed = bcrypt.hashpw(b"demo-password", bcrypt.gensalt()).decode("utf-8")
    mock_user = User(
        id=1,
        email="admin@demo.local",
        full_name="Demo Admin",
        password_hash=hashed,
        role="admin",
        is_active=True,
    )

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        payload = {"email": "admin@demo.local", "password": "demo-password"}
        res = client.post("/auth/login", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "admin@demo.local"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Admin Router Tests (/admin/*)
# ---------------------------------------------------------------------------

ADMIN_ENDPOINTS = [
    ("GET", "/admin/access-requests"),
    ("POST", "/admin/access-requests/1/approve"),
    ("POST", "/admin/access-requests/1/reject"),
    ("POST", "/admin/credentials/1/revoke"),
    ("GET", "/admin/logs"),
    ("GET", "/admin/nodes"),
]


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_routes_require_authentication(method: str, path: str):
    """Verify that all admin endpoints reject unauthenticated requests with 401 unauthorized."""
    res = client.request(method, path)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_routes_reject_non_admin_users(method: str, path: str):
    """Verify that all admin endpoints reject non-admin users with 403 forbidden."""
    user_token = create_test_token(role="user")
    headers = {"Authorization": f"Bearer {user_token}"}
    res = client.request(method, path, headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden"


def test_admin_read_routes_with_admin_token_succeed():
    """Verify that authenticated admin read endpoints return 200 OK."""
    admin_token = create_test_token(role="admin")
    headers = {"Authorization": f"Bearer {admin_token}"}
    for path in ["/admin/access-requests", "/admin/logs", "/admin/nodes"]:
        res = client.get(path, headers=headers)
        assert res.status_code == 200
        assert isinstance(res.json(), list)


def test_admin_mutation_routes_with_admin_token_reach_domain_logic():
    """
    Verify that authenticated admin mutation endpoints reach live domain logic
    (returning 404 not_found for non-existent entities) rather than 501 placeholders.
    """
    admin_token = create_test_token(role="admin")
    headers = {"Authorization": f"Bearer {admin_token}"}

    res_approve = client.post(
        "/admin/access-requests/99999/approve",
        json={"note": "Test approve", "replace_existing": False},
        headers=headers,
    )
    assert res_approve.status_code == 404
    assert res_approve.json()["error"]["code"] == "not_found"

    res_reject = client.post(
        "/admin/access-requests/99999/reject",
        json={"note": "Test reject"},
        headers=headers,
    )
    assert res_reject.status_code == 404
    assert res_reject.json()["error"]["code"] == "not_found"

    res_revoke = client.post(
        "/admin/credentials/99999/revoke",
        json={"note": "Test revoke"},
        headers=headers,
    )
    assert res_revoke.status_code == 404
    assert res_revoke.json()["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# Device Router Tests (POST /device/v1/sync)
# ---------------------------------------------------------------------------


def test_device_sync_requires_authentication():
    """Verify that POST /device/v1/sync without device headers returns 401 invalid_device_key."""
    res = client.post("/device/v1/sync", json={})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_device_key"


def test_device_sync_invalid_payload_returns_422():
    """
    Verify that POST /device/v1/sync with valid device authentication headers
    but invalid/empty payload returns 422 validation_error per contract §3.3.
    """
    from app.services.time_utils import now_utc_string

    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": now_utc_string(),
    }
    res = client.post("/device/v1/sync", json={}, headers=headers)
    assert res.status_code == 422
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "validation_error"
