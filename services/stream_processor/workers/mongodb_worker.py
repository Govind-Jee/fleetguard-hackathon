"""
FleetGuard Pulse - MongoDB Raw Telemetry Persistence Worker

Consumer Group: 'mongodb-raw-consumer-group'
Topic: 'vehicle.telemetry.v1'
Target: MongoDB database 'fleetguard_telemetry', collection 'raw_telemetry'

Micro-batches raw vehicle telemetry records for high-throughput, decoupled cold storage.
Completely isolated from real-time alerting to prevent backpressure propagation.
"""

import json
import logging
import signal
import time
from typing import List, Optional
from confluent_kafka import Consumer, KafkaError
import pymongo
from pymongo import UpdateOne

from services.stream_processor.metrics import default_metrics, StreamMetrics

logger = logging.getLogger("stream_processor.mongodb_worker")


class MongoDBWorker:
    """Worker micro-batching raw telemetry events into MongoDB."""

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        group_id: str = "mongodb-raw-consumer-group",
        topic: str = "vehicle.telemetry.v1",
        mongo_uri: str = "mongodb://fleetguard_user:fleetguard_dev_password@localhost:27017/?authSource=admin",
        database_name: str = "fleetguard_telemetry",
        collection_name: str = "raw_telemetry",
        batch_size: int = 500,
        flush_interval_sec: float = 0.5,
        metrics: Optional[StreamMetrics] = None,
        auto_offset_reset: str = "latest",
    ):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.topic = topic
        self.batch_size = batch_size
        self.flush_interval_sec = flush_interval_sec
        self.metrics = metrics or default_metrics
        self.running = False

        # Initialize MongoDB client
        self.mongo_client = pymongo.MongoClient(
            mongo_uri, serverSelectionTimeoutMS=5000
        )
        self.db = self.mongo_client[database_name]
        self.collection = self.db[collection_name]

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
        self.buffer: List[dict] = []
        self.last_flush = time.time()

    def flush_batch(self) -> int:
        """Flush buffered events to MongoDB via idempotent bulk write."""
        if not self.buffer:
            return 0

        count = len(self.buffer)
        operations = [
            UpdateOne(
                {"event_id": doc["event_id"]},
                {"$setOnInsert": doc},
                upsert=True,
            )
            for doc in self.buffer
        ]

        try:
            self.collection.bulk_write(operations, ordered=False)
            try:
                self.consumer.commit(asynchronous=False)
            except Exception as ce:
                logger.debug("Offset commit skipped or not available: %s", ce)
            self.metrics.increment("mongodb_persisted", count)
            logger.debug("Successfully flushed %d records to MongoDB.", count)
        except Exception as e:
            logger.error("Error flushing batch of %d records to MongoDB: %s", count, e)
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
                        if "event_id" in raw_dict:
                            self.buffer.append(raw_dict)
                            total_processed += 1
                    except Exception as err:
                        logger.warning("Failed to parse event for MongoDB: %s", err)

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
            logger.info("Interrupted. Shutting down MongoDB worker.")
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
            self.mongo_client.close()
        except Exception:
            pass
        logger.info("MongoDBWorker stopped cleanly.")


def run_mongodb_worker(
    bootstrap_servers: str = "localhost:9092",
    mongo_uri: str = "mongodb://fleetguard_user:fleetguard_dev_password@localhost:27017/?authSource=admin",
    max_messages: Optional[int] = None,
    auto_offset_reset: str = "latest",
) -> None:
    """Entrypoint function to run the MongoDB worker."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    worker = MongoDBWorker(
        bootstrap_servers=bootstrap_servers,
        mongo_uri=mongo_uri,
        auto_offset_reset=auto_offset_reset,
    )

    def handle_sig(sig, frame):
        logger.info("Received signal %d, shutting down...", sig)
        worker.running = False

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    worker.run(max_messages=max_messages)
