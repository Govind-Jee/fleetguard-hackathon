"""
FleetGuard Pulse - Unit Tests for Historical Batch Analytics.
Tests time-window validation, analytical data models, ClickHouse failure handling,
and empty-result boundary conditions.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import pytest

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
from services.api.exceptions import DatabaseUnavailableError, ResourceNotFoundError


def test_time_window_valid_creation():
    """Verify standard ISO parsing and time window creation."""
    start = "2026-09-01T00:00:00Z"
    end = "2026-09-15T00:00:00Z"
    window = TimeWindow.create(start_str=start, end_str=end)
    assert window.start_time < window.end_time
    assert (window.end_time - window.start_time).days == 14


def test_time_window_default_fallback():
    """Verify default fallback to 30 days when dates omitted."""
    window = TimeWindow.create()
    diff = window.end_time - window.start_time
    assert diff.days in (29, 30)


def test_time_window_inverted_dates_rejected():
    """Reject start_time >= end_time with descriptive ValueError."""
    start = "2026-09-20T00:00:00Z"
    end = "2026-09-10T00:00:00Z"
    with pytest.raises(ValueError, match="must be strictly before"):
        TimeWindow.create(start_str=start, end_str=end)


def test_time_window_equal_dates_rejected():
    """Reject start_time == end_time."""
    same = "2026-09-10T12:00:00Z"
    with pytest.raises(ValueError, match="must be strictly before"):
        TimeWindow.create(start_str=same, end_str=same)


def test_time_window_excessive_span_rejected():
    """Reject time windows greater than 90 days for interactive OLAP protection."""
    start = "2026-01-01T00:00:00Z"
    end = "2026-05-01T00:00:00Z"  # ~120 days
    with pytest.raises(ValueError, match="exceeds maximum interactive span of 90 days"):
        TimeWindow.create(start_str=start, end_str=end)


def test_time_window_malformed_iso_rejected():
    """Reject non-ISO timestamp string formatting."""
    with pytest.raises(ValueError, match="Expected ISO-8601"):
        TimeWindow.create(start_str="not-a-timestamp", end_str="2026-09-10T00:00:00Z")


def test_models_validation():
    """Test instantiation and constraints of Pydantic analytical models."""
    metrics = FleetReliabilityMetrics(
        tenant_id="a0000000-0000-0000-0000-000000000001",
        start_time="2026-09-01T00:00:00Z",
        end_time="2026-09-15T00:00:00Z",
        total_monitored_vehicles=100,
        telemetry_event_count=50000,
        fault_event_count=120,
        critical_fault_count=15,
        affected_vehicle_count=8,
        fault_rate=0.0024,
    )
    assert metrics.fault_rate == 0.0024
    assert metrics.critical_fault_count == 15

    freq = FaultFrequencyResponse(
        tenant_id="a0000000-0000-0000-0000-000000000001",
        start_time="2026-09-01T00:00:00Z",
        end_time="2026-09-15T00:00:00Z",
        total_fault_events=50,
        faults=[
            FaultFrequencyItem(
                fault_type="P0524",
                occurrence_count=30,
                affected_vehicle_count=5,
                percentage=60.0,
            )
        ],
    )
    assert len(freq.faults) == 1
    assert freq.faults[0].percentage == 60.0


def test_analytics_service_clickhouse_unavailable():
    """Verify service raises DatabaseUnavailableError when ClickHouse client is None."""
    mock_pg = MagicMock()
    with pytest.raises(DatabaseUnavailableError):
        BatchAnalyticsService.get_fleet_reliability(
            ch_client=None,
            pg_conn=mock_pg,
            tenant_id="tenant-123",
        )


def test_analytics_service_empty_tenant_vehicles():
    """Verify neutral zeroed response when tenant has zero assigned vehicles."""
    mock_ch = MagicMock()
    mock_pg = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []
    mock_pg.cursor.return_value.__enter__.return_value = mock_cur

    res = BatchAnalyticsService.get_fleet_reliability(
        ch_client=mock_ch,
        pg_conn=mock_pg,
        tenant_id="tenant-empty",
    )
    assert res.total_monitored_vehicles == 0
    assert res.telemetry_event_count == 0
    assert res.fault_rate == 0.0
    # ClickHouse query must not even be executed
    mock_ch.query.assert_not_called()


def test_analytics_service_fleet_not_found():
    """Verify ResourceNotFoundError when specified fleet_id does not belong to tenant."""
    mock_ch = MagicMock()
    mock_pg = MagicMock()
    mock_cur = MagicMock()
    # Fleet check returns None
    mock_cur.fetchone.return_value = None
    mock_pg.cursor.return_value.__enter__.return_value = mock_cur

    with pytest.raises(ResourceNotFoundError):
        BatchAnalyticsService.get_fleet_reliability(
            ch_client=mock_ch,
            pg_conn=mock_pg,
            tenant_id="tenant-1",
            fleet_id="fleet-nonexistent",
        )
