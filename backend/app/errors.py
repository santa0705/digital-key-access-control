"""
errors.py -- Standard error envelope and exception handlers.

Contract 3.2: All error responses must use the single JSON envelope:
    {"error": {"code": "<code>", "message": "<message>"}}

Contract 3.3: Maps domain exception codes to HTTP status codes.
Contract G7: Domain services raise standardised domain exceptions; this
             module maps them into HTTP responses. Routers never manually
             construct error JSON dictionaries.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# Fallback mapping from HTTP status code to contract error code
STATUS_TO_CODE: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "invalid_state",
    422: "validation_error",
    500: "internal_error",
    503: "service_unavailable",
}


# ---------------------------------------------------------------------------
# Base Domain and Application Exception
# ---------------------------------------------------------------------------

class AppError(Exception):
    """
    Base domain exception that maps directly to the standard contract error envelope.
    Supports both Person A (http_status) and Person B (status_code) property conventions.
    """
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.http_status = status_code


class DomainError(AppError):
    """
    Person A domain-layer error alias.
    Maintains exact constructor signature (code, message, http_status).
    """
    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(code=code, message=message, status_code=http_status)


# ---------------------------------------------------------------------------
# Specific Subclasses (Person B)
# ---------------------------------------------------------------------------

class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required", code: str = "unauthorized"):
        super().__init__(code=code, message=message, status_code=status.HTTP_401_UNAUTHORIZED)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Permission denied", code: str = "forbidden"):
        super().__init__(code=code, message=message, status_code=status.HTTP_403_FORBIDDEN)


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found", code: str = "not_found"):
        super().__init__(code=code, message=message, status_code=status.HTTP_404_NOT_FOUND)


class ConflictError(AppError):
    def __init__(self, message: str = "Invalid state transition", code: str = "invalid_state"):
        super().__init__(code=code, message=message, status_code=status.HTTP_409_CONFLICT)


class ActiveCredentialExistsError(AppError):
    def __init__(self, message: str = "An active credential already exists for this resource."):
        super().__init__(code="active_credential_exists", message=message, status_code=status.HTTP_409_CONFLICT)


class WindowExpiredError(AppError):
    def __init__(self, message: str = "Access window has expired."):
        super().__init__(code="window_expired", message=message, status_code=status.HTTP_409_CONFLICT)


class PinUnavailableError(AppError):
    def __init__(self, message: str = "PIN is unavailable."):
        super().__init__(code="pin_unavailable", message=message, status_code=status.HTTP_409_CONFLICT)


class SyncStateInconsistentError(AppError):
    def __init__(self, message: str = "Sync state counter is inconsistent."):
        super().__init__(code="sync_state_inconsistent", message=message, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


# ---------------------------------------------------------------------------
# Convenience factory helpers (Person A)
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
# JSON envelope builders
# ---------------------------------------------------------------------------

def format_error_payload(code: str, message: str) -> dict[str, dict[str, str]]:
    """Helper returning standard contract error dictionary."""
    return {"error": {"code": code, "message": message}}


def _error_envelope(code: str, message: str) -> dict[str, dict[str, str]]:
    """Alias for format_error_payload for Person A compatibility."""
    return format_error_payload(code=code, message=message)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Handles domain AppError and DomainError instances."""
    return JSONResponse(
        status_code=exc.status_code,
        content=format_error_payload(code=exc.code, message=exc.message),
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Handles request validation errors (Pydantic / FastAPI 422).
    Flattens field validation errors into a single human-readable message with code 'validation_error'.
    """
    messages: list[str] = []
    for err in exc.errors():
        loc_parts = [str(part) for part in err.get("loc", []) if part != "body"]
        field = ".".join(loc_parts) if loc_parts else ""
        msg = err.get("msg", "Invalid value")
        if field:
            messages.append(f"{field}: {msg}")
        else:
            messages.append(msg)

    summary = "; ".join(messages) if messages else "Request validation failed."
    status_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)
    return JSONResponse(
        status_code=status_422,
        content=format_error_payload(code="validation_error", message=summary),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    Handles Starlette / FastAPI HTTPExceptions.
    Ensures standard {"error": {"code": "...", "message": "..."}} format for all HTTP errors.
    """
    status_code = exc.status_code
    code = STATUS_TO_CODE.get(status_code, "error")

    if isinstance(exc.detail, dict):
        code = str(exc.detail.get("code", code))
        message = str(exc.detail.get("message", "An error occurred."))
    elif isinstance(exc.detail, str):
        message = exc.detail
    else:
        message = "An error occurred."

    # Prevent leaking internal stack traces or database errors on 500
    if status_code >= 500 and status_code != 503:
        message = "An internal server error occurred."

    return JSONResponse(
        status_code=status_code,
        content=format_error_payload(code=code, message=message),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler for unhandled exceptions.
    Prevents leakage of database credentials, tracebacks, or secrets.
    """
    logger.exception("Unhandled server exception: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=format_error_payload(code="internal_error", message="An internal server error occurred."),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Registers standard exception handlers on the FastAPI application."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
