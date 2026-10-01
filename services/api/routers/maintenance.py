"""
FleetGuard Pulse - Maintenance & Work Orders Router.
"""

from fastapi import APIRouter, Depends, status
import psycopg2

from services.api.auth.models import AuthenticatedUser, UserRole
from services.api.dependencies import check_rate_limit, get_current_user, get_db, require_roles
from services.api.schemas.maintenance import WorkOrderCreateRequest, WorkOrderResponse
from services.api.services.maintenance_service import MaintenanceService

router = APIRouter(prefix="/maintenance", tags=["Maintenance"], dependencies=[Depends(check_rate_limit)])


@router.post(
    "/work-orders",
    response_model=WorkOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Work Order",
    description="Creates a normalized 3NF maintenance work order. Validates vehicle existence, maintenance type, and tenant isolation boundary.",
)
async def create_work_order(
    request: WorkOrderCreateRequest,
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
):
    return MaintenanceService.create_work_order(
        conn=conn,
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.user_id,
        request=request,
    )
