"""
main.py -- FastAPI application entry point for Digital Key Access Control API.

Registers:
  - Custom error handlers (AppError, DomainError, RequestValidationError, StarletteHTTPException)
  - CORS middleware
  - Person A and Person B routers (/auth, /resources, /access-requests, /admin, /device/v1)
  - Operational health probe (GET /health)
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

# Ensure backend package root is importable
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings
from app.db import get_db
from app.errors import register_error_handlers
from app.routers.access_requests import router as access_requests_router
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.device import router as device_router
from app.routers.resources import router as resources_router

from contextlib import asynccontextmanager

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Server lifespan lifecycle handler.
    Validates cryptographic keys on server boot per docs/credential-policy.md §2.1.
    Specifically validates Fernet(PIN_ENC_KEY). Fails fast if PIN_ENC_KEY is missing,
    unconfigured, or set to placeholder.
    Optionally executes automated migrations and seeding if AUTO_MIGRATE is enabled.
    """
    import os
    import logging
    logger = logging.getLogger("app.startup")

    from app.services.credentials import get_fernet_cipher
    try:
        get_fernet_cipher()
    except ValueError as exc:
        raise RuntimeError(
            f"Server boot failed: {exc} "
            "Please configure a valid 32-byte URL-safe base64 Fernet key via the PIN_ENC_KEY "
            "environment variable (e.g. $env:PIN_ENC_KEY) or in .env. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ) from exc

    if os.getenv("AUTO_MIGRATE", "").lower() in ("true", "1", "yes"):
        logger.info("Executing automated database migration...")
        from alembic import command
        from alembic.config import Config
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        command.upgrade(cfg, "head")
        logger.info("Database migration completed.")

        if os.getenv("AUTO_SEED", "").lower() in ("true", "1", "yes"):
            logger.info("Executing automated demo database seeding...")
            from app.db import SessionLocal
            from app.seed import seed_database
            with SessionLocal() as session:
                counts = seed_database(session)
            logger.info("Database seeded successfully: %s", counts)

    yield


app = FastAPI(
    title="Digital Key Access Control API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Register custom error handlers (standard envelope + validation_error)
register_error_handlers(app)

# CORS middleware configured from CORS_ORIGINS with local dev fallback and Vercel regex
configured_origins = set(settings.cors_origins_list)
default_dev_origins = {
    "http://localhost:3000",
    "http://localhost:4173",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:4173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
}
effective_cors_origins = sorted(configured_origins | default_dev_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=effective_cors_origins,
    allow_origin_regex=r"^https:\/\/.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Register Person A and Person B routers
# ---------------------------------------------------------------------------
app.include_router(auth_router)
app.include_router(resources_router)
app.include_router(access_requests_router)
app.include_router(admin_router)
app.include_router(device_router)


# ---------------------------------------------------------------------------
# Operational Health probe
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Operational"])
def health_check(db: Session = Depends(get_db)):
    """
    Operational health probe.
    Executes SELECT 1 to verify database connectivity.
    Returns status ok and server_time in UTC (ISO-8601 with trailing Z).
    """
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed",
        ) from exc

    server_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "status": "ok",
        "server_time": server_time,
        "database": "connected",
    }
