#!/usr/bin/env python3
"""
FleetGuard Pulse - Distributed Ingestion Throughput & Burst Benchmark (Phase 11)

Measures empirical performance of the real Redpanda-based ingestion pipeline:
1. Baseline: Moderate multi-worker ingestion and consumer processing.
2. Sustained 100K: Target sustained 100,000 events/sec workload into Redpanda (60s window).
3. Burst 300K: Target 300,000 events/sec rapid burst tolerance and recovery (10s window).

Features:
- 100% unique UUIDv4 event_id generated per message (no static templates)
- Key and body VIN exact equality on every record
- Monotonic per-VIN sequence numbers and fresh UTC timestamps
- Canonical TelemetryEvent schema version 1.0
- Delivery callbacks distinguishing attempted vs successfully delivered vs failed
- Consumer workers execute the real FleetGuard RealTimeWorker processing path:
  TelemetryValidator -> TwoTierDeduplicator -> OutOfOrderProtector ->
  StreamingStatsRegistry -> HealthAnomalyDetector
- Dedicated topic isolation on 'vehicle.telemetry.benchmark.v1' (16 partitions)
- Automated data-integrity assertions and post-burst recovery drain measurement
"""

import argparse
from datetime import datetime, timezone
import json
import logging
import multiprocessing as mp
import os
import platform
import subprocess
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from confluent_kafka import Consumer, Producer, TopicPartition

# Add project root to path for stream processor imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.stream_processor.workers.real_time_worker import RealTimeWorker
from services.simulator.schema import TelemetryEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("fleetguard.benchmark")

BENCHMARK_TOPIC = "vehicle.telemetry.benchmark.v1"
NUM_PARTITIONS = 16
BOOTSTRAP_SERVERS = os.getenv("REDPANDA_BROKERS", "localhost:9092")


def get_container_stats() -> Dict[str, Dict[str, str]]:
    """Capture snapshot of container CPU and Memory usage via docker stats."""
    try:
        cmd = [
            "docker", "stats", "--no-stream", "--format",
            "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        stats = {}
        for line in res.stdout.strip().split("\n"):
            if not line or "|" not in line:
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                name, cpu, mem_usage, mem_perc = parts[0], parts[1], parts[2], parts[3]
                stats[name] = {
                    "cpu_perc": cpu,
                    "mem_usage": mem_usage,
                    "mem_perc": mem_perc,
                }
        return stats
    except Exception as e:
        logger.warning("Could not fetch docker stats: %s", e)
        return {}


def purge_and_recreate_benchmark_topic(
    bootstrap_servers: str = BOOTSTRAP_SERVERS,
    topic: str = BENCHMARK_TOPIC,
    partitions: int = NUM_PARTITIONS,
) -> bool:
    """Purge and recreate the dedicated benchmark topic in Redpanda to ensure zero initial offsets."""
    try:
        logger.info("Purging and recreating benchmark topic '%s' with %d partitions...", topic, partitions)
        subprocess.run(
            ["docker", "exec", "fleetguard-redpanda", "rpk", "topic", "delete", topic],
            capture_output=True, text=True
        )
        time.sleep(1.0)
        res = subprocess.run(
            ["docker", "exec", "fleetguard-redpanda", "rpk", "topic", "create", topic, "-p", str(partitions)],
            capture_output=True, text=True, check=True
        )
        time.sleep(1.5)
        logger.info("Topic recreated successfully: %s", res.stdout.strip().replace("\n", " "))
        return True
    except Exception as e:
        logger.error("Failed to purge/recreate benchmark topic: %s", e)
        return False


def get_partition_highwater_marks(
    bootstrap_servers: str = BOOTSTRAP_SERVERS,
    topic: str = BENCHMARK_TOPIC,
    num_partitions: int = NUM_PARTITIONS,
) -> Dict[int, int]:
    """Get high-water mark offset for all topic partitions."""
    c = Consumer({"bootstrap.servers": bootstrap_servers, "group.id": f"hwm-check-{uuid.uuid4().hex[:8]}"})
    hwm = {}
    for p in range(num_partitions):
        tp = TopicPartition(topic, p)
        try:
            _, high = c.get_watermark_offsets(tp, timeout=5.0)
            hwm[p] = high
        except Exception as e:
            logger.error("Failed to fetch watermark for partition %d: %s", p, e)
            hwm[p] = 0
    c.close()
    return hwm


def get_consumer_group_offsets(
    group_id: str,
    bootstrap_servers: str = BOOTSTRAP_SERVERS,
    topic: str = BENCHMARK_TOPIC,
    num_partitions: int = NUM_PARTITIONS,
) -> Tuple[Dict[int, int], int]:
    """Get committed offsets and total lag for a consumer group across all partitions."""
    c = Consumer({"bootstrap.servers": bootstrap_servers, "group.id": group_id})
    tps = [TopicPartition(topic, p) for p in range(num_partitions)]
    try:
        committed = c.committed(tps, timeout=5.0)
        hwm = get_partition_highwater_marks(bootstrap_servers, topic, num_partitions)
        offsets = {}
        total_lag = 0
        for tp in committed:
            current = tp.offset if tp.offset >= 0 else 0
            high = hwm.get(tp.partition, 0)
            lag = max(0, high - current)
            offsets[tp.partition] = current
            total_lag += lag
        c.close()
        return offsets, total_lag
    except Exception as e:
        logger.warning("Could not fetch group offsets for %s: %s", group_id, e)
        c.close()
        return {}, 0


def generate_telemetry_payload(vin: str, seq: int, ts_iso: str, ptype: str) -> bytes:
    """Generate canonical TelemetryEvent JSON bytes with a fresh unique UUIDv4 event_id."""
    eid = str(uuid.uuid4())
    if ptype == "ICE":
        return (
            f'{{"schema_version":"1.0","event_id":"{eid}","vin":"{vin}","timestamp":"{ts_iso}",'
            f'"sequence_number":{seq},"vehicle_type":"ICE","latitude":40.7128,"longitude":-74.0060,'
            f'"speed_kmh":55.4,"odometer_km":15000.0,"vibration":0.28,"dtc_codes":[],'
            f'"oil_pressure_kpa":320.0,"coolant_temp_c":92.5,"engine_rpm":2250.0,"battery_voltage_v":13.8}}'
        ).encode("ascii")
    elif ptype == "BEV":
        return (
            f'{{"schema_version":"1.0","event_id":"{eid}","vin":"{vin}","timestamp":"{ts_iso}",'
            f'"sequence_number":{seq},"vehicle_type":"BEV","latitude":40.7128,"longitude":-74.0060,'
            f'"speed_kmh":62.1,"odometer_km":18200.0,"vibration":0.15,"dtc_codes":[],'
            f'"battery_voltage_v":13.6,"soc_pct":78.5,"pack_voltage_v":395.0,"motor_rpm":4200.0,"cell_temp_delta_c":1.2}}'
        ).encode("ascii")
    else:
        return (
            f'{{"schema_version":"1.0","event_id":"{eid}","vin":"{vin}","timestamp":"{ts_iso}",'
            f'"sequence_number":{seq},"vehicle_type":"HEV","latitude":40.7128,"longitude":-74.0060,'
            f'"speed_kmh":48.0,"odometer_km":16100.0,"vibration":0.20,"dtc_codes":[],'
            f'"oil_pressure_kpa":310.0,"coolant_temp_c":89.0,"engine_rpm":1950.0,"battery_voltage_v":13.7,'
            f'"soc_pct":65.0,"pack_voltage_v":280.0,"motor_rpm":3100.0,"cell_temp_delta_c":0.8}}'
        ).encode("ascii")


def producer_worker(
    worker_id: int,
    target_rate_per_sec: float,
    duration_sec: float,
    bootstrap_servers: str,
    topic: str,
    batch_size: int,
    linger_ms: int,
    result_dict: Dict[str, Any],
):
    """
    Dedicated producer process generating genuinely unique telemetry events
    and publishing with delivery callback accounting.
    """
    conf = {
        "bootstrap.servers": bootstrap_servers,
        "client.id": f"benchmark-producer-{worker_id}",
        "queue.buffering.max.messages": 500000,
        "queue.buffering.max.kbytes": 524288,  # 512 MB buffer per worker
        "linger.ms": linger_ms,
        "batch.num.messages": batch_size,
        "acks": 1,
        "compression.type": "lz4",
    }
    p = Producer(conf)

    attempted = 0
    delivered = 0
    failed = 0
    producer_errors = []

    def delivery_cb(err, msg):
        nonlocal delivered, failed
        if err is not None:
            failed += 1
            if len(producer_errors) < 5:
                producer_errors.append(str(err))
        else:
            delivered += 1

    t0 = time.perf_counter()
    target_end_time = t0 + duration_sec
    unthrottled = target_rate_per_sec <= 0

    chunk_size = 500
    chunk_interval = chunk_size / max(target_rate_per_sec, 1.0) if not unthrottled else 0.0

    vin_range_per_worker = 12500
    vin_offset_base = worker_id * vin_range_per_worker
    powertrain_types = ["ICE", "BEV", "HEV"]

    # Local per-VIN sequence tracking
    vin_seqs = [1000] * vin_range_per_worker

    while time.perf_counter() < target_end_time:
        t_chunk_start = time.perf_counter()
        ts_iso = datetime.now(timezone.utc).isoformat()

        for _ in range(chunk_size):
            local_idx = attempted % vin_range_per_worker
            vin_num = (vin_offset_base + local_idx) % 100000
            vin = f"1HGCR2F83HA{vin_num:06d}"
            vin_key = vin.encode("ascii")

            seq = vin_seqs[local_idx]
            vin_seqs[local_idx] += 1
            ptype = powertrain_types[local_idx % 3]

            payload = generate_telemetry_payload(vin, seq, ts_iso, ptype)

            try:
                p.produce(topic=topic, key=vin_key, value=payload, on_delivery=delivery_cb)
                attempted += 1
            except BufferError:
                p.poll(20)
                try:
                    p.produce(topic=topic, key=vin_key, value=payload, on_delivery=delivery_cb)
                    attempted += 1
                except Exception as ex:
                    failed += 1
                    if len(producer_errors) < 5:
                        producer_errors.append(f"ProduceBufferException: {ex}")
            except Exception as ex:
                failed += 1
                if len(producer_errors) < 5:
                    producer_errors.append(f"ProduceException: {ex}")

        p.poll(0)

        if not unthrottled:
            elapsed_chunk = time.perf_counter() - t_chunk_start
            sleep_needed = chunk_interval - elapsed_chunk
            if sleep_needed > 0.001:
                time.sleep(sleep_needed)

    # Flush remaining messages
    flush_deadline = time.perf_counter() + 60.0
    remaining = p.flush(15.0)
    while remaining > 0 and time.perf_counter() < flush_deadline:
        remaining = p.flush(5.0)

    t1 = time.perf_counter()
    actual_duration = t1 - t0

    result_dict[worker_id] = {
        "worker_id": worker_id,
        "events_attempted": attempted,
        "events_delivered": delivered,
        "events_failed": failed,
        "remaining_unflushed": remaining,
        "producer_errors": producer_errors,
        "duration_sec": actual_duration,
        "rate": delivered / max(actual_duration, 0.001),
    }


def consumer_worker(
    worker_id: int,
    group_id: str,
    stop_event: Any,
    bootstrap_servers: str,
    topic: str,
    result_dict: Dict[str, Any],
):
    """
    Dedicated consumer process invoking the real FleetGuard RealTimeWorker pipeline.
    Validates TelemetryEvent schema, checks TwoTierDeduplicator Bloom filter,
    verifies OutOfOrderProtector sequence watermarks, updates StreamingStatsRegistry,
    and runs HealthAnomalyDetector rules.
    """
    worker = RealTimeWorker(
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        telemetry_topic=topic,
        auto_offset_reset="earliest",
        enable_downstream_persistence=False,
    )
    worker.consumer.subscribe([topic])

    consumed = 0
    processed = 0
    duplicates = 0
    invalid = 0
    consumer_errors = 0
    key_body_mismatches = 0

    t0 = time.perf_counter()

    while not stop_event.is_set():
        msgs = worker.consumer.consume(num_messages=1000, timeout=0.1)
        if not msgs:
            continue
        for msg in msgs:
            if msg.error():
                consumer_errors += 1
                continue

            consumed += 1
            raw_val = msg.value()
            key_val = msg.key()

            # Periodic key-body consistency sample
            if consumed % 10000 == 1 and key_val and raw_val:
                try:
                    parsed = json.loads(raw_val)
                    if key_val.decode("ascii") != parsed.get("vin"):
                        key_body_mismatches += 1
                except Exception:
                    invalid += 1

            # Execute real FleetGuard processing pipeline
            ok = worker.process_message(raw_val)
            if ok:
                processed += 1
            else:
                invalid += 1

    # Drain any remaining records briefly after stop_event
    while True:
        msgs = worker.consumer.consume(num_messages=1000, timeout=0.1)
        if not msgs:
            break
        for msg in msgs:
            if not msg.error():
                consumed += 1
                ok = worker.process_message(msg.value())
                if ok:
                    processed += 1
                else:
                    invalid += 1

    worker.consumer.close()
    t1 = time.perf_counter()
    actual_duration = t1 - t0

    result_dict[worker_id] = {
        "worker_id": worker_id,
        "consumed": consumed,
        "processed": processed,
        "duplicates": duplicates,
        "invalid": invalid,
        "key_body_mismatches": key_body_mismatches,
        "consumer_errors": consumer_errors,
        "duration_sec": actual_duration,
        "rate": processed / max(actual_duration, 0.001),
    }


class DistributedIngestionHarness:
    """Manages multi-process benchmark runs, offset tracking, and resource telemetry."""

    def __init__(
        self,
        bootstrap_servers: str = BOOTSTRAP_SERVERS,
        topic: str = BENCHMARK_TOPIC,
        num_partitions: int = NUM_PARTITIONS,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.num_partitions = num_partitions

    def run_benchmark_phase(
        self,
        phase_name: str,
        target_rate: float,
        duration_sec: float,
        num_producers: int = 8,
        num_consumers: int = 8,
        batch_size: int = 5000,
        linger_ms: int = 10,
        clean_topic: bool = True,
    ) -> Dict[str, Any]:
        """Execute a single performance experiment phase with complete lifecycle isolation."""
        logger.info("\n" + "=" * 80)
        logger.info("STARTING PHASE: %s", phase_name)
        logger.info(
            "Config: Target Rate=%.0f ev/s | Duration=%.1fs | Producers=%d | Consumers=%d | Topic=%s (Partitions=%d)",
            target_rate, duration_sec, num_producers, num_consumers, self.topic, self.num_partitions,
        )
        logger.info("=" * 80)

        # 1. Clean topic isolation
        if clean_topic:
            purge_and_recreate_benchmark_topic(self.bootstrap_servers, self.topic, self.num_partitions)

        # 2. Check initial watermarks
        hwm_initial = get_partition_highwater_marks(self.bootstrap_servers, self.topic, self.num_partitions)
        total_hwm_initial = sum(hwm_initial.values())
        logger.info("Initial Topic High-Water Mark: %d across %d partitions", total_hwm_initial, self.num_partitions)

        # 3. Dedicated consumer group
        group_id = f"bench-{phase_name.lower()}-{uuid.uuid4().hex[:8]}"

        container_stats_pre = get_container_stats()

        manager = mp.Manager()
        producer_results = manager.dict()
        consumer_results = manager.dict()
        consumer_stop_event = manager.Event()

        target_per_producer = target_rate / max(num_producers, 1) if target_rate > 0 else 0.0

        # 4. Start consumers
        consumer_procs = []
        for i in range(num_consumers):
            p = mp.Process(
                target=consumer_worker,
                args=(i, group_id, consumer_stop_event, self.bootstrap_servers, self.topic, consumer_results),
            )
            consumer_procs.append(p)
            p.start()

        # Let consumers establish partition rebalance
        time.sleep(2.5)

        # Measure pre-test lag
        _, lag_pre_test = get_consumer_group_offsets(group_id, self.bootstrap_servers, self.topic, self.num_partitions)
        logger.info("Consumer Group '%s' initialized (Pre-test Lag: %d)", group_id, lag_pre_test)

        # 5. Start producers
        producer_procs = []
        t_start = time.perf_counter()
        for i in range(num_producers):
            p = mp.Process(
                target=producer_worker,
                args=(
                    i, target_per_producer, duration_sec, self.bootstrap_servers,
                    self.topic, batch_size, linger_ms, producer_results
                ),
            )
            producer_procs.append(p)
            p.start()

        # 6. Monitor progress, peak lag, and resource stats during workload
        peak_backlog = 0
        container_stats_peak = {}
        while any(p.is_alive() for p in producer_procs):
            time.sleep(1.0)
            try:
                _, current_lag = get_consumer_group_offsets(group_id, self.bootstrap_servers, self.topic, self.num_partitions)
                if current_lag > peak_backlog:
                    peak_backlog = current_lag
            except Exception:
                pass
            if not container_stats_peak:
                container_stats_peak = get_container_stats()

        for p in producer_procs:
            p.join()
        t_end_producers = time.perf_counter()
        producer_duration = t_end_producers - t_start

        if not container_stats_peak:
            container_stats_peak = get_container_stats()

        # Measure lag immediately after producer stops
        _, lag_after_producer_stop = get_consumer_group_offsets(group_id, self.bootstrap_servers, self.topic, self.num_partitions)
        peak_backlog = max(peak_backlog, lag_after_producer_stop)

        # 7. Drain backlog until lag <= 100 or timeout
        t_drain_start = time.perf_counter()
        drain_deadline = t_drain_start + 45.0
        final_lag = lag_after_producer_stop
        while time.perf_counter() < drain_deadline:
            _, current_lag = get_consumer_group_offsets(group_id, self.bootstrap_servers, self.topic, self.num_partitions)
            final_lag = current_lag
            if current_lag <= 100:
                break
            time.sleep(0.5)
        recovery_time_sec = time.perf_counter() - t_drain_start

        # Signal consumers to stop and join
        consumer_stop_event.set()
        for p in consumer_procs:
            p.join(timeout=5.0)
        t_end_all = time.perf_counter()
        total_duration = t_end_all - t_start

        container_stats_post = get_container_stats()

        # 8. Post-run metrics & broker watermark accounting
        hwm_final = get_partition_highwater_marks(self.bootstrap_servers, self.topic, self.num_partitions)
        total_hwm_final = sum(hwm_final.values())
        broker_accepted_events = total_hwm_final - total_hwm_initial

        partition_deltas = {p: hwm_final.get(p, 0) - hwm_initial.get(p, 0) for p in range(self.num_partitions)}

        # Aggregations
        total_attempted = sum(r["events_attempted"] for r in producer_results.values())
        total_delivered = sum(r["events_delivered"] for r in producer_results.values())
        total_failed = sum(r["events_failed"] for r in producer_results.values())
        total_unflushed = sum(r["remaining_unflushed"] for r in producer_results.values())
        achieved_producer_rate = total_delivered / max(producer_duration, 0.001)
        broker_ingestion_rate = broker_accepted_events / max(producer_duration, 0.001)

        total_consumed = sum(r["consumed"] for r in consumer_results.values())
        total_processed = sum(r["processed"] for r in consumer_results.values())
        total_duplicates = sum(r["duplicates"] for r in consumer_results.values())
        total_invalid = sum(r["invalid"] for r in consumer_results.values())
        total_consumer_errors = sum(r["consumer_errors"] for r in consumer_results.values())
        total_key_mismatches = sum(r.get("key_body_mismatches", 0) for r in consumer_results.values())
        achieved_consumer_rate = total_processed / max(total_duration, 0.001)

        events_lost = max(0, total_delivered - broker_accepted_events)
        loss_pct = (events_lost / total_delivered * 100.0) if total_delivered > 0 else 0.0

        # Automated Integrity Assertions
        integrity_passed = True
        integrity_failures = []

        if total_attempted != (total_delivered + total_failed):
            integrity_passed = False
            integrity_failures.append(f"Attempted mismatch: {total_attempted} != {total_delivered} + {total_failed}")

        if broker_accepted_events != total_delivered:
            integrity_passed = False
            integrity_failures.append(f"Broker HWM mismatch: broker accepted {broker_accepted_events} != producer delivered {total_delivered}")

        if total_key_mismatches > 0:
            integrity_passed = False
            integrity_failures.append(f"Key-Body VIN mismatches detected: {total_key_mismatches}")

        if total_failed > 0:
            integrity_failures.append(f"Producer failures detected: {total_failed}")

        phase_summary = {
            "phase": phase_name,
            "target_rate_ev_s": target_rate,
            "configured_duration_s": duration_sec,
            "actual_producer_duration_s": round(producer_duration, 2),
            "total_benchmark_duration_s": round(total_duration, 2),
            "producers_count": num_producers,
            "consumers_count": num_consumers,
            "producer_metrics": {
                "events_attempted": total_attempted,
                "events_delivered": total_delivered,
                "events_failed": total_failed,
                "unflushed_events": total_unflushed,
                "delivery_rate_ev_s": round(achieved_producer_rate, 1),
            },
            "broker_metrics": {
                "topic": self.topic,
                "num_partitions": self.num_partitions,
                "initial_total_hwm": total_hwm_initial,
                "final_total_hwm": total_hwm_final,
                "accepted_events": broker_accepted_events,
                "broker_rate_ev_s": round(broker_ingestion_rate, 1),
                "per_partition_deltas": partition_deltas,
            },
            "consumer_metrics": {
                "group_id": group_id,
                "processing_path": "RealTimeWorker(process_message) -> TelemetryValidator, TwoTierDeduplicator, OutOfOrderProtector, StreamingStatsRegistry, HealthAnomalyDetector",
                "events_consumed": total_consumed,
                "events_processed": total_processed,
                "events_duplicate": total_duplicates,
                "events_invalid": total_invalid,
                "key_body_mismatches": total_key_mismatches,
                "consumer_errors": total_consumer_errors,
                "processing_rate_ev_s": round(achieved_consumer_rate, 1),
            },
            "lag_metrics": {
                "lag_pre_test": lag_pre_test,
                "peak_backlog": peak_backlog,
                "lag_after_producer_stop": lag_after_producer_stop,
                "final_lag": final_lag,
                "recovery_time_s": round(recovery_time_sec, 2),
            },
            "integrity": {
                "passed": integrity_passed,
                "failures": integrity_failures,
                "events_lost": events_lost,
                "loss_percentage": round(loss_pct, 4),
            },
            "container_resources": {
                "pre_test": container_stats_pre,
                "peak": container_stats_peak,
                "post_test": container_stats_post,
            },
        }

        logger.info("\n" + "=" * 80)
        logger.info("PHASE SUMMARY: %s", phase_name)
        logger.info("  Target Rate:           %s ev/s", f"{target_rate:,.0f}")
        logger.info("  Events Attempted:      %s", f"{total_attempted:,}")
        logger.info("  Events Delivered:      %s", f"{total_delivered:,}")
        logger.info("  Broker Accepted (HWM): %s", f"{broker_accepted_events:,}")
        logger.info("  Producer Delivery Rate:%s ev/s", f"{achieved_producer_rate:,.1f}")
        logger.info("  Broker Ingestion Rate: %s ev/s", f"{broker_ingestion_rate:,.1f}")
        logger.info("  RealTimeWorker Process:%s", f"{total_processed:,}")
        logger.info("  Consumer Rate:         %s ev/s", f"{achieved_consumer_rate:,.1f}")
        logger.info("  Events Lost:           %d (%.4f%%)", events_lost, loss_pct)
        logger.info("  Peak Backlog:          %s", f"{peak_backlog:,}")
        logger.info("  Drain Recovery Time:   %.2fs", recovery_time_sec)
        logger.info("  Final Consumer Lag:    %s", f"{final_lag:,}")
        logger.info("  Integrity Check:       %s", "PASSED" if integrity_passed else f"FAILED: {integrity_failures}")
        logger.info("=" * 80 + "\n")

        return phase_summary


def main():
    parser = argparse.ArgumentParser(description="FleetGuard Pulse Distributed Ingestion Benchmark")
    parser.add_argument(
        "--mode",
        choices=["baseline", "sustained-100k", "burst-300k", "sequential"],
        default="sequential",
        help="Benchmark mode to execute",
    )
    parser.add_argument(
        "--sustained-duration",
        type=float,
        default=60.0,
        help="Duration in seconds for the sustained 100K test (default: 60s)",
    )
    parser.add_argument(
        "--burst-duration",
        type=float,
        default=10.0,
        help="Duration in seconds for the burst 300K test (default: 10s)",
    )
    parser.add_argument("--output", type=str, default="docs/benchmark_results_phase11.json", help="Output JSON results")
    args = parser.parse_args()

    harness = DistributedIngestionHarness()
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "cpu_cores": os.cpu_count(),
            "python_version": platform.python_version(),
            "redpanda_brokers": BOOTSTRAP_SERVERS,
            "topic": BENCHMARK_TOPIC,
            "partitions": NUM_PARTITIONS,
        },
        "phases": {},
    }

    # 1. Baseline Phase (Phase 11A)
    if args.mode in ["baseline", "sequential"]:
        logger.info("\n>>> EXECUTING BASELINE BENCHMARK (20K TARGET, 15s) <<<")
        res_baseline = harness.run_benchmark_phase(
            phase_name="BASELINE",
            target_rate=20000.0,
            duration_sec=15.0,
            num_producers=4,
            num_consumers=4,
            clean_topic=True,
        )
        results["phases"]["baseline"] = res_baseline
        logger.info("Baseline complete. Cooling down 5.0s...")
        time.sleep(5.0)

    # 2. Sustained 100K Phase (Phase 11B)
    if args.mode in ["sustained-100k", "sequential"]:
        logger.info("\n>>> EXECUTING SUSTAINED 100K BENCHMARK (100K TARGET, %.1fs WINDOW) <<<", args.sustained_duration)
        res_100k = harness.run_benchmark_phase(
            phase_name="SUSTAINED_100K",
            target_rate=100000.0,
            duration_sec=args.sustained_duration,
            num_producers=8,
            num_consumers=8,
            clean_topic=True,
        )
        results["phases"]["sustained_100k"] = res_100k
        logger.info("Sustained 100K complete. Cooling down 8.0s before burst test...")
        time.sleep(8.0)

    # 3. Burst 300K Phase (Phase 11C)
    if args.mode in ["burst-300k", "sequential"]:
        logger.info("\n>>> EXECUTING BURST 300K BENCHMARK (300K TARGET, %.1fs BURST) <<<", args.burst_duration)
        res_300k = harness.run_benchmark_phase(
            phase_name="BURST_300K",
            target_rate=300000.0,
            duration_sec=args.burst_duration,
            num_producers=8,
            num_consumers=8,
            clean_topic=True,
        )
        results["phases"]["burst_300k"] = res_300k

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    logger.info("Results successfully written to %s", args.output)


if __name__ == "__main__":
    main()
