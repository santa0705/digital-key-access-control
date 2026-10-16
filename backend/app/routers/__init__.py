"""Router package for Digital Key Access Control API."""
from app.routers.access_requests import router as access_requests_router
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.device import router as device_router
from app.routers.resources import router as resources_router

__all__ = [
    "admin_router",
    "auth_router",
    "device_router",
    "resources_router",
    "access_requests_router",
]
