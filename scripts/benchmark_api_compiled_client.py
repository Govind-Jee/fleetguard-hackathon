#!/usr/bin/env python3
"""
FleetGuard Pulse - Unbiased Concurrent API Latency Validation (Phase 12D).
Uses a compiled external load generator (/usr/sbin/ab - ApacheBench) to generate
concurrent load against the live FastAPI instance on loopback TCP sockets.
Eliminates client-side Python asyncio / GIL scheduling contention.
"""

import argparse
from datetime import datetime, timezone
import json
import logging
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import psycopg2

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.api.auth.jwt import create_access_token
from services.api.auth.models import UserRole

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fleetguard.compiled_benchmark")

AB_PATH = "/usr/sbin/ab"
BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
TENANT_ID = "a0000000-0000-0000-0000-000000000001"
TEST_VIN = "1HGCR2F83HA000001"
TEST_FLEET_ID = "d0000000-0000-0000-0000-000000000001"
TEST_VECTOR = "0.64,2.05,0.59,0.86,3.75,0.49,-1.15,0.44,0.00,0.00,0.00,0.00,0.54,0.88,1.00,0.00"

# Keycloak-compatible dev JWT token with multi-tenant roles
TOKEN = create_access_token(
    user_id="b0000000-0000-0000-0000-000000000001",
    tenant_id=TENANT_ID,
    email="admin@metrotransit.com",
    roles=[UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN],
)
AUTH_HEADER = f"Authorization: Bearer {TOKEN}"


def check_prerequisites() -> bool:
    """Verify ApacheBench binary exists and FastAPI server is ready."""
    if not os.path.isfile(AB_PATH) or not os.access(AB_PATH, os.X_OK):
        logger.error("ApacheBench not found or not executable at %s", AB_PATH)
        return False

    try:
        import urllib.request
        with urllib.request.urlopen(f"{BASE_URL}/ready", timeout=5.0) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode())
                logger.info("FastAPI Server Ready at %s (Datastores: %s)", BASE_URL, body.get("datastores"))
                return True
            else:
                logger.error("FastAPI /ready returned HTTP %d", resp.status)
                return False
    except Exception as e:
        logger.error("Failed to connect to FastAPI at %s: %s", BASE_URL, e)
        return False


def get_postgres_active_connections() -> int:
    """Query current active connection count from PostgreSQL."""
    try:
        conn = psycopg2.connect(
            host="localhost", port=5433, dbname="fleetguard",
            user="fleetguard_user", password="fleetguard_dev_password",
            connect_timeout=2,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_stat_activity WHERE state IS NOT NULL;")
            cnt = cur.fetchone()[0]
        conn.close()
        return cnt
    except Exception:
        return -1


def parse_ab_output(stdout: str) -> Dict[str, Any]:
    """Parse ApacheBench text output to extract structured latency and throughput metrics."""
    data: Dict[str, Any] = {
        "complete_requests": 0,
        "failed_requests": 0,
        "non_2xx_responses": 0,
        "time_taken_s": 0.0,
        "throughput_rps": 0.0,
        "mean_ms": 0.0,
        "median_ms": 0.0,
        "min_ms": 0.0,
        "max_ms": 0.0,
        "percentiles": {},
    }

    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("Complete requests:"):
            m = re.search(r"Complete requests:\s+(\d+)", line)
            if m: data["complete_requests"] = int(m.group(1))
        elif line.startswith("Failed requests:"):
            m = re.search(r"Failed requests:\s+(\d+)", line)
            if m: data["failed_requests"] = int(m.group(1))
        elif line.startswith("Non-2xx responses:"):
            m = re.search(r"Non-2xx responses:\s+(\d+)", line)
            if m: data["non_2xx_responses"] = int(m.group(1))
        elif line.startswith("Time taken for tests:"):
            m = re.search(r"Time taken for tests:\s+([\d\.]+)", line)
            if m: data["time_taken_s"] = float(m.group(1))
        elif line.startswith("Requests per second:"):
            m = re.search(r"Requests per second:\s+([\d\.]+)", line)
            if m: data["throughput_rps"] = float(m.group(1))
        elif line.startswith("Time per request:") and "(mean)" in line and "(mean, across" not in line:
            m = re.search(r"Time per request:\s+([\d\.]+)", line)
            if m: data["mean_ms"] = float(m.group(1))
        elif line.startswith("Total:") and "min" not in line:
            parts = re.split(r"\s+", line)
            # Total: min mean sd median max
            if len(parts) >= 6:
                try:
                    data["min_ms"] = float(parts[1])
                    data["median_ms"] = float(parts[4])
                    data["max_ms"] = float(parts[5])
                except ValueError:
                    pass
        elif "%" in line:
            m = re.match(r"(\d+)%\s+(\d+)", line)
            if m:
                pct = int(m.group(1))
                val_ms = float(m.group(2))
                data["percentiles"][str(pct)] = val_ms
                if pct == 50:
                    data["p50_ms"] = val_ms
                elif pct == 90:
                    data["p90_ms"] = val_ms
                elif pct == 95:
                    data["p95_ms"] = val_ms
                elif pct == 99:
                    data["p99_ms"] = val_ms
                elif pct == 100:
                    data["max_ms"] = val_ms

    if "p50_ms" not in data and data["median_ms"] > 0:
        data["p50_ms"] = data["median_ms"]

    return data


def run_ab(url: str, concurrency: int, requests: int, is_authenticated: bool = True) -> Tuple[Dict[str, Any], str]:
    """Execute /usr/sbin/ab command and return structured metrics."""
    cmd = [
        AB_PATH,
        "-n", str(requests),
        "-c", str(concurrency),
    ]
    if is_authenticated:
        cmd.extend(["-H", AUTH_HEADER])
    cmd.append(url)

    t0 = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True)
    t1 = time.perf_counter()

    parsed = parse_ab_output(res.stdout)
    parsed["wall_time_s"] = round(t1 - t0, 3)
    parsed["command"] = " ".join(cmd[:4] + (["-H 'Authorization: Bearer <token>'"] if is_authenticated else []) + [cmd[-1]])
    return parsed, res.stdout


def benchmark_endpoint(
    label: str,
    path: str,
    concurrency: int,
    requests: int,
    warmup: int,
    is_authenticated: bool = True,
) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    logger.info("Testing %s | Concurrency=%d | Requests=%d...", label, concurrency, requests)

    # 1. Warm-up
    if warmup > 0:
        warmup_c = min(concurrency, 10)
        run_ab(url, concurrency=warmup_c, requests=warmup, is_authenticated=is_authenticated)

    # Sample resource metrics before
    pg_conns_before = get_postgres_active_connections()

    # 2. Measurement run
    metrics, raw_stdout = run_ab(url, concurrency=concurrency, requests=requests, is_authenticated=is_authenticated)

    pg_conns_after = get_postgres_active_connections()

    p95 = metrics.get("p95_ms", 0.0)
    p99 = metrics.get("p99_ms", 0.0)
    errors = metrics.get("failed_requests", 0) + metrics.get("non_2xx_responses", 0)

    p95_passed = (p95 <= 200.0)
    p99_passed = (p99 <= 500.0)
    sla_passed = p95_passed and p99_passed and (errors == 0)

    result = {
        "endpoint": label,
        "path": path,
        "concurrency": concurrency,
        "total_requests": requests,
        "completed_requests": metrics.get("complete_requests", requests),
        "failed_requests": metrics.get("failed_requests", 0),
        "non_2xx_responses": metrics.get("non_2xx_responses", 0),
        "throughput_rps": metrics.get("throughput_rps", 0.0),
        "mean_ms": metrics.get("mean_ms", 0.0),
        "p50_ms": metrics.get("p50_ms", 0.0),
        "p90_ms": metrics.get("p90_ms", 0.0),
        "p95_ms": p95,
        "p99_ms": p99,
        "max_ms": metrics.get("max_ms", 0.0),
        "wall_time_s": metrics.get("wall_time_s", 0.0),
        "pg_active_conns_peak": max(pg_conns_before, pg_conns_after),
        "p95_sla_met": p95_passed,
        "p99_sla_met": p99_passed,
        "sla_passed": sla_passed,
        "command": metrics.get("command", ""),
    }

    status_str = "PASS" if sla_passed else "FAIL"
    logger.info("  -> %s c=%d: p50=%.1fms | p95=%.1fms | p99=%.1fms | RPS=%.1f | Errors=%d [%s]",
                label, concurrency, result["p50_ms"], result["p95_ms"], result["p99_ms"],
                result["throughput_rps"], errors, status_str)
    return result


def main():
    parser = argparse.ArgumentParser(description="Unbiased Concurrent API Latency SLA Benchmark (Phase 12D)")
    parser.add_argument("--concurrency", type=str, default="10,20,50", help="Comma-separated concurrency tiers")
    parser.add_argument("--requests", type=int, default=1000, help="Requests per benchmark block")
    parser.add_argument("--warmup", type=int, default=50, help="Warm-up requests before measurement")
    parser.add_argument("--output", type=str, default="docs/api_concurrent_benchmark_phase12d.json", help="Output JSON path")
    args = parser.parse_args()

    if not check_prerequisites():
        sys.exit(1)

    concurrency_tiers = [int(c.strip()) for c in args.concurrency.split(",") if c.strip()]

    endpoints = [
        ("GET /health", "/health", False),
        ("GET /vehicles", "/vehicles?limit=20&page=1", True),
        ("GET /vehicles/{vin}", f"/vehicles/{TEST_VIN}", True),
        ("GET /vehicles/{vin}/risk", f"/vehicles/{TEST_VIN}/risk", True),
        ("GET /alerts", "/alerts", True),
        ("GET /fleets/{fleet_id}/health", f"/fleets/{TEST_FLEET_ID}/health", True),
        ("GET /diagnostics/similar", f"/diagnostics/similar?vector={TEST_VECTOR}&limit=5", True),
    ]

    results_by_tier: Dict[str, List[Dict[str, Any]]] = {}
    all_summary: List[Dict[str, Any]] = []

    for c in concurrency_tiers:
        tier_key = f"concurrency_{c}"
        results_by_tier[tier_key] = []
        for label, path, is_auth in endpoints:
            res = benchmark_endpoint(
                label=label,
                path=path,
                concurrency=c,
                requests=args.requests,
                warmup=args.warmup,
                is_authenticated=is_auth,
            )
            results_by_tier[tier_key].append(res)
            all_summary.append(res)

    # Write output JSON
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "12D",
        "benchmark_type": "compiled_client_unbiased",
        "client_binary": AB_PATH,
        "environment": {
            "platform": "macOS Darwin arm64",
            "fastapi_base_url": BASE_URL,
            "target_sla": {
                "p95_max_ms": 200.0,
                "p99_max_ms": 500.0,
                "max_allowed_errors": 0,
            },
        },
        "concurrency_sweep": results_by_tier,
    }

    out_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    logger.info("Benchmark results saved to %s", out_path)

    # Print summary table
    print("\n" + "=" * 125)
    print("FLEETGUARD PULSE — UNBIASED COMPILED CLIENT API LATENCY BENCHMARK REPORT (PHASE 12D - REQ-025)")
    print("=" * 125)
    print(f"{'Endpoint':<30} | {'C':<2} | {'Reqs':<5} | {'p50 (ms)':<9} | {'p95 (ms)':<9} | {'p99 (ms)':<9} | {'Max (ms)':<9} | {'RPS':<8} | {'Errors':<6} | {'SLA Status'}")
    print("-" * 125)
    for r in all_summary:
        status_str = "PASS" if r["sla_passed"] else "FAIL"
        errs = r["failed_requests"] + r["non_2xx_responses"]
        print(f"{r['endpoint']:<30} | {r['concurrency']:<2} | {r['total_requests']:<5} | {r['p50_ms']:>9.1f} | {r['p95_ms']:>9.1f} | {r['p99_ms']:>9.1f} | {r['max_ms']:>9.1f} | {r['throughput_rps']:>8.1f} | {errs:>6} | {status_str}")
    print("=" * 125)


if __name__ == "__main__":
    main()
