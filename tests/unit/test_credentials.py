import hashlib
import hmac
import pytest
from cryptography.fernet import Fernet

from app.services.credentials import (
    compute_pin_hmac,
    decrypt_pin,
    encrypt_pin,
    generate_pin,
    validate_pin_format,
    verify_pin_hmac,
)

# Test-only secrets (never used in production)
TEST_HMAC_KEY = "dkac-test-vector-key-0001"
TEST_FERNET_KEY = Fernet.generate_key().decode("utf-8")


def test_generate_pin_format_and_length():
    """Verify that generate_pin produces uniformly formatted 6-digit decimal strings."""
    pins = [generate_pin() for _ in range(50)]
    for pin in pins:
        assert isinstance(pin, str)
        assert len(pin) == 6
        assert pin.isdigit()
        assert validate_pin_format(pin) is True


def test_validate_pin_format():
    """Verify validation boundaries for 6-digit PIN strings."""
    assert validate_pin_format("000000") is True
    assert validate_pin_format("000042") is True
    assert validate_pin_format("999999") is True
    assert validate_pin_format("12345") is False  # 5 digits
    assert validate_pin_format("1234567") is False  # 7 digits
    assert validate_pin_format("abcdef") is False  # non-digits
    assert validate_pin_format("") is False


def test_pin_hmac_official_test_vectors():
    """
    Verify exact compliance with official Test Vector 1 in docs/credential-policy.md §2.3.
    """
    pin = "482916"

    # Resource A
    expected_hmac_a = "e48f878502a47172ea00cf018627956dab95a5073357dc5b01220bc4179093bc"
    calculated_a = compute_pin_hmac("A", pin, hmac_key=TEST_HMAC_KEY)
    assert calculated_a == expected_hmac_a
    assert verify_pin_hmac("A", pin, expected_hmac_a, hmac_key=TEST_HMAC_KEY) is True

    # Resource B (same PIN, different resource yields different digest)
    expected_hmac_b = "ed29df457234511590c7bc93b50d72e12d91ef377ff1fa0e81245087c0e937ca"
    calculated_b = compute_pin_hmac("B", pin, hmac_key=TEST_HMAC_KEY)
    assert calculated_b == expected_hmac_b
    assert verify_pin_hmac("B", pin, expected_hmac_b, hmac_key=TEST_HMAC_KEY) is True

    # Cross-resource verification must fail
    assert verify_pin_hmac("B", pin, expected_hmac_a, hmac_key=TEST_HMAC_KEY) is False
    assert verify_pin_hmac("A", pin, expected_hmac_b, hmac_key=TEST_HMAC_KEY) is False


def test_pin_hmac_leading_zeros():
    """Verify that leading zeros in PIN strings are preserved during canonical HMAC computation."""
    pin_leading_zero = "000042"
    expected_digest = hmac.new(
        TEST_HMAC_KEY.encode("utf-8"),
        b"A:000042",
        hashlib.sha256,
    ).hexdigest().lower()

    computed = compute_pin_hmac("A", pin_leading_zero, hmac_key=TEST_HMAC_KEY)
    assert computed == expected_digest
    assert verify_pin_hmac("A", pin_leading_zero, expected_digest, hmac_key=TEST_HMAC_KEY) is True

    # Suffix without leading zero must not verify
    assert verify_pin_hmac("A", "42", expected_digest, hmac_key=TEST_HMAC_KEY) is False
    assert verify_pin_hmac("A", "000043", expected_digest, hmac_key=TEST_HMAC_KEY) is False


def test_compute_pin_hmac_validation_errors():
    """Verify that invalid inputs raise ValueError."""
    with pytest.raises(ValueError, match="Resource code cannot be empty"):
        compute_pin_hmac("", "123456", hmac_key=TEST_HMAC_KEY)

    with pytest.raises(ValueError, match="PIN must be exactly 6 decimal digits"):
        compute_pin_hmac("A", "12345", hmac_key=TEST_HMAC_KEY)

    with pytest.raises(ValueError, match="PIN HMAC key is not configured"):
        compute_pin_hmac("A", "123456", hmac_key="")


def test_pin_encryption_roundtrip():
    """Verify Fernet encryption and decryption round-trip with test key."""
    # Standard PIN
    pin = "482916"
    ciphertext = encrypt_pin(pin, enc_key=TEST_FERNET_KEY)
    assert isinstance(ciphertext, str)
    assert ciphertext != pin
    decrypted = decrypt_pin(ciphertext, enc_key=TEST_FERNET_KEY)
    assert decrypted == pin

    # Leading-zero PIN preservation
    pin_zero = "000042"
    ciphertext_zero = encrypt_pin(pin_zero, enc_key=TEST_FERNET_KEY)
    decrypted_zero = decrypt_pin(ciphertext_zero, enc_key=TEST_FERNET_KEY)
    assert decrypted_zero == pin_zero
    assert len(decrypted_zero) == 6


def test_pin_encryption_invalid_inputs_and_corrupted_ciphertext():
    """Verify error handling on invalid encryption keys and corrupted ciphertexts."""
    # Malformed PIN format on encryption
    with pytest.raises(ValueError, match="PIN must be exactly 6 decimal digits"):
        encrypt_pin("123", enc_key=TEST_FERNET_KEY)

    # Invalid Fernet key configuration
    with pytest.raises(ValueError, match="Invalid Fernet encryption key configuration"):
        encrypt_pin("123456", enc_key="not-a-valid-base64-fernet-key")

    # Empty ciphertext
    with pytest.raises(ValueError, match="Encrypted PIN ciphertext cannot be empty"):
        decrypt_pin("", enc_key=TEST_FERNET_KEY)

    # Corrupted / tampered ciphertext
    with pytest.raises(ValueError, match="Failed to decrypt PIN"):
        decrypt_pin("gAAAAABl-corrupted-ciphertext-token-here", enc_key=TEST_FERNET_KEY)

    # Decrypt with wrong valid Fernet key
    other_key = Fernet.generate_key().decode("utf-8")
    ct = encrypt_pin("123456", enc_key=TEST_FERNET_KEY)
    with pytest.raises(ValueError, match="Failed to decrypt PIN"):
        decrypt_pin(ct, enc_key=other_key)
