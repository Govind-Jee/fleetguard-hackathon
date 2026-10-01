"""
Unit tests for FleetGuard Pulse Telemetry Simulator (F-01).

Validates:
- Schema validation for ICE, HEV, BEV
- Malformed event rejection
- Deterministic seed generation and reproducibility
- Fault progression correlation
- Duplicate injection behavior
- Out-of-order event generation
- Partition key integrity
"""

import unittest
from services.simulator.schema import TelemetryEvent, VehicleHealthState, VehicleType
from services.simulator.vehicle import create_initial_vehicle, simulate_telemetry_step, generate_synthetic_vin
from services.simulator.generator import TelemetryGenerator
import random


class TestTelemetrySchemaValidation(unittest.TestCase):
    def test_valid_ice_event(self):
        event = TelemetryEvent(
            event_id="00000000-0000-0000-0000-000000000001",
            vin="1FLC0000000000001",
            timestamp="2026-10-01T12:00:00Z",
            sequence_number=1,
            vehicle_type=VehicleType.ICE,
            latitude=33.7490,
            longitude=-84.3880,
            speed_kmh=85.0,
            odometer_km=15000.0,
            vibration=0.25,
            dtc_codes=[],
            oil_pressure_kpa=350.0,
            coolant_temp_c=90.0,
            engine_rpm=1800.0,
            battery_voltage_v=13.8,
        )
        self.assertEqual(event.vehicle_type, VehicleType.ICE)
        self.assertEqual(event.oil_pressure_kpa, 350.0)

    def test_valid_hev_event(self):
        event = TelemetryEvent(
            event_id="00000000-0000-0000-0000-000000000002",
            vin="1FLH0000000000002",
            timestamp="2026-10-01T12:00:00Z",
            sequence_number=1,
            vehicle_type=VehicleType.HEV,
            latitude=33.7490,
            longitude=-84.3880,
            speed_kmh=60.0,
            odometer_km=25000.0,
            vibration=0.20,
            dtc_codes=[],
            oil_pressure_kpa=320.0,
            coolant_temp_c=88.0,
            battery_voltage_v=13.8,
            soc_pct=65.0,
        )
        self.assertEqual(event.vehicle_type, VehicleType.HEV)
        self.assertEqual(event.soc_pct, 65.0)

    def test_valid_bev_event(self):
        event = TelemetryEvent(
            event_id="00000000-0000-0000-0000-000000000003",
            vin="1FLE0000000000003",
            timestamp="2026-10-01T12:00:00Z",
            sequence_number=1,
            vehicle_type=VehicleType.BEV,
            latitude=33.7490,
            longitude=-84.3880,
            speed_kmh=75.0,
            odometer_km=12000.0,
            vibration=0.18,
            dtc_codes=[],
            motor_rpm=4500.0,
            pack_voltage_v=395.0,
            soc_pct=80.0,
            cell_temp_delta_c=1.2,
        )
        self.assertEqual(event.vehicle_type, VehicleType.BEV)
        self.assertEqual(event.cell_temp_delta_c, 1.2)

    def test_invalid_vin_length_rejected(self):
        with self.assertRaises(ValueError):
            TelemetryEvent(
                event_id="00000000-0000-0000-0000-000000000004",
                vin="SHORTVIN",  # Invalid length
                timestamp="2026-10-01T12:00:00Z",
                sequence_number=1,
                vehicle_type=VehicleType.ICE,
                latitude=33.7490,
                longitude=-84.3880,
                speed_kmh=80.0,
                odometer_km=100.0,
                vibration=0.2,
                oil_pressure_kpa=300.0,
                coolant_temp_c=90.0,
                engine_rpm=1500.0,
            )

    def test_ice_missing_oil_pressure_rejected(self):
        with self.assertRaises(ValueError):
            TelemetryEvent(
                event_id="00000000-0000-0000-0000-000000000005",
                vin="1FLC0000000000005",
                timestamp="2026-10-01T12:00:00Z",
                sequence_number=1,
                vehicle_type=VehicleType.ICE,
                latitude=33.7490,
                longitude=-84.3880,
                speed_kmh=80.0,
                odometer_km=100.0,
                vibration=0.2,
                coolant_temp_c=90.0,
                engine_rpm=1500.0,
                # Missing oil_pressure_kpa
            )

    def test_bev_missing_cell_temp_delta_rejected(self):
        with self.assertRaises(ValueError):
            TelemetryEvent(
                event_id="00000000-0000-0000-0000-000000000006",
                vin="1FLE0000000000006",
                timestamp="2026-10-01T12:00:00Z",
                sequence_number=1,
                vehicle_type=VehicleType.BEV,
                latitude=33.7490,
                longitude=-84.3880,
                speed_kmh=80.0,
                odometer_km=100.0,
                vibration=0.2,
                pack_voltage_v=400.0,
                soc_pct=75.0,
                # Missing cell_temp_delta_c
            )


class TestDeterministicVehicleGeneration(unittest.TestCase):
    def test_vin_format(self):
        vin_ice = generate_synthetic_vin(1, VehicleType.ICE)
        vin_hev = generate_synthetic_vin(2, VehicleType.HEV)
        vin_bev = generate_synthetic_vin(3, VehicleType.BEV)
        self.assertEqual(len(vin_ice), 17)
        self.assertTrue(vin_ice.startswith("1FLC"))
        self.assertTrue(vin_hev.startswith("1FLH"))
        self.assertTrue(vin_bev.startswith("1FLE"))

    def test_deterministic_reproducibility(self):
        v1 = create_initial_vehicle(10, seed=12345)
        v2 = create_initial_vehicle(10, seed=12345)
        self.assertEqual(v1.vin, v2.vin)
        self.assertEqual(v1.vehicle_type, v2.vehicle_type)
        self.assertEqual(v1.model, v2.model)
        self.assertEqual(v1.model_year, v2.model_year)
        self.assertEqual(v1.odometer_km, v2.odometer_km)
        self.assertEqual(v1.latitude, v2.latitude)
        self.assertEqual(v1.longitude, v2.longitude)

    def test_vehicle_type_distribution_diversity(self):
        generator = TelemetryGenerator(vehicle_count=100, seed=42)
        generator.initialize_vehicles()
        types = {v.vehicle_type for v in generator.vehicles}
        self.assertIn(VehicleType.ICE, types)
        self.assertIn(VehicleType.HEV, types)
        self.assertIn(VehicleType.BEV, types)


class TestPhysicalProgressionAndAnomalies(unittest.TestCase):
    def test_fault_progression_sensor_correlation(self):
        v_healthy = create_initial_vehicle(0, seed=1)
        v_healthy.health_state = VehicleHealthState.HEALTHY
        v_healthy.vehicle_type = VehicleType.ICE

        v_failure = create_initial_vehicle(1, seed=1)
        v_failure.health_state = VehicleHealthState.FAILURE
        v_failure.vehicle_type = VehicleType.ICE

        rng = random.Random(42)
        event_h = simulate_telemetry_step(v_healthy, rng=rng, noise_enabled=False)
        event_f = simulate_telemetry_step(v_failure, rng=rng, noise_enabled=False)

        # Failure state must exhibit elevated coolant temp and degraded oil pressure
        self.assertGreater(event_f.coolant_temp_c, event_h.coolant_temp_c)
        self.assertLess(event_f.oil_pressure_kpa, event_h.oil_pressure_kpa)
        self.assertGreater(event_f.vibration, event_h.vibration)
        # Critical DTCs must be populated under failure
        self.assertTrue(len(event_f.dtc_codes) > 0)
        self.assertIn("P0524", event_f.dtc_codes)

    def test_sequence_number_increments(self):
        v = create_initial_vehicle(0, seed=42)
        rng = random.Random(42)
        e1 = simulate_telemetry_step(v, rng=rng)
        e2 = simulate_telemetry_step(v, rng=rng)
        self.assertEqual(e2.sequence_number, e1.sequence_number + 1)


class TestDuplicateAndReorderingInjection(unittest.TestCase):
    def test_duplicate_injection(self):
        # Verify duplicate events are emitted and IDs are preserved
        gen = TelemetryGenerator(vehicle_count=5, seed=42, duplicate_rate=0.5, reorder_rate=0.0)
        seen_ids = set()
        duplicates_found = 0
        for event, is_dup, is_reord in gen.stream_events(max_events=40):
            if is_dup:
                duplicates_found += 1
                self.assertIn(event.event_id, seen_ids, "Duplicate event must preserve identical event_id")
            seen_ids.add(event.event_id)
        self.assertGreater(duplicates_found, 0, "Duplicate events should be injected")

    def test_reordering_injection(self):
        # Verify out-of-order events occur
        gen = TelemetryGenerator(vehicle_count=10, seed=42, duplicate_rate=0.0, reorder_rate=0.5, reorder_buffer_size=5)
        reord_count = 0
        for event, is_dup, is_reord in gen.stream_events(max_events=40):
            if is_reord:
                reord_count += 1
        self.assertGreater(reord_count, 0, "Out-of-order events should be injected")


class TestVehiclePopulationCoverage(unittest.TestCase):
    def test_sample_population_100_percent_vin_coverage(self):
        # Fast unit test on 1,000 vehicle population
        gen = TelemetryGenerator(vehicle_count=1000, seed=42, duplicate_rate=0.0, reorder_rate=0.0)
        gen.initialize_vehicles()
        self.assertEqual(len(gen.vehicles), 1000)

        seen_vins = set()
        for event, is_dup, is_reord in gen.stream_events(max_events=1000):
            seen_vins.add(event.vin)
            self.assertEqual(event.schema_version, "1.0")
            self.assertGreaterEqual(event.sequence_number, 1)

        self.assertEqual(len(seen_vins), 1000, "Every vehicle in pool must be covered 1:1")


if __name__ == "__main__":
    unittest.main()
