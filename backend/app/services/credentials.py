from datetime import datetime, timezone
import hashlib
import hmac
import re
import secrets
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import get_settings

PIN_REGEX = re.compile(r"^\d{6}$")


def generate_pin() -> str:
    """
    Generates a uniformly distributed 6-digit PIN as a zero-padded string.
    Range: '000000' to '999999'.
    """
    return f"{secrets.randbelow(1_000_000):06d}"


def validate_pin_format(pin: str) -> bool:
    """
    Validates that a PIN is exactly 6 decimal digits.
    """
    return bool(PIN_REGEX.match(pin))


def compute_pin_hmac(resource_code: str, pin: str, hmac_key: str | None = None) -> str:
    """
    Computes keyed HMAC-SHA256 for a PIN bound to a resource code.
    Canonical message: '<resource_code>:<pin>' (e.g. 'A:482916').
    Output: 64-character lowercase hex digest.
    """
    if not resource_code:
        raise ValueError("Resource code cannot be empty.")
    if not validate_pin_format(pin):
        raise ValueError("PIN must be exactly 6 decimal digits.")

    key = hmac_key if hmac_key is not None else get_settings().PIN_HMAC_KEY
    if not key:
        raise ValueError("PIN HMAC key is not configured.")

    canonical_message = f"{resource_code.strip().upper()}:{pin}"
    key_bytes = key.encode("utf-8")
    message_bytes = canonical_message.encode("utf-8")

    return hmac.new(key_bytes, message_bytes, hashlib.sha256).hexdigest().lower()


def verify_pin_hmac(
    resource_code: str,
    pin: str,
    expected_hmac: str,
    hmac_key: str | None = None,
) -> bool:
    """
    Constant-time comparison verifying that a candidate PIN matches the expected HMAC digest.
    """
    if not expected_hmac:
        return False
    try:
        calculated_hmac = compute_pin_hmac(resource_code, pin, hmac_key)
        return hmac.compare_digest(calculated_hmac, expected_hmac.strip().lower())
    except ValueError:
        return False


def get_fernet_cipher(enc_key: str | None = None) -> Fernet:
    """
    Constructs a Fernet cipher instance using the configured or provided key.
    Raises ValueError with a sanitized message on invalid key configuration.
    """
    raw_key = enc_key if enc_key is not None else get_settings().PIN_ENC_KEY
    key = (raw_key or "").strip()
    if not key or key.startswith("replace_with_"):
        raise ValueError("PIN encryption key is not configured or uses placeholder template.")

    try:
        key_bytes = key.encode("utf-8")
        return Fernet(key_bytes)
    except Exception as exc:
        raise ValueError("Invalid Fernet encryption key configuration.") from exc


def encrypt_pin(pin: str, enc_key: str | None = None) -> str:
    """
    Encrypts a plaintext PIN string using Fernet symmetric encryption.
    Returns base64-encoded ciphertext string.
    """
    if not validate_pin_format(pin):
        raise ValueError("PIN must be exactly 6 decimal digits.")

    cipher = get_fernet_cipher(enc_key)
    encrypted_bytes = cipher.encrypt(pin.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_pin(pin_encrypted: str, enc_key: str | None = None) -> str:
    """
    Decrypts a Fernet-encrypted PIN ciphertext back to plaintext.
    Raises ValueError if ciphertext is malformed, corrupted, or cannot be verified.
    """
    if not pin_encrypted:
        raise ValueError("Encrypted PIN ciphertext cannot be empty.")

    cipher = get_fernet_cipher(enc_key)
    try:
        decrypted_bytes = cipher.decrypt(pin_encrypted.encode("utf-8"))
        decrypted_pin = decrypted_bytes.decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt PIN: invalid ciphertext or corrupted key.") from exc
    except Exception as exc:
        raise ValueError("Failed to decrypt PIN.") from exc

    if not validate_pin_format(decrypted_pin):
        raise ValueError("Decrypted payload is not a valid 6-digit PIN.")

    return decrypted_pin


def sweep_expired_credentials(
    db: Session,
    resource_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> list:
    """
    Performs the policy-mandated expiry sweep (docs/credential-policy.md Sections 3.1 & 4.1).
    Sweeps active credentials where valid_until <= now.
    Atomically updates status to 'expired', advances change_seq via allocate_next_change_seq(),
    and emits 'credential_expired' audit events.
    """
    from app.models.access_events import EventReason, EventType
    from app.models.credentials import Credential, CredentialStatus
    from app.services.events import record_server_event
    from app.services.sequence import allocate_next_change_seq

    check_time = now if now is not None else datetime.now(timezone.utc)
    if check_time.tzinfo is None:
        check_time = check_time.replace(tzinfo=timezone.utc)

    query = (
        db.query(Credential)
        .filter(
            Credential.status == CredentialStatus.ACTIVE.value,
            Credential.valid_until <= check_time,
        )
    )
    if resource_id is not None:
        query = query.filter(Credential.resource_id == resource_id)

    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        query = query.with_for_update()

    expired_creds = query.order_by(Credential.id.asc()).all()
    swept = []
    for cred in expired_creds:
        next_seq = allocate_next_change_seq(db)
        cred.status = CredentialStatus.EXPIRED.value
        cred.change_seq = next_seq
        record_server_event(
            db=db,
            event_type=EventType.CREDENTIAL_EXPIRED.value,
            reason=EventReason.EXPIRED.value,
            resource_id=cred.resource_id,
            request_id=cred.request_id,
            credential_id=cred.id,
            note="Automatic expiration sweep: valid_until passed",
        )
        swept.append(cred)

    if swept:
        db.flush()

    return swept
