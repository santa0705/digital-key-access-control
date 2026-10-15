import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(BaseModel):
    """
    POST /auth/login request body.
    Requires email in standard format and non-empty password.
    """
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=1, description="User password")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if not EMAIL_REGEX.match(cleaned):
            raise ValueError("Invalid email format.")
        return cleaned


class UserSummary(BaseModel):
    """
    User information object returned in auth response and user endpoints.
    Matches docs/api-contract.md §5.1.
    """
    id: int
    email: str
    full_name: str
    role: Literal["user", "admin"]

    model_config = ConfigDict(from_attributes=True)


class LoginResponse(BaseModel):
    """
    POST /auth/login 200 OK response body.
    Strictly mirrors docs/api-contract.md §5.1.
    """
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = 28800
    user: UserSummary
