"""
FleetGuard Pulse - Alert Domain Schemas.
Represents authoritative durable business alerts stored in PostgreSQL 16.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

from services.api.schemas.common import PaginationMeta


class AlertSummary(BaseModel):
    alert_id: str
    tenant_id: str
    vehicle_id: str
    vin: str
    telemetry_event_id: str
    severity: str  # WARNING, CRITICAL
    fault_type: str
    message: str
    sequence_number: int
    is_acknowledged: bool
    created_at: str


class AlertDetail(AlertSummary):
    acknowledged_at: Optional[str] = None
    acknowledged_by_user_id: Optional[str] = None
    resolution_work_order_id: Optional[str] = None
    updated_at: str


class AlertListResponse(BaseModel):
    items: List[AlertSummary]
    pagination: PaginationMeta
