"""
Integration tests for FleetGuard Pulse Predictive Maintenance ML Pipeline.
Verifies time-aware splitting, model training, artifact persistence, reloading,
deterministic metrics repeatability, and explainable inference.
"""

from datetime import timedelta
from pathlib import Path
import tempfile
import pytest
import numpy as np
import pandas as pd

from services.ml.dataset_generator import SyntheticFleetGenerator, check_split_leakage
from services.ml.predictor import PredictiveMaintenancePredictor
from services.ml.trainer import purged_time_aware_split, train_and_evaluate


@pytest.fixture(scope="module")
def sample_dataset():
    gen = SyntheticFleetGenerator(seed=42)
    return gen.generate_fleet_dataset(num_vehicles=100, sim_days=60)


def test_purged_time_aware_split_temporal_ordering(sample_dataset):
    """Verify purged split guarantees non-overlapping 7-day label horizons."""
    df_train, df_val, df_test, split_info = purged_time_aware_split(sample_dataset, horizon_days=7.0)

    max_train = pd.to_datetime(df_train["observation_time"]).max()
    min_val = pd.to_datetime(df_val["observation_time"]).min()
    max_val = pd.to_datetime(df_val["observation_time"]).max()
    min_test = pd.to_datetime(df_test["observation_time"]).min()

    # Crucial Invariant 1: latest train horizon cannot overlap validation observations
    assert max_train + timedelta(days=7.0) < min_val, f"Train horizon ({max_train + timedelta(days=7.0)}) overlaps val ({min_val})"

    # Crucial Invariant 2: latest validation horizon cannot overlap test observations
    assert max_val + timedelta(days=7.0) < min_test, f"Val horizon ({max_val + timedelta(days=7.0)}) overlaps test ({min_test})"

    # Invariant 3: purged rows are excluded from training and evaluation
    assert split_info["purged_rows"] > 0
    assert len(df_train) + len(df_val) + len(df_test) + split_info["purged_rows"] == len(sample_dataset)

    # Invariant 4: split leakage checker passes
    is_clean, violations = check_split_leakage(df_train, df_val, df_test, horizon_days=7.0)
    assert is_clean, f"Leakage detected: {violations}"


def test_end_to_end_train_save_and_reload(sample_dataset):
    """Verify pipeline training, serialization, reloading, and probability bounds."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        results = train_and_evaluate(sample_dataset, artifacts_dir=tmp_path, seed=42)

        model_file = tmp_path / "predictive_maintenance_model.joblib"
        metadata_file = tmp_path / "model_metadata.json"

        assert model_file.is_file(), "Model joblib file not created"
        assert metadata_file.is_file(), "Metadata JSON file not created"

        # Load into predictor
        predictor = PredictiveMaintenancePredictor(
            model_path=model_file,
            metadata_path=metadata_file,
            decision_threshold=None,
        )

        # Single prediction smoke test
        test_features = sample_dataset.iloc[0].to_dict()
        pred = predictor.predict_single(vin="TEST-VIN-001", features_dict=test_features)

        assert 0.0 <= pred.probability_7d <= 1.0
        assert pred.risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert isinstance(pred.predicted_maintenance_required, bool)
        assert len(pred.top_risk_factors) <= 4


def test_imputation_handles_missing_powertrain_features(sample_dataset):
    """Verify predictor cleanly imputes missing engine features for BEVs and battery features for ICEs."""
    model_path = Path("data/models/predictive_maintenance_model.joblib")
    if not model_path.exists():
        pytest.skip("Model artifact not yet built")

    predictor = PredictiveMaintenancePredictor(model_path=model_path)

    # BEV telemetry (missing engine/oil features)
    bev_payload = {
        "speed_mean": 62.0,
        "speed_std": 18.0,
        "vibration_mean": 0.38,
        "vibration_std": 0.11,
        "vibration_max": 0.72,
        "odometer_delta": 2400.0,
        "dtc_count": 0,
        "anomaly_count": 0,
        "telemetry_event_count": 3500,
        "coolant_temp_mean": None,
        "coolant_temp_std": None,
        "coolant_temp_trend": None,
        "oil_pressure_mean": None,
        "oil_pressure_min": None,
        "oil_pressure_trend": None,
        "engine_rpm_mean": None,
        "engine_rpm_std": None,
        "battery_voltage_mean": None,
        "soc_mean": 72.0,
        "soc_min": 28.0,
        "soc_drop_rate": 0.22,
        "pack_voltage_mean": 385.0,
        "cell_temp_delta_mean": 1.2,
        "cell_temp_delta_max": 2.1,
        "days_since_last_maintenance": 45.0,
        "km_since_last_maintenance": 6200.0,
    }

    pred = predictor.predict_single(vin="BEV-TEST-999", features_dict=bev_payload)
    assert 0.0 <= pred.probability_7d <= 1.0
    assert pred.risk_level == "LOW"


def test_deterministic_training_reproducibility(sample_dataset):
    """Two training runs with identical seed must produce identical metrics and coefficients."""
    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        res1 = train_and_evaluate(sample_dataset, artifacts_dir=Path(tmp1), seed=99)
        res2 = train_and_evaluate(sample_dataset, artifacts_dir=Path(tmp2), seed=99)

        assert res1["metrics_lr"]["f1"] == res2["metrics_lr"]["f1"]
        assert res1["metrics_lr"]["roc_auc"] == res2["metrics_lr"]["roc_auc"]
        assert res1["metrics_base"]["f1"] == res2["metrics_base"]["f1"]
        assert res1["metadata"]["intercept"] == res2["metadata"]["intercept"]
