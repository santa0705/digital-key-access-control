from datetime import datetime, timedelta, timezone
import jwt
import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.deps import AuthenticatedUser, decode_access_token
from app.schemas.auth import LoginRequest, LoginResponse, UserSummary

settings = get_settings()


def test_login_request_valid():
    """Verify that a valid login payload is parsed and email is normalized."""
    req = LoginRequest(email=" USER@demo.local ", password="secret-password")
    assert req.email == "user@demo.local"
    assert req.password == "secret-password"


def test_login_request_invalid_email():
    """Verify that malformed email addresses raise validation error."""
    with pytest.raises(ValidationError) as exc:
        LoginRequest(email="not-an-email", password="secret-password")
    assert "Invalid email format" in str(exc.value)


def test_login_request_empty_password():
    """Verify that empty password strings are rejected."""
    with pytest.raises(ValidationError):
        LoginRequest(email="user@demo.local", password="")


def test_user_summary_roles():
    """Verify that UserSummary accepts only 'user' or 'admin' roles."""
    user = UserSummary(id=2, email="user@demo.local", full_name="Demo User", role="user")
    assert user.id == 2
    assert user.role == "user"

    admin = UserSummary(id=1, email="admin@demo.local", full_name="Admin User", role="admin")
    assert admin.role == "admin"

    with pytest.raises(ValidationError):
        UserSummary(id=3, email="guest@demo.local", full_name="Guest", role="superadmin")


def test_login_response_serialization():
    """Verify that LoginResponse structure strictly matches the contract JSON shape."""
    user = UserSummary(id=2, email="user@demo.local", full_name="Demo User", role="user")
    resp = LoginResponse(
        access_token="test.jwt.token",
        token_type="bearer",
        expires_in=28800,
        user=user,
    )
    data = resp.model_dump()
    assert data == {
        "access_token": "test.jwt.token",
        "token_type": "bearer",
        "expires_in": 28800,
        "user": {
            "id": 2,
            "email": "user@demo.local",
            "full_name": "Demo User",
            "role": "user",
        },
    }


def test_login_token_claims_compatibility():
    """Verify that token claims issued by the planned login flow work with decode_access_token and AuthenticatedUser."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=28800)

    # Token payload issued by login
    claims = {
        "sub": "2",
        "role": "user",
        "email": "user@demo.local",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")

    # Decode and validate using backend dependency helper
    decoded = decode_access_token(token)
    assert decoded["sub"] == "2"
    assert decoded["role"] == "user"
    assert decoded["email"] == "user@demo.local"

    # Verify compatibility with AuthenticatedUser
    auth_user = AuthenticatedUser(
        id=int(decoded["sub"]),
        role=decoded["role"],
        email=decoded["email"],
    )
    assert auth_user.id == 2
    assert auth_user.role == "user"
    assert auth_user.email == "user@demo.local"
