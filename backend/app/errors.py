"""
errors.py -- Standard error envelope and exception handlers.

Contract 3.2: All error responses must use the single JSON envelope:
    {"error": {"code": "<code>", "message": "<message>"}}

Contract 3.3: Maps domain exception codes to HTTP status codes.
Contract G7: Domain services raise standardised domain exceptions; this
             module maps them into HTTP responses.  Routers never manually
             construct error JSON dictionaries.
"""
from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


# ---------------------------------------------------------------------------
# Domain exception
# ---------------------------------------------------------------------------

class DomainError(Exception):
    """
    Base class for all domain-layer errors raised by service functions.

    Attributes
    ----------
    code:        Contract error code string (e.g. "not_found", "forbidden").
    message:     Human-readable description.
    http_status: HTTP status code to send to the client.
    """

    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# ---------------------------------------------------------------------------
# Convenience factory helpers (one per contract error code)
# ---------------------------------------------------------------------------

def err_unauthorized(message: str = "Authentication required.") -> DomainError:
    return DomainError("unauthorized", message, status.HTTP_401_UNAUTHORIZED)


def err_forbidden(message: str = "You do not have permission to perform this action.") -> DomainError:
    return DomainError("forbidden", message, status.HTTP_403_FORBIDDEN)


def err_not_found(message: str = "The requested resource was not found.") -> DomainError:
    return DomainError("not_found", message, status.HTTP_404_NOT_FOUND)


def err_resource_not_found(message: str = "Resource not found.") -> DomainError:
    return DomainError("resource_not_found", message, status.HTTP_404_NOT_FOUND)


def err_invalid_state(message: str) -> DomainError:
    return DomainError("invalid_state", message, status.HTTP_409_CONFLICT)


def err_active_credential_exists(message: str) -> DomainError:
    return DomainError("active_credential_exists", message, status.HTTP_409_CONFLICT)


def err_window_expired(message: str = "Access request validity window has already passed.") -> DomainError:
    return DomainError("window_expired", message, status.HTTP_409_CONFLICT)


def err_pin_unavailable(message: str = "PIN is not available: credential is not active.") -> DomainError:
    return DomainError("pin_unavailable", message, status.HTTP_409_CONFLICT)


def err_validation(message: str) -> DomainError:
    return DomainError("validation_error", message, status.HTTP_422_UNPROCESSABLE_ENTITY)


# ---------------------------------------------------------------------------
# JSON envelope builder
# ---------------------------------------------------------------------------

def _error_envelope(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# Exception handlers -- register onto the FastAPI app instance
# ---------------------------------------------------------------------------

def register_error_handlers(app: FastAPI) -> None:
    """Attach all custom error handlers to *app*."""

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=_error_envelope(exc.code, exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Flatten all Pydantic/FastAPI validation errors into a single message.
        messages = []
        for error in exc.errors():
            loc = " -> ".join(str(p) for p in error.get("loc", []) if p != "body")
            msg = error.get("msg", "Invalid value")
            if loc:
                messages.append(f"{loc}: {msg}")
            else:
                messages.append(msg)
        combined = "; ".join(messages) if messages else "Request validation failed."
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_envelope("validation_error", combined),
        )
