"""
FleetGuard Pulse - Real-Time Detection Worker

Consumer Group: 'real-time-detection-consumer-group'
Topic: 'vehicle.telemetry.v1'

Performs the low-latency real-time processing loop:
Validation -> Deduplication -> Ordering Protection -> Streaming Stats -> Anomaly Detection -> Redis Hot State -> Alert Publication.
"""

import logging
import signal
import time
from typing import Optional
from confluent_kafka import Consumer, KafkaError, KafkaException

from services.stream_processor.validator import TelemetryValidator
from services.stream_processor.dedup import TwoTierDeduplicator
from services.stream_processor.ordering import OutOfOrderProtector
from services.stream_processor.statistics import StreamingStatsRegistry
from services.stream_processor.detector import HealthAnomalyDetector
from services.stream_processor.state import RedisStateManager
from services.stream_processor.alert_publisher import AlertPublisher
from services.stream_processor.metrics import default_metrics, StreamMetrics

logger = logging.getLogger("stream_processor.real_time_worker")


class RealTimeWorker:
    """Worker implementing the real-time detection pipeline."""

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        group_id: str = "real-time-detection-consumer-group",
        telemetry_topic: str = "vehicle.telemetry.v1",
        alerts_topic: str = "vehicle.alerts.v1",
        redis_host: str = "localhost",
        redis_port: int = 6380,
        metrics: Optional[StreamMetrics] = None,
        auto_offset_reset: str = "latest",
    ):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.telemetry_topic = telemetry_topic
        self.alerts_topic = alerts_topic
        self.metrics = metrics or default_metrics
        self.running = False

        # Initialize pipeline stages
        self.redis_state = RedisStateManager(
            host=redis_host, port=redis_port, metrics=self.metrics
        )
        self.validator = TelemetryValidator(metrics=self.metrics)
        self.deduplicator = TwoTierDeduplicator(
            redis_client=self.redis_state.client, metrics=self.metrics
        )
        self.ordering_protector = OutOfOrderProtector(
            redis_client=self.redis_state.client, metrics=self.metrics
        )
        self.stats_registry = StreamingStatsRegistry()
        self.detector = HealthAnomalyDetector(metrics=self.metrics)
        self.alert_publisher = AlertPublisher(
            bootstrap_servers=bootstrap_servers, topic=alerts_topic
        )

        # Consumer configuration
        self.consumer_config = {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": auto_offset_reset,
            "enable.auto.commit": True,
            "auto.commit.interval.ms": 1000,
            "fetch.min.bytes": 1,
            "fetch.wait.max.ms": 100,
        }
        self.consumer = Consumer(self.consumer_config)

    def process_message(self, raw_value: bytes) -> bool:
        """
        Execute full real-time detection pipeline for a single message.
        Returns True if successfully processed, False otherwise.
        """
        start_time = time.perf_counter()

        # Step 1: Schema validation
        event, err = self.validator.validate(raw_value)
        if event is None:
            return False

        # Step 2: Deduplication
        if self.deduplicator.is_duplicate(event.event_id):
            return False

        # Step 3: Out-of-order check
        is_in_order, _ = self.ordering_protector.check_and_update(
            vin=event.vin,
            sequence_number=event.sequence_number,
            timestamp=event.timestamp,
        )

        # Step 4: Streaming statistics
        stats = self.stats_registry.get_or_create(event.vin)

        # Step 5: Vehicle health & anomaly detection
        health_status, alerts = self.detector.evaluate(event, stats)

        # Step 6: Update Redis hot state (only if event is in-order)
        latest_alert = alerts[0] if alerts else None
        if is_in_order:
            self.redis_state.update_vehicle_state(
                event=event,
                health_status=health_status,
                latest_alert=latest_alert,
            )

        # Step 7: Publish alerts to vehicle.alerts.v1
        for alert in alerts:
            self.alert_publisher.publish_alert(alert)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        self.metrics.record_latency(elapsed_ms)
        return True

    def run(self, max_messages: Optional[int] = None) -> None:
        """Main consumer event loop."""
        self.running = True
        self.consumer.subscribe([self.telemetry_topic])
        logger.info(
            "Subscribed to %s as group '%s'", self.telemetry_topic, self.group_id
        )

        processed = 0
        try:
            while self.running:
                msg = self.consumer.poll(timeout=0.5)
                if msg is None:
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        logger.error("Consumer error: %s", msg.error())
                        continue

                self.process_message(msg.value())
                processed += 1

                if max_messages and processed >= max_messages:
                    logger.info("Reached target max_messages (%d). Stopping.", max_messages)
                    break

        except KeyboardInterrupt:
            logger.info("Interrupted by user. Shutting down worker.")
        finally:
            self.stop()

    def stop(self) -> None:
        """Gracefully flush and close resources."""
        self.running = False
        try:
            self.consumer.close()
        except Exception:
            pass
        try:
            self.alert_publisher.flush(timeout=3.0)
        except Exception:
            pass
        try:
            self.redis_state.close()
        except Exception:
            pass
        logger.info("RealTimeWorker stopped cleanly.")


def run_real_time_worker(
    bootstrap_servers: str = "localhost:9092",
    redis_host: str = "localhost",
    redis_port: int = 6380,
    max_messages: Optional[int] = None,
    auto_offset_reset: str = "latest",
) -> None:
    """Entrypoint function to run the real-time worker."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    worker = RealTimeWorker(
        bootstrap_servers=bootstrap_servers,
        redis_host=redis_host,
        redis_port=redis_port,
        auto_offset_reset=auto_offset_reset,
    )

    def handle_sig(sig, frame):
        logger.info("Received signal %d, shutting down...", sig)
        worker.running = False

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    worker.run(max_messages=max_messages)
