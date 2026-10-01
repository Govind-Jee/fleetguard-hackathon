"""
FleetGuard Pulse - ClickHouse Analytical Query Templates.
Aggregates historical vehicle telemetry into reliability metrics,
fault frequency breakdowns, MTBF distributions, trends, and degradation rankings.
Uses ReplacingMergeTree FINAL and vector aggregations.
"""

# Categorical fault detection conditions aligned with domain rules
CRITICAL_FAULT_COND = """
(hasAny(dtc_codes, ['P0217', 'P0524', 'P0A80', 'P0A78', 'P0300', 'P0A1F'])
 OR coolant_temp_c >= 115.0
 OR (oil_pressure_kpa <= 80.0 AND engine_rpm > 500)
 OR cell_temp_delta_c >= 8.0
 OR vibration >= 4.0
 OR (vehicle_type = 'BEV' AND soc_pct <= 5.0))
"""

FAULT_COND = """
(length(dtc_codes) > 0
 OR coolant_temp_c >= 105.0
 OR (oil_pressure_kpa <= 150.0 AND engine_rpm > 500)
 OR cell_temp_delta_c >= 5.0
 OR vibration >= 2.0
 OR (vehicle_type = 'BEV' AND soc_pct <= 15.0))
"""


FLEET_RELIABILITY_SUMMARY_SQL = f"""
SELECT
    uniqExact(vin) AS monitored_vehicles,
    count() AS total_events,
    countIf({CRITICAL_FAULT_COND}) AS critical_faults,
    countIf({FAULT_COND}) AS fault_events,
    uniqExactIf(vin, {FAULT_COND}) AS affected_vehicles
FROM vehicle_telemetry FINAL
WHERE vin IN %(vins)s AND timestamp >= %(start_time)s AND timestamp <= %(end_time)s
"""


FAULT_FREQUENCY_SQL = f"""
WITH dtc_faults AS (
    SELECT 
        arrayJoin(dtc_codes) AS fault_type,
        vin
    FROM vehicle_telemetry FINAL
    WHERE vin IN %(vins)s AND timestamp >= %(start_time)s AND timestamp <= %(end_time)s
          AND length(dtc_codes) > 0
),
physical_faults AS (
    SELECT 
        arrayJoin(
            arrayFilter(x -> x != '', [
                if(coolant_temp_c >= 115.0, 'ENGINE_OVERHEAT', if(coolant_temp_c >= 105.0, 'COOLANT_TEMP_HIGH', '')),
                if(oil_pressure_kpa <= 80.0 AND engine_rpm > 500, 'OIL_PRESSURE_CRITICAL_LOW', if(oil_pressure_kpa <= 150.0 AND engine_rpm > 500, 'OIL_PRESSURE_LOW', '')),
                if(cell_temp_delta_c >= 8.0, 'BATTERY_THERMAL_RUNAWAY_RISK', if(cell_temp_delta_c >= 5.0, 'BATTERY_CELL_IMBALANCE', '')),
                if(vibration >= 4.0, 'EXCESSIVE_VIBRATION', if(vibration >= 2.0, 'ELEVATED_VIBRATION', '')),
                if(vehicle_type = 'BEV' AND soc_pct <= 5.0, 'CRITICAL_LOW_SOC', if(vehicle_type = 'BEV' AND soc_pct <= 15.0, 'LOW_BATTERY_SOC', ''))
            ])
        ) AS fault_type,
        vin
    FROM vehicle_telemetry FINAL
    WHERE vin IN %(vins)s AND timestamp >= %(start_time)s AND timestamp <= %(end_time)s
),
all_faults AS (
    SELECT fault_type, vin FROM dtc_faults
    UNION ALL
    SELECT fault_type, vin FROM physical_faults
)
SELECT 
    fault_type,
    count() AS occurrence_count,
    uniqExact(vin) AS affected_vehicle_count
FROM all_faults
WHERE fault_type != ''
GROUP BY fault_type
ORDER BY occurrence_count DESC
"""


MTBF_SQL = f"""
WITH raw_failures AS (
    SELECT 
        vin,
        timestamp,
        if(row_number() OVER (PARTITION BY vin ORDER BY timestamp) = 1, NULL,
           dateDiff('second', lagInFrame(timestamp) OVER (PARTITION BY vin ORDER BY timestamp), timestamp)) AS diff_prev_sec
    FROM vehicle_telemetry FINAL
    WHERE vin IN %(vins)s AND timestamp >= %(start_time)s AND timestamp <= %(end_time)s
          AND ({CRITICAL_FAULT_COND})
),
distinct_incidents AS (
    SELECT 
        vin,
        timestamp,
        if(row_number() OVER (PARTITION BY vin ORDER BY timestamp) = 1, NULL,
           dateDiff('second', lagInFrame(timestamp) OVER (PARTITION BY vin ORDER BY timestamp), timestamp)) AS tbf_sec
    FROM raw_failures
    WHERE diff_prev_sec IS NULL OR diff_prev_sec > 1800
),
operating_span AS (
    SELECT 
        coalesce(sum(dateDiff('second', min_ts, max_ts)) / 3600.0, 0.0) AS total_operating_hours,
        uniqExact(vin) AS vehicles_evaluated
    FROM (
        SELECT vin, min(timestamp) AS min_ts, max(timestamp) AS max_ts
        FROM vehicle_telemetry FINAL
        WHERE vin IN %(vins)s AND timestamp >= %(start_time)s AND timestamp <= %(end_time)s
        GROUP BY vin
    )
)
SELECT 
    count() AS total_incidents,
    countIf(tbf_sec IS NOT NULL) AS intervals_count,
    avg(tbf_sec) / 3600.0 AS mean_mtbf_hours,
    median(tbf_sec) / 3600.0 AS median_mtbf_hours,
    min(tbf_sec) / 3600.0 AS min_tbf_hours,
    max(tbf_sec) / 3600.0 AS max_tbf_hours,
    any(o.total_operating_hours) AS total_operating_hours,
    any(o.vehicles_evaluated) AS vehicles_evaluated
FROM distinct_incidents
CROSS JOIN operating_span o
"""


RELIABILITY_TREND_DAY_SQL = f"""
SELECT 
    toString(toDate(timestamp)) AS period,
    uniqExact(vin) AS vehicles_observed,
    count() AS telemetry_events,
    countIf({CRITICAL_FAULT_COND}) AS failure_events,
    round(countIf({CRITICAL_FAULT_COND}) / nullIf(count(), 0), 4) AS fault_rate
FROM vehicle_telemetry FINAL
WHERE vin IN %(vins)s AND timestamp >= %(start_time)s AND timestamp <= %(end_time)s
GROUP BY period
ORDER BY period ASC
"""

RELIABILITY_TREND_WEEK_SQL = f"""
SELECT 
    toString(toMonday(timestamp)) AS period,
    uniqExact(vin) AS vehicles_observed,
    count() AS telemetry_events,
    countIf({CRITICAL_FAULT_COND}) AS failure_events,
    round(countIf({CRITICAL_FAULT_COND}) / nullIf(count(), 0), 4) AS fault_rate
FROM vehicle_telemetry FINAL
WHERE vin IN %(vins)s AND timestamp >= %(start_time)s AND timestamp <= %(end_time)s
GROUP BY period
ORDER BY period ASC
"""


DEGRADATION_RANKING_SQL = f"""
SELECT 
    vin,
    vehicle_type,
    count() AS telemetry_events,
    countIf({FAULT_COND}) AS fault_events,
    countIf({CRITICAL_FAULT_COND}) AS critical_faults,
    round(avg(vibration), 2) AS avg_vibration,
    round(max(vibration), 2) AS max_vibration,
    round(avg(coolant_temp_c), 1) AS avg_coolant_temp,
    round(min(oil_pressure_kpa), 1) AS min_oil_pressure,
    round(avg(cell_temp_delta_c), 1) AS avg_cell_temp_delta,
    least(100.0, round(
        35.0 * countIf({CRITICAL_FAULT_COND}) 
        + 10.0 * (countIf({FAULT_COND}) - countIf({CRITICAL_FAULT_COND})) 
        + 15.0 * least(3.0, max(vibration) / 2.0)
    , 1)) AS degradation_score
FROM vehicle_telemetry FINAL
WHERE vin IN %(vins)s AND timestamp >= %(start_time)s AND timestamp <= %(end_time)s
GROUP BY vin, vehicle_type
ORDER BY degradation_score DESC, critical_faults DESC, fault_events DESC, vin ASC
LIMIT %(limit)s
"""
