"""
FleetGuard Pulse - Historical Analytics Summary Schemas.
"""

from typing import Dict
from pydantic import BaseModel, Field


class AnalyticsSummaryResponse(BaseModel):
    """Lightweight historical fleet-wide analytics summary."""
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
