"""
FleetGuard Pulse - SQL Optimization Benchmark & EXPLAIN ANALYZE Comparison

Executes an empirical EXPLAIN (ANALYZE, BUFFERS) comparison on PostgreSQL:
1. Seeds a representative dataset of 10,000 vehicles and 25,000 work orders.
2. Runs the critical fleet dispatch query WITHOUT composite index (Sequential Scan).
3. Adds the targeted composite index: (tenant_id, status, priority).
4. Runs the query WITH the index (Index Scan).
5. Outputs raw EXPLAIN plans, buffer hits, and execution times.
"""

import time
import psycopg2


def run_benchmark():
    conn = psycopg2.connect(
        host="localhost",
        port=5433,
        dbname="fleetguard",
        user="fleetguard_user",
        password="fleetguard_dev_password",
    )
    conn.autocommit = True
    cur = conn.cursor()

    print("=" * 70)
    print("FLEETGUARD PULSE - SQL OPTIMIZATION EXPLAIN ANALYZE BENCHMARK")
    print("=" * 70)

    # Step 1: Populate synthetic vehicles and work orders if needed
    cur.execute("SELECT count(*) FROM vehicles WHERE tenant_id = 'a0000000-0000-0000-0000-000000000001';")
    veh_count = cur.fetchone()[0]

    if veh_count < 5000:
        print("Generating 10,000 vehicles for benchmark...")
        cur.execute("""
        INSERT INTO vehicles (vin, tenant_id, fleet_id, depot_id, model_id, license_plate, manufacture_year, status, initial_odometer_km)
        SELECT 
            'BENCHVIN' || lpad(i::text, 9, '0'),
            'a0000000-0000-0000-0000-000000000001'::uuid,
            'd0000000-0000-0000-0000-000000000001'::uuid,
            'c0000000-0000-0000-0000-000000000001'::uuid,
            ((i % 6) + 1),
            'IL-BCH-' || i::text,
            2020 + (i % 5),
            CASE WHEN i % 10 = 0 THEN 'MAINTENANCE' ELSE 'ACTIVE' END,
            (i * 12.5)
        FROM generate_series(100, 10099) AS i
        ON CONFLICT (vin) DO NOTHING;
        """)

    cur.execute("SELECT count(*) FROM work_orders WHERE tenant_id = 'a0000000-0000-0000-0000-000000000001';")
    wo_count = cur.fetchone()[0]

    if wo_count < 10000:
        print("Generating 25,000 work orders for benchmark...")
        cur.execute("""
        INSERT INTO work_orders (tenant_id, vehicle_id, type_id, priority, status, scheduled_at)
        SELECT 
            'a0000000-0000-0000-0000-000000000001'::uuid,
            v.vehicle_id,
            ((i % 6) + 1),
            CASE 
                WHEN i % 20 = 0 THEN 'CRITICAL'
                WHEN i % 5 = 0 THEN 'HIGH'
                WHEN i % 2 = 0 THEN 'MEDIUM'
                ELSE 'LOW'
            END,
            CASE 
                WHEN i % 15 = 0 THEN 'IN_PROGRESS'
                WHEN i % 4 = 0 THEN 'SCHEDULED'
                WHEN i % 2 = 0 THEN 'COMPLETED'
                ELSE 'PENDING'
            END,
            NOW() - (i || ' hours')::interval
        FROM generate_series(1, 25000) AS i
        CROSS JOIN LATERAL (
            SELECT vehicle_id FROM vehicles 
            WHERE tenant_id = 'a0000000-0000-0000-0000-000000000001' 
            ORDER BY vehicle_id LIMIT 1 OFFSET (i % 1000)
        ) v;
        """)

    # Target Query: Critical Dispatch Query
    query = """
    EXPLAIN (ANALYZE, BUFFERS)
    SELECT 
        wo.work_order_id,
        wo.vehicle_id,
        v.vin,
        v.license_plate,
        mt.name AS maintenance_type_name,
        wo.priority,
        wo.status,
        wo.scheduled_at
    FROM work_orders wo
    JOIN vehicles v ON wo.vehicle_id = v.vehicle_id
    JOIN maintenance_types mt ON wo.type_id = mt.type_id
    WHERE wo.tenant_id = 'a0000000-0000-0000-0000-000000000001'
      AND wo.status = 'IN_PROGRESS'
      AND wo.priority = 'CRITICAL'
    ORDER BY wo.scheduled_at ASC;
    """

    # Step 2: Ensure any composite index is dropped for UNOPTIMIZED test
    cur.execute("DROP INDEX IF EXISTS idx_work_orders_tenant_status_priority;")
    cur.execute("DROP INDEX IF EXISTS idx_work_orders_composite_dispatch;")
    cur.execute("VACUUM ANALYZE work_orders;")
    cur.execute("VACUUM ANALYZE vehicles;")

    print("\n" + "=" * 70)
    print("1. EXPLAIN (ANALYZE, BUFFERS) - UNOPTIMIZED (NO COMPOSITE INDEX)")
    print("=" * 70)
    cur.execute(query)
    unoptimized_lines = [r[0] for r in cur.fetchall()]
    unoptimized_output = "\n".join(unoptimized_lines)
    print(unoptimized_output)

    # Step 3: Create the Targeted Composite Index
    print("\nCreating Composite Index: idx_work_orders_composite_dispatch ON work_orders(tenant_id, status, priority, scheduled_at)...")
    cur.execute("""
    CREATE INDEX idx_work_orders_composite_dispatch 
    ON work_orders (tenant_id, status, priority, scheduled_at);
    """)
    cur.execute("VACUUM ANALYZE work_orders;")

    # Step 4: Run EXPLAIN (ANALYZE, BUFFERS) - OPTIMIZED
    print("\n" + "=" * 70)
    print("2. EXPLAIN (ANALYZE, BUFFERS) - OPTIMIZED (WITH COMPOSITE INDEX)")
    print("=" * 70)
    cur.execute(query)
    optimized_lines = [r[0] for r in cur.fetchall()]
    optimized_output = "\n".join(optimized_lines)
    print(optimized_output)

    # Save outputs to scratch or doc
    cur.close()
    conn.close()

    return unoptimized_output, optimized_output


if __name__ == "__main__":
    run_benchmark()
