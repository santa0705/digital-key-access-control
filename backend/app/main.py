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

try:
    from app.config import get_settings
    from app.db import get_db
    from app.errors import register_error_handlers
    from app.routers.admin import router as admin_router
    from app.routers.resources import router as resources_router
    from app.routers.access_requests import router as access_requests_router
except ImportError:
    from .config import get_settings
    from .db import get_db
    from .errors import register_error_handlers
    from .routers.admin import router as admin_router
    from .routers.resources import router as resources_router
    from .routers.access_requests import router as access_requests_router

settings = get_settings()

app = FastAPI(
    title="Digital Key Access Control API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Register custom error handlers (standard envelope + validation_error)
register_error_handlers(app)

# CORS middleware configured from CORS_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Register Person A routers
# ---------------------------------------------------------------------------
app.include_router(resources_router)
app.include_router(access_requests_router)
app.include_router(admin_router)



# ---------------------------------------------------------------------------
# Health probe (owned by Person B, kept in main.py per existing structure)
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
