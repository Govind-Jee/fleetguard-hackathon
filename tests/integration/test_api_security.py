"""
FleetGuard Pulse - API Security, Authentication, RBAC, and Multi-Tenant Isolation Tests.
Verifies cryptographic JWT verification, expired/tampered token rejection,
role-based permissions, cross-tenant isolation guarantees, and rate limiting.
"""

from datetime import timedelta
import pytest
from fastapi.testclient import TestClient

from services.api.app import app
from services.api.auth.jwt import create_access_token
from services.api.auth.models import UserRole
from services.api.config import settings

# Test Tenant Identifiers from Migration 003 Seed Data
TENANT_1_ID = "a0000000-0000-0000-0000-000000000001"  # Metro Transit Authority
TENANT_2_ID = "a0000000-0000-0000-0000-000000000002"  # Apex Logistics Corp


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_unauthenticated_request_rejected(client):
    """Endpoints requiring authentication must return 401 UNAUTHORIZED when no token is passed."""
    res = client.get("/vehicles")
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "UNAUTHORIZED"


def test_expired_jwt_rejected(client):
    """Expired JWT token must be rejected with 401 UNAUTHORIZED."""
    expired_token = create_access_token(
        user_id="test-expired-user",
        tenant_id=TENANT_1_ID,
        email="expired@metrotransit.com",
        roles=[UserRole.ADMIN],
        expires_delta=timedelta(seconds=-30),  # Expired in past
    )
    headers = {"Authorization": f"Bearer {expired_token}"}
    res = client.get("/vehicles", headers=headers)
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "UNAUTHORIZED"
    assert "expired" in data["error"]["message"].lower()


def test_wrong_audience_jwt_rejected(client):
    """Token with invalid 'aud' claim must be rejected with 401 UNAUTHORIZED."""
    bad_aud_token = create_access_token(
        user_id="test-aud-user",
        tenant_id=TENANT_1_ID,
        email="aud@metrotransit.com",
        roles=[UserRole.ADMIN],
        audience="wrong-client-app-audience",
    )
    headers = {"Authorization": f"Bearer {bad_aud_token}"}
    res = client.get("/vehicles", headers=headers)
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "UNAUTHORIZED"


def test_wrong_issuer_jwt_rejected(client):
    """Token with invalid 'iss' claim must be rejected with 401 UNAUTHORIZED."""
    bad_iss_token = create_access_token(
        user_id="test-iss-user",
        tenant_id=TENANT_1_ID,
        email="iss@metrotransit.com",
        roles=[UserRole.ADMIN],
        issuer="https://malicious-idp.com/auth",
    )
    headers = {"Authorization": f"Bearer {bad_iss_token}"}
    res = client.get("/vehicles", headers=headers)
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "UNAUTHORIZED"


def test_tampered_signature_jwt_rejected(client):
    """Token signed with wrong cryptographic key must be rejected with 401 UNAUTHORIZED."""
    tampered_token = create_access_token(
        user_id="test-tamper-user",
        tenant_id=TENANT_1_ID,
        email="tamper@metrotransit.com",
        roles=[UserRole.ADMIN],
        secret_key="completely-wrong-untrusted-key-32b-min!",
    )
    headers = {"Authorization": f"Bearer {tampered_token}"}
    res = client.get("/vehicles", headers=headers)
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "UNAUTHORIZED"


def test_rbac_technician_forbidden_from_analytics(client):
    """TECHNICIAN role accessing /analytics/summary (requires ADMIN or DISPATCHER) must be rejected with 403 FORBIDDEN."""
    tech_token = create_access_token(
        user_id="tech-user-1",
        tenant_id=TENANT_1_ID,
        email="tech@metrotransit.com",
        roles=[UserRole.TECHNICIAN],
    )
    headers = {"Authorization": f"Bearer {tech_token}"}
    res = client.get("/analytics/summary", headers=headers)
    assert res.status_code == 403
    data = res.json()
    assert data["error"]["code"] == "FORBIDDEN_INSUFFICIENT_ROLE"


def test_rbac_dispatcher_forbidden_from_vector_diagnostics(client):
    """DISPATCHER role accessing /diagnostics/similar (requires TECHNICIAN or ADMIN) must be rejected with 403 FORBIDDEN."""
    dispatch_token = create_access_token(
        user_id="dispatch-user-1",
        tenant_id=TENANT_1_ID,
        email="dispatch@metrotransit.com",
        roles=[UserRole.DISPATCHER],
    )
    headers = {"Authorization": f"Bearer {dispatch_token}"}
    query_vector = "0.64,2.05,0.59,0.86,3.75,0.49,-1.15,0.44,0.00,0.00,0.00,0.00,0.54,0.88,1.00,0.00"
    res = client.get(f"/diagnostics/similar?vector={query_vector}", headers=headers)
    assert res.status_code == 403
    data = res.json()
    assert data["error"]["code"] == "FORBIDDEN_INSUFFICIENT_ROLE"


def test_tenant_isolation_vehicle_lookup(client):
    """Tenant 2 user attempting to query a Tenant 1 vehicle must receive 404 NOT FOUND (never data from Tenant 1)."""
    # 1. Tenant 1 fetches one of its vehicles
    t1_token = create_access_token(
        user_id="t1-admin",
        tenant_id=TENANT_1_ID,
        email="admin@metrotransit.com",
        roles=[UserRole.ADMIN],
    )
    res_t1 = client.get("/vehicles?limit=1", headers={"Authorization": f"Bearer {t1_token}"})
    assert res_t1.status_code == 200
    t1_vin = res_t1.json()["items"][0]["vin"]

    # 2. Tenant 2 attempts to fetch Tenant 1's VIN
    t2_token = create_access_token(
        user_id="t2-admin",
        tenant_id=TENANT_2_ID,  # Apex Logistics Corp
        email="admin@apexlogistics.com",
        roles=[UserRole.ADMIN],
    )
    res_t2 = client.get(f"/vehicles/{t1_vin}", headers={"Authorization": f"Bearer {t2_token}"})
    assert res_t2.status_code == 404
    data = res_t2.json()
    assert data["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_tenant_isolation_work_order_creation(client):
    """Tenant 2 user attempting to create a work order for a Tenant 1 vehicle must receive 404 NOT FOUND."""
    # 1. Get Tenant 1 VIN
    t1_token = create_access_token(
        user_id="t1-admin",
        tenant_id=TENANT_1_ID,
        email="admin@metrotransit.com",
        roles=[UserRole.ADMIN],
    )
    res_t1 = client.get("/vehicles?limit=1", headers={"Authorization": f"Bearer {t1_token}"})
    t1_vin = res_t1.json()["items"][0]["vin"]

    # 2. Tenant 2 tries to create work order targeting Tenant 1 vehicle
    t2_token = create_access_token(
        user_id="t2-admin",
        tenant_id=TENANT_2_ID,
        email="admin@apexlogistics.com",
        roles=[UserRole.ADMIN],
    )
    payload = {
        "vin": t1_vin,
        "type_id": 1,
        "priority": "HIGH",
    }
    res_t2 = client.post("/maintenance/work-orders", json=payload, headers={"Authorization": f"Bearer {t2_token}"})
    assert res_t2.status_code == 404
    assert res_t2.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_rate_limiter_throttling_triggers_429(client):
    """Exceeding configured rate limit quota must return HTTP 429 with Retry-After header."""
    # Create unique token for isolated tenant rate limit test
    unique_tenant = "99999999-0000-0000-0000-000000000099"
    token = create_access_token(
        user_id="rate-limit-test-user",
        tenant_id=unique_tenant,
        email="rl@test.com",
        roles=[UserRole.ADMIN],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Temporarily set lower limit in memory for fast testing
    original_limit = settings.RATE_LIMIT_REQUESTS_PER_MINUTE
    settings.RATE_LIMIT_REQUESTS_PER_MINUTE = 5

    try:
        status_codes = []
        for _ in range(7):
            res = client.get("/vehicles?limit=1", headers=headers)
            status_codes.append(res.status_code)

        assert 429 in status_codes
        idx = status_codes.index(429)
        # Verify 429 response attributes
        res_429 = client.get("/vehicles?limit=1", headers=headers)
        assert res_429.status_code == 429
        data = res_429.json()
        assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "Retry-After" in res_429.headers
    finally:
        settings.RATE_LIMIT_REQUESTS_PER_MINUTE = original_limit


def test_production_auth_fails_safely_on_misconfiguration(client):
    """
    When AUTH_DEV_MODE is False and no RS256 public key or non-dev secret is set,
    the auth system must fail safely with 401 UNAUTHORIZED rather than silently allowing insecure dev secrets.
    """
    token = create_access_token(
        user_id="prod-test-user",
        tenant_id=TENANT_1_ID,
        email="prod@metrotransit.com",
        roles=[UserRole.ADMIN],
    )
    headers = {"Authorization": f"Bearer {token}"}

    original_dev_mode = settings.AUTH_DEV_MODE
    original_public_key = settings.JWT_PUBLIC_KEY
    original_secret = settings.JWT_SECRET_KEY

    try:
        settings.AUTH_DEV_MODE = False
        settings.JWT_PUBLIC_KEY = ""
        settings.JWT_SECRET_KEY = "fleetguard-dev-super-secret-jwt-key-32b-min!!"

        res = client.get("/vehicles", headers=headers)
        assert res.status_code == 401
        data = res.json()
        assert data["error"]["code"] == "UNAUTHORIZED"
        assert "misconfigured" in data["error"]["message"].lower() or "required" in data["error"]["message"].lower()
    finally:
        settings.AUTH_DEV_MODE = original_dev_mode
        settings.JWT_PUBLIC_KEY = original_public_key
        settings.JWT_SECRET_KEY = original_secret


def test_tenant_isolation_alerts_lookup(client):
    """Tenant 2 user querying a Tenant 1 alert must receive 404 NOT FOUND."""
    t1_alert_id = "90000000-0000-0000-0000-000000000001"
    t2_token = create_access_token(
        user_id="t2-dispatcher",
        tenant_id=TENANT_2_ID,
        email="dispatcher@apexlogistics.com",
        roles=[UserRole.DISPATCHER],
    )
    res = client.get(f"/alerts/{t1_alert_id}", headers={"Authorization": f"Bearer {t2_token}"})
    assert res.status_code == 404
    data = res.json()
    assert data["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_tenant_isolation_fleet_health(client):
    """Tenant 2 user querying health of Tenant 1 fleet must receive 404 NOT FOUND."""
    t1_fleet_id = "d0000000-0000-0000-0000-000000000001"
    t2_token = create_access_token(
        user_id="t2-dispatcher",
        tenant_id=TENANT_2_ID,
        email="dispatcher@apexlogistics.com",
        roles=[UserRole.DISPATCHER],
    )
    res = client.get(f"/fleets/{t1_fleet_id}/health", headers={"Authorization": f"Bearer {t2_token}"})
    assert res.status_code == 404
    data = res.json()
    assert data["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_tenant_isolation_analytics_summary(client):
    """Tenant 2 analytics summary must only reflect Tenant 2 assets (0 vehicles in seed) and never Tenant 1 data."""
    t2_token = create_access_token(
        user_id="t2-admin",
        tenant_id=TENANT_2_ID,
        email="admin@apexlogistics.com",
        roles=[UserRole.ADMIN],
    )
    res = client.get("/analytics/summary", headers={"Authorization": f"Bearer {t2_token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["tenant_id"] == TENANT_2_ID
    assert data["total_monitored_vehicles"] == 0
    assert data["active_fleets_count"] == 0
    assert data["average_fleet_odometer_km"] == 0.0

