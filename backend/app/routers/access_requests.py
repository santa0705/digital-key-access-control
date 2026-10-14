"""
routers/access_requests.py -- Person A access-request endpoints.

Implements:
  POST /access-requests        (Contract 5.2)
  GET  /access-requests/me     (Contract 5.2)
  GET  /access-requests/{id}/pin (Contract 5.2)

HTTP concerns handled here:
  - Route routing, tags, and status codes.
  - Authentication dependency (get_current_user).
  - Cache headers on PIN response (Cache-Control: no-store, private; Pragma: no-cache).
  - Serialization into Pydantic output schemas.

All business logic, database transactions, entity validation, and atomic audit logging
are delegated to app.services.access_requests.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models.users import User
from app.schemas.access_requests import (
    AccessRequestCreate,
    AccessRequestOut,
    PinRevealOut,
    _fmt_utc_z,
)
from app.services import access_requests as access_requests_service

router = APIRouter(tags=["Access Requests"])
_settings = get_settings()


# ---------------------------------------------------------------------------
# POST /access-requests
# ---------------------------------------------------------------------------

@router.post(
    "/access-requests",
    response_model=AccessRequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create access request",
)
def create_access_request(
    body: AccessRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AccessRequestOut:
    """
    POST /access-requests

    Submit a new access request for a resource.  Returns the created
    AccessRequest with status 'pending' and credential null.
    """
    req = access_requests_service.create_access_request(
        db=db,
        user=current_user,
        body=body,
    )
    return AccessRequestOut.from_orm_obj(req)


# ---------------------------------------------------------------------------
# GET /access-requests/me
# ---------------------------------------------------------------------------
# NOTE: This route MUST be declared BEFORE /access-requests/{id}/pin so that
#       FastAPI does not try to match the literal "me" as an integer id.

@router.get(
    "/access-requests/me",
    response_model=list[AccessRequestOut],
    summary="List my access requests",
)
def list_my_access_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AccessRequestOut]:
    """
    GET /access-requests/me

    Return all access requests submitted by the calling user, newest first.
    Returns [] when none exist.
    """
    rows = access_requests_service.get_user_access_requests(
        db=db,
        user_id=current_user.id,
    )
    return [AccessRequestOut.from_orm_obj(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /access-requests/{id}/pin
# ---------------------------------------------------------------------------

@router.get(
    "/access-requests/{request_id}/pin",
    response_model=PinRevealOut,
    summary="Reveal PIN for access request",
)
def reveal_pin(
    request_id: int,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PinRevealOut:
    """
    GET /access-requests/{id}/pin

    Reveal the decrypted 6-digit PIN for an approved, active-credential
    access request.

    Security:
      - Only the request owner may call this endpoint.
        Admin users and other users receive 403 forbidden.
      - PIN is only revealed when credential.status == 'active'.
      - Cache-Control: no-store, private and Pragma: no-cache are set.
      - A 'pin_revealed' audit event is recorded atomically.
    """
    # Set mandatory no-cache headers (Contract 3.4).
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"

    req, plain_pin = access_requests_service.reveal_pin_for_owner(
        db=db,
        user=current_user,
        request_id=request_id,
    )

    cred = req.credential
    assert cred is not None

    return PinRevealOut(
        request_id=req.id,
        resource_code=req.resource.code,
        pin=plain_pin,
        valid_from=_fmt_utc_z(cred.valid_from),
        valid_until=_fmt_utc_z(cred.valid_until),
    )
