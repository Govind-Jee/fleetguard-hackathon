"""
FleetGuard Pulse - ClickHouse Historical Analytics Worker

Consumer Group: 'clickhouse-analytics-consumer-group'
Topic: 'vehicle.telemetry.v1'
Target: ClickHouse table 'fleetguard_analytics.vehicle_telemetry'

Micro-batches historical vehicle telemetry records for high-throughput OLAP analytics.
Completely isolated from real-time alerting to prevent backpressure propagation.
"""

from datetime import datetime, timezone
import json
import logging
import signal
import time
from typing import List, Optional
from confluent_kafka import Consumer, KafkaError
import clickhouse_connect

from services.stream_processor.metrics import default_metrics, StreamMetrics

logger = logging.getLogger("stream_processor.clickhouse_worker")

CLICKHOUSE_COLUMNS = [
    "event_id",
    "vin",
    "timestamp",
    "sequence_number",
    "vehicle_type",
    "latitude",
    "longitude",
    "speed_kmh",
    "odometer_km",
    "vibration",
    "dtc_codes",
    "oil_pressure_kpa",
    "coolant_temp_c",
    "engine_rpm",
    "battery_voltage_v",
    "soc_pct",
    "pack_voltage_v",
    "motor_rpm",
    "cell_temp_delta_c",
]


class ClickHouseWorker:
    """Worker micro-batching telemetry records into ClickHouse."""

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        group_id: str = "clickhouse-analytics-consumer-group",
        topic: str = "vehicle.telemetry.v1",
        clickhouse_host: str = "localhost",
        clickhouse_port: int = 8123,
        clickhouse_user: str = "default",
        clickhouse_password: str = "fleetguard_dev_password",
        database_name: str = "fleetguard_analytics",
        table_name: str = "vehicle_telemetry",
        batch_size: int = 1000,
        flush_interval_sec: float = 1.0,
        metrics: Optional[StreamMetrics] = None,
        auto_offset_reset: str = "latest",
    ):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.topic = topic
        self.database_name = database_name
        self.table_name = table_name
        self.batch_size = batch_size
        self.flush_interval_sec = flush_interval_sec
        self.metrics = metrics or default_metrics
        self.running = False

        # Initialize ClickHouse client
        self.ch_client = clickhouse_connect.get_client(
            host=clickhouse_host,
            port=clickhouse_port,
            username=clickhouse_user,
            password=clickhouse_password,
            database=database_name,
        )

        # Initialize Kafka Consumer
        self.consumer_config = {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": auto_offset_reset,
            "enable.auto.commit": False,  # Manual commit after batch flush
            "fetch.min.bytes": 1024,
            "fetch.wait.max.ms": 200,
        }
        self.consumer = Consumer(self.consumer_config)
        self.buffer: List[List] = []
        self.last_flush = time.time()

    def _parse_row(self, raw_dict: dict) -> Optional[List]:
        """Convert telemetry JSON dictionary into a flat row matching ClickHouse schema."""
        try:
            ts_str = raw_dict["timestamp"].replace("Z", "+00:00")
            ts = datetime.fromisoformat(ts_str)

            return [
                raw_dict["event_id"],
                raw_dict["vin"],
                ts,
                int(raw_dict["sequence_number"]),
                raw_dict["vehicle_type"],
                float(raw_dict["latitude"]),
                float(raw_dict["longitude"]),
                float(raw_dict["speed_kmh"]),
                float(raw_dict["odometer_km"]),
                float(raw_dict["vibration"]),
                raw_dict.get("dtc_codes", []),
                raw_dict.get("oil_pressure_kpa"),
                raw_dict.get("coolant_temp_c"),
                raw_dict.get("engine_rpm"),
                raw_dict.get("battery_voltage_v"),
                raw_dict.get("soc_pct"),
                raw_dict.get("pack_voltage_v"),
                raw_dict.get("motor_rpm"),
                raw_dict.get("cell_temp_delta_c"),
            ]
        except Exception as e:
            logger.warning("Failed to parse row for ClickHouse: %s", e)
            return None

    def flush_batch(self) -> int:
        """Flush buffered rows into ClickHouse."""
        if not self.buffer:
            return 0

        count = len(self.buffer)
        try:
            self.ch_client.insert(
                table=self.table_name,
                data=self.buffer,
                column_names=CLICKHOUSE_COLUMNS,
            )
            try:
                self.consumer.commit(asynchronous=False)
            except Exception as ce:
                logger.debug("Offset commit skipped or not available: %s", ce)
            self.metrics.increment("clickhouse_persisted", count)
            logger.debug("Successfully flushed %d records to ClickHouse.", count)
        except Exception as e:
            logger.error("Error inserting batch of %d records to ClickHouse: %s", count, e)
        finally:
            self.buffer.clear()
            self.last_flush = time.time()

        return count

    def run(self, max_messages: Optional[int] = None) -> None:
        """Main worker loop."""
        self.running = True
        self.consumer.subscribe([self.topic])
        logger.info(
            "Subscribed to %s as group '%s' (batch_size: %d, interval: %.2fs)",
            self.topic,
            self.group_id,
            self.batch_size,
            self.flush_interval_sec,
        )

        total_processed = 0
        try:
            while self.running:
                msg = self.consumer.poll(timeout=0.1)

                if msg is not None and not msg.error():
                    try:
                        raw_dict = json.loads(msg.value())
                        row = self._parse_row(raw_dict)
                        if row:
                            self.buffer.append(row)
                            total_processed += 1
                    except Exception as err:
                        logger.warning("Failed to process event for ClickHouse: %s", err)

                # Check flush triggers
                time_since_flush = time.time() - self.last_flush
                if len(self.buffer) >= self.batch_size or (
                    self.buffer and time_since_flush >= self.flush_interval_sec
                ):
                    self.flush_batch()

                if max_messages and total_processed >= max_messages:
                    logger.info("Reached target max_messages (%d). Stopping.", max_messages)
                    break

            # Final flush before stopping
            self.flush_batch()

        except KeyboardInterrupt:
            logger.info("Interrupted. Shutting down ClickHouse worker.")
        finally:
            self.stop()

    def stop(self) -> None:
        """Gracefully flush and close resources."""
        self.running = False
        try:
            self.flush_batch()
        except Exception:
            pass
        try:
            self.consumer.close()
        except Exception:
            pass
        try:
            self.ch_client.close()
        except Exception:
            pass
        logger.info("ClickHouseWorker stopped cleanly.")


def run_clickhouse_worker(
    bootstrap_servers: str = "localhost:9092",
    clickhouse_host: str = "localhost",
    clickhouse_port: int = 8123,
    max_messages: Optional[int] = None,
    auto_offset_reset: str = "latest",
) -> None:
    """Entrypoint function to run the ClickHouse worker."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    worker = ClickHouseWorker(
        bootstrap_servers=bootstrap_servers,
        clickhouse_host=clickhouse_host,
        clickhouse_port=clickhouse_port,
        auto_offset_reset=auto_offset_reset,
    )

    def handle_sig(sig, frame):
        logger.info("Received signal %d, shutting down...", sig)
        worker.running = False

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    worker.run(max_messages=max_messages)
