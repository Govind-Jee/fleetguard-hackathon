"""
FleetGuard Pulse - Real-Time Alert Bridge Worker

Consumes high-priority mechanical and safety alerts from Redpanda topic 'vehicle.alerts.v1'
and pushes them to connected dashboard clients via FastAPI's WebSocket broadcast endpoint.
Completes the end-to-end decoupled streaming alert pipeline:
Ingest -> Broker -> RealTimeWorker -> Alerts Topic -> Alert Bridge -> WebSocket -> UI
"""

import json
import logging
from typing import Optional
from confluent_kafka import Consumer, KafkaError
import httpx

logger = logging.getLogger("stream_processor.alert_bridge")


class AlertBridgeWorker:
    """Kafka/Redpanda consumer bridging vehicle alerts to the WebSocket push gateway."""

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        alerts_topic: str = "vehicle.alerts.v1",
        group_id: str = "alert-bridge-worker-group",
        broadcast_url: str = "http://127.0.0.1:8000/ws/broadcast",
        auto_offset_reset: str = "latest",
        timeout_sec: float = 5.0,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.alerts_topic = alerts_topic
        self.group_id = group_id
        self.broadcast_url = broadcast_url
        self.running = False

        self.consumer_config = {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": auto_offset_reset,
            "enable.auto.commit": True,
            "auto.commit.interval.ms": 1000,
            "session.timeout.ms": 10000,
        }
        self.consumer = Consumer(self.consumer_config)
        self.http_client = httpx.Client(timeout=timeout_sec)

    def process_message(self, raw_value: bytes) -> bool:
        """Forward an alert payload to FastAPI's WebSocket broadcast endpoint."""
        try:
            alert_data = json.loads(raw_value.decode("utf-8"))
            tenant_id = alert_data.get("tenant_id", "a0000000-0000-0000-0000-000000000001")
            payload = {
                "type": "CRITICAL_ALERT",
                "tenant_id": tenant_id,
                "alert": alert_data,
            }
            resp = self.http_client.post(self.broadcast_url, json=payload)
            if resp.status_code == 200:
                return True
            else:
                logger.warning("Broadcast failed with status %d: %s", resp.status_code, resp.text)
                return False
        except Exception as e:
            logger.error("Failed to forward alert message: %s", e)
            return False

    def run(self, max_messages: Optional[int] = None) -> int:
        """Main event loop consuming from alerts topic and forwarding to WebSocket gateway."""
        self.running = True
        self.consumer.subscribe([self.alerts_topic])
        logger.info("Subscribed to %s as group '%s'", self.alerts_topic, self.group_id)

        processed = 0
        try:
            while self.running:
                msg = self.consumer.poll(timeout=0.1)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    logger.error("Alert consumer error: %s", msg.error())
                    continue

                if self.process_message(msg.value()):
                    processed += 1
                    if max_messages and processed >= max_messages:
                        break
        finally:
            self.consumer.close()
            self.http_client.close()
            logger.info("AlertBridgeWorker stopped. Processed %d alerts.", processed)

        return processed

    def stop(self) -> None:
        self.running = False


def run_alert_bridge_worker(
    bootstrap_servers: str = "localhost:9092",
    alerts_topic: str = "vehicle.alerts.v1",
    group_id: str = "alert-bridge-worker-group",
    broadcast_url: str = "http://127.0.0.1:8000/ws/broadcast",
    max_messages: Optional[int] = None,
    auto_offset_reset: str = "latest",
) -> int:
    """Helper entrypoint for multiprocessing and CLI execution."""
    worker = AlertBridgeWorker(
        bootstrap_servers=bootstrap_servers,
        alerts_topic=alerts_topic,
        group_id=group_id,
        broadcast_url=broadcast_url,
        auto_offset_reset=auto_offset_reset,
    )
    return worker.run(max_messages=max_messages)
