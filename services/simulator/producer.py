"""
FleetGuard Pulse - Redpanda Telemetry Producer

High-throughput, non-blocking Kafka/Redpanda producer utilizing confluent-kafka.
Publishes telemetry partitioned strictly by VIN to topic 'vehicle.telemetry.v1'.
"""

import json
import logging
import os
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("fleetguard.simulator.producer")

DEFAULT_TOPIC = "vehicle.telemetry.v1"
DEFAULT_BROKERS = os.getenv("REDPANDA_BROKERS", "localhost:9092")


class TelemetryProducer:
    """
    High-performance producer targeting Redpanda Kafka interface.
    """
    def __init__(
        self,
        bootstrap_servers: str = DEFAULT_BROKERS,
        topic: str = DEFAULT_TOPIC,
        dry_run: bool = False,
        batch_size: int = 1000,
        linger_ms: int = 10,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.dry_run = dry_run
        self.batch_size = batch_size
        self.linger_ms = linger_ms

        # Metrics
        self.messages_produced = 0
        self.messages_delivered = 0
        self.messages_failed = 0
        self.duplicates_emitted = 0
        self.reorders_emitted = 0

        self._producer: Any = None
        if not self.dry_run:
            self._init_producer()

    def _init_producer(self) -> None:
        try:
            from confluent_kafka import Producer
            conf = {
                "bootstrap.servers": self.bootstrap_servers,
                "client.id": "fleetguard-simulator-producer",
                "queue.buffering.max.messages": 200000,
                "queue.buffering.max.kbytes": 262144,  # 256 MB buffer
                "linger.ms": self.linger_ms,
                "batch.num.messages": self.batch_size,
                "acks": 1,  # Fast durable acknowledgment
            }
            self._producer = Producer(conf)
            logger.info("Connected to Redpanda at %s", self.bootstrap_servers)
        except Exception as e:
            logger.warning("Could not initialize confluent_kafka Producer (%s). Running in dry-run mode.", e)
            self.dry_run = True

    def _delivery_callback(self, err: Any, msg: Any) -> None:
        if err is not None:
            self.messages_failed += 1
            logger.error("Failed to deliver message: %s", err)
        else:
            self.messages_delivered += 1

    def produce(
        self,
        event_dict: Dict[str, Any],
        is_duplicate: bool = False,
        is_reordered: bool = False,
    ) -> bool:
        """
        Publishes a telemetry event to Redpanda partitioned strictly by VIN.
        """
        vin = event_dict.get("vin", "")
        payload = json.dumps(event_dict).encode("utf-8")

        if is_duplicate:
            self.duplicates_emitted += 1
        if is_reordered:
            self.reorders_emitted += 1

        self.messages_produced += 1

        if self.dry_run or self._producer is None:
            self.messages_delivered += 1
            return True

        try:
            # Partition key is strictly the VIN string
            self._producer.produce(
                topic=self.topic,
                key=vin.encode("utf-8"),
                value=payload,
                on_delivery=self._delivery_callback,
            )
            # Service delivery callbacks periodically
            if self.messages_produced % 500 == 0:
                self._producer.poll(0)
            return True
        except BufferError:
            # Internal queue full - flush briefly
            self._producer.poll(50)
            try:
                self._producer.produce(
                    topic=self.topic,
                    key=vin.encode("utf-8"),
                    value=payload,
                    on_delivery=self._delivery_callback,
                )
                return True
            except Exception as e:
                self.messages_failed += 1
                logger.error("Drop event on buffer overflow: %s", e)
                return False
        except Exception as e:
            self.messages_failed += 1
            logger.error("Produce error: %s", e)
            return False

    def flush(self, timeout_sec: float = 10.0) -> int:
        """Flushes buffered messages and returns remaining buffer count."""
        if self._producer is not None:
            return self._producer.flush(timeout_sec)
        return 0

    def close(self) -> None:
        """Gracefully flushes and closes producer."""
        if self._producer is not None:
            self.flush(5.0)
            self._producer = None
