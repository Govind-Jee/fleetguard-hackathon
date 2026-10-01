"""
FleetGuard Pulse - API Service Contract Verification Suite.
Validates runtime HTTP responses against the published OpenAPI 3.1 contract specification.
Verifies response schemas, required properties, types, enum bounds, and contract invariants.
"""

import pytest
from fastapi.testclient import TestClient

from services.api.app import app
from services.api.auth.jwt import create_access_token
from services.api.auth.models import UserRole

TENANT_1_ID = "a0000000-0000-0000-0000-000000000001"
ADMIN_USER_ID = "b0000000-0000-0000-0000-000000000001"
TECH_USER_ID = "b0000000-0000-0000-0000-000000000003"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers():
    token = create_access_token(
        user_id=ADMIN_USER_ID,
        tenant_id=TENANT_1_ID,
        email="admin@metrotransit.com",
        roles=[UserRole.ADMIN, UserRole.TECHNICIAN, UserRole.DISPATCHER],
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def openapi_spec():
    return app.openapi()


def test_openapi_contract_schema_definitions(openapi_spec):
    """Verify that OpenAPI specification declares canonical contract models with required properties."""
    schemas = openapi_spec.get("components", {}).get("schemas", {})

    # Check key models exist
    required_schemas = [
        "VehicleSummary",
        "VehicleListResponse",
        "VehicleRiskResponse",
        "RiskFactorExplanation",
        "AlertSummary",
        "AlertListResponse",
        "DiagnosticSimilarityResponse",
        "DiagnosticSignatureMatch",
        "WorkOrderCreateRequest",
        "WorkOrderResponse",
    ]
    for s in required_schemas:
        assert s in schemas, f"OpenAPI contract missing schema: {s}"

    # Contract Invariant: VehicleRiskResponse required fields
    risk_props = schemas["VehicleRiskResponse"]["properties"]
    assert "probability_7d" in risk_props
    assert "predicted_maintenance_required" in risk_props
    assert "risk_level" in risk_props
    assert "top_risk_factors" in risk_props
    assert "protective_factors" in risk_props


def test_get_vehicles_contract_invariants(client, auth_headers):
    """Contract Test: GET /vehicles must satisfy schema structure and pagination invariants."""
    res = client.get("/vehicles?limit=5&page=1", headers=auth_headers)
    assert res.status_code == 200
    assert "application/json" in res.headers["content-type"]

    body = res.json()
    assert isinstance(body["items"], list)
    assert isinstance(body["pagination"], dict)

    pag = body["pagination"]
    assert pag["page"] == 1
    assert pag["limit"] == 5
    assert isinstance(pag["total_count"], int)
    assert isinstance(pag["total_pages"], int)

    for item in body["items"]:
        # Verify VehicleSummary contract
        assert len(item["vin"]) == 17
        assert item["status"] in ("ACTIVE", "MAINTENANCE", "DECOMMISSIONED", "INACTIVE")
        assert isinstance(item["manufacture_year"], int)
        assert isinstance(item["model"], dict)
        assert item["model"]["vehicle_type"] in ("ICE", "HEV", "BEV")


def test_get_vehicle_risk_contract_invariants(client, auth_headers):
    """Contract Test: GET /vehicles/{vin}/risk must return calibrated probability, factor rankings, and disclaimer."""
    # Fetch a valid vehicle VIN
    list_res = client.get("/vehicles?limit=1", headers=auth_headers)
    vin = list_res.json()["items"][0]["vin"]

    res = client.get(f"/vehicles/{vin}/risk", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()

    # Validate exact contract properties
    assert body["vin"] == vin
    assert isinstance(body["probability_7d"], float)
    assert 0.0 <= body["probability_7d"] <= 1.0
    assert isinstance(body["predicted_maintenance_required"], bool)
    assert body["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert isinstance(body["decision_threshold"], float)
    assert isinstance(body["top_risk_factors"], list)
    assert isinstance(body["protective_factors"], list)
    assert isinstance(body["model_version"], str)
    assert isinstance(body["disclaimer"], str)

    # Validate factor explanation contract
    for f in body["top_risk_factors"] + body["protective_factors"]:
        assert isinstance(f["feature_name"], str)
        assert isinstance(f["standardized_value"], float)
        assert isinstance(f["coefficient"], float)
        assert isinstance(f["contribution"], float)
        assert f["direction"] in ("INCREASES_RISK", "REDUCES_RISK")


def test_get_alerts_contract_invariants(client, auth_headers):
    """Contract Test: GET /alerts must return alert items conforming to AlertSummary contract."""
    res = client.get("/alerts?limit=5", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()

    assert isinstance(body["items"], list)
    assert isinstance(body["pagination"], dict)

    for a in body["items"]:
        assert isinstance(a["alert_id"], str)
        assert isinstance(a["vin"], str)
        assert a["severity"] in ("WARNING", "CRITICAL")
        assert isinstance(a["fault_type"], str)
        assert isinstance(a["message"], str)
        assert isinstance(a["sequence_number"], int)
        assert isinstance(a["is_acknowledged"], bool)
        assert isinstance(a["created_at"], str)


def test_get_diagnostics_similar_contract_invariants(client, auth_headers):
    """Contract Test: GET /diagnostics/similar must return 16-D matches with distance and similarity scores."""
    vec = "0.64,2.05,0.59,0.86,3.75,0.49,-1.15,0.44,0.00,0.00,0.00,0.00,0.54,0.88,1.00,0.00"
    res = client.get(f"/diagnostics/similar?vector={vec}&limit=3", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()

    assert body["query_vector_dimension"] == 16
    assert isinstance(body["matches"], list)
    assert len(body["matches"]) <= 3

    for m in body["matches"]:
        assert isinstance(m["signature_id"], str)
        assert isinstance(m["fault_type"], str)
        assert m["vehicle_type"] in ("ICE", "HEV", "BEV")
        assert isinstance(m["cosine_distance"], float)
        assert m["cosine_distance"] >= 0.0
        assert isinstance(m["similarity_score"], float)
        assert 0.0 <= m["similarity_score"] <= 1.0


def test_post_work_orders_contract_invariants(client, auth_headers):
    """Contract Test: POST /maintenance/work-orders must enforce request constraints and return WorkOrderResponse."""
    list_res = client.get("/vehicles?limit=1", headers=auth_headers)
    vin = list_res.json()["items"][0]["vin"]

    valid_payload = {
        "vin": vin,
        "type_id": 1,
        "priority": "HIGH",
        "scheduled_at": "2026-10-06T08:00:00Z",
    }
    res = client.post("/maintenance/work-orders", json=valid_payload, headers=auth_headers)
    assert res.status_code == 201
    body = res.json()

    assert isinstance(body["work_order_id"], str)
    assert body["tenant_id"] == TENANT_1_ID
    assert body["vin"] == vin
    assert body["type_id"] == 1
    assert body["priority"] == "HIGH"
    assert body["status"] == "PENDING"
    assert isinstance(body["created_at"], str)


def test_post_work_orders_request_contract_violation_rejected(client, auth_headers):
    """Contract Test: POST /maintenance/work-orders with invalid enum priority must return HTTP 422."""
    list_res = client.get("/vehicles?limit=1", headers=auth_headers)
    vin = list_res.json()["items"][0]["vin"]

    invalid_payload = {
        "vin": vin,
        "type_id": 1,
        "priority": "ULTRA_URGENT_INVALID_PRIORITY",
    }
    res = client.post("/maintenance/work-orders", json=invalid_payload, headers=auth_headers)
    assert res.status_code == 422
    body = res.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "validation_errors" in body["error"]["details"]
