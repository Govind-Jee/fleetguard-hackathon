"""
FleetGuard Pulse - Batch Analytics Package.
Provides historical reliability intelligence, fault frequencies, MTBF,
and vehicle degradation ranking from ClickHouse OLAP storage.
"""

from services.analytics.models import (
    FaultFrequencyItem,
    FaultFrequencyResponse,
    FleetReliabilityMetrics,
    MTBFMetrics,
    ReliabilityTrendItem,
    ReliabilityTrendResponse,
    TimeWindow,
    VehicleDegradationItem,
    VehicleDegradationResponse,
)
from services.analytics.service import BatchAnalyticsService

__all__ = [
    "BatchAnalyticsService",
    "TimeWindow",
    "FleetReliabilityMetrics",
    "FaultFrequencyItem",
    "FaultFrequencyResponse",
    "MTBFMetrics",
    "ReliabilityTrendItem",
    "ReliabilityTrendResponse",
    "VehicleDegradationItem",
    "VehicleDegradationResponse",
]
