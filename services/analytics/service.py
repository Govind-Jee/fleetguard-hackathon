"""
FleetGuard Pulse - Batch Analytics Service Layer.
Executes efficient OLAP aggregations in ClickHouse across historical telemetry
with strict tenant scoping and PostgreSQL 3NF metadata cross-referencing.
"""

from datetime import datetime, timezone
import logging
from typing import List, Optional, Tuple
import psycopg2

from services.analytics.models import (
    FaultFrequencyItem,
    FaultFrequencyResponse,
    FleetReliabilityMetrics,
    MTBFMetrics,
    ReliabilityTrendItem,
    ReliabilityTrendResponse,
    TimeWindow,
    VehicleDegradationItem,
    VehicleDegradationResponse,
)
from services.analytics.queries import (
    DEGRADATION_RANKING_SQL,
    FAULT_FREQUENCY_SQL,
    FLEET_RELIABILITY_SUMMARY_SQL,
    MTBF_SQL,
    RELIABILITY_TREND_DAY_SQL,
    RELIABILITY_TREND_WEEK_SQL,
)
from services.api.exceptions import (
    DatabaseUnavailableError,
    InvalidInputError,
    ResourceNotFoundError,
)

logger = logging.getLogger("fleetguard.analytics.service")


class BatchAnalyticsService:
    """Service executing batch OLAP reliability and degradation analytics against ClickHouse."""

    @staticmethod
    def _resolve_tenant_vins(
        pg_conn: psycopg2.extensions.connection,
        tenant_id: str,
        fleet_id: Optional[str] = None,
    ) -> List[str]:
        """
        Queries PostgreSQL 3NF domain tables to resolve authorized VINs within tenant boundary.
        Prevents cross-tenant analytical data leakage.
        """
        with pg_conn.cursor() as cur:
            if fleet_id:
                # Verify fleet exists and belongs to tenant
                cur.execute(
                    "SELECT fleet_id FROM fleets WHERE fleet_id = %s AND tenant_id = %s;",
                    (fleet_id, tenant_id),
                )
                if not cur.fetchone():
                    raise ResourceNotFoundError("Fleet", fleet_id)

                cur.execute(
                    "SELECT vin FROM vehicles WHERE tenant_id = %s AND fleet_id = %s;",
                    (tenant_id, fleet_id),
                )
            else:
                cur.execute(
                    "SELECT vin FROM vehicles WHERE tenant_id = %s;",
                    (tenant_id,),
                )
            rows = cur.fetchall()
            return [r[0] for r in rows]

    @staticmethod
    def get_fleet_reliability(
        ch_client,
        pg_conn: psycopg2.extensions.connection,
        tenant_id: str,
        fleet_id: Optional[str] = None,
        time_window: Optional[TimeWindow] = None,
    ) -> FleetReliabilityMetrics:
        """Computes aggregate fleet reliability summary from ClickHouse telemetry."""
        if not ch_client:
            raise DatabaseUnavailableError("ClickHouse")

        window = time_window or TimeWindow.create()
        vins = BatchAnalyticsService._resolve_tenant_vins(pg_conn, tenant_id, fleet_id)

        if not vins:
            return FleetReliabilityMetrics(
                tenant_id=tenant_id,
                fleet_id=fleet_id,
                start_time=window.start_time.isoformat(),
                end_time=window.end_time.isoformat(),
                total_monitored_vehicles=0,
                telemetry_event_count=0,
                fault_event_count=0,
                critical_fault_count=0,
                affected_vehicle_count=0,
                fault_rate=0.0,
            )

        params = {
            "vins": tuple(vins),
            "start_time": window.start_time,
            "end_time": window.end_time,
        }

        try:
            res = ch_client.query(
                FLEET_RELIABILITY_SUMMARY_SQL,
                parameters=params,
                settings={"max_query_size": 10485760},
            )
            row = res.result_rows[0] if res.result_rows else (0, 0, 0, 0, 0)
            monitored_v = int(row[0])
            total_events = int(row[1])
            critical_faults = int(row[2])
            fault_events = int(row[3])
            affected_v = int(row[4])
            fault_rate = round(fault_events / total_events, 4) if total_events > 0 else 0.0

            return FleetReliabilityMetrics(
                tenant_id=tenant_id,
                fleet_id=fleet_id,
                start_time=window.start_time.isoformat(),
                end_time=window.end_time.isoformat(),
                total_monitored_vehicles=monitored_v,
                telemetry_event_count=total_events,
                fault_event_count=fault_events,
                critical_fault_count=critical_faults,
                affected_vehicle_count=affected_v,
                fault_rate=fault_rate,
            )
        except Exception as e:
            logger.error("ClickHouse fleet reliability query failed: %s", e)
            raise DatabaseUnavailableError("ClickHouse")

    @staticmethod
    def get_fault_frequency(
        ch_client,
        pg_conn: psycopg2.extensions.connection,
        tenant_id: str,
        fleet_id: Optional[str] = None,
        time_window: Optional[TimeWindow] = None,
    ) -> FaultFrequencyResponse:
        """Groups historical faults by DTC code or physical fault classification."""
        if not ch_client:
            raise DatabaseUnavailableError("ClickHouse")

        window = time_window or TimeWindow.create()
        vins = BatchAnalyticsService._resolve_tenant_vins(pg_conn, tenant_id, fleet_id)

        if not vins:
            return FaultFrequencyResponse(
                tenant_id=tenant_id,
                fleet_id=fleet_id,
                start_time=window.start_time.isoformat(),
                end_time=window.end_time.isoformat(),
                total_fault_events=0,
                faults=[],
            )

        params = {
            "vins": tuple(vins),
            "start_time": window.start_time,
            "end_time": window.end_time,
        }

        try:
            res = ch_client.query(
                FAULT_FREQUENCY_SQL,
                parameters=params,
                settings={"max_query_size": 10485760},
            )
            rows = res.result_rows or []
            total_fault_count = sum(r[1] for r in rows)

            items: List[FaultFrequencyItem] = []
            for r in rows:
                fault_name = str(r[0])
                count = int(r[1])
                affected_v = int(r[2])
                pct = round((count / total_fault_count) * 100.0, 2) if total_fault_count > 0 else 0.0
                items.append(
                    FaultFrequencyItem(
                        fault_type=fault_name,
                        occurrence_count=count,
                        affected_vehicle_count=affected_v,
                        percentage=pct,
                    )
                )

            return FaultFrequencyResponse(
                tenant_id=tenant_id,
                fleet_id=fleet_id,
                start_time=window.start_time.isoformat(),
                end_time=window.end_time.isoformat(),
                total_fault_events=total_fault_count,
                faults=items,
            )
        except Exception as e:
            logger.error("ClickHouse fault frequency query failed: %s", e)
            raise DatabaseUnavailableError("ClickHouse")

    @staticmethod
    def get_mtbf(
        ch_client,
        pg_conn: psycopg2.extensions.connection,
        tenant_id: str,
        fleet_id: Optional[str] = None,
        time_window: Optional[TimeWindow] = None,
    ) -> MTBFMetrics:
        """Calculates Mean Time Between Failures for qualifying failure incidents."""
        if not ch_client:
            raise DatabaseUnavailableError("ClickHouse")

        window = time_window or TimeWindow.create()
        vins = BatchAnalyticsService._resolve_tenant_vins(pg_conn, tenant_id, fleet_id)

        if not vins:
            return MTBFMetrics(
                tenant_id=tenant_id,
                fleet_id=fleet_id,
                start_time=window.start_time.isoformat(),
                end_time=window.end_time.isoformat(),
                total_failure_incidents=0,
                total_operating_hours=0.0,
                vehicles_evaluated=0,
                notes="No vehicles found in tenant scope.",
            )

        params = {
            "vins": tuple(vins),
            "start_time": window.start_time,
            "end_time": window.end_time,
        }

        try:
            res = ch_client.query(
                MTBF_SQL,
                parameters=params,
                settings={"max_query_size": 10485760},
            )
            if not res.result_rows:
                return MTBFMetrics(
                    tenant_id=tenant_id,
                    fleet_id=fleet_id,
                    start_time=window.start_time.isoformat(),
                    end_time=window.end_time.isoformat(),
                    total_failure_incidents=0,
                    total_operating_hours=0.0,
                    vehicles_evaluated=len(vins),
                    notes="No failure incidents observed in time window.",
                )

            row = res.result_rows[0]
            total_incidents = int(row[0])
            intervals_count = int(row[1])
            mean_mtbf = round(float(row[2]), 2) if row[2] is not None else None
            median_mtbf = round(float(row[3]), 2) if row[3] is not None else None
            min_tbf = round(float(row[4]), 2) if row[4] is not None else None
            max_tbf = round(float(row[5]), 2) if row[5] is not None else None
            total_op_hours = round(float(row[6]), 2) if row[6] is not None else 0.0
            v_evaluated = int(row[7]) if row[7] is not None else len(vins)

            notes = None
            if intervals_count == 0:
                notes = (
                    f"Observed {total_incidents} failure incidents. Insufficient recurring "
                    f"failures on individual assets to compute empirical MTBF intervals."
                )

            return MTBFMetrics(
                tenant_id=tenant_id,
                fleet_id=fleet_id,
                start_time=window.start_time.isoformat(),
                end_time=window.end_time.isoformat(),
                mean_mtbf_hours=mean_mtbf,
                median_mtbf_hours=median_mtbf,
                min_tbf_hours=min_tbf,
                max_tbf_hours=max_tbf,
                total_failure_incidents=total_incidents,
                total_operating_hours=total_op_hours,
                vehicles_evaluated=v_evaluated,
                notes=notes,
            )
        except Exception as e:
            logger.error("ClickHouse MTBF query failed: %s", e)
            raise DatabaseUnavailableError("ClickHouse")

    @staticmethod
    def get_reliability_trend(
        ch_client,
        pg_conn: psycopg2.extensions.connection,
        tenant_id: str,
        fleet_id: Optional[str] = None,
        time_window: Optional[TimeWindow] = None,
        granularity: str = "day",
    ) -> ReliabilityTrendResponse:
        """Produces time-bucketed reliability trends with optional work order correlations."""
        if not ch_client:
            raise DatabaseUnavailableError("ClickHouse")

        window = time_window or TimeWindow.create()
        vins = BatchAnalyticsService._resolve_tenant_vins(pg_conn, tenant_id, fleet_id)

        if not vins:
            return ReliabilityTrendResponse(
                tenant_id=tenant_id,
                fleet_id=fleet_id,
                start_time=window.start_time.isoformat(),
                end_time=window.end_time.isoformat(),
                granularity=granularity,
                trends=[],
            )

        sql = RELIABILITY_TREND_WEEK_SQL if granularity == "week" else RELIABILITY_TREND_DAY_SQL
        params = {
            "vins": tuple(vins),
            "start_time": window.start_time,
            "end_time": window.end_time,
        }

        try:
            res = ch_client.query(
                sql,
                parameters=params,
                settings={"max_query_size": 10485760},
            )
            rows = res.result_rows or []

            # Query PostgreSQL for maintenance work order completions bucketed by date
            wo_counts = {}
            with pg_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT TO_CHAR(created_at, 'YYYY-MM-DD') AS p, COUNT(*)
                    FROM work_orders
                    WHERE tenant_id = %s AND created_at >= %s AND created_at <= %s
                    GROUP BY p;
                    """,
                    (tenant_id, window.start_time, window.end_time),
                )
                for r in cur.fetchall():
                    wo_counts[r[0]] = int(r[1])

            trends: List[ReliabilityTrendItem] = []
            for r in rows:
                p_str = str(r[0])
                v_obs = int(r[1])
                t_events = int(r[2])
                f_events = int(r[3])
                f_rate = float(r[4])
                m_events = wo_counts.get(p_str, 0)

                trends.append(
                    ReliabilityTrendItem(
                        period=p_str,
                        vehicles_observed=v_obs,
                        telemetry_event_count=t_events,
                        failure_events=f_events,
                        fault_rate=f_rate,
                        maintenance_events=m_events,
                    )
                )

            return ReliabilityTrendResponse(
                tenant_id=tenant_id,
                fleet_id=fleet_id,
                start_time=window.start_time.isoformat(),
                end_time=window.end_time.isoformat(),
                granularity=granularity,
                trends=trends,
            )
        except Exception as e:
            logger.error("ClickHouse reliability trend query failed: %s", e)
            raise DatabaseUnavailableError("ClickHouse")

    @staticmethod
    def get_vehicle_degradation_ranking(
        ch_client,
        pg_conn: psycopg2.extensions.connection,
        tenant_id: str,
        fleet_id: Optional[str] = None,
        time_window: Optional[TimeWindow] = None,
        limit: int = 10,
    ) -> VehicleDegradationResponse:
        """
        Ranks vehicles showing worsening historical condition based strictly on telemetry
        available before the reporting cutoff.
        """
        if not ch_client:
            raise DatabaseUnavailableError("ClickHouse")

        safe_limit = max(1, min(limit, 100))
        window = time_window or TimeWindow.create()
        vins = BatchAnalyticsService._resolve_tenant_vins(pg_conn, tenant_id, fleet_id)

        if not vins:
            return VehicleDegradationResponse(
                tenant_id=tenant_id,
                fleet_id=fleet_id,
                start_time=window.start_time.isoformat(),
                end_time=window.end_time.isoformat(),
                limit=safe_limit,
                total_evaluated=0,
                ranked_vehicles=[],
            )

        params = {
            "vins": tuple(vins),
            "start_time": window.start_time,
            "end_time": window.end_time,
            "limit": safe_limit,
        }

        try:
            res = ch_client.query(
                DEGRADATION_RANKING_SQL,
                parameters=params,
                settings={"max_query_size": 10485760},
            )
            rows = res.result_rows or []

            items: List[VehicleDegradationItem] = []
            for r in rows:
                vin = str(r[0])
                v_type = str(r[1])
                t_events = int(r[2])
                f_events = int(r[3])
                c_faults = int(r[4])
                avg_vib = float(r[5])
                max_vib = float(r[6])
                avg_coolant = float(r[7]) if r[7] is not None else None
                min_oil = float(r[8]) if r[8] is not None else None
                avg_cell_delta = float(r[9]) if r[9] is not None else None
                deg_score = float(r[10])

                if deg_score >= 70.0:
                    deg_level = "SEVERE"
                elif deg_score >= 40.0:
                    deg_level = "ELEVATED"
                elif deg_score >= 15.0:
                    deg_level = "MODERATE"
                else:
                    deg_level = "NORMAL"

                items.append(
                    VehicleDegradationItem(
                        vin=vin,
                        vehicle_type=v_type,
                        telemetry_events=t_events,
                        fault_events=f_events,
                        critical_faults=c_faults,
                        avg_vibration=avg_vib,
                        max_vibration=max_vib,
                        avg_coolant_temp=avg_coolant,
                        min_oil_pressure=min_oil,
                        avg_cell_temp_delta=avg_cell_delta,
                        degradation_score=deg_score,
                        degradation_level=deg_level,
                    )
                )

            return VehicleDegradationResponse(
                tenant_id=tenant_id,
                fleet_id=fleet_id,
                start_time=window.start_time.isoformat(),
                end_time=window.end_time.isoformat(),
                limit=safe_limit,
                total_evaluated=len(vins),
                ranked_vehicles=items,
            )
        except Exception as e:
            logger.error("ClickHouse vehicle degradation query failed: %s", e)
            raise DatabaseUnavailableError("ClickHouse")
