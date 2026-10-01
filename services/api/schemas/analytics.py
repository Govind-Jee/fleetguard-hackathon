"""
FleetGuard Pulse - Historical Analytics Summary Schemas.
Combines PostgreSQL 3NF operational metrics with ClickHouse OLAP reliability intelligence.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from services.analytics.models import (
    FaultFrequencyItem,
    FaultFrequencyResponse,
    FleetReliabilityMetrics,
    MTBFMetrics,
    ReliabilityTrendItem,
    ReliabilityTrendResponse,
    VehicleDegradationItem,
    VehicleDegradationResponse,
)


class AnalyticsSummaryResponse(BaseModel):
    """Lightweight historical fleet-wide operational summary from PostgreSQL 3NF."""
    tenant_id: str
    total_monitored_vehicles: int
    active_fleets_count: int
    powertrain_breakdown: Dict[str, int] = Field(default_factory=dict)
    total_alerts_recorded: int
    unresolved_alerts_count: int
    completed_work_orders_count: int
    average_fleet_odometer_km: float
    data_source: str = "PostgreSQL 3NF Domain Aggregates"
    as_of_timestamp: str


# Re-export ClickHouse OLAP models for API responses
FleetReliabilityResponse = FleetReliabilityMetrics
MTBFResponse = MTBFMetrics

__all__ = [
    "AnalyticsSummaryResponse",
    "FleetReliabilityResponse",
    "FaultFrequencyItem",
    "FaultFrequencyResponse",
    "MTBFResponse",
    "ReliabilityTrendItem",
    "ReliabilityTrendResponse",
    "VehicleDegradationItem",
    "VehicleDegradationResponse",
]
