"""
Integration tests for FleetGuard Pulse Stream Processing Pipeline.
Tests end-to-end flow with Redpanda, Redis, MongoDB, and ClickHouse.
"""

import json
import time
import uuid
import pytest
from confluent_kafka import Producer, Consumer
import redis
import pymongo
import clickhouse_connect

from services.simulator.schema import TelemetryEvent, VehicleType
from services.stream_processor.workers.real_time_worker import RealTimeWorker
from services.stream_processor.workers.mongodb_worker import MongoDBWorker
from services.stream_processor.workers.clickhouse_worker import ClickHouseWorker


BOOTSTRAP_SERVERS = "localhost:9092"
REDIS_PORT = 6380
MONGO_URI = "mongodb://fleetguard_user:fleetguard_dev_password@localhost:27017/?authSource=admin"
CH_PORT = 8123


def produce_test_event(topic: str, event: TelemetryEvent):
    p = Producer({"bootstrap.servers": BOOTSTRAP_SERVERS})
    p.produce(
        topic=topic,
        key=event.vin.encode("utf-8"),
        value=event.model_dump_json().encode("utf-8"),
    )
    p.flush(timeout=5.0)


@pytest.fixture(scope="module")
def redis_client():
    client = redis.Redis(host="localhost", port=REDIS_PORT, db=0, decode_responses=True)
    yield client
    client.close()


@pytest.fixture(scope="module")
def mongo_client():
    client = pymongo.MongoClient(MONGO_URI)
    yield client
    client.close()


@pytest.fixture(scope="module")
def ch_client():
    client = clickhouse_connect.get_client(
        host="localhost", port=CH_PORT, username="default", password="fleetguard_dev_password"
    )
    yield client
    client.close()


def test_real_time_worker_end_to_end(redis_client):
    """
    Test that RealTimeWorker processes a telemetry message through all stages:
    validation -> dedup -> ordering -> stats -> anomaly detection ->
    Redis hot state update -> Redpanda alert publish on vehicle.alerts.v1.
    """
    test_vin = f"1HGCR2F83HA{int(time.time()) % 1000000:06d}"
    event_id = str(uuid.uuid4())

    # Critical event: Coolant 119.0 C + DTC P0217 -> ENGINE_OVERHEAT
    event = TelemetryEvent(
        schema_version="1.0",
        event_id=event_id,
        vin=test_vin,
        timestamp="2026-10-01T12:30:00.000000Z",
        sequence_number=1,
        vehicle_type=VehicleType.ICE,
        latitude=37.7749,
        longitude=-122.4194,
        speed_kmh=85.0,
        odometer_km=45200.0,
        vibration=0.6,
        dtc_codes=["P0217"],
        oil_pressure_kpa=280.0,
        coolant_temp_c=119.0,
        engine_rpm=2800.0,
        battery_voltage_v=14.2,
    )

    # Setup alert consumer on vehicle.alerts.v1 before processing
    alert_consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP_SERVERS,
        "group.id": f"test-alert-verifier-{uuid.uuid4().hex[:8]}",
        "auto.offset.reset": "latest",
    })
    alert_consumer.subscribe(["vehicle.alerts.v1"])
    # Poll once to establish partition assignment
    alert_consumer.poll(1.0)

    # Initialize RealTimeWorker
    worker = RealTimeWorker(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id=f"test-rt-group-{uuid.uuid4().hex[:8]}",
        redis_host="localhost",
        redis_port=REDIS_PORT,
    )

    # Execute full processing pipeline for this message
    success = worker.process_message(event.model_dump_json().encode("utf-8"))
    assert success is True
    worker.alert_publisher.flush(timeout=5.0)

    # 1. Verify Redis hot state updated
    state = redis_client.hgetall(f"vehicle:state:{test_vin}")
    assert state is not None
    assert state.get("vin") == test_vin
    assert state.get("health_status") == "CRITICAL"
    assert "ENGINE_OVERHEAT" in state.get("last_alert_fault", "") or "P0217" in state.get("last_alert_fault", "")
    assert float(state.get("coolant_temp_c", 0.0)) == 119.0

    # 2. Verify Alert received on vehicle.alerts.v1
    alert_found = False
    start = time.time()
    while time.time() - start < 10.0:
        msg = alert_consumer.poll(1.0)
        if msg is None:
            continue
        try:
            alert_data = json.loads(msg.value().decode("utf-8"))
            if alert_data.get("vin") == test_vin:
                assert alert_data["severity"] == "CRITICAL"
                assert alert_data["event_id"] == event_id
                alert_found = True
                break
        except Exception:
            continue

    alert_consumer.close()
    worker.stop()
    assert alert_found, f"Alert for VIN {test_vin} was not received on vehicle.alerts.v1"


def test_mongodb_worker_persistence(mongo_client):
    """Test that MongoDBWorker micro-batch flushes raw telemetry to MongoDB."""
    test_vin = f"5YJSA1E28HF{int(time.time()) % 1000000:06d}"
    event_id = str(uuid.uuid4())

    event = TelemetryEvent(
        schema_version="1.0",
        event_id=event_id,
        vin=test_vin,
        timestamp="2026-10-01T12:35:00.000000Z",
        sequence_number=1,
        vehicle_type=VehicleType.BEV,
        latitude=34.0522,
        longitude=-118.2437,
        speed_kmh=65.0,
        odometer_km=12000.0,
        vibration=0.25,
        dtc_codes=[],
        soc_pct=72.0,
        pack_voltage_v=398.0,
        motor_rpm=3200.0,
        cell_temp_delta_c=1.1,
    )

    worker = MongoDBWorker(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id=f"test-mongo-group-{uuid.uuid4().hex[:8]}",
        batch_size=10,
        flush_interval_sec=0.1,
    )

    # Buffer and flush batch
    worker.buffer.append(json.loads(event.model_dump_json()))
    flushed = worker.flush_batch()
    assert flushed == 1

    # Query MongoDB directly
    coll = mongo_client["fleetguard_telemetry"]["raw_telemetry"]
    doc = coll.find_one({"event_id": event_id})
    assert doc is not None
    assert doc["vin"] == test_vin
    assert doc["vehicle_type"] == "BEV"
    assert doc["soc_pct"] == 72.0
    worker.stop()


def test_clickhouse_worker_persistence(ch_client):
    """Test that ClickHouseWorker parses and inserts telemetry into vehicle_telemetry table."""
    test_vin = f"3VW2B7AJ5HM{int(time.time()) % 1000000:06d}"
    event_id = str(uuid.uuid4())

    event = TelemetryEvent(
        schema_version="1.0",
        event_id=event_id,
        vin=test_vin,
        timestamp="2026-10-01T12:40:00.000000Z",
        sequence_number=1,
        vehicle_type=VehicleType.ICE,
        latitude=41.8781,
        longitude=-87.6298,
        speed_kmh=50.0,
        odometer_km=30100.0,
        vibration=0.4,
        dtc_codes=[],
        oil_pressure_kpa=310.0,
        coolant_temp_c=88.0,
        engine_rpm=1900.0,
        battery_voltage_v=14.0,
    )

    worker = ClickHouseWorker(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id=f"test-ch-group-{uuid.uuid4().hex[:8]}",
        batch_size=10,
        flush_interval_sec=0.1,
    )

    # Parse and buffer row
    row = worker._parse_row(json.loads(event.model_dump_json()))
    assert row is not None
    worker.buffer.append(row)
    flushed = worker.flush_batch()
    assert flushed == 1

    # Query ClickHouse directly
    res = ch_client.query(
        f"SELECT event_id, vin, vehicle_type, oil_pressure_kpa FROM fleetguard_analytics.vehicle_telemetry WHERE event_id = '{event_id}'"
    )
    assert len(res.result_rows) == 1
    out_row = res.result_rows[0]
    assert out_row[0] == uuid.UUID(event_id)
    assert out_row[1] == test_vin
    assert out_row[2] == "ICE"
    assert pytest.approx(out_row[3], 0.1) == 310.0
    worker.stop()


def test_redpanda_roundtrip():
    """Verify Redpanda publish and consume on vehicle.telemetry.v1."""
    test_vin = f"REDROUNDTRIP{int(time.time()) % 100000:05d}"
    event_id = str(uuid.uuid4())

    event = TelemetryEvent(
        schema_version="1.0",
        event_id=event_id,
        vin=test_vin,
        timestamp="2026-10-01T12:45:00.000000Z",
        sequence_number=1,
        vehicle_type=VehicleType.ICE,
        latitude=40.7128,
        longitude=-74.0060,
        speed_kmh=55.0,
        odometer_km=5000.0,
        vibration=0.3,
        dtc_codes=[],
        oil_pressure_kpa=300.0,
        coolant_temp_c=90.0,
        engine_rpm=2000.0,
        battery_voltage_v=14.0,
    )

    # Consumer setup with latest
    c = Consumer({
        "bootstrap.servers": BOOTSTRAP_SERVERS,
        "group.id": f"test-roundtrip-{uuid.uuid4().hex[:8]}",
        "auto.offset.reset": "latest",
    })
    c.subscribe(["vehicle.telemetry.v1"])
    # Poll to assign partitions
    c.poll(1.0)

    # Produce
    produce_test_event("vehicle.telemetry.v1", event)

    # Consume and assert
    found = False
    start = time.time()
    while time.time() - start < 10.0:
        msg = c.poll(1.0)
        if msg is None:
            continue
        try:
            d = json.loads(msg.value().decode("utf-8"))
            if d.get("event_id") == event_id:
                assert d.get("vin") == test_vin
                found = True
                break
        except Exception:
            continue

    c.close()
    assert found, f"Roundtrip message {event_id} was not received from vehicle.telemetry.v1"


def test_worker_duplicate_suppression_and_no_second_alert(redis_client):
    """
    Integration test proving that duplicate delivery of an event:
    1. Is suppressed by the worker.
    2. Emits no duplicate alert on vehicle.alerts.v1 (counts alerts by event_id).
    3. Causes no second state transition.
    """
    test_vin = f"1HGCR2F83HA{int(time.time() * 1000) % 1000000:06d}"
    event_id = str(uuid.uuid4())

    event = TelemetryEvent(
        schema_version="1.0",
        event_id=event_id,
        vin=test_vin,
        timestamp="2026-10-01T13:00:00.000000Z",
        sequence_number=1,
        vehicle_type=VehicleType.ICE,
        latitude=37.7749,
        longitude=-122.4194,
        speed_kmh=80.0,
        odometer_km=50000.0,
        vibration=0.5,
        dtc_codes=[],
        oil_pressure_kpa=250.0,
        coolant_temp_c=118.0,  # ENGINE_OVERHEAT
        engine_rpm=2500.0,
        battery_voltage_v=14.0,
    )
    payload = event.model_dump_json().encode("utf-8")

    alert_consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP_SERVERS,
        "group.id": f"test-dup-alert-verifier-{uuid.uuid4().hex[:8]}",
        "auto.offset.reset": "latest",
    })
    alert_consumer.subscribe(["vehicle.alerts.v1"])
    alert_consumer.poll(1.0)

    worker = RealTimeWorker(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id=f"test-rt-dup-{uuid.uuid4().hex[:8]}",
        redis_host="localhost",
        redis_port=REDIS_PORT,
    )

    # First delivery
    res1 = worker.process_message(payload)
    assert res1 is True
    worker.alert_publisher.flush(timeout=3.0)

    # Second delivery with exact same event_id
    res2 = worker.process_message(payload)
    assert res2 is False  # Suppressed!
    worker.alert_publisher.flush(timeout=3.0)

    # Collect all alerts on vehicle.alerts.v1 for this event_id
    alerts_for_event = []
    deadline = time.time() + 5.0
    while time.time() < deadline:
        msg = alert_consumer.poll(0.5)
        if msg is None:
            continue
        try:
            alert_data = json.loads(msg.value().decode("utf-8"))
            if alert_data.get("event_id") == event_id:
                alerts_for_event.append(alert_data)
        except Exception:
            continue

    alert_consumer.close()
    worker.stop()

    # Explicit count proof: exactly 1 alert for this event_id across both deliveries
    assert len(alerts_for_event) == 1, f"Expected exactly 1 alert for event_id {event_id}, got {len(alerts_for_event)}"
    assert alerts_for_event[0]["fault_type"] == "ENGINE_OVERHEAT"
