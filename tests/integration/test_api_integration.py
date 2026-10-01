"""
FleetGuard Pulse - End-to-End API Integration Tests.
Tests real interaction with PostgreSQL 16 (relational domain & pgvector),
Redis 7 hot state, ML predictor pipeline, and WebSocket push stream.
"""

import json
import pytest
from fastapi.testclient import TestClient

from services.api.app import app
from services.api.auth.jwt import create_access_token
from services.api.auth.models import UserRole

# Seed Constants
TENANT_1_ID = "a0000000-0000-0000-0000-000000000001"  # Metro Transit Authority
FLEET_1_ID = "d0000000-0000-0000-0000-000000000001"   # Express Regional Delivery
ADMIN_USER_ID = "b0000000-0000-0000-0000-000000000001"
DISPATCH_USER_ID = "b0000000-0000-0000-0000-000000000002"
TECH_USER_ID = "b0000000-0000-0000-0000-000000000003"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin_headers():
    token = create_access_token(
        user_id=ADMIN_USER_ID,
        tenant_id=TENANT_1_ID,
        email="admin@metrotransit.com",
        roles=[UserRole.ADMIN],
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def dispatcher_headers():
    token = create_access_token(
        user_id=DISPATCH_USER_ID,
        tenant_id=TENANT_1_ID,
        email="dispatch@metrotransit.com",
        roles=[UserRole.DISPATCHER],
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def technician_headers():
    token = create_access_token(
        user_id=TECH_USER_ID,
        tenant_id=TENANT_1_ID,
        email="tech@metrotransit.com",
        roles=[UserRole.TECHNICIAN],
    )
    return {"Authorization": f"Bearer {token}"}


def test_readiness_probe_all_datastores(client):
    """GET /ready must return READY and verify all connected datastores."""
    res = client.get("/ready")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "READY"
    assert data["datastores"]["postgres"] is True
    assert data["datastores"]["redis"] is True


def test_vehicles_listing_and_pagination(client, dispatcher_headers):
    """GET /vehicles must return paginated vehicle entities scoped to tenant."""
    res = client.get("/vehicles?limit=10&page=1", headers=dispatcher_headers)
    assert res.status_code == 200
    data = res.json()

    assert "items" in data
    assert "pagination" in data
    assert len(data["items"]) <= 10
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["total_count"] > 0

    first_v = data["items"][0]
    assert "vin" in first_v
    assert "fleet_id" in first_v
    assert "model" in first_v
    assert first_v["model"]["vehicle_type"] in ("ICE", "HEV", "BEV")


def test_vehicles_filtering_by_fleet_and_powertrain(client, dispatcher_headers):
    """GET /vehicles filtering by fleet_id and vehicle_type must return matching subset."""
    res = client.get(f"/vehicles?fleet_id={FLEET_1_ID}&vehicle_type=ICE&limit=5", headers=dispatcher_headers)
    assert res.status_code == 200
    data = res.json()
    for item in data["items"]:
        assert item["fleet_id"] == FLEET_1_ID
        assert item["model"]["vehicle_type"] == "ICE"


def test_vehicle_authoritative_and_hot_state_lookup(client, dispatcher_headers):
    """GET /vehicles/{vin} must separate authoritative relational metadata from transient Redis hot state."""
    # Fetch first vehicle VIN
    list_res = client.get("/vehicles?limit=1", headers=dispatcher_headers)
    test_vin = list_res.json()["items"][0]["vin"]

    res = client.get(f"/vehicles/{test_vin}", headers=dispatcher_headers)
    assert res.status_code == 200
    data = res.json()

    assert data["vin"] == test_vin
    assert "authoritative" in data
    auth = data["authoritative"]
    assert auth["vin"] == test_vin
    assert auth["tenant_id"] == TENANT_1_ID
    assert "fleet" in auth
    assert "depot" in auth
    assert "model" in auth

    # Transient state field present (dict or null if not currently publishing)
    assert "transient_state" in data


def test_vehicle_health_summary(client, dispatcher_headers):
    """GET /vehicles/{vin}/health must combine Redis operational telemetry and PostgreSQL alerts."""
    list_res = client.get("/vehicles?limit=1", headers=dispatcher_headers)
    test_vin = list_res.json()["items"][0]["vin"]

    res = client.get(f"/vehicles/{test_vin}/health", headers=dispatcher_headers)
    assert res.status_code == 200
    data = res.json()

    assert data["vin"] == test_vin
    assert data["current_health_state"] in ("NOMINAL", "WARNING", "CRITICAL")
    assert "alert_summary" in data
    assert "unacknowledged_alert_count" in data["alert_summary"]


def test_predictive_risk_scoring(client, dispatcher_headers):
    """GET /vehicles/{vin}/risk must execute verified ML predictor and return 7-day risk estimate."""
    list_res = client.get("/vehicles?limit=1", headers=dispatcher_headers)
    test_vin = list_res.json()["items"][0]["vin"]

    res = client.get(f"/vehicles/{test_vin}/risk", headers=dispatcher_headers)
    assert res.status_code == 200
    data = res.json()

    assert data["vin"] == test_vin
    assert 0.0 <= data["probability_7d"] <= 1.0
    assert data["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert isinstance(data["predicted_maintenance_required"], bool)
    assert data["decision_threshold"] > 0.0
    assert len(data["top_risk_factors"]) > 0
    assert "disclaimer" in data
    assert "estimated probability" in data["disclaimer"].lower()


def test_predictive_risk_dynamic_reaction_to_live_telemetry(client, technician_headers):
    """
    Live ML Data Path Test:
    Proves that GET /vehicles/{vin}/risk dynamically ingests live telemetry features
    from Redis hot state (vehicle:state:{vin}) and recomputes risk probability accordingly.
    """
    from services.api.db import get_redis_client
    r_client = get_redis_client()
    test_vin = "1HGCR2F83HA000001"
    state_key = f"vehicle:state:{test_vin}"
    cache_key = f"vehicle:risk:{test_vin}"

    try:
        # 1. Inject nominal telemetry into Redis
        r_client.hset(
            state_key,
            mapping={
                "speed_kmh": "50.0",
                "vibration": "0.15",
                "coolant_temp_c": "84.0",
                "oil_pressure_kpa": "340.0",
                "engine_rpm": "1400",
                "dtc_codes": "[]",
                "health_status": "NORMAL",
                "odometer_km": "45000.0",
                "sequence_number": "100",
            },
        )
        r_client.delete(cache_key)

        res_nominal = client.get(f"/vehicles/{test_vin}/risk", headers=technician_headers)
        assert res_nominal.status_code == 200
        data_nominal = res_nominal.json()
        prob_nominal = data_nominal["probability_7d"]

        # 2. Inject critical telemetry (severe vibration + overheating + critical DTCs)
        r_client.hset(
            state_key,
            mapping={
                "speed_kmh": "75.0",
                "vibration": "4.8",
                "coolant_temp_c": "119.5",
                "oil_pressure_kpa": "65.0",
                "engine_rpm": "2900",
                "dtc_codes": json.dumps(["P0217", "P0524"]),
                "health_status": "CRITICAL",
                "odometer_km": "46200.0",
                "sequence_number": "1500",
            },
        )
        r_client.delete(cache_key)

        res_critical = client.get(f"/vehicles/{test_vin}/risk", headers=technician_headers)
        assert res_critical.status_code == 200
        data_critical = res_critical.json()
        prob_critical = data_critical["probability_7d"]

        # 3. Assertions
        assert prob_critical > prob_nominal, f"Critical risk ({prob_critical}) must exceed nominal risk ({prob_nominal})"
        assert data_critical["risk_level"] in ("HIGH", "CRITICAL")
        assert data_critical["predicted_maintenance_required"] is True

        # Verify explainability factors reflect live inputs
        risk_factor_names = [f["feature_name"] for f in data_critical["top_risk_factors"]]
        assert any(feat in risk_factor_names for feat in ("vibration_mean", "coolant_temp_mean", "anomaly_count", "oil_pressure_mean"))

    finally:
        # Cleanup
        r_client.delete(cache_key)
        r_client.delete(state_key)


def test_pgvector_diagnostic_similarity_search(client, technician_headers):
    """GET /diagnostics/similar must execute pgvector cosine distance search against 16-D signatures."""
    # Test vector: Engine overheat signature from migration 003 seed
    query_vector = "0.64,2.05,0.59,0.86,3.75,0.49,-1.15,0.44,0.00,0.00,0.00,0.00,0.54,0.88,1.00,0.00"
    res = client.get(f"/diagnostics/similar?vector={query_vector}&limit=3", headers=technician_headers)
    assert res.status_code == 200
    data = res.json()

    assert data["query_vector_dimension"] == 16
    assert len(data["matches"]) >= 1
    top_match = data["matches"][0]
    assert top_match["fault_type"] == "ENGINE_OVERHEAT"
    assert top_match["cosine_distance"] < 0.05
    assert top_match["similarity_score"] > 0.95


def test_fleets_listing_and_health_aggregation(client, dispatcher_headers):
    """GET /fleets and /fleets/{fleet_id}/health must compute consolidated aggregates without N+1 overhead."""
    res_list = client.get("/fleets", headers=dispatcher_headers)
    assert res_list.status_code == 200
    fleets = res_list.json()["items"]
    assert len(fleets) >= 1

    fleet_id = fleets[0]["fleet_id"]
    res_health = client.get(f"/fleets/{fleet_id}/health", headers=dispatcher_headers)
    assert res_health.status_code == 200
    health = res_health.json()

    assert health["fleet_id"] == fleet_id
    assert health["total_vehicles"] > 0
    assert "vehicles_by_status" in health
    assert "vehicles_by_type" in health
    assert "health_status_counts" in health
    assert "work_orders_summary" in health


def test_alerts_listing_and_detail(client, dispatcher_headers):
    """GET /alerts and /alerts/{alert_id} must retrieve durable alerts."""
    res = client.get("/alerts?limit=5", headers=dispatcher_headers)
    assert res.status_code == 200
    data = res.json()
    assert "items" in data

    if len(data["items"]) > 0:
        alert_id = data["items"][0]["alert_id"]
        res_single = client.get(f"/alerts/{alert_id}", headers=dispatcher_headers)
        assert res_single.status_code == 200
        assert res_single.json()["alert_id"] == alert_id


def test_work_order_creation_success(client, dispatcher_headers):
    """POST /maintenance/work-orders must create 3NF work order record."""
    list_res = client.get("/vehicles?limit=1", headers=dispatcher_headers)
    test_vin = list_res.json()["items"][0]["vin"]

    payload = {
        "vin": test_vin,
        "type_id": 1,
        "priority": "HIGH",
        "scheduled_at": "2026-10-05T09:00:00Z",
        "assigned_technician_id": TECH_USER_ID,
    }
    res = client.post("/maintenance/work-orders", json=payload, headers=dispatcher_headers)
    assert res.status_code == 201
    data = res.json()

    assert data["vin"] == test_vin
    assert data["tenant_id"] == TENANT_1_ID
    assert data["priority"] == "HIGH"
    assert data["status"] == "PENDING"
    assert "work_order_id" in data


def test_historical_analytics_summary(client, dispatcher_headers):
    """GET /analytics/summary must return high-level fleet operational metrics."""
    res = client.get("/analytics/summary", headers=dispatcher_headers)
    assert res.status_code == 200
    data = res.json()

    assert data["tenant_id"] == TENANT_1_ID
    assert data["total_monitored_vehicles"] > 0
    assert data["active_fleets_count"] > 0
    assert "powertrain_breakdown" in data
    assert data["average_fleet_odometer_km"] >= 0.0


def test_websocket_alerts_stream_smoke(client):
    """WS /ws/alerts must accept connections and respond to PING heartbeats."""
    token = create_access_token(
        user_id=ADMIN_USER_ID,
        tenant_id=TENANT_1_ID,
        email="admin@metrotransit.com",
        roles=[UserRole.ADMIN],
    )
    with client.websocket_connect(f"/ws/alerts?token={token}") as ws:
        init_frame = ws.receive_json()
        assert init_frame["type"] == "CONNECTION_ESTABLISHED"
        assert init_frame["tenant_id"] == TENANT_1_ID

        ws.send_text(json.dumps({"type": "PING"}))
        pong_frame = ws.receive_json()
        assert pong_frame["type"] == "PONG"


def test_websocket_functional_alert_delivery(client):
    """
    WebSocket functional alert-delivery integration test:
    1. Connect client to /ws/alerts with Tenant 1 JWT token.
    2. Dispatch a known critical alert.
    3. Verify connected WebSocket receives the alert frame.
    4. Verify alert_id, vin, severity, and fault_type match.
    5. Verify duplicate alert is suppressed by idempotency guard.
    """
    import asyncio
    from services.api.db import get_redis_client
    from services.api.services.alert_dispatcher import alert_dispatcher

    token = create_access_token(
        user_id=ADMIN_USER_ID,
        tenant_id=TENANT_1_ID,
        email="admin@metrotransit.com",
        roles=[UserRole.ADMIN],
    )
    r_client = get_redis_client()

    with client.websocket_connect(f"/ws/alerts?token={token}") as ws:
        init_frame = ws.receive_json()
        assert init_frame["type"] == "CONNECTION_ESTABLISHED"
        assert init_frame["tenant_id"] == TENANT_1_ID

        alert_id = "test-live-alert-001"
        test_alert = {
            "alert_id": alert_id,
            "vin": "1FDXE4FN8PK123456",
            "tenant_id": TENANT_1_ID,
            "severity": "CRITICAL",
            "fault_type": "ENGINE_OVERHEAT",
            "message": "Engine coolant temperature critical (108.5C)",
            "sequence_number": 1045,
            "telemetry_event_id": "event-uuid-8888",
        }

        # Clear any prior dedup key for test idempotency
        r_client.delete(f"alert:dispatched:{alert_id}")

        # Dispatch alert asynchronously
        loop = asyncio.get_event_loop()
        dispatched = loop.run_until_complete(
            alert_dispatcher.dispatch_alert(test_alert, redis_client=r_client)
        )
        assert dispatched is True, "First alert dispatch must succeed"

        # Receive frame over WebSocket
        received_frame = ws.receive_json()
        assert received_frame["type"] == "CRITICAL_ALERT"
        alert_payload = received_frame["alert"]
        assert alert_payload["alert_id"] == alert_id
        assert alert_payload["vin"] == "1FDXE4FN8PK123456"
        assert alert_payload["severity"] == "CRITICAL"
        assert alert_payload["fault_type"] == "ENGINE_OVERHEAT"

        # Attempt to dispatch the exact duplicate alert
        dispatched_duplicate = loop.run_until_complete(
            alert_dispatcher.dispatch_alert(test_alert, redis_client=r_client)
        )
        assert dispatched_duplicate is False, "Duplicate alert must be suppressed by idempotency guard"
