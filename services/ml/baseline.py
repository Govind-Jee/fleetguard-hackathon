"""
FleetGuard Pulse - Deterministic Rule-Based Baseline Model.
Provides an interpretable threshold-based maintenance risk baseline using only
information known at observation time t.
"""

from typing import Dict, List, Tuple
import numpy as np
import pandas as pd


class RuleBasedRiskBaseline:
    """
    Deterministic rule-based risk baseline.
    Evaluates physical sensor degradation rules to compute an empirical risk score (0.0 to 1.0)
    and binary 7-day maintenance risk classification.
    """

    def __init__(self, decision_threshold: float = 0.50):
        self.decision_threshold = decision_threshold
        # Thresholds derived from vehicle engineering domain limits
        self.rules = [
            ("vibration_warning", lambda r: (r.get("vibration_mean") or 0) > 0.80 or (r.get("vibration_max") or 0) > 2.0, 1.5),
            ("coolant_overheat_warning", lambda r: (r.get("coolant_temp_mean") or 0) > 102.0 or (r.get("coolant_temp_trend") or 0) > 3.0, 1.5),
            ("oil_pressure_low_warning", lambda r: (0 < (r.get("oil_pressure_mean") or 999) < 220.0) or (0 < (r.get("oil_pressure_min") or 999) < 140.0) or ((r.get("oil_pressure_trend") or 0) < -3.5), 1.5),
            ("cell_delta_warning", lambda r: (r.get("cell_temp_delta_mean") or 0) > 2.8 or (r.get("cell_temp_delta_max") or 0) > 4.5, 1.5),
            ("active_dtc_warning", lambda r: (r.get("dtc_count") or 0) >= 1, 1.0),
            ("anomaly_cluster_warning", lambda r: (r.get("anomaly_count") or 0) >= 3, 1.0),
            ("maintenance_overdue", lambda r: (r.get("days_since_last_maintenance") or 0) > 120.0 or (r.get("km_since_last_maintenance") or 0) > 25000.0, 0.5),
        ]

    def score_single(self, row: Dict) -> Tuple[float, int, List[str]]:
        """Compute continuous risk score and binary prediction for a single feature dictionary."""
        total_weight = 0.0
        max_normalizer = 4.0
        triggered_rules: List[str] = []

        for name, condition, weight in self.rules:
            try:
                if condition(row):
                    total_weight += weight
                    triggered_rules.append(name)
            except Exception:
                pass

        risk_score = min(1.0, total_weight / max_normalizer)
        pred_binary = 1 if risk_score >= self.decision_threshold else 0
        return risk_score, pred_binary, triggered_rules

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return Nx2 probability array [[P(0), P(1)], ...]."""
        scores = []
        for _, row in X.iterrows():
            score, _, _ = self.score_single(row.to_dict())
            scores.append([1.0 - score, score])
        return np.array(scores)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return binary predictions [0 or 1]."""
        preds = []
        for _, row in X.iterrows():
            _, pred, _ = self.score_single(row.to_dict())
            preds.append(pred)
        return np.array(preds)
