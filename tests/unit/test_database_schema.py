"""
Unit tests for FleetGuard Pulse relational database schema, migrations, and design specifications.
Validates migration scripts and documentation integrity without requiring live database connections.
"""

from pathlib import Path
import unittest


class TestDatabaseSchemaUnit(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2]
        self.migrations_dir = self.root / "infra" / "database" / "migrations"

    def test_migration_files_exist(self):
        expected_migrations = [
            "001_initial_relational_schema.sql",
            "002_pgvector_signatures.sql",
            "003_seed_dev_data.sql",
        ]
        for mig in expected_migrations:
            file_path = self.migrations_dir / mig
            self.assertTrue(file_path.is_file(), f"Migration file {mig} missing")

    def test_schema_defines_13_domain_tables(self):
        migration_001 = (self.migrations_dir / "001_initial_relational_schema.sql").read_text()
        required_tables = [
            "tenants",
            "fleets",
            "depots",
            "vehicle_models",
            "vehicles",
            "maintenance_types",
            "maintenance_records",
            "work_orders",
            "alerts",
            "users",
            "roles",
            "user_roles",
            "audit_logs",
        ]
        for tbl in required_tables:
            self.assertIn(
                f"CREATE TABLE IF NOT EXISTS {tbl}",
                migration_001,
                f"Table {tbl} not created in 001_initial_relational_schema.sql",
            )

    def test_foreign_key_and_constraint_definitions(self):
        migration_001 = (self.migrations_dir / "001_initial_relational_schema.sql").read_text()
        # Verify FKs
        self.assertIn("REFERENCES tenants(tenant_id) ON DELETE CASCADE", migration_001)
        self.assertIn("REFERENCES fleets(fleet_id) ON DELETE RESTRICT", migration_001)
        self.assertIn("REFERENCES depots(depot_id) ON DELETE RESTRICT", migration_001)
        self.assertIn("REFERENCES vehicle_models(model_id) ON DELETE RESTRICT", migration_001)
        self.assertIn("REFERENCES vehicles(vehicle_id) ON DELETE CASCADE", migration_001)
        self.assertIn("REFERENCES maintenance_types(type_id) ON DELETE RESTRICT", migration_001)
        self.assertIn("REFERENCES users(user_id) ON DELETE SET NULL", migration_001)

        # Verify Unique constraints
        self.assertIn("vin VARCHAR(17) NOT NULL UNIQUE", migration_001)
        self.assertIn("email VARCHAR(255) NOT NULL UNIQUE", migration_001)
        self.assertIn("name VARCHAR(255) NOT NULL UNIQUE", migration_001)
        self.assertIn("role_name VARCHAR(50) NOT NULL UNIQUE", migration_001)

        # Verify Composite dispatch index
        self.assertIn("idx_work_orders_composite_dispatch", migration_001)
        self.assertIn("(tenant_id, status, priority, scheduled_at)", migration_001)

    def test_pgvector_migration_definition(self):
        migration_002 = (self.migrations_dir / "002_pgvector_signatures.sql").read_text()
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector;", migration_002)
        self.assertIn("CREATE TABLE IF NOT EXISTS diagnostic_signatures", migration_002)
        self.assertIn("embedding vector(16) NOT NULL", migration_002)
        self.assertIn("USING hnsw (embedding vector_cosine_ops)", migration_002)
        self.assertIn("WITH (m = 16, ef_construction = 64)", migration_002)

    def test_seed_migration_contains_required_entities_and_vectors(self):
        migration_003 = (self.migrations_dir / "003_seed_dev_data.sql").read_text()
        self.assertIn("INSERT INTO tenants", migration_003)
        self.assertIn("INSERT INTO fleets", migration_003)
        self.assertIn("INSERT INTO depots", migration_003)
        self.assertIn("INSERT INTO vehicle_models", migration_003)
        self.assertIn("INSERT INTO vehicles", migration_003)
        self.assertIn("INSERT INTO maintenance_types", migration_003)
        self.assertIn("INSERT INTO roles", migration_003)
        self.assertIn("INSERT INTO users", migration_003)
        self.assertIn("INSERT INTO user_roles", migration_003)
        self.assertIn("INSERT INTO diagnostic_signatures", migration_003)
        
        # Verify at least 5 distinct failure modes seeded
        failure_modes = [
            "ENGINE_OVERHEAT",
            "OIL_PRESSURE_CRITICAL_LOW",
            "BATTERY_THERMAL_RUNAWAY_RISK",
            "BATTERY_CELL_IMBALANCE",
            "EXCESSIVE_VIBRATION",
            "INVERTER_DEGRADATION",
        ]
        for mode in failure_modes:
            self.assertIn(mode, migration_003)

    def test_documentation_files_exist_and_cover_requirements(self):
        db_doc = self.root / "docs" / "database-design.md"
        opt_doc = self.root / "docs" / "sql-optimization.md"
        self.assertTrue(db_doc.is_file(), "docs/database-design.md missing")
        self.assertTrue(opt_doc.is_file(), "docs/sql-optimization.md missing")

        db_text = db_doc.read_text()
        self.assertIn("erDiagram", db_text)
        self.assertIn("First Normal Form (1NF)", db_text)
        self.assertIn("Second Normal Form (2NF)", db_text)
        self.assertIn("Third Normal Form (3NF)", db_text)
        self.assertIn("vehicle_models", db_text)
        self.assertIn("maintenance_types", db_text)
        self.assertIn("user_roles", db_text)
        self.assertIn("audit_logs", db_text)
        self.assertIn("diagnostic_signatures", db_text)

        opt_text = opt_doc.read_text()
        self.assertIn("EXPLAIN (ANALYZE, BUFFERS)", opt_text)
        self.assertIn("idx_work_orders_composite_dispatch", opt_text)
        self.assertIn("Unoptimized Execution Plan", opt_text)
        self.assertIn("Optimized Execution Plan", opt_text)


if __name__ == "__main__":
    unittest.main()
