"""
FleetGuard Pulse - Telemetry Stream Generator & Dataset Seeder

Handles deterministic seed creation for 100K+ vehicles and high-throughput streaming
telemetry generation with controlled duplicates, reordering, noise, and bursts.
"""

import csv
import os
import random
import time
from collections import deque
from pathlib import Path
from typing import Deque, Generator, List, Optional, Tuple

from services.simulator.schema import TelemetryEvent
from services.simulator.vehicle import VehicleState, create_initial_vehicle, simulate_telemetry_step


class TelemetryGenerator:
    """
    High-scale, memory-efficient streaming telemetry generator.
    """
    def __init__(
        self,
        vehicle_count: int = 100000,
        seed: int = 42,
        duplicate_rate: float = 0.01,
        reorder_rate: float = 0.02,
        reorder_buffer_size: int = 50,
        noise_enabled: bool = True,
        burst_multiplier: float = 3.0,
        burst_duration_sec: float = 0.0,
    ):
        self.vehicle_count = vehicle_count
        self.seed = seed
        self.duplicate_rate = duplicate_rate
        self.reorder_rate = reorder_rate
        self.reorder_buffer_size = reorder_buffer_size
        self.noise_enabled = noise_enabled
        self.burst_multiplier = burst_multiplier
        self.burst_duration_sec = burst_duration_sec

        self.rng = random.Random(seed)
        self.vehicles: List[VehicleState] = []
        
        # Bounded buffers for duplicate and out-of-order injection
        self._duplicate_queue: Deque[TelemetryEvent] = deque(maxlen=200)
        self._reorder_buffer: List[TelemetryEvent] = []
        
        # Operational counters
        self.total_generated = 0
        self.total_duplicates = 0
        self.total_reordered = 0
        
        self._initialized = False

    def initialize_vehicles(self, max_count: Optional[int] = None) -> None:
        """
        Lazily creates the in-memory pool of compact VehicleState instances.
        """
        count = max_count or self.vehicle_count
        self.vehicles = [create_initial_vehicle(i, self.seed) for i in range(count)]
        self._initialized = True

    def stream_events(
        self,
        max_events: Optional[int] = None,
    ) -> Generator[Tuple[TelemetryEvent, bool, bool], None, None]:
        """
        Yields a continuous stream of TelemetryEvents with realistic anomalies.
        Returns tuples of: (event, is_duplicate, is_reordered)
        """
        if not self._initialized:
            self.initialize_vehicles()

        num_vehicles = len(self.vehicles)
        if num_vehicles == 0:
            return

        emitted = 0
        v_idx = 0

        while True:
            if max_events is not None and emitted >= max_events:
                break

            # 1. Check if we should inject a duplicate event from the duplicate queue
            if self._duplicate_queue and self.rng.random() < self.duplicate_rate:
                dup_event = self._duplicate_queue.popleft()
                self.total_duplicates += 1
                emitted += 1
                yield dup_event, True, False
                continue

            # 2. Advance vehicle state and generate fresh event
            vehicle = self.vehicles[v_idx]
            event = simulate_telemetry_step(
                vehicle=vehicle,
                rng=self.rng,
                noise_enabled=self.noise_enabled,
            )
            self.total_generated += 1
            v_idx = (v_idx + 1) % num_vehicles

            # 3. Add to duplicate candidate queue
            if self.duplicate_rate > 0.0 and self.rng.random() < (self.duplicate_rate * 1.5):
                # Save a copy to re-emit later
                self._duplicate_queue.append(event)

            # 4. Out-of-order handling via bounded shuffle buffer
            if self.reorder_rate > 0.0:
                self._reorder_buffer.append(event)
                if len(self._reorder_buffer) >= self.reorder_buffer_size:
                    # Randomly pick an event from the buffer if reordering triggers
                    if self.rng.random() < self.reorder_rate:
                        pick_idx = self.rng.randint(0, len(self._reorder_buffer) - 2)
                        out_event = self._reorder_buffer.pop(pick_idx)
                        self.total_reordered += 1
                        emitted += 1
                        yield out_event, False, True
                    else:
                        out_event = self._reorder_buffer.pop(0)
                        emitted += 1
                        yield out_event, False, False
            else:
                emitted += 1
                yield event, False, False

        # Flush remaining reorder buffer
        while self._reorder_buffer:
            if max_events is not None and emitted >= max_events:
                break
            out_event = self._reorder_buffer.pop(0)
            emitted += 1
            yield out_event, False, False


def generate_seed_vehicle_dataset(
    output_path: str = "data/seed/vehicles.csv",
    count: int = 100000,
    seed: int = 42,
) -> int:
    """
    Generates a deterministic dataset containing at least 100,000 synthetic vehicles.
    Writes to CSV and returns the total number of vehicles generated.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "vehicle_id",
        "vin",
        "vehicle_type",
        "model",
        "model_year",
        "fleet_id",
        "depot_id",
        "maintenance_age_days",
        "vehicle_state_seed",
    ]

    with open(path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for i in range(count):
            v = create_initial_vehicle(i, seed=seed)
            writer.writerow({
                "vehicle_id": v.vehicle_id,
                "vin": v.vin,
                "vehicle_type": v.vehicle_type.value,
                "model": v.model,
                "model_year": v.model_year,
                "fleet_id": v.fleet_id,
                "depot_id": v.depot_id,
                "maintenance_age_days": v.maintenance_age_days,
                "vehicle_state_seed": v.vehicle_state_seed,
            })

    return count
