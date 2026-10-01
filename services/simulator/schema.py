"""
FleetGuard Pulse - Telemetry Event Schema

Defines the versioned Pydantic models for connected vehicle telemetry.
Validates common telematics headers alongside powertrain-specific signals for ICE, HEV, and BEV.
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class VehicleType(str, Enum):
    ICE = "ICE"
    HEV = "HEV"
    BEV = "BEV"


class VehicleHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADATION = "DEGRADATION"
    WARNING = "WARNING"
    FAILURE = "FAILURE"


class TelemetryEvent(BaseModel):
    """
    Standardized, versioned connected vehicle telemetry event schema.
    """
    schema_version: str = Field(default="1.0", description="Schema specification version")
    event_id: str = Field(..., description="Unique UUIDv4 event identifier")
    vin: str = Field(..., min_length=17, max_length=17, description="Standardized 17-character VIN")
    timestamp: str = Field(..., description="ISO-8601 UTC timestamp with microsecond precision")
    sequence_number: int = Field(..., ge=1, description="Monotonically increasing sequence number per VIN")
    vehicle_type: VehicleType = Field(..., description="Powertrain classification: ICE, HEV, BEV")
    
    # Kinematic & Spatial
    latitude: float = Field(..., ge=-90.0, le=90.0, description="WGS84 latitude")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="WGS84 longitude")
    speed_kmh: float = Field(..., ge=0.0, le=250.0, description="Vehicle ground speed in km/h")
    odometer_km: float = Field(..., ge=0.0, description="Cumulative vehicle odometer reading in km")
    vibration: float = Field(..., ge=0.0, description="Tri-axial peak acceleration magnitude in G")
    
    # Diagnostic Trouble Codes
    dtc_codes: List[str] = Field(default_factory=list, description="Active OBD-II / UDS diagnostic trouble codes")

    # Powertrain-Specific Signals: ICE & HEV
    oil_pressure_kpa: Optional[float] = Field(None, ge=0.0, le=1000.0, description="Engine oil pressure in kPa")
    coolant_temp_c: Optional[float] = Field(None, ge=-40.0, le=200.0, description="Engine coolant temperature in Celsius")
    engine_rpm: Optional[float] = Field(None, ge=0.0, le=9000.0, description="Internal combustion engine RPM")
    battery_voltage_v: Optional[float] = Field(None, ge=0.0, le=1000.0, description="12V / auxiliary battery voltage")

    # Powertrain-Specific Signals: HEV & BEV
    soc_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="High-voltage battery State of Charge percentage")
    pack_voltage_v: Optional[float] = Field(None, ge=0.0, le=1000.0, description="Traction battery pack voltage")
    motor_rpm: Optional[float] = Field(None, ge=0.0, le=25000.0, description="Electric drive motor RPM")
    cell_temp_delta_c: Optional[float] = Field(None, ge=0.0, le=60.0, description="Max-to-min battery cell temperature delta")

    @field_validator("vin")
    @classmethod
    def validate_vin_format(cls, v: str) -> str:
        clean = v.strip().upper()
        if len(clean) != 17:
            raise ValueError(f"VIN must be exactly 17 characters, got {len(clean)}")
        return clean

    @model_validator(mode="after")
    def validate_powertrain_fields(self) -> "TelemetryEvent":
        """Enforce powertrain-specific presence and consistency rules."""
        if self.vehicle_type == VehicleType.ICE:
            if self.oil_pressure_kpa is None:
                raise ValueError("ICE vehicles require 'oil_pressure_kpa'")
            if self.coolant_temp_c is None:
                raise ValueError("ICE vehicles require 'coolant_temp_c'")
            if self.engine_rpm is None:
                raise ValueError("ICE vehicles require 'engine_rpm'")

        elif self.vehicle_type == VehicleType.HEV:
            if self.oil_pressure_kpa is None:
                raise ValueError("HEV vehicles require 'oil_pressure_kpa'")
            if self.coolant_temp_c is None:
                raise ValueError("HEV vehicles require 'coolant_temp_c'")
            if self.soc_pct is None:
                raise ValueError("HEV vehicles require 'soc_pct'")

        elif self.vehicle_type == VehicleType.BEV:
            if self.pack_voltage_v is None:
                raise ValueError("BEV vehicles require 'pack_voltage_v'")
            if self.soc_pct is None:
                raise ValueError("BEV vehicles require 'soc_pct'")
            if self.cell_temp_delta_c is None:
                raise ValueError("BEV vehicles require 'cell_temp_delta_c'")

        return self
