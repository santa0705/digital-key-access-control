"""
tests/unit/test_device_sync.py -- Unit tests for ESP32 device synchronization endpoint and protocol.

Authoritative contracts:
  - docs/api-contract.md §5.4 (POST /device/v1/sync)
  - docs/credential-policy.md §2.3 (Cryptographic Test Vector 2: X-Server-Signature)
  - docs/credential-policy.md §4 (Transaction Boundaries & Lock Ordering)
  - docs/credential-policy.md §5 (Synchronization Contract & Device Rules DR-1 to DR-8)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.access_events import AccessEvent, EventReason, EventSource, EventType
from app.models.access_requests import AccessRequest
from app.models.credentials import Credential, CredentialStatus
from app.models.nodes import Node
from app.models.resources import Resource
from app.models.sync_state import SyncState
from app.models.users import User
from app.schemas.device import DeviceEventIn, DeviceSyncIn
from app.services.sync import (
    process_device_sync,
    sign_sync_response,
    verify_sync_response_signature,
)
from app.services.time_utils import format_utc_timestamp, now_utc, now_utc_string

settings = get_settings()

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
def test_db_session():
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

    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()

    # Seed baseline fixtures: 1 user, 2 resources (A and B), 1 node ('node-01'), 1 sync_state
    user = User(
        id=1,
        email="demo@demo.local",
        full_name="Demo User",
        password_hash="hash",
        role="user",
        is_active=True,
    )
    res_a = Resource(id=1, code="A", name="Locker A", kind="physical", is_active=True)
    res_b = Resource(id=2, code="B", name="Locker B", kind="physical", is_active=True)
    node = Node(
        id=1,
        node_code="node-01",
        firmware_version="0.1.0",
        time_state="server_anchored",
        last_acked_seq=0,
    )
    sync = SyncState(id=1, epoch="3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411", current_seq=0)

    session.add_all([user, res_a, res_b, node, sync])
    session.commit()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(test_db_session):
    """TestClient overriding get_db dependency with test SQLite database."""
    app.dependency_overrides[get_db] = lambda: test_db_session
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# 1. Cryptographic Test Vector 2 Verification
# ---------------------------------------------------------------------------


def test_sync_response_signature_test_vector_2():
    """
    Verify exact compliance with Cryptographic Test Vector 2 in docs/credential-policy.md §2.3.
    Test key: 'dkac-device-test-key-0001'
    Canonical message: '{"server_time":"2026-10-12T09:15:02Z","request_nonce":"c4b8e21a8f9042b7"}'
    Expected signature: 'c9c1a47b519b81ab2d9423dc9f6d57b379da7d2ef35326212ef9ccba6f972022'
    """
    test_key = "dkac-device-test-key-0001"
    canonical_body = b'{"server_time":"2026-10-12T09:15:02Z","request_nonce":"c4b8e21a8f9042b7"}'
    expected_sig = "c9c1a47b519b81ab2d9423dc9f6d57b379da7d2ef35326212ef9ccba6f972022"

    calculated_sig = sign_sync_response(canonical_body, device_api_key=test_key)
    assert calculated_sig == expected_sig

    assert verify_sync_response_signature(canonical_body, expected_sig, device_api_key=test_key)
    # Altered body must fail
    assert not verify_sync_response_signature(
        b'{"server_time":"2026-10-12T09:15:03Z","request_nonce":"c4b8e21a8f9042b7"}',
        expected_sig,
        device_api_key=test_key,
    )
    # Altered signature must fail
    assert not verify_sync_response_signature(
        canonical_body,
        "0000000000000000000000000000000000000000000000000000000000000000",
        device_api_key=test_key,
    )


# ---------------------------------------------------------------------------
# 2. Authentication & Header Validation (Contract §5.4 & §3.3)
# ---------------------------------------------------------------------------


def test_sync_missing_device_key_returns_401(client):
    """Missing X-Device-Key returns 401 invalid_device_key."""
    headers = {"X-Device-Timestamp": now_utc_string()}
    res = client.post("/device/v1/sync", json={}, headers=headers)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_device_key"


def test_sync_invalid_device_key_returns_401(client):
    """Incorrect X-Device-Key returns 401 invalid_device_key."""
    headers = {
        "X-Device-Key": "wrong-device-key-that-does-not-match",
        "X-Device-Timestamp": now_utc_string(),
    }
    res = client.post("/device/v1/sync", json={}, headers=headers)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_device_key"


def test_sync_missing_device_timestamp_returns_401(client):
    """Missing X-Device-Timestamp returns 401 invalid_device_timestamp."""
    headers = {"X-Device-Key": settings.DEVICE_API_KEY}
    res = client.post("/device/v1/sync", json={}, headers=headers)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_device_timestamp"


def test_sync_skewed_device_timestamp_returns_401(client):
    """X-Device-Timestamp skewed by > 30s returns 401 invalid_device_timestamp."""
    skewed_time = now_utc() - timedelta(seconds=35)
    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": format_utc_timestamp(skewed_time),
    }
    res = client.post("/device/v1/sync", json={}, headers=headers)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_device_timestamp"


def test_sync_malformed_device_timestamp_returns_422(client):
    """Malformed X-Device-Timestamp returns 422 validation_error."""
    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": "2026-10-12T12:00:00.123Z",  # Fractional seconds rejected
    }
    res = client.post("/device/v1/sync", json={}, headers=headers)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# 3. Request Nonce & Schema Validation
# ---------------------------------------------------------------------------


def test_sync_invalid_request_nonce_format_returns_422(client):
    """Request nonce must be exactly 16 lowercase hex characters."""
    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": now_utc_string(),
    }
    # Nonce too short
    payload = {
        "node_code": "node-01",
        "epoch": "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
        "last_seq": 0,
        "request_nonce": "short",
    }
    res = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"

    # Nonce containing non-hex characters
    payload["request_nonce"] = "c4b8e21a8f9042bZ"
    res = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


def test_sync_unknown_node_returns_404(client):
    """Unregistered node_code returns 404 unknown_node."""
    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": now_utc_string(),
    }
    payload = {
        "node_code": "unregistered-terminal-node",
        "epoch": "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
        "last_seq": 0,
        "request_nonce": "c4b8e21a8f9042b7",
    }
    res = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "unknown_node"


# ---------------------------------------------------------------------------
# 4. Successful Sync Protocol, HMAC Signature, and Nonce Echoing
# ---------------------------------------------------------------------------


def test_sync_successful_returns_valid_signature_and_echoes_nonce(client):
    """
    Verify complete success sync response:
      - HTTP 200
      - X-Server-Signature header present and strictly valid
      - request_nonce echoed
      - Server time present and strict ISO-8601 UTC
    """
    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": now_utc_string(),
    }
    nonce = "c4b8e21a8f9042b7"
    payload = {
        "node_code": "node-01",
        "firmware_version": "0.1.0",
        "epoch": "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
        "last_seq": 0,
        "request_nonce": nonce,
        "time_state": "server_anchored",
        "device_time": now_utc_string(),
        "events": [],
    }
    res = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()

    # Echo request nonce
    assert data["request_nonce"] == nonce
    assert data["epoch"] == "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411"
    assert "server_time" in data
    assert data["server_time"].endswith("Z")

    # Verify response body HMAC signature
    sig_header = res.headers.get("X-Server-Signature")
    assert sig_header is not None
    assert len(sig_header) == 64
    assert verify_sync_response_signature(res.content, sig_header, settings.DEVICE_API_KEY)


def test_sync_updates_node_status(client, test_db_session):
    """Verify sync updates Node last_seen_at, firmware_version, time_state, last_acked_seq."""
    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": now_utc_string(),
    }
    payload = {
        "node_code": "node-01",
        "firmware_version": "0.2.1-beta",
        "epoch": "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
        "last_seq": 15,
        "request_nonce": "1234567890abcdef",
        "time_state": "rtc_validated",
    }
    res = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res.status_code == 200

    node = test_db_session.query(Node).filter(Node.node_code == "node-01").first()
    assert node.firmware_version == "0.2.1-beta"
    assert node.time_state == "rtc_validated"
    assert node.last_acked_seq == 15
    assert node.last_seen_at is not None


# ---------------------------------------------------------------------------
# 5. Delta Sync vs Full Resync & Sequence Correctness
# ---------------------------------------------------------------------------


def test_sync_epoch_mismatch_triggers_full_resync(client, test_db_session):
    """
    If terminal sends an epoch that does not match server epoch,
    server orders full_resync=True and sends active credentials snapshot.
    """
    now = now_utc()
    # Create an active credential
    req = AccessRequest(
        user_id=1,
        resource_id=1,
        start_at=now,
        end_at=now + timedelta(hours=1),
        status="approved",
    )
    test_db_session.add(req)
    test_db_session.flush()

    cred = Credential(
        request_id=req.id,
        resource_id=1,
        pin_hmac="e48f878502a47172ea00cf018627956dab95a5073357dc5b01220bc4179093bc",
        pin_encrypted="enc-pin",
        valid_from=now,
        valid_until=now + timedelta(hours=1),
        status="active",
        change_seq=1,
    )
    sync_state = test_db_session.get(SyncState, 1)
    sync_state.current_seq = 1
    test_db_session.add(cred)
    test_db_session.commit()

    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": now_utc_string(),
    }
    # Device sends an unknown / old epoch
    payload = {
        "node_code": "node-01",
        "epoch": "00000000-0000-0000-0000-000000000000",
        "last_seq": 45,
        "request_nonce": "aabbccddeeff0011",
    }
    res = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["full_resync"] is True
    assert data["from_seq"] == 0
    assert data["to_seq"] == 1
    assert data["server_seq"] == 1
    assert len(data["credentials"]) == 1
    assert data["credentials"][0]["id"] == cred.id
    assert data["credentials"][0]["status"] == "active"
    assert data["credentials"][0]["resource_code"] == "A"


def test_sync_device_sequence_ahead_triggers_full_resync(client, test_db_session):
    """If device sends last_seq > server_seq, server triggers full_resync=True."""
    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": now_utc_string(),
    }
    payload = {
        "node_code": "node-01",
        "epoch": "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
        "last_seq": 999,  # Server current_seq is 0
        "request_nonce": "aabbccddeeff0022",
    }
    res = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["full_resync"] is True


def test_sync_delta_mode_returns_monotonic_changes(client, test_db_session):
    """
    In delta mode (epoch matches, last_seq <= server_seq):
    Returns credentials where change_seq > last_seq strictly ascending in (from_seq, to_seq].
    """
    now = now_utc()
    req1 = AccessRequest(
        user_id=1,
        resource_id=1,
        start_at=now,
        end_at=now + timedelta(hours=1),
        status="approved",
    )
    req2 = AccessRequest(
        user_id=1,
        resource_id=2,
        start_at=now,
        end_at=now + timedelta(hours=1),
        status="approved",
    )
    test_db_session.add_all([req1, req2])
    test_db_session.flush()

    cred1 = Credential(
        request_id=req1.id,
        resource_id=1,
        pin_hmac="hmac-1",
        pin_encrypted="enc-1",
        valid_from=now,
        valid_until=now + timedelta(hours=1),
        status="revoked",
        revoke_reason="admin",
        change_seq=43,
    )
    cred2 = Credential(
        request_id=req2.id,
        resource_id=2,
        pin_hmac="hmac-2",
        pin_encrypted="enc-2",
        valid_from=now,
        valid_until=now + timedelta(hours=1),
        status="active",
        change_seq=44,
    )
    sync_state = test_db_session.get(SyncState, 1)
    sync_state.current_seq = 44
    test_db_session.add_all([cred1, cred2])
    test_db_session.commit()

    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": now_utc_string(),
    }
    payload = {
        "node_code": "node-01",
        "epoch": "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
        "last_seq": 42,
        "request_nonce": "aabbccddeeff0033",
    }
    res = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["full_resync"] is False
    assert data["from_seq"] == 42
    assert data["to_seq"] == 44
    assert data["server_seq"] == 44
    assert len(data["credentials"]) == 2
    assert [c["change_seq"] for c in data["credentials"]] == [43, 44]
    assert data["credentials"][0]["status"] == "revoked"
    assert data["credentials"][1]["status"] == "active"


def test_sync_delta_mode_no_changes(client):
    """When last_seq == server_seq, returns from_seq == to_seq == last_seq, credentials=[]."""
    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": now_utc_string(),
    }
    payload = {
        "node_code": "node-01",
        "epoch": "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
        "last_seq": 0,
        "request_nonce": "aabbccddeeff0044",
    }
    res = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["full_resync"] is False
    assert data["from_seq"] == 0
    assert data["to_seq"] == 0
    assert data["credentials"] == []
    assert data["has_more"] is False


# ---------------------------------------------------------------------------
# 6. Telemetry Event Ingestion, Deduplication, & Stale Epoch Handling
# ---------------------------------------------------------------------------


def test_sync_ingests_telemetry_events_and_acks(client, test_db_session):
    """Telemetry events are durably inserted and their event_ids returned in acked_event_ids."""
    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": now_utc_string(),
    }
    event_id = "node-01-000101-a1b2c3d4"
    payload = {
        "node_code": "node-01",
        "epoch": "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
        "last_seq": 0,
        "request_nonce": "aabbccddeeff0055",
        "events": [
            {
                "event_id": event_id,
                "event_type": "pin_rejected",
                "reason": "wrong_pin",
                "resource_code": "A",
                "credential_id": None,
                "device_time": now_utc_string(),
                "time_trusted": True,
            }
        ],
    }
    res = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert event_id in data["acked_event_ids"]

    # Assert persisted in access_events
    ev = test_db_session.query(AccessEvent).filter(AccessEvent.event_id == event_id).first()
    assert ev is not None
    assert ev.source == "device"
    assert ev.event_type == "pin_rejected"
    assert ev.reason == "wrong_pin"
    assert ev.resource_id == 1
    assert ev.time_trusted is True


def test_sync_event_deduplication(client, test_db_session):
    """Duplicate event submissions do not duplicate rows in database and are safely acknowledged."""
    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": now_utc_string(),
    }
    event_id = "node-01-000102-duplicate1"
    event_payload = {
        "event_id": event_id,
        "event_type": "unlock_command_issued",
        "reason": None,
        "resource_code": "A",
        "credential_id": None,
        "device_time": now_utc_string(),
        "time_trusted": True,
    }
    payload = {
        "node_code": "node-01",
        "epoch": "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
        "last_seq": 0,
        "request_nonce": "aabbccddeeff0066",
        "events": [event_payload],
    }
    # First sync
    res1 = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res1.status_code == 200
    assert event_id in res1.json()["acked_event_ids"]

    # Second sync with same event (retry over network)
    payload["request_nonce"] = "aabbccddeeff0067"
    res2 = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res2.status_code == 200
    assert event_id in res2.json()["acked_event_ids"]

    # Exactly 1 row in DB
    count = test_db_session.query(AccessEvent).filter(AccessEvent.event_id == event_id).count()
    assert count == 1


def test_sync_stale_epoch_unknown_credential_handling(client, test_db_session):
    """
    Contract §5.4: If an event carries a credential_id that does not exist in DB (e.g. from
    prior epoch), it is inserted with credential_id = NULL and note = 'unknown_credential'.
    """
    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": now_utc_string(),
    }
    event_id = "node-01-000103-stalecred"
    payload = {
        "node_code": "node-01",
        "epoch": "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
        "last_seq": 0,
        "request_nonce": "aabbccddeeff0077",
        "events": [
            {
                "event_id": event_id,
                "event_type": "pin_rejected",
                "reason": "expired",
                "resource_code": "A",
                "credential_id": 99999,  # Does not exist
                "device_time": now_utc_string(),
                "time_trusted": True,
            }
        ],
    }
    res = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res.status_code == 200
    assert event_id in res.json()["acked_event_ids"]

    ev = test_db_session.query(AccessEvent).filter(AccessEvent.event_id == event_id).first()
    assert ev is not None
    assert ev.credential_id is None
    assert ev.note == "unknown_credential"


def test_sync_credential_accepted_transitions_to_consumed(client, test_db_session):
    """
    When credential_accepted is received for an active credential:
      - Credential transitions to 'consumed'
      - consumed_at and consumed_node_id are set
      - change_seq is monotonically incremented
      - 'credential_consumed' server audit event is recorded
    """
    now = now_utc()
    req = AccessRequest(
        user_id=1,
        resource_id=1,
        start_at=now,
        end_at=now + timedelta(hours=1),
        status="approved",
    )
    test_db_session.add(req)
    test_db_session.flush()

    cred = Credential(
        request_id=req.id,
        resource_id=1,
        pin_hmac="hmac-consume-test",
        pin_encrypted="enc-pin",
        valid_from=now,
        valid_until=now + timedelta(hours=1),
        status="active",
        change_seq=1,
    )
    sync_state = test_db_session.get(SyncState, 1)
    sync_state.current_seq = 1
    test_db_session.add(cred)
    test_db_session.commit()

    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": now_utc_string(),
    }
    event_id = "node-01-000104-acceptcred"
    payload = {
        "node_code": "node-01",
        "epoch": "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
        "last_seq": 1,
        "request_nonce": "aabbccddeeff0088",
        "events": [
            {
                "event_id": event_id,
                "event_type": "credential_accepted",
                "reason": None,
                "resource_code": "A",
                "credential_id": cred.id,
                "device_time": now_utc_string(),
                "time_trusted": True,
            }
        ],
    }
    res = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res.status_code == 200

    test_db_session.refresh(cred)
    assert cred.status == CredentialStatus.CONSUMED.value
    assert cred.consumed_node_id == 1
    assert cred.consumed_at is not None
    assert cred.change_seq == 2

    # Verify server audit log
    audit_ev = (
        test_db_session.query(AccessEvent)
        .filter(AccessEvent.event_type == EventType.CREDENTIAL_CONSUMED.value)
        .first()
    )
    assert audit_ev is not None
    assert audit_ev.credential_id == cred.id
    assert audit_ev.source == "server"


# ---------------------------------------------------------------------------
# 7. Fail-Closed Error Scenarios & Inconsistency
# ---------------------------------------------------------------------------


def test_sync_state_inconsistent_returns_503(client, test_db_session):
    """
    Contract §3.3: If sync_state.current_seq < max(credentials.change_seq),
    raises 503 sync_state_inconsistent.
    """
    now = now_utc()
    req = AccessRequest(
        user_id=1,
        resource_id=1,
        start_at=now,
        end_at=now + timedelta(hours=1),
        status="approved",
    )
    test_db_session.add(req)
    test_db_session.flush()

    cred = Credential(
        request_id=req.id,
        resource_id=1,
        pin_hmac="hmac-inconsistent",
        pin_encrypted="enc",
        valid_from=now,
        valid_until=now + timedelta(hours=1),
        status="active",
        change_seq=50,  # change_seq is 50
    )
    sync_state = test_db_session.get(SyncState, 1)
    sync_state.current_seq = 10  # current_seq is 10 < 50 (inconsistent!)
    test_db_session.add(cred)
    test_db_session.commit()

    headers = {
        "X-Device-Key": settings.DEVICE_API_KEY,
        "X-Device-Timestamp": now_utc_string(),
    }
    payload = {
        "node_code": "node-01",
        "epoch": "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
        "last_seq": 10,
        "request_nonce": "aabbccddeeff0099",
    }
    res = client.post("/device/v1/sync", json=payload, headers=headers)
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "sync_state_inconsistent"


def test_sync_transaction_rollback_preserves_fail_closed(test_db_session, monkeypatch):
    """
    If a database error occurs during event processing, the transaction rolls back,
    and uncommitted events are never acknowledged.
    """
    event_id = "node-01-000105-failclosed"
    payload = DeviceSyncIn(
        node_code="node-01",
        epoch="3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
        last_seq=0,
        request_nonce="aabbccddeeff00aa",
        events=[
            DeviceEventIn(
                event_id=event_id,
                event_type="pin_rejected",
                reason="wrong_pin",
                resource_code="A",
                credential_id=None,
                time_trusted=True,
            )
        ],
    )

    # Force an exception on db.commit
    def failing_commit():
        raise RuntimeError("Simulated database failure during commit")

    monkeypatch.setattr(test_db_session, "commit", failing_commit)

    with pytest.raises(RuntimeError):
        process_device_sync(test_db_session, payload)

    # Ensure event was not saved
    ev = test_db_session.query(AccessEvent).filter(AccessEvent.event_id == event_id).first()
    assert ev is None
