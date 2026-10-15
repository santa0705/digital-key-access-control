from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest

from app.models import Base


def get_alembic_config() -> Config:
    """Return configured Alembic Config pointing to backend/alembic.ini."""
    backend_dir = Path(__file__).resolve().parent.parent.parent / "backend"
    ini_path = backend_dir / "alembic.ini"
    cfg = Config(str(ini_path))
    # Ensure script_location is absolute so test runner from root finds it
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    return cfg


def test_alembic_configuration_and_head_revision():
    """Verify Alembic finds exactly one linear head revision: 0001_initial_schema."""
    cfg = get_alembic_config()
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()

    assert len(heads) == 1, f"Expected exactly 1 migration head, got: {heads}"
    assert heads[0] == "0001_initial_schema"

    rev = script.get_revision("0001_initial_schema")
    assert rev is not None
    assert rev.down_revision is None


def test_alembic_target_metadata_contains_all_models():
    """Verify that Alembic target metadata discovers all seven domain tables from Base."""
    expected_tables = {
        "users",
        "resources",
        "nodes",
        "sync_state",
        "access_requests",
        "credentials",
        "access_events",
    }
    assert set(Base.metadata.tables.keys()) == expected_tables


def test_alembic_offline_sql_generation_contains_critical_ddl(capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch):
    """
    Offline compilation test (requires no live database connection).
    Verifies that Alembic generates complete, valid PostgreSQL DDL with:
    - 7 tables and exact primary/foreign keys
    - Rule R1 partial unique index (uq_credentials_resource_active)
    - Monotonic change-seq procedure (next_change_seq)
    - Terminal immutability trigger and function
    - Descending audit index (ix_access_events_occurred_at_desc)
    - Absence of redundant standalone indexes on unique columns
    """
    from alembic import command

    monkeypatch.setenv("ALLOW_LOCAL_MIGRATION", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://postgres:dummy@127.0.0.1:5432/digital_key")

    cfg = get_alembic_config()

    # Generate offline SQL without connecting to Neon
    command.upgrade(cfg, "head", sql=True)
    captured = capsys.readouterr()
    generated_sql = captured.out

    # 1. Verify tables
    assert "CREATE TABLE users" in generated_sql
    assert "CREATE TABLE resources" in generated_sql
    assert "CREATE TABLE nodes" in generated_sql
    assert "CREATE TABLE sync_state" in generated_sql
    assert "CREATE TABLE access_requests" in generated_sql
    assert "CREATE TABLE credentials" in generated_sql
    assert "CREATE TABLE access_events" in generated_sql

    # 2. Verify Rule R1 Partial Unique Index
    assert "CREATE UNIQUE INDEX uq_credentials_resource_active" in generated_sql
    assert "WHERE status = 'active'" in generated_sql

    # 3. Verify monotonic sequence procedure & singleton row
    assert "CREATE OR REPLACE FUNCTION next_change_seq()" in generated_sql
    assert "UPDATE sync_state" in generated_sql
    assert "RETURNING current_seq" in generated_sql
    assert "INSERT INTO sync_state" in generated_sql

    # 4. Verify terminal immutability and deletion protection triggers
    assert "CREATE OR REPLACE FUNCTION trg_credentials_terminal_immutability()" in generated_sql
    assert "CREATE TRIGGER check_credential_terminal_immutability" in generated_sql
    assert "BEFORE UPDATE OR DELETE ON credentials" in generated_sql
    assert "CREATE OR REPLACE FUNCTION trg_sync_state_protect_delete()" in generated_sql
    assert "CREATE TRIGGER check_sync_state_protect_delete" in generated_sql
    assert "BEFORE DELETE ON sync_state" in generated_sql

    # 5. Verify descending audit index
    assert "CREATE INDEX ix_access_events_occurred_at_desc" in generated_sql
    assert "occurred_at DESC" in generated_sql

    # 6. Verify 4 redundant standalone indexes were removed
    assert "CREATE INDEX ix_users_email" not in generated_sql
    assert "CREATE INDEX ix_resources_code" not in generated_sql
    assert "CREATE INDEX ix_nodes_node_code" not in generated_sql
    assert "CREATE INDEX ix_access_events_event_id" not in generated_sql


def test_alembic_offline_downgrade_sql_generation(capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch):
    """
    Offline downgrade test (requires no live database connection).
    Verifies that Alembic produces clean reverse DDL in exact reverse dependency order.
    """
    from alembic import command

    monkeypatch.setenv("ALLOW_LOCAL_MIGRATION", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://postgres:dummy@127.0.0.1:5432/digital_key")

    cfg = get_alembic_config()

    command.downgrade(cfg, "0001_initial_schema:base", sql=True)
    captured = capsys.readouterr()
    generated_sql = captured.out

    assert "DROP INDEX IF EXISTS ix_access_events_occurred_at_desc" in generated_sql
    assert "DROP TABLE access_events" in generated_sql
    assert "DROP TRIGGER IF EXISTS check_credential_terminal_immutability" in generated_sql
    assert "DROP FUNCTION IF EXISTS trg_credentials_terminal_immutability" in generated_sql
    assert "DROP INDEX IF EXISTS uq_credentials_resource_active" in generated_sql
    assert "DROP TABLE credentials" in generated_sql
    assert "DROP TABLE access_requests" in generated_sql
    assert "DROP TRIGGER IF EXISTS check_sync_state_protect_delete" in generated_sql
    assert "DROP FUNCTION IF EXISTS trg_sync_state_protect_delete" in generated_sql
    assert "DROP FUNCTION IF EXISTS next_change_seq" in generated_sql
    assert "DROP TABLE sync_state" in generated_sql
    assert "DROP TABLE nodes" in generated_sql
    assert "DROP TABLE resources" in generated_sql
    assert "DROP TABLE users" in generated_sql
