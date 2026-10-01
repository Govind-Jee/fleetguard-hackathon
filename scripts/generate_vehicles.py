#!/usr/bin/env python3
"""
FleetGuard Pulse - Reproducible Seed Vehicle Dataset Generator

Generates a deterministic dataset of at least 100,000 synthetic commercial vehicles
spanning ICE, HEV, and BEV powertrains. Contains zero real personal or vehicle-owner PII.
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure root directory is on PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.simulator.generator import generate_seed_vehicle_dataset


def main():
    parser = argparse.ArgumentParser(description="Generate FleetGuard Pulse 100K Vehicle Seed Dataset")
    parser.add_argument("--count", type=int, default=100000, help="Number of vehicles (default: 100000)")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed (default: 42)")
    parser.add_argument("--output", type=str, default="data/seed/vehicles.csv", help="Output path")
    args = parser.parse_args()

    print(f"Generating {args.count:,} synthetic vehicles into {args.output} with seed {args.seed}...")
    start_time = time.perf_counter()
    total = generate_seed_vehicle_dataset(output_path=args.output, count=args.count, seed=args.seed)
    elapsed = time.perf_counter() - start_time
    print(f"Successfully generated {total:,} vehicles in {elapsed:.2f} seconds ({total / max(elapsed, 0.001):,.0f} vehicles/sec).")


if __name__ == "__main__":
    main()
