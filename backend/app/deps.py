"""
deps.py -- FastAPI dependencies shared across Person A and Person B routers.

Provides:
  - decode_access_token: verifies and decodes JWT tokens.
  - require_user: validates Bearer JWT token claims and returns AuthenticatedUser.
  - require_admin: enforces 'admin' role on authenticated user.
  - get_current_user: retrieves the full User ORM row from database.
  - get_db: database session generator.
  - validate_device_timestamp: enforces ±30-second clock skew on access terminals.
  - require_device: validates terminal headers (X-Device-Key, X-Device-Timestamp).
"""
from __future__ import annotations

from datetime import datetime
import hmac
from typing import Annotated, Optional
import jwt
from fastapi import Depends, Header, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import AppError, ForbiddenError, UnauthorizedError
from app.models.users import User
from app.services.time_utils import now_utc, parse_utc_timestamp

_settings = get_settings()
_bearer_scheme = HTTPBearer(auto_error=False)

JWT_ALGORITHM = "HS256"
DEVICE_TIMESTAMP_MAX_SKEW_S: int = 30


# ---------------------------------------------------------------------------
# User Models & Authentication Dependencies
# ---------------------------------------------------------------------------

class AuthenticatedUser(BaseModel):
    """
    Representation of an authenticated user derived from verified JWT claims.
    Provides .id, .role, and .email.
    """
    id: int
    role: str
    email: Optional[str] = None

    model_config = ConfigDict(frozen=True)


def decode_access_token(token: str) -> dict:
    """
    Decodes and validates a JWT token using settings.JWT_SECRET and HS256.
    Enforces signature, expiration, and rejects unsigned tokens ("none" algorithm).
    Maps JWT exceptions to UnauthorizedError without leaking tracebacks.
    """
    try:
        payload = jwt.decode(
            token,
            _settings.JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError(message="Token has expired.", code="unauthorized") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError(message="Invalid token.", code="unauthorized") from exc


async def require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> AuthenticatedUser:
    """
    FastAPI dependency extracting Bearer token and verifying user claims.
    Returns AuthenticatedUser with .id and .role.
    """
    if credentials is None or not credentials.credentials or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError(
            message="Authentication credentials were not provided.",
            code="unauthorized",
        )

    token = credentials.credentials
    payload = decode_access_token(token)

    sub = payload.get("sub")
    role = payload.get("role", "user")
    email = payload.get("email")

    if not sub:
        raise UnauthorizedError(message="Token subject is missing.", code="unauthorized")

    try:
        user_id = int(sub)
    except (ValueError, TypeError) as exc:
        raise UnauthorizedError(message="Invalid subject identifier.", code="unauthorized") from exc

    return AuthenticatedUser(id=user_id, role=role, email=email)


async def require_admin(
    current_user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> AuthenticatedUser:
    """
    FastAPI dependency requiring that current_user has role == 'admin'.
    Raises 403 forbidden if user has a non-admin role.
    """
    if current_user.role != "admin":
        raise ForbiddenError(
            message="Administrator privileges required.",
            code="forbidden",
        )
    return current_user


def get_current_user(
    auth_user: Annotated[AuthenticatedUser, Depends(require_user)],
    db: Session = Depends(get_db),
) -> User:
    """
    Retrieve the authenticated User ORM row from the database.
    Raises UnauthorizedError if user does not exist or is inactive.
    """
    user = db.get(User, auth_user.id)
    if user is None or not user.is_active:
        raise UnauthorizedError("User not found or inactive.", code="unauthorized")

    return user


# ---------------------------------------------------------------------------
# Device Authentication Layer (docs/api-contract.md §5.4 & §3.3)
# ---------------------------------------------------------------------------

class AuthenticatedDevice(BaseModel):
    """
    Representation of an authenticated access terminal derived from
    verified X-Device-Key and X-Device-Timestamp headers.
    """
    timestamp: datetime

    model_config = ConfigDict(frozen=True)


def validate_device_timestamp(
    timestamp_str: str | None,
    current_time: datetime | None = None,
    max_skew_seconds: int = DEVICE_TIMESTAMP_MAX_SKEW_S,
) -> datetime:
    """
    Validates X-Device-Timestamp header against current UTC server time.
    Enforces ±30s maximum clock skew per docs/api-contract.md §5.4.
    Rules:
      - Missing or empty header -> 401 invalid_device_timestamp
      - Malformed format -> 422 validation_error (per contract §3.1)
      - Clock skew |timestamp - server_time| > max_skew_seconds -> 401 invalid_device_timestamp
    """
    if timestamp_str is None or not timestamp_str.strip():
        raise UnauthorizedError(
            message="Missing X-Device-Timestamp header.",
            code="invalid_device_timestamp",
        )

    try:
        device_time = parse_utc_timestamp(timestamp_str)
    except (ValueError, TypeError) as exc:
        raise AppError(
            code="validation_error",
            message=f"Invalid timestamp format in X-Device-Timestamp: {exc}",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc

    server_time = current_time if current_time is not None else now_utc()
    diff_seconds = (device_time - server_time).total_seconds()
    skew_seconds = abs(diff_seconds)

    if skew_seconds > max_skew_seconds:
        raise UnauthorizedError(
            message=f"Device request timestamp skew ({skew_seconds:.1f}s) exceeds maximum allowed ±{max_skew_seconds}s.",
            code="invalid_device_timestamp",
        )

    return device_time


async def require_device(
    x_device_key: Annotated[str | None, Header(alias="X-Device-Key")] = None,
    x_device_timestamp: Annotated[str | None, Header(alias="X-Device-Timestamp")] = None,
) -> AuthenticatedDevice:
    """
    FastAPI dependency validating access terminal requests:
    1. Validates X-Device-Key using constant-time comparison (hmac.compare_digest) against DEVICE_API_KEY.
    2. Validates X-Device-Timestamp freshness (within ±30s of server UTC time).
    Returns AuthenticatedDevice instance.
    """
    if x_device_key is None or not x_device_key:
        raise UnauthorizedError(
            message="Missing or invalid device key.",
            code="invalid_device_key",
        )

    configured_key = _settings.DEVICE_API_KEY
    if not configured_key:
        raise UnauthorizedError(
            message="Missing or invalid device key.",
            code="invalid_device_key",
        )

    key_bytes = x_device_key.encode("utf-8")
    configured_bytes = configured_key.encode("utf-8")

    if not hmac.compare_digest(key_bytes, configured_bytes):
        raise UnauthorizedError(
            message="Missing or invalid device key.",
            code="invalid_device_key",
        )

    device_time = validate_device_timestamp(x_device_timestamp)
    return AuthenticatedDevice(timestamp=device_time)
