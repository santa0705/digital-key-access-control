import pytest
from sqlalchemy import BigInteger, SmallInteger
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import (
    AccessEvent,
    AccessRequest,
    Base,
    Credential,
    CredentialStatus,
    RevokeReason,
    EventReason,
    EventSource,
    EventType,
    Node,
    NodeTimeState,
    RequestStatus,
    Resource,
    ResourceKind,
    SyncState,
    User,
    UserRole,
)


def test_metadata_contains_all_seven_tables():
    """Verify that all seven required domain tables are registered in the Declarative Base metadata."""
    expected_tables = {
        "users",
        "resources",
        "nodes",
        "sync_state",
        "access_requests",
        "credentials",
        "access_events",
    }
    registered_tables = set(Base.metadata.tables.keys())
    assert registered_tables == expected_tables, f"Tables mismatch: {registered_tables ^ expected_tables}"


def test_users_table_structure_and_constraints():
    """Verify users table columns, types, nullability, unique keys, and check constraints."""
    table = Base.metadata.tables["users"]

    # Primary key must be 64-bit integer
    assert isinstance(table.c.id.type, BigInteger)
    assert table.c.id.primary_key is True

    # Email uniqueness and nullability
    assert table.c.email.nullable is False
    assert table.c.email.unique is True

    # Check constraint on role
    check_names = {ck.name for ck in table.constraints if hasattr(ck, "sqltext")}
    assert "ck_users_role" in check_names
    ck_role = next(ck for ck in table.constraints if getattr(ck, "name", None) == "ck_users_role")
    assert "user" in str(ck_role.sqltext)
    assert "admin" in str(ck_role.sqltext)


def test_resources_table_structure_and_constraints():
    """Verify resources table columns, code constraints ('A', 'B'), and kind constraints."""
    table = Base.metadata.tables["resources"]

    assert isinstance(table.c.id.type, BigInteger)
    assert table.c.code.unique is True
    assert table.c.code.nullable is False

    check_names = {ck.name for ck in table.constraints if hasattr(ck, "sqltext")}
    assert "ck_resources_code" in check_names
    assert "ck_resources_kind" in check_names

    ck_code = next(ck for ck in table.constraints if getattr(ck, "name", None) == "ck_resources_code")
    assert "'A'" in str(ck_code.sqltext) and "'B'" in str(ck_code.sqltext)

    ck_kind = next(ck for ck in table.constraints if getattr(ck, "name", None) == "ck_resources_kind")
    assert "physical" in str(ck_kind.sqltext) and "simulated" in str(ck_kind.sqltext)


def test_nodes_table_structure_and_constraints():
    """Verify nodes table for terminal hardware with time_state constraints and sequence counters."""
    table = Base.metadata.tables["nodes"]

    assert isinstance(table.c.id.type, BigInteger)
    assert table.c.node_code.unique is True
    assert isinstance(table.c.last_acked_seq.type, BigInteger)

    check_names = {ck.name for ck in table.constraints if hasattr(ck, "sqltext")}
    assert "ck_nodes_time_state" in check_names


def test_sync_state_singleton_constraint():
    """Verify sync_state table has id=1 constraint for gap-free monotonic sequencing."""
    table = Base.metadata.tables["sync_state"]

    assert isinstance(table.c.id.type, SmallInteger)
    assert isinstance(table.c.current_seq.type, BigInteger)

    check_names = {ck.name for ck in table.constraints if hasattr(ck, "sqltext")}
    assert "ck_sync_state_single_row" in check_names
    ck_single = next(ck for ck in table.constraints if getattr(ck, "name", None) == "ck_sync_state_single_row")
    assert "id = 1" in str(ck_single.sqltext)


def test_access_requests_table_structure_and_window_checks():
    """Verify access_requests table constraints: duration <= 24h, end_at > start_at, and status enum."""
    table = Base.metadata.tables["access_requests"]

    assert isinstance(table.c.id.type, BigInteger)
    assert table.c.user_id.nullable is False
    assert table.c.resource_id.nullable is False

    # Foreign key targets
    fk_targets = {fk.target_fullname for fk in table.foreign_keys}
    assert "users.id" in fk_targets
    assert "resources.id" in fk_targets

    check_names = {ck.name for ck in table.constraints if hasattr(ck, "sqltext")}
    assert "ck_access_requests_status" in check_names
    assert "ck_access_requests_end_after_start" in check_names
    assert "ck_access_requests_max_24h" in check_names


def test_credentials_table_rule_r1_and_pin_protection():
    """
    Verify credentials table:
    - Rule R1: Partial unique index (resource_id) WHERE status = 'active'
    - Composite unique constraint (resource_id, pin_hmac)
    - Request unique foreign key (one credential per request)
    - Valid window check
    - No plaintext PIN column exists
    """
    table = Base.metadata.tables["credentials"]

    assert isinstance(table.c.id.type, BigInteger)
    assert isinstance(table.c.change_seq.type, BigInteger)
    assert table.c.change_seq.unique is True
    assert table.c.request_id.unique is True

    # Assert no plaintext PIN column exists anywhere
    assert "pin" not in table.c
    assert "plaintext_pin" not in table.c
    assert "pin_hmac" in table.c
    assert "pin_encrypted" in table.c

    # Check constraints
    check_names = {ck.name for ck in table.constraints if hasattr(ck, "sqltext")}
    assert "ck_credentials_status" in check_names
    assert "ck_credentials_revoke_reason" in check_names
    assert "ck_credentials_valid_window" in check_names

    # Verify ck_credentials_revoke_reason rule expression
    revoke_ck = next(ck for ck in table.constraints if getattr(ck, "name", "") == "ck_credentials_revoke_reason")
    ck_sql = str(revoke_ck.sqltext)
    assert "status = 'revoked'" in ck_sql
    assert "revoke_reason IN ('admin', 'superseded')" in ck_sql
    assert "status != 'revoked' AND revoke_reason IS NULL" in ck_sql

    # Composite uniqueness on (resource_id, pin_hmac)
    uq_constraints = [c for c in table.constraints if hasattr(c, "columns") and len(c.columns) == 2]
    composite_cols = {col.name for c in uq_constraints for col in c.columns}
    assert "resource_id" in composite_cols
    assert "pin_hmac" in composite_cols

    # Partial unique index (Rule R1)
    partial_indexes = [idx for idx in table.indexes if getattr(idx, "name", "") == "uq_credentials_resource_active"]
    assert len(partial_indexes) == 1, "Missing partial unique index uq_credentials_resource_active"
    idx_r1 = partial_indexes[0]
    assert idx_r1.unique is True
    assert "status = 'active'" in str(idx_r1.dialect_options["postgresql"]["where"])

    # Verify no redundant standalone index on resource_id exists on credentials table
    resource_id_indexes = [
        idx for idx in table.indexes
        if [c.name for c in idx.columns] == ["resource_id"] and not idx.unique
    ]
    assert len(resource_id_indexes) == 0, f"Found redundant index on resource_id: {resource_id_indexes}"


def test_access_events_table_structure_and_audit_checks():
    """Verify access_events table check constraints on source, event_type, reason, and descending index."""
    table = Base.metadata.tables["access_events"]

    assert isinstance(table.c.id.type, BigInteger)
    assert table.c.event_id.unique is True
    assert table.c.event_id.nullable is False

    check_names = {ck.name for ck in table.constraints if hasattr(ck, "sqltext")}
    assert "ck_access_events_source" in check_names
    assert "ck_access_events_event_type" in check_names
    assert "ck_access_events_reason" in check_names
    assert "ck_access_events_device_time_trusted" in check_names

    # Check for descending occurred_at index
    index_names = {idx.name for idx in table.indexes}
    assert "ix_access_events_occurred_at_desc" in index_names


def test_postgresql_ddl_compilation():
    """Assert that all seven tables and partial indexes compile cleanly to valid PostgreSQL DDL."""
    pg_dialect = postgresql.dialect()

    for table_name, table in Base.metadata.tables.items():
        create_stmt = str(CreateTable(table).compile(dialect=pg_dialect))
        assert f"CREATE TABLE {table_name}" in create_stmt
        assert len(create_stmt) > 0

    # Test compilation of partial unique index
    credentials_table = Base.metadata.tables["credentials"]
    r1_index = next(idx for idx in credentials_table.indexes if idx.name == "uq_credentials_resource_active")
    index_ddl = str(CreateIndex(r1_index).compile(dialect=pg_dialect))
    assert "CREATE UNIQUE INDEX uq_credentials_resource_active ON credentials (resource_id) WHERE status = 'active'" in index_ddl


def test_model_enums_and_constants():
    """Verify all StrEnum constants match documented lowercase snake_case values."""
    assert UserRole.USER == "user"
    assert UserRole.ADMIN == "admin"

    assert ResourceKind.PHYSICAL == "physical"
    assert ResourceKind.SIMULATED == "simulated"

    assert NodeTimeState.UNTRUSTED == "untrusted"
    assert NodeTimeState.RTC_VALIDATED == "rtc_validated"
    assert NodeTimeState.SERVER_ANCHORED == "server_anchored"

    assert RequestStatus.PENDING == "pending"
    assert RequestStatus.APPROVED == "approved"
    assert RequestStatus.REJECTED == "rejected"
    assert RequestStatus.REVOKED == "revoked"

    assert CredentialStatus.ACTIVE == "active"
    assert CredentialStatus.CONSUMED == "consumed"
    assert CredentialStatus.EXPIRED == "expired"
    assert CredentialStatus.REVOKED == "revoked"

    assert RevokeReason.ADMIN == "admin"
    assert RevokeReason.SUPERSEDED == "superseded"

    assert EventSource.DEVICE == "device"
    assert EventSource.SERVER == "server"

    assert EventType.PIN_REJECTED == "pin_rejected"
    assert EventType.CREDENTIAL_ACCEPTED == "credential_accepted"
    assert EventType.UNLOCK_COMMAND_ISSUED == "unlock_command_issued"
    assert EventType.LOCKOUT_STARTED == "lockout_started"
    assert EventType.REQUEST_CREATED == "request_created"
    assert EventType.REQUEST_APPROVED == "request_approved"
    assert EventType.REQUEST_REJECTED == "request_rejected"
    assert EventType.CREDENTIAL_ISSUED == "credential_issued"
    assert EventType.CREDENTIAL_REPLACED == "credential_replaced"
    assert EventType.CREDENTIAL_REVOKED == "credential_revoked"
    assert EventType.CREDENTIAL_EXPIRED == "credential_expired"
    assert EventType.CREDENTIAL_CONSUMED == "credential_consumed"
    assert EventType.PIN_REVEALED == "pin_revealed"

    assert EventReason.WRONG_PIN == "wrong_pin"
    assert EventReason.WRONG_RESOURCE == "wrong_resource"
    assert EventReason.EXPIRED == "expired"
    assert EventReason.NOT_YET_VALID == "not_yet_valid"
    assert EventReason.CONSUMED == "consumed"
    assert EventReason.REVOKED == "revoked"
    assert EventReason.TIME_UNTRUSTED == "time_untrusted"
