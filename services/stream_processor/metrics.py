"""
FleetGuard Pulse - Stream Processing Metrics

Thread-safe metrics collection and Prometheus exposition for stream processing workers.
"""

import threading
import time
from typing import Any, Dict


class StreamMetrics:
    """Thread-safe metrics collector for telemetry stream processing pipeline."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters = {
            "events_received": 0,
            "events_valid": 0,
            "events_invalid": 0,
            "events_duplicate": 0,
            "events_out_of_order": 0,
            "redis_state_updates": 0,
            "alerts_critical": 0,
            "alerts_warning": 0,
            "mongodb_persisted": 0,
            "clickhouse_persisted": 0,
        }
        self._latencies_ms = []
        self._max_latency_samples = 1000
        self._start_time = time.time()

    def increment(self, metric: str, value: int = 1) -> None:
        """Increment a metric counter."""
        with self._lock:
            if metric in self._counters:
                self._counters[metric] += value
            else:
                self._counters[metric] = value

    def record_latency(self, latency_ms: float) -> None:
        """Record processing latency for an event."""
        with self._lock:
            if len(self._latencies_ms) >= self._max_latency_samples:
                self._latencies_ms.pop(0)
            self._latencies_ms.append(latency_ms)

    def snapshot(self) -> Dict[str, Any]:
        """Return a snapshot of current metrics."""
        with self._lock:
            latencies = list(self._latencies_ms)
            avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
            p99_latency = (
                sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0.0
            )
            uptime_sec = time.time() - self._start_time
            rate_sec = self._counters.get("events_received", 0) / max(uptime_sec, 0.001)

            return {
                **self._counters,
                "uptime_seconds": round(uptime_sec, 2),
                "avg_latency_ms": round(avg_latency, 3),
                "p99_latency_ms": round(p99_latency, 3),
                "throughput_events_per_sec": round(rate_sec, 2),
            }

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus text exposition format."""
        s = self.snapshot()
        lines = [
            "# HELP fleetguard_stream_events_received_total Total events received from Redpanda",
            "# TYPE fleetguard_stream_events_received_total counter",
            f"fleetguard_stream_events_received_total {s['events_received']}",
            "",
            "# HELP fleetguard_stream_events_valid_total Total events passing schema validation",
            "# TYPE fleetguard_stream_events_valid_total counter",
            f"fleetguard_stream_events_valid_total {s['events_valid']}",
            "",
            "# HELP fleetguard_stream_events_invalid_total Total events failing schema validation",
            "# TYPE fleetguard_stream_events_invalid_total counter",
            f"fleetguard_stream_events_invalid_total {s['events_invalid']}",
            "",
            "# HELP fleetguard_stream_events_duplicate_total Total duplicate events suppressed",
            "# TYPE fleetguard_stream_events_duplicate_total counter",
            f"fleetguard_stream_events_duplicate_total {s['events_duplicate']}",
            "",
            "# HELP fleetguard_stream_events_out_of_order_total Total out-of-order events detected",
            "# TYPE fleetguard_stream_events_out_of_order_total counter",
            f"fleetguard_stream_events_out_of_order_total {s['events_out_of_order']}",
            "",
            "# HELP fleetguard_stream_redis_updates_total Total Redis hot state hash updates",
            "# TYPE fleetguard_stream_redis_updates_total counter",
            f"fleetguard_stream_redis_updates_total {s['redis_state_updates']}",
            "",
            "# HELP fleetguard_stream_alerts_total Total health alerts emitted by severity",
            "# TYPE fleetguard_stream_alerts_total counter",
            f'fleetguard_stream_alerts_total{{severity="CRITICAL"}} {s["alerts_critical"]}',
            f'fleetguard_stream_alerts_total{{severity="WARNING"}} {s["alerts_warning"]}',
            "",
            "# HELP fleetguard_stream_mongodb_persisted_total Total raw events written to MongoDB",
            "# TYPE fleetguard_stream_mongodb_persisted_total counter",
            f"fleetguard_stream_mongodb_persisted_total {s['mongodb_persisted']}",
            "",
            "# HELP fleetguard_stream_clickhouse_persisted_total Total events written to ClickHouse",
            "# TYPE fleetguard_stream_clickhouse_persisted_total counter",
            f"fleetguard_stream_clickhouse_persisted_total {s['clickhouse_persisted']}",
            "",
            "# HELP fleetguard_stream_latency_ms Average event processing latency in milliseconds",
            "# TYPE fleetguard_stream_latency_ms gauge",
            f"fleetguard_stream_latency_ms {s['avg_latency_ms']}",
        ]
        return "\n".join(lines) + "\n"


# Shared global metrics instance
default_metrics = StreamMetrics()
