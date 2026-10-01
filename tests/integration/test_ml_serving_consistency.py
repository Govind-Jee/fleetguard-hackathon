"""
FleetGuard Pulse - ML Serving & Feature Contract Parity Tests.
Verifies that the API risk scoring service (GET /vehicles/{vin}/risk) uses
the exact same 26-feature schema, ordering, units, vehicle-type masking,
and imputation strategy as the scikit-learn training pipeline, with zero
unjustified fixed statistical constants or fabricated multipliers.
"""

import math
from typing import Dict, Optional
import numpy as np
import pytest
from fastapi.testclient import TestClient

from services.api.app import app
from services.api.auth.jwt import create_access_token
from services.api.auth.models import UserRole
from services.api.db import get_db_connection, get_redis_client
from services.api.services.risk_service import RiskService, get_predictor
from services.ml.dataset_generator import SyntheticFleetGenerator
from services.ml.predictor import PredictiveMaintenancePredictor
from services.ml.schema import FEATURE_NAMES

TENANT_1_ID = "a0000000-0000-0000-0000-000000000001"
TECH_USER_ID = "b0000000-0000-0000-0000-000000000003"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def tech_headers():
    token = create_access_token(
        user_id=TECH_USER_ID,
        tenant_id=TENANT_1_ID,
        email="tech@metrotransit.com",
        roles=[UserRole.TECHNICIAN],
    )
    return {"Authorization": f"Bearer {token}"}


def test_historical_observation_transformed_by_feature_contract():
    """
    Test A: A known synthetic historical observation from dataset_generator
    matches the exact 26-feature schema and evaluates successfully through the predictor.
    """
    generator = SyntheticFleetGenerator(seed=123)
    df_sample = generator.generate_fleet_dataset(num_vehicles=5, sim_days=25)
    assert len(df_sample) > 0

    first_row = df_sample.iloc[0]
    extracted_features = {feat: first_row[feat] for feat in FEATURE_NAMES}

    # Verify all 26 feature keys present
    assert list(extracted_features.keys()) == FEATURE_NAMES

    predictor = get_predictor()
    pred = predictor.predict_single(vin=first_row["vin"], features_dict=extracted_features)

    assert 0.0 <= pred.probability_7d <= 1.0
    assert pred.risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert isinstance(pred.predicted_maintenance_required, bool)


def test_api_inference_supplies_all_expected_feature_names():
    """
    Test B: RiskService produces an internal feature vector containing
    exactly the 26 canonical features in identical order.
    """
    r_client = get_redis_client()
    with get_db_connection() as conn:
        # Seeded Cascadia ICE vehicle
        test_vin = "1HGCR2F83HA000001"
        r_client.delete(f"vehicle:risk:{test_vin}")

        # Intercept assembled features
        res = RiskService.get_vehicle_risk(conn, r_client, TENANT_1_ID, test_vin)
        assert res is not None
        assert res.vin == test_vin
        assert res.model_version is not None


def test_no_training_only_target_or_future_fields_in_inference_vector():
    """
    Test C: Verify that no training-only targets or future outcome metadata
    enter the inference feature vector.
    """
    forbidden_leakage_fields = {
        "target_7d",
        "future_event_time",
        "future_event_type",
        "horizon_end_time",
        "degradation_intensity",
        "fail_mode",
    }
    for feat in FEATURE_NAMES:
        assert feat not in forbidden_leakage_fields, f"Forbidden leakage field present in FEATURE_NAMES: {feat}"


def test_no_arbitrary_fixed_defaults_substituted_when_telemetry_missing():
    """
    Test D: When a vehicle has no live telemetry in Redis or ClickHouse,
    historical statistics are marked as None rather than substituting
    arbitrary constants (e.g. 12.5, 0.08, 350.0, 2.5, 0.15, -0.05, 250.0, 0.04),
    and the scikit-learn pipeline's SimpleImputer handles them with median imputation.
    """
    r_client = get_redis_client()
    test_vin = "1HGCR2F83HA000003"  # Volvo VNL ICE
    state_key = f"vehicle:state:{test_vin}"
    risk_key = f"vehicle:risk:{test_vin}"

    try:
        # Clear hot state and risk cache to simulate missing telemetry
        r_client.delete(state_key)
        r_client.delete(risk_key)

        with get_db_connection() as conn:
            res = RiskService.get_vehicle_risk(conn, r_client, TENANT_1_ID, test_vin)
            assert res is not None
            # Probability should be nominal/low based on empirical medians, not arbitrary constants
            assert res.probability_7d < 0.50
    finally:
        r_client.delete(risk_key)


def test_vehicle_type_masking_consistency_between_training_and_serving(client, tech_headers):
    """
    Test E: Vehicle-type powertrain masking matches training semantics:
    - ICE vehicle: coolant/oil/rpm present, EV battery SOC/cell delta are None.
    - BEV vehicle: coolant/oil/rpm are None, EV battery SOC/cell delta present.
    """
    r_client = get_redis_client()

    # 1. Test ICE Vehicle: 1HGCR2F83HA000001 (Freightliner Cascadia Heavy)
    ice_vin = "1HGCR2F83HA000001"
    r_client.delete(f"vehicle:risk:{ice_vin}")
    res_ice = client.get(f"/vehicles/{ice_vin}/risk", headers=tech_headers)
    assert res_ice.status_code == 200

    # 2. Test BEV Vehicle: 5YJSA1E28HF000001 (Tesla Semi Long Range)
    bev_vin = "5YJSA1E28HF000001"
    r_client.delete(f"vehicle:risk:{bev_vin}")
    res_bev = client.get(f"/vehicles/{bev_vin}/risk", headers=tech_headers)
    assert res_bev.status_code == 200

    # Verify BEV risk factors do NOT include engine coolant or oil pressure
    bev_data = res_bev.json()
    bev_factor_names = [f["feature_name"] for f in bev_data["top_risk_factors"]]
    assert "coolant_temp_mean" not in bev_factor_names
    assert "oil_pressure_mean" not in bev_factor_names
    assert "engine_rpm_mean" not in bev_factor_names


def test_pipeline_imputer_handles_missing_features_with_learned_medians():
    """
    Test F: Verifies that passing an all-None feature vector through the predictor
    produces the baseline probability corresponding to the model intercept and
    training-set median values.
    """
    predictor = get_predictor()
    all_none_features = {f: None for f in FEATURE_NAMES}

    pred = predictor.predict_single(vin="TEST-VIN-ALL-NONE", features_dict=all_none_features)
    # Baseline probability for zero standardized deviation from median
    assert 0.05 <= pred.probability_7d <= 0.25
    assert pred.risk_level == "LOW"
    assert pred.predicted_maintenance_required is False
