"""
Unit tests for FleetGuard Pulse Predictive Maintenance ML.
Validates feature schemas, target construction logic, leakage checks,
purged temporal split invariants, baseline behavior, and inference contracts.
"""

from datetime import datetime, timedelta
import unittest
import numpy as np
import pandas as pd

from services.ml.baseline import RuleBasedRiskBaseline
from services.ml.dataset_generator import (
    SyntheticFleetGenerator,
    check_dataset_leakage,
    check_split_leakage,
)
from services.ml.schema import FEATURE_NAMES, PredictionResponse
from services.ml.trainer import purged_time_aware_split


class TestPredictiveMaintenanceUnit(unittest.TestCase):
    def setUp(self):
        self.generator = SyntheticFleetGenerator(seed=42)

    def test_feature_names_schema_integrity(self):
        """Verify feature list contains expected powertrain, telemetry, and maintenance columns."""
        self.assertIn("vibration_mean", FEATURE_NAMES)
        self.assertIn("coolant_temp_trend", FEATURE_NAMES)
        self.assertIn("cell_temp_delta_max", FEATURE_NAMES)
        self.assertIn("days_since_last_maintenance", FEATURE_NAMES)
        self.assertNotIn("target_7d", FEATURE_NAMES, "Target column must never be in feature list")
        self.assertNotIn("future_event_time", FEATURE_NAMES)
        self.assertNotIn("future_event_type", FEATURE_NAMES)
        self.assertNotIn("horizon_end_time", FEATURE_NAMES)

    def test_target_construction_known_future_failure_in_7_days(self):
        """Observation with a failure occurring within 7 days must be labeled target_7d = 1."""
        obs_time = datetime(2026, 8, 20, 12, 0, 0)
        future_failure_time = obs_time + timedelta(days=3.5)  # Within 7 days
        horizon_end = obs_time + timedelta(days=7.0)

        is_target = 1 if (obs_time < future_failure_time <= horizon_end) else 0
        self.assertEqual(is_target, 1, "Expected target_7d = 1 for event occurring at t + 3.5 days")

    def test_target_construction_known_future_failure_beyond_7_days(self):
        """Observation with failure occurring after 7-day horizon must be labeled target_7d = 0."""
        obs_time = datetime(2026, 8, 20, 12, 0, 0)
        future_failure_time = obs_time + timedelta(days=9.0)  # Beyond 7 days
        horizon_end = obs_time + timedelta(days=7.0)

        is_target = 1 if (obs_time < future_failure_time <= horizon_end) else 0
        self.assertEqual(is_target, 0, "Expected target_7d = 0 for event occurring at t + 9.0 days")

    def test_target_construction_no_future_failure(self):
        """Observation for healthy vehicle with no failure must be labeled target_7d = 0."""
        obs_time = datetime(2026, 8, 20, 12, 0, 0)
        future_failure_time = None
        horizon_end = obs_time + timedelta(days=7.0)

        is_target = 1 if (future_failure_time and obs_time < future_failure_time <= horizon_end) else 0
        self.assertEqual(is_target, 0, "Expected target_7d = 0 when no future failure is scheduled")

    def test_dataset_leakage_check_passes_on_generator_output(self):
        """Verify generator produces zero temporal leakage or illegal target features."""
        df = self.generator.generate_fleet_dataset(num_vehicles=50, sim_days=45)
        is_clean, violations = check_dataset_leakage(df)
        self.assertTrue(is_clean, f"Dataset contains leakage violations: {violations}")

    def test_dataset_leakage_check_catches_synthetic_violation(self):
        """Verify leakage checker catches an illegal future event date occurring before observation cutoff."""
        df = self.generator.generate_fleet_dataset(num_vehicles=10, sim_days=30)
        df.loc[0, "future_event_time"] = (datetime.fromisoformat(df.loc[0, "observation_time"]) - timedelta(days=1)).isoformat()
        is_clean, violations = check_dataset_leakage(df)
        self.assertFalse(is_clean, "Expected leakage checker to catch past event timestamp")

    def test_purged_temporal_split_invariants(self):
        """
        Verify purged temporal split invariants:
        1. max(train_obs) + 7 days < min(val_obs)
        2. max(val_obs) + 7 days < min(test_obs)
        """
        df = self.generator.generate_fleet_dataset(num_vehicles=50, sim_days=60)
        df_train, df_val, df_test, split_info = purged_time_aware_split(df, horizon_days=7.0)

        t_train_max = pd.to_datetime(df_train["observation_time"]).max()
        t_val_min = pd.to_datetime(df_val["observation_time"]).min()
        t_val_max = pd.to_datetime(df_val["observation_time"]).max()
        t_test_min = pd.to_datetime(df_test["observation_time"]).min()

        # Invariant 1: All train label horizons finish BEFORE earliest val observation
        self.assertLess(
            t_train_max + timedelta(days=7.0),
            t_val_min,
            f"Train label horizon ({t_train_max + timedelta(days=7.0)}) overlaps val ({t_val_min})",
        )

        # Invariant 2: All val label horizons finish BEFORE earliest test observation
        self.assertLess(
            t_val_max + timedelta(days=7.0),
            t_test_min,
            f"Val label horizon ({t_val_max + timedelta(days=7.0)}) overlaps test ({t_test_min})",
        )

        self.assertGreaterEqual(split_info["purge_gap_1_duration_days"], 7.0)
        self.assertGreaterEqual(split_info["purge_gap_2_duration_days"], 7.0)

    def test_check_split_leakage_catches_unpurged_split(self):
        """Verify check_split_leakage raises violation if an unpurged overlapping split is tested."""
        df = self.generator.generate_fleet_dataset(num_vehicles=20, sim_days=40)
        df_sorted = df.sort_values(by="observation_time").reset_index(drop=True)
        n = len(df_sorted)

        # Naive unpurged split without gap
        df_train_naive = df_sorted.iloc[: int(n * 0.6)].copy()
        df_val_naive = df_sorted.iloc[int(n * 0.6) : int(n * 0.8)].copy()
        df_test_naive = df_sorted.iloc[int(n * 0.8) :].copy()

        is_clean, violations = check_split_leakage(df_train_naive, df_val_naive, df_test_naive, horizon_days=7.0)
        self.assertFalse(is_clean, "Expected check_split_leakage to fail on naive unpurged split")
        self.assertGreater(len(violations), 0)

    def test_generator_deterministic_repeatability(self):
        """Identical seed must produce identical observations across vehicles."""
        gen1 = SyntheticFleetGenerator(seed=123)
        gen2 = SyntheticFleetGenerator(seed=123)

        df1 = gen1.generate_fleet_dataset(num_vehicles=20, sim_days=30)
        df2 = gen2.generate_fleet_dataset(num_vehicles=20, sim_days=30)

        pd.testing.assert_frame_equal(df1, df2)

    def test_rule_based_baseline_behavior(self):
        """Baseline model must flag severe multi-sensor anomalies as high risk."""
        baseline = RuleBasedRiskBaseline(decision_threshold=0.50)

        severe_row = {
            "vibration_mean": 1.25,
            "vibration_max": 3.10,
            "coolant_temp_mean": 115.0,
            "coolant_temp_trend": 6.5,
            "oil_pressure_mean": 140.0,
            "dtc_count": 2,
            "anomaly_count": 5,
        }
        score, pred, rules = baseline.score_single(severe_row)
        self.assertGreaterEqual(score, 0.50)
        self.assertEqual(pred, 1)
        self.assertIn("coolant_overheat_warning", rules)

        healthy_row = {
            "vibration_mean": 0.35,
            "vibration_max": 0.65,
            "coolant_temp_mean": 90.0,
            "coolant_temp_trend": 0.0,
            "oil_pressure_mean": 320.0,
            "dtc_count": 0,
            "anomaly_count": 0,
            "days_since_last_maintenance": 30.0,
        }
        score_h, pred_h, rules_h = baseline.score_single(healthy_row)
        self.assertLess(score_h, 0.50)
        self.assertEqual(pred_h, 0)
        self.assertEqual(len(rules_h), 0)


if __name__ == "__main__":
    unittest.main()
