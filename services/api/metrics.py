"""
FleetGuard Pulse - API Prometheus Metrics Registry.
Maintains thread-safe in-memory counters, gauges, and latency histograms,
and exports them in standard Prometheus exposition format at /metrics.
"""

import threading
import time
from typing import Dict, List, Tuple


class APIMetricsRegistry:
    """Thread-safe Prometheus metrics collector for FleetGuard Pulse API."""

    def __init__(self):
        self._lock = threading.Lock()

        # HTTP Requests: (method, endpoint, status_code) -> count
        self._http_requests_total: Dict[Tuple[str, str, int], int] = {}

        # HTTP Latencies: (method, endpoint) -> (count, sum_seconds)
        self._http_request_duration_sum: Dict[Tuple[str, str], float] = {}
        self._http_request_duration_count: Dict[Tuple[str, str], int] = {}

        # Latency buckets (seconds): 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, +Inf
        self._duration_buckets = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
        # (method, endpoint, le) -> count
        self._http_duration_bucket_counts: Dict[Tuple[str, str, float], int] = {}

        # Active WebSockets
        self._active_ws_connections: int = 0

        # ML Predictions: (model_version) -> count
        self._ml_predictions_total: Dict[str, int] = {}
        self._ml_prediction_duration_sum: float = 0.0
        self._ml_prediction_duration_count: int = 0

        # Datastore errors: (store) -> count
        self._db_errors_total: Dict[str, int] = {}

        # Rate limit rejections: (tenant_id) -> count
        self._rate_limit_rejections_total: int = 0

    def record_request(self, method: str, endpoint: str, status_code: int, duration_seconds: float) -> None:
        """Record completed HTTP request and duration."""
        with self._lock:
            # 1. Counter
            key = (method, endpoint, status_code)
            self._http_requests_total[key] = self._http_requests_total.get(key, 0) + 1

            # 2. Duration summary
            dur_key = (method, endpoint)
            self._http_request_duration_sum[dur_key] = (
                self._http_request_duration_sum.get(dur_key, 0.0) + duration_seconds
            )
            self._http_request_duration_count[dur_key] = (
                self._http_request_duration_count.get(dur_key, 0) + 1
            )

            # 3. Histogram buckets
            for b in self._duration_buckets:
                if duration_seconds <= b:
                    b_key = (method, endpoint, b)
                    self._http_duration_bucket_counts[b_key] = (
                        self._http_duration_bucket_counts.get(b_key, 0) + 1
                    )

    def inc_ws_connections(self) -> None:
        with self._lock:
            self._active_ws_connections += 1

    def dec_ws_connections(self) -> None:
        with self._lock:
            self._active_ws_connections = max(0, self._active_ws_connections - 1)

    def record_prediction(self, model_version: str, duration_seconds: float) -> None:
        with self._lock:
            self._ml_predictions_total[model_version] = (
                self._ml_predictions_total.get(model_version, 0) + 1
            )
            self._ml_prediction_duration_sum += duration_seconds
            self._ml_prediction_duration_count += 1

    def record_db_error(self, store: str) -> None:
        with self._lock:
            self._db_errors_total[store] = self._db_errors_total.get(store, 0) + 1

    def record_rate_limit_rejection(self) -> None:
        with self._lock:
            self._rate_limit_rejections_total += 1

    def export_prometheus_text(self) -> str:
        """Render metrics in Prometheus text exposition format."""
        lines: List[str] = [
            "# HELP fleetguard_http_requests_total Total HTTP requests processed by endpoint and status.",
            "# TYPE fleetguard_http_requests_total counter",
        ]
        with self._lock:
            for (m, ep, st), count in sorted(self._http_requests_total.items()):
                lines.append(
                    f'fleetguard_http_requests_total{{method="{m}",endpoint="{ep}",status="{st}"}} {count}'
                )

            lines.extend([
                "",
                "# HELP fleetguard_http_request_duration_seconds HTTP request duration in seconds.",
                "# TYPE fleetguard_http_request_duration_seconds histogram",
            ])
            for (m, ep), count in sorted(self._http_request_duration_count.items()):
                sum_sec = self._http_request_duration_sum.get((m, ep), 0.0)
                # Buckets
                for b in self._duration_buckets:
                    b_count = self._http_duration_bucket_counts.get((m, ep, b), 0)
                    lines.append(
                        f'fleetguard_http_request_duration_seconds_bucket{{method="{m}",endpoint="{ep}",le="{b}"}} {b_count}'
                    )
                lines.append(
                    f'fleetguard_http_request_duration_seconds_bucket{{method="{m}",endpoint="{ep}",le="+Inf"}} {count}'
                )
                lines.append(
                    f'fleetguard_http_request_duration_seconds_sum{{method="{m}",endpoint="{ep}"}} {sum_sec:.6f}'
                )
                lines.append(
                    f'fleetguard_http_request_duration_seconds_count{{method="{m}",endpoint="{ep}"}} {count}'
                )

            lines.extend([
                "",
                "# HELP fleetguard_active_ws_connections Currently connected WebSocket alert clients.",
                "# TYPE fleetguard_active_ws_connections gauge",
                f"fleetguard_active_ws_connections {self._active_ws_connections}",
                "",
                "# HELP fleetguard_ml_predictions_total Total ML inference requests executed.",
                "# TYPE fleetguard_ml_predictions_total counter",
            ])
            for ver, count in sorted(self._ml_predictions_total.items()):
                lines.append(f'fleetguard_ml_predictions_total{{version="{ver}"}} {count}')

            lines.extend([
                "",
                "# HELP fleetguard_ml_prediction_duration_seconds ML inference duration in seconds.",
                "# TYPE fleetguard_ml_prediction_duration_seconds summary",
                f"fleetguard_ml_prediction_duration_seconds_sum {self._ml_prediction_duration_sum:.6f}",
                f"fleetguard_ml_prediction_duration_seconds_count {self._ml_prediction_duration_count}",
                "",
                "# HELP fleetguard_db_errors_total Total backend datastore connectivity or query errors.",
                "# TYPE fleetguard_db_errors_total counter",
            ])
            for store, count in sorted(self._db_errors_total.items()):
                lines.append(f'fleetguard_db_errors_total{{store="{store}"}} {count}')

            lines.extend([
                "",
                "# HELP fleetguard_rate_limit_exceeded_total Total HTTP 429 rate limit events.",
                "# TYPE fleetguard_rate_limit_exceeded_total counter",
                f"fleetguard_rate_limit_exceeded_total {self._rate_limit_rejections_total}",
            ])

        return "\n".join(lines) + "\n"


# Global singleton metrics instance
api_metrics = APIMetricsRegistry()
