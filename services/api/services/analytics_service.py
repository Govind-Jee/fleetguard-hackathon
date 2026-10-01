"""
FleetGuard Pulse - Historical Fleet Analytics Service Layer.
Computes fast, lightweight domain aggregate analytics from PostgreSQL 3NF storage.
"""

from datetime import datetime, timezone
import logging
import psycopg2

from services.api.schemas.analytics import AnalyticsSummaryResponse

logger = logging.getLogger("fleetguard.api.services.analytics")


class AnalyticsService:

    @staticmethod
    def get_summary(
        conn: psycopg2.extensions.connection,
        tenant_id: str,
    ) -> AnalyticsSummaryResponse:
        """Compute aggregated operational metrics across all assets in tenant scope."""
        # Query 1: Vehicle & powertrain metrics
        sql_vehicles = """
        SELECT 
            COUNT(v.vehicle_id) AS total_vehicles,
            COUNT(DISTINCT v.fleet_id) AS total_fleets,
            COUNT(v.vehicle_id) FILTER (WHERE m.vehicle_type = 'ICE') AS ice_count,
            COUNT(v.vehicle_id) FILTER (WHERE m.vehicle_type = 'HEV') AS hev_count,
            COUNT(v.vehicle_id) FILTER (WHERE m.vehicle_type = 'BEV') AS bev_count,
            COALESCE(AVG(v.initial_odometer_km), 0.0) AS avg_odo
        FROM vehicles v
        JOIN vehicle_models m ON v.model_id = m.model_id
        WHERE v.tenant_id = %s;
        """
        with conn.cursor() as cur:
            cur.execute(sql_vehicles, (tenant_id,))
            v_row = cur.fetchone()

        total_v = v_row[0] if v_row else 0
        total_f = v_row[1] if v_row else 0
        ice_c = v_row[2] if v_row else 0
        hev_c = v_row[3] if v_row else 0
        bev_c = v_row[4] if v_row else 0
        avg_odo = float(v_row[5]) if v_row else 0.0

        # Query 2: Alerts and work order completions
        sql_activity = """
        SELECT 
            (SELECT COUNT(*) FROM alerts WHERE tenant_id = %s) AS total_alerts,
            (SELECT COUNT(*) FROM alerts WHERE tenant_id = %s AND is_acknowledged = FALSE) AS unack_alerts,
            (SELECT COUNT(*) FROM work_orders WHERE tenant_id = %s AND status = 'COMPLETED') AS completed_wo;
        """
        with conn.cursor() as cur:
            cur.execute(sql_activity, (tenant_id, tenant_id, tenant_id))
            act_row = cur.fetchone()

        tot_alerts = act_row[0] if act_row else 0
        unack_alerts = act_row[1] if act_row else 0
        completed_wo = act_row[2] if act_row else 0

        return AnalyticsSummaryResponse(
            tenant_id=tenant_id,
            total_monitored_vehicles=total_v,
            active_fleets_count=total_f,
            powertrain_breakdown={"ICE": ice_c, "HEV": hev_c, "BEV": bev_c},
            total_alerts_recorded=tot_alerts,
            unresolved_alerts_count=unack_alerts,
            completed_work_orders_count=completed_wo,
            average_fleet_odometer_km=round(avg_odo, 2),
            as_of_timestamp=datetime.now(timezone.utc).isoformat(),
        )
