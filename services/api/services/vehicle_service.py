"""
FleetGuard Pulse - Vehicle Service Layer.
Encapsulates SQL pagination, multi-tenant scoping, and Redis hot state integration.
"""

import json
import logging
from math import ceil
from typing import Any, Dict, List, Optional, Tuple
import psycopg2
import redis

from services.api.schemas.vehicles import (
    VehicleAuthoritativeDetail,
    VehicleDetailResponse,
    VehicleHealthResponse,
    VehicleHotState,
    VehicleLocation,
    VehicleAlertSummary,
    VehicleModelSpecs,
    VehicleSummary,
    VehicleListResponse,
)
from services.api.schemas.common import PaginationMeta

logger = logging.getLogger("fleetguard.api.services.vehicle")


class VehicleService:

    @staticmethod
    def list_vehicles(
        conn: psycopg2.extensions.connection,
        tenant_id: str,
        fleet_id: Optional[str] = None,
        vehicle_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> VehicleListResponse:
        """
        Query paginated vehicles belonging strictly to tenant_id.
        Uses SQL window function COUNT(*) OVER() to avoid separate count query.
        """
        page = max(1, page)
        limit = min(200, max(1, limit))
        offset = (page - 1) * limit

        query_parts = [
            """
            SELECT 
                v.vehicle_id, v.vin, v.license_plate, v.status, v.manufacture_year,
                f.fleet_id, f.name AS fleet_name, f.code AS fleet_code,
                d.depot_id, d.name AS depot_name, d.code AS depot_code,
                m.make, m.model_name, m.year AS model_year, m.vehicle_type,
                m.engine_displacement_l, m.battery_capacity_kwh, m.curb_weight_kg,
                COUNT(*) OVER() AS full_count
            FROM vehicles v
            JOIN fleets f ON v.fleet_id = f.fleet_id
            JOIN depots d ON v.depot_id = d.depot_id
            JOIN vehicle_models m ON v.model_id = m.model_id
            WHERE v.tenant_id = %s
            """
        ]
        params: List[Any] = [tenant_id]

        if fleet_id:
            query_parts.append("AND v.fleet_id = %s")
            params.append(fleet_id)
        if vehicle_type:
            query_parts.append("AND m.vehicle_type = %s")
            params.append(vehicle_type.upper())
        if status:
            query_parts.append("AND v.status = %s")
            params.append(status.upper())

        query_parts.append("ORDER BY v.vin ASC LIMIT %s OFFSET %s;")
        params.extend([limit, offset])

        full_sql = " ".join(query_parts)

        with conn.cursor() as cur:
            cur.execute(full_sql, params)
            rows = cur.fetchall()

        total_count = rows[0][-1] if rows else 0
        total_pages = ceil(total_count / limit) if total_count > 0 else 0

        items: List[VehicleSummary] = []
        for r in rows:
            items.append(
                VehicleSummary(
                    vehicle_id=str(r[0]),
                    vin=r[1],
                    license_plate=r[2],
                    status=r[3],
                    manufacture_year=r[4],
                    fleet_id=str(r[5]),
                    fleet_name=r[6],
                    fleet_code=r[7],
                    depot_id=str(r[8]),
                    depot_name=r[9],
                    depot_code=r[10],
                    model=VehicleModelSpecs(
                        make=r[11],
                        model_name=r[12],
                        year=r[13],
                        vehicle_type=r[14],
                        engine_displacement_l=float(r[15]) if r[15] is not None else None,
                        battery_capacity_kwh=float(r[16]) if r[16] is not None else None,
                        curb_weight_kg=r[17],
                    ),
                )
            )

        return VehicleListResponse(
            items=items,
            pagination=PaginationMeta(
                page=page,
                limit=limit,
                total_count=total_count,
                total_pages=total_pages,
            ),
        )

    @staticmethod
    def get_vehicle_detail(
        conn: psycopg2.extensions.connection,
        redis_client: redis.Redis,
        tenant_id: str,
        vin: str,
    ) -> Optional[VehicleDetailResponse]:
        """
        Fetch vehicle record, ensuring strict tenant isolation.
        Enriches authoritative data with transient Redis hot state.
        """
        sql = """
        SELECT 
            v.vehicle_id, v.vin, v.tenant_id, v.license_plate, v.manufacture_year, v.status,
            v.initial_odometer_km, v.created_at, v.updated_at,
            f.fleet_id, f.name AS fleet_name, f.code AS fleet_code,
            d.depot_id, d.name AS depot_name, d.code AS depot_code,
            m.make, m.model_name, m.year AS model_year, m.vehicle_type,
            m.engine_displacement_l, m.battery_capacity_kwh, m.curb_weight_kg
        FROM vehicles v
        JOIN fleets f ON v.fleet_id = f.fleet_id
        JOIN depots d ON v.depot_id = d.depot_id
        JOIN vehicle_models m ON v.model_id = m.model_id
        WHERE v.vin = %s AND v.tenant_id = %s;
        """
        with conn.cursor() as cur:
            cur.execute(sql, (vin, tenant_id))
            r = cur.fetchone()

        if not r:
            return None

        authoritative = VehicleAuthoritativeDetail(
            vehicle_id=str(r[0]),
            vin=r[1],
            tenant_id=str(r[2]),
            license_plate=r[3],
            manufacture_year=r[4],
            status=r[5],
            initial_odometer_km=float(r[6]),
            created_at=r[7].isoformat() if hasattr(r[7], "isoformat") else str(r[7]),
            updated_at=r[8].isoformat() if hasattr(r[8], "isoformat") else str(r[8]),
            fleet={"fleet_id": str(r[9]), "name": r[10], "code": r[11]},
            depot={"depot_id": str(r[12]), "name": r[13], "code": r[14]},
            model=VehicleModelSpecs(
                make=r[15],
                model_name=r[16],
                year=r[17],
                vehicle_type=r[18],
                engine_displacement_l=float(r[19]) if r[19] is not None else None,
                battery_capacity_kwh=float(r[20]) if r[20] is not None else None,
                curb_weight_kg=r[21],
            ),
        )

        # Retrieve transient Redis hot state
        hot_state: Optional[VehicleHotState] = None
        try:
            raw_hot = redis_client.hgetall(f"vehicle:state:{vin}")
            if raw_hot and "sequence_number" in raw_hot:
                dtcs = []
                if "dtc_codes" in raw_hot:
                    try:
                        dtcs = json.loads(raw_hot["dtc_codes"])
                    except Exception:
                        dtcs = []

                hot_state = VehicleHotState(
                    sequence_number=int(raw_hot.get("sequence_number", 0)),
                    timestamp=raw_hot.get("timestamp", ""),
                    health_status=raw_hot.get("health_status", "NOMINAL"),
                    latitude=float(raw_hot.get("latitude", 0.0)),
                    longitude=float(raw_hot.get("longitude", 0.0)),
                    speed_kmh=float(raw_hot.get("speed_kmh", 0.0)),
                    odometer_km=float(raw_hot.get("odometer_km", 0.0)),
                    vibration=float(raw_hot.get("vibration", 0.0)),
                    dtc_codes=dtcs,
                    oil_pressure_kpa=float(raw_hot["oil_pressure_kpa"]) if "oil_pressure_kpa" in raw_hot else None,
                    coolant_temp_c=float(raw_hot["coolant_temp_c"]) if "coolant_temp_c" in raw_hot else None,
                    engine_rpm=float(raw_hot["engine_rpm"]) if "engine_rpm" in raw_hot else None,
                    battery_voltage_v=float(raw_hot["battery_voltage_v"]) if "battery_voltage_v" in raw_hot else None,
                    soc_pct=float(raw_hot["soc_pct"]) if "soc_pct" in raw_hot else None,
                    pack_voltage_v=float(raw_hot["pack_voltage_v"]) if "pack_voltage_v" in raw_hot else None,
                    motor_rpm=float(raw_hot["motor_rpm"]) if "motor_rpm" in raw_hot else None,
                    cell_temp_delta_c=float(raw_hot["cell_temp_delta_c"]) if "cell_temp_delta_c" in raw_hot else None,
                    updated_at=raw_hot.get("updated_at", ""),
                )
        except Exception as e:
            logger.warning("Failed to fetch Redis hot state for %s: %s", vin, e)

        return VehicleDetailResponse(
            vin=vin,
            authoritative=authoritative,
            transient_state=hot_state,
        )

    @staticmethod
    def get_vehicle_health(
        conn: psycopg2.extensions.connection,
        redis_client: redis.Redis,
        tenant_id: str,
        vin: str,
    ) -> Optional[VehicleHealthResponse]:
        """
        Consolidated vehicle operational health view combining Redis hot state
        and PostgreSQL durable alert statistics.
        """
        # Validate existence & tenant ownership
        with conn.cursor() as cur:
            cur.execute("SELECT vehicle_id FROM vehicles WHERE vin = %s AND tenant_id = %s;", (vin, tenant_id))
            row = cur.fetchone()

        if not row:
            return None
        vehicle_id = str(row[0])

        # Redis hot state
        raw_hot = {}
        try:
            raw_hot = redis_client.hgetall(f"vehicle:state:{vin}") or {}
        except Exception as e:
            logger.warning("Redis error querying hot state for %s: %s", vin, e)

        # PostgreSQL alerts summary
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    COUNT(*) FILTER (WHERE is_acknowledged = FALSE) AS unack_count,
                    (SELECT severity FROM alerts WHERE vehicle_id = %s ORDER BY created_at DESC LIMIT 1) AS latest_sev,
                    (SELECT fault_type FROM alerts WHERE vehicle_id = %s ORDER BY created_at DESC LIMIT 1) AS latest_fault,
                    (SELECT message FROM alerts WHERE vehicle_id = %s ORDER BY created_at DESC LIMIT 1) AS latest_msg,
                    (SELECT created_at FROM alerts WHERE vehicle_id = %s ORDER BY created_at DESC LIMIT 1) AS latest_ts
                FROM alerts
                WHERE vehicle_id = %s AND tenant_id = %s;
                """,
                (vehicle_id, vehicle_id, vehicle_id, vehicle_id, vehicle_id, tenant_id),
            )
            a_row = cur.fetchone()

        unack_count = a_row[0] if a_row else 0
        latest_sev = a_row[1] if a_row else None
        latest_fault = a_row[2] if a_row else None
        latest_msg = a_row[3] if a_row else None
        latest_ts = a_row[4].isoformat() if (a_row and a_row[4]) else None

        alert_summary = VehicleAlertSummary(
            unacknowledged_alert_count=unack_count,
            latest_severity=latest_sev,
            latest_fault_type=latest_fault,
            latest_alert_message=latest_msg,
            latest_alert_timestamp=latest_ts,
        )

        loc = None
        if "latitude" in raw_hot and "longitude" in raw_hot:
            loc = VehicleLocation(
                latitude=float(raw_hot["latitude"]),
                longitude=float(raw_hot["longitude"]),
            )

        raw_status = raw_hot.get("health_status", "NOMINAL")
        current_health = "NOMINAL" if raw_status in ("NORMAL", "NOMINAL") else raw_status
        if unack_count > 0 and current_health == "NOMINAL":
            current_health = "WARNING"

        return VehicleHealthResponse(
            vin=vin,
            current_health_state=current_health,
            latest_telemetry_timestamp=raw_hot.get("timestamp"),
            latest_sequence_number=int(raw_hot["sequence_number"]) if "sequence_number" in raw_hot else None,
            location=loc,
            speed_kmh=float(raw_hot["speed_kmh"]) if "speed_kmh" in raw_hot else None,
            odometer_km=float(raw_hot["odometer_km"]) if "odometer_km" in raw_hot else None,
            alert_summary=alert_summary,
        )
