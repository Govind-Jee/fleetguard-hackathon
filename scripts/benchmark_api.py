"""
FleetGuard Pulse - API Latency Benchmark Script.
Measures representative endpoints across warm runs to evaluate mean, p50, p95, and p99 response times.
"""

import sys
import time
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from services.api.app import app
from services.api.auth.jwt import create_access_token
from services.api.auth.models import UserRole

TENANT_1_ID = "a0000000-0000-0000-0000-000000000001"
FLEET_1_ID = "d0000000-0000-0000-0000-000000000001"
ADMIN_USER_ID = "b0000000-0000-0000-0000-000000000001"


def run_benchmark():
    from services.api.config import settings
    settings.RATE_LIMIT_ENABLED = False

    client = TestClient(app)

    token = create_access_token(
        user_id=ADMIN_USER_ID,
        tenant_id=TENANT_1_ID,
        email="admin@metrotransit.com",
        roles=[UserRole.ADMIN],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Fetch a sample VIN
    v_res = client.get("/vehicles?limit=1", headers=headers)
    sample_vin = v_res.json()["items"][0]["vin"]

    endpoints: List[Tuple[str, str, dict]] = [
        ("GET /health", "/health", {}),
        ("GET /vehicles", "/vehicles?limit=20", headers),
        (f"GET /vehicles/{sample_vin}", f"/vehicles/{sample_vin}", headers),
        (f"GET /vehicles/{sample_vin}/risk", f"/vehicles/{sample_vin}/risk", headers),
        ("GET /alerts", "/alerts?limit=20", headers),
        (f"GET /fleets/{FLEET_1_ID}/health", f"/fleets/{FLEET_1_ID}/health", headers),
    ]

    print("================================================================================")
    print("FleetGuard Pulse — API Latency Benchmark (100 Requests per Endpoint)")
    print("================================================================================")
    print(f"{'Endpoint':<35} | {'Mean (ms)':<10} | {'p50 (ms)':<10} | {'p95 (ms)':<10} | {'p99 (ms)':<10}")
    print("-" * 80)

    results = []

    for label, url, req_headers in endpoints:
        # Warmup
        for _ in range(5):
            client.get(url, headers=req_headers)

        latencies_ms = []
        for _ in range(100):
            t0 = time.perf_counter()
            res = client.get(url, headers=req_headers)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
            assert res.status_code == 200, f"Benchmark request failed with {res.status_code}: {res.text}"

        latencies_ms.sort()
        mean = sum(latencies_ms) / len(latencies_ms)
        p50 = latencies_ms[50]
        p95 = latencies_ms[95]
        p99 = latencies_ms[99]

        print(f"{label:<35} | {mean:<10.2f} | {p50:<10.2f} | {p95:<10.2f} | {p99:<10.2f}")
        results.append({
            "endpoint": label,
            "mean_ms": mean,
            "p50_ms": p50,
            "p95_ms": p95,
            "p99_ms": p99,
        })

    settings.RATE_LIMIT_ENABLED = True
    print("================================================================================")
    return results


if __name__ == "__main__":
    run_benchmark()
