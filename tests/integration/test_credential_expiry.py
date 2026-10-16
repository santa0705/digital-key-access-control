"""
tests/integration/test_credential_expiry.py -- Regression tests for Credential Expiry Lifecycle & Enforcement.

Verifies:
  1. PIN retrieval before, during, exactly at, and after expiry.
  2. Strict 409 pin_unavailable rejection on expired credentials.
  3. Ownership and authorization protections preserved.
  4. CredentialSummary API dynamic effective status ('expired', 'active', 'revoked', 'consumed').
  5. Policy-consistent Expiry Sweep during admin approval (unblocking Rule R1).
  6. Change sequence monotonic advance on expiry transitions.
  7. Terminal status immutability.
"""
from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

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
from app.models.credentials import Credential, CredentialStatus, RevokeReason
from app.models.resources import Resource, ResourceKind
from app.models.sync_state import SyncState
from app.models.users import User, UserRole
from app.services.credentials import sweep_expired_credentials
from tests.integration.test_api_integration import _API_INTEGRATION_DDL

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
    import app.routers.admin as admin_mod
    monkeypatch.setattr(admin_mod, "_settings", settings)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    with _engine.connect() as conn:
        for stmt in _API_INTEGRATION_DDL:
            conn.execute(text(stmt))
        conn.commit()

    session = _SessionLocal()
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
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _mint_jwt(user_id: int, role: str) -> str:
    import jwt
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, _TEST_JWT_SECRET, algorithm="HS256")


class TestCredentialExpiryEnforcement:
    def test_pin_retrieval_at_and_after_expiry(self, client: TestClient, db: Session):
        """Verify PIN retrieval is accepted before expiry and rejected at/after expiry."""
        # 1. Setup resource, sync_state, owner and non-owner
        owner = User(
            email="owner@test.local",
            full_name="Owner User",
            password_hash="hash",
            role=UserRole.USER.value,
        )
        other = User(
            email="other@test.local",
            full_name="Other User",
            password_hash="hash",
            role=UserRole.USER.value,
        )
        res = Resource(code="A", name="Locker A", kind=ResourceKind.PHYSICAL.value)
        sync = SyncState(id=1, epoch="epoch-test", current_seq=1)
        db.add_all([owner, other, res, sync])
        db.commit()

        owner_headers = {"Authorization": f"Bearer {_mint_jwt(owner.id, 'user')}"}
        other_headers = {"Authorization": f"Bearer {_mint_jwt(other.id, 'user')}"}

        # 2. Create access request and active credential
        cipher = Fernet(_TEST_FERNET_KEY.encode())
        enc_pin = cipher.encrypt(b"654321").decode("utf-8")

        now = datetime.now(timezone.utc)
        req = AccessRequest(
            user_id=owner.id,
            resource_id=res.id,
            start_at=now - timedelta(minutes=30),
            end_at=now + timedelta(minutes=30),
            status=RequestStatus.APPROVED.value,
        )
        db.add(req)
        db.commit()

        cred = Credential(
            request_id=req.id,
            resource_id=res.id,
            pin_hmac="a" * 64,
            pin_encrypted=enc_pin,
            valid_from=now - timedelta(minutes=30),
            valid_until=now + timedelta(minutes=30),
            status=CredentialStatus.ACTIVE.value,
            change_seq=10,
        )
        db.add(cred)
        db.commit()

        # Case 1: Within window -> 200 OK
        resp = client.get(f"/access-requests/{req.id}/pin", headers=owner_headers)
        assert resp.status_code == 200
        assert resp.json()["pin"] == "654321"

        # Case 2: Other user -> 403 Forbidden
        resp_other = client.get(f"/access-requests/{req.id}/pin", headers=other_headers)
        assert resp_other.status_code == 403
        assert resp_other.json()["error"]["code"] == "forbidden"

        # Case 3: Exactly at expiry -> 409 pin_unavailable
        cred.valid_until = datetime.now(timezone.utc)
        db.commit()

        resp_exact = client.get(f"/access-requests/{req.id}/pin", headers=owner_headers)
        assert resp_exact.status_code == 409
        err_exact = resp_exact.json()
        assert err_exact["error"]["code"] == "pin_unavailable"
        assert "expired" in err_exact["error"]["message"].lower()

        # Case 4: After expiry -> 409 pin_unavailable
        cred.valid_until = datetime.now(timezone.utc) - timedelta(minutes=10)
        db.commit()

        resp_past = client.get(f"/access-requests/{req.id}/pin", headers=owner_headers)
        assert resp_past.status_code == 409
        err_past = resp_past.json()
        assert err_past["error"]["code"] == "pin_unavailable"
        assert "expired" in err_past["error"]["message"].lower()

    def test_api_effective_status_derivation(self, client: TestClient, db: Session):
        """Verify CredentialSummary serializes expired status for active rows past valid_until."""
        user = User(
            email="u@test.local",
            full_name="User",
            password_hash="hash",
            role=UserRole.USER.value,
        )
        res = Resource(code="A", name="Locker A", kind=ResourceKind.PHYSICAL.value)
        sync = SyncState(id=1, epoch="epoch-test", current_seq=1)
        db.add_all([user, res, sync])
        db.commit()

        now = datetime.now(timezone.utc)
        cipher = Fernet(_TEST_FERNET_KEY.encode())

        # 1. Expired credential (status='active' in DB, valid_until in past)
        req_exp = AccessRequest(
            user_id=user.id,
            resource_id=res.id,
            start_at=now - timedelta(hours=2),
            end_at=now - timedelta(hours=1),
            status=RequestStatus.APPROVED.value,
        )
        db.add(req_exp)
        db.commit()

        cred_exp = Credential(
            request_id=req_exp.id,
            resource_id=res.id,
            pin_hmac="1" * 64,
            pin_encrypted=cipher.encrypt(b"111111").decode(),
            valid_from=now - timedelta(hours=2),
            valid_until=now - timedelta(hours=1),
            status=CredentialStatus.ACTIVE.value,
            change_seq=2,
        )
        db.add(cred_exp)
        db.commit()

        # Call GET /access-requests/me
        headers = {"Authorization": f"Bearer {_mint_jwt(user.id, 'user')}"}
        resp = client.get("/access-requests/me", headers=headers)
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["credential"]["status"] == "expired"
        assert items[0]["credential"]["id"] == cred_exp.id

    def test_r1_approval_after_previous_credential_expires(self, client: TestClient, db: Session):
        """Verify that an expired active credential is automatically swept and does NOT block new approval."""
        admin = User(
            email="admin@test.local",
            full_name="Admin",
            password_hash="hash",
            role=UserRole.ADMIN.value,
        )
        user = User(
            email="user@test.local",
            full_name="User",
            password_hash="hash",
            role=UserRole.USER.value,
        )
        res = Resource(code="A", name="Locker A", kind=ResourceKind.PHYSICAL.value)
        sync = SyncState(id=1, epoch="epoch-test", current_seq=5)
        db.add_all([admin, user, res, sync])
        db.commit()

        now = datetime.now(timezone.utc)
        cipher = Fernet(_TEST_FERNET_KEY.encode())

        # Old request and expired active credential
        old_req = AccessRequest(
            user_id=user.id,
            resource_id=res.id,
            start_at=now - timedelta(hours=2),
            end_at=now - timedelta(minutes=15),
            status=RequestStatus.APPROVED.value,
        )
        db.add(old_req)
        db.commit()

        old_cred = Credential(
            request_id=old_req.id,
            resource_id=res.id,
            pin_hmac="a" * 64,
            pin_encrypted=cipher.encrypt(b"111111").decode(),
            valid_from=now - timedelta(hours=2),
            valid_until=now - timedelta(minutes=15),
            status=CredentialStatus.ACTIVE.value,
            change_seq=5,
        )
        db.add(old_cred)
        db.commit()

        # New pending request for the same resource
        new_req = AccessRequest(
            user_id=user.id,
            resource_id=res.id,
            start_at=now,
            end_at=now + timedelta(hours=1),
            status=RequestStatus.PENDING.value,
        )
        db.add(new_req)
        db.commit()

        admin_headers = {"Authorization": f"Bearer {_mint_jwt(admin.id, 'admin')}"}

        # Approve WITHOUT replace_existing. Must succeed because old credential has expired!
        resp = client.post(
            f"/admin/access-requests/{new_req.id}/approve",
            json={"replace_existing": False, "note": "Approved after expiry"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["credential"]["status"] == "active"

        # Verify old credential was swept to expired in the DB
        db.refresh(old_cred)
        assert old_cred.status == CredentialStatus.EXPIRED.value
        assert old_cred.change_seq == 6  # incremented by sweep

        # Verify new credential has higher sequence
        new_cred_id = data["credential"]["id"]
        new_cred = db.get(Credential, new_cred_id)
        assert new_cred.change_seq == 7  # incremented by issue

        # Verify audit event for credential_expired was recorded
        expired_events = (
            db.query(AccessEvent)
            .filter(AccessEvent.event_type == EventType.CREDENTIAL_EXPIRED.value)
            .all()
        )
        assert len(expired_events) == 1
        assert expired_events[0].credential_id == old_cred.id

    def test_terminal_statuses_preserved(self, db: Session):
        """Verify that revoked and consumed credentials are never mutated by the sweep."""
        res = Resource(code="A", name="Locker A", kind=ResourceKind.PHYSICAL.value)
        sync = SyncState(id=1, epoch="epoch-test", current_seq=1)
        user = User(email="u@test.local", full_name="User", password_hash="h", role="user")
        db.add_all([res, sync, user])
        db.commit()

        now = datetime.now(timezone.utc)
        r1 = AccessRequest(user_id=user.id, resource_id=res.id, start_at=now - timedelta(hours=2), end_at=now - timedelta(hours=1))
        r2 = AccessRequest(user_id=user.id, resource_id=res.id, start_at=now - timedelta(hours=2), end_at=now - timedelta(hours=1))
        db.add_all([r1, r2])
        db.commit()

        c_rev = Credential(
            request_id=r1.id,
            resource_id=res.id,
            pin_hmac="1" * 64,
            pin_encrypted="enc",
            valid_from=now - timedelta(hours=2),
            valid_until=now - timedelta(hours=1),
            status=CredentialStatus.REVOKED.value,
            revoke_reason=RevokeReason.ADMIN.value,
            change_seq=2,
        )
        c_con = Credential(
            request_id=r2.id,
            resource_id=res.id,
            pin_hmac="2" * 64,
            pin_encrypted="enc",
            valid_from=now - timedelta(hours=2),
            valid_until=now - timedelta(hours=1),
            status=CredentialStatus.CONSUMED.value,
            change_seq=3,
        )
        db.add_all([c_rev, c_con])
        db.commit()

        # Run sweep
        swept = sweep_expired_credentials(db)
        assert len(swept) == 0

        db.refresh(c_rev)
        db.refresh(c_con)
        assert c_rev.status == CredentialStatus.REVOKED.value
        assert c_con.status == CredentialStatus.CONSUMED.value
