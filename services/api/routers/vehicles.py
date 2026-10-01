"""
FleetGuard Pulse - Vehicle Domain Routers.
Endpoints for vehicle directory, detailed metadata, operational health, and predictive risk.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query
import psycopg2
import redis

from services.api.auth.models import AuthenticatedUser, UserRole
from services.api.dependencies import check_rate_limit, get_current_user, get_db, get_redis, require_roles
from services.api.exceptions import ResourceNotFoundError
from services.api.schemas.risk import VehicleRiskResponse
from services.api.schemas.vehicles import (
    VehicleDetailResponse,
    VehicleHealthResponse,
    VehicleListResponse,
)
from services.api.services.risk_service import RiskService
from services.api.services.vehicle_service import VehicleService

router = APIRouter(prefix="/vehicles", tags=["Vehicles"], dependencies=[Depends(check_rate_limit)])


@router.get(
    "",
    response_model=VehicleListResponse,
    summary="List Monitored Vehicles",
    description="Returns paginated vehicle records strictly scoped to the authenticated tenant. Supports fleet and powertrain filters.",
)
async def list_vehicles(
    fleet_id: Optional[str] = Query(None, description="Filter by fleet UUID"),
    vehicle_type: Optional[str] = Query(None, pattern="^(ICE|HEV|BEV)$", description="Filter by powertrain type"),
    status: Optional[str] = Query(None, pattern="^(ACTIVE|MAINTENANCE|DECOMMISSIONED|INACTIVE)$", description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
):
    return VehicleService.list_vehicles(
        conn=conn,
        tenant_id=current_user.tenant_id,
        fleet_id=fleet_id,
        vehicle_type=vehicle_type,
        status=status,
        page=page,
        limit=limit,
    )


@router.get(
    "/{vin}",
    response_model=VehicleDetailResponse,
    summary="Get Vehicle Details",
    description="Returns authoritative PostgreSQL 3NF relational data and current Redis transient hot state. Enforces tenant boundary.",
)
async def get_vehicle_detail(
    vin: str,
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
    r_client: redis.Redis = Depends(get_redis),
):
    result = VehicleService.get_vehicle_detail(
        conn=conn,
        redis_client=r_client,
        tenant_id=current_user.tenant_id,
        vin=vin,
    )
    if not result:
        raise ResourceNotFoundError(resource="Vehicle", identifier=vin)
    return result


@router.get(
    "/{vin}/health",
    response_model=VehicleHealthResponse,
    summary="Get Vehicle Operational Health",
    description="Returns latest operational status combining Redis hot state (GPS, telemetry, sequence) and PostgreSQL alerts summary.",
)
async def get_vehicle_health(
    vin: str,
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
    r_client: redis.Redis = Depends(get_redis),
):
    health = VehicleService.get_vehicle_health(
        conn=conn,
        redis_client=r_client,
        tenant_id=current_user.tenant_id,
        vin=vin,
    )
    if not health:
        raise ResourceNotFoundError(resource="Vehicle", identifier=vin)
    return health


@router.get(
    "/{vin}/risk",
    response_model=VehicleRiskResponse,
    summary="Get Vehicle Predictive Maintenance Risk",
    description=(
        "Estimates the probability that the vehicle will experience a failure or require unscheduled maintenance "
        "within the next 7 days using the trained scikit-learn Logistic Regression Pipeline. "
        "Decomposes log-odds into local contributing risk and protective factors."
    ),
)
async def get_vehicle_risk(
    vin: str,
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
    r_client: redis.Redis = Depends(get_redis),
):
    risk = RiskService.get_vehicle_risk(
        conn=conn,
        redis_client=r_client,
        tenant_id=current_user.tenant_id,
        vin=vin,
    )
    if not risk:
        raise ResourceNotFoundError(resource="Vehicle", identifier=vin)
    return risk
