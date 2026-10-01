"""
Integration test for Redpanda publishing and consumption.
Publishes telemetry events using TelemetryProducer and verifies delivery.
"""

import json
import os
import time
import unittest
import uuid
from services.simulator.producer import TelemetryProducer
from services.simulator.generator import TelemetryGenerator


class TestRedpandaIntegration(unittest.TestCase):
    def setUp(self):
        self.bootstrap_servers = os.getenv("REDPANDA_BROKERS", "localhost:9092")
        self.topic = "vehicle.telemetry.v1"

    def test_publish_and_consume_redpanda(self):
        try:
            from confluent_kafka import Consumer, KafkaError
        except ImportError:
            self.skipTest("confluent_kafka not available in environment")

        producer = TelemetryProducer(
            bootstrap_servers=self.bootstrap_servers,
            topic=self.topic,
            dry_run=False,
        )

        if producer.dry_run:
            self.skipTest("TelemetryProducer running in dry-run mode (broker unreachable)")

        # Generate 15 sample events
        generator = TelemetryGenerator(vehicle_count=5, seed=99)
        test_events = []
        for event, is_dup, is_reord in generator.stream_events(max_events=15):
            test_events.append(event)
            success = producer.produce(event.model_dump())
            self.assertTrue(success)

        remaining = producer.flush(timeout_sec=5.0)
        self.assertEqual(remaining, 0, "All messages should be flushed to broker")
        self.assertEqual(producer.messages_produced, 15)
        producer.close()

        # Verify messages using confluent-kafka consumer
        consumer_conf = {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": f"test-verify-group-{uuid.uuid4().hex[:8]}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
        }
        consumer = Consumer(consumer_conf)
        consumer.subscribe([self.topic])

        received = []
        # Poll for records
        for _ in range(30):
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                if len(received) >= 15:
                    break
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                break
            payload = json.loads(msg.value().decode("utf-8"))
            received.append(payload)
            if len(received) >= 15:
                break

        consumer.close()
        self.assertGreaterEqual(len(received), 15, "Should consume at least the 15 published test events")
        first = received[0]
        self.assertIn("vin", first)
        self.assertIn("timestamp", first)
        self.assertIn("schema_version", first)
        self.assertEqual(first["schema_version"], "1.0")

    def test_redpanda_historical_replay(self):
        """
        REQ-008 Verification: Proves durable partitioned message replay.
        Ensures a separate consumer group or seek operation can rewind
        and re-read historical telemetry from an earlier offset.
        """
        from confluent_kafka import Producer, Consumer, TopicPartition
        from services.simulator.schema import TelemetryEvent, VehicleType

        test_vin = f"1HGCR2F83HA{int(time.time() * 1000) % 1000000:06d}"
        target_event_id = str(uuid.uuid4())

        event = TelemetryEvent(
            schema_version="1.0",
            event_id=target_event_id,
            vin=test_vin,
            timestamp="2026-10-01T13:30:00.000000Z",
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

        produced_meta = {}

        def cb(err, msg):
            if err is not None:
                raise RuntimeError(str(err))
            produced_meta["topic"] = msg.topic()
            produced_meta["partition"] = msg.partition()
            produced_meta["offset"] = msg.offset()

        producer = Producer({"bootstrap.servers": self.bootstrap_servers})
        producer.produce(
            topic=self.topic,
            key=test_vin.encode("utf-8"),
            value=event.model_dump_json().encode("utf-8"),
            callback=cb,
        )
        producer.flush(timeout=5.0)

        topic = produced_meta["topic"]
        partition = produced_meta["partition"]
        offset = produced_meta["offset"]

        # First consumption pass (Consumer Group 1)
        c1 = Consumer({
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": f"test-replay-c1-{uuid.uuid4().hex[:8]}",
            "enable.auto.commit": False,
        })
        c1.assign([TopicPartition(topic, partition, offset)])
        msg1 = c1.poll(timeout=5.0)
        self.assertIsNotNone(msg1)
        data1 = json.loads(msg1.value().decode("utf-8"))
        self.assertEqual(data1["event_id"], target_event_id)
        self.assertEqual(msg1.offset(), offset)
        c1.commit(offsets=[TopicPartition(topic, partition, offset + 1)], asynchronous=False)
        c1.close()

        # Replay pass (Consumer Group 2 rewinding to offset)
        c2 = Consumer({
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": f"test-replay-c2-{uuid.uuid4().hex[:8]}",
            "enable.auto.commit": False,
        })
        c2.assign([TopicPartition(topic, partition, offset)])
        msg2 = c2.poll(timeout=5.0)
        self.assertIsNotNone(msg2)
        data2 = json.loads(msg2.value().decode("utf-8"))
        self.assertEqual(data2["event_id"], target_event_id)
        self.assertEqual(msg2.offset(), offset)
        c2.close()

        # Seek-based replay within group
        c3 = Consumer({
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": f"test-replay-c3-{uuid.uuid4().hex[:8]}",
            "enable.auto.commit": False,
        })
        c3.assign([TopicPartition(topic, partition, offset)])
        msg3 = c3.poll(timeout=5.0)
        self.assertIsNotNone(msg3)
        c3.commit(offsets=[TopicPartition(topic, partition, offset + 1)], asynchronous=False)

        # Seek back to previous offset
        c3.seek(TopicPartition(topic, partition, offset))
        msg3_replay = c3.poll(timeout=5.0)
        self.assertIsNotNone(msg3_replay)
        self.assertEqual(json.loads(msg3_replay.value().decode("utf-8"))["event_id"], target_event_id)
        self.assertEqual(msg3_replay.offset(), offset)
        c3.close()


if __name__ == "__main__":
    unittest.main()
