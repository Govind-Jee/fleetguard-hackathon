"""
FleetGuard Pulse - Vehicle Domain Schemas.
Enforces separation between authoritative PostgreSQL 3NF data and transient Redis hot state.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from services.api.schemas.common import PaginationMeta


class VehicleModelSpecs(BaseModel):
    make: str
    model_name: str
    year: int
    vehicle_type: str  # ICE, HEV, BEV
    engine_displacement_l: Optional[float] = None
    battery_capacity_kwh: Optional[float] = None
    curb_weight_kg: Optional[int] = None


class VehicleSummary(BaseModel):
    vehicle_id: str
    vin: str
    license_plate: Optional[str] = None
    status: str  # ACTIVE, MAINTENANCE, DECOMMISSIONED, INACTIVE
    manufacture_year: int
    fleet_id: str
    fleet_name: str
    fleet_code: str
    depot_id: str
    depot_name: str
    depot_code: str
    model: VehicleModelSpecs


class VehicleListResponse(BaseModel):
    items: List[VehicleSummary]
    pagination: PaginationMeta


class VehicleHotState(BaseModel):
    """Transient real-time operational state sourced from Redis."""
    sequence_number: int
    timestamp: str
    health_status: str  # NOMINAL, WARNING, CRITICAL
    latitude: float
    longitude: float
    speed_kmh: float
    odometer_km: float
    vibration: float
    dtc_codes: List[str] = Field(default_factory=list)
    oil_pressure_kpa: Optional[float] = None
    coolant_temp_c: Optional[float] = None
    engine_rpm: Optional[float] = None
    battery_voltage_v: Optional[float] = None
    soc_pct: Optional[float] = None
    pack_voltage_v: Optional[float] = None
    motor_rpm: Optional[float] = None
    cell_temp_delta_c: Optional[float] = None
    updated_at: str


class VehicleAuthoritativeDetail(BaseModel):
    """Authoritative normalized relational record from PostgreSQL 16."""
    vehicle_id: str
    vin: str
    tenant_id: str
    license_plate: Optional[str] = None
    manufacture_year: int
    status: str
    initial_odometer_km: float
    created_at: str
    updated_at: str
    fleet: Dict[str, Any]
    depot: Dict[str, Any]
    model: VehicleModelSpecs


class VehicleDetailResponse(BaseModel):
    """Comprehensive vehicle view cleanly distinguishing authoritative metadata from transient telemetry."""
    vin: str
    authoritative: VehicleAuthoritativeDetail
    transient_state: Optional[VehicleHotState] = None


class VehicleLocation(BaseModel):
    latitude: float
    longitude: float


class VehicleAlertSummary(BaseModel):
    unacknowledged_alert_count: int
    latest_severity: Optional[str] = None
    latest_fault_type: Optional[str] = None
    latest_alert_message: Optional[str] = None
    latest_alert_timestamp: Optional[str] = None


class VehicleHealthResponse(BaseModel):
    """Consolidated operational health status for dashboard monitoring."""
    vin: str
    current_health_state: str  # NOMINAL, WARNING, CRITICAL
    latest_telemetry_timestamp: Optional[str] = None
    latest_sequence_number: Optional[int] = None
    location: Optional[VehicleLocation] = None
    speed_kmh: Optional[float] = None
    odometer_km: Optional[float] = None
    alert_summary: VehicleAlertSummary
