"""
schemas/admin.py -- Pydantic schemas for administrative endpoints.

Covers:
  - GET /admin/logs  (Contract 5.3)
  - GET /admin/nodes (Contract 5.3)
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict


class AdminLogEntryOut(BaseModel):
    id: int
    source: str
    event_id: str
    event_type: str
    reason: Optional[str] = None
    resource_code: Optional[str] = None
    request_id: Optional[int] = None
    credential_id: Optional[int] = None
    actor: Optional[str] = None
    note: Optional[str] = None
    device_time: Optional[str] = None
    time_trusted: Optional[bool] = None
    occurred_at: str

    model_config = ConfigDict(from_attributes=True)


class AdminNodeOut(BaseModel):
    id: int
    node_code: str
    firmware_version: Optional[str] = None
    last_seen_at: Optional[str] = None
    online: bool
    time_state: Optional[str] = None
    last_acked_seq: int
    server_seq: int

    model_config = ConfigDict(from_attributes=True)
