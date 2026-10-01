"""
FleetGuard Pulse - Synthetic Longitudinal ML Dataset Generator.
Generates reproducible vehicle telemetry histories, computes strictly backward-looking
features over an observation window [t - 14d, t], and constructs the 7-day target
TARGET_7D based on future events in (t, t + 7d].
"""

import math
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from services.ml.schema import FEATURE_NAMES, ObservationRecord


class SyntheticFleetGenerator:
    """
    Deterministic longitudinal vehicle state and telemetry generator for predictive maintenance.
    Simulates multi-week operational wear, progressive degradation trajectories,
    maintenance events, and failure occurrences across ICE, HEV, and BEV powertrains.
    """

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
        self.np_rng = np.random.RandomState(seed)

    def generate_fleet_dataset(
        self,
        num_vehicles: int = 1000,
        sim_days: int = 90,
        observation_interval_days: int = 3,
        window_days: int = 14,
        horizon_days: int = 7,
        start_date: datetime = datetime(2026, 8, 1, 0, 0, 0),
    ) -> pd.DataFrame:
        """
        Generate longitudinal observation rows with backward features and 7-day forward targets.
        """
        records: List[Dict] = []

        # Powertrain distribution: 60% ICE, 25% HEV, 15% BEV
        vehicle_types = (
            ["ICE"] * int(num_vehicles * 0.60)
            + ["HEV"] * int(num_vehicles * 0.25)
            + ["BEV"] * int(num_vehicles * 0.15)
        )
        # Pad to exact count if rounding difference
        while len(vehicle_types) < num_vehicles:
            vehicle_types.append("ICE")

        self.rng.shuffle(vehicle_types)

        for i in range(num_vehicles):
            vin = f"1HGCR2F{i:05d}{vehicle_types[i][:2]}"
            v_type = vehicle_types[i]

            # Determine if this vehicle will develop a degradation/failure trajectory
            # ~18% of vehicles experience an unplanned degradation/failure
            will_degrade = self.rng.random() < 0.18
            failure_time: Optional[datetime] = None
            degradation_start_time: Optional[datetime] = None

            if will_degrade:
                # Failure occurs between day 20 and day (sim_days - 4)
                fail_day = self.rng.uniform(20.0, sim_days - 4.0)
                failure_time = start_date + timedelta(days=fail_day)
                # Degradation starts 3.5 to 9 days prior to failure
                lead_days = self.rng.uniform(3.5, 9.0)
                degradation_start_time = failure_time - timedelta(days=lead_days)

            # Failure mode category
            fail_mode = "NONE"
            if will_degrade:
                if v_type == "ICE":
                    fail_mode = self.rng.choice(["COOLING_OVERHEAT", "OIL_PRESSURE_LOSS", "BEARING_VIBRATION"])
                elif v_type == "HEV":
                    fail_mode = self.rng.choice(["COOLING_OVERHEAT", "BATTERY_CELL_IMBALANCE", "BEARING_VIBRATION"])
                else:  # BEV
                    fail_mode = self.rng.choice(["BATTERY_CELL_IMBALANCE", "INVERTER_DEGRADATION", "BEARING_VIBRATION"])

            # Baseline metrics per vehicle
            base_odometer = self.rng.uniform(15000.0, 140000.0)
            daily_km = self.rng.uniform(120.0, 320.0)
            last_maint_date = start_date - timedelta(days=self.rng.uniform(10.0, 120.0))

            # Generate observation points starting after window_days burn-in
            current_obs_day = float(window_days)
            while current_obs_day <= (sim_days - horizon_days):
                obs_time = start_date + timedelta(days=current_obs_day)
                window_start = obs_time - timedelta(days=window_days)
                horizon_end = obs_time + timedelta(days=horizon_days)

                # Has vehicle already failed before obs_time? If so, stop generating future observations for it
                if failure_time and obs_time >= failure_time:
                    break

                # Determine 7-day target: does failure occur in (obs_time, horizon_end]?
                target_7d = 0
                event_timestamp_str: Optional[str] = None
                if failure_time and (obs_time < failure_time <= horizon_end):
                    target_7d = 1
                    event_timestamp_str = failure_time.isoformat()

                # Calculate degradation intensity at obs_time strictly using past information
                degradation_intensity = 0.0
                if degradation_start_time and obs_time > degradation_start_time:
                    total_lead = (failure_time - degradation_start_time).total_seconds()
                    elapsed = (obs_time - degradation_start_time).total_seconds()
                    degradation_intensity = min(1.0, max(0.0, elapsed / total_lead))

                # Synthesize backward window features [window_start, obs_time]
                features = self._compute_backward_features(
                    v_type=v_type,
                    window_days=window_days,
                    degradation_intensity=degradation_intensity,
                    fail_mode=fail_mode,
                    daily_km=daily_km,
                    base_odometer=base_odometer + (current_obs_day * daily_km),
                    last_maint_date=last_maint_date,
                    obs_time=obs_time,
                )

                row = {
                    "observation_id": f"OBS-{vin}-{int(current_obs_day)}",
                    "vin": vin,
                    "vehicle_type": v_type,
                    "observation_time": obs_time.isoformat(),
                    "window_start_time": window_start.isoformat(),
                    "horizon_end_time": horizon_end.isoformat(),
                    "future_event_time": event_timestamp_str,
                    "future_event_type": fail_mode if target_7d == 1 else None,
                    "target_7d": target_7d,
                }
                row.update(features)
                records.append(row)

                current_obs_day += observation_interval_days

        df = pd.DataFrame(records)
        return df

    def _compute_backward_features(
        self,
        v_type: str,
        window_days: int,
        degradation_intensity: float,
        fail_mode: str,
        daily_km: float,
        base_odometer: float,
        last_maint_date: datetime,
        obs_time: datetime,
    ) -> Dict[str, Optional[float]]:
        """
        Compute deterministic summary features strictly using past window telemetry [obs_time - window_days, obs_time].
        """
        # Common driving metrics
        speed_mean = self.rng.uniform(45.0, 75.0)
        speed_std = self.rng.uniform(15.0, 25.0)
        odometer_delta = daily_km * window_days * self.rng.uniform(0.92, 1.08)
        telemetry_event_count = int(window_days * self.rng.uniform(250, 300))

        # Vibration metrics
        base_vib = 0.35 + self.rng.uniform(-0.05, 0.05)
        if fail_mode == "BEARING_VIBRATION" and degradation_intensity > 0:
            vib_mean = base_vib + (1.2 * degradation_intensity) + self.rng.uniform(-0.05, 0.05)
            vib_std = 0.10 + (0.45 * degradation_intensity)
            vib_max = vib_mean + (2.5 * vib_std)
        else:
            vib_mean = base_vib + (0.05 * degradation_intensity)
            vib_std = self.rng.uniform(0.08, 0.14)
            vib_max = vib_mean + self.rng.uniform(0.3, 0.7)

        # Realistic DTC and Anomaly counts (including natural ambient noise on healthy assets)
        ambient_anom = 1 if self.rng.random() < 0.12 else 0
        ambient_dtc = 1 if self.rng.random() < 0.04 else 0

        if degradation_intensity > 0.4:
            base_dtc = ambient_dtc + int(self.rng.uniform(1, 4))
            base_anom = ambient_anom + int(self.rng.uniform(2, 8) * degradation_intensity)
        elif degradation_intensity > 0.1:
            base_dtc = ambient_dtc
            base_anom = ambient_anom + int(self.rng.uniform(1, 3))
        else:
            base_dtc = ambient_dtc
            base_anom = ambient_anom

        # Maintenance context
        days_since_maint = (obs_time - last_maint_date).total_seconds() / 86400.0
        km_since_maint = days_since_maint * daily_km

        # Powertrain-specific features
        coolant_mean = None
        coolant_std = None
        coolant_trend = None
        oil_mean = None
        oil_min = None
        oil_trend = None
        rpm_mean = None
        rpm_std = None
        v12_mean = None

        soc_mean = None
        soc_min = None
        soc_drop_rate = None
        pack_v_mean = None
        cell_delta_mean = None
        cell_delta_max = None

        if v_type in ("ICE", "HEV"):
            c_base = 90.0 + self.rng.uniform(-2.0, 2.0)
            if fail_mode == "COOLING_OVERHEAT" and degradation_intensity > 0:
                coolant_mean = c_base + (24.0 * degradation_intensity)
                coolant_std = 3.0 + (6.0 * degradation_intensity)
                coolant_trend = 1.5 + (8.0 * degradation_intensity)
            else:
                coolant_mean = c_base + (1.5 * degradation_intensity)
                coolant_std = self.rng.uniform(2.5, 4.5)
                coolant_trend = self.rng.uniform(-0.5, 0.5)

            oil_base = 320.0 + self.rng.uniform(-15.0, 15.0)
            if fail_mode == "OIL_PRESSURE_LOSS" and degradation_intensity > 0:
                oil_mean = oil_base - (190.0 * degradation_intensity)
                oil_min = max(40.0, oil_mean - (60.0 * degradation_intensity))
                oil_trend = -2.0 - (12.0 * degradation_intensity)
            else:
                oil_mean = oil_base - (10.0 * degradation_intensity)
                oil_min = oil_mean - self.rng.uniform(40.0, 70.0)
                oil_trend = self.rng.uniform(-0.8, 0.8)

            rpm_mean = self.rng.uniform(1800.0, 2400.0)
            rpm_std = self.rng.uniform(350.0, 550.0)
            v12_mean = 14.1 + self.rng.uniform(-0.2, 0.2)

        if v_type in ("HEV", "BEV"):
            soc_mean = 65.0 + self.rng.uniform(-8.0, 8.0)
            soc_min = 25.0 + self.rng.uniform(-5.0, 5.0)
            pack_v_mean = 390.0 + self.rng.uniform(-10.0, 10.0) if v_type == "BEV" else 240.0

            delta_base = 1.1 + self.rng.uniform(-0.2, 0.2)
            if fail_mode == "BATTERY_CELL_IMBALANCE" and degradation_intensity > 0:
                cell_delta_mean = delta_base + (4.5 * degradation_intensity)
                cell_delta_max = cell_delta_mean + 2.0 + (3.0 * degradation_intensity)
                soc_drop_rate = 0.28 + (0.35 * degradation_intensity)
            else:
                cell_delta_mean = delta_base + (0.2 * degradation_intensity)
                cell_delta_max = cell_delta_mean + self.rng.uniform(0.6, 1.2)
                soc_drop_rate = self.rng.uniform(0.18, 0.25)

        return {
            "speed_mean": round(speed_mean, 2),
            "speed_std": round(speed_std, 2),
            "vibration_mean": round(vib_mean, 4),
            "vibration_std": round(vib_std, 4),
            "vibration_max": round(vib_max, 4),
            "odometer_delta": round(odometer_delta, 1),
            "dtc_count": base_dtc,
            "anomaly_count": base_anom,
            "telemetry_event_count": telemetry_event_count,
            "coolant_temp_mean": round(coolant_mean, 2) if coolant_mean is not None else None,
            "coolant_temp_std": round(coolant_std, 2) if coolant_std is not None else None,
            "coolant_temp_trend": round(coolant_trend, 2) if coolant_trend is not None else None,
            "oil_pressure_mean": round(oil_mean, 1) if oil_mean is not None else None,
            "oil_pressure_min": round(oil_min, 1) if oil_min is not None else None,
            "oil_pressure_trend": round(oil_trend, 2) if oil_trend is not None else None,
            "engine_rpm_mean": round(rpm_mean, 1) if rpm_mean is not None else None,
            "engine_rpm_std": round(rpm_std, 1) if rpm_std is not None else None,
            "battery_voltage_mean": round(v12_mean, 2) if v12_mean is not None else None,
            "soc_mean": round(soc_mean, 2) if soc_mean is not None else None,
            "soc_min": round(soc_min, 2) if soc_min is not None else None,
            "soc_drop_rate": round(soc_drop_rate, 4) if soc_drop_rate is not None else None,
            "pack_voltage_mean": round(pack_v_mean, 1) if pack_v_mean is not None else None,
            "cell_temp_delta_mean": round(cell_delta_mean, 2) if cell_delta_mean is not None else None,
            "cell_temp_delta_max": round(cell_delta_max, 2) if cell_delta_max is not None else None,
            "days_since_last_maintenance": round(days_since_maint, 1),
            "km_since_last_maintenance": round(km_since_maint, 1),
        }


def check_dataset_leakage(df: pd.DataFrame) -> Tuple[bool, List[str]]:
    """
    Automated row-level leakage audit.
    Verifies:
    1. Feature columns contain no target columns or horizon metadata.
    2. Observation time is strictly before horizon end time.
    3. Future event time (if present) occurs strictly after observation time.
    4. Target 7D is 1 iff future event time is within (obs_time, obs_time + 7 days].
    """
    violations: List[str] = []

    # Check 1: Feature list does not contain target or metadata
    forbidden_features = {"target_7d", "future_event_time", "future_event_type", "horizon_end_time"}
    for f in FEATURE_NAMES:
        if f in forbidden_features:
            violations.append(f"Forbidden column in feature list: {f}")

    # Check 2: Temporal chronology per row
    for idx, row in df.iterrows():
        obs_dt = datetime.fromisoformat(row["observation_time"])
        horizon_dt = datetime.fromisoformat(row["horizon_end_time"])
        window_start_dt = datetime.fromisoformat(row["window_start_time"])

        if obs_dt <= window_start_dt:
            violations.append(f"Row {idx}: observation_time <= window_start_time")
        if horizon_dt <= obs_dt:
            violations.append(f"Row {idx}: horizon_end_time <= observation_time")

        if pd.notna(row["future_event_time"]) and row["future_event_time"]:
            event_dt = datetime.fromisoformat(row["future_event_time"])
            if event_dt <= obs_dt:
                violations.append(f"Row {idx}: future_event_time ({event_dt}) occurs at or before observation_time ({obs_dt})! LEAKAGE!")
            if event_dt > horizon_dt and row["target_7d"] == 1:
                violations.append(f"Row {idx}: target_7d is 1 but event is after horizon!")
            if obs_dt < event_dt <= horizon_dt and row["target_7d"] != 1:
                violations.append(f"Row {idx}: event in horizon but target_7d is not 1!")

        if len(violations) > 10:
            break

    return (len(violations) == 0, violations)


def check_split_leakage(
    df_train: pd.DataFrame,
    df_val: pd.DataFrame,
    df_test: pd.DataFrame,
    horizon_days: float = 7.0,
) -> Tuple[bool, List[str]]:
    """
    Automated split-level temporal label-horizon leakage audit.
    Guarantees:
    1. For every training observation t: t + horizon_days < min(val_observation_time)
    2. For every validation observation t: t + horizon_days < min(test_observation_time)
    """
    violations: List[str] = []

    train_max_obs = pd.to_datetime(df_train["observation_time"]).max()
    val_min_obs = pd.to_datetime(df_val["observation_time"]).min()
    val_max_obs = pd.to_datetime(df_val["observation_time"]).max()
    test_min_obs = pd.to_datetime(df_test["observation_time"]).min()

    # Invariant 1: train max horizon < val min obs
    train_max_horizon = train_max_obs + timedelta(days=horizon_days)
    if train_max_horizon >= val_min_obs:
        violations.append(
            f"Train-to-Val label horizon overlap! Latest train horizon: {train_max_horizon} >= Earliest val obs: {val_min_obs}"
        )

    # Invariant 2: val max horizon < test min obs
    val_max_horizon = val_max_obs + timedelta(days=horizon_days)
    if val_max_horizon >= test_min_obs:
        violations.append(
            f"Val-to-Test label horizon overlap! Latest val horizon: {val_max_horizon} >= Earliest test obs: {test_min_obs}"
        )

    return (len(violations) == 0, violations)
