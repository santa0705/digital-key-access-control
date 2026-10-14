"""
backend/app/services/access_requests.py -- Access request service layer.

Implements Person A's business logic for:
  - Contract 5.2 & Policy 4.1: Access request lifecycle.
  - Validation: start_at / end_at window checks, resource existence, authenticated user ownership.
  - Transaction boundaries: atomic request creation + audit event emission.
  - PIN retrieval: owner verification, active credential status check, Fernet decryption,
    atomic 'pin_revealed' audit logging.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.errors import (
    err_forbidden,
    err_not_found,
    err_pin_unavailable,
    err_resource_not_found,
    err_validation,
)
from app.models.access_requests import AccessRequest, RequestStatus
from app.models.credentials import CredentialStatus
from app.models.resources import Resource
from app.models.users import User
from app.schemas.access_requests import AccessRequestCreate
from app.services.events import record_pin_revealed, record_request_created

_settings = get_settings()


def load_request_with_relations(db: Session, request_id: int) -> Optional[AccessRequest]:
    """Load an AccessRequest with all relations needed for serialisation."""
    return (
        db.query(AccessRequest)
        .options(
            joinedload(AccessRequest.resource),
            joinedload(AccessRequest.user),
            joinedload(AccessRequest.credential),
        )
        .filter(AccessRequest.id == request_id)
        .first()
    )


def create_access_request(
    db: Session,
    user: User,
    body: AccessRequestCreate,
) -> AccessRequest:
    """
    Submit a new access request for a resource.

    Enforces:
      - start_at is not more than 1 minute in the past (server UTC).
      - resource_id exists in the database.
      - Atomicity: Creates the AccessRequest and 'request_created' audit event
        within the same database transaction. Rolls back on any failure.

    Returns:
      The created AccessRequest ORM instance with relations loaded.
    """
    now_utc = datetime.now(timezone.utc)
    start_dt = body.parsed_start()

    if start_dt < (now_utc - timedelta(minutes=1)):
        raise err_validation(
            "start_at cannot be more than 1 minute in the past relative to server UTC."
        )

    end_dt = body.parsed_end()

    # Verify target resource exists
    resource = db.get(Resource, body.resource_id)
    if resource is None:
        raise err_resource_not_found(
            f"Resource with id {body.resource_id} does not exist."
        )

    try:
        req = AccessRequest(
            user_id=user.id,
            resource_id=resource.id,
            start_at=start_dt,
            end_at=end_dt,
            purpose=body.purpose,
            status=RequestStatus.PENDING.value,
        )
        db.add(req)
        db.flush()  # obtain req.id for audit event linking

        # Atomically record audit event
        record_request_created(db=db, request=req, actor_user_id=user.id)
        db.commit()
    except Exception:
        db.rollback()
        raise

    # Reload with relations for serialisation
    return load_request_with_relations(db, req.id)  # type: ignore[return-value]


def get_user_access_requests(db: Session, user_id: int) -> list[AccessRequest]:
    """
    Return all access requests submitted by the calling user, newest first.
    Returns [] when none exist.
    """
    return (
        db.query(AccessRequest)
        .options(
            joinedload(AccessRequest.resource),
            joinedload(AccessRequest.user),
            joinedload(AccessRequest.credential),
        )
        .filter(AccessRequest.user_id == user_id)
        .order_by(AccessRequest.created_at.desc())
        .all()
    )


def get_access_request_for_owner(
    db: Session,
    request_id: int,
    user_id: int,
) -> AccessRequest:
    """
    Retrieve an AccessRequest, enforcing that user_id is the creator.

    Raises:
      - 404 not_found if request does not exist.
      - 403 forbidden if user is not the creator of the request.
    """
    req = load_request_with_relations(db, request_id)
    if req is None:
        raise err_not_found(f"Access request {request_id} does not exist.")

    if req.user_id != user_id:
        raise err_forbidden(
            "Only the request creator may retrieve the PIN for this request."
        )

    return req


def decrypt_pin(pin_encrypted: str, enc_key: Optional[str] = None) -> str:
    """Decrypt a Fernet-encrypted PIN using the configured PIN_ENC_KEY."""
    if enc_key is None:
        import app.routers.access_requests as ar_mod
        if hasattr(ar_mod, "_settings") and getattr(ar_mod._settings, "PIN_ENC_KEY", None):
            enc_key = ar_mod._settings.PIN_ENC_KEY
        else:
            enc_key = get_settings().PIN_ENC_KEY
    cipher = Fernet(enc_key.encode())
    try:
        return cipher.decrypt(pin_encrypted.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception) as exc:
        raise err_pin_unavailable("PIN decryption failed; credential may be corrupted.") from exc


def reveal_pin_for_owner(
    db: Session,
    user: User,
    request_id: int,
) -> Tuple[AccessRequest, str]:
    """
    Verify ownership and credential status, decrypt PIN, and record audit event.

    Enforces:
      - Only creator can access (admins/other users receive 403).
      - Credential must be in 'active' status.
      - Atomically records 'pin_revealed' audit event before returning PIN.
      - Transaction rollback ensures no audit event if decryption fails.

    Returns:
      Tuple of (AccessRequest, plaintext_pin).
    """
    req = get_access_request_for_owner(db, request_id, user.id)

    cred = req.credential
    if cred is None or cred.status != CredentialStatus.ACTIVE.value:
        if cred is None:
            msg = (
                f"Access request {request_id} has no associated credential "
                f"(status: {req.status})."
            )
        else:
            msg = (
                f"PIN is not available: credential {cred.id} is in terminal "
                f"state '{cred.status}'."
            )
        raise err_pin_unavailable(msg)

    # Decrypt plain PIN
    plain_pin = decrypt_pin(cred.pin_encrypted)

    # Atomically record audit event
    try:
        record_pin_revealed(
            db=db,
            request=req,
            credential_id=cred.id,
            actor_user_id=user.id,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return req, plain_pin
