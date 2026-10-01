"""
FleetGuard Pulse - Fleet Management Routers.
"""

from fastapi import APIRouter, Depends
import psycopg2

from services.api.auth.models import AuthenticatedUser, UserRole
from services.api.dependencies import check_rate_limit, get_current_user, get_db, require_roles
from services.api.exceptions import ResourceNotFoundError
from services.api.schemas.fleets import FleetHealthResponse, FleetListResponse
from services.api.services.fleet_service import FleetService

router = APIRouter(prefix="/fleets", tags=["Fleets"], dependencies=[Depends(check_rate_limit)])


@router.get(
    "",
    response_model=FleetListResponse,
    summary="List Fleets",
    description="Returns all fleets belonging strictly to the authenticated tenant.",
)
async def list_fleets(
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
):
    return FleetService.list_fleets(
        conn=conn,
        tenant_id=current_user.tenant_id,
    )


@router.get(
    "/{fleet_id}/health",
    response_model=FleetHealthResponse,
    summary="Get Consolidated Fleet Health",
    description="Returns aggregate health status, vehicle breakdown, and work-order counts computed using optimized SQL queries (zero N+1 overhead).",
)
async def get_fleet_health(
    fleet_id: str,
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
):
    health = FleetService.get_fleet_health(
        conn=conn,
        tenant_id=current_user.tenant_id,
        fleet_id=fleet_id,
    )
    if not health:
        raise ResourceNotFoundError(resource="Fleet", identifier=fleet_id)
    return health
