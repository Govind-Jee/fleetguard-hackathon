"""
FleetGuard Pulse - Historical Analytics Router.
"""

from fastapi import APIRouter, Depends
import psycopg2

from services.api.auth.models import AuthenticatedUser, UserRole
from services.api.dependencies import check_rate_limit, get_current_user, get_db, require_roles
from services.api.schemas.analytics import AnalyticsSummaryResponse
from services.api.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"], dependencies=[Depends(check_rate_limit)])


@router.get(
    "/summary",
    response_model=AnalyticsSummaryResponse,
    summary="Get Historical Fleet Analytics Summary",
    description="Returns aggregate historical fleet operational summary including asset counts, powertrain mix, and alert totals.",
)
async def get_analytics_summary(
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER)),
    conn: psycopg2.extensions.connection = Depends(get_db),
):
    return AnalyticsService.get_summary(
        conn=conn,
        tenant_id=current_user.tenant_id,
    )
