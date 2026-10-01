"""
FleetGuard Pulse - API Custom Exceptions & Global Exception Handlers.
Guarantees clean, structured error JSON without leaking stack traces, SQL,
file paths, or internal credentials.
"""

import logging
import uuid
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("fleetguard.api.exceptions")


class FleetGuardAPIException(Exception):
    """Base class for all FleetGuard domain and API exceptions."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_SERVER_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class AuthenticationError(FleetGuardAPIException):
    """Raised when authentication token is missing, invalid, or expired."""

    def __init__(self, message: str = "Invalid or expired authentication credentials", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="UNAUTHORIZED",
            status_code=status.HTTP_401_UNAUTHORIZED,
            details=details,
        )


class InsufficientPermissionsError(FleetGuardAPIException):
    """Raised when authenticated user lacks the required RBAC role."""

    def __init__(self, message: str = "Insufficient role permissions for requested action", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="FORBIDDEN_INSUFFICIENT_ROLE",
            status_code=status.HTTP_403_FORBIDDEN,
            details=details,
        )


class TenantAccessForbiddenError(FleetGuardAPIException):
    """Raised when user attempts cross-tenant resource access."""

    def __init__(self, message: str = "Access to requested resource is forbidden across tenant boundaries", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="FORBIDDEN_TENANT_ISOLATION",
            status_code=status.HTTP_403_FORBIDDEN,
            details=details,
        )


class ResourceNotFoundError(FleetGuardAPIException):
    """Raised when entity does not exist within the tenant domain."""

    def __init__(self, resource: str, identifier: str):
        super().__init__(
            message=f"{resource} with identifier '{identifier}' was not found within tenant domain",
            code="RESOURCE_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"resource": resource, "identifier": identifier},
        )


class ResourceConflictError(FleetGuardAPIException):
    """Raised on unique constraint or state conflict."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="RESOURCE_CONFLICT",
            status_code=status.HTTP_409_CONFLICT,
            details=details,
        )


class InvalidInputError(FleetGuardAPIException):
    """Raised when semantic request validation fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="INVALID_INPUT",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details,
        )


class RateLimitExceededError(FleetGuardAPIException):
    """Raised when request rate exceeds configured quota."""

    def __init__(self, retry_after: int = 60, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message="API rate limit exceeded. Please throttle requests.",
            code="RATE_LIMIT_EXCEEDED",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details=details or {"retry_after_seconds": retry_after},
        )
        self.retry_after = retry_after


class DatabaseUnavailableError(FleetGuardAPIException):
    """Raised when datastore connection fails."""

    def __init__(self, datastore: str = "database"):
        super().__init__(
            message=f"Underlying {datastore} service is temporarily unavailable",
            code="SERVICE_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"datastore": datastore},
        )


def build_error_payload(code: str, message: str, request_id: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Uniform structured JSON error schema."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
        "request_id": request_id,
    }


def register_exception_handlers(app: FastAPI) -> None:
    """Register uniform structured exception handlers with FastAPI application."""

    @app.exception_handler(FleetGuardAPIException)
    async def handle_fleetguard_exception(request: Request, exc: FleetGuardAPIException):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.warning(
            "FleetGuardAPIException [%s] (%s): %s on %s %s",
            exc.code,
            exc.status_code,
            exc.message,
            request.method,
            request.url.path,
        )
        headers = {}
        if isinstance(exc, RateLimitExceededError):
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_payload(exc.code, exc.message, request_id, exc.details),
            headers=headers,
        )

    @app.exception_handler(StarletteHTTPException)
    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        status_code = getattr(exc, "status_code", 500)
        code = "HTTP_ERROR"
        if status_code == status.HTTP_401_UNAUTHORIZED:
            code = "UNAUTHORIZED"
        elif status_code == status.HTTP_403_FORBIDDEN:
            code = "FORBIDDEN"
        elif status_code == status.HTTP_404_NOT_FOUND:
            code = "RESOURCE_NOT_FOUND"

        detail = getattr(exc, "detail", "HTTP request error")
        message = detail if isinstance(detail, str) else "HTTP request error"
        details = detail if isinstance(detail, dict) else {}
        headers = getattr(exc, "headers", None) or {}
        return JSONResponse(
            status_code=status_code,
            content=build_error_payload(code, message, request_id, details),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        sanitized_errors = []
        for err in exc.errors():
            loc = " -> ".join(str(l) for l in err.get("loc", []))
            sanitized_errors.append({
                "field": loc,
                "issue": err.get("msg", "Invalid parameter"),
                "type": err.get("type", "value_error"),
            })
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=build_error_payload(
                code="VALIDATION_ERROR",
                message="Request payload failed structural schema validation",
                request_id=request_id,
                details={"validation_errors": sanitized_errors},
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.error(
            "Unhandled server exception on %s %s (request_id=%s): %s",
            request.method,
            request.url.path,
            request_id,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=build_error_payload(
                code="INTERNAL_SERVER_ERROR",
                message="An unexpected internal server error occurred. Please contact system support.",
                request_id=request_id,
            ),
        )
