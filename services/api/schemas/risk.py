"""
FleetGuard Pulse - Predictive Risk Schemas.
Represents 7-day failure probability estimates and local additive explainability factors.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class RiskFactorExplanation(BaseModel):
    feature_name: str
    feature_value: Optional[float] = None
    standardized_value: float
    coefficient: float
    contribution: float
    direction: str  # INCREASES_RISK or REDUCES_RISK


class VehicleRiskResponse(BaseModel):
    """
    Predictive maintenance estimation response.
    Estimates the probability that a vehicle will require maintenance or experience
    a failure within the next 7 days based on recent operational telemetry trends.
    """
    vin: str
    probability_7d: float = Field(..., ge=0.0, le=1.0, description="Estimated 7-day failure probability")
    predicted_maintenance_required: bool
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    decision_threshold: float
    top_risk_factors: List[RiskFactorExplanation]
    protective_factors: List[RiskFactorExplanation]
    model_version: str
    prediction_timestamp: str
    disclaimer: str = (
        "Statistical risk estimate represents estimated probability of unscheduled maintenance "
        "or mechanical failure within the next 7 days based on longitudinal CAN-bus degradation. "
        "This is an advisory risk score, not a deterministic guarantee of component failure."
    )
