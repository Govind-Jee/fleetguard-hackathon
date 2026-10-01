"""
FleetGuard Pulse - Simulator Command Line Interface (CLI)

Supports seed dataset generation and streaming telemetry generation in both
dry-run and Redpanda publish modes.
"""

import argparse
import logging
import os
import sys
import time
from typing import Optional

from services.simulator.generator import TelemetryGenerator, generate_seed_vehicle_dataset
from services.simulator.producer import TelemetryProducer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("fleetguard.simulator")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.simulator",
        description="FleetGuard Pulse 100K+ Connected Vehicle Telemetry Simulator",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. generate-vehicles command
    gen_parser = subparsers.add_parser(
        "generate-vehicles",
        help="Generate synthetic seed vehicle dataset (e.g. 100,000 vehicles)",
    )
    gen_parser.add_argument(
        "--count",
        type=int,
        default=int(os.getenv("SIMULATOR_VEHICLE_COUNT", "100000")),
        help="Number of synthetic vehicles to generate (default: 100,000)",
    )
    gen_parser.add_argument(
        "--seed",
        type=int,
        default=int(os.getenv("SIMULATOR_SEED", "42")),
        help="Deterministic random seed (default: 42)",
    )
    gen_parser.add_argument(
        "--output",
        type=str,
        default=os.getenv("SIMULATOR_OUTPUT_FILE", "data/seed/vehicles.csv"),
        help="Output CSV file path (default: data/seed/vehicles.csv)",
    )

    # 2. run command
    run_parser = subparsers.add_parser(
        "run",
        help="Execute real-time streaming telemetry simulation",
    )
    run_parser.add_argument(
        "--vehicles",
        type=int,
        default=int(os.getenv("SIMULATOR_VEHICLE_COUNT", "100000")),
        help="Number of active vehicles in simulation pool (default: 100,000)",
    )
    run_parser.add_argument(
        "--rate",
        type=float,
        default=float(os.getenv("SIMULATOR_TARGET_RATE", "1000.0")),
        help="Target telemetry generation rate in events/second (default: 1000)",
    )
    run_parser.add_argument(
        "--seed",
        type=int,
        default=int(os.getenv("SIMULATOR_SEED", "42")),
        help="Random seed for repeatable simulation",
    )
    run_parser.add_argument(
        "--brokers",
        type=str,
        default=os.getenv("REDPANDA_BROKERS", "localhost:9092"),
        help="Redpanda / Kafka bootstrap brokers (default: localhost:9092)",
    )
    run_parser.add_argument(
        "--topic",
        type=str,
        default=os.getenv("SIMULATOR_TOPIC", "vehicle.telemetry.v1"),
        help="Destination message topic (default: vehicle.telemetry.v1)",
    )
    run_parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Maximum events to emit before exit (default: None / continuous)",
    )
    run_parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Run duration in seconds (0 = run until max-events or interrupted)",
    )
    run_parser.add_argument(
        "--duplicate-rate",
        type=float,
        default=float(os.getenv("SIMULATOR_DUPLICATE_RATE", "0.01")),
        help="Fraction of events duplicated (default: 0.01 / 1%%)",
    )
    run_parser.add_argument(
        "--reorder-rate",
        type=float,
        default=float(os.getenv("SIMULATOR_REORDER_RATE", "0.02")),
        help="Fraction of events emitted out-of-order (default: 0.02 / 2%%)",
    )
    run_parser.add_argument(
        "--burst-multiplier",
        type=float,
        default=3.0,
        help="Multiplier during traffic bursts (default: 3.0x)",
    )
    run_parser.add_argument(
        "--burst-duration",
        type=float,
        default=0.0,
        help="Duration of traffic burst in seconds (default: 0.0)",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Generate telemetry in-memory without publishing to Redpanda",
    )

    return parser


def handle_generate_vehicles(args: argparse.Namespace) -> int:
    logger.info("Generating %d synthetic vehicles into %s (seed=%d)...", args.count, args.output, args.seed)
    start_t = time.perf_counter()
    count = generate_seed_vehicle_dataset(
        output_path=args.output,
        count=args.count,
        seed=args.seed,
    )
    elapsed = time.perf_counter() - start_t
    logger.info("Successfully wrote %d vehicles in %.2f seconds (%.0f vehicles/sec).", count, elapsed, count / max(elapsed, 0.001))
    return 0


def handle_run_simulation(args: argparse.Namespace) -> int:
    logger.info(
        "Initializing telemetry generator: vehicles=%d, target_rate=%.1f ev/s, seed=%d, dry_run=%s",
        args.vehicles, args.rate, args.seed, args.dry_run
    )
    
    init_start = time.perf_counter()
    generator = TelemetryGenerator(
        vehicle_count=args.vehicles,
        seed=args.seed,
        duplicate_rate=args.duplicate_rate,
        reorder_rate=args.reorder_rate,
        burst_multiplier=args.burst_multiplier,
        burst_duration_sec=args.burst_duration,
    )
    generator.initialize_vehicles()
    init_elapsed = time.perf_counter() - init_start
    logger.info("Vehicle pool initialized in %.3f seconds.", init_elapsed)

    producer = TelemetryProducer(
        bootstrap_servers=args.brokers,
        topic=args.topic,
        dry_run=args.dry_run,
    )

    start_time = time.perf_counter()
    last_report = start_time
    events_since_report = 0
    total_emitted = 0

    # Rate limiting parameters
    target_interval = 1.0 / max(args.rate, 1.0) if args.rate > 0 else 0.0
    burst_end_time = start_time + args.burst_duration if args.burst_duration > 0 else 0.0

    try:
        for event, is_dup, is_reordered in generator.stream_events(max_events=args.max_events):
            now = time.perf_counter()
            
            # Check duration limit
            if args.duration > 0 and (now - start_time) >= args.duration:
                break

            # Handle burst rate adaptation
            current_rate = args.rate
            if now < burst_end_time:
                current_rate = args.rate * args.burst_multiplier
            target_interval = 1.0 / max(current_rate, 1.0)

            # Produce record
            producer.produce(
                event_dict=event.model_dump(),
                is_duplicate=is_dup,
                is_reordered=is_reordered,
            )

            events_since_report += 1
            total_emitted += 1

            # Periodic progress log
            if (now - last_report) >= 2.0:
                elapsed_period = now - last_report
                actual_rate = events_since_report / elapsed_period
                logger.info(
                    "Emitted %d events (rate: %.1f ev/s) | Duplicates: %d | Reordered: %d | Delivered: %d",
                    total_emitted, actual_rate, producer.duplicates_emitted, producer.reorders_emitted, producer.messages_delivered
                )
                last_report = now
                events_since_report = 0

            # Inter-event pacing for throttled runs
            if target_interval > 0.0001:
                next_event_time = start_time + (total_emitted * target_interval)
                sleep_duration = next_event_time - time.perf_counter()
                if sleep_duration > 0.001:
                    time.sleep(sleep_duration)

    except KeyboardInterrupt:
        logger.info("Simulation interrupted by user.")
    finally:
        total_time = time.perf_counter() - start_time
        logger.info("Flushing producer buffers...")
        producer.close()
        avg_rate = total_emitted / max(total_time, 0.001)
        logger.info(
            "=== Simulation Summary ===\n"
            "Total Events Generated: %d\n"
            "Total Duplicates:       %d (%.2f%%)\n"
            "Total Reordered:        %d (%.2f%%)\n"
            "Total Delivered:        %d\n"
            "Total Failed:           %d\n"
            "Total Duration:         %.2f s\n"
            "Average Rate:           %.1f events/sec",
            total_emitted,
            producer.duplicates_emitted,
            (producer.duplicates_emitted / max(total_emitted, 1)) * 100,
            producer.reorders_emitted,
            (producer.reorders_emitted / max(total_emitted, 1)) * 100,
            producer.messages_delivered,
            producer.messages_failed,
            total_time,
            avg_rate,
        )

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "generate-vehicles":
        return handle_generate_vehicles(args)
    elif args.command == "run":
        return handle_run_simulation(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
