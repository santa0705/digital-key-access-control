"""
schemas/access_requests.py -- Pydantic schemas for access-request endpoints.

Contract 4.1 (Shared AccessRequest object), 5.2 (POST /access-requests,
GET /access-requests/me, GET /access-requests/{id}/pin).

Timestamp rules (Contract 3.1):
  - Strict ISO-8601 UTC with seconds precision and literal uppercase Z suffix.
  - Fractional seconds or non-Z offsets are rejected (validation_error).
  - start_at cannot be more than 1 minute in the past.
  - end_at > start_at, duration <= 24 h.

PIN rules:
  - Plaintext PIN never included in AccessRequestOut.
  - PinRevealOut is the only schema that carries a plaintext PIN, and only
    after ownership and active-credential checks pass in the router.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Strict Z-suffix UTC pattern: YYYY-MM-DDTHH:MM:SSZ (no fractional seconds,
# no +HH:MM offsets).
_UTC_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _parse_utc_z(value: str, field_name: str) -> datetime:
    """
    Parse an ISO-8601 UTC timestamp that MUST end with literal 'Z' and have
    no fractional seconds.  Raises ValueError for anything else.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    if not _UTC_Z_RE.match(value):
        raise ValueError(
            f"{field_name} must be in strict ISO-8601 UTC format "
            f"'YYYY-MM-DDTHH:MM:SSZ' (no fractional seconds, no +00:00 offset). "
            f"Got: {value!r}"
        )
    # Replace trailing Z with +00:00 so Python can parse it, then normalise.
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt


def _fmt_utc_z(dt: datetime) -> str:
    """Format a timezone-aware datetime as strict 'YYYY-MM-DDTHH:MM:SSZ'."""
    utc = dt.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Nested output schemas
# ---------------------------------------------------------------------------

class ResourceSummary(BaseModel):
    """Embedded resource snippet inside AccessRequestOut."""
    id: int
    code: str
    name: str
    kind: str

    model_config = ConfigDict(from_attributes=True)


class UserSummary(BaseModel):
    """Embedded user snippet inside AccessRequestOut."""
    id: int
    full_name: str

    model_config = ConfigDict(from_attributes=True)


class CredentialSummary(BaseModel):
    """
    Embedded credential snippet inside AccessRequestOut.

    Rules:
      - pin_hmac and pin_encrypted are NEVER included here.
      - revoke_reason is null when status != revoked.
    """
    id: int
    status: str
    valid_from: str
    valid_until: str
    revoke_reason: Optional[str]

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_obj(cls, cred) -> "CredentialSummary":
        return cls(
            id=cred.id,
            status=cred.status,
            valid_from=_fmt_utc_z(cred.valid_from),
            valid_until=_fmt_utc_z(cred.valid_until),
            revoke_reason=cred.revoke_reason,
        )


# ---------------------------------------------------------------------------
# Request input schema
# ---------------------------------------------------------------------------

class AccessRequestCreate(BaseModel):
    """
    Body for POST /access-requests.

    Validation rules (Contract 5.2):
      - start_at and end_at must be strict 'YYYY-MM-DDTHH:MM:SSZ'.
      - end_at > start_at.
      - Duration <= 24 hours.
      - start_at cannot be more than 1 minute in the past (checked in router
        where server UTC is available, not here, to allow unit-testable schemas).
    """
    resource_id: int = Field(..., gt=0, description="ID of the target resource.")
    start_at: str = Field(..., description="Access window start (YYYY-MM-DDTHH:MM:SSZ).")
    end_at: str = Field(..., description="Access window end (YYYY-MM-DDTHH:MM:SSZ).")
    purpose: Optional[str] = Field(
        None,
        max_length=200,
        description="Optional human-readable purpose (max 200 chars).",
    )

    # Parsed datetime objects (populated after validation).
    _start_dt: datetime = None
    _end_dt: datetime = None

    @field_validator("start_at")
    @classmethod
    def validate_start_at(cls, v: str) -> str:
        _parse_utc_z(v, "start_at")  # raises ValueError if invalid
        return v

    @field_validator("end_at")
    @classmethod
    def validate_end_at(cls, v: str) -> str:
        _parse_utc_z(v, "end_at")  # raises ValueError if invalid
        return v

    @model_validator(mode="after")
    def validate_window(self) -> "AccessRequestCreate":
        start_dt = _parse_utc_z(self.start_at, "start_at")
        end_dt = _parse_utc_z(self.end_at, "end_at")

        if end_dt <= start_dt:
            raise ValueError("end_at must be strictly after start_at.")

        if (end_dt - start_dt) > timedelta(hours=24):
            raise ValueError("Access window duration must not exceed 24 hours.")

        return self

    def parsed_start(self) -> datetime:
        """Return parsed start_at as UTC-aware datetime."""
        return _parse_utc_z(self.start_at, "start_at")

    def parsed_end(self) -> datetime:
        """Return parsed end_at as UTC-aware datetime."""
        return _parse_utc_z(self.end_at, "end_at")


# ---------------------------------------------------------------------------
# Response output schemas
# ---------------------------------------------------------------------------

class AccessRequestOut(BaseModel):
    """
    Shared AccessRequest object (Contract 4.1).

    Rules:
      - When status is 'pending' or 'rejected', credential, decision_note,
        and decided_at are null.
      - Plaintext PIN is never included.
    """
    id: int
    resource: ResourceSummary
    user: UserSummary
    start_at: str
    end_at: str
    purpose: Optional[str]
    status: str
    decision_note: Optional[str]
    decided_at: Optional[str]
    created_at: str
    credential: Optional[CredentialSummary]

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_obj(cls, req) -> "AccessRequestOut":
        """
        Build AccessRequestOut from an AccessRequest ORM object.
        Enforces nullability rules for pending/rejected states.
        """
        status = req.status
        show_decision = status in ("approved", "revoked")

        cred_out = None
        if req.credential is not None:
            cred_out = CredentialSummary.from_orm_obj(req.credential)

        return cls(
            id=req.id,
            resource=ResourceSummary.model_validate(req.resource),
            user=UserSummary.model_validate(req.user),
            start_at=_fmt_utc_z(req.start_at),
            end_at=_fmt_utc_z(req.end_at),
            purpose=req.purpose,
            status=status,
            decision_note=req.decision_note if show_decision else None,
            decided_at=_fmt_utc_z(req.decided_at) if (show_decision and req.decided_at) else None,
            created_at=_fmt_utc_z(req.created_at),
            credential=cred_out,
        )


class PinRevealOut(BaseModel):
    """
    Response for GET /access-requests/{id}/pin.

    Contract 5.2:
      {"request_id": 5, "resource_code": "A", "pin": "482916",
       "valid_from": "...", "valid_until": "..."}

    This is the only schema allowed to carry a plaintext PIN.
    The router must never return this unless ownership and active-status checks
    have already passed.
    """
    request_id: int
    resource_code: str
    pin: str
    valid_from: str
    valid_until: str
