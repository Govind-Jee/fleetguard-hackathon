"""
FleetGuard Pulse - Redpanda Replay Verification Script

Empirically proves durable partitioned message replay on Redpanda topic 'vehicle.telemetry.v1'.
Verifies that committed consumer groups or offset seeks can rewind and re-read historical events.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from confluent_kafka import Producer, Consumer, TopicPartition
from services.simulator.schema import TelemetryEvent, VehicleType

BOOTSTRAP_SERVERS = "localhost:9092"
TOPIC = "vehicle.telemetry.v1"


def run_replay_verification():
    print("=" * 70)
    print("FLEETGUARD PULSE - REDPANDA REPLAY CAPABILITY VERIFICATION")
    print("=" * 70)

    # 1. Create a unique telemetry event
    test_vin = f"1HGCR2F83HA{int(time.time() * 1000) % 1000000:06d}"
    target_event_id = str(uuid.uuid4())

    event = TelemetryEvent(
        schema_version="1.0",
        event_id=target_event_id,
        vin=test_vin,
        timestamp=datetime.now(timezone.utc).isoformat(),
        sequence_number=1,
        vehicle_type=VehicleType.ICE,
        latitude=37.7749,
        longitude=-122.4194,
        speed_kmh=65.0,
        odometer_km=15000.0,
        vibration=0.4,
        dtc_codes=[],
        oil_pressure_kpa=310.0,
        coolant_temp_c=91.0,
        engine_rpm=2100.0,
        battery_voltage_v=14.1,
    )

    # 2. Produce event to Redpanda and capture partition & offset
    produced_meta = {}

    def delivery_report(err, msg):
        if err is not None:
            raise RuntimeError(f"Delivery failed: {err}")
        produced_meta["topic"] = msg.topic()
        produced_meta["partition"] = msg.partition()
        produced_meta["offset"] = msg.offset()

    producer = Producer({"bootstrap.servers": BOOTSTRAP_SERVERS})
    producer.produce(
        topic=TOPIC,
        key=test_vin.encode("utf-8"),
        value=event.model_dump_json().encode("utf-8"),
        callback=delivery_report,
    )
    producer.flush(timeout=5.0)

    topic = produced_meta["topic"]
    partition = produced_meta["partition"]
    target_offset = produced_meta["offset"]

    print(f"[PRODUCED] Topic:     {topic}")
    print(f"[PRODUCED] Partition: {partition}")
    print(f"[PRODUCED] Offset:    {target_offset}")
    print(f"[PRODUCED] Event ID:  {target_event_id}")
    print(f"[PRODUCED] VIN:       {test_vin}")
    print("-" * 70)

    # 3. First consumption pass with Consumer Group 1
    group_id_1 = f"replay-verify-group-1-{uuid.uuid4().hex[:8]}"
    consumer_1 = Consumer({
        "bootstrap.servers": BOOTSTRAP_SERVERS,
        "group.id": group_id_1,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })

    # Explicitly assign the specific partition at target_offset
    tp = TopicPartition(topic, partition, target_offset)
    consumer_1.assign([tp])

    first_read_event_id = None
    first_read_offset = None
    start = time.time()
    while time.time() - start < 5.0:
        msg = consumer_1.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            continue
        try:
            d = json.loads(msg.value().decode("utf-8"))
            if d.get("event_id") == target_event_id:
                first_read_event_id = d["event_id"]
                first_read_offset = msg.offset()
                # Commit offset + 1
                consumer_1.commit(
                    offsets=[TopicPartition(topic, partition, msg.offset() + 1)],
                    asynchronous=False,
                )
                break
        except Exception:
            continue

    consumer_1.close()

    assert first_read_event_id == target_event_id, "First pass failed to read event"
    assert first_read_offset == target_offset, "First pass offset mismatch"
    print(f"[FIRST PASS]  Result: SUCCESS | Offset: {first_read_offset} | Event ID: {first_read_event_id}")

    # 4. Replay pass with Consumer Group 2 (or rewound consumer)
    group_id_2 = f"replay-verify-group-2-{uuid.uuid4().hex[:8]}"
    consumer_2 = Consumer({
        "bootstrap.servers": BOOTSTRAP_SERVERS,
        "group.id": group_id_2,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })

    # Rewind / Replay by assigning the exact historical offset again
    consumer_2.assign([TopicPartition(topic, partition, target_offset)])

    replay_read_event_id = None
    replay_read_offset = None
    start = time.time()
    while time.time() - start < 5.0:
        msg = consumer_2.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            continue
        try:
            d = json.loads(msg.value().decode("utf-8"))
            if d.get("event_id") == target_event_id:
                replay_read_event_id = d["event_id"]
                replay_read_offset = msg.offset()
                break
        except Exception:
            continue

    consumer_2.close()

    assert replay_read_event_id == target_event_id, "Replay pass failed to re-read event"
    assert replay_read_offset == target_offset, "Replay pass offset mismatch"
    print(f"[REPLAY PASS] Result: SUCCESS | Offset: {replay_read_offset} | Event ID: {replay_read_event_id}")

    # 5. Method 3: Seek-based replay within the same consumer group
    group_id_3 = f"replay-seek-group-{uuid.uuid4().hex[:8]}"
    consumer_3 = Consumer({
        "bootstrap.servers": BOOTSTRAP_SERVERS,
        "group.id": group_id_3,
        "enable.auto.commit": False,
    })
    consumer_3.assign([TopicPartition(topic, partition, target_offset)])
    # Read once
    msg1 = consumer_3.poll(3.0)
    assert msg1 is not None and json.loads(msg1.value().decode("utf-8"))["event_id"] == target_event_id
    # Commit advanced offset
    consumer_3.commit(offsets=[TopicPartition(topic, partition, target_offset + 1)], asynchronous=False)

    # Now seek back to target_offset (in-group rewind)
    consumer_3.seek(TopicPartition(topic, partition, target_offset))
    msg2 = consumer_3.poll(3.0)
    assert msg2 is not None and json.loads(msg2.value().decode("utf-8"))["event_id"] == target_event_id
    consumer_3.close()
    print(f"[SEEK REPLAY] Result: SUCCESS | Offset: {msg2.offset()} | Event ID: {target_event_id}")

    print("-" * 70)
    print("REPLAY VERIFICATION SUMMARY:")
    print(f"  Topic:                     {topic}")
    print(f"  Partition:                 {partition}")
    print(f"  Offset:                    {target_offset}")
    print(f"  Event ID:                  {target_event_id}")
    print(f"  First Consumption:         SUCCESS (Offset {first_read_offset})")
    print(f"  Replay Consumption (Grp2): SUCCESS (Offset {replay_read_offset})")
    print(f"  In-Group Seek Replay:      SUCCESS (Offset {msg2.offset()})")
    print("=" * 70)
    print("\033[1;32mREDPANDA REPLAY CAPABILITY EMPIRICALLY VERIFIED!\033[0m")
    print("=" * 70)


if __name__ == "__main__":
    run_replay_verification()
