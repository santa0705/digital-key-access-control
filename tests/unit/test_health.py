import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.main import app

client = TestClient(app)


def test_settings_loaded():
    """Verify that settings load with valid configuration and architectural constants."""
    settings = get_settings()
    assert settings.SYNC_PAGE_SIZE == 8
    assert settings.EVENT_BATCH_MAX == 20
    assert settings.ONLINE_WINDOW_S == 45
    assert len(settings.cors_origins_list) >= 1


def test_direct_database_connection():
    """Verify that direct connection to PostgreSQL executes successfully without schema errors."""
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1")).scalar()
        assert result == 1


def test_health_endpoint():
    """Verify that the /health endpoint executes SELECT 1 and returns expected contract shape."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data.get("status") == "ok"
    assert data.get("database") == "connected"
    assert "server_time" in data
    # Server time must end with 'Z' representing UTC
    assert data["server_time"].endswith("Z")
