"""
FleetGuard Pulse - Stream Processing CLI & Multi-Worker Supervisor
"""

import argparse
import logging
import multiprocessing
import sys
import time

from services.stream_processor.workers.real_time_worker import run_real_time_worker
from services.stream_processor.workers.mongodb_worker import run_mongodb_worker
from services.stream_processor.workers.clickhouse_worker import run_clickhouse_worker

logger = logging.getLogger("stream_processor.cli")


def main():
    parser = argparse.ArgumentParser(
        description="FleetGuard Pulse - Real-Time Telemetry Stream Processor"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Common arguments
    for cmd in ["real-time", "mongodb", "clickhouse", "all"]:
        sub = subparsers.add_parser(cmd, help=f"Run {cmd} worker")
        sub.add_argument(
            "--bootstrap-servers",
            default="localhost:9092",
            help="Kafka/Redpanda broker address",
        )
        sub.add_argument(
            "--max-messages",
            type=int,
            default=None,
            help="Stop after processing N messages",
        )
        sub.add_argument(
            "--offset-reset",
            default="latest",
            choices=["latest", "earliest"],
            help="Consumer offset reset strategy",
        )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.command == "real-time":
        run_real_time_worker(
            bootstrap_servers=args.bootstrap_servers,
            max_messages=args.max_messages,
            auto_offset_reset=args.offset_reset,
        )
    elif args.command == "mongodb":
        run_mongodb_worker(
            bootstrap_servers=args.bootstrap_servers,
            max_messages=args.max_messages,
            auto_offset_reset=args.offset_reset,
        )
    elif args.command == "clickhouse":
        run_clickhouse_worker(
            bootstrap_servers=args.bootstrap_servers,
            max_messages=args.max_messages,
            auto_offset_reset=args.offset_reset,
        )
    elif args.command == "all":
        logger.info("Spawning all 3 stream processor workers concurrently...")
        p_rt = multiprocessing.Process(
            target=run_real_time_worker,
            kwargs={
                "bootstrap_servers": args.bootstrap_servers,
                "max_messages": args.max_messages,
                "auto_offset_reset": args.offset_reset,
            },
        )
        p_mg = multiprocessing.Process(
            target=run_mongodb_worker,
            kwargs={
                "bootstrap_servers": args.bootstrap_servers,
                "max_messages": args.max_messages,
                "auto_offset_reset": args.offset_reset,
            },
        )
        p_ch = multiprocessing.Process(
            target=run_clickhouse_worker,
            kwargs={
                "bootstrap_servers": args.bootstrap_servers,
                "max_messages": args.max_messages,
                "auto_offset_reset": args.offset_reset,
            },
        )

        p_rt.start()
        p_mg.start()
        p_ch.start()

        try:
            while p_rt.is_alive() or p_mg.is_alive() or p_ch.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Terminating all stream workers...")
            p_rt.terminate()
            p_mg.terminate()
            p_ch.terminate()
            p_rt.join()
            p_mg.join()
            p_ch.join()


if __name__ == "__main__":
    main()
