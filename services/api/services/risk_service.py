"""
FleetGuard Pulse - Predictive Risk Service.
Connects to the trained scikit-learn Logistic Regression Pipeline in services.ml.predictor.
Uses cached singleton predictor instance and Redis short-lived risk caching.
"""

import json
import logging
import math
import time
from typing import Dict, Optional
import psycopg2
import redis

from services.api.config import settings
from services.api.db import get_clickhouse_client
from services.api.metrics import api_metrics
from services.api.schemas.risk import RiskFactorExplanation, VehicleRiskResponse
from services.ml.predictor import PredictiveMaintenancePredictor
from services.ml.schema import FEATURE_NAMES

logger = logging.getLogger("fleetguard.api.services.risk")

# Singleton predictor instance loaded once into memory
_predictor_instance: Optional[PredictiveMaintenancePredictor] = None


def get_predictor() -> PredictiveMaintenancePredictor:
    """Return or initialize singleton ML predictor instance."""
    global _predictor_instance
    if _predictor_instance is None:
        logger.info("Initializing PredictiveMaintenancePredictor from: %s", settings.MODEL_PATH)
        _predictor_instance = PredictiveMaintenancePredictor(
            model_path=settings.MODEL_PATH,
            metadata_path=settings.MODEL_METADATA_PATH,
        )
    return _predictor_instance


class RiskService:

    @staticmethod
    def get_vehicle_risk(
        conn: psycopg2.extensions.connection,
        redis_client: redis.Redis,
        tenant_id: str,
        vin: str,
    ) -> Optional[VehicleRiskResponse]:
        """
        Estimate 7-day failure risk probability for a vehicle.
        Enforces tenant isolation, queries historical window state & maintenance context,
        and provides local explainability strictly adhering to the ML feature contract.
        """
        # 1. Verify vehicle exists within tenant domain
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT v.vehicle_id, v.initial_odometer_km, m.vehicle_type
                FROM vehicles v
                JOIN vehicle_models m ON v.model_id = m.model_id
                WHERE v.vin = %s AND v.tenant_id = %s;
                """,
                (vin, tenant_id),
            )
            v_row = cur.fetchone()

        if not v_row:
            return None

        vehicle_id, init_odo, vehicle_type = v_row[0], float(v_row[1]), str(v_row[2])

        # 2. Check Redis cache first (avoid redundant computation if queried recently)
        cache_key = f"vehicle:risk:{vin}"
        try:
            cached_data = redis_client.get(cache_key)
            if cached_data:
                cached_dict = json.loads(cached_data)
                return VehicleRiskResponse(**cached_dict)
        except Exception as e:
            logger.debug("Redis risk cache check error: %s", e)

        # 3. Fetch latest maintenance context from PostgreSQL (authoritative 3NF store)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    EXTRACT(DAY FROM (NOW() - MAX(performed_at))) AS days_since_maint,
                    MAX(odometer_km) AS last_maint_odo
                FROM maintenance_records
                WHERE vehicle_id = %s;
                """,
                (vehicle_id,),
            )
            m_row = cur.fetchone()

        days_since_maint = float(m_row[0]) if (m_row and m_row[0] is not None) else None
        last_maint_odo = float(m_row[1]) if (m_row and m_row[1] is not None) else None

        # 4. Fetch hot telemetry from Redis (instantaneous operating state)
        raw_hot = {}
        try:
            raw_hot = redis_client.hgetall(f"vehicle:state:{vin}") or {}
        except Exception as e:
            logger.warning("Failed to fetch hot state for risk scoring of %s: %s", vin, e)

        current_odo = float(raw_hot.get("odometer_km", init_odo)) if "odometer_km" in raw_hot else None
        km_since_maint = (
            max(0.0, current_odo - last_maint_odo)
            if (current_odo is not None and last_maint_odo is not None)
            else None
        )

        # 5. Fetch 14-day backward window aggregates from ClickHouse if available
        ch_stats: Dict[str, Optional[float]] = {}
        try:
            ch_client = get_clickhouse_client()
            if ch_client:
                query = """
                SELECT
                    count() AS n,
                    avg(speed_kmh) AS spd_mean,
                    stddevSamp(speed_kmh) AS spd_std,
                    avg(vibration) AS vib_mean,
                    stddevSamp(vibration) AS vib_std,
                    max(vibration) AS vib_max,
                    max(odometer_km) - min(odometer_km) AS odo_delta,
                    avg(coolant_temp_c) AS coolant_mean,
                    stddevSamp(coolant_temp_c) AS coolant_std,
                    avg(oil_pressure_kpa) AS oil_mean,
                    min(oil_pressure_kpa) AS oil_min,
                    avg(engine_rpm) AS rpm_mean,
                    stddevSamp(engine_rpm) AS rpm_std,
                    avg(battery_voltage_v) AS v12_mean,
                    avg(soc_pct) AS soc_mean,
                    min(soc_pct) AS soc_min,
                    avg(pack_voltage_v) AS pack_v_mean,
                    avg(cell_temp_delta_c) AS cell_d_mean,
                    max(cell_temp_delta_c) AS cell_d_max
                FROM vehicle_telemetry
                WHERE vin = %(vin)s AND timestamp >= NOW() - INTERVAL 14 DAY
                """
                res = ch_client.query(query, parameters={"vin": vin})
                if res.result_rows and res.result_rows[0][0] >= 2:
                    row = res.result_rows[0]
                    ch_stats = {
                        "n": float(row[0]),
                        "spd_mean": float(row[1]) if row[1] is not None and not math.isnan(row[1]) else None,
                        "spd_std": float(row[2]) if row[2] is not None and not math.isnan(row[2]) else None,
                        "vib_mean": float(row[3]) if row[3] is not None and not math.isnan(row[3]) else None,
                        "vib_std": float(row[4]) if row[4] is not None and not math.isnan(row[4]) else None,
                        "vib_max": float(row[5]) if row[5] is not None and not math.isnan(row[5]) else None,
                        "odo_delta": float(row[6]) if row[6] is not None and not math.isnan(row[6]) else None,
                        "coolant_mean": float(row[7]) if row[7] is not None and not math.isnan(row[7]) else None,
                        "coolant_std": float(row[8]) if row[8] is not None and not math.isnan(row[8]) else None,
                        "oil_mean": float(row[9]) if row[9] is not None and not math.isnan(row[9]) else None,
                        "oil_min": float(row[10]) if row[10] is not None and not math.isnan(row[10]) else None,
                        "rpm_mean": float(row[11]) if row[11] is not None and not math.isnan(row[11]) else None,
                        "rpm_std": float(row[12]) if row[12] is not None and not math.isnan(row[12]) else None,
                        "v12_mean": float(row[13]) if row[13] is not None and not math.isnan(row[13]) else None,
                        "soc_mean": float(row[14]) if row[14] is not None and not math.isnan(row[14]) else None,
                        "soc_min": float(row[15]) if row[15] is not None and not math.isnan(row[15]) else None,
                        "pack_v_mean": float(row[16]) if row[16] is not None and not math.isnan(row[16]) else None,
                        "cell_d_mean": float(row[17]) if row[17] is not None and not math.isnan(row[17]) else None,
                        "cell_d_max": float(row[18]) if row[18] is not None and not math.isnan(row[18]) else None,
                    }
        except Exception as e:
            logger.debug("ClickHouse telemetry history query skipped: %s", e)

        # 6. Assemble observation feature mapping strictly adhering to ML training schema
        # Missing values (None) are handled via SimpleImputer(strategy="median") in the pipeline.
        is_ice_or_hev = vehicle_type in ("ICE", "HEV")
        is_hev_or_bev = vehicle_type in ("HEV", "BEV")

        features: Dict[str, Optional[float]] = {
            "speed_mean": ch_stats.get("spd_mean") or (float(raw_hot["speed_kmh"]) if "speed_kmh" in raw_hot else None),
            "speed_std": ch_stats.get("spd_std"),
            "vibration_mean": ch_stats.get("vib_mean") or (float(raw_hot["vibration"]) if "vibration" in raw_hot else None),
            "vibration_std": ch_stats.get("vib_std"),
            "vibration_max": ch_stats.get("vib_max") or (float(raw_hot["vibration"]) if "vibration" in raw_hot else None),
            "odometer_delta": ch_stats.get("odo_delta"),
            "dtc_count": len(json.loads(raw_hot["dtc_codes"])) if "dtc_codes" in raw_hot else (0 if raw_hot else None),
            "anomaly_count": 1 if raw_hot.get("health_status") in ("WARNING", "CRITICAL") else (0 if raw_hot else None),
            "telemetry_event_count": ch_stats.get("n") or (int(raw_hot["sequence_number"]) if "sequence_number" in raw_hot else None),
            # Powertrain features: ICE / HEV
            "coolant_temp_mean": (ch_stats.get("coolant_mean") or (float(raw_hot["coolant_temp_c"]) if "coolant_temp_c" in raw_hot else None)) if is_ice_or_hev else None,
            "coolant_temp_std": ch_stats.get("coolant_std") if is_ice_or_hev else None,
            "coolant_temp_trend": None,
            "oil_pressure_mean": (ch_stats.get("oil_mean") or (float(raw_hot["oil_pressure_kpa"]) if "oil_pressure_kpa" in raw_hot else None)) if is_ice_or_hev else None,
            "oil_pressure_min": (ch_stats.get("oil_min") or (float(raw_hot["oil_pressure_kpa"]) if "oil_pressure_kpa" in raw_hot else None)) if is_ice_or_hev else None,
            "oil_pressure_trend": None,
            "engine_rpm_mean": (ch_stats.get("rpm_mean") or (float(raw_hot["engine_rpm"]) if "engine_rpm" in raw_hot else None)) if is_ice_or_hev else None,
            "engine_rpm_std": ch_stats.get("rpm_std") if is_ice_or_hev else None,
            "battery_voltage_mean": (ch_stats.get("v12_mean") or (float(raw_hot["battery_voltage_v"]) if "battery_voltage_v" in raw_hot else None)) if is_ice_or_hev else None,
            # Powertrain features: HEV / BEV
            "soc_mean": (ch_stats.get("soc_mean") or (float(raw_hot["soc_pct"]) if "soc_pct" in raw_hot else None)) if is_hev_or_bev else None,
            "soc_min": (ch_stats.get("soc_min") or (float(raw_hot["soc_pct"]) if "soc_pct" in raw_hot else None)) if is_hev_or_bev else None,
            "soc_drop_rate": None,
            "pack_voltage_mean": (ch_stats.get("pack_v_mean") or (float(raw_hot["pack_voltage_v"]) if "pack_voltage_v" in raw_hot else None)) if is_hev_or_bev else None,
            "cell_temp_delta_mean": (ch_stats.get("cell_d_mean") or (float(raw_hot["cell_temp_delta_c"]) if "cell_temp_delta_c" in raw_hot else None)) if is_hev_or_bev else None,
            "cell_temp_delta_max": (ch_stats.get("cell_d_max") or (float(raw_hot["cell_temp_delta_c"]) if "cell_temp_delta_c" in raw_hot else None)) if is_hev_or_bev else None,
            # Maintenance lifecycle context
            "days_since_last_maintenance": days_since_maint,
            "km_since_last_maintenance": km_since_maint,
        }

        # Automated schema & feature ordering contract guard
        assert list(features.keys()) == FEATURE_NAMES, (
            f"Inference features schema mismatch! Expected: {FEATURE_NAMES}, Got: {list(features.keys())}"
        )

        # 6. Predict using singleton model pipeline
        predictor = get_predictor()
        t0 = time.perf_counter()
        prediction = predictor.predict_single(vin=vin, features_dict=features)
        pred_duration = time.perf_counter() - t0
        api_metrics.record_prediction(model_version=prediction.model_version, duration_seconds=pred_duration)

        # 7. Convert to API response
        top_risks = [
            RiskFactorExplanation(
                feature_name=f.feature_name,
                feature_value=f.feature_value,
                standardized_value=round(f.standardized_value, 4),
                coefficient=round(f.coefficient, 4),
                contribution=round(f.contribution, 4),
                direction=f.direction,
            )
            for f in prediction.top_risk_factors
        ]
        protective = [
            RiskFactorExplanation(
                feature_name=f.feature_name,
                feature_value=f.feature_value,
                standardized_value=round(f.standardized_value, 4),
                coefficient=round(f.coefficient, 4),
                contribution=round(f.contribution, 4),
                direction=f.direction,
            )
            for f in prediction.protective_factors
        ]

        response = VehicleRiskResponse(
            vin=vin,
            probability_7d=round(prediction.probability_7d, 4),
            predicted_maintenance_required=prediction.predicted_maintenance_required,
            risk_level=prediction.risk_level,
            decision_threshold=prediction.decision_threshold,
            top_risk_factors=top_risks,
            protective_factors=protective,
            model_version=prediction.model_version,
            prediction_timestamp=prediction.prediction_timestamp,
        )

        # 8. Cache response in Redis
        try:
            redis_client.set(
                cache_key,
                response.model_dump_json(),
                ex=settings.RISK_CACHE_TTL_SECONDS,
            )
        except Exception as e:
            logger.debug("Failed to cache risk response in Redis: %s", e)

        return response
