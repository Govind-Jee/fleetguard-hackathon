#!/usr/bin/env python3
"""
Scale and memory benchmark for FleetGuard Pulse Simulator (F-01).

Measures startup time, in-memory footprint, and event generation rate
across 10K, 50K, and 100K vehicle pools.
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


def get_memory_mb() -> float:
    # ru_maxrss is in bytes on macOS Darwin, kilobytes on Linux
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return usage / (1024 * 1024)
    return usage / 1024


def benchmark_scale(vehicle_count: int, test_events: int = 20000):
    gc.collect()
    mem_before = get_memory_mb()

    # 1. Measure startup / initialization time
    t0 = time.perf_counter()
    generator = TelemetryGenerator(
        vehicle_count=vehicle_count,
        seed=42,
        duplicate_rate=0.01,
        reorder_rate=0.02,
    )
    generator.initialize_vehicles()
    startup_time = time.perf_counter() - t0

    mem_after = get_memory_mb()
    net_mem_mb = max(0.0, mem_after - mem_before)

    # 2. Measure throughput (events generated per second)
    t1 = time.perf_counter()
    emitted = 0
    for event, is_dup, is_reord in generator.stream_events(max_events=test_events):
        emitted += 1
    gen_time = time.perf_counter() - t1
    event_rate = emitted / max(gen_time, 0.001)

    print(
        f"| {vehicle_count:>7,d} | {startup_time:>11.3f} s | {net_mem_mb:>10.2f} MB | "
        f"{emitted:>11,d} | {gen_time:>10.3f} s | {event_rate:>13,.0f} ev/s |"
    )

    return {
        "vehicle_count": vehicle_count,
        "startup_time": startup_time,
        "memory_mb": net_mem_mb,
        "events": emitted,
        "rate": event_rate,
    }


def main():
    print("=========================================================================================")
    print("FleetGuard Pulse Simulator - Scale & Memory Performance Benchmark")
    print("=========================================================================================")
    print(
        f"| Vehicles | Startup Time | Net Memory | Test Events | Gen Time   | Generation Rate |"
    )
    print("|---------:|-------------:|-----------:|------------:|-----------:|----------------:|")

    benchmark_scale(10000, test_events=10000)
    benchmark_scale(50000, test_events=25000)
    benchmark_scale(100000, test_events=50000)
    print("=========================================================================================")


if __name__ == "__main__":
    main()
