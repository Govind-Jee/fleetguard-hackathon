"""
FleetGuard Pulse - Stream Processor Data Models & Alert Schemas
"""

from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class AlertSeverity(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class CriticalAlert(BaseModel):
    """
    Standardized payload for real-time safety & mechanical alerts published to 'vehicle.alerts.v1'.
    """
    alert_id: str = Field(..., description="Unique UUIDv4 alert identifier")
    event_id: str = Field(..., description="Originating telemetry event UUID")
    vin: str = Field(..., min_length=17, max_length=17, description="Standardized 17-character VIN")
    timestamp: str = Field(..., description="Timestamp when fault was observed (UTC ISO-8601)")
    severity: AlertSeverity = Field(..., description="Alert severity: WARNING or CRITICAL")
    fault_type: str = Field(..., description="Machine-readable fault classification")
    message: str = Field(..., description="Human-readable actionable alert explanation")
    sequence_number: int = Field(..., description="Sequence number of originating telemetry event")
    metrics_snapshot: Dict[str, Any] = Field(default_factory=dict, description="Key sensor measurements triggering alert")
