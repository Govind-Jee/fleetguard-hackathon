"""
FleetGuard Pulse - Prometheus Metrics Exposition Router.
"""

from fastapi import APIRouter, Response
from services.api.metrics import api_metrics

router = APIRouter(tags=["Observability"])


@router.get(
    "/metrics",
    summary="Prometheus Metrics",
    description="Exposes application telemetry, HTTP latencies, active WebSockets, and ML inferences in standard Prometheus exposition format.",
)
async def get_metrics():
    content = api_metrics.export_prometheus_text()
    return Response(
        content=content,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
