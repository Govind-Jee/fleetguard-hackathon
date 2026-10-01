"""
FleetGuard Pulse - Historical Analytics & Reliability Intelligence Router.
Exposes OLAP metrics computed from ClickHouse and operational summaries from PostgreSQL.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query
import psycopg2

from services.analytics.models import TimeWindow
from services.analytics.service import BatchAnalyticsService
from services.api.auth.models import AuthenticatedUser, UserRole
from services.api.dependencies import (
    check_rate_limit,
    get_ch,
    get_db,
    require_roles,
)
from services.api.exceptions import InvalidInputError
from services.api.schemas.analytics import (
    AnalyticsSummaryResponse,
    FaultFrequencyResponse,
    FleetReliabilityResponse,
    MTBFResponse,
    ReliabilityTrendResponse,
    VehicleDegradationResponse,
)
from services.api.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"], dependencies=[Depends(check_rate_limit)])


def _parse_time_window(start_time: Optional[str], end_time: Optional[str]) -> TimeWindow:
    """Helper converting string query parameters into validated TimeWindow model."""
    try:
        return TimeWindow.create(start_str=start_time, end_str=end_time)
    except ValueError as e:
        raise InvalidInputError(message=str(e))


@router.get(
    "/summary",
    response_model=AnalyticsSummaryResponse,
    summary="Get Operational Fleet Analytics Summary",
    description="Returns aggregate operational metrics from PostgreSQL 3NF storage.",
)
async def get_analytics_summary(
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER)),
    conn: psycopg2.extensions.connection = Depends(get_db),
):
    return AnalyticsService.get_summary(
        conn=conn,
        tenant_id=current_user.tenant_id,
    )


@router.get(
    "/reliability",
    response_model=FleetReliabilityResponse,
    summary="Get Fleet Reliability Summary",
    description="Returns event counts, fault volume, critical failures, and fault rate from ClickHouse.",
)
async def get_fleet_reliability(
    fleet_id: Optional[str] = Query(None, description="Optional fleet boundary filter"),
    start_time: Optional[str] = Query(None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO-8601 end timestamp"),
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
    ch_client = Depends(get_ch),
):
    window = _parse_time_window(start_time, end_time)
    return BatchAnalyticsService.get_fleet_reliability(
        ch_client=ch_client,
        pg_conn=conn,
        tenant_id=current_user.tenant_id,
        fleet_id=fleet_id,
        time_window=window,
    )


@router.get(
    "/faults",
    response_model=FaultFrequencyResponse,
    summary="Get Fault Frequency Breakdown",
    description="Aggregates DTC codes and physical threshold anomalies by frequency and affected vehicles.",
)
async def get_fault_frequency(
    fleet_id: Optional[str] = Query(None, description="Optional fleet boundary filter"),
    start_time: Optional[str] = Query(None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO-8601 end timestamp"),
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
    ch_client = Depends(get_ch),
):
    window = _parse_time_window(start_time, end_time)
    return BatchAnalyticsService.get_fault_frequency(
        ch_client=ch_client,
        pg_conn=conn,
        tenant_id=current_user.tenant_id,
        fleet_id=fleet_id,
        time_window=window,
    )


@router.get(
    "/mtbf",
    response_model=MTBFResponse,
    summary="Get Mean Time Between Failures",
    description="Calculates empirical operating intervals between consecutive debounced failure incidents.",
)
async def get_fleet_mtbf(
    fleet_id: Optional[str] = Query(None, description="Optional fleet boundary filter"),
    start_time: Optional[str] = Query(None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO-8601 end timestamp"),
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
    ch_client = Depends(get_ch),
):
    window = _parse_time_window(start_time, end_time)
    return BatchAnalyticsService.get_mtbf(
        ch_client=ch_client,
        pg_conn=conn,
        tenant_id=current_user.tenant_id,
        fleet_id=fleet_id,
        time_window=window,
    )


@router.get(
    "/trends",
    response_model=ReliabilityTrendResponse,
    summary="Get Historical Reliability Trends",
    description="Time-bucketed series of telemetry activity, failure events, and maintenance actions.",
)
async def get_reliability_trends(
    fleet_id: Optional[str] = Query(None, description="Optional fleet boundary filter"),
    start_time: Optional[str] = Query(None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO-8601 end timestamp"),
    granularity: str = Query("day", pattern="^(day|week)$", description="Aggregation bucket granularity"),
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
    ch_client = Depends(get_ch),
):
    window = _parse_time_window(start_time, end_time)
    return BatchAnalyticsService.get_reliability_trend(
        ch_client=ch_client,
        pg_conn=conn,
        tenant_id=current_user.tenant_id,
        fleet_id=fleet_id,
        time_window=window,
        granularity=granularity,
    )


@router.get(
    "/degradation",
    response_model=VehicleDegradationResponse,
    summary="Get Vehicle Degradation Ranking",
    description="Ranks assets exhibiting historical condition worsening based on telemetry signals prior to cutoff.",
)
async def get_vehicle_degradation(
    fleet_id: Optional[str] = Query(None, description="Optional fleet boundary filter"),
    start_time: Optional[str] = Query(None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO-8601 end timestamp"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of ranked assets to return"),
    current_user: AuthenticatedUser = Depends(require_roles(UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN)),
    conn: psycopg2.extensions.connection = Depends(get_db),
    ch_client = Depends(get_ch),
):
    window = _parse_time_window(start_time, end_time)
    return BatchAnalyticsService.get_vehicle_degradation_ranking(
        ch_client=ch_client,
        pg_conn=conn,
        tenant_id=current_user.tenant_id,
        fleet_id=fleet_id,
        time_window=window,
        limit=limit,
    )
