"""
FleetGuard Pulse - ClickHouse Batch Analytics Integration Tests.
Executes OLAP queries against real ClickHouse container (port 8123) and PostgreSQL (port 5433).
Verifies fleet summary, fault frequency, MTBF, trends, degradation ranking,
and deduplication-on-read semantics.
"""

from datetime import datetime, timezone, timedelta
import os
import uuid
import clickhouse_connect
import psycopg2
import pytest

from services.analytics.models import TimeWindow
from services.analytics.service import BatchAnalyticsService

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5433"))
PG_DB = os.getenv("POSTGRES_DB", "fleetguard")
PG_USER = os.getenv("POSTGRES_USER", "fleetguard_user")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "fleetguard_dev_password")

CH_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CH_PORT = int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123"))
CH_USER = os.getenv("CLICKHOUSE_USER", "default")
CH_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "fleetguard_dev_password")
CH_DB = os.getenv("CLICKHOUSE_DB", "fleetguard_analytics")

METRO_TENANT_ID = "a0000000-0000-0000-0000-000000000001"


@pytest.fixture(scope="module")
def pg_conn():
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
    )
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def ch_client():
    client = clickhouse_connect.get_client(
        host=CH_HOST,
        port=CH_PORT,
        username=CH_USER,
        password=CH_PASSWORD,
        database=CH_DB,
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def seeded_telemetry(ch_client, pg_conn):
    """Seed synthetic telemetry for test VINs to verify analytical queries deterministically."""
    # Fetch real VIN from Metro Transit tenant (offset by 50 to avoid collision with live-telemetry test VINs)
    with pg_conn.cursor() as cur:
        cur.execute("SELECT vin FROM vehicles WHERE tenant_id = %s OFFSET 50 LIMIT 3;", (METRO_TENANT_ID,))
        vins = [r[0] for r in cur.fetchall()]
        assert len(vins) >= 3, "Requires at least 3 seeded vehicles"

    vin_healthy, vin_faulty, vin_critical = vins[0], vins[1], vins[2]
    now = datetime.now(timezone.utc)
    base_ts = now - timedelta(days=2)

    rows = []
    # Vehicle 1: 5 Nominal events
    for i in range(5):
        ts = base_ts + timedelta(hours=i * 2)
        rows.append([
            uuid.uuid4(), vin_healthy, ts, 1000 + i, "ICE", 40.71, -74.00,
            60.0, 10000.0 + i * 50, 0.25, [], 350.0, 90.0, 2200.0, 13.8, None, None, None, None
        ])

    # Vehicle 2: 3 Warning events (Elevated vibration & Coolant warning)
    for i in range(3):
        ts = base_ts + timedelta(hours=i * 3)
        rows.append([
            uuid.uuid4(), vin_faulty, ts, 2000 + i, "ICE", 40.72, -74.01,
            45.0, 15000.0 + i * 30, 2.8, ["P0117"], 220.0, 108.0, 2500.0, 13.5, None, None, None, None
        ])

    # Vehicle 3: 4 Events with 2 distinct Critical failure incidents separated by 5 hours (for MTBF)
    # Incident 1 (events at t and t+10s - debounced into 1 incident)
    ts1 = base_ts + timedelta(hours=1)
    rows.append([
        uuid.uuid4(), vin_critical, ts1, 3000, "ICE", 40.73, -74.02,
        20.0, 25000.0, 0.4, ["P0524"], 65.0, 118.0, 1500.0, 12.8, None, None, None, None
    ])
    rows.append([
        uuid.uuid4(), vin_critical, ts1 + timedelta(seconds=10), 3001, "ICE", 40.73, -74.02,
        15.0, 25000.1, 0.5, ["P0524"], 60.0, 119.0, 1400.0, 12.8, None, None, None, None
    ])
    # Incident 2 (event at t + 6 hours - distinct incident > 1800s later)
    ts2 = base_ts + timedelta(hours=7)
    rows.append([
        uuid.uuid4(), vin_critical, ts2, 3002, "ICE", 40.73, -74.02,
        0.0, 25050.0, 4.5, ["P0300"], 50.0, 122.0, 1200.0, 12.5, None, None, None, None
    ])

    cols = [
        "event_id", "vin", "timestamp", "sequence_number", "vehicle_type", "latitude", "longitude",
        "speed_kmh", "odometer_km", "vibration", "dtc_codes", "oil_pressure_kpa", "coolant_temp_c",
        "engine_rpm", "battery_voltage_v", "soc_pct", "pack_voltage_v", "motor_rpm", "cell_temp_delta_c"
    ]
    ch_client.insert("vehicle_telemetry", rows, column_names=cols)

    try:
        yield {
            "healthy_vin": vin_healthy,
            "faulty_vin": vin_faulty,
            "critical_vin": vin_critical,
            "start_time": base_ts - timedelta(hours=1),
            "end_time": now + timedelta(hours=1),
        }
    finally:
        ch_client.command(
            f"ALTER TABLE vehicle_telemetry DELETE WHERE vin IN ('{vin_healthy}', '{vin_faulty}', '{vin_critical}')"
        )


def test_clickhouse_fleet_reliability_summary(ch_client, pg_conn, seeded_telemetry):
    """Test fleet reliability summary returns correct totals, fault counts, and rates."""
    window = TimeWindow(
        start_time=seeded_telemetry["start_time"],
        end_time=seeded_telemetry["end_time"],
    )
    res = BatchAnalyticsService.get_fleet_reliability(
        ch_client=ch_client,
        pg_conn=pg_conn,
        tenant_id=METRO_TENANT_ID,
        time_window=window,
    )

    assert res.total_monitored_vehicles >= 3
    assert res.telemetry_event_count >= 11
    assert res.fault_event_count >= 6  # 3 warning + 3 critical
    assert res.critical_fault_count >= 3  # 3 critical events
    assert res.affected_vehicle_count >= 2  # faulty + critical
    assert 0.0 < res.fault_rate <= 1.0


def test_clickhouse_fault_frequency(ch_client, pg_conn, seeded_telemetry):
    """Test fault frequency groups DTCs and physical fault classifications with percentages."""
    window = TimeWindow(
        start_time=seeded_telemetry["start_time"],
        end_time=seeded_telemetry["end_time"],
    )
    res = BatchAnalyticsService.get_fault_frequency(
        ch_client=ch_client,
        pg_conn=pg_conn,
        tenant_id=METRO_TENANT_ID,
        time_window=window,
    )

    assert res.total_fault_events > 0
    assert len(res.faults) > 0

    fault_types = {f.fault_type for f in res.faults}
    # Check that our seeded faults are detected
    assert "P0524" in fault_types or "ENGINE_OVERHEAT" in fault_types or "OIL_PRESSURE_CRITICAL_LOW" in fault_types

    # Ensure percentages are non-zero and sum to ~100%
    total_pct = sum(f.percentage for f in res.faults)
    assert 99.0 <= total_pct <= 101.0


def test_clickhouse_mtbf_calculation(ch_client, pg_conn, seeded_telemetry):
    """Test MTBF calculates empirical intervals between consecutive debounced failure incidents."""
    window = TimeWindow(
        start_time=seeded_telemetry["start_time"],
        end_time=seeded_telemetry["end_time"],
    )
    res = BatchAnalyticsService.get_mtbf(
        ch_client=ch_client,
        pg_conn=pg_conn,
        tenant_id=METRO_TENANT_ID,
        time_window=window,
    )

    assert res.total_failure_incidents >= 2
    assert res.total_operating_hours >= 0.0
    # Between ts1 and ts2 is ~6 hours interval
    if res.mean_mtbf_hours is not None:
        assert res.mean_mtbf_hours > 0.0
        assert res.min_tbf_hours is not None
        assert res.max_tbf_hours is not None


def test_clickhouse_reliability_trends(ch_client, pg_conn, seeded_telemetry):
    """Test time-bucketed trend grouping by day."""
    window = TimeWindow(
        start_time=seeded_telemetry["start_time"],
        end_time=seeded_telemetry["end_time"],
    )
    res = BatchAnalyticsService.get_reliability_trend(
        ch_client=ch_client,
        pg_conn=pg_conn,
        tenant_id=METRO_TENANT_ID,
        time_window=window,
        granularity="day",
    )

    assert len(res.trends) > 0
    first_bucket = res.trends[0]
    assert first_bucket.vehicles_observed > 0
    assert first_bucket.telemetry_event_count > 0
    assert 0.0 <= first_bucket.fault_rate <= 1.0


def test_clickhouse_vehicle_degradation_ranking(ch_client, pg_conn, seeded_telemetry):
    """Test bounded degradation ranking prioritizes assets with worsening condition."""
    window = TimeWindow(
        start_time=seeded_telemetry["start_time"],
        end_time=seeded_telemetry["end_time"],
    )
    res = BatchAnalyticsService.get_vehicle_degradation_ranking(
        ch_client=ch_client,
        pg_conn=pg_conn,
        tenant_id=METRO_TENANT_ID,
        time_window=window,
        limit=5,
    )

    assert len(res.ranked_vehicles) <= 5
    assert len(res.ranked_vehicles) > 0

    # Ensure ranking is sorted descending by degradation_score
    scores = [v.degradation_score for v in res.ranked_vehicles]
    assert scores == sorted(scores, reverse=True)

    # Critical VIN should have a high degradation score and level ELEVATED or SEVERE
    critical_vin = seeded_telemetry["critical_vin"]
    matching = [v for v in res.ranked_vehicles if v.vin == critical_vin]
    if matching:
        assert matching[0].degradation_score >= 40.0
        assert matching[0].degradation_level in ("ELEVATED", "SEVERE")


def test_clickhouse_deduplication_on_read(ch_client):
    """Verify that duplicate events (identical event_id & sorting key) are NOT double counted."""
    test_vin = "TEST_DEDUP_CH_999"
    ev_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    row = [
        ev_id, test_vin, now, 9999, "ICE", 40.0, -74.0, 50.0, 100.0, 0.3,
        ["P0117"], 300.0, 95.0, 2000.0, 13.8, None, None, None, None
    ]
    cols = [
        "event_id", "vin", "timestamp", "sequence_number", "vehicle_type", "latitude", "longitude",
        "speed_kmh", "odometer_km", "vibration", "dtc_codes", "oil_pressure_kpa", "coolant_temp_c",
        "engine_rpm", "battery_voltage_v", "soc_pct", "pack_voltage_v", "motor_rpm", "cell_temp_delta_c"
    ]

    # Insert original and exact duplicate in separate micro-batch blocks
    ch_client.insert("vehicle_telemetry", [row], column_names=cols)
    ch_client.insert("vehicle_telemetry", [row], column_names=cols)

    try:
        # Raw count without FINAL has duplicate rows before background merge
        raw_count = ch_client.command(f"SELECT count() FROM vehicle_telemetry WHERE vin = '{test_vin}'")
        assert raw_count == 2, "Expected 2 physical rows inserted"

        # Query with FINAL performs deduplication on read
        final_count = ch_client.command(f"SELECT count() FROM vehicle_telemetry FINAL WHERE vin = '{test_vin}'")
        assert final_count == 1, "ReplacingMergeTree FINAL must deduplicate to exactly 1 record"

        # Unique event_id aggregate also guarantees exactly 1
        uniq_count = ch_client.command(f"SELECT uniqExact(event_id) FROM vehicle_telemetry WHERE vin = '{test_vin}'")
        assert uniq_count == 1, "uniqExact(event_id) must count 1"
    finally:
        ch_client.command(f"ALTER TABLE vehicle_telemetry DELETE WHERE vin = '{test_vin}'")


def test_clickhouse_out_of_order_event_handling(ch_client):
    """Verify that out-of-order events are ordered chronologically by sorting key during query and window functions."""
    test_vin = "TEST_OOO_CH_999"
    now = datetime.now(timezone.utc)

    # Insert event with seq 2 (later time t2) first, then seq 1 (earlier time t1)
    t2 = now
    t1 = now - timedelta(hours=2)
    # Both events are critical failures separated by 2 hours
    row2 = [
        uuid.uuid4(), test_vin, t2, 2, "ICE", 40.0, -74.0, 50.0, 100.1, 0.3,
        ["P0217"], 300.0, 118.0, 2000.0, 13.8, None, None, None, None
    ]
    row1 = [
        uuid.uuid4(), test_vin, t1, 1, "ICE", 40.0, -74.0, 50.0, 100.0, 0.3,
        ["P0217"], 300.0, 118.0, 2000.0, 13.8, None, None, None, None
    ]

    cols = [
        "event_id", "vin", "timestamp", "sequence_number", "vehicle_type", "latitude", "longitude",
        "speed_kmh", "odometer_km", "vibration", "dtc_codes", "oil_pressure_kpa", "coolant_temp_c",
        "engine_rpm", "battery_voltage_v", "soc_pct", "pack_voltage_v", "motor_rpm", "cell_temp_delta_c"
    ]
    # Ingestion order: row2 (t2) followed by row1 (t1)
    ch_client.insert("vehicle_telemetry", [row2, row1], column_names=cols)

    try:
        res = ch_client.query(f"SELECT sequence_number FROM vehicle_telemetry FINAL WHERE vin = '{test_vin}' ORDER BY timestamp ASC")
        seqs = [r[0] for r in res.result_rows]
        assert seqs == [1, 2], "Chronological order must be preserved regardless of insertion sequence"

        # Verify MTBF window function evaluates t1 before t2 despite arrival order
        from services.analytics.queries import MTBF_SQL
        mtbf_res = ch_client.query(
            MTBF_SQL,
            parameters={
                "vins": (test_vin,),
                "start_time": t1 - timedelta(minutes=10),
                "end_time": t2 + timedelta(minutes=10),
            },
        )
        total_incidents, intervals_count, mean_mtbf_hours, _, _, _, _, _ = mtbf_res.result_rows[0]
        assert total_incidents == 2
        assert intervals_count == 1
        assert mean_mtbf_hours == pytest.approx(2.0, rel=1e-2), "MTBF window function must order chronologically to produce 2.0 hr interval"
    finally:
        ch_client.command(f"ALTER TABLE vehicle_telemetry DELETE WHERE vin = '{test_vin}'")
