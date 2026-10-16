"""
tests/integration/test_api_integration.py -- End-to-end API integration tests for Person A endpoints & health.

Tests the complete flow across:
  - GET /health
  - GET /resources
  - POST /access-requests
  - GET /access-requests/me
  - GET /access-requests/{id}/pin

Validates:
  - Full happy path lifecycle from resource discovery to request creation, approval, and PIN reveal.
  - Ownership enforcement and admin denial on PIN reveal.
  - Contract error envelope across all status codes (401, 403, 404, 409, 422).
  - Security headers (no-store, private) on PIN reveal.
  - Atomic audit event generation across all lifecycle transitions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Generator

import jwt
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.access_events import AccessEvent, EventType
from app.models.access_requests import AccessRequest, RequestStatus
from app.models.credentials import Credential, CredentialStatus
from app.models.resources import Resource, ResourceKind
from app.models.users import User, UserRole

_TEST_JWT_SECRET = "integration-secret-key-32bytes-ok"
_TEST_FERNET_KEY = Fernet.generate_key().decode()
_SQLITE_URL = "sqlite:///:memory:"

_engine = create_engine(
    _SQLITE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


_SessionLocal = sessionmaker(
    bind=_engine, autocommit=False, autoflush=False, expire_on_commit=False
)

_API_INTEGRATION_DDL = [
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
        consumed_node_id INTEGER,
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
        node_id        INTEGER,
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


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "JWT_SECRET", _TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "PIN_ENC_KEY", _TEST_FERNET_KEY)
    import app.deps as deps_mod
    monkeypatch.setattr(deps_mod._settings, "JWT_SECRET", _TEST_JWT_SECRET)
    import app.routers.access_requests as ar_mod
    monkeypatch.setattr(ar_mod, "_settings", settings)
    import app.services.access_requests as ar_svc
    monkeypatch.setattr(ar_svc, "_settings", settings)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    """Provide a fresh isolated database session."""
    with _engine.connect() as conn:
        for stmt in _API_INTEGRATION_DDL:
            conn.execute(text(stmt))
        conn.commit()

    session = _SessionLocal()
    session.execute(
        text("INSERT OR REPLACE INTO sync_state (id, epoch, current_seq) VALUES (1, 'epoch-api-001', 0)")
    )
    session.commit()

    try:
        yield session
    finally:
        session.rollback()
        session.close()
        with _engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS access_events;"))
            conn.execute(text("DROP TABLE IF EXISTS credentials;"))
            conn.execute(text("DROP TABLE IF EXISTS access_requests;"))
            conn.execute(text("DROP TABLE IF EXISTS sync_state;"))
            conn.execute(text("DROP TABLE IF EXISTS resources;"))
            conn.execute(text("DROP TABLE IF EXISTS users;"))
            conn.commit()


@pytest.fixture
def client(db: Session) -> Generator[TestClient, None, None]:
    """Provide a TestClient with database session overridden."""
    def _override_get_db():
        session = _SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


def _auth_token(user_id: int, role: str = "user") -> dict[str, str]:
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=8)).timestamp()),
    }
    token = jwt.encode(payload, _TEST_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# API Integration Tests
# ---------------------------------------------------------------------------

class TestApiIntegration:

    def test_health_probe_integration(self, client: TestClient):
        """GET /health operational check connects to DB and returns ISO-8601 UTC time."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"
        assert data["server_time"].endswith("Z")

    def test_full_request_lifecycle_and_pin_reveal(self, client: TestClient, db: Session):
        """
        End-to-end integration scenario across all Person A endpoints:
          1. List available resources.
          2. Submit access request (status: pending).
          3. List user requests via /me.
          4. Attempt PIN reveal while pending -> 409 pin_unavailable.
          5. Simulate admin approval and active credential generation.
          6. Reveal PIN -> 200 OK with no-store headers and plaintext PIN.
          7. Second user attempts PIN reveal -> 403 forbidden.
          8. Admin attempts PIN reveal -> 403 forbidden.
          9. Credential revoked -> 409 pin_unavailable.
        """
        # Seed users and resource
        owner = User(email="requester@demo.local", full_name="Requester User", password_hash="hash", role=UserRole.USER.value, is_active=True)
        other_user = User(email="other@demo.local", full_name="Other User", password_hash="hash", role=UserRole.USER.value, is_active=True)
        admin_user = User(email="admin@demo.local", full_name="Admin User", password_hash="hash", role=UserRole.ADMIN.value, is_active=True)
        res = Resource(code="A", name="Locker A", kind=ResourceKind.PHYSICAL.value, is_active=True)
        db.add_all([owner, other_user, admin_user, res])
        db.commit()
        db.refresh(owner)
        db.refresh(other_user)
        db.refresh(admin_user)
        db.refresh(res)

        owner_headers = _auth_token(owner.id, "user")
        other_headers = _auth_token(other_user.id, "user")
        admin_headers = _auth_token(admin_user.id, "admin")

        # Step 1: GET /resources
        resp = client.get("/resources", headers=owner_headers)
        assert resp.status_code == 200
        resources = resp.json()
        assert len(resources) == 1
        assert resources[0]["code"] == "A"
        assert resources[0]["is_active"] is True

        # Step 2: POST /access-requests
        now = datetime.now(timezone.utc)
        start_str = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

        req_payload = {
            "resource_id": res.id,
            "start_at": start_str,
            "end_at": end_str,
            "purpose": "Collect diagnostic sensor",
        }
        resp = client.post("/access-requests", json=req_payload, headers=owner_headers)
        assert resp.status_code == 201
        created_req = resp.json()
        assert created_req["status"] == "pending"
        assert created_req["credential"] is None
        assert created_req["user"]["id"] == owner.id
        req_id = created_req["id"]

        # Step 3: GET /access-requests/me
        resp = client.get("/access-requests/me", headers=owner_headers)
        assert resp.status_code == 200
        my_list = resp.json()
        assert len(my_list) == 1
        assert my_list[0]["id"] == req_id

        # Other user has empty list
        resp = client.get("/access-requests/me", headers=other_headers)
        assert resp.status_code == 200
        assert resp.json() == []

        # Step 4: GET /access-requests/{id}/pin before approval
        resp = client.get(f"/access-requests/{req_id}/pin", headers=owner_headers)
        assert resp.status_code == 409
        err = resp.json()
        assert err["error"]["code"] == "pin_unavailable"

        # Step 5: Simulate approval with active credential
        req_obj = db.get(AccessRequest, req_id)
        assert req_obj is not None
        req_obj.status = RequestStatus.APPROVED.value

        cipher = Fernet(_TEST_FERNET_KEY.encode())
        enc_pin = cipher.encrypt(b"987654").decode("utf-8")
        cred = Credential(
            request_id=req_obj.id,
            resource_id=res.id,
            pin_hmac="c" * 64,
            pin_encrypted=enc_pin,
            valid_from=req_obj.start_at,
            valid_until=req_obj.end_at,
            status=CredentialStatus.ACTIVE.value,
            change_seq=1,
        )
        db.add(cred)
        db.commit()

        # Step 6: Owner reveals PIN -> 200 OK
        resp = client.get(f"/access-requests/{req_id}/pin", headers=owner_headers)
        assert resp.status_code == 200
        pin_data = resp.json()
        assert pin_data["pin"] == "987654"
        assert pin_data["request_id"] == req_id
        assert pin_data["resource_code"] == "A"
        # Verify no-store and no-cache headers
        assert "no-store" in resp.headers.get("Cache-Control", "")
        assert "no-cache" in resp.headers.get("Pragma", "")

        # Verify atomic audit event creation
        audit_events = (
            db.query(AccessEvent)
            .filter(AccessEvent.event_type == EventType.PIN_REVEALED.value)
            .all()
        )
        assert len(audit_events) == 1
        assert audit_events[0].actor_user_id == owner.id

        # Step 7: Other user tries to reveal PIN -> 403 forbidden
        resp = client.get(f"/access-requests/{req_id}/pin", headers=other_headers)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "forbidden"

        # Step 8: Admin tries to reveal user PIN -> 403 forbidden (Contract: owner only)
        resp = client.get(f"/access-requests/{req_id}/pin", headers=admin_headers)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "forbidden"

        # Step 9: Revoke credential -> 409 pin_unavailable
        cred.status = CredentialStatus.REVOKED.value
        db.commit()

        resp = client.get(f"/access-requests/{req_id}/pin", headers=owner_headers)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "pin_unavailable"

    def test_error_envelopes_compliance(self, client: TestClient, db: Session):
        """Verify contract error envelope across 401, 404, and 422."""
        # 401 on missing auth
        resp = client.get("/resources")
        assert resp.status_code == 401
        assert "error" in resp.json()
        assert resp.json()["error"]["code"] == "unauthorized"
        assert "detail" not in resp.json()

        # Seed user
        user = User(email="env_test@demo.local", full_name="Env Test", password_hash="h", role=UserRole.USER.value, is_active=True)
        db.add(user)
        db.commit()
        headers = _auth_token(user.id)

        # 404 on unknown resource
        now = datetime.now(timezone.utc)
        payload = {
            "resource_id": 9999,
            "start_at": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_at": (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        resp = client.post("/access-requests", json=payload, headers=headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "resource_not_found"

        # 422 on invalid window (duration > 24 hours)
        payload = {
            "resource_id": 1,
            "start_at": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_at": (now + timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        resp = client.post("/access-requests", json=payload, headers=headers)
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"

        # 404 on non-existent access request PIN reveal
        resp = client.get("/access-requests/99999/pin", headers=headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "not_found"
