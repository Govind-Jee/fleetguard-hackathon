#!/usr/bin/env python3
"""
FleetGuard Pulse - API Concurrency Bottleneck Profiler (Phase 12C).
Systematically profiles where time is spent during concurrent requests:
1. Client-side total round-trip latency
2. Network / socket accept / worker queue wait time
3. ASGI middleware + routing dispatch time
4. Rate limiter (Redis) pipeline execution time
5. Database connection pool checkout wait time
6. Raw SQL execution time (psycopg2)
7. Response serialization / Pydantic validation time
"""

import asyncio
import gc
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import httpx

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.api.auth.jwt import create_access_token
from services.api.auth.models import UserRole

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fleetguard.profiler")

BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
TENANT_ID = "a0000000-0000-0000-0000-000000000001"
TEST_VIN = "1HGCR2F83HA000001"
TEST_FLEET_ID = "d0000000-0000-0000-0000-000000000001"
TEST_VECTOR = "0.64,2.05,0.59,0.86,3.75,0.49,-1.15,0.44,0.00,0.00,0.00,0.00,0.54,0.88,1.00,0.00"

TOKEN = create_access_token(
    user_id="b0000000-0000-0000-0000-000000000001",
    tenant_id=TENANT_ID,
    email="admin@metrotransit.com",
    roles=[UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN],
)
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}


async def profile_request(
    client: httpx.AsyncClient,
    path: str,
    headers: Dict[str, str],
    sem: asyncio.Semaphore,
) -> Dict[str, Any]:
    async with sem:
        t0 = time.perf_counter()
        resp = await client.get(path, headers=headers)
        t1 = time.perf_counter()

    client_total_ms = (t1 - t0) * 1000.0
    status_code = resp.status_code

    # Extract server-side instrumentation headers if available
    proc_time_ms = float(resp.headers.get("X-Process-Time-Ms", "0"))
    db_checkout_ms = float(resp.headers.get("X-DB-Checkout-Ms", "0"))
    sql_time_ms = float(resp.headers.get("X-SQL-Time-Ms", "0"))
    redis_time_ms = float(resp.headers.get("X-Redis-Time-Ms", "0"))

    queue_wait_ms = max(0.0, client_total_ms - proc_time_ms) if proc_time_ms > 0 else 0.0

    return {
        "client_total_ms": client_total_ms,
        "status_code": status_code,
        "proc_time_ms": proc_time_ms,
        "queue_wait_ms": queue_wait_ms,
        "db_checkout_ms": db_checkout_ms,
        "sql_time_ms": sql_time_ms,
        "redis_time_ms": redis_time_ms,
    }


async def run_profile(
    path: str,
    headers: Dict[str, str],
    concurrency: int,
    num_requests: int = 200,
) -> Dict[str, Any]:
    limits = httpx.Limits(max_connections=concurrency + 50, max_keepalive_connections=concurrency + 20)
    async with httpx.AsyncClient(base_url=BASE_URL, limits=limits, timeout=15.0) as client:
        # Warm-up
        warm_sem = asyncio.Semaphore(min(10, concurrency))
        await asyncio.gather(*[profile_request(client, path, headers, warm_sem) for _ in range(20)])

        sem = asyncio.Semaphore(concurrency)
        tasks = [profile_request(client, path, headers, sem) for _ in range(num_requests)]
        results = await asyncio.gather(*tasks)

    # Compute percentiles
    def p(vals, pct):
        if not vals:
            return 0.0
        s = sorted(vals)
        k = (len(s) - 1) * pct / 100.0
        f = int(k)
        c = f + 1 if f + 1 < len(s) else f
        return s[f] + (k - f) * (s[c] - s[f])

    client_totals = [r["client_total_ms"] for r in results]
    proc_times = [r["proc_time_ms"] for r in results if r["proc_time_ms"] > 0]
    queue_waits = [r["queue_wait_ms"] for r in results if r["proc_time_ms"] > 0]
    db_checkouts = [r["db_checkout_ms"] for r in results if r["db_checkout_ms"] > 0]
    sql_times = [r["sql_time_ms"] for r in results if r["sql_time_ms"] > 0]
    redis_times = [r["redis_time_ms"] for r in results if r["redis_time_ms"] > 0]

    return {
        "concurrency": concurrency,
        "requests": num_requests,
        "status_codes": {code: sum(1 for r in results if r["status_code"] == code) for code in set(r["status_code"] for r in results)},
        "client_p50_ms": round(p(client_totals, 50), 2),
        "client_p95_ms": round(p(client_totals, 95), 2),
        "client_p99_ms": round(p(client_totals, 99), 2),
        "server_proc_p50_ms": round(p(proc_times, 50), 2),
        "server_proc_p95_ms": round(p(proc_times, 95), 2),
        "queue_wait_p50_ms": round(p(queue_waits, 50), 2),
        "queue_wait_p95_ms": round(p(queue_waits, 95), 2),
        "db_checkout_p95_ms": round(p(db_checkouts, 95), 2),
        "sql_time_p95_ms": round(p(sql_times, 95), 2),
        "redis_time_p95_ms": round(p(redis_times, 95), 2),
    }


async def main():
    endpoints = [
        ("GET /health", "/health", {}),
        ("GET /vehicles", "/vehicles?limit=20&page=1", AUTH_HEADERS),
        ("GET /vehicles/{vin}", f"/vehicles/{TEST_VIN}", AUTH_HEADERS),
        ("GET /vehicles/{vin}/risk", f"/vehicles/{TEST_VIN}/risk", AUTH_HEADERS),
        ("GET /alerts", "/alerts", AUTH_HEADERS),
        ("GET /fleets/{fleet_id}/health", f"/fleets/{TEST_FLEET_ID}/health", AUTH_HEADERS),
        ("GET /diagnostics/similar", f"/diagnostics/similar?vector={TEST_VECTOR}&limit=5", AUTH_HEADERS),
    ]

    print("=" * 110)
    print("FLEETGUARD PULSE — CONCURRENCY BOTTLENECK PROFILING REPORT")
    print("=" * 110)
    print(f"{'Endpoint':<30} | {'C':<2} | {'Client p50':<10} | {'Client p95':<10} | {'Server p95':<10} | {'Queue p95':<10} | {'SQL p95':<10} | {'DBchk p95':<10}")
    print("-" * 110)

    for label, path, headers in endpoints:
        for c in [10, 20, 50]:
            stats = await run_profile(path, headers, concurrency=c, num_requests=300)
            print(f"{label:<30} | {c:<2} | {stats['client_p50_ms']:>8.2f}ms | {stats['client_p95_ms']:>8.2f}ms | {stats['server_proc_p95_ms']:>8.2f}ms | {stats['queue_wait_p95_ms']:>8.2f}ms | {stats['sql_time_p95_ms']:>8.2f}ms | {stats['db_checkout_p95_ms']:>8.2f}ms")

if __name__ == "__main__":
    asyncio.run(main())
