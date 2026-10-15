import hashlib
import hmac
import re
import secrets
from cryptography.fernet import Fernet, InvalidToken

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
    key = enc_key if enc_key is not None else get_settings().PIN_ENC_KEY
    if not key:
        raise ValueError("PIN encryption key is not configured.")

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
