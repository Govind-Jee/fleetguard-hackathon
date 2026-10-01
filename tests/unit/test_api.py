"""
FleetGuard Pulse - Unit Tests for API Layer.
Validates application initialization, OpenAPI specification, public health probes,
Prometheus metrics exposition, defensive security headers, and structured error schemas.
"""

import pytest
from fastapi.testclient import TestClient

from services.api.app import app
from services.api.metrics import api_metrics


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_liveness_probe(client):
    """GET /health must return HTTP 200 with HEALTHY status without authentication."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert data["service"] == "fleetguard-pulse-api"
    assert "timestamp" in data


def test_openapi_schema_integrity(client):
    """OpenAPI schema must be valid and expose all documented domain paths."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["openapi"].startswith("3.")
    assert schema["info"]["title"] == "FleetGuard Pulse API"

    paths = schema["paths"]
    expected_endpoints = [
        "/health",
        "/ready",
        "/metrics",
        "/vehicles",
        "/vehicles/{vin}",
        "/vehicles/{vin}/health",
        "/vehicles/{vin}/risk",
        "/alerts",
        "/alerts/{alert_id}",
        "/fleets",
        "/fleets/{fleet_id}/health",
        "/diagnostics/similar",
        "/maintenance/work-orders",
        "/analytics/summary",
    ]
    for ep in expected_endpoints:
        assert ep in paths, f"Expected endpoint {ep} missing from OpenAPI specification"


def test_security_headers_present(client):
    """Every HTTP response must contain defensive security headers."""
    response = client.get("/health")
    assert response.status_code == 200
    headers = response.headers

    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in headers
    assert "X-Request-ID" in headers


def test_prometheus_metrics_exposition(client):
    """GET /metrics must return standard Prometheus text format with registered counters."""
    # Trigger a request to ensure counters are incremented
    client.get("/health")

    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")

    body = response.text
    assert "# HELP fleetguard_http_requests_total" in body
    assert "# TYPE fleetguard_http_requests_total counter" in body
    assert "# HELP fleetguard_active_ws_connections" in body
    assert "# TYPE fleetguard_active_ws_connections gauge" in body
    assert "# HELP fleetguard_ml_predictions_total" in body
    assert "fleetguard_http_requests_total" in body


def test_structured_404_error_schema(client):
    """Unmapped routes must return structured JSON error conforming to canonical schema."""
    response = client.get("/non-existent-route-for-testing")
    assert response.status_code == 404
    data = response.json()

    assert "error" in data
    assert data["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert "message" in data["error"]
    assert "request_id" in data
