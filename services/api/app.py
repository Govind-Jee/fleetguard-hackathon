"""
FleetGuard Pulse - FastAPI Application Factory.
Configures CORS, defensive security headers, structured exception handlers,
Prometheus metrics, and all domain API routers.
"""

from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.api.config import settings
from services.api.db import close_db_pools, init_db_pools
from services.api.exceptions import register_exception_handlers
from services.api.routers import (
    alerts,
    analytics,
    diagnostics,
    fleets,
    health,
    maintenance,
    metrics,
    vehicles,
    ws,
)
from services.api.security import SecurityHeadersMiddleware

logger = logging.getLogger("fleetguard.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and graceful shutdown lifecycle hooks."""
    logger.info("Initializing FleetGuard Pulse API (env=%s)...", settings.ENVIRONMENT)
    init_db_pools()
    yield
    logger.info("Draining connections and shutting down FleetGuard Pulse API...")
    close_db_pools()


def create_app() -> FastAPI:
    """Factory function creating the production-ready FastAPI instance."""
    app = FastAPI(
        title="FleetGuard Pulse API",
        description=(
            "Authoritative enterprise REST and WebSocket API for FleetGuard Pulse: "
            "Connected Vehicle Predictive Maintenance, Real-Time Fleet Health, "
            "and Anomaly Intelligence Platform."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 1. Defensive Security Headers & Metrics Middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # 2. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset", "Retry-After"],
    )

    # 3. Global Structured Exception Handlers
    register_exception_handlers(app)

    # 4. Domain Routers
    app.include_router(health.router)
    app.include_router(vehicles.router)
    app.include_router(alerts.router)
    app.include_router(fleets.router)
    app.include_router(diagnostics.router)
    app.include_router(maintenance.router)
    app.include_router(analytics.router)
    app.include_router(ws.router)
    app.include_router(metrics.router)

    return app


# Default ASGI application instance for uvicorn
app = create_app()
