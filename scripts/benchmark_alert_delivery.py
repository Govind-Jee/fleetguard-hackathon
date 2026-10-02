#!/usr/bin/env python3
"""
FleetGuard Pulse - End-to-End Critical Alert Delivery Latency Benchmark (Phase 12E / REQ-024)

Empirically validates REQ-024:
"Critical alert delivery under 5 seconds from ingestion to notification/dispatch."

Measures true end-to-end latency across all five decoupled segments:
  1. Telemetry Producer -> Redpanda Broker Ack (t1 - t0)
  2. Broker Queue -> RealTimeWorker Consume (t2 - t1)
  3. RealTimeWorker Detection & Alert Publish -> vehicle.alerts.v1 (t3 - t2)
  4. Alerts Topic -> Alert Bridge -> WebSocket Broadcast -> Client Receipt (t4 - t3)
  5. Total End-to-End: Ingestion Reference -> WebSocket Client Receipt (t4 - t0)

Runs two controlled conditions:
  - Test A: Normal Controlled Stream (1,000 critical events at controlled rate, zero background)
  - Test B: Concurrent Stream Pressure (1,000 critical events interleaved with active background load)
"""

import argparse
from datetime import datetime, timezone
import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

import httpx
import websockets
from websockets.sync.client import connect as ws_connect
from confluent_kafka import Producer, Consumer, KafkaError

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.simulator.schema import TelemetryEvent, VehicleType
from services.stream_processor.workers.real_time_worker import RealTimeWorker
from services.stream_processor.workers.alert_bridge_worker import AlertBridgeWorker
from services.api.auth.jwt import create_access_token
from services.api.auth.models import UserRole

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fleetguard.alert_benchmark")

TENANT_ID = "a0000000-0000-0000-0000-000000000001"


def compute_percentiles(values: List[float]) -> Dict[str, float]:
    """Calculate statistical distribution percentiles."""
    if not values:
        return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0, "std": 0.0}
    s = sorted(values)
    n = len(s)
    def pct(p: float) -> float:
        idx = int(math.ceil(p / 100.0 * n)) - 1
        return s[max(0, min(idx, n - 1))]

    mean_val = sum(s) / n
    variance = sum((x - mean_val) ** 2 for x in s) / n if n > 1 else 0.0
    return {
        "p50": round(pct(50), 2),
        "p90": round(pct(90), 2),
        "p95": round(pct(95), 2),
        "p99": round(pct(99), 2),
        "min": round(s[0], 2),
        "max": round(s[-1], 2),
        "mean": round(mean_val, 2),
        "std": round(math.sqrt(variance), 2),
    }


class InstrumentedRealTimeWorker(RealTimeWorker):
    """RealTimeWorker instrumented with granular timestamp capture per benchmark event."""

    def __init__(self, timeline: Dict[str, Dict[str, float]], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeline = timeline

    def process_message(self, raw_value: bytes) -> bool:
        t_consume = time.perf_counter()
        # Parse event_id quickly to record t2
        try:
            ev_data = json.loads(raw_value.decode("utf-8"))
            event_id = ev_data.get("event_id")
            if event_id and event_id in self.timeline:
                self.timeline[event_id]["t2_worker_consume"] = t_consume
        except Exception:
            event_id = None

        res = super().process_message(raw_value)

        t_processed = time.perf_counter()
        if event_id and event_id in self.timeline:
            self.timeline[event_id]["t3_alert_pub"] = t_processed

        return res


class InstrumentedAlertBridge(AlertBridgeWorker):
    """AlertBridgeWorker instrumented to record bridge forwarding timestamp."""

    def __init__(self, timeline: Dict[str, Dict[str, float]], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeline = timeline

    def process_message(self, raw_value: bytes) -> bool:
        t_bridge_start = time.perf_counter()
        try:
            alert_data = json.loads(raw_value.decode("utf-8"))
            event_id = alert_data.get("event_id")
        except Exception:
            event_id = None

        res = super().process_message(raw_value)

        t_bridge_done = time.perf_counter()
        if event_id and event_id in self.timeline:
            self.timeline[event_id]["t3b_bridge_forward"] = t_bridge_done

        return res


class AlertDeliveryBenchmarkHarness:
    """Orchestrates end-to-end alert delivery latency measurement across Redpanda and WebSocket."""

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        telemetry_topic: str = "vehicle.telemetry.v1",
        alerts_topic: str = "vehicle.alerts.v1",
        api_base_url: str = "http://127.0.0.1:8000",
        ws_url: str = "ws://127.0.0.1:8000/ws/alerts",
        tenant_id: str = TENANT_ID,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.telemetry_topic = telemetry_topic
        self.alerts_topic = alerts_topic
        self.api_base_url = api_base_url
        self.ws_url = ws_url
        self.tenant_id = tenant_id

        # Generate authentication token
        self.token = create_access_token(
            user_id="benchmark-alert-user",
            tenant_id=tenant_id,
            email="benchmark@metrotransit.com",
            roles=[UserRole.ADMIN, UserRole.DISPATCHER],
        )

    def verify_server_ready(self) -> bool:
        """Ensure FastAPI /health endpoint responds."""
        try:
            resp = httpx.get(f"{self.api_base_url}/health", timeout=3.0)
            return resp.status_code == 200
        except Exception as e:
            logger.error("FastAPI server not responsive at %s: %s", self.api_base_url, e)
            return False

    def query_consumer_lag(self, group_id: str) -> int:
        """Query Redpanda consumer group lag."""
        try:
            res = subprocess.run(
                ["docker", "exec", "fleetguard-redpanda", "rpk", "group", "describe", group_id, "-p"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode != 0:
                return 0
            total_lag = 0
            for line in res.stdout.splitlines():
                parts = line.split()
                # Typical rpk format: TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG ...
                if len(parts) >= 5 and parts[0] == self.telemetry_topic:
                    try:
                        lag = int(parts[4])
                        total_lag += max(0, lag)
                    except ValueError:
                        pass
            return total_lag
        except Exception:
            return 0

    def generate_critical_event(self, vin: str, seq: int) -> TelemetryEvent:
        """Generate canonical ICE telemetry event with deterministic ENGINE_OVERHEAT trigger."""
        return TelemetryEvent(
            schema_version="1.0",
            event_id=str(uuid.uuid4()),
            vin=vin,
            timestamp=datetime.now(timezone.utc).isoformat(),
            sequence_number=seq,
            vehicle_type=VehicleType.ICE,
            latitude=37.7749,
            longitude=-122.4194,
            speed_kmh=65.0,
            odometer_km=14200.0 + seq,
            vibration=0.35,  # Sub-critical normal vibration
            dtc_codes=[],
            oil_pressure_kpa=320.0,
            coolant_temp_c=118.5,  # Deterministic ENGINE_OVERHEAT (>= 115.0 C)
            engine_rpm=2200.0,
            battery_voltage_v=14.1,
        )

    def generate_normal_event(self, vin: str, seq: int) -> TelemetryEvent:
        """Generate normal non-alerting telemetry event for background stream pressure."""
        return TelemetryEvent(
            schema_version="1.0",
            event_id=str(uuid.uuid4()),
            vin=vin,
            timestamp=datetime.now(timezone.utc).isoformat(),
            sequence_number=seq,
            vehicle_type=VehicleType.ICE,
            latitude=37.7749,
            longitude=-122.4194,
            speed_kmh=60.0,
            odometer_km=10000.0 + seq,
            vibration=0.30,
            dtc_codes=[],
            oil_pressure_kpa=340.0,
            coolant_temp_c=88.0,  # Completely normal operating temp
            engine_rpm=2000.0,
            battery_voltage_v=14.2,
        )

    def run_condition(
        self,
        condition_name: str,
        critical_event_count: int = 1000,
        critical_target_rate: float = 50.0,
        background_event_count: int = 0,
        background_target_rate: float = 0.0,
    ) -> Dict[str, Any]:
        """Execute a controlled test condition and return empirical distribution metrics."""
        logger.info(
            "=== Starting Condition: %s (Critical: %d @ %.1f ev/s | Background: %d @ %.1f ev/s) ===",
            condition_name,
            critical_event_count,
            critical_target_rate,
            background_event_count,
            background_target_rate,
        )

        test_run_id = uuid.uuid4().hex[:8]
        rt_group = f"alert-bench-rt-{test_run_id}"
        bridge_group = f"alert-bench-bridge-{test_run_id}"

        # Timeline registry: event_id -> dict of timestamps
        timeline: Dict[str, Dict[str, float]] = {}
        expected_event_ids: Set[str] = set()
        received_alerts: List[Dict[str, Any]] = []
        duplicate_alerts: List[str] = []
        unrelated_alerts: List[str] = []

        # 1. Initialize Workers
        rt_worker = InstrumentedRealTimeWorker(
            timeline=timeline,
            bootstrap_servers=self.bootstrap_servers,
            group_id=rt_group,
            telemetry_topic=self.telemetry_topic,
            alerts_topic=self.alerts_topic,
            auto_offset_reset="latest",
            enable_downstream_persistence=True,
        )

        bridge_worker = InstrumentedAlertBridge(
            timeline=timeline,
            bootstrap_servers=self.bootstrap_servers,
            alerts_topic=self.alerts_topic,
            group_id=bridge_group,
            broadcast_url=f"{self.api_base_url}/ws/broadcast",
            auto_offset_reset="latest",
        )

        # 2. Warm up consumer partition assignments
        logger.info("Warming up consumer group partition assignments...")
        rt_worker.consumer.subscribe([self.telemetry_topic])
        bridge_worker.consumer.subscribe([self.alerts_topic])
        for _ in range(10):
            rt_worker.consumer.poll(0.2)
            bridge_worker.consumer.poll(0.2)
        logger.info("Consumer assignments established.")

        # 3. Start Workers in Threads
        thread_rt = threading.Thread(target=rt_worker.run, daemon=True)
        thread_bridge = threading.Thread(target=bridge_worker.run, daemon=True)
        thread_rt.start()
        thread_bridge.start()

        time.sleep(0.5)

        # 4. Connect WebSocket Client (Synchronous Client inside dedicated thread)
        ws_connected_event = threading.Event()
        ws_stop_event = threading.Event()
        ws_uri = f"{self.ws_url}?token={self.token}"

        def websocket_listener():
            try:
                with ws_connect(ws_uri, max_size=10_000_000) as ws:
                    init_raw = ws.recv(timeout=5.0)
                    init_data = json.loads(init_raw)
                    if init_data.get("type") == "CONNECTION_ESTABLISHED":
                        ws_connected_event.set()

                    while not ws_stop_event.is_set():
                        try:
                            msg = ws.recv(timeout=0.2)
                        except Exception:
                            continue
                        t_recv = time.perf_counter()

                        try:
                            frame = json.loads(msg)
                        except Exception:
                            continue

                        if frame.get("type") != "CRITICAL_ALERT":
                            continue

                        alert_obj = frame.get("alert", {})
                        ev_id = alert_obj.get("event_id") or alert_obj.get("telemetry_event_id")
                        if not ev_id:
                            continue

                        if ev_id in expected_event_ids:
                            if ev_id in timeline and "t4_ws_receive" in timeline[ev_id]:
                                duplicate_alerts.append(ev_id)
                            else:
                                if ev_id in timeline:
                                    timeline[ev_id]["t4_ws_receive"] = t_recv
                                received_alerts.append({
                                    "event_id": ev_id,
                                    "alert_id": alert_obj.get("alert_id"),
                                    "vin": alert_obj.get("vin"),
                                    "fault_type": alert_obj.get("fault_type"),
                                    "recv_time": t_recv,
                                })
                        else:
                            unrelated_alerts.append(ev_id)
            except Exception as e:
                logger.warning("WebSocket listener encountered exception: %s", e)

        thread_ws = threading.Thread(target=websocket_listener, daemon=True)
        thread_ws.start()

        if not ws_connected_event.wait(timeout=5.0):
            raise RuntimeError("WebSocket failed to establish connection within 5.0 seconds")
        logger.info("WebSocket connected and listening on %s", ws_uri)

        # 5. Prepare Test Events
        logger.info("Pre-generating %d critical events...", critical_event_count)
        critical_events: List[TelemetryEvent] = []
        for i in range(1, critical_event_count + 1):
            vin = f"1HGCR2F83HA{i:06d}"
            ev = self.generate_critical_event(vin=vin, seq=1)
            critical_events.append(ev)
            expected_event_ids.add(ev.event_id)
            timeline[ev.event_id] = {
                "t0_ingest": 0.0,
                "t1_broker_ack": 0.0,
                "t2_worker_consume": 0.0,
                "t3_alert_pub": 0.0,
                "t3b_bridge_forward": 0.0,
                "t4_ws_receive": 0.0,
            }

        # Background events if pressure condition
        bg_events: List[TelemetryEvent] = []
        if background_event_count > 0:
            logger.info("Pre-generating %d background normal telemetry events...", background_event_count)
            for j in range(1, background_event_count + 1):
                vin_bg = f"1FLC000000{j:06d}"
                bg_events.append(self.generate_normal_event(vin=vin_bg, seq=1))

        # 6. Producer Configuration
        producer = Producer({
            "bootstrap.servers": self.bootstrap_servers,
            "linger.ms": 0,
            "acks": "all",
            "retries": 3,
        })

        def ack_callback(err, msg):
            t_ack = time.perf_counter()
            if err is None:
                try:
                    raw = msg.value()
                    data = json.loads(raw.decode("utf-8"))
                    ev_id = data.get("event_id")
                    if ev_id in timeline:
                        timeline[ev_id]["t1_broker_ack"] = t_ack
                except Exception:
                    pass

        # 7. Execution: Stream Injection
        logger.info("Starting ingestion stream...")
        start_time = time.perf_counter()
        peak_lag = 0

        # Run background producer thread if background_event_count > 0
        bg_stop_event = threading.Event()
        if bg_events:
            def background_producer_worker():
                interval = 1.0 / background_target_rate if background_target_rate > 0 else 0
                for bg_ev in bg_events:
                    if bg_stop_event.is_set():
                        break
                    producer.produce(
                        topic=self.telemetry_topic,
                        key=bg_ev.vin.encode("utf-8"),
                        value=bg_ev.model_dump_json().encode("utf-8"),
                    )
                    producer.poll(0)
                    if interval > 0:
                        time.sleep(interval)

            t_bg = threading.Thread(target=background_producer_worker, daemon=True)
            t_bg.start()

        # Ingest Critical Events at Controlled Rate
        crit_interval = 1.0 / critical_target_rate if critical_target_rate > 0 else 0
        for idx, ev in enumerate(critical_events):
            t0 = time.perf_counter()
            timeline[ev.event_id]["t0_ingest"] = t0
            producer.produce(
                topic=self.telemetry_topic,
                key=ev.vin.encode("utf-8"),
                value=ev.model_dump_json().encode("utf-8"),
                callback=ack_callback,
            )
            producer.poll(0)

            # Sample lag periodically
            if idx % 100 == 0:
                cur_lag = self.query_consumer_lag(rt_group)
                if cur_lag > peak_lag:
                    peak_lag = cur_lag

            if crit_interval > 0:
                time.sleep(crit_interval)

        producer.flush(10.0)
        bg_stop_event.set()
        logger.info("All %d critical events dispatched to broker. Awaiting WebSocket delivery...", critical_event_count)

        # 8. Wait for Complete WebSocket Delivery or Timeout
        deadline = time.perf_counter() + 15.0
        while time.perf_counter() < deadline:
            cur_lag = self.query_consumer_lag(rt_group)
            if cur_lag > peak_lag:
                peak_lag = cur_lag

            if len(received_alerts) >= critical_event_count:
                break
            time.sleep(0.1)

        total_duration = time.perf_counter() - start_time
        ws_stop_event.set()
        rt_worker.stop()
        bridge_worker.stop()

        # 9. Compute Metric Distributions
        e2e_latencies: List[float] = []
        seg1_latencies: List[float] = []
        seg2_latencies: List[float] = []
        seg3_latencies: List[float] = []
        seg4_latencies: List[float] = []

        for ev_id in expected_event_ids:
            entry = timeline.get(ev_id, {})
            t0 = entry.get("t0_ingest", 0.0)
            t1 = entry.get("t1_broker_ack", 0.0)
            t2 = entry.get("t2_worker_consume", 0.0)
            t3 = entry.get("t3_alert_pub", 0.0)
            t3b = entry.get("t3b_bridge_forward", 0.0)
            t4 = entry.get("t4_ws_receive", 0.0)

            if t0 > 0 and t4 > 0 and t4 >= t0:
                e2e_latencies.append((t4 - t0) * 1000.0)

            if t0 > 0 and t1 > 0 and t1 >= t0:
                seg1_latencies.append((t1 - t0) * 1000.0)

            if t1 > 0 and t2 > 0 and t2 >= t1:
                seg2_latencies.append((t2 - t1) * 1000.0)

            if t2 > 0 and t3 > 0 and t3 >= t2:
                seg3_latencies.append((t3 - t2) * 1000.0)

            if t3 > 0 and t4 > 0 and t4 >= t3:
                seg4_latencies.append((t4 - t3) * 1000.0)

        e2e_stats = compute_percentiles(e2e_latencies)
        seg1_stats = compute_percentiles(seg1_latencies)
        seg2_stats = compute_percentiles(seg2_latencies)
        seg3_stats = compute_percentiles(seg3_latencies)
        seg4_stats = compute_percentiles(seg4_latencies)

        received_count = len(received_alerts)
        missing_count = critical_event_count - received_count
        duplicate_count = len(duplicate_alerts)
        unrelated_count = len(unrelated_alerts)

        loss_rate = (missing_count / critical_event_count) * 100.0 if critical_event_count > 0 else 0.0
        duplicate_rate = (duplicate_count / critical_event_count) * 100.0 if critical_event_count > 0 else 0.0

        # REQ-024 SLA Evaluation: p95 < 5,000 ms (5.0 seconds) and 0 loss
        is_sla_met = (
            e2e_stats["p95"] < 5000.0
            and e2e_stats["p99"] < 5000.0
            and missing_count == 0
            and duplicate_count == 0
        )

        return {
            "condition": condition_name,
            "critical_events_sent": critical_event_count,
            "background_events_sent": background_event_count,
            "expected_alerts": critical_event_count,
            "received_alerts": received_count,
            "missing_alerts": missing_count,
            "duplicate_alerts": duplicate_count,
            "unrelated_alerts": unrelated_count,
            "loss_rate_pct": round(loss_rate, 4),
            "duplicate_rate_pct": round(duplicate_rate, 4),
            "total_duration_sec": round(total_duration, 2),
            "effective_critical_rate_rps": round(critical_event_count / total_duration, 2) if total_duration > 0 else 0.0,
            "peak_consumer_lag": peak_lag,
            "sla_target_ms": 5000.0,
            "sla_met": is_sla_met,
            "end_to_end_latency_ms": e2e_stats,
            "segment_latencies_ms": {
                "segment_1_producer_to_broker_ack": seg1_stats,
                "segment_2_broker_to_worker_consume": seg2_stats,
                "segment_3_worker_detect_to_alert_pub": seg3_stats,
                "segment_4_alert_pub_to_ws_receive": seg4_stats,
            },
        }


def main():
    parser = argparse.ArgumentParser(description="FleetGuard Pulse - REQ-024 Critical Alert Latency Benchmark")
    parser.add_argument("--condition", choices=["all", "normal", "pressure"], default="all", help="Test condition to run")
    parser.add_argument("--events", type=int, default=1000, help="Number of critical events to inject")
    parser.add_argument("--rate", type=float, default=50.0, help="Injection rate (events/sec)")
    parser.add_argument("--bg-events", type=int, default=5000, help="Background event count for pressure test")
    parser.add_argument("--bg-rate", type=float, default=500.0, help="Background injection rate (events/sec)")
    parser.add_argument("--output", default="docs/alert_delivery_benchmark_phase12e.json", help="Path to save raw JSON results")
    args = parser.parse_args()

    harness = AlertDeliveryBenchmarkHarness()

    if not harness.verify_server_ready():
        logger.error("API server is not responsive at %s. Please start Uvicorn first.", harness.api_base_url)
        sys.exit(1)

    results: Dict[str, Any] = {
        "benchmark": "FleetGuard Pulse - REQ-024 End-to-End Critical Alert Delivery Latency",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "sla_threshold_ms": 5000.0,
        "environment": {
            "os": sys.platform,
            "python_version": sys.version.split()[0],
            "api_endpoint": harness.api_base_url,
            "ws_endpoint": harness.ws_url,
            "redpanda_broker": harness.bootstrap_servers,
            "telemetry_topic": harness.telemetry_topic,
            "alerts_topic": harness.alerts_topic,
        },
        "conditions": {},
    }

    if args.condition in ("all", "normal"):
        res_a = harness.run_condition(
            condition_name="Test A: Normal Controlled Stream",
            critical_event_count=args.events,
            critical_target_rate=args.rate,
            background_event_count=0,
            background_target_rate=0.0,
        )
        results["conditions"]["test_a_normal"] = res_a

    if args.condition in ("all", "pressure"):
        # Let topic settle
        time.sleep(1.0)
        res_b = harness.run_condition(
            condition_name="Test B: Concurrent Stream Pressure",
            critical_event_count=args.events,
            critical_target_rate=args.rate,
            background_event_count=args.bg_events,
            background_target_rate=args.bg_rate,
        )
        results["conditions"]["test_b_pressure"] = res_b

    # Print Formatted Results
    print("\n" + "=" * 90)
    print("FLEETGUARD PULSE — REQ-024 END-TO-END CRITICAL ALERT DELIVERY BENCHMARK REPORT")
    print("=" * 90)
    print(f"SLA Target: Critical alert delivery in < 5,000 ms (5.0 seconds) from ingestion\n")

    print("| Condition | Events | Received | Missing | Duplicates | Loss % | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) | Peak Lag | SLA Status |")
    print("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |")
    for key, c in results["conditions"].items():
        e2e = c["end_to_end_latency_ms"]
        status_str = "PASS" if c["sla_met"] else "FAIL"
        print(
            f"| {c['condition']} | {c['critical_events_sent']:,} | {c['received_alerts']:,} | "
            f"{c['missing_alerts']} | {c['duplicate_alerts']} | {c['loss_rate_pct']:.2f}% | "
            f"{e2e['p50']} | {e2e['p95']} | {e2e['p99']} | {e2e['max']} | {c['peak_consumer_lag']} | **{status_str}** |"
        )

    print("\n" + "-" * 90)
    print("SEGMENT LATENCY BREAKDOWN (p50 / p95 / p99 in ms):")
    print("-" * 90)
    for key, c in results["conditions"].items():
        print(f"\nCondition: {c['condition']}")
        segs = c["segment_latencies_ms"]
        print(f"  1. Producer -> Broker Ack:       p50={segs['segment_1_producer_to_broker_ack']['p50']} ms | p95={segs['segment_1_producer_to_broker_ack']['p95']} ms | p99={segs['segment_1_producer_to_broker_ack']['p99']} ms")
        print(f"  2. Broker Queue -> Worker:       p50={segs['segment_2_broker_to_worker_consume']['p50']} ms | p95={segs['segment_2_broker_to_worker_consume']['p95']} ms | p99={segs['segment_2_broker_to_worker_consume']['p99']} ms")
        print(f"  3. Worker Detect & Alert Pub:    p50={segs['segment_3_worker_detect_to_alert_pub']['p50']} ms | p95={segs['segment_3_worker_detect_to_alert_pub']['p95']} ms | p99={segs['segment_3_worker_detect_to_alert_pub']['p99']} ms")
        print(f"  4. Alerts Topic -> WS Delivery:  p50={segs['segment_4_alert_pub_to_ws_receive']['p50']} ms | p95={segs['segment_4_alert_pub_to_ws_receive']['p95']} ms | p99={segs['segment_4_alert_pub_to_ws_receive']['p99']} ms")
        print(f"  --> Total End-to-End Latency:    p50={c['end_to_end_latency_ms']['p50']} ms | p95={c['end_to_end_latency_ms']['p95']} ms | p99={c['end_to_end_latency_ms']['p99']} ms")

    # Save to JSON
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    logger.info("Raw benchmark results written to %s", args.output)


if __name__ == "__main__":
    main()
