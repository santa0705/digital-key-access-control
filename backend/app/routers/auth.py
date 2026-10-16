"""
routers/auth.py -- Authentication endpoints (Person B).

Implements:
  - POST /auth/login (Contract 5.1)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import bcrypt
from fastapi import APIRouter, Depends, status
import jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import UnauthorizedError
from app.models.users import User
from app.schemas.auth import LoginRequest, LoginResponse, UserSummary

router = APIRouter(prefix="/auth", tags=["Authentication"])
_settings = get_settings()


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user or admin",
    description="Authenticate user or admin using email and password; returns JWT session token (HS256, 8-hour lifetime).",
)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """
    POST /auth/login
    """
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not user.is_active:
        raise UnauthorizedError(
            message="Invalid email or password.",
            code="invalid_credentials",
        )

    try:
        pw_matches = bcrypt.checkpw(
            payload.password.encode("utf-8"),
            user.password_hash.encode("utf-8"),
        )
    except Exception:
        pw_matches = False

    if not pw_matches:
        raise UnauthorizedError(
            message="Invalid email or password.",
            code="invalid_credentials",
        )

    now = datetime.now(timezone.utc)
    expires_in_seconds = 28800  # 8 hours
    exp = now + timedelta(seconds=expires_in_seconds)

    token_payload = {
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }

    access_token = jwt.encode(
        token_payload,
        _settings.JWT_SECRET,
        algorithm="HS256",
    )

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in_seconds,
        user=UserSummary(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
        ),
    )
