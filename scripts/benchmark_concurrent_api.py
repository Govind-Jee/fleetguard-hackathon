#!/usr/bin/env python3
"""
FleetGuard Pulse - Concurrent API Latency SLA Benchmark (Phase 12B - REQ-025)

Measures empirical network latency across core REST endpoints of the running FastAPI server
under multi-client concurrency sweeps (10, 20, and 50 concurrent workers).
Verifies the production latency SLA:
- p95 < 200 ms
- p99 < 500 ms

Endpoints evaluated:
- GET /health (System liveness baseline)
- GET /vehicles (3NF paginated relational query with tenant isolation)
- GET /vehicles/{vin} (Single vehicle relational lookup + Redis hot state)
- GET /vehicles/{vin}/risk (Predictive maintenance ML 7-day failure risk inference + explainability)
- GET /alerts (Durable alert history with tenant filtering)
- GET /fleets/{fleet_id}/health (Fleet health aggregate aggregation query)
- GET /diagnostics/similar (16-D pgvector cosine similarity nearest-neighbor search)
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import platform
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

# Project root import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.api.auth.jwt import create_access_token
from services.api.auth.models import UserRole

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("fleetguard.api_benchmark")

TENANT_1_ID = "a0000000-0000-0000-0000-000000000001"
FLEET_1_ID = "d0000000-0000-0000-0000-000000000001"
ADMIN_USER_ID = "b0000000-0000-0000-0000-000000000001"

SAMPLE_VECTOR = "0.64,2.05,0.59,0.86,3.75,0.49,-1.15,0.44,0.00,0.00,0.00,0.00,0.54,0.88,1.00,0.00"


def get_docker_stats() -> Dict[str, Dict[str, str]]:
    """Capture resource metrics for core datastore containers."""
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
            if len(parts) >= 4 and "fleetguard" in parts[0]:
                stats[parts[0]] = {
                    "cpu_perc": parts[1],
                    "mem_usage": parts[2],
                    "mem_perc": parts[3],
                }
        return stats
    except Exception as e:
        logger.warning("Could not fetch docker stats: %s", e)
        return {}


async def check_api_readiness(base_url: str) -> bool:
    """Verify that FastAPI server is listening and reporting datastore readiness."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/ready")
            if resp.status_code == 200:
                data = resp.json()
                datastores = data.get("datastores", {})
                logger.info("FastAPI Server Ready: %s (Datastores: %s)", base_url, datastores)
                return True
            else:
                logger.error("FastAPI readiness returned HTTP %d: %s", resp.status_code, resp.text)
                return False
    except Exception as e:
        logger.error("Could not connect to FastAPI server at %s: %s", base_url, e)
        return False


async def execute_request_worker(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    headers: Dict[str, str],
    sem: asyncio.Semaphore,
) -> Tuple[float, int, Optional[str]]:
    """Execute a single HTTP request under concurrency semaphore and record round-trip latency."""
    async with sem:
        t0 = time.perf_counter()
        try:
            resp = await client.get(path, headers=headers)
            t1 = time.perf_counter()
            latency_ms = (t1 - t0) * 1000.0
            return latency_ms, resp.status_code, None
        except httpx.TimeoutException:
            t1 = time.perf_counter()
            return (t1 - t0) * 1000.0, 408, "TimeoutException"
        except Exception as e:
            t1 = time.perf_counter()
            return (t1 - t0) * 1000.0, 599, str(e)


async def benchmark_endpoint(
    base_url: str,
    label: str,
    path: str,
    headers: Dict[str, str],
    concurrency: int,
    total_requests: int,
    warmup_requests: int,
) -> Dict[str, Any]:
    """Execute warmup and concurrent load test for a specific endpoint."""
    logger.info("Benchmarking %s (Concurrency=%d, Requests=%d, Warmup=%d)...",
                label, concurrency, total_requests, warmup_requests)

    limits = httpx.Limits(max_connections=concurrency + 50, max_keepalive_connections=concurrency + 20)
    timeout = httpx.Timeout(15.0, connect=5.0)

    async with httpx.AsyncClient(base_url=base_url, limits=limits, timeout=timeout) as client:
        # 1. Warm-up phase
        warmup_sem = asyncio.Semaphore(min(concurrency, 10))
        warmup_tasks = [
            execute_request_worker(client, "GET", path, headers, warmup_sem)
            for _ in range(warmup_requests)
        ]
        await asyncio.gather(*warmup_tasks)

        # 2. Measurement phase
        sem = asyncio.Semaphore(concurrency)
        t_start = time.perf_counter()
        tasks = [
            execute_request_worker(client, "GET", path, headers, sem)
            for _ in range(total_requests)
        ]
        results = await asyncio.gather(*tasks)
        t_end = time.perf_counter()

    wall_time_s = t_end - t_start

    latencies_ms = []
    status_distribution: Dict[str, int] = {}
    errors = 0
    timeouts = 0

    for lat_ms, status_code, err in results:
        latencies_ms.append(lat_ms)
        status_key = str(status_code)
        status_distribution[status_key] = status_distribution.get(status_key, 0) + 1
        if status_code != 200:
            errors += 1
        if status_code == 408 or err == "TimeoutException":
            timeouts += 1

    latencies_ms.sort()
    n = len(latencies_ms)
    mean_ms = sum(latencies_ms) / max(n, 1)
    p50_ms = latencies_ms[int(0.50 * n)] if n else 0.0
    p90_ms = latencies_ms[int(0.90 * n)] if n else 0.0
    p95_ms = latencies_ms[int(0.95 * n)] if n else 0.0
    p99_ms = latencies_ms[int(0.99 * n)] if n else 0.0
    max_ms = latencies_ms[-1] if n else 0.0
    min_ms = latencies_ms[0] if n else 0.0
    throughput_rps = n / max(wall_time_s, 0.001)

    p95_passed = p95_ms < 200.0
    p99_passed = p99_ms < 500.0
    sla_passed = p95_passed and p99_passed and (errors == 0)

    return {
        "endpoint": label,
        "path": path,
        "concurrency": concurrency,
        "total_requests": total_requests,
        "successful_requests": total_requests - errors,
        "failed_requests": errors,
        "timeout_count": timeouts,
        "status_distribution": status_distribution,
        "wall_time_s": round(wall_time_s, 3),
        "throughput_rps": round(throughput_rps, 1),
        "mean_ms": round(mean_ms, 2),
        "min_ms": round(min_ms, 2),
        "p50_ms": round(p50_ms, 2),
        "p90_ms": round(p90_ms, 2),
        "p95_ms": round(p95_ms, 2),
        "p99_ms": round(p99_ms, 2),
        "max_ms": round(max_ms, 2),
        "p95_sla_met": p95_passed,
        "p99_sla_met": p99_passed,
        "sla_passed": sla_passed,
    }


async def run_concurrent_suite(
    base_url: str,
    concurrency_levels: List[int],
    requests_per_endpoint: int,
    warmup_requests: int,
    output_path: str,
):
    """Execute concurrent API benchmark across all endpoints and concurrency levels."""
    logger.info("Initializing Concurrent API Benchmark Suite...")

    # Verify server readiness
    if not await check_api_readiness(base_url):
        logger.error("FastAPI server is not ready at %s. Aborting benchmark.", base_url)
        sys.exit(1)

    # Generate authenticated JWT token
    token = create_access_token(
        user_id=ADMIN_USER_ID,
        tenant_id=TENANT_1_ID,
        email="admin@metrotransit.com",
        roles=[UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN],
    )
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Fetch real valid sample VIN from database
    async with httpx.AsyncClient(base_url=base_url) as client:
        v_res = await client.get("/vehicles?limit=1", headers=auth_headers)
        if v_res.status_code != 200:
            logger.error("Failed to query sample VIN: %s", v_res.text)
            sys.exit(1)
        sample_vin = v_res.json()["items"][0]["vin"]
        logger.info("Sample VIN identified for entity benchmarks: %s", sample_vin)

    endpoints = [
        ("GET /health", "/health", {}),
        ("GET /vehicles", "/vehicles?limit=20&page=1", auth_headers),
        (f"GET /vehicles/{{vin}}", f"/vehicles/{sample_vin}", auth_headers),
        (f"GET /vehicles/{{vin}}/risk", f"/vehicles/{sample_vin}/risk", auth_headers),
        ("GET /alerts", "/alerts?limit=20&page=1", auth_headers),
        (f"GET /fleets/{{fleet_id}}/health", f"/fleets/{FLEET_1_ID}/health", auth_headers),
        ("GET /diagnostics/similar", f"/diagnostics/similar?vector={SAMPLE_VECTOR}&limit=5", auth_headers),
    ]

    benchmark_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "cpu_cores": os.cpu_count(),
            "python_version": platform.python_version(),
            "fastapi_base_url": base_url,
            "target_sla": {
                "p95_max_ms": 200.0,
                "p99_max_ms": 500.0,
            },
        },
        "concurrency_sweep": {},
        "resource_snapshots": {},
    }

    # Capture initial container stats
    benchmark_data["resource_snapshots"]["initial"] = get_docker_stats()

    all_results_flat = []

    for conc in concurrency_levels:
        logger.info("\n" + "=" * 80)
        logger.info(">>> EXECUTING CONCURRENCY LEVEL: %d CLIENTS <<<", conc)
        logger.info("=" * 80)

        level_results = []
        for label, path, req_headers in endpoints:
            res = await benchmark_endpoint(
                base_url=base_url,
                label=label,
                path=path,
                headers=req_headers,
                concurrency=conc,
                total_requests=requests_per_endpoint,
                warmup_requests=warmup_requests,
            )
            level_results.append(res)
            all_results_flat.append(res)
            time.sleep(0.5)  # brief cooldown between endpoints

        benchmark_data["concurrency_sweep"][f"concurrency_{conc}"] = level_results
        benchmark_data["resource_snapshots"][f"post_concurrency_{conc}"] = get_docker_stats()

    # Save raw JSON results
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(benchmark_data, f, indent=2)
    logger.info("Raw benchmark results successfully saved to %s", output_path)

    # Print Formatted Markdown Table
    print("\n" + "=" * 110)
    print("FLEETGUARD PULSE — CONCURRENT API LATENCY SLA BENCHMARK REPORT (REQ-025)")
    print("=" * 110)
    print(f"{'Endpoint':<32} | {'Concurrency':<11} | {'Requests':<8} | {'p50 (ms)':<9} | {'p95 (ms)':<9} | {'p99 (ms)':<9} | {'Max (ms)':<9} | {'Errors':<6} | {'SLA Status':<10}")
    print("-" * 110)
    for r in all_results_flat:
        sla_str = "PASS" if r["sla_passed"] else "FAIL"
        print(f"{r['endpoint']:<32} | {r['concurrency']:<11} | {r['total_requests']:<8} | {r['p50_ms']:<9.2f} | {r['p95_ms']:<9.2f} | {r['p99_ms']:<9.2f} | {r['max_ms']:<9.2f} | {r['failed_requests']:<6} | {sla_str:<10}")
    print("=" * 110)

    # Overall SLA Determination
    all_passed = all(r["sla_passed"] for r in all_results_flat)
    print(f"\nOVERALL REQ-025 SLA RESULT: {'ALL PASS (PROVEN)' if all_passed else 'DEGRADED / NOT PROVEN'}")


def main():
    parser = argparse.ArgumentParser(description="FleetGuard Pulse Concurrent API Latency Benchmark")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:8000", help="FastAPI Base URL (default: http://127.0.0.1:8000)")
    parser.add_argument("--concurrency", type=str, default="10,20,50", help="Comma-separated concurrency levels (default: 10,20,50)")
    parser.add_argument("--requests", type=int, default=1000, help="Measured requests per endpoint per concurrency (default: 1000)")
    parser.add_argument("--warmup", type=int, default=50, help="Warmup requests per endpoint (default: 50)")
    parser.add_argument("--output", type=str, default="docs/api_concurrent_benchmark_phase12.json", help="Output JSON path")
    args = parser.parse_args()

    concurrency_levels = [int(c.strip()) for c in args.concurrency.split(",") if c.strip()]
    asyncio.run(run_concurrent_suite(
        base_url=args.url,
        concurrency_levels=concurrency_levels,
        requests_per_endpoint=args.requests,
        warmup_requests=args.warmup,
        output_path=args.output,
    ))


if __name__ == "__main__":
    main()
