"""
FleetGuard Pulse - Fleet Health Service Layer.
Executes consolidated, constant-time aggregate SQL queries without N+1 overhead.
"""

import logging
from typing import List, Optional
import psycopg2

from services.api.schemas.fleets import FleetHealthResponse, FleetListResponse, FleetSummary

logger = logging.getLogger("fleetguard.api.services.fleet")


class FleetService:

    @staticmethod
    def list_fleets(
        conn: psycopg2.extensions.connection,
        tenant_id: str,
    ) -> FleetListResponse:
        """List all fleets belonging to tenant."""
        sql = """
        SELECT fleet_id, tenant_id, name, code, description, created_at
        FROM fleets
        WHERE tenant_id = %s
        ORDER BY name ASC;
        """
        with conn.cursor() as cur:
            cur.execute(sql, (tenant_id,))
            rows = cur.fetchall()

        items = [
            FleetSummary(
                fleet_id=str(r[0]),
                tenant_id=str(r[1]),
                name=r[2],
                code=r[3],
                description=r[4],
                created_at=r[5].isoformat() if hasattr(r[5], "isoformat") else str(r[5]),
            )
            for r in rows
        ]
        return FleetListResponse(items=items)

    @staticmethod
    def get_fleet_health(
        conn: psycopg2.extensions.connection,
        tenant_id: str,
        fleet_id: str,
    ) -> Optional[FleetHealthResponse]:
        """
        Compute consolidated fleet health using two optimized aggregate SQL queries.
        Zero N+1 query overhead.
        """
        # Query 1: Fleet metadata + vehicle status & powertrain type breakdown
        sql_vehicles = """
        SELECT 
            f.fleet_id, f.name, f.code,
            COUNT(v.vehicle_id) AS total_vehicles,
            COUNT(v.vehicle_id) FILTER (WHERE v.status = 'ACTIVE') AS active_count,
            COUNT(v.vehicle_id) FILTER (WHERE v.status = 'MAINTENANCE') AS maint_count,
            COUNT(v.vehicle_id) FILTER (WHERE v.status = 'INACTIVE') AS inactive_count,
            COUNT(v.vehicle_id) FILTER (WHERE v.status = 'DECOMMISSIONED') AS decomm_count,
            COUNT(v.vehicle_id) FILTER (WHERE m.vehicle_type = 'ICE') AS ice_count,
            COUNT(v.vehicle_id) FILTER (WHERE m.vehicle_type = 'HEV') AS hev_count,
            COUNT(v.vehicle_id) FILTER (WHERE m.vehicle_type = 'BEV') AS bev_count
        FROM fleets f
        LEFT JOIN vehicles v ON f.fleet_id = v.fleet_id
        LEFT JOIN vehicle_models m ON v.model_id = m.model_id
        WHERE f.fleet_id = %s AND f.tenant_id = %s
        GROUP BY f.fleet_id, f.name, f.code;
        """
        with conn.cursor() as cur:
            cur.execute(sql_vehicles, (fleet_id, tenant_id))
            f_row = cur.fetchone()

        if not f_row:
            return None

        # Query 2: Fleet-wide active alerts & work-order status breakdown
        sql_activity = """
        SELECT 
            COUNT(DISTINCT a.alert_id) FILTER (WHERE a.severity = 'CRITICAL' AND a.is_acknowledged = FALSE) AS crit_alerts,
            COUNT(DISTINCT a.vehicle_id) FILTER (WHERE a.severity IN ('WARNING', 'CRITICAL') AND a.is_acknowledged = FALSE) AS high_risk_vehicles,
            COUNT(DISTINCT wo.work_order_id) FILTER (WHERE wo.status = 'PENDING') AS wo_pending,
            COUNT(DISTINCT wo.work_order_id) FILTER (WHERE wo.status = 'SCHEDULED') AS wo_scheduled,
            COUNT(DISTINCT wo.work_order_id) FILTER (WHERE wo.status = 'IN_PROGRESS') AS wo_in_progress,
            COUNT(DISTINCT wo.work_order_id) FILTER (WHERE wo.status = 'COMPLETED') AS wo_completed
        FROM vehicles v
        LEFT JOIN alerts a ON v.vehicle_id = a.vehicle_id
        LEFT JOIN work_orders wo ON v.vehicle_id = wo.vehicle_id
        WHERE v.fleet_id = %s AND v.tenant_id = %s;
        """
        with conn.cursor() as cur:
            cur.execute(sql_activity, (fleet_id, tenant_id))
            act_row = cur.fetchone()

        total_v = f_row[3]
        active_v = f_row[4]
        maint_v = f_row[5]
        inactive_v = f_row[6]
        decomm_v = f_row[7]
        ice_v = f_row[8]
        hev_v = f_row[9]
        bev_v = f_row[10]

        crit_alerts = act_row[0] if act_row else 0
        high_risk = act_row[1] if act_row else 0
        wo_pending = act_row[2] if act_row else 0
        wo_scheduled = act_row[3] if act_row else 0
        wo_in_prog = act_row[4] if act_row else 0
        wo_completed = act_row[5] if act_row else 0

        # Health status estimates
        warning_count = max(0, high_risk - crit_alerts)
        nominal_count = max(0, active_v - high_risk)

        return FleetHealthResponse(
            fleet_id=str(f_row[0]),
            fleet_name=f_row[1],
            fleet_code=f_row[2],
            total_vehicles=total_v,
            vehicles_by_status={
                "ACTIVE": active_v,
                "MAINTENANCE": maint_v,
                "INACTIVE": inactive_v,
                "DECOMMISSIONED": decomm_v,
            },
            vehicles_by_type={
                "ICE": ice_v,
                "HEV": hev_v,
                "BEV": bev_v,
            },
            health_status_counts={
                "NOMINAL": nominal_count,
                "WARNING": warning_count,
                "CRITICAL": crit_alerts,
            },
            critical_alert_count=crit_alerts,
            high_risk_vehicle_count=high_risk,
            work_orders_summary={
                "PENDING": wo_pending,
                "SCHEDULED": wo_scheduled,
                "IN_PROGRESS": wo_in_prog,
                "COMPLETED": wo_completed,
            },
        )
