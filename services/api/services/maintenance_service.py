"""
FleetGuard Pulse - Maintenance & Work Order Service Layer.
Enforces multi-tenant ownership on vehicles and technicians, validates catalogs,
and persists normalized 3NF work order records.
"""

import logging
from typing import Optional
import psycopg2

from services.api.exceptions import InvalidInputError, ResourceNotFoundError
from services.api.schemas.maintenance import WorkOrderCreateRequest, WorkOrderResponse

logger = logging.getLogger("fleetguard.api.services.maintenance")


class MaintenanceService:

    @staticmethod
    def create_work_order(
        conn: psycopg2.extensions.connection,
        tenant_id: str,
        actor_user_id: str,
        request: WorkOrderCreateRequest,
    ) -> WorkOrderResponse:
        """
        Create a new maintenance work order.
        Strictly validates vehicle existence and tenant ownership, preventing cross-tenant references.
        """
        # 1. Validate vehicle existence within tenant boundary
        with conn.cursor() as cur:
            cur.execute(
                "SELECT vehicle_id FROM vehicles WHERE vin = %s AND tenant_id = %s;",
                (request.vin, tenant_id),
            )
            v_row = cur.fetchone()

        if not v_row:
            raise ResourceNotFoundError(resource="Vehicle", identifier=request.vin)
        vehicle_id = str(v_row[0])

        # 2. Validate maintenance type catalog existence
        with conn.cursor() as cur:
            cur.execute(
                "SELECT type_id, name FROM maintenance_types WHERE type_id = %s;",
                (request.type_id,),
            )
            m_row = cur.fetchone()

        if not m_row:
            raise ResourceNotFoundError(resource="MaintenanceType", identifier=str(request.type_id))
        type_name = str(m_row[1])

        # 3. Validate technician assignment if provided
        tech_id: Optional[str] = None
        if request.assigned_technician_id:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id FROM users WHERE user_id = %s AND tenant_id = %s;",
                    (request.assigned_technician_id, tenant_id),
                )
                u_row = cur.fetchone()
            if not u_row:
                raise ResourceNotFoundError(
                    resource="AssignedTechnician",
                    identifier=request.assigned_technician_id,
                )
            tech_id = str(u_row[0])

        # 4. Insert normalized work order
        sql_insert = """
        INSERT INTO work_orders (
            tenant_id, vehicle_id, type_id, priority, status,
            assigned_technician_id, scheduled_at
        ) VALUES (
            %s, %s, %s, %s, 'PENDING', %s, %s
        ) RETURNING work_order_id, created_at, updated_at;
        """
        with conn.cursor() as cur:
            cur.execute(
                sql_insert,
                (
                    tenant_id,
                    vehicle_id,
                    request.type_id,
                    request.priority,
                    tech_id,
                    request.scheduled_at,
                ),
            )
            ins_row = cur.fetchone()

        work_order_id = str(ins_row[0])
        created_at = ins_row[1].isoformat() if hasattr(ins_row[1], "isoformat") else str(ins_row[1])
        updated_at = ins_row[2].isoformat() if hasattr(ins_row[2], "isoformat") else str(ins_row[2])

        logger.info(
            "Created work order %s for VIN %s (tenant=%s, priority=%s)",
            work_order_id,
            request.vin,
            tenant_id,
            request.priority,
        )

        return WorkOrderResponse(
            work_order_id=work_order_id,
            tenant_id=tenant_id,
            vehicle_id=vehicle_id,
            vin=request.vin,
            type_id=request.type_id,
            maintenance_type_name=type_name,
            priority=request.priority,
            status="PENDING",
            assigned_technician_id=tech_id,
            scheduled_at=request.scheduled_at,
            created_at=created_at,
            updated_at=updated_at,
        )
