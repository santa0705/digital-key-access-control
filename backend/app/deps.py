"""
deps.py -- FastAPI dependencies shared across Person A routers.

Provides:
  - get_current_user: decodes Bearer JWT, returns the User ORM object.
                      Raises DomainError("unauthorized") for missing/invalid/
                      expired tokens.
  - require_user:     alias for get_current_user (any authenticated user).

Person B owns the auth/login route and JWT minting.  This module only
VERIFIES tokens using the same JWT_SECRET and algorithm (HS256).

Token shape expected (subset):
    {"sub": "<user_id>", "role": "<user|admin>", "exp": <unix_ts>}
"""
from __future__ import annotations

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import err_unauthorized
from app.models.users import User

_bearer_scheme = HTTPBearer(auto_error=False)
_settings = get_settings()

JWT_ALGORITHM = "HS256"


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Decode the Bearer JWT from the Authorization header and return the
    authenticated User ORM row.

    Raises DomainError "unauthorized" for:
      - Missing Authorization header
      - Malformed token
      - Expired token
      - Unknown user_id in token
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise err_unauthorized("Missing or malformed Authorization header.")

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            _settings.JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise err_unauthorized("Token has expired.")
    except jwt.InvalidTokenError:
        raise err_unauthorized("Invalid token.")

    user_id_raw = payload.get("sub")
    if user_id_raw is None:
        raise err_unauthorized("Token missing subject claim.")

    try:
        user_id = int(user_id_raw)
    except (ValueError, TypeError):
        raise err_unauthorized("Token subject is not a valid user ID.")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise err_unauthorized("User not found or inactive.")

    return user
