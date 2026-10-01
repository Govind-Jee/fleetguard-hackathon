"""
FleetGuard Pulse - Analytics Security & Multi-Tenant Isolation Tests.
Verifies JWT authentication, RBAC authorization, strict tenant boundaries,
and input validation defenses across all /analytics API endpoints.
"""

import os
from fastapi.testclient import TestClient
import psycopg2
import pytest

from services.api.app import app
from services.api.auth.jwt import create_access_token
from services.api.auth.models import UserRole

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5433"))
PG_DB = os.getenv("POSTGRES_DB", "fleetguard")
PG_USER = os.getenv("POSTGRES_USER", "fleetguard_user")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "fleetguard_dev_password")

TENANT_1_ID = "a0000000-0000-0000-0000-000000000001"  # Metro Transit
TENANT_2_ID = "a0000000-0000-0000-0000-000000000002"  # Apex Logistics


CH_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CH_PORT = int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123"))
CH_USER = os.getenv("CLICKHOUSE_USER", "default")
CH_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "fleetguard_dev_password")
CH_DB = os.getenv("CLICKHOUSE_DB", "fleetguard_analytics")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def tenant_1_token():
    return create_access_token(
        user_id="b0000000-0000-0000-0000-000000000001",
        tenant_id=TENANT_1_ID,
        email="admin@metrotransit.com",
        roles=[UserRole.ADMIN, UserRole.DISPATCHER],
    )


@pytest.fixture(scope="module")
def tenant_2_token():
    return create_access_token(
        user_id="b0000000-0000-0000-0000-000000000002",
        tenant_id=TENANT_2_ID,
        email="dispatcher@apexlogistics.com",
        roles=[UserRole.DISPATCHER],
    )


@pytest.fixture(scope="module")
def seeded_security_telemetry():
    """Seed telemetry for Tenant 1 vehicle to prove tenant isolation against ClickHouse."""
    import clickhouse_connect
    from datetime import datetime, timezone, timedelta
    import uuid

    # Dynamically fetch a valid vehicle belonging to Tenant 1
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD
    )
    with conn.cursor() as cur:
        cur.execute("SELECT vin FROM vehicles WHERE tenant_id = %s OFFSET 100 LIMIT 1;", (TENANT_1_ID,))
        test_vin = str(cur.fetchone()[0])
    conn.close()

    ch = clickhouse_connect.get_client(
        host=CH_HOST, port=CH_PORT, username=CH_USER, password=CH_PASSWORD, database=CH_DB
    )
    row = [
        uuid.uuid4(), test_vin, datetime.now(timezone.utc) - timedelta(minutes=5), 100, "ICE", 40.71, -74.00,
        50.0, 10000.0, 0.3, [], 320.0, 90.0, 2000.0, 13.8, None, None, None, None
    ]
    cols = [
        "event_id", "vin", "timestamp", "sequence_number", "vehicle_type", "latitude", "longitude",
        "speed_kmh", "odometer_km", "vibration", "dtc_codes", "oil_pressure_kpa", "coolant_temp_c",
        "engine_rpm", "battery_voltage_v", "soc_pct", "pack_voltage_v", "motor_rpm", "cell_temp_delta_c"
    ]
    ch.insert("vehicle_telemetry", [row], column_names=cols)
    try:
        yield test_vin
    finally:
        ch.command(f"ALTER TABLE vehicle_telemetry DELETE WHERE vin = '{test_vin}'")
        ch.close()


def test_analytics_endpoints_require_authentication(client):
    """Ensure all analytics endpoints reject unauthenticated access with 401."""
    endpoints = [
        "/analytics/summary",
        "/analytics/reliability",
        "/analytics/faults",
        "/analytics/mtbf",
        "/analytics/trends",
        "/analytics/degradation",
    ]
    for ep in endpoints:
        resp = client.get(ep)
        assert resp.status_code == 401, f"Expected 401 for {ep}, got {resp.status_code}"


def test_analytics_tenant_isolation_negative_leakage(client, tenant_1_token, tenant_2_token, seeded_security_telemetry):
    """
    Negative test: Tenant 2 (Apex Logistics) must NOT receive aggregates, vehicle counts,
    or degradation rankings belonging to Tenant 1 (Metro Transit).
    """
    # 1. Tenant 1 gets positive summary
    resp1 = client.get(
        "/analytics/reliability",
        headers={"Authorization": f"Bearer {tenant_1_token}"},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["tenant_id"] == TENANT_1_ID
    assert data1["total_monitored_vehicles"] > 0

    # 2. Tenant 2 has zero vehicles in Metro Transit; must receive 0 metrics
    resp2 = client.get(
        "/analytics/reliability",
        headers={"Authorization": f"Bearer {tenant_2_token}"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["tenant_id"] == TENANT_2_ID
    assert data2["total_monitored_vehicles"] == 0
    assert data2["telemetry_event_count"] == 0
    assert data2["fault_event_count"] == 0


def test_analytics_fleet_filter_cross_tenant_rejection(client, tenant_1_token, tenant_2_token):
    """
    Negative test: Tenant 2 must NOT be allowed to filter by a fleet_id belonging to Tenant 1.
    Must return 404 ResourceNotFoundError.
    """
    # Fetch a valid fleet_id belonging to Tenant 1
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD
    )
    with conn.cursor() as cur:
        cur.execute("SELECT fleet_id FROM fleets WHERE tenant_id = %s LIMIT 1;", (TENANT_1_ID,))
        row = cur.fetchone()
        assert row is not None
        tenant_1_fleet_id = str(row[0])
    conn.close()

    # Tenant 2 tries to use Tenant 1's fleet_id
    resp = client.get(
        f"/analytics/reliability?fleet_id={tenant_1_fleet_id}",
        headers={"Authorization": f"Bearer {tenant_2_token}"},
    )
    assert resp.status_code == 404, "Cross-tenant fleet filtering must be rejected with 404"
    assert "was not found within tenant domain" in resp.json()["error"]["message"]


def test_analytics_degradation_ranking_tenant_isolation(client, tenant_2_token):
    """
    Verify Tenant 2 degradation ranking does not leak any Tenant 1 vehicles.
    """
    resp = client.get(
        "/analytics/degradation?limit=10",
        headers={"Authorization": f"Bearer {tenant_2_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == TENANT_2_ID
    assert len(data["ranked_vehicles"]) == 0
    assert data["total_evaluated"] == 0


def test_analytics_invalid_time_window_rejected(client, tenant_1_token):
    """Verify inverted time window start >= end is rejected with 422."""
    resp = client.get(
        "/analytics/reliability?start_time=2026-09-20T00:00:00Z&end_time=2026-09-10T00:00:00Z",
        headers={"Authorization": f"Bearer {tenant_1_token}"},
    )
    assert resp.status_code == 422
    assert "must be strictly before" in resp.json()["error"]["message"]


def test_analytics_excessive_time_window_rejected(client, tenant_1_token):
    """Verify time window > 90 days is rejected with 422."""
    resp = client.get(
        "/analytics/reliability?start_time=2026-01-01T00:00:00Z&end_time=2026-05-01T00:00:00Z",
        headers={"Authorization": f"Bearer {tenant_1_token}"},
    )
    assert resp.status_code == 422
    assert "exceeds maximum interactive span of 90 days" in resp.json()["error"]["message"]
