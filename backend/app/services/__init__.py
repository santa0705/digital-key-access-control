"""
backend/app/services package -- Person A and Person B backend services.

Person A services:
  - access_requests: Request creation, ownership checks, and PIN reveal coordination.
  - events: Telemetry/audit event creation, validation, and unknown credential handling.
  - sequence: Change sequence allocation (next_change_seq) and transaction coordination.
"""
from app.services import access_requests, events, sequence

__all__ = ["access_requests", "events", "sequence"]
