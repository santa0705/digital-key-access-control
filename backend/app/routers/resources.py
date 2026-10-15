"""
routers/resources.py -- GET /resources endpoint (Person A).

Contract 5.2:
  GET /resources
    Auth: Bearer token (user or admin)
    Returns: list of all resources with id, code, name, kind, is_active.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models.resources import Resource
from app.models.users import User
from app.schemas.resources import ResourceOut

router = APIRouter(tags=["Resources"])


@router.get(
    "/resources",
    response_model=list[ResourceOut],
    summary="List all resources",
    description=(
        "Return all physical and simulated locker resources. "
        "Requires a valid Bearer token (user or admin)."
    ),
)
def list_resources(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[ResourceOut]:
    """
    GET /resources

    Lists every Resource row.  No filtering; all resources are returned
    regardless of is_active status (contract example shows is_active: true,
    but the contract does not restrict to active-only at the list level).
    """
    resources = db.query(Resource).order_by(Resource.id).all()
    return [ResourceOut.model_validate(r) for r in resources]
