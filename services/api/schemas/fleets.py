"""
FleetGuard Pulse - Fleet Health & Aggregation Schemas.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class FleetSummary(BaseModel):
    fleet_id: str
    tenant_id: str
    name: str
    code: str
    description: Optional[str] = None
    created_at: str


class FleetListResponse(BaseModel):
    items: List[FleetSummary]


class FleetHealthResponse(BaseModel):
    """Consolidated fleet-wide operational health metrics."""
    fleet_id: str
    fleet_name: str
    fleet_code: str
    total_vehicles: int
    vehicles_by_status: Dict[str, int] = Field(default_factory=dict)
    vehicles_by_type: Dict[str, int] = Field(default_factory=dict)
    health_status_counts: Dict[str, int] = Field(default_factory=dict)
    critical_alert_count: int = 0
    high_risk_vehicle_count: int = 0
    work_orders_summary: Dict[str, int] = Field(default_factory=dict)
