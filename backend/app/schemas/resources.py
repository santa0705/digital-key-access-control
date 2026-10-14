"""
schemas/resources.py -- Pydantic output schema for Resource objects.

Contract 5.2 (GET /resources) response shape:
    [{"id": 1, "code": "A", "name": "Locker A", "kind": "physical", "is_active": true}, ...]
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ResourceOut(BaseModel):
    """Serialized resource object returned by GET /resources."""

    id: int
    code: str
    name: str
    kind: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
