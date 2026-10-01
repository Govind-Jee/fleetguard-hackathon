"""
FleetGuard Pulse - Historical Batch Analytics Data Models.
Defines typed schemas and validation for reporting time windows,
reliability summaries, MTBF, fault frequencies, and degradation rankings.
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class TimeWindow(BaseModel):
    """
    Validated time window for batch analytics queries.
    Enforces ISO 8601 parsing, start < end, and maximum query span (90 days).
    """
    start_time: datetime
    end_time: datetime

    @model_validator(mode="after")
    def validate_window(self) -> "TimeWindow":
        if self.start_time >= self.end_time:
            raise ValueError(
                f"Invalid time window: start_time ({self.start_time.isoformat()}) "
                f"must be strictly before end_time ({self.end_time.isoformat()})"
            )
        max_span = timedelta(days=90)
        if (self.end_time - self.start_time) > max_span:
            raise ValueError(
                f"Time window exceeds maximum interactive span of 90 days. "
                f"Requested span: {(self.end_time - self.start_time).days} days."
            )
        return self

    @classmethod
    def create(
        cls,
        start_str: Optional[str] = None,
        end_str: Optional[str] = None,
        default_days: int = 30,
    ) -> "TimeWindow":
        """Factory parsing ISO strings with safe default fallback (past 30 days)."""
        now = datetime.now(timezone.utc)
        if end_str:
            try:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            except ValueError as e:
                raise ValueError(f"Invalid end_time format '{end_str}'. Expected ISO-8601.") from e
        else:
            end_dt = now

        if start_str:
            try:
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except ValueError as e:
                raise ValueError(f"Invalid start_time format '{start_str}'. Expected ISO-8601.") from e
        else:
            start_dt = end_dt - timedelta(days=default_days)

        return cls(start_time=start_dt, end_time=end_dt)


class FleetReliabilityMetrics(BaseModel):
    """Aggregated fleet reliability metrics across analytical telemetry."""
    tenant_id: str
    fleet_id: Optional[str] = None
    start_time: str
    end_time: str
    total_monitored_vehicles: int = Field(..., ge=0)
    telemetry_event_count: int = Field(..., ge=0)
    fault_event_count: int = Field(..., ge=0)
    critical_fault_count: int = Field(..., ge=0)
    affected_vehicle_count: int = Field(..., ge=0)
    fault_rate: float = Field(..., ge=0.0, le=1.0)


class FaultFrequencyItem(BaseModel):
    """Individual fault type occurrence frequency and impacted asset count."""
    fault_type: str
    occurrence_count: int = Field(..., ge=0)
    affected_vehicle_count: int = Field(..., ge=0)
    percentage: float = Field(..., ge=0.0, le=100.0)


class FaultFrequencyResponse(BaseModel):
    """Fault breakdown grouped by fault type and DTC."""
    tenant_id: str
    fleet_id: Optional[str] = None
    start_time: str
    end_time: str
    total_fault_events: int = Field(..., ge=0)
    faults: List[FaultFrequencyItem]


class MTBFMetrics(BaseModel):
    """Mean Time Between Failures metrics for fleet assets."""
    tenant_id: str
    fleet_id: Optional[str] = None
    start_time: str
    end_time: str
    mean_mtbf_hours: Optional[float] = None
    median_mtbf_hours: Optional[float] = None
    min_tbf_hours: Optional[float] = None
    max_tbf_hours: Optional[float] = None
    total_failure_incidents: int = Field(..., ge=0)
    total_operating_hours: float = Field(..., ge=0.0)
    vehicles_evaluated: int = Field(..., ge=0)
    notes: Optional[str] = None


class ReliabilityTrendItem(BaseModel):
    """Time-bucketed trend of vehicle activity, failures, and maintenance."""
    period: str
    vehicles_observed: int = Field(..., ge=0)
    telemetry_event_count: int = Field(..., ge=0)
    failure_events: int = Field(..., ge=0)
    fault_rate: float = Field(..., ge=0.0, le=1.0)
    maintenance_events: int = Field(default=0, ge=0)


class ReliabilityTrendResponse(BaseModel):
    """Chronological series of reliability and maintenance volume."""
    tenant_id: str
    fleet_id: Optional[str] = None
    start_time: str
    end_time: str
    granularity: str = "day"
    trends: List[ReliabilityTrendItem]


class VehicleDegradationItem(BaseModel):
    """Historical telemetry-based condition metrics for a specific asset."""
    vin: str
    vehicle_type: str
    telemetry_events: int = Field(..., ge=0)
    fault_events: int = Field(..., ge=0)
    critical_faults: int = Field(..., ge=0)
    avg_vibration: float
    max_vibration: float
    avg_coolant_temp: Optional[float] = None
    min_oil_pressure: Optional[float] = None
    avg_cell_temp_delta: Optional[float] = None
    degradation_score: float = Field(..., ge=0.0, le=100.0)
    degradation_level: str


class VehicleDegradationResponse(BaseModel):
    """Ranked listing of assets showing historical condition worsening."""
    tenant_id: str
    fleet_id: Optional[str] = None
    start_time: str
    end_time: str
    limit: int
    total_evaluated: int
    ranked_vehicles: List[VehicleDegradationItem]
