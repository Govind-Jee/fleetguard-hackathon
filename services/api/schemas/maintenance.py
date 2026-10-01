"""
FleetGuard Pulse - Maintenance & Work Order Schemas.
"""

from typing import Optional
from pydantic import BaseModel, Field


class WorkOrderCreateRequest(BaseModel):
    vin: str = Field(..., min_length=17, max_length=17, description="Vehicle Identification Number")
    type_id: int = Field(..., ge=1, description="Maintenance type catalog ID")
    priority: str = Field(..., pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    scheduled_at: Optional[str] = None
    assigned_technician_id: Optional[str] = None


class WorkOrderResponse(BaseModel):
    work_order_id: str
    tenant_id: str
    vehicle_id: str
    vin: str
    type_id: int
    maintenance_type_name: str
    priority: str
    status: str
    assigned_technician_id: Optional[str] = None
    scheduled_at: Optional[str] = None
    created_at: str
    updated_at: str
