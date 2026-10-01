"""
FleetGuard Pulse - Real-Time Alert WebSocket Router.
Exposes live operational alert notifications to connected browser dashboard clients.
Scoped strictly by tenant boundary. Best-effort delivery.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from services.api.auth.jwt import verify_jwt_token
from services.api.auth.models import AuthenticatedUser
from services.api.metrics import api_metrics

logger = logging.getLogger("fleetguard.api.ws")

router = APIRouter(tags=["WebSockets"])


class AlertConnectionManager:
    """Manages active WebSocket client connections grouped by tenant_id."""

    def __init__(self):
        # tenant_id -> List[WebSocket]
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, tenant_id: str) -> None:
        await websocket.accept()
        async with self._lock:
            if tenant_id not in self.active_connections:
                self.active_connections[tenant_id] = []
            self.active_connections[tenant_id].append(websocket)
            api_metrics.inc_ws_connections()
        logger.info("WebSocket connected for tenant %s. Active clients: %d", tenant_id, len(self.active_connections[tenant_id]))

    async def disconnect(self, websocket: WebSocket, tenant_id: str) -> None:
        async with self._lock:
            if tenant_id in self.active_connections:
                if websocket in self.active_connections[tenant_id]:
                    self.active_connections[tenant_id].remove(websocket)
                if not self.active_connections[tenant_id]:
                    del self.active_connections[tenant_id]
            api_metrics.dec_ws_connections()
        logger.info("WebSocket disconnected for tenant %s", tenant_id)

    async def broadcast_to_tenant(self, tenant_id: str, message: dict) -> None:
        """Send message to all connected clients of a specific tenant."""
        async with self._lock:
            clients = list(self.active_connections.get(tenant_id, []))

        for client in clients:
            try:
                await client.send_json(message)
            except Exception as e:
                logger.warning("Error sending WebSocket message to client in tenant %s: %s", tenant_id, e)

    def active_count_for_tenant(self, tenant_id: str) -> int:
        return len(self.active_connections.get(tenant_id, []))


ws_manager = AlertConnectionManager()


@router.websocket("/ws/alerts")
async def websocket_alerts_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None, description="Bearer JWT access token for tenant authentication"),
):
    """
    Real-time push channel for critical fleet alerts.
    Authenticates via query param token, scopes broadcasts to tenant,
    and supports bidirectional heartbeat ping/pong.
    """
    # 1. Authenticate connection
    user: Optional[AuthenticatedUser] = None
    if token:
        try:
            user = verify_jwt_token(token)
        except Exception as e:
            logger.warning("WebSocket authentication failed: %s", e)
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid authentication token")
            return
    else:
        # Development fallback tenant if auth is disabled or not provided in dev mode
        from services.api.config import settings
        if settings.AUTH_DEV_MODE:
            # Default to seed tenant 1 for smoke tests
            tenant_id = "a0000000-0000-0000-0000-000000000001"
            user = AuthenticatedUser(
                user_id="dev-ws-user",
                tenant_id=tenant_id,
                email="dev.ws@metrotransit.com",
            )
        else:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication token required")
            return

    tenant_id = user.tenant_id
    await ws_manager.connect(websocket, tenant_id)

    try:
        # Send initial connection acknowledgment
        await websocket.send_json({
            "type": "CONNECTION_ESTABLISHED",
            "message": "Connected to FleetGuard Pulse real-time alert stream",
            "tenant_id": tenant_id,
        })

        # Keep connection open and process incoming control frames (e.g., ping/pong)
        while True:
            raw_text = await websocket.receive_text()
            try:
                data = json.loads(raw_text)
                msg_type = data.get("type", "").upper()
                if msg_type == "PING":
                    await websocket.send_json({"type": "PONG"})
                elif msg_type == "SUBSCRIBE":
                    await websocket.send_json({"type": "ACK_SUBSCRIBE", "topic": "alerts"})
                else:
                    await websocket.send_json({"type": "ACK", "received": msg_type})
            except json.JSONDecodeError:
                await websocket.send_json({"type": "ERROR", "message": "Malformed JSON frame"})
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, tenant_id)
    except Exception as e:
        logger.error("WebSocket unhandled exception: %s", e)
        await ws_manager.disconnect(websocket, tenant_id)


@router.post("/ws/broadcast")
async def broadcast_alert_endpoint(alert_payload: dict):
    """
    Broadcasts a critical alert frame directly to active WebSocket connections.
    Used by streaming pipeline workers and acceptance test injectors.
    """
    inner_alert = alert_payload.get("alert", alert_payload)
    tenant_id = (
        alert_payload.get("tenant_id")
        or inner_alert.get("tenant_id")
        or "a0000000-0000-0000-0000-000000000001"
    )

    if alert_payload.get("type") == "CRITICAL_ALERT":
        frame = alert_payload
    else:
        frame = {
            "type": "CRITICAL_ALERT",
            "alert": inner_alert,
        }

    await ws_manager.broadcast_to_tenant(tenant_id, frame)
    return {
        "status": "BROADCASTED",
        "tenant_id": tenant_id,
        "active_clients": ws_manager.active_count_for_tenant(tenant_id),
    }

