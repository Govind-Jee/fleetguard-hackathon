"""
Unit tests for FleetGuard Pulse Stream Processing Pipeline.
Covers validation, deduplication, ordering protection, statistics, and anomaly detection.
"""

import json
import math
import pytest
from unittest.mock import MagicMock

from services.simulator.schema import TelemetryEvent, VehicleType
from services.stream_processor.validator import TelemetryValidator
from services.stream_processor.dedup import CountingBloomFilter, TwoTierDeduplicator
from services.stream_processor.ordering import OutOfOrderProtector
from services.stream_processor.statistics import (
    WelfordAccumulator,
    EWMASmoother,
    VehicleStreamingStats,
    StreamingStatsRegistry,
)
from services.stream_processor.detector import HealthAnomalyDetector
from services.stream_processor.models import AlertSeverity, CriticalAlert
from services.stream_processor.metrics import StreamMetrics


def create_sample_ice_event(
    vin: str = "1HGCR2F83HA000001",
    seq: int = 1,
    vibration: float = 0.5,
    coolant: float = 90.0,
    oil_press: float = 300.0,
    dtc: list = None,
) -> TelemetryEvent:
    return TelemetryEvent(
        schema_version="1.0",
        event_id=f"evt-{vin}-{seq}",
        vin=vin,
        timestamp="2026-10-01T12:00:00.000000Z",
        sequence_number=seq,
        vehicle_type=VehicleType.ICE,
        latitude=37.7749,
        longitude=-122.4194,
        speed_kmh=60.0,
        odometer_km=15000.0,
        vibration=vibration,
        dtc_codes=dtc or [],
        oil_pressure_kpa=oil_press,
        coolant_temp_c=coolant,
        engine_rpm=2200.0,
        battery_voltage_v=14.1,
    )


def create_sample_bev_event(
    vin: str = "5YJSA1E28HF000002",
    seq: int = 1,
    soc: float = 80.0,
    cell_delta: float = 1.2,
    vibration: float = 0.3,
) -> TelemetryEvent:
    return TelemetryEvent(
        schema_version="1.0",
        event_id=f"evt-{vin}-{seq}",
        vin=vin,
        timestamp="2026-10-01T12:00:00.000000Z",
        sequence_number=seq,
        vehicle_type=VehicleType.BEV,
        latitude=34.0522,
        longitude=-118.2437,
        speed_kmh=75.0,
        odometer_km=8500.0,
        vibration=vibration,
        dtc_codes=[],
        soc_pct=soc,
        pack_voltage_v=395.0,
        motor_rpm=4500.0,
        cell_temp_delta_c=cell_delta,
    )


# --- 1. Validator Tests ---

def test_validator_success():
    metrics = StreamMetrics()
    validator = TelemetryValidator(metrics=metrics)
    event = create_sample_ice_event()
    raw_json = event.model_dump_json()

    parsed, err = validator.validate(raw_json)
    assert err is None
    assert parsed is not None
    assert parsed.vin == event.vin
    assert metrics.snapshot()["events_valid"] == 1


def test_validator_malformed_json():
    metrics = StreamMetrics()
    validator = TelemetryValidator(metrics=metrics)
    parsed, err = validator.validate("NOT A VALID JSON {{{")
    assert parsed is None
    assert "JSON decode failure" in err
    assert metrics.snapshot()["events_invalid"] == 1


def test_validator_schema_violation():
    metrics = StreamMetrics()
    validator = TelemetryValidator(metrics=metrics)
    # Missing required powertrain field for ICE
    invalid_data = {
        "schema_version": "1.0",
        "event_id": "bad-1",
        "vin": "1HGCR2F83HA000001",
        "timestamp": "2026-10-01T12:00:00Z",
        "sequence_number": 1,
        "vehicle_type": "ICE",
        "latitude": 37.0,
        "longitude": -122.0,
        "speed_kmh": 50.0,
        "odometer_km": 1000.0,
        "vibration": 0.5,
        # missing oil_pressure_kpa, coolant_temp_c, engine_rpm
    }
    parsed, err = validator.validate(invalid_data)
    assert parsed is None
    assert "Schema validation error" in err
    assert metrics.snapshot()["events_invalid"] == 1


# --- 2. Deduplication Tests ---

def test_counting_bloom_filter_membership():
    cbf = CountingBloomFilter(capacity=1000, error_rate=0.01)
    cbf.add("event-001")
    assert cbf.contains("event-001") is True
    assert cbf.contains("event-999") is False

    # Test removal
    removed = cbf.remove("event-001")
    assert removed is True
    assert cbf.contains("event-001") is False


def test_two_tier_deduplicator():
    metrics = StreamMetrics()
    dedup = TwoTierDeduplicator(capacity=1000, exact_cache_size=500, metrics=metrics)

    # First arrival: not a duplicate
    assert dedup.is_duplicate("evt-12345") is False

    # Second arrival of same event: duplicate detected!
    assert dedup.is_duplicate("evt-12345") is True
    assert metrics.snapshot()["events_duplicate"] == 1

    # Distinct event: not duplicate
    assert dedup.is_duplicate("evt-67890") is False


# --- 3. Out-of-Order Protector Tests ---

def test_out_of_order_protection():
    metrics = StreamMetrics()
    protector = OutOfOrderProtector(metrics=metrics)

    vin = "1HGCR2F83HA000001"

    # seq 1 arrives
    in_order, last_seq = protector.check_and_update(vin, 1, "2026-10-01T12:00:00Z")
    assert in_order is True
    assert last_seq is None

    # seq 2 arrives
    in_order, last_seq = protector.check_and_update(vin, 2, "2026-10-01T12:00:01Z")
    assert in_order is True
    assert last_seq == 1

    # seq 1 re-arrives (stale / out-of-order)
    in_order, last_seq = protector.check_and_update(vin, 1, "2026-10-01T12:00:00Z")
    assert in_order is False
    assert last_seq == 2
    assert metrics.snapshot()["events_out_of_order"] == 1

    # seq 5 arrives (gap, but in order)
    in_order, last_seq = protector.check_and_update(vin, 5, "2026-10-01T12:00:05Z")
    assert in_order is True
    assert last_seq == 2


# --- 4. Statistics Tests (Welford & EWMA) ---

def test_welford_accumulator():
    w = WelfordAccumulator()
    samples = [10.0, 20.0, 30.0, 40.0, 50.0]
    for s in samples:
        w.update(s)

    assert w.count == 5
    assert w.mean == 30.0
    # Sample variance for [10, 20, 30, 40, 50] is 250.0
    assert pytest.approx(w.sample_variance, 0.001) == 250.0
    # Standard deviation is sqrt(250) ~= 15.811
    assert pytest.approx(w.standard_deviation, 0.001) == math.sqrt(250.0)

    # Z-score for 50.0: (50 - 30) / 15.811388 ~= 1.2649
    expected_z = 20.0 / math.sqrt(250.0)
    assert pytest.approx(w.z_score(50.0), 0.001) == expected_z


def test_ewma_smoother():
    smoother = EWMASmoother(alpha=0.5)
    # First value initializes value
    assert smoother.update(100.0) == 100.0
    # Second value: 0.5 * 50 + 0.5 * 100 = 75.0
    assert smoother.update(50.0) == 75.0
    # Third value: 0.5 * 50 + 0.5 * 75 = 62.5
    assert smoother.update(50.0) == 62.5


# --- 5. Health & Anomaly Detector Tests ---

def test_detector_normal_event():
    detector = HealthAnomalyDetector()
    stats = VehicleStreamingStats()
    event = create_sample_ice_event()

    severity, alerts = detector.evaluate(event, stats)
    assert severity == AlertSeverity.NORMAL
    assert len(alerts) == 0


def test_detector_excessive_vibration():
    detector = HealthAnomalyDetector()
    stats = VehicleStreamingStats()
    event = create_sample_ice_event(vibration=4.5)

    severity, alerts = detector.evaluate(event, stats)
    assert severity == AlertSeverity.CRITICAL
    assert len(alerts) == 1
    assert alerts[0].fault_type == "EXCESSIVE_VIBRATION"
    assert alerts[0].severity == AlertSeverity.CRITICAL


def test_detector_engine_overheat():
    detector = HealthAnomalyDetector()
    stats = VehicleStreamingStats()
    event = create_sample_ice_event(coolant=118.5)

    severity, alerts = detector.evaluate(event, stats)
    assert severity == AlertSeverity.CRITICAL
    assert any(a.fault_type == "ENGINE_OVERHEAT" for a in alerts)


def test_detector_oil_pressure_loss():
    detector = HealthAnomalyDetector()
    stats = VehicleStreamingStats()
    event = create_sample_ice_event(oil_press=60.0)

    severity, alerts = detector.evaluate(event, stats)
    assert severity == AlertSeverity.CRITICAL
    assert any(a.fault_type == "OIL_PRESSURE_CRITICAL_LOW" for a in alerts)


def test_detector_bev_thermal_runaway_risk():
    detector = HealthAnomalyDetector()
    stats = VehicleStreamingStats()
    event = create_sample_bev_event(cell_delta=9.2)

    severity, alerts = detector.evaluate(event, stats)
    assert severity == AlertSeverity.CRITICAL
    assert any(a.fault_type == "BATTERY_THERMAL_RUNAWAY_RISK" for a in alerts)


def test_detector_critical_dtc_code():
    detector = HealthAnomalyDetector()
    stats = VehicleStreamingStats()
    event = create_sample_ice_event(dtc=["P0217"])

    severity, alerts = detector.evaluate(event, stats)
    assert severity == AlertSeverity.CRITICAL
    assert any("P0217" in a.fault_type for a in alerts)


def test_duplicate_event_alert_and_state_idempotency():
    """
    Focused idempotency audit test:
    Proves that when the exact same event_id is delivered twice:
    1. The duplicate event is suppressed by deduplication.
    2. No second critical alert is emitted for this event_id.
    3. No second state transition occurs in Redis hot state.
    4. Explicitly counts alerts emitted by event_id.
    """
    metrics = StreamMetrics()
    validator = TelemetryValidator(metrics=metrics)
    dedup = TwoTierDeduplicator(capacity=1000, exact_cache_size=500, metrics=metrics)
    ordering = OutOfOrderProtector(metrics=metrics)
    stats_reg = StreamingStatsRegistry()
    detector = HealthAnomalyDetector(metrics=metrics)

    published_alerts = []
    mock_publisher = MagicMock()
    mock_publisher.publish_alert.side_effect = lambda a: published_alerts.append(a)

    state_updates = []
    mock_state = MagicMock()
    mock_state.update_vehicle_state.side_effect = lambda **kw: state_updates.append(kw)

    # Event with severe fault (coolant 118.5 C)
    event = create_sample_ice_event(coolant=118.5)
    raw_payload = event.model_dump_json().encode("utf-8")

    def run_pipeline(payload):
        ev, _ = validator.validate(payload)
        if ev is None:
            return False
        if dedup.is_duplicate(ev.event_id):
            return False
        in_order, _ = ordering.check_and_update(ev.vin, ev.sequence_number, ev.timestamp)
        stats = stats_reg.get_or_create(ev.vin)
        severity, alerts = detector.evaluate(ev, stats)
        if in_order:
            mock_state.update_vehicle_state(
                event=ev, health_status=severity, latest_alert=alerts[0] if alerts else None
            )
        for a in alerts:
            mock_publisher.publish_alert(a)
        return True

    # 1. First delivery: event processed, alert emitted, state updated
    res1 = run_pipeline(raw_payload)
    assert res1 is True
    alerts_for_event = [a for a in published_alerts if a.event_id == event.event_id]
    assert len(alerts_for_event) == 1
    assert alerts_for_event[0].fault_type == "ENGINE_OVERHEAT"
    assert len(state_updates) == 1
    initial_alert_count = len(alerts_for_event)

    # 2. Second delivery: exact same event_id re-transmitted
    res2 = run_pipeline(raw_payload)
    assert res2 is False  # Suppressed by deduplicator

    # 3. Verify no second alert was emitted for this event_id
    alerts_after_dup = [a for a in published_alerts if a.event_id == event.event_id]
    assert len(alerts_after_dup) == initial_alert_count == 1
    assert mock_publisher.publish_alert.call_count == 1

    # 4. Verify no second state transition occurred
    assert len(state_updates) == 1
    assert mock_state.update_vehicle_state.call_count == 1

    # 5. Verify metrics record duplicate suppression
    assert metrics.snapshot()["events_duplicate"] == 1
