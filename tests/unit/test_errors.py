import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.errors import (
    ActiveCredentialExistsError,
    AppError,
    ConflictError,
    NotFoundError,
    PinUnavailableError,
    register_error_handlers,
)
from app.main import app

# Client for the primary application
main_client = TestClient(app)


# Dedicated test application to test error handlers in isolation without mutating main.py routes
@pytest.fixture
def error_test_client() -> TestClient:
    test_app = FastAPI()
    register_error_handlers(test_app)

    class ValidationSample(BaseModel):
        code: str = Field(..., min_length=1)
        count: int

    @test_app.post("/test-validate")
    def validate_route(payload: ValidationSample):
        return {"received": payload.code}

    @test_app.get("/test-http-error")
    def http_error_route():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requested resource was not found.",
        )

    @test_app.get("/test-domain-conflict")
    def domain_conflict_route():
        raise ConflictError(
            message="Request 5 is already approved; only pending requests can be approved."
        )

    @test_app.get("/test-active-credential")
    def active_cred_route():
        raise ActiveCredentialExistsError(
            message="Resource A has active credential 6 (request 4)."
        )

    @test_app.get("/test-pin-unavailable")
    def pin_unavail_route():
        raise PinUnavailableError(message="PIN is unavailable for expired credential.")

    @test_app.get("/test-unhandled-exception")
    def unhandled_route():
        # Simulate an internal crash containing sensitive database information
        raise RuntimeError(
            "Connection failed: postgresql+psycopg://user:super_secret_db_password@localhost/db"
        )

    return TestClient(test_app, raise_server_exceptions=False)


def test_main_app_404_envelope():
    """Verify that undefined routes on main app return the contract 404 error envelope."""
    response = main_client.get("/non-existent-endpoint-path")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "not_found"
    assert data["error"]["message"] == "Not Found"


def test_validation_error_422_envelope(error_test_client: TestClient):
    """Verify that malformed/missing request bodies produce 422 with code 'validation_error'."""
    # Sending missing 'count' and invalid 'code' type
    response = error_test_client.post("/test-validate", json={"code": ""})
    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "validation_error"
    # Ensure field names are reflected in the human-readable summary
    assert "code" in data["error"]["message"] or "count" in data["error"]["message"]


def test_http_exception_envelope(error_test_client: TestClient):
    """Verify that HTTPExceptions produce the standard error envelope with appropriate status."""
    response = error_test_client.get("/test-http-error")
    assert response.status_code == 404
    data = response.json()
    assert data == {
        "error": {
            "code": "not_found",
            "message": "Requested resource was not found.",
        }
    }


def test_domain_app_errors(error_test_client: TestClient):
    """Verify that domain exceptions map cleanly to contract codes and HTTP statuses."""
    # Test ConflictError (409 invalid_state)
    res_conflict = error_test_client.get("/test-domain-conflict")
    assert res_conflict.status_code == 409
    assert res_conflict.json() == {
        "error": {
            "code": "invalid_state",
            "message": "Request 5 is already approved; only pending requests can be approved.",
        }
    }

    # Test ActiveCredentialExistsError (409 active_credential_exists)
    res_active = error_test_client.get("/test-active-credential")
    assert res_active.status_code == 409
    assert res_active.json()["error"]["code"] == "active_credential_exists"

    # Test PinUnavailableError (409 pin_unavailable)
    res_pin = error_test_client.get("/test-pin-unavailable")
    assert res_pin.status_code == 409
    assert res_pin.json()["error"]["code"] == "pin_unavailable"


def test_unhandled_exception_does_not_leak_secrets(error_test_client: TestClient):
    """Verify that uncaught exceptions return safe 500 error envelope without exposing secrets."""
    response = error_test_client.get("/test-unhandled-exception")
    assert response.status_code == 500
    data = response.json()
    assert data == {
        "error": {
            "code": "internal_error",
            "message": "An internal server error occurred.",
        }
    }
    # Ensure sensitive credentials or stack traces are not leaked in the body
    assert "super_secret_db_password" not in response.text
    assert "postgresql" not in response.text
    assert "Traceback" not in response.text
