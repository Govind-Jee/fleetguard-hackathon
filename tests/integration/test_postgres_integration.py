"""
Integration tests for PostgreSQL 16 3NF Relational Domain & pgvector in FleetGuard Pulse.
Verifies table constraints, foreign key enforcement, uniqueness, check constraints,
migration runner idempotency, and cosine distance nearest-neighbor vector search.
"""

import os
import uuid
import pytest
import psycopg2
from psycopg2 import errors

from infra.database.migrate import get_connection_params, run_migrations


@pytest.fixture(scope="module")
def db_conn():
    config = get_connection_params()
    conn = psycopg2.connect(**config)
    conn.autocommit = False
    yield conn
    conn.close()


def test_migration_runner_idempotency():
    """Verify running migrations on an up-to-date database is a safe no-op."""
    config = get_connection_params()
    applied = run_migrations(config)
    assert applied == [], "Expected zero new migrations on already-migrated database"


def test_valid_relational_entity_insertion_and_joins(db_conn):
    """Verify insertion of full 3NF hierarchy and normalized relational JOIN queries."""
    with db_conn.cursor() as cur:
        # Create test tenant
        tenant_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO tenants (tenant_id, name) VALUES (%s, %s);",
            (tenant_id, f"Test Tenant {tenant_id[:8]}"),
        )

        # Create test fleet
        fleet_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO fleets (fleet_id, tenant_id, name, code) VALUES (%s, %s, %s, %s);",
            (fleet_id, tenant_id, "Express Fleet", f"FLT-{tenant_id[:4]}"),
        )

        # Create test depot
        depot_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO depots (depot_id, tenant_id, name, code, city) VALUES (%s, %s, %s, %s, %s);",
            (depot_id, tenant_id, "North Station", f"DEP-{tenant_id[:4]}", "Chicago"),
        )

        # Fetch an existing vehicle model (from seed)
        cur.execute("SELECT model_id FROM vehicle_models LIMIT 1;")
        model_id = cur.fetchone()[0]

        # Create vehicle
        vehicle_id = str(uuid.uuid4())
        vin = f"1TEST{uuid.uuid4().hex[:12].upper()}"
        cur.execute(
            """
            INSERT INTO vehicles (vehicle_id, vin, tenant_id, fleet_id, depot_id, model_id, license_plate, manufacture_year, status, initial_odometer_km)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """,
            (vehicle_id, vin, tenant_id, fleet_id, depot_id, model_id, "TEST-999", 2024, "ACTIVE", 1500.0),
        )

        # Verify 3NF relational JOIN
        cur.execute(
            """
            SELECT v.vin, v.status, f.name AS fleet_name, d.name AS depot_name, vm.make, vm.model_name
            FROM vehicles v
            JOIN fleets f ON v.fleet_id = f.fleet_id
            JOIN depots d ON v.depot_id = d.depot_id
            JOIN vehicle_models vm ON v.model_id = vm.model_id
            WHERE v.vehicle_id = %s;
            """,
            (vehicle_id,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == vin
        assert row[1] == "ACTIVE"
        assert row[2] == "Express Fleet"
        assert row[3] == "North Station"

    db_conn.rollback()


def test_foreign_key_enforcement_invalid_tenant(db_conn):
    """Attempting to insert a vehicle with a non-existent tenant_id must violate FK constraint."""
    with db_conn.cursor() as cur:
        fake_tenant_id = str(uuid.uuid4())
        cur.execute("SELECT fleet_id FROM fleets LIMIT 1;")
        fleet_id = cur.fetchone()[0]
        cur.execute("SELECT depot_id FROM depots LIMIT 1;")
        depot_id = cur.fetchone()[0]
        cur.execute("SELECT model_id FROM vehicle_models LIMIT 1;")
        model_id = cur.fetchone()[0]

        with pytest.raises(errors.ForeignKeyViolation):
            cur.execute(
                """
                INSERT INTO vehicles (vehicle_id, vin, tenant_id, fleet_id, depot_id, model_id, manufacture_year)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (str(uuid.uuid4()), f"1FKTEST{uuid.uuid4().hex[:10].upper()}", fake_tenant_id, fleet_id, depot_id, model_id, 2024),
            )
    db_conn.rollback()


def test_foreign_key_enforcement_invalid_model(db_conn):
    """Attempting to insert a vehicle with non-existent model_id must fail."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT tenant_id FROM tenants LIMIT 1;")
        tenant_id = cur.fetchone()[0]
        cur.execute("SELECT fleet_id FROM fleets LIMIT 1;")
        fleet_id = cur.fetchone()[0]
        cur.execute("SELECT depot_id FROM depots LIMIT 1;")
        depot_id = cur.fetchone()[0]
        invalid_model_id = 999999

        with pytest.raises(errors.ForeignKeyViolation):
            cur.execute(
                """
                INSERT INTO vehicles (vehicle_id, vin, tenant_id, fleet_id, depot_id, model_id, manufacture_year)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (str(uuid.uuid4()), f"1FKMDL{uuid.uuid4().hex[:11].upper()}", tenant_id, fleet_id, depot_id, invalid_model_id, 2024),
            )
    db_conn.rollback()


def test_unique_constraint_vin(db_conn):
    """Inserting duplicate VIN must raise UniqueViolation."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT vin, tenant_id, fleet_id, depot_id, model_id FROM vehicles LIMIT 1;")
        existing_vin, tenant_id, fleet_id, depot_id, model_id = cur.fetchone()

        with pytest.raises(errors.UniqueViolation):
            cur.execute(
                """
                INSERT INTO vehicles (vehicle_id, vin, tenant_id, fleet_id, depot_id, model_id, manufacture_year)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (str(uuid.uuid4()), existing_vin, tenant_id, fleet_id, depot_id, model_id, 2024),
            )
    db_conn.rollback()


def test_unique_constraint_user_email(db_conn):
    """Inserting duplicate user email must raise UniqueViolation."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT email, tenant_id FROM users LIMIT 1;")
        existing_email, tenant_id = cur.fetchone()

        with pytest.raises(errors.UniqueViolation):
            cur.execute(
                """
                INSERT INTO users (user_id, tenant_id, email, full_name, password_hash)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (str(uuid.uuid4()), tenant_id, existing_email, "Duplicate User", "hash"),
            )
    db_conn.rollback()


def test_check_constraint_vehicle_status(db_conn):
    """Inserting invalid vehicle status must raise CheckViolation."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT tenant_id, fleet_id, depot_id, model_id FROM vehicles LIMIT 1;")
        tenant_id, fleet_id, depot_id, model_id = cur.fetchone()

        with pytest.raises(errors.CheckViolation):
            cur.execute(
                """
                INSERT INTO vehicles (vehicle_id, vin, tenant_id, fleet_id, depot_id, model_id, status, manufacture_year)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (str(uuid.uuid4()), f"1CHK{uuid.uuid4().hex[:13].upper()}", tenant_id, fleet_id, depot_id, model_id, "FLYING_MODE", 2024),
            )
    db_conn.rollback()


def test_pgvector_cosine_similarity_search(db_conn):
    """Verify pgvector 16-D embedding search retrieves expected nearest neighbor using cosine distance."""
    with db_conn.cursor() as cur:
        # Reference test vector: Engine Overheat Anomaly
        # [vib_g, vib_z, vib_ewma, coolant_norm, coolant_z, oil_norm, oil_z, rpm_norm, pack_v_norm, soc_norm, cell_d_norm, cell_d_z, speed_norm, v12_norm, dtc_sev, type_flag]
        query_vector = "[0.64, 2.05, 0.59, 0.86, 3.75, 0.49, -1.15, 0.44, 0.00, 0.00, 0.00, 0.00, 0.54, 0.88, 1.00, 0.00]"

        cur.execute(
            """
            SELECT 
                signature_id,
                fault_type,
                vehicle_type,
                description,
                embedding <=> %s::vector AS cosine_distance
            FROM diagnostic_signatures
            ORDER BY embedding <=> %s::vector
            LIMIT 3;
            """,
            (query_vector, query_vector),
        )
        results = cur.fetchall()
        assert len(results) >= 1
        top_match = results[0]
        signature_id, fault_type, v_type, desc, dist = top_match

        # Top match must be ENGINE_OVERHEAT with distance < 0.01 (cosine similarity > 0.99)
        assert fault_type == "ENGINE_OVERHEAT", f"Expected ENGINE_OVERHEAT, got {fault_type}"
        assert v_type == "ICE"
        assert dist < 0.01, f"Expected cosine distance < 0.01, got {dist}"

        # Ranking order: distance of subsequent matches must be >= top match
        for r in results[1:]:
            assert r[4] >= dist
    db_conn.rollback()
