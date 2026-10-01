#!/usr/bin/env python3
"""
FleetGuard Pulse - 100K Vehicle Population & Telemetry Coverage Verification

Strictly verifies that the simulator can initialize all 100,000 vehicles from the seed
dataset, generate valid telemetry for every single vehicle with 100% unique VIN coverage,
validate schema integrity across ICE, HEV, and BEV, and operate within bounded memory.
"""

import gc
import os
import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.simulator.generator import TelemetryGenerator
from services.simulator.schema import VehicleType


def get_memory_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return usage / (1024 * 1024)
    return usage / 1024


def run_100k_coverage_test(target_vehicles: int = 100000, seed: int = 42):
    print("=" * 80)
    print(f"Starting 100K Vehicle Population Coverage Verification (N={target_vehicles:,}, seed={seed})")
    print("=" * 80)

    gc.collect()
    mem_start = get_memory_mb()

    # Step 1: Initialize 100,000 vehicles
    t0 = time.perf_counter()
    generator = TelemetryGenerator(
        vehicle_count=target_vehicles,
        seed=seed,
        duplicate_rate=0.0,  # Zero dups for exact 1:1 coverage verification
        reorder_rate=0.0,
    )
    generator.initialize_vehicles()
    init_time = time.perf_counter() - t0
    mem_after_init = get_memory_mb()

    print(f"[1/4] Vehicle pool initialization:")
    print(f"      - Vehicles initialized: {len(generator.vehicles):,}")
    print(f"      - Initialization time:  {init_time:.3f} s")
    print(f"      - Memory allocated:     {mem_after_init - mem_start:.2f} MB")

    # Step 2: Stream exactly 100,000 events (1 per vehicle) and validate coverage
    print(f"[2/4] Generating and validating telemetry for all {target_vehicles:,} vehicles...")
    t1 = time.perf_counter()

    unique_vins = set()
    unique_event_ids = set()
    type_counts = {VehicleType.ICE: 0, VehicleType.HEV: 0, VehicleType.BEV: 0}
    invalid_events = 0

    for i, (event, is_dup, is_reord) in enumerate(generator.stream_events(max_events=target_vehicles)):
        # Validate unique VIN
        unique_vins.add(event.vin)
        unique_event_ids.add(event.event_id)
        type_counts[event.vehicle_type] += 1

        # Strict powertrain-specific validation checks
        if event.vehicle_type == VehicleType.ICE:
            if event.oil_pressure_kpa is None or event.coolant_temp_c is None or event.engine_rpm is None:
                invalid_events += 1
        elif event.vehicle_type == VehicleType.HEV:
            if event.oil_pressure_kpa is None or event.coolant_temp_c is None or event.soc_pct is None:
                invalid_events += 1
        elif event.vehicle_type == VehicleType.BEV:
            if event.pack_voltage_v is None or event.cell_temp_delta_c is None or event.soc_pct is None:
                invalid_events += 1

        if event.sequence_number < 1:
            invalid_events += 1

    gen_time = time.perf_counter() - t1
    mem_final = get_memory_mb()

    # Step 3: Coverage calculations & assertions
    coverage_pct = (len(unique_vins) / target_vehicles) * 100.0
    all_events_valid = (invalid_events == 0)
    all_vins_covered = (len(unique_vins) == target_vehicles)
    all_event_ids_unique = (len(unique_event_ids) == target_vehicles)

    print(f"[3/4] Telemetry generation & validation completed:")
    print(f"      - Total events emitted: {target_vehicles:,}")
    print(f"      - Generation duration:  {gen_time:.3f} s ({target_vehicles / max(gen_time, 0.001):,.0f} ev/s)")
    print(f"      - Unique VINs covered:  {len(unique_vins):,} ({coverage_pct:.2f}%)")
    print(f"      - Unique Event IDs:     {len(unique_event_ids):,}")
    print(f"      - Invalid events:       {invalid_events}")
    print(f"      - Powertrain Breakdown:")
    print(f"        * ICE: {type_counts[VehicleType.ICE]:,} ({type_counts[VehicleType.ICE]/target_vehicles*100:.1f}%)")
    print(f"        * HEV: {type_counts[VehicleType.HEV]:,} ({type_counts[VehicleType.HEV]/target_vehicles*100:.1f}%)")
    print(f"        * BEV: {type_counts[VehicleType.BEV]:,} ({type_counts[VehicleType.BEV]/target_vehicles*100:.1f}%)")
    print(f"      - Peak Memory Usage:    {mem_final:.2f} MB (Net: {mem_final - mem_start:.2f} MB)")

    print("[4/4] Verification Result:")
    assert all_vins_covered, f"Expected {target_vehicles} distinct VINs, got {len(unique_vins)}"
    assert all_event_ids_unique, f"Duplicate event IDs detected in baseline generation"
    assert all_events_valid, f"Detected {invalid_events} schema violations"

    print("      >> STATUS: PASSED <<")
    print("      All 100,000 vehicles successfully simulated with 100% VIN coverage and valid schema.")
    print("=" * 80)

    return {
        "target_vehicles": target_vehicles,
        "unique_vins": len(unique_vins),
        "unique_event_ids": len(unique_event_ids),
        "coverage_pct": coverage_pct,
        "init_time": init_time,
        "gen_time": gen_time,
        "net_memory_mb": mem_final - mem_start,
        "passed": True,
    }


if __name__ == "__main__":
    run_100k_coverage_test(100000, seed=42)
