"""
FleetGuard Pulse - Real-Time Alert Dispatcher for WebSockets.
Subscribes to or dispatches high-priority alerts to connected dashboard clients.
Enforces multi-tenant scoping and idempotent duplicate suppression.
"""

import json
import logging
import time
from typing import Any, Dict, Optional, Set
import psycopg2
import redis

from services.api.routers.ws import ws_manager

logger = logging.getLogger("fleetguard.api.services.alert_dispatcher")


class AlertDispatcher:
    """Dispatches alerts to active tenant WebSocket connections with deduplication."""

    def __init__(self, dedup_ttl_seconds: int = 120):
        self.dedup_ttl_seconds = dedup_ttl_seconds
        # In-memory fallback dedup cache: alert_id -> expire_timestamp
        self._local_dedup_cache: Dict[str, float] = {}

    def is_duplicate(self, alert_id: str, redis_client: Optional[redis.Redis] = None) -> bool:
        """
        Check if alert has already been dispatched.
        Uses Redis atomic key if available, else in-memory cache.
        """
        now = time.time()

        # Clean expired in-memory keys
        expired_keys = [k for k, exp in self._local_dedup_cache.items() if exp < now]
        for k in expired_keys:
            del self._local_dedup_cache[k]

        if redis_client:
            try:
                dedup_key = f"alert:dispatched:{alert_id}"
                # SETNX returns True if key was set (i.e., not duplicate)
                was_set = redis_client.set(dedup_key, "1", ex=self.dedup_ttl_seconds, nx=True)
                return not was_set
            except Exception as e:
                logger.warning("Redis dedup check error, falling back to in-memory: %s", e)

        # In-memory fallback
        if alert_id in self._local_dedup_cache:
            return True

        self._local_dedup_cache[alert_id] = now + self.dedup_ttl_seconds
        return False

    async def dispatch_alert(
        self,
        alert_data: Dict[str, Any],
        conn: Optional[psycopg2.extensions.connection] = None,
        redis_client: Optional[redis.Redis] = None,
    ) -> bool:
        """
        Dispatch a critical alert to connected WebSocket clients for the vehicle's tenant.

        Returns:
            True if dispatched to WebSocket clients.
            False if suppressed as a duplicate or target tenant not found.
        """
        alert_id = str(alert_data.get("alert_id", ""))
        vin = alert_data.get("vin", "")

        if not alert_id or not vin:
            logger.warning("Malformed alert payload missing alert_id or vin: %s", alert_data)
            return False

        # 1. Idempotency & Deduplication Check
        if self.is_duplicate(alert_id, redis_client):
            logger.info("Duplicate alert %s for VIN %s suppressed by idempotency guard", alert_id, vin)
            return False

        # 2. Resolve Tenant ID
        tenant_id = alert_data.get("tenant_id")
        if not tenant_id and conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT tenant_id FROM vehicles WHERE vin = %s;", (vin,))
                    row = cur.fetchone()
                    if row:
                        tenant_id = str(row[0])
            except Exception as e:
                logger.error("Failed to query tenant for VIN %s: %s", vin, e)

        if not tenant_id:
            logger.warning("Cannot dispatch alert %s: unable to resolve tenant for VIN %s", alert_id, vin)
            return False

        # 3. Format message frame
        message_frame = {
            "type": "CRITICAL_ALERT",
            "alert": {
                "alert_id": alert_id,
                "vin": vin,
                "tenant_id": tenant_id,
                "severity": alert_data.get("severity", "CRITICAL"),
                "fault_type": alert_data.get("fault_type", "UNKNOWN_FAULT"),
                "message": alert_data.get("message", ""),
                "sequence_number": alert_data.get("sequence_number", 0),
                "timestamp": alert_data.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                "telemetry_event_id": alert_data.get("telemetry_event_id", ""),
            },
        }

        # 4. Broadcast to connected WebSocket clients for this tenant
        await ws_manager.broadcast_to_tenant(tenant_id, message_frame)

        # 5. Also publish to Redis Pub/Sub channel for multi-worker support
        if redis_client:
            try:
                redis_client.publish(f"fleetguard:alerts:{tenant_id}", json.dumps(message_frame))
            except Exception as e:
                logger.debug("Redis PubSub publish error: %s", e)

        logger.info(
            "Dispatched alert %s (%s) for VIN %s to tenant %s (active ws clients: %d)",
            alert_id,
            alert_data.get("fault_type"),
            vin,
            tenant_id,
            ws_manager.active_count_for_tenant(tenant_id),
        )
        return True


# Global singleton alert dispatcher
alert_dispatcher = AlertDispatcher()
