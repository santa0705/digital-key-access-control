"""
tests/unit/test_events.py -- Unit tests for telemetry and audit event service.

Verifies:
  - Event validation rules and check constraint parity (sources, types, reasons, time_trusted).
  - Server audit events emission (canonical 'srv-<hex>' ID format, time_trusted=None).
  - Idempotent device event ingestion (duplicate event_ids safely ignored).
  - Stale/unknown credential handling (sets credential_id=None, note='unknown_credential').
  - Credential consumption on credential_accepted event (active -> consumed with monotonic change_seq).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.access_events import AccessEvent, EventReason, EventSource, EventType
from app.models.access_requests import AccessRequest, RequestStatus
from app.models.credentials import Credential, CredentialStatus
from app.models.nodes import Node
from app.models.resources import Resource
from app.models.sync_state import SyncState
from app.models.users import User, UserRole
from app.services.events import (
    generate_server_event_id,
    ingest_device_event,
    record_pin_revealed,
    record_request_created,
    record_server_event,
    validate_event_fields,
)

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
def db_session():
    """In-memory SQLite session with foreign keys enabled."""
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

    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()

    # Create sync_state singleton
    sync = SyncState(id=1, epoch="epoch-unit-test-1", current_seq=10)
    session.add(sync)

    # Create dummy user, resource, request, credential, node
    user = User(
        email="user@test.local",
        full_name="Test User",
        password_hash="hash",
        role=UserRole.USER.value,
    )
    res = Resource(code="A", name="Locker A", kind="physical")
    node = Node(node_code="node-01", firmware_version="0.1.0")
    session.add_all([user, res, node])
    session.flush()

    now = datetime.now(timezone.utc)
    req = AccessRequest(
        user_id=user.id,
        resource_id=res.id,
        start_at=now,
        end_at=now + timedelta(hours=1),
        status=RequestStatus.APPROVED.value,
    )
    session.add(req)
    session.flush()

    cred = Credential(
        request_id=req.id,
        resource_id=res.id,
        pin_hmac="hmac_test_vec",
        pin_encrypted="enc_test_vec",
        valid_from=now,
        valid_until=now + timedelta(hours=1),
        status=CredentialStatus.ACTIVE.value,
        change_seq=10,
    )
    session.add(cred)
    session.commit()

    yield session

    session.close()


def test_validate_event_fields():
    """Field validation enforces check constraints."""
    # Valid server event
    validate_event_fields(
        source=EventSource.SERVER.value,
        event_type=EventType.REQUEST_CREATED.value,
    )

    # Valid device event
    validate_event_fields(
        source=EventSource.DEVICE.value,
        event_type=EventType.PIN_REJECTED.value,
        reason=EventReason.WRONG_PIN.value,
        time_trusted=True,
    )

    # Invalid source
    with pytest.raises(ValueError, match="Invalid event source"):
        validate_event_fields(
            source="unknown_source",
            event_type=EventType.PIN_REJECTED.value,
            time_trusted=True,
        )

    # Invalid event_type
    with pytest.raises(ValueError, match="Invalid event_type"):
        validate_event_fields(
            source=EventSource.DEVICE.value,
            event_type="invalid_event_type",
            time_trusted=True,
        )

    # Invalid reason
    with pytest.raises(ValueError, match="Invalid event reason"):
        validate_event_fields(
            source=EventSource.DEVICE.value,
            event_type=EventType.PIN_REJECTED.value,
            reason="invalid_reason",
            time_trusted=True,
        )

    # Device event missing time_trusted violates check constraint
    with pytest.raises(ValueError, match="time_trusted"):
        validate_event_fields(
            source=EventSource.DEVICE.value,
            event_type=EventType.PIN_REJECTED.value,
            time_trusted=None,
        )


def test_server_event_generation(db_session):
    """Server events emit canonical ID, source='server', and time_trusted=None."""
    server_id = generate_server_event_id()
    assert server_id.startswith("srv-")
    assert len(server_id) == 12  # 'srv-' + 8 hex chars

    req = db_session.query(AccessRequest).first()
    user = db_session.query(User).first()

    event = record_request_created(db_session, request=req, actor_user_id=user.id)
    db_session.commit()

    assert event.id is not None
    assert event.source == EventSource.SERVER.value
    assert event.event_type == EventType.REQUEST_CREATED.value
    assert event.time_trusted is None
    assert event.request_id == req.id
    assert event.actor_user_id == user.id


def test_ingest_device_event_idempotency(db_session):
    """Device events are ingested idempotently; duplicate event_id is safely ignored."""
    node = db_session.query(Node).first()
    res = db_session.query(Resource).first()
    now = datetime.now(timezone.utc)

    # First ingestion succeeds
    ev1 = ingest_device_event(
        db_session,
        event_id="node-01-000001-a1b2c3d4",
        event_type=EventType.PIN_REJECTED.value,
        device_time=now,
        time_trusted=True,
        resource_id=res.id,
        node_id=node.id,
        reason=EventReason.WRONG_PIN.value,
    )
    db_session.commit()
    assert ev1 is not None
    assert ev1.event_id == "node-01-000001-a1b2c3d4"

    # Second ingestion with same event_id returns None (idempotent duplicate)
    ev2 = ingest_device_event(
        db_session,
        event_id="node-01-000001-a1b2c3d4",
        event_type=EventType.PIN_REJECTED.value,
        device_time=now,
        time_trusted=True,
        resource_id=res.id,
        node_id=node.id,
        reason=EventReason.WRONG_PIN.value,
    )
    assert ev2 is None

    # Total rows in DB is still 1
    count = db_session.query(AccessEvent).filter(AccessEvent.event_id == "node-01-000001-a1b2c3d4").count()
    assert count == 1


def test_ingest_device_event_unknown_credential(db_session):
    """Events referencing a non-existent credential set credential_id=None and note='unknown_credential'."""
    node = db_session.query(Node).first()
    res = db_session.query(Resource).first()
    now = datetime.now(timezone.utc)

    ev = ingest_device_event(
        db_session,
        event_id="node-01-000002-unknown-cred",
        event_type=EventType.PIN_REJECTED.value,
        device_time=now,
        time_trusted=True,
        resource_id=res.id,
        node_id=node.id,
        credential_id=999999,  # Non-existent
        reason=EventReason.EXPIRED.value,
        note="device note",
    )
    db_session.commit()

    assert ev is not None
    assert ev.credential_id is None
    assert "unknown_credential" in (ev.note or "")
    assert "device note" in (ev.note or "")


def test_ingest_device_event_credential_consumption(db_session):
    """Ingesting credential_accepted transitions an active credential to consumed with new change_seq."""
    node = db_session.query(Node).first()
    res = db_session.query(Resource).first()
    cred = db_session.query(Credential).first()
    assert cred.status == CredentialStatus.ACTIVE.value
    old_seq = cred.change_seq

    now = datetime.now(timezone.utc)
    ev = ingest_device_event(
        db_session,
        event_id="node-01-000003-consume",
        event_type=EventType.CREDENTIAL_ACCEPTED.value,
        device_time=now,
        time_trusted=True,
        resource_id=res.id,
        node_id=node.id,
        credential_id=cred.id,
    )
    db_session.commit()

    assert ev is not None
    assert cred.status == CredentialStatus.CONSUMED.value
    assert cred.consumed_at is not None
    assert cred.consumed_node_id == node.id
    assert cred.change_seq > old_seq
