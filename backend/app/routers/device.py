"""
routers/device.py -- Device synchronization endpoints (Person B).

Implements:
  - POST /device/v1/sync (Contract 5.4)
"""
from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import AuthenticatedDevice, require_device
from app.schemas.device import DeviceSyncIn, DeviceSyncOut
from app.services.sync import process_device_sync

router = APIRouter(prefix="/device/v1", tags=["Device Synchronization"])


@router.post(
    "/sync",
    status_code=status.HTTP_200_OK,
    response_model=DeviceSyncOut,
    summary="Device synchronization protocol endpoint",
    description=(
        "Authenticated device synchronization endpoint for ESP32 access terminals. "
        "Enforces X-Device-Key, strict UTC X-Device-Timestamp, durable event ingestion, "
        "delta synchronization, request nonce echoing, and X-Server-Signature HMAC-SHA256."
    ),
)
def device_sync(
    payload: DeviceSyncIn,
    _device: Annotated[AuthenticatedDevice, Depends(require_device)],
    db: Session = Depends(get_db),
) -> Response:
    """
    POST /device/v1/sync - Authenticated device sync protocol.
    Protected by require_device (X-Device-Key and X-Device-Timestamp).
    """
    _, response_bytes, signature = process_device_sync(
        db=db,
        payload=payload,
    )
    return Response(
        content=response_bytes,
        media_type="application/json",
        headers={"X-Server-Signature": signature},
    )
