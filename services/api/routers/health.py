"""
FleetGuard Pulse - Health and Readiness Probes.
Unauthenticated endpoints for container orchestrators (Kubernetes/Compose) and load balancers.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Response, status

from services.api.db import check_clickhouse_health, check_postgres_health, check_redis_health
from services.api.schemas.common import HealthResponse, ReadinessDatastoreStatus, ReadinessResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness Probe",
    description="Returns HTTP 200 if the FastAPI application process is alive and accepting traffic.",
)
async def get_health():
    return HealthResponse(
        status="HEALTHY",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness Probe",
    description="Probes connectivity to PostgreSQL, Redis, and ClickHouse datastores. Returns 503 if primary database is down.",
)
async def get_readiness(response: Response):
    pg_ok = check_postgres_health()
    redis_ok = check_redis_health()
    ch_ok = check_clickhouse_health()

    is_ready = pg_ok and redis_ok

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        overall_status = "DEGRADED"
    else:
        overall_status = "READY"

    return ReadinessResponse(
        status=overall_status,
        datastores=ReadinessDatastoreStatus(
            postgres=pg_ok,
            redis=redis_ok,
            clickhouse=ch_ok,
        ),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
