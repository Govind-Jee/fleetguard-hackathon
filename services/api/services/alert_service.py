"""
FleetGuard Pulse - Alert Service Layer.
Queries durable operational and critical alerts from PostgreSQL with strict tenant scoping.
"""

import logging
from math import ceil
from typing import Any, List, Optional
import psycopg2

from services.api.schemas.alerts import AlertDetail, AlertListResponse, AlertSummary
from services.api.schemas.common import PaginationMeta

logger = logging.getLogger("fleetguard.api.services.alert")


class AlertService:

    @staticmethod
    def list_alerts(
        conn: psycopg2.extensions.connection,
        tenant_id: str,
        fleet_id: Optional[str] = None,
        vin: Optional[str] = None,
        severity: Optional[str] = None,
        is_acknowledged: Optional[bool] = None,
        page: int = 1,
        limit: int = 50,
    ) -> AlertListResponse:
        """Query paginated alerts belonging strictly to the requesting tenant."""
        page = max(1, page)
        limit = min(200, max(1, limit))
        offset = (page - 1) * limit

        query_parts = [
            """
            SELECT 
                a.alert_id, a.tenant_id, a.vehicle_id, v.vin, a.telemetry_event_id,
                a.severity, a.fault_type, a.message, a.sequence_number,
                a.is_acknowledged, a.created_at,
                COUNT(*) OVER() AS full_count
            FROM alerts a
            JOIN vehicles v ON a.vehicle_id = v.vehicle_id
            WHERE a.tenant_id = %s
            """
        ]
        params: List[Any] = [tenant_id]

        if fleet_id:
            query_parts.append("AND v.fleet_id = %s")
            params.append(fleet_id)
        if vin:
            query_parts.append("AND v.vin = %s")
            params.append(vin)
        if severity:
            query_parts.append("AND a.severity = %s")
            params.append(severity.upper())
        if is_acknowledged is not None:
            query_parts.append("AND a.is_acknowledged = %s")
            params.append(is_acknowledged)

        query_parts.append("ORDER BY a.created_at DESC LIMIT %s OFFSET %s;")
        params.extend([limit, offset])

        full_sql = " ".join(query_parts)

        with conn.cursor() as cur:
            cur.execute(full_sql, params)
            rows = cur.fetchall()

        total_count = rows[0][-1] if rows else 0
        total_pages = ceil(total_count / limit) if total_count > 0 else 0

        items: List[AlertSummary] = []
        for r in rows:
            items.append(
                AlertSummary(
                    alert_id=str(r[0]),
                    tenant_id=str(r[1]),
                    vehicle_id=str(r[2]),
                    vin=r[3],
                    telemetry_event_id=str(r[4]),
                    severity=r[5],
                    fault_type=r[6],
                    message=r[7],
                    sequence_number=r[8],
                    is_acknowledged=bool(r[9]),
                    created_at=r[10].isoformat() if hasattr(r[10], "isoformat") else str(r[10]),
                )
            )

        return AlertListResponse(
            items=items,
            pagination=PaginationMeta(
                page=page,
                limit=limit,
                total_count=total_count,
                total_pages=total_pages,
            ),
        )

    @staticmethod
    def get_alert_by_id(
        conn: psycopg2.extensions.connection,
        tenant_id: str,
        alert_id: str,
    ) -> Optional[AlertDetail]:
        """Fetch alert record by ID, enforcing tenant isolation boundary."""
        sql = """
        SELECT 
            a.alert_id, a.tenant_id, a.vehicle_id, v.vin, a.telemetry_event_id,
            a.severity, a.fault_type, a.message, a.sequence_number,
            a.is_acknowledged, a.created_at, a.acknowledged_at,
            a.acknowledged_by_user_id, a.resolution_work_order_id, a.updated_at
        FROM alerts a
        JOIN vehicles v ON a.vehicle_id = v.vehicle_id
        WHERE a.alert_id = %s AND a.tenant_id = %s;
        """
        with conn.cursor() as cur:
            cur.execute(sql, (alert_id, tenant_id))
            r = cur.fetchone()

        if not r:
            return None

        return AlertDetail(
            alert_id=str(r[0]),
            tenant_id=str(r[1]),
            vehicle_id=str(r[2]),
            vin=r[3],
            telemetry_event_id=str(r[4]),
            severity=r[5],
            fault_type=r[6],
            message=r[7],
            sequence_number=r[8],
            is_acknowledged=bool(r[9]),
            created_at=r[10].isoformat() if hasattr(r[10], "isoformat") else str(r[10]),
            acknowledged_at=r[11].isoformat() if (r[11] and hasattr(r[11], "isoformat")) else (str(r[11]) if r[11] else None),
            acknowledged_by_user_id=str(r[12]) if r[12] else None,
            resolution_work_order_id=str(r[13]) if r[13] else None,
            updated_at=r[14].isoformat() if hasattr(r[14], "isoformat") else str(r[14]),
        )
