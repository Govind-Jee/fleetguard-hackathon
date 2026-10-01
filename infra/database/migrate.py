"""
FleetGuard Pulse - Database Migration Runner

Applies versioned SQL migrations in alphabetical order to PostgreSQL.
Tracks applied versions in the 'schema_migrations' table within atomic transactions.
"""

import os
from pathlib import Path
import sys
from typing import Dict, List, Optional
import psycopg2

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def get_connection_params(config: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Retrieve database connection parameters from environment or config dictionary."""
    cfg = config or {}
    return {
        "host": cfg.get("host") or os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(cfg.get("port") or os.getenv("POSTGRES_PORT", "5433")),
        "dbname": cfg.get("dbname") or os.getenv("POSTGRES_DB", "fleetguard"),
        "user": cfg.get("user") or os.getenv("POSTGRES_USER", "fleetguard_user"),
        "password": cfg.get("password") or os.getenv("POSTGRES_PASSWORD", "fleetguard_dev_password"),
    }


def get_connection(config: Optional[Dict[str, str]] = None):
    params = get_connection_params(config)
    return psycopg2.connect(**params)


def init_migration_table(conn) -> None:
    """Ensure the schema_migrations tracking table exists."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(100) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    conn.commit()


def get_applied_migrations(conn) -> List[str]:
    """Return sorted list of already applied migration version strings."""
    init_migration_table(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version ASC;")
        rows = cur.fetchall()
        return [r[0] for r in rows]


def run_migrations(config: Optional[Dict[str, str]] = None) -> List[str]:
    """
    Execute all pending migrations in atomic transactions.

    Returns:
        List of newly applied migration file names.
    """
    conn = get_connection(config)
    applied_now: List[str] = []

    try:
        init_migration_table(conn)
        applied = set(get_applied_migrations(conn))

        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        if not migration_files:
            print(f"No SQL migration files found in {MIGRATIONS_DIR}")
            return []

        for file_path in migration_files:
            version = file_path.name
            if version in applied:
                continue

            print(f"Applying migration: {version}...")
            with open(file_path, "r", encoding="utf-8") as f:
                sql_content = f.read()

            with conn.cursor() as cur:
                cur.execute(sql_content)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s);",
                    (version,),
                )
            conn.commit()
            applied_now.append(version)
            print(f"  ✓ Applied {version} successfully.")

    except Exception as e:
        conn.rollback()
        print(f"Migration error during execution: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()

    return applied_now


if __name__ == "__main__":
    applied = run_migrations()
    print(f"Migration run finished. Newly applied: {len(applied)} migrations.")
