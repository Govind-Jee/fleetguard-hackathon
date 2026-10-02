"""
FleetGuard Pulse - Security Headers and Request Context Middleware.
Applies enterprise defensive HTTP headers (CSP, HSTS, frame protection, nosniff),
generates unique request IDs, and collects Prometheus request metrics.
"""

import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from services.api.config import settings
from services.api.metrics import api_metrics


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Injects OWASP-recommended security headers into every outgoing HTTP response,
    tracks request latency for Prometheus, and propagates correlation request IDs.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Generate or capture correlation request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        start_time = time.perf_counter()

        try:
            response: Response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - start_time
            api_metrics.record_request(
                method=request.method,
                endpoint=request.url.path,
                status_code=500,
                duration_seconds=duration,
            )
            raise

        duration = time.perf_counter() - start_time

        # Record metrics
        api_metrics.record_request(
            method=request.method,
            endpoint=request.url.path,
            status_code=response.status_code,
            duration_seconds=duration,
        )

        # Security Headers
        response.headers["X-Process-Time-Ms"] = f"{(duration * 1000.0):.3f}"
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self';"
        )

        # HSTS in production or HTTPS environments
        if settings.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        # Rate Limit Headers if computed by RateLimiter
        if hasattr(request.state, "rate_limit_limit"):
            response.headers["X-RateLimit-Limit"] = str(request.state.rate_limit_limit)
        if hasattr(request.state, "rate_limit_remaining"):
            response.headers["X-RateLimit-Remaining"] = str(request.state.rate_limit_remaining)
        if hasattr(request.state, "rate_limit_reset"):
            response.headers["X-RateLimit-Reset"] = str(request.state.rate_limit_reset)

        return response
