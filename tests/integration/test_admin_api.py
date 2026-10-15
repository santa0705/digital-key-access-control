"""
tests/integration/test_admin_api.py -- Integration tests for GET /admin/logs and GET /admin/nodes.

Verifies:
  - Role-based access control: Non-admin users are strictly rejected with 403 forbidden.
  - Missing/invalid credentials rejected with 401 unauthorized.
  - GET /admin/logs:
      * Newest-first ordering.
      * Filtering by source ('all', 'device', 'server').
      * Limit parameter handling.
      * Actor and resource code serialization.
  - GET /admin/nodes:
      * Online status calculation based on ONLINE_WINDOW_S (45s).
      * Projection of server_seq from sync_state.
  - Seed utility idempotency and safety guards.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.migration_guard import MigrationTargetError
from app.models.access_events import AccessEvent, EventReason, EventSource, EventType
from app.models.nodes import Node, NodeTimeState
from app.models.resources import Resource, ResourceKind
from app.models.sync_state import SyncState
from app.models.users import User, UserRole
from app.seed import seed_database, verify_safe_seed_target

_TEST_JWT_SECRET = "admin-integration-secret-key-32b"

_SQLITE_DDL = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        email       TEXT NOT NULL UNIQUE,
        full_name   TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role        TEXT NOT NULL DEFAULT 'user',
        is_active   INTEGER NOT NULL DEFAULT 1,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS resources (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        code      TEXT NOT NULL UNIQUE,
        name      TEXT NOT NULL,
        kind      TEXT NOT NULL DEFAULT 'physical',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS nodes (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        node_code        TEXT NOT NULL UNIQUE,
        firmware_version TEXT,
        last_seen_at     TEXT,
        time_state       TEXT,
        last_acked_seq   INTEGER NOT NULL DEFAULT 0,
        created_at       TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_state (
        id          INTEGER PRIMARY KEY,
        epoch       TEXT NOT NULL,
        current_seq INTEGER NOT NULL DEFAULT 0
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS access_requests (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL REFERENCES users(id),
        resource_id   INTEGER NOT NULL REFERENCES resources(id),
        start_at      TEXT NOT NULL,
        end_at        TEXT NOT NULL,
        purpose       TEXT,
        status        TEXT NOT NULL DEFAULT 'pending',
        decided_by    INTEGER REFERENCES users(id),
        decided_at    TEXT,
        decision_note TEXT,
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS credentials (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id      INTEGER NOT NULL UNIQUE REFERENCES access_requests(id),
        resource_id     INTEGER NOT NULL REFERENCES resources(id),
        pin_hmac        TEXT NOT NULL,
        pin_encrypted   TEXT NOT NULL,
        valid_from      TEXT NOT NULL,
        valid_until     TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'active',
        change_seq      INTEGER NOT NULL UNIQUE,
        revoke_reason   TEXT,
        consumed_at     TEXT,
        consumed_node_id INTEGER REFERENCES nodes(id),
        revoked_at      TEXT,
        revoked_by      INTEGER REFERENCES users(id),
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS access_events (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id       TEXT NOT NULL UNIQUE,
        source         TEXT NOT NULL,
        event_type     TEXT NOT NULL,
        reason         TEXT,
        node_id        INTEGER REFERENCES nodes(id),
        actor_user_id  INTEGER REFERENCES users(id),
        request_id     INTEGER REFERENCES access_requests(id),
        resource_id    INTEGER REFERENCES resources(id),
        credential_id  INTEGER REFERENCES credentials(id),
        note           TEXT,
        device_time    TEXT,
        time_trusted   INTEGER,
        occurred_at    TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
]


@pytest.fixture
def admin_test_env(monkeypatch):
    """Sets up an in-memory SQLite database and test client with overridden JWT settings."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    with engine.begin() as conn:
        for stmt in _SQLITE_DDL:
            conn.execute(text(stmt))

    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    settings = get_settings()
    monkeypatch.setattr(settings, "JWT_SECRET", _TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "ONLINE_WINDOW_S", 45)
    import app.deps as deps_mod
    monkeypatch.setattr(deps_mod._settings, "JWT_SECRET", _TEST_JWT_SECRET)
    import app.routers.admin as admin_router_mod
    monkeypatch.setattr(admin_router_mod, "_settings", settings)

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    # Seed users: admin and regular user
    with TestingSessionLocal() as session:
        admin_user = User(
            id=1,
            email="admin@demo.local",
            full_name="Demo Admin",
            password_hash="hash",
            role=UserRole.ADMIN.value,
            is_active=True,
        )
        normal_user = User(
            id=2,
            email="user@demo.local",
            full_name="Demo User",
            password_hash="hash",
            role=UserRole.USER.value,
            is_active=True,
        )
        res_a = Resource(
            id=1,
            code="A",
            name="Locker A",
            kind=ResourceKind.PHYSICAL.value,
            is_active=True,
        )
        res_b = Resource(
            id=2,
            code="B",
            name="Locker B",
            kind=ResourceKind.SIMULATED.value,
            is_active=True,
        )
        sync = SyncState(
            id=1,
            epoch="epoch-admin-test-01",
            current_seq=42,
        )
        node_online = Node(
            id=1,
            node_code="node-01",
            firmware_version="0.1.0",
            last_seen_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            time_state=NodeTimeState.SERVER_ANCHORED.value,
            last_acked_seq=40,
        )
        node_offline = Node(
            id=2,
            node_code="node-02",
            firmware_version="0.0.9",
            last_seen_at=datetime.now(timezone.utc) - timedelta(seconds=100),
            time_state=NodeTimeState.RTC_VALIDATED.value,
            last_acked_seq=30,
        )
        session.add_all([admin_user, normal_user, res_a, res_b, sync, node_online, node_offline])
        session.commit()

        # Add audit and telemetry events
        t1 = datetime.now(timezone.utc) - timedelta(minutes=5)
        t2 = datetime.now(timezone.utc) - timedelta(minutes=2)
        ev_server = AccessEvent(
            id=1,
            event_id="srv-00000001",
            source=EventSource.SERVER.value,
            event_type=EventType.CREDENTIAL_ISSUED.value,
            resource_id=res_a.id,
            actor_user_id=admin_user.id,
            occurred_at=t1,
        )
        ev_device = AccessEvent(
            id=2,
            event_id="node-01-000001-a1b2",
            source=EventSource.DEVICE.value,
            event_type=EventType.PIN_REJECTED.value,
            reason=EventReason.WRONG_PIN.value,
            node_id=node_online.id,
            resource_id=res_a.id,
            device_time=t2,
            time_trusted=True,
            occurred_at=t2,
        )
        session.add_all([ev_server, ev_device])
        session.commit()

    client = TestClient(app)

    yield {
        "client": client,
        "engine": engine,
        "SessionLocal": TestingSessionLocal,
    }

    app.dependency_overrides.clear()


def _mint_jwt(user_id: int, role: str) -> str:
    """Helper to generate JWT tokens for test calls."""
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, _TEST_JWT_SECRET, algorithm="HS256")


def test_admin_logs_rbac_and_errors(admin_test_env):
    """GET /admin/logs enforces authentication and admin-only role."""
    client: TestClient = admin_test_env["client"]

    # 1. Missing Authorization header -> 401 unauthorized
    resp_no_auth = client.get("/admin/logs")
    assert resp_no_auth.status_code == 401
    data = resp_no_auth.json()
    assert data["error"]["code"] == "unauthorized"

    # 2. Non-admin user token -> 403 forbidden
    user_token = _mint_jwt(user_id=2, role="user")
    resp_user = client.get(
        "/admin/logs",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp_user.status_code == 403
    data = resp_user.json()
    assert data["error"]["code"] == "forbidden"


def test_admin_logs_query_and_filtering(admin_test_env):
    """GET /admin/logs returns newest-first logs and filters by source."""
    client: TestClient = admin_test_env["client"]
    admin_token = _mint_jwt(user_id=1, role="admin")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Source: all (default)
    resp = client.get("/admin/logs", headers=headers)
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) == 2
    # Verify newest first (id 2 occurred at t2 > id 1 at t1)
    assert logs[0]["id"] == 2
    assert logs[0]["source"] == "device"
    assert logs[0]["actor"] == "node-01"
    assert logs[0]["resource_code"] == "A"
    assert logs[0]["time_trusted"] is True

    assert logs[1]["id"] == 1
    assert logs[1]["source"] == "server"
    assert logs[1]["actor"] == "admin@demo.local"
    assert logs[1]["resource_code"] == "A"
    assert logs[1]["time_trusted"] is None

    # 2. Source: device
    resp_device = client.get("/admin/logs?source=device", headers=headers)
    assert resp_device.status_code == 200
    device_logs = resp_device.json()
    assert len(device_logs) == 1
    assert device_logs[0]["source"] == "device"

    # 3. Source: server
    resp_server = client.get("/admin/logs?source=server", headers=headers)
    assert resp_server.status_code == 200
    server_logs = resp_server.json()
    assert len(server_logs) == 1
    assert server_logs[0]["source"] == "server"

    # 4. Limit parameter
    resp_limit = client.get("/admin/logs?limit=1", headers=headers)
    assert resp_limit.status_code == 200
    assert len(resp_limit.json()) == 1


def test_admin_nodes_endpoint(admin_test_env):
    """GET /admin/nodes returns connectivity status and sequence alignment."""
    client: TestClient = admin_test_env["client"]
    admin_token = _mint_jwt(user_id=1, role="admin")
    user_token = _mint_jwt(user_id=2, role="user")

    # 1. Non-admin forbidden
    resp_user = client.get("/admin/nodes", headers={"Authorization": f"Bearer {user_token}"})
    assert resp_user.status_code == 403

    # 2. Admin success
    resp_admin = client.get("/admin/nodes", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp_admin.status_code == 200
    nodes = resp_admin.json()
    assert len(nodes) == 2

    # Node 1 was seen 10s ago -> online: True
    n1 = next(n for n in nodes if n["node_code"] == "node-01")
    assert n1["online"] is True
    assert n1["server_seq"] == 42
    assert n1["last_acked_seq"] == 40

    # Node 2 was seen 100s ago -> online: False
    n2 = next(n for n in nodes if n["node_code"] == "node-02")
    assert n2["online"] is False
    assert n2["server_seq"] == 42
    assert n2["last_acked_seq"] == 30


def test_seed_utility_idempotency_and_safety(admin_test_env):
    """Test seed_database runs idempotently and safety guard rejects remote databases."""
    SessionLocal = admin_test_env["SessionLocal"]

    with SessionLocal() as session:
        # First call on populated DB
        counts = seed_database(session)
        # Should not duplicate existing records
        assert counts["users"] == 0  # admin & user already exist in fixture
        assert counts["resources"] == 0  # Locker A & B already exist in fixture
        assert counts["nodes"] == 0  # node-01 already exists in fixture
        assert counts["sync_state"] == 0  # sync_state exists in fixture

    # Test safety guard against remote database target
    fake_neon_url = "postgresql+psycopg://neondb_owner:secret@ep-sparkling-salad.c-7.us-east-2.aws.neon.tech/neondb"
    with pytest.raises(MigrationTargetError):
        verify_safe_seed_target(
            type("MockSession", (), {"get_bind": lambda self: type("MockBind", (), {"dialect": type("D", (), {"name": "postgresql"})(), "url": fake_neon_url})()})()
        )
