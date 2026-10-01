"""
FleetGuard Pulse - ClickHouse Analytical Query Benchmark.
Measures execution latency, server processing metrics, and row throughput
for all 5 core historical batch analytics OLAP queries.
"""

from datetime import datetime, timezone, timedelta
import os
import sys
import time
import clickhouse_connect
import psycopg2

sys.path.insert(0, os.path.abspath("."))

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5433"))
PG_DB = os.getenv("POSTGRES_DB", "fleetguard")
PG_USER = os.getenv("POSTGRES_USER", "fleetguard_user")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "fleetguard_dev_password")

CH_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CH_PORT = int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123"))
CH_USER = os.getenv("CLICKHOUSE_USER", "default")
CH_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "fleetguard_dev_password")
CH_DB = os.getenv("CLICKHOUSE_DB", "fleetguard_analytics")

METRO_TENANT_ID = "a0000000-0000-0000-0000-000000000001"

from services.analytics.queries import (
    DEGRADATION_RANKING_SQL,
    FAULT_FREQUENCY_SQL,
    FLEET_RELIABILITY_SUMMARY_SQL,
    MTBF_SQL,
    RELIABILITY_TREND_DAY_SQL,
)


def run_benchmark():
    pg_conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD
    )
    with pg_conn.cursor() as cur:
        cur.execute("SELECT vin FROM vehicles WHERE tenant_id = %s;", (METRO_TENANT_ID,))
        vins = [r[0] for r in cur.fetchall()]
    pg_conn.close()

    ch_client = clickhouse_connect.get_client(
        host=CH_HOST,
        port=CH_PORT,
        username=CH_USER,
        password=CH_PASSWORD,
        database=CH_DB,
        settings={"max_query_size": 10485760},
    )

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=30)
    end_time = now

    queries = {
        "Fleet Reliability Summary": (FLEET_RELIABILITY_SUMMARY_SQL, {"vins": tuple(vins), "start_time": start_time, "end_time": end_time}),
        "Fault Frequency Breakdown": (FAULT_FREQUENCY_SQL, {"vins": tuple(vins), "start_time": start_time, "end_time": end_time}),
        "Mean Time Between Failures (MTBF)": (MTBF_SQL, {"vins": tuple(vins), "start_time": start_time, "end_time": end_time}),
        "Reliability Daily Trend": (RELIABILITY_TREND_DAY_SQL, {"vins": tuple(vins), "start_time": start_time, "end_time": end_time}),
        "Vehicle Degradation Ranking": (DEGRADATION_RANKING_SQL, {"vins": tuple(vins), "start_time": start_time, "end_time": end_time, "limit": 10}),
    }

    results = {}
    total_rows = ch_client.command("SELECT count() FROM vehicle_telemetry")
    print("=" * 78)
    print("FLEETGUARD PULSE — LOCAL CLICKHOUSE QUERY BENCHMARK")
    print("Note: Measures local ClickHouse OLAP query execution; NOT distributed throughput.")
    print(f"Tenant: Metro Transit ({len(vins):,} scoped vehicles)")
    print(f"Dataset: {total_rows} physical rows in vehicle_telemetry")
    print(f"Time Window: {start_time.isoformat()} to {end_time.isoformat()}")
    print("=" * 78)

    # Warmup
    for name, (sql, params) in queries.items():
        ch_client.query(sql, parameters=params, settings={"max_query_size": 10485760})

    # Benchmark 20 iterations
    ITERATIONS = 20
    for name, (sql, params) in queries.items():
        durations = []
        rows_processed_list = []
        result_rows_count = 0

        for _ in range(ITERATIONS):
            t0 = time.perf_counter()
            res = ch_client.query(sql, parameters=params, settings={"max_query_size": 10485760})
            t1 = time.perf_counter()
            durations.append((t1 - t0) * 1000.0)  # ms
            result_rows_count = len(res.result_rows) if res.result_rows else 0
            if hasattr(res, "summary") and res.summary:
                rows_processed_list.append(int(res.summary.get("read_rows", 0)))

        durations.sort()
        mean_ms = sum(durations) / len(durations)
        p50_ms = durations[len(durations) // 2]
        p95_ms = durations[int(len(durations) * 0.95)]
        p99_ms = durations[-1]
        avg_read_rows = sum(rows_processed_list) / len(rows_processed_list) if rows_processed_list else 0

        results[name] = {
            "mean_ms": round(mean_ms, 2),
            "p50_ms": round(p50_ms, 2),
            "p95_ms": round(p95_ms, 2),
            "p99_ms": round(p99_ms, 2),
            "result_rows": result_rows_count,
            "read_rows": avg_read_rows,
        }

        print(f"\nQuery: {name}")
        print(f"  Result Rows:     {result_rows_count}")
        print(f"  Rows Processed:  {avg_read_rows:,.0f}")
        print(f"  Latency (20 iters): Mean={mean_ms:.2f}ms | p50={p50_ms:.2f}ms | p95={p95_ms:.2f}ms | p99={p99_ms:.2f}ms")

    print("\n" + "=" * 78)
    ch_client.close()
    return results


if __name__ == "__main__":
    run_benchmark()
