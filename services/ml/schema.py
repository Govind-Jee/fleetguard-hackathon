"""
FleetGuard Pulse - Predictive Maintenance ML Schemas.
Defines feature contracts, observation models, and prediction schemas.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


# Canonical ordered list of features expected by the model pipeline
FEATURE_NAMES: List[str] = [
    # Common cross-powertrain telemetry features
    "speed_mean",
    "speed_std",
    "vibration_mean",
    "vibration_std",
    "vibration_max",
    "odometer_delta",
    "dtc_count",
    "anomaly_count",
    "telemetry_event_count",
    # ICE / HEV features
    "coolant_temp_mean",
    "coolant_temp_std",
    "coolant_temp_trend",
    "oil_pressure_mean",
    "oil_pressure_min",
    "oil_pressure_trend",
    "engine_rpm_mean",
    "engine_rpm_std",
    "battery_voltage_mean",
    # HEV / BEV features
    "soc_mean",
    "soc_min",
    "soc_drop_rate",
    "pack_voltage_mean",
    "cell_temp_delta_mean",
    "cell_temp_delta_max",
    # Maintenance lifecycle context
    "days_since_last_maintenance",
    "km_since_last_maintenance",
]


class ObservationRecord(BaseModel):
    """Metadata and feature snapshot at an exact prediction cutoff timestamp t."""
    observation_id: str
    vin: str
    vehicle_type: str  # ICE, HEV, BEV
    observation_time: str
    window_start_time: str
    horizon_end_time: str
    # Future outcome metadata (strictly for ground truth labeling, NOT model features)
    future_event_time: Optional[str] = None
    future_event_type: Optional[str] = None
    target_7d: int = Field(..., ge=0, le=1)
    # Features dictionary strictly computed from [window_start_time, observation_time]
    features: Dict[str, Optional[float]]


class FeatureExplanation(BaseModel):
    """Component contribution to log-odds prediction."""
    feature_name: str
    feature_value: Optional[float]
    standardized_value: float
    coefficient: float
    contribution: float  # coefficient * standardized_value
    direction: str  # INCREASES_RISK or REDUCES_RISK


class PredictionResponse(BaseModel):
    """Inference output schema for predictive maintenance risk estimation."""
    vin: str
    prediction_timestamp: str
    probability_7d: float = Field(..., ge=0.0, le=1.0)
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    predicted_maintenance_required: bool
    decision_threshold: float
    top_risk_factors: List[FeatureExplanation]
    protective_factors: List[FeatureExplanation]
    model_version: str
