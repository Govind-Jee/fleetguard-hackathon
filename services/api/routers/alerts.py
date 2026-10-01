"""
FleetGuard Pulse - Alert Domain Routers.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query
import psycopg2

from services.api.auth.models import AuthenticatedUser, UserRole
from services.api.dependencies import check_rate_limit, get_current_user, get_db, require_roles
from services.api.exceptions import ResourceNotFoundError
from services.api.schemas.alerts import AlertDetail, AlertListResponse
from services.api.services.alert_service import AlertService

router = APIRouter(prefix="/alerts", tags=["Alerts"], dependencies=[Depends(check_rate_limit)])


@router.get(
    "",
    response_model=AlertListResponse,
    summary="List Operational Alerts",
    description="Returns durable historical alerts scoped to authenticated tenant. Supports severity and vehicle filters.",
)
async def list_alerts(
    fleet_id: Optional[str] = Query(None, description="Filter by fleet UUID"),
    vin: Optional[str] = Query(None, description="Filter by VIN"),
    severity: Optional[str] = Query(None, pattern="^(WARNING|CRITICAL)$", description="Filter by alert severity"),
    is_acknowledged: Optional[bool] = Query(None, description="Filter by acknowledgment status"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
):
    return AlertService.list_alerts(
        conn=conn,
        tenant_id=current_user.tenant_id,
        fleet_id=fleet_id,
        vin=vin,
        severity=severity,
        is_acknowledged=is_acknowledged,
        page=page,
        limit=limit,
    )


@router.get(
    "/{alert_id}",
    response_model=AlertDetail,
    summary="Get Alert Details",
    description="Returns authoritative alert record by ID, verifying tenant ownership.",
)
async def get_alert(
    alert_id: str,
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
):
    alert = AlertService.get_alert_by_id(
        conn=conn,
        tenant_id=current_user.tenant_id,
        alert_id=alert_id,
    )
    if not alert:
        raise ResourceNotFoundError(resource="Alert", identifier=alert_id)
    return alert
