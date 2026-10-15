"""
tests/unit/test_migration_guard.py -- Comprehensive tests for the fail-closed Alembic migration guard.
"""
import pytest

from app.migration_guard import (
    MigrationTargetError,
    mask_database_url,
    parse_port_allowlist,
    parse_string_allowlist,
    validate_migration_target,
)


def test_guard_rejects_by_default_without_opt_in():
    """Fail-closed: local migration is prohibited unless ALLOW_LOCAL_MIGRATION=true."""
    with pytest.raises(MigrationTargetError, match="disabled by default"):
        validate_migration_target(
            url_to_check="postgresql://user:pass@127.0.0.1:5432/digital_key",
            allow_local_migration=False,
        )


def test_guard_rejects_falsy_opt_in_strings():
    """Falsy opt-in strings (false, 0, no) fail closed."""
    for falsy_val in ["false", "0", "no", "off", "", None]:
        with pytest.raises(MigrationTargetError, match="disabled by default"):
            validate_migration_target(
                url_to_check="postgresql://user:pass@127.0.0.1:5432/digital_key",
                allow_local_migration=falsy_val,
            )


def test_guard_rejects_empty_or_missing_url():
    """Missing or empty URL fails closed."""
    with pytest.raises(MigrationTargetError, match="missing or empty"):
        validate_migration_target(
            url_to_check="",
            allow_local_migration=True,
        )


def test_guard_rejects_remote_neon_target():
    """Remote cloud URLs such as Neon are strictly rejected."""
    neon_url = "postgresql+psycopg://neondb_owner:secret_password@ep-cool-neon.tech/neondb"
    with pytest.raises(MigrationTargetError, match="not in the approved migration hosts allowlist"):
        validate_migration_target(
            url_to_check=neon_url,
            allow_local_migration=True,
            approved_hosts={"localhost", "127.0.0.1", "::1"},
            approved_ports={5432},
            approved_db_names={"digital_key"},
        )


def test_guard_accepts_valid_local_targets():
    """Loopback addresses (localhost, 127.0.0.1, ::1) with matching db and port pass."""
    for host in ["localhost", "127.0.0.1", "::1", "[::1]"]:
        result = validate_migration_target(
            url_to_check=f"postgresql+psycopg://digital_key_user:secret@{host}:5432/digital_key",
            allow_local_migration=True,
            approved_hosts={"localhost", "127.0.0.1", "::1"},
            approved_ports={5432},
            approved_db_names={"digital_key"},
        )
        assert result.port == 5432
        assert result.database == "digital_key"
        assert "***" in result.masked_url
        assert "secret" not in result.masked_url


def test_guard_defaults_missing_port_to_5432():
    """If port is omitted in the URL, it defaults to standard PostgreSQL port 5432."""
    result = validate_migration_target(
        url_to_check="postgresql+psycopg://user:pass@localhost/digital_key",
        allow_local_migration=True,
        approved_hosts={"localhost"},
        approved_ports={5432},
        approved_db_names={"digital_key"},
    )
    assert result.port == 5432


def test_guard_rejects_unapproved_port():
    """Ports outside approved_ports fail closed."""
    with pytest.raises(MigrationTargetError, match="Port 5433 is not in the approved migration ports"):
        validate_migration_target(
            url_to_check="postgresql+psycopg://user:pass@localhost:5433/digital_key",
            allow_local_migration=True,
            approved_hosts={"localhost"},
            approved_ports={5432},
            approved_db_names={"digital_key"},
        )


def test_guard_rejects_empty_or_invalid_port_allowlist():
    """Empty or non-integer port allowlists fail closed."""
    with pytest.raises(MigrationTargetError, match="Approved migration ports allowlist is empty"):
        validate_migration_target(
            url_to_check="postgresql+psycopg://user:pass@localhost:5432/digital_key",
            allow_local_migration=True,
            approved_hosts={"localhost"},
            approved_ports=set(),
            approved_db_names={"digital_key"},
        )

    with pytest.raises(MigrationTargetError, match="Invalid port configuration"):
        parse_port_allowlist("5432,invalid_port")


def test_guard_rejects_empty_host_allowlist():
    """Empty host allowlist fails closed."""
    with pytest.raises(MigrationTargetError, match="Approved migration hosts allowlist is empty"):
        validate_migration_target(
            url_to_check="postgresql+psycopg://user:pass@localhost:5432/digital_key",
            allow_local_migration=True,
            approved_hosts=set(),
            approved_ports={5432},
            approved_db_names={"digital_key"},
        )


def test_guard_rejects_unapproved_database_name():
    """Database name mismatch fails closed."""
    with pytest.raises(MigrationTargetError, match="Database 'other_db' is not in the approved migration database"):
        validate_migration_target(
            url_to_check="postgresql+psycopg://user:pass@localhost:5432/other_db",
            allow_local_migration=True,
            approved_hosts={"localhost"},
            approved_ports={5432},
            approved_db_names={"digital_key"},
        )


def test_guard_rejects_empty_database_allowlist():
    """Empty database name allowlist fails closed."""
    with pytest.raises(MigrationTargetError, match="Approved migration databases allowlist is empty"):
        validate_migration_target(
            url_to_check="postgresql+psycopg://user:pass@localhost:5432/digital_key",
            allow_local_migration=True,
            approved_hosts={"localhost"},
            approved_ports={5432},
            approved_db_names=set(),
        )


def test_guard_enforces_user_allowlist_when_configured():
    """If approved_users is configured, non-matching users fail closed."""
    with pytest.raises(MigrationTargetError, match="is not in approved migration users allowlist"):
        validate_migration_target(
            url_to_check="postgresql+psycopg://hacker:pass@localhost:5432/digital_key",
            allow_local_migration=True,
            approved_hosts={"localhost"},
            approved_ports={5432},
            approved_db_names={"digital_key"},
            approved_users={"digital_key_user", "postgres"},
        )

    result = validate_migration_target(
        url_to_check="postgresql+psycopg://digital_key_user:pass@localhost:5432/digital_key",
        allow_local_migration=True,
        approved_hosts={"localhost"},
        approved_ports={5432},
        approved_db_names={"digital_key"},
        approved_users={"digital_key_user", "postgres"},
    )
    assert result.username == "digital_key_user"


def test_mask_database_url_never_exposes_password():
    """Sanitizer masks passwords cleanly without exposing secrets."""
    secret = "P@ssw0rd!#%^&*"
    raw_url = f"postgresql+psycopg://admin:{secret}@127.0.0.1:5432/digital_key"
    masked = mask_database_url(raw_url)
    assert secret not in masked
    assert "***" in masked
    assert "admin" in masked
    assert "127.0.0.1:5432" in masked
    assert "digital_key" in masked
