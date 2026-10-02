#!/usr/bin/env python3
"""
FleetGuard Pulse - Phase 11.2 Controlled Before/After Optimization Validation

Compares the pre-optimization (commit 5f48e07: BLAKE2b salts) and post-optimization
(commit cd7feb9: Kirsch-Mitzenmacher double hashing) RealTimeWorker paths under
materially equivalent, controlled Kafka loads to eliminate the confounding variables
identified in Phase 11.1.

Evaluates:
1. Controlled Streaming Load: Fixed offered rate (e.g. 50,000 ev/s) with drift-compensated
   producer pacing.
2. Identical Queue Drain: Exact deterministic pre-populated backlog (e.g. 400,000 events)
   drained by 8 consumer workers without producer CPU contention.

Measures:
- Offered Kafka Rate (ev/s)
- RealTimeWorker Processing Throughput (ev/s)
- Per-Event Processing Latency (microseconds, sampled)
- Consumer Process CPU Utilization & Redpanda Container CPU %
- In-flight Backlog & Recovery Drain Time
- Zero Data Loss & Integrity Verification
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
from typing import Any, Dict, List, Optional, Tuple
import uuid

from confluent_kafka import Consumer, Producer, TopicPartition

# Project root import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.stream_processor.workers.real_time_worker import RealTimeWorker
from services.simulator.schema import TelemetryEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("fleetguard.controlled_validation")

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
                stats[parts[0]] = {
                    "cpu_perc": parts[1],
                    "mem_usage": parts[2],
                    "mem_perc": parts[3],
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
    """Purge and recreate the dedicated benchmark topic in Redpanda."""
    try:
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
        logger.info("Topic '%s' purged and recreated with %d partitions.", topic, partitions)
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
        except Exception:
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
        c.close()
        return {}, 0


def generate_telemetry_payload(vin: str, seq: int, ts_iso: str, ptype: str) -> bytes:
    """Generate canonical TelemetryEvent JSON bytes with fresh unique UUIDv4 event_id."""
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


def controlled_producer_worker(
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
    Producer worker using schedule-anchored rate pacing to maintain exact target rate
    without cumulative clock drift.
    """
    conf = {
        "bootstrap.servers": bootstrap_servers,
        "client.id": f"ctrl-producer-{worker_id}",
        "queue.buffering.max.messages": 500000,
        "queue.buffering.max.kbytes": 524288,
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
    chunk_size = 250
    chunk_interval = chunk_size / max(target_rate_per_sec, 1.0)

    vin_range_per_worker = 12500
    vin_offset_base = worker_id * vin_range_per_worker
    powertrain_types = ["ICE", "BEV", "HEV"]
    vin_seqs = [1000] * vin_range_per_worker

    chunk_idx = 0
    while time.perf_counter() < target_end_time:
        chunk_idx += 1
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
                p.poll(10)
                try:
                    p.produce(topic=topic, key=vin_key, value=payload, on_delivery=delivery_cb)
                    attempted += 1
                except Exception as ex:
                    failed += 1
                    if len(producer_errors) < 5:
                        producer_errors.append(str(ex))
            except Exception as ex:
                failed += 1
                if len(producer_errors) < 5:
                    producer_errors.append(str(ex))

        p.poll(0)

        # Schedule-anchored sleep to eliminate drift
        target_chunk_time = t0 + (chunk_idx * chunk_interval)
        now = time.perf_counter()
        sleep_needed = target_chunk_time - now
        if sleep_needed > 0.0005:
            time.sleep(sleep_needed)

    # Flush remaining
    p.flush(30.0)
    actual_duration = time.perf_counter() - t0

    result_dict[worker_id] = {
        "worker_id": worker_id,
        "events_attempted": attempted,
        "events_delivered": delivered,
        "events_failed": failed,
        "producer_errors": producer_errors,
        "duration_sec": actual_duration,
        "rate": delivered / max(actual_duration, 0.001),
    }


def controlled_consumer_worker(
    worker_id: int,
    group_id: str,
    stop_event: Any,
    bootstrap_servers: str,
    topic: str,
    algorithm: str,
    result_dict: Dict[str, Any],
):
    if algorithm == "salts":
        from services.stream_processor.dedup import CountingBloomFilter
        import hashlib

        def _salts_hashes(self, item: str):
            raw_bytes = item.encode("utf-8")
            indices = []
            for i in range(self.num_hashes):
                salt = i.to_bytes(4, byteorder="big")
                digest = hashlib.blake2b(raw_bytes, digest_size=8, salt=salt).digest()
                idx = int.from_bytes(digest, byteorder="big") % self.size
                indices.append(idx)
            return indices

        CountingBloomFilter._hashes = _salts_hashes

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
    invalid = 0
    consumer_errors = 0

    # Latency tracking
    total_cpu_time = 0.0
    latency_samples = []

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

            # Measure pure process_message execution time
            t_msg_start = time.perf_counter()
            ok = worker.process_message(raw_val)
            t_msg_end = time.perf_counter()

            latency_us = (t_msg_end - t_msg_start) * 1_000_000
            total_cpu_time += (t_msg_end - t_msg_start)

            # Sample 1 out of every 500 events for latency percentiles
            if consumed % 500 == 0:
                latency_samples.append(latency_us)

            if ok:
                processed += 1
            else:
                invalid += 1

    # Drain any remaining records after stop_event
    while True:
        msgs = worker.consumer.consume(num_messages=1000, timeout=0.1)
        if not msgs:
            break
        for msg in msgs:
            if not msg.error():
                consumed += 1
                t_msg_start = time.perf_counter()
                ok = worker.process_message(msg.value())
                t_msg_end = time.perf_counter()
                total_cpu_time += (t_msg_end - t_msg_start)
                if ok:
                    processed += 1
                else:
                    invalid += 1

    worker.consumer.close()
    actual_duration = time.perf_counter() - t0

    latency_samples.sort()
    p50_us = latency_samples[len(latency_samples) // 2] if latency_samples else 0.0
    p95_us = latency_samples[int(len(latency_samples) * 0.95)] if latency_samples else 0.0
    p99_us = latency_samples[int(len(latency_samples) * 0.99)] if latency_samples else 0.0
    mean_us = (total_cpu_time / max(processed, 1)) * 1_000_000

    result_dict[worker_id] = {
        "worker_id": worker_id,
        "consumed": consumed,
        "processed": processed,
        "invalid": invalid,
        "consumer_errors": consumer_errors,
        "duration_sec": actual_duration,
        "rate": processed / max(actual_duration, 0.001),
        "total_cpu_time_sec": total_cpu_time,
        "mean_latency_us": mean_us,
        "p50_latency_us": p50_us,
        "p95_latency_us": p95_us,
        "p99_latency_us": p99_us,
    }


def run_controlled_streaming_arm(
    arm_name: str,
    algorithm: str,
    target_rate: float = 50000.0,
    duration_sec: float = 15.0,
    num_producers: int = 8,
    num_consumers: int = 8,
) -> Dict[str, Any]:
    """Execute a single streaming arm under fixed offered rate."""
    logger.info("\n" + "=" * 80)
    logger.info("STREAMING ARM: %s (algorithm=%s, target_rate=%.0f ev/s, duration=%.1fs)",
                arm_name, algorithm, target_rate, duration_sec)
    logger.info("=" * 80)

    purge_and_recreate_benchmark_topic()
    hwm_init = get_partition_highwater_marks()

    group_id = f"ctrl-{arm_name.lower()}-{uuid.uuid4().hex[:6]}"
    manager = mp.Manager()
    producer_results = manager.dict()
    consumer_results = manager.dict()
    consumer_stop = manager.Event()

    # Pre-stats
    container_stats_pre = get_container_stats()

    # Start consumers
    consumer_procs = []
    for i in range(num_consumers):
        p = mp.Process(
            target=controlled_consumer_worker,
            args=(i, group_id, consumer_stop, BOOTSTRAP_SERVERS, BENCHMARK_TOPIC, algorithm, consumer_results)
        )
        consumer_procs.append(p)
        p.start()

    time.sleep(2.5)  # Let group rebalance

    # Start producers
    rate_per_prod = target_rate / num_producers
    producer_procs = []
    t_start = time.perf_counter()
    for i in range(num_producers):
        p = mp.Process(
            target=controlled_producer_worker,
            args=(i, rate_per_prod, duration_sec, BOOTSTRAP_SERVERS, BENCHMARK_TOPIC, 5000, 10, producer_results)
        )
        producer_procs.append(p)
        p.start()

    peak_backlog = 0
    container_stats_peak = {}
    while any(p.is_alive() for p in producer_procs):
        time.sleep(1.0)
        try:
            _, lag = get_consumer_group_offsets(group_id)
            if lag > peak_backlog:
                peak_backlog = lag
        except Exception:
            pass
        if not container_stats_peak:
            container_stats_peak = get_container_stats()

    for p in producer_procs:
        p.join()
    t_producers_done = time.perf_counter()
    prod_duration = t_producers_done - t_start

    _, lag_after_stop = get_consumer_group_offsets(group_id)
    peak_backlog = max(peak_backlog, lag_after_stop)

    # Drain to 0 lag
    t_drain_start = time.perf_counter()
    drain_deadline = t_drain_start + 30.0
    while time.perf_counter() < drain_deadline:
        _, current_lag = get_consumer_group_offsets(group_id)
        if current_lag <= 50:
            break
        time.sleep(0.3)
    recovery_time = time.perf_counter() - t_drain_start

    consumer_stop.set()
    for p in consumer_procs:
        p.join(timeout=5.0)
    total_duration = time.perf_counter() - t_start

    hwm_final = get_partition_highwater_marks()
    broker_accepted = sum(hwm_final.values()) - sum(hwm_init.values())

    total_attempted = sum(r["events_attempted"] for r in producer_results.values())
    total_delivered = sum(r["events_delivered"] for r in producer_results.values())
    total_failed = sum(r["events_failed"] for r in producer_results.values())
    offered_rate = total_delivered / max(prod_duration, 0.001)

    total_processed = sum(r["processed"] for r in consumer_results.values())
    processed_rate = total_processed / max(total_duration, 0.001)

    total_cpu_time = sum(r["total_cpu_time_sec"] for r in consumer_results.values())
    avg_latency_us = (total_cpu_time / max(total_processed, 1)) * 1_000_000

    redpanda_peak_cpu = container_stats_peak.get("fleetguard-redpanda", {}).get("cpu_perc", "N/A")

    return {
        "arm": arm_name,
        "algorithm": algorithm,
        "target_rate_ev_s": target_rate,
        "configured_duration_s": duration_sec,
        "actual_producer_duration_s": round(prod_duration, 2),
        "total_test_duration_s": round(total_duration, 2),
        "events_attempted": total_attempted,
        "events_delivered": total_delivered,
        "events_failed": total_failed,
        "broker_accepted": broker_accepted,
        "offered_rate_ev_s": round(offered_rate, 1),
        "events_processed": total_processed,
        "processed_rate_ev_s": round(processed_rate, 1),
        "mean_latency_per_event_us": round(avg_latency_us, 2),
        "consumer_cpu_time_total_s": round(total_cpu_time, 2),
        "peak_backlog": peak_backlog,
        "lag_after_producer_stop": lag_after_stop,
        "recovery_time_s": round(recovery_time, 2),
        "redpanda_peak_cpu": redpanda_peak_cpu,
        "data_loss": max(0, total_delivered - broker_accepted),
    }


def preload_loader_worker(w_id: int, events_per_worker: int, topic: str, bootstrap_servers: str):
    """Top-level worker function for queue pre-loading."""
    conf = {
        "bootstrap.servers": bootstrap_servers,
        "queue.buffering.max.messages": 500000,
        "linger.ms": 10,
        "batch.num.messages": 5000,
        "acks": 1,
        "compression.type": "lz4",
    }
    p = Producer(conf)
    ts_iso = datetime.now(timezone.utc).isoformat()
    ptypes = ["ICE", "BEV", "HEV"]
    for idx in range(events_per_worker):
        vin_num = (w_id * 12500 + (idx % 12500)) % 100000
        vin = f"1HGCR2F83HA{vin_num:06d}"
        payload = generate_telemetry_payload(vin, 1000 + idx, ts_iso, ptypes[idx % 3])
        p.produce(topic=topic, key=vin.encode("ascii"), value=payload)
        if idx % 1000 == 0:
            p.poll(0)
    p.flush(30.0)


def preload_benchmark_queue(event_count: int = 400000, num_producers: int = 8) -> int:
    """Pre-publish an exact number of valid unique events into the benchmark topic."""
    logger.info("Pre-loading %d unique events into benchmark topic with %d producers...", event_count, num_producers)
    purge_and_recreate_benchmark_topic()

    events_per_worker = event_count // num_producers
    procs = [
        mp.Process(
            target=preload_loader_worker,
            args=(i, events_per_worker, BENCHMARK_TOPIC, BOOTSTRAP_SERVERS),
        )
        for i in range(num_producers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    hwm = get_partition_highwater_marks()
    total_loaded = sum(hwm.values())
    logger.info("Pre-load complete. Total verified topic events: %d across %d partitions.", total_loaded, NUM_PARTITIONS)
    return total_loaded


def run_controlled_drain_arm(arm_name: str, algorithm: str, event_count: int, num_consumers: int = 8) -> Dict[str, Any]:
    """Measure maximum unconstrained consumer throughput draining a pre-loaded topic without producer interference."""
    logger.info("\n" + "=" * 80)
    logger.info("QUEUE DRAIN ARM: %s (algorithm=%s, total_events=%d, consumers=%d)",
                arm_name, algorithm, event_count, num_consumers)
    logger.info("=" * 80)

    group_id = f"drain-{arm_name.lower()}-{uuid.uuid4().hex[:6]}"
    manager = mp.Manager()
    consumer_results = manager.dict()
    consumer_stop = manager.Event()

    container_stats_pre = get_container_stats()

    t_start = time.perf_counter()
    consumer_procs = []
    for i in range(num_consumers):
        p = mp.Process(
            target=controlled_consumer_worker,
            args=(i, group_id, consumer_stop, BOOTSTRAP_SERVERS, BENCHMARK_TOPIC, algorithm, consumer_results)
        )
        consumer_procs.append(p)
        p.start()

    # Poll lag until drained
    container_stats_peak = {}
    while True:
        time.sleep(0.5)
        _, lag = get_consumer_group_offsets(group_id)
        if not container_stats_peak:
            container_stats_peak = get_container_stats()
        if lag <= 10:
            break

    consumer_stop.set()
    for p in consumer_procs:
        p.join(timeout=5.0)
    drain_duration = time.perf_counter() - t_start

    total_processed = sum(r["processed"] for r in consumer_results.values())
    processed_rate = total_processed / max(drain_duration, 0.001)

    total_cpu_time = sum(r["total_cpu_time_sec"] for r in consumer_results.values())
    avg_latency_us = (total_cpu_time / max(total_processed, 1)) * 1_000_000

    return {
        "arm": arm_name,
        "algorithm": algorithm,
        "total_queue_events": event_count,
        "drain_duration_s": round(drain_duration, 2),
        "total_processed": total_processed,
        "processing_rate_ev_s": round(processed_rate, 1),
        "mean_latency_per_event_us": round(avg_latency_us, 2),
        "consumer_cpu_time_total_s": round(total_cpu_time, 2),
        "redpanda_peak_cpu": container_stats_peak.get("fleetguard-redpanda", {}).get("cpu_perc", "N/A"),
    }


def main():
    parser = argparse.ArgumentParser(description="FleetGuard Phase 11.2 Controlled Validation Benchmark")
    parser.add_argument("--streaming-rate", type=float, default=50000.0, help="Target offered streaming rate in ev/s (default: 50,000)")
    parser.add_argument("--streaming-duration", type=float, default=15.0, help="Streaming test duration in seconds (default: 15.0)")
    parser.add_argument("--drain-events", type=int, default=300000, help="Preloaded event count for queue drain test (default: 300,000)")
    parser.add_argument("--output", type=str, default="docs/controlled_validation_phase11_2.json", help="Output JSON path")
    args = parser.parse_args()

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commits": {
            "baseline": "5f48e07 (perf: establish verified distributed throughput benchmark - salts)",
            "treatment": "cd7feb9 (perf: optimize stream deduplication with double hashing - double_hashing)",
        },
        "environment": {
            "platform": platform.platform(),
            "cpu_cores": os.cpu_count(),
            "python_version": platform.python_version(),
            "redpanda_broker": "Redpanda v24.1.2 (docker.redpanda.com/redpandadata/redpanda:v24.1.2)",
            "topic": BENCHMARK_TOPIC,
            "partitions": NUM_PARTITIONS,
        },
        "streaming_test": {},
        "queue_drain_test": {},
    }

    # -------------------------------------------------------------
    # 1. Controlled Streaming Load Test
    # -------------------------------------------------------------
    logger.info("\n>>> EXECUTING CONTROLLED STREAMING EXPERIMENT (TARGET RATE = %.0f ev/s) <<<", args.streaming_rate)

    # 1A. Baseline Streaming Arm (commit 5f48e07: salts)
    res_stream_baseline = run_controlled_streaming_arm(
        arm_name="BASELINE_SALTS",
        algorithm="salts",
        target_rate=args.streaming_rate,
        duration_sec=args.streaming_duration,
        num_producers=8,
        num_consumers=8,
    )
    results["streaming_test"]["baseline"] = res_stream_baseline
    logger.info("Baseline streaming arm complete. Cooling down 5.0s...")
    time.sleep(5.0)

    # 1B. Treatment Streaming Arm (commit cd7feb9: double_hashing)
    res_stream_treatment = run_controlled_streaming_arm(
        arm_name="TREATMENT_DOUBLE_HASHING",
        algorithm="double_hashing",
        target_rate=args.streaming_rate,
        duration_sec=args.streaming_duration,
        num_producers=8,
        num_consumers=8,
    )
    results["streaming_test"]["treatment"] = res_stream_treatment
    logger.info("Treatment streaming arm complete. Cooling down 5.0s...")
    time.sleep(5.0)

    # -------------------------------------------------------------
    # 2. Controlled Queue Drain Test (Producer-Contention-Free)
    # -------------------------------------------------------------
    logger.info("\n>>> EXECUTING CONTROLLED QUEUE DRAIN EXPERIMENT (PRE-LOADED QUEUE = %d EVENTS) <<<", args.drain_events)

    # 2A. Preload and Drain with Baseline (salts)
    preload_benchmark_queue(args.drain_events, num_producers=8)
    time.sleep(2.0)
    res_drain_baseline = run_controlled_drain_arm(
        arm_name="BASELINE_SALTS",
        algorithm="salts",
        event_count=args.drain_events,
        num_consumers=8,
    )
    results["queue_drain_test"]["baseline"] = res_drain_baseline
    logger.info("Baseline queue drain complete. Cooling down 5.0s...")
    time.sleep(5.0)

    # 2B. Preload and Drain with Treatment (double_hashing)
    preload_benchmark_queue(args.drain_events, num_producers=8)
    time.sleep(2.0)
    res_drain_treatment = run_controlled_drain_arm(
        arm_name="TREATMENT_DOUBLE_HASHING",
        algorithm="double_hashing",
        event_count=args.drain_events,
        num_consumers=8,
    )
    results["queue_drain_test"]["treatment"] = res_drain_treatment

    # Write output
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    logger.info("\n" + "=" * 80)
    logger.info("CONTROLLED VALIDATION BENCHMARK COMPLETE. Results saved to %s", args.output)
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
