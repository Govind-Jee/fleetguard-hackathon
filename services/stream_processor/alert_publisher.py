"""
FleetGuard Pulse - Real-Time Alert Publisher

Publishes high-priority mechanical and safety alerts to Redpanda topic 'vehicle.alerts.v1'.
Keyed by VIN to preserve per-vehicle causal event ordering across consumer partitions.
"""

import json
import logging
from typing import Optional
from confluent_kafka import Producer

from services.stream_processor.models import CriticalAlert

logger = logging.getLogger("stream_processor.alert_publisher")


class AlertPublisher:
    """Kafka/Redpanda publisher for critical vehicle health alerts."""

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        topic: str = "vehicle.alerts.v1",
    ):
        self.topic = topic
        self.bootstrap_servers = bootstrap_servers
        self._producer_config = {
            "bootstrap.servers": bootstrap_servers,
            "client.id": "fleetguard-alert-publisher",
            "acks": "all",
            "retries": 3,
            "linger.ms": 5,
        }
        self.producer = Producer(self._producer_config)

    def _delivery_report(self, err, msg):
        """Callback for message delivery status."""
        if err is not None:
            logger.error("Alert delivery failed: %s [topic: %s]", err, msg.topic())
        else:
            logger.debug(
                "Alert delivered to %s [%d] at offset %d",
                msg.topic(),
                msg.partition(),
                msg.offset(),
            )

    def publish_alert(self, alert: CriticalAlert) -> bool:
        """
        Publish a CriticalAlert to Redpanda.

        Args:
            alert: Validated CriticalAlert model instance.

        Returns:
            True if queued successfully, False otherwise.
        """
        try:
            payload = alert.model_dump_json()
            key = alert.vin.encode("utf-8")
            self.producer.produce(
                topic=self.topic,
                key=key,
                value=payload.encode("utf-8"),
                callback=self._delivery_report,
            )
            # Poll to trigger callbacks and clear delivery buffer
            self.producer.poll(0)
            return True
        except BufferError:
            logger.warning("Producer queue full, flushing...")
            self.producer.flush(timeout=2.0)
            # Retry once
            self.producer.produce(
                topic=self.topic,
                key=alert.vin.encode("utf-8"),
                value=alert.model_dump_json().encode("utf-8"),
                callback=self._delivery_report,
            )
            return True
        except Exception as e:
            logger.error("Failed to publish alert %s: %s", alert.alert_id, e)
            return False

    def flush(self, timeout: float = 5.0) -> int:
        """Wait for all pending messages to be delivered."""
        return self.producer.flush(timeout=timeout)
