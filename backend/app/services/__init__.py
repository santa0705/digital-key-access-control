"""
backend/app/services package -- Person A and Person B backend services.

Services:
  - access_requests: Request creation, ownership checks, and PIN reveal coordination.
  - events: Telemetry/audit event creation, validation, and unknown credential handling.
  - sequence: Change sequence allocation (allocate_next_change_seq) and transaction coordination.
  - credentials: PIN generation, HMAC calculation/verification, and Fernet encryption/decryption.
  - time_utils: Strict ISO-8601 UTC timestamp parsing, formatting, and freshness validation.
"""
from app.services import access_requests, credentials, events, sequence, time_utils
from app.services.credentials import (
    compute_pin_hmac,
    decrypt_pin,
    encrypt_pin,
    generate_pin,
    validate_pin_format,
    verify_pin_hmac,
)
from app.services.sequence import allocate_next_change_seq
from app.services.time_utils import (
    format_utc_timestamp,
    is_credential_window_active,
    is_time_anchor_fresh,
    now_utc,
    now_utc_string,
    parse_utc_timestamp,
)

__all__ = [
    "access_requests",
    "events",
    "sequence",
    "credentials",
    "time_utils",
    "allocate_next_change_seq",
    "compute_pin_hmac",
    "decrypt_pin",
    "encrypt_pin",
    "generate_pin",
    "validate_pin_format",
    "verify_pin_hmac",
    "format_utc_timestamp",
    "is_credential_window_active",
    "is_time_anchor_fresh",
    "now_utc",
    "now_utc_string",
    "parse_utc_timestamp",
]
