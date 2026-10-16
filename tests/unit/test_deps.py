import time
from datetime import datetime, timedelta, timezone
import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.config import get_settings
from app.deps import AuthenticatedUser, require_admin, require_user
from app.errors import register_error_handlers

settings = get_settings()


def create_token(
    sub: str = "2",
    role: str = "user",
    email: str = "user@demo.local",
    expires_in_seconds: int = 3600,
    secret: str = settings.JWT_SECRET,
    algorithm: str = "HS256",
) -> str:
    """Helper creating test JWT tokens."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=expires_in_seconds)
    payload = {
        "sub": sub,
        "role": role,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


@pytest.fixture
def auth_client() -> TestClient:
    """Dedicated test FastAPI app with user and admin protected endpoints."""
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/user-only")
    def user_route(user: AuthenticatedUser = Depends(require_user)):
        return {"user_id": user.id, "role": user.role}

    @app.get("/admin-only")
    def admin_route(admin: AuthenticatedUser = Depends(require_admin)):
        return {"admin_id": admin.id, "role": admin.role}

    return TestClient(app)


def test_missing_token_returns_401(auth_client: TestClient):
    """Calling a protected route without Authorization header yields 401 unauthorized."""
    res = auth_client.get("/user-only")
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "unauthorized"
    assert "not provided" in data["error"]["message"].lower()


def test_malformed_token_returns_401(auth_client: TestClient):
    """Sending a random invalid string yields 401 unauthorized."""
    headers = {"Authorization": "Bearer not-a-valid-jwt-token"}
    res = auth_client.get("/user-only", headers=headers)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_expired_token_returns_401(auth_client: TestClient):
    """Sending an expired token yields 401 unauthorized."""
    expired_token = create_token(expires_in_seconds=-10)
    headers = {"Authorization": f"Bearer {expired_token}"}
    res = auth_client.get("/user-only", headers=headers)
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "unauthorized"
    assert "expired" in data["error"]["message"].lower()


def test_invalid_signature_returns_401(auth_client: TestClient):
    """Token signed with an incorrect secret yields 401 unauthorized."""
    wrong_token = create_token(secret="completely_wrong_secret_key_1234567890")
    headers = {"Authorization": f"Bearer {wrong_token}"}
    res = auth_client.get("/user-only", headers=headers)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_unsigned_none_algorithm_token_rejected(auth_client: TestClient):
    """Token with algorithm 'none' is rejected."""
    now = int(time.time())
    payload = {"sub": "2", "role": "user", "exp": now + 3600}
    # Unsigned token format: header.payload.
    unsigned_token = jwt.encode(payload, key="", algorithm="none")
    headers = {"Authorization": f"Bearer {unsigned_token}"}
    res = auth_client.get("/user-only", headers=headers)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_valid_user_token_accesses_user_route(auth_client: TestClient):
    """Valid user token succeeds on user route."""
    token = create_token(sub="5", role="user")
    headers = {"Authorization": f"Bearer {token}"}
    res = auth_client.get("/user-only", headers=headers)
    assert res.status_code == 200
    assert res.json() == {"user_id": 5, "role": "user"}


def test_user_token_denied_on_admin_route(auth_client: TestClient):
    """Standard user token on admin route yields 403 forbidden."""
    token = create_token(sub="5", role="user")
    headers = {"Authorization": f"Bearer {token}"}
    res = auth_client.get("/admin-only", headers=headers)
    assert res.status_code == 403
    data = res.json()
    assert data["error"]["code"] == "forbidden"
    assert "administrator" in data["error"]["message"].lower()


def test_admin_token_accesses_admin_route(auth_client: TestClient):
    """Admin token succeeds on admin route."""
    token = create_token(sub="1", role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    res = auth_client.get("/admin-only", headers=headers)
    assert res.status_code == 200
    assert res.json() == {"admin_id": 1, "role": "admin"}
