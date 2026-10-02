"""
FleetGuard Pulse - Datastore Connection Management & Pooling.
Provides thread-safe connection pools for PostgreSQL 16 (psycopg2 ThreadedConnectionPool),
Redis 7, and ClickHouse.
"""

import logging
from contextlib import contextmanager
from typing import Generator, Optional
import psycopg2
from psycopg2.pool import PoolError, ThreadedConnectionPool
import redis
import clickhouse_connect
import time

from services.api.config import settings
from services.api.exceptions import DatabaseUnavailableError
from services.api.metrics import api_metrics

logger = logging.getLogger("fleetguard.api.db")

# Thread-safe global singletons
_pg_pool: Optional[ThreadedConnectionPool] = None
_redis_client: Optional[redis.Redis] = None
_clickhouse_client = None


def init_db_pools() -> None:
    """Initialize connection pools on application startup."""
    global _pg_pool, _redis_client, _clickhouse_client

    # 1. PostgreSQL Pool
    try:
        _pg_pool = ThreadedConnectionPool(
            minconn=settings.POSTGRES_POOL_MIN,
            maxconn=settings.POSTGRES_POOL_MAX,
            **settings.postgres_connection_dict,
        )
        logger.info(
            "PostgreSQL connection pool initialized (min=%d, max=%d, db=%s)",
            settings.POSTGRES_POOL_MIN,
            settings.POSTGRES_POOL_MAX,
            settings.POSTGRES_DB,
        )
    except Exception as e:
        logger.error("Failed to initialize PostgreSQL pool: %s", e)
        api_metrics.record_db_error("postgres")
        # Do not crash immediately so healthcheck can report degraded status

    # 2. Redis Connection
    try:
        _redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            db=settings.REDIS_DB,
            decode_responses=True,
            socket_timeout=3.0,
            socket_connect_timeout=3.0,
        )
        _redis_client.ping()
        logger.info("Redis connection established on %s:%d", settings.REDIS_HOST, settings.REDIS_PORT)
    except Exception as e:
        logger.error("Failed to connect to Redis: %s", e)
        api_metrics.record_db_error("redis")

    # 3. ClickHouse Client
    try:
        _clickhouse_client = clickhouse_connect.get_client(
            host=settings.CLICKHOUSE_HOST,
            port=settings.CLICKHOUSE_PORT,
            username=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD,
            database=settings.CLICKHOUSE_DB,
            connect_timeout=3,
            send_receive_timeout=5,
            settings={"max_query_size": 10485760},
        )
        logger.info(
            "ClickHouse client connected on %s:%d (db=%s)",
            settings.CLICKHOUSE_HOST,
            settings.CLICKHOUSE_PORT,
            settings.CLICKHOUSE_DB,
        )
    except Exception as e:
        logger.warning("ClickHouse connection skipped/unavailable: %s", e)


def close_db_pools() -> None:
    """Safely drain and close all connection pools on shutdown."""
    global _pg_pool, _redis_client, _clickhouse_client
    if _pg_pool:
        try:
            _pg_pool.closeall()
            logger.info("PostgreSQL connection pool closed.")
        except Exception as e:
            logger.error("Error closing PostgreSQL pool: %s", e)
        finally:
            _pg_pool = None

    if _redis_client:
        try:
            _redis_client.close()
            logger.info("Redis connection closed.")
        except Exception as e:
            logger.error("Error closing Redis client: %s", e)
        finally:
            _redis_client = None

    if _clickhouse_client:
        try:
            _clickhouse_client.close()
        except Exception:
            pass
        finally:
            _clickhouse_client = None


@contextmanager
def get_db_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Context manager that checks out a connection from PostgreSQL pool,
    commits on success, rolls back on error, and returns it to the pool.
    """
    global _pg_pool
    if _pg_pool is None or getattr(_pg_pool, "closed", False):
        init_db_pools()

    if _pg_pool is None:
        api_metrics.record_db_error("postgres")
        raise DatabaseUnavailableError("PostgreSQL")

    conn = None
    start_wait = time.perf_counter()
    timeout = 2.0  # seconds bounded queue wait for pool exhaustion
    while conn is None:
        try:
            conn = _pg_pool.getconn()
        except PoolError:
            if time.perf_counter() - start_wait >= timeout:
                api_metrics.record_db_error("postgres")
                raise
            time.sleep(0.005)

    try:
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        api_metrics.record_db_error("postgres")
        raise
    finally:
        if conn and _pg_pool:
            _pg_pool.putconn(conn)


def get_redis_client() -> redis.Redis:
    """Return active Redis client singleton."""
    global _redis_client
    if _redis_client is None:
        init_db_pools()
    if _redis_client is None:
        api_metrics.record_db_error("redis")
        raise DatabaseUnavailableError("Redis")
    return _redis_client


def get_clickhouse_client():
    """Return active ClickHouse client or None if offline."""
    global _clickhouse_client
    return _clickhouse_client


def check_postgres_health() -> bool:
    """Lightweight health probe for PostgreSQL."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                return cur.fetchone()[0] == 1
    except Exception:
        return False


def check_redis_health() -> bool:
    """Lightweight health probe for Redis."""
    try:
        r = get_redis_client()
        return bool(r.ping())
    except Exception:
        return False


def check_clickhouse_health() -> bool:
    """Lightweight health probe for ClickHouse."""
    try:
        ch = get_clickhouse_client()
        if ch:
            return bool(ch.ping())
        return False
    except Exception:
        return False
