"""
FleetGuard Pulse - Redis Hot State Manager

Maintains hot operational state for all active connected vehicles under 'vehicle:state:{vin}'.
Uses atomic Lua check-and-set to guarantee monotonic sequence progression and prevent race conditions.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional
import redis

from services.simulator.schema import TelemetryEvent
from services.stream_processor.models import AlertSeverity, CriticalAlert
from services.stream_processor.metrics import default_metrics

logger = logging.getLogger("stream_processor.state")

LUA_CONDITIONAL_UPDATE = """
local current_seq = redis.call('HGET', KEYS[1], 'sequence_number')
local incoming_seq = tonumber(ARGV[1])

if not current_seq or incoming_seq > tonumber(current_seq) then
    local data = cjson.decode(ARGV[2])
    for k, v in pairs(data) do
        redis.call('HSET', KEYS[1], k, tostring(v))
    end
    -- Also add to active vehicles set
    redis.call('SADD', 'vehicles:active', data['vin'])
    return 1
else
    return 0
end
"""


class RedisStateManager:
    """Manages vehicle hot state in Redis with atomic out-of-order protection."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6380,
        db: int = 0,
        password: Optional[str] = None,
        metrics=None,
    ):
        self.host = host
        self.port = port
        self.client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
        self.metrics = metrics or default_metrics
        # Register Lua script
        self._lua_update = self.client.register_script(LUA_CONDITIONAL_UPDATE)

    def ping(self) -> bool:
        """Verify Redis connectivity."""
        try:
            return bool(self.client.ping())
        except Exception as e:
            logger.error("Redis ping failed: %s", e)
            return False

    def update_vehicle_state(
        self,
        event: TelemetryEvent,
        health_status: AlertSeverity,
        latest_alert: Optional[CriticalAlert] = None,
    ) -> bool:
        """
        Atomically update vehicle hot state in Redis if incoming sequence_number is strictly greater.

        Returns:
            True if state was updated.
            False if incoming event was out-of-order / superseded by a higher sequence number.
        """
        key = f"vehicle:state:{event.vin}"

        # Construct flat payload for Redis Hash
        payload: Dict[str, Any] = {
            "vin": event.vin,
            "vehicle_type": event.vehicle_type.value,
            "timestamp": event.timestamp,
            "sequence_number": event.sequence_number,
            "health_status": health_status.value,
            "latitude": event.latitude,
            "longitude": event.longitude,
            "speed_kmh": event.speed_kmh,
            "odometer_km": event.odometer_km,
            "vibration": event.vibration,
            "dtc_codes": json.dumps(event.dtc_codes),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        # Optional powertrain fields
        if event.oil_pressure_kpa is not None:
            payload["oil_pressure_kpa"] = event.oil_pressure_kpa
        if event.coolant_temp_c is not None:
            payload["coolant_temp_c"] = event.coolant_temp_c
        if event.engine_rpm is not None:
            payload["engine_rpm"] = event.engine_rpm
        if event.battery_voltage_v is not None:
            payload["battery_voltage_v"] = event.battery_voltage_v
        if event.soc_pct is not None:
            payload["soc_pct"] = event.soc_pct
        if event.pack_voltage_v is not None:
            payload["pack_voltage_v"] = event.pack_voltage_v
        if event.motor_rpm is not None:
            payload["motor_rpm"] = event.motor_rpm
        if event.cell_temp_delta_c is not None:
            payload["cell_temp_delta_c"] = event.cell_temp_delta_c

        # Alert metadata
        if latest_alert is not None:
            payload["last_alert_id"] = latest_alert.alert_id
            payload["last_alert_severity"] = latest_alert.severity.value
            payload["last_alert_fault"] = latest_alert.fault_type
            payload["last_alert_message"] = latest_alert.message
            payload["last_alert_timestamp"] = latest_alert.timestamp

        try:
            res = self._lua_update(
                keys=[key],
                args=[event.sequence_number, json.dumps(payload)],
            )
            if res == 1:
                self.metrics.increment("redis_state_updates")
                return True
            else:
                logger.debug(
                    "Redis state update skipped for VIN %s (seq %d not newer)",
                    event.vin,
                    event.sequence_number,
                )
                return False
        except Exception as e:
            logger.error("Failed to execute atomic Redis state update for %s: %s", key, e)
            return False

    def get_vehicle_state(self, vin: str) -> Optional[Dict[str, str]]:
        """Retrieve full hot state hash for a vehicle."""
        key = f"vehicle:state:{vin}"
        try:
            state = self.client.hgetall(key)
            return state if state else None
        except Exception as e:
            logger.error("Failed to get vehicle state for %s: %s", vin, e)
            return None

    def get_active_vins(self) -> List[str]:
        """Return list of all active VINs."""
        try:
            return list(self.client.smembers("vehicles:active"))
        except Exception as e:
            logger.error("Failed to get active vehicles set: %s", e)
            return []

    def close(self) -> None:
        """Close connection."""
        try:
            self.client.close()
        except Exception:
            pass
