"""
schemas/device.py -- Pydantic schemas for access terminal device synchronization.

Authoritative specification:
  - docs/api-contract.md §5.4 (Device Synchronization Protocol)
  - docs/credential-policy.md §5 (Synchronization Contract)
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.access_events import EventReason, EventType
from app.services.time_utils import parse_utc_timestamp


class DeviceEventIn(BaseModel):
    """
    Telemetry event uploaded by ESP32 access terminal.
    Follows docs/api-contract.md §5.4.
    """
    event_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique event ID formatted as node-01-<6-digit-nvs-counter>-<8-hex-random>",
    )
    event_type: str = Field(
        ...,
        description="Device telemetry event type (e.g. pin_rejected, credential_accepted)",
    )
    reason: Optional[str] = Field(
        None,
        description="Optional failure reason (e.g. wrong_pin, expired, consumed)",
    )
    resource_code: Optional[str] = Field(
        None,
        max_length=10,
        description="Resource code (e.g. 'A')",
    )
    credential_id: Optional[int] = Field(
        None,
        description="Referenced credential ID or null",
    )
    device_time: Optional[str] = Field(
        None,
        description="Device timestamp in strict ISO-8601 UTC Z format",
    )
    time_trusted: bool = Field(
        ...,
        description="Whether device clock was trusted at event time",
    )

    @field_validator("event_type")
    @classmethod
    def validate_event_type_allowed(cls, v: str) -> str:
        valid_device_types = {
            EventType.PIN_REJECTED.value,
            EventType.CREDENTIAL_ACCEPTED.value,
            EventType.UNLOCK_COMMAND_ISSUED.value,
            EventType.LOCKOUT_STARTED.value,
        }
        if v not in valid_device_types:
            raise ValueError(f"Invalid device event_type '{v}'. Must be one of {sorted(valid_device_types)}")
        return v

    @field_validator("reason")
    @classmethod
    def validate_reason_allowed(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            valid_reasons = {r.value for r in EventReason}
            if v not in valid_reasons:
                raise ValueError(f"Invalid event reason '{v}'. Must be one of {sorted(valid_reasons)}")
        return v

    @field_validator("device_time")
    @classmethod
    def validate_device_time_utc(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                parse_utc_timestamp(v)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid timestamp format for device_time: {exc}") from exc
        return v


class DeviceSyncIn(BaseModel):
    """
    Request payload for POST /device/v1/sync.
    Follows docs/api-contract.md §5.4.
    """
    node_code: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Node identifier (e.g. 'node-01')",
    )
    firmware_version: Optional[str] = Field(
        None,
        max_length=50,
        description="Current terminal firmware version",
    )
    epoch: str = Field(
        ...,
        description="Current synchronization epoch known to device",
    )
    last_seq: int = Field(
        ...,
        ge=0,
        description="Last monotonically acknowledged change sequence number stored in NVS",
    )
    request_nonce: str = Field(
        ...,
        min_length=16,
        max_length=16,
        pattern=r"^[0-9a-f]{16}$",
        description="16-character lowercase hex random nonce generated per request",
    )
    time_state: Optional[str] = Field(
        None,
        description="Node time trust state (untrusted, rtc_validated, server_anchored)",
    )
    device_time: Optional[str] = Field(
        None,
        description="Current device clock in strict ISO-8601 UTC Z format",
    )
    events: list[DeviceEventIn] = Field(
        default_factory=list,
        max_length=20,
        description="Batch of queued telemetry events (max 20 per sync)",
    )

    @field_validator("device_time")
    @classmethod
    def validate_device_time_utc(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                parse_utc_timestamp(v)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid timestamp format for device_time: {exc}") from exc
        return v


class CredentialSyncOut(BaseModel):
    """
    Credential object serialized in sync delta/full resync.
    Contains pin_hmac, NEVER plaintext PIN.
    """
    id: int
    change_seq: int
    resource_code: str
    status: str
    valid_from: str
    valid_until: str
    pin_hmac: str

    model_config = ConfigDict(from_attributes=True)


class DeviceSyncOut(BaseModel):
    """
    Response payload for POST /device/v1/sync.
    Follows docs/api-contract.md §5.4.
    """
    server_time: str = Field(
        ...,
        description="Server authoritative UTC timestamp (seconds precision, literal Z)",
    )
    epoch: str = Field(
        ...,
        description="Current server database synchronization epoch",
    )
    request_nonce: str = Field(
        ...,
        description="Echoed 16-character lowercase hex request nonce",
    )
    full_resync: bool = Field(
        ...,
        description="True if device must purge and replace local credential store",
    )
    from_seq: int = Field(
        ...,
        ge=0,
        description="Lower sequence boundary of the delta response",
    )
    to_seq: int = Field(
        ...,
        ge=0,
        description="Upper sequence boundary included in this response",
    )
    server_seq: int = Field(
        ...,
        ge=0,
        description="Authoritative current server change_seq pointer",
    )
    has_more: bool = Field(
        ...,
        description="True if additional pages of credential deltas remain",
    )
    credentials: list[CredentialSyncOut] = Field(
        default_factory=list,
        description="List of credential delta updates or full snapshot records",
    )
    acked_event_ids: list[str] = Field(
        default_factory=list,
        description="List of event IDs durably committed to database",
    )
