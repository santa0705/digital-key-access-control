"""
routers/device.py -- Device synchronization endpoints (Person B).

Implements:
  - POST /device/v1/sync (Contract 5.4)
"""
from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Depends, status

from app.deps import AuthenticatedDevice, require_device
from app.errors import AppError

router = APIRouter(prefix="/device/v1", tags=["Device Synchronization"])


@router.post(
    "/sync",
    status_code=status.HTTP_200_OK,
    summary="Device synchronization protocol endpoint",
)
def device_sync(
    device: Annotated[AuthenticatedDevice, Depends(require_device)],
):
    """
    POST /device/v1/sync - Authenticated device sync protocol.
    Protected by require_device (X-Device-Key and X-Device-Timestamp).
    Placeholder handler: firmware delta sync service pending.
    """
    raise AppError(
        code="not_implemented",
        message="Device synchronization protocol endpoint is not implemented yet.",
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
    )
