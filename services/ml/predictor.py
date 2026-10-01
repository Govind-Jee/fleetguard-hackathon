"""
FleetGuard Pulse - Predictive Maintenance Inference Engine.
Loads serialized Logistic Regression Pipeline, validates input features, computes
failure probability within 7 days, and provides local component explanations.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union
import joblib
import numpy as np
import pandas as pd

from services.ml.schema import (
    FEATURE_NAMES,
    FeatureExplanation,
    PredictionResponse,
)


class PredictiveMaintenancePredictor:
    """
    Lightweight, production-ready inference engine for 7-day maintenance risk estimation.
    """

    def __init__(
        self,
        model_path: Union[str, Path] = "data/models/predictive_maintenance_model.joblib",
        metadata_path: Union[str, Path] = "data/models/model_metadata.json",
        decision_threshold: Optional[float] = None,
    ):
        self.model_path = Path(model_path)
        self.metadata_path = Path(metadata_path)

        if not self.model_path.exists():
            raise FileNotFoundError(f"Model file not found at: {self.model_path}")

        # Load serialized scikit-learn pipeline
        self.pipeline = joblib.load(self.model_path)

        # Load metadata if available
        self.metadata = {}
        if self.metadata_path.exists():
            with open(self.metadata_path, "r") as f:
                self.metadata = json.load(f)

        # Adopt validation-selected threshold if not explicitly overridden
        if decision_threshold is None:
            self.decision_threshold = self.metadata.get("threshold_selection", {}).get("selected_threshold", 0.50)
        else:
            self.decision_threshold = decision_threshold

        # Cache pipeline steps for fast explainability
        self.imputer = self.pipeline.named_steps["imputer"]
        self.scaler = self.pipeline.named_steps["scaler"]
        self.classifier = self.pipeline.named_steps["classifier"]
        self.coefficients = self.classifier.coef_[0]
        self.intercept = float(self.classifier.intercept_[0])

    def _prepare_dataframe(self, features_dict: Dict[str, Optional[float]]) -> pd.DataFrame:
        """Align input dictionary against canonical FEATURE_NAMES schema."""
        row = {}
        for feat in FEATURE_NAMES:
            val = features_dict.get(feat)
            row[feat] = np.nan if val is None else float(val)
        return pd.DataFrame([row], columns=FEATURE_NAMES)

    def predict_single(
        self,
        vin: str,
        features_dict: Dict[str, Optional[float]],
        prediction_timestamp: Optional[str] = None,
    ) -> PredictionResponse:
        """
        Estimate 7-day failure risk probability and extract top contributing features.
        """
        if prediction_timestamp is None:
            prediction_timestamp = datetime.utcnow().isoformat()

        df_input = self._prepare_dataframe(features_dict)

        # Compute probability
        proba_7d = float(self.pipeline.predict_proba(df_input)[0, 1])
        predicted_maint = proba_7d >= self.decision_threshold

        # Determine qualitative risk level
        if proba_7d < 0.25:
            risk_level = "LOW"
        elif proba_7d < 0.50:
            risk_level = "MEDIUM"
        elif proba_7d < 0.75:
            risk_level = "HIGH"
        else:
            risk_level = "CRITICAL"

        # Generate linear model explanation (standardized contribution: beta_i * z_i)
        X_imputed = self.imputer.transform(df_input)
        X_scaled = self.scaler.transform(X_imputed)[0]

        explanations: List[FeatureExplanation] = []
        for i, feat_name in enumerate(FEATURE_NAMES):
            raw_val = features_dict.get(feat_name)
            std_val = float(X_scaled[i])
            coef = float(self.coefficients[i])
            contribution = round(coef * std_val, 4)
            direction = "INCREASES_RISK" if contribution > 0 else "REDUCES_RISK"

            explanations.append(FeatureExplanation(
                feature_name=feat_name,
                feature_value=raw_val,
                standardized_value=round(std_val, 3),
                coefficient=round(coef, 4),
                contribution=contribution,
                direction=direction,
            ))

        # Partition into risk factors (positive contribution) and protective factors (negative contribution)
        risk_factors = [e for e in explanations if e.contribution > 0]
        risk_factors.sort(key=lambda x: x.contribution, reverse=True)

        protective_factors = [e for e in explanations if e.contribution < 0]
        protective_factors.sort(key=lambda x: x.contribution, reverse=False)

        return PredictionResponse(
            vin=vin,
            prediction_timestamp=prediction_timestamp,
            probability_7d=round(proba_7d, 4),
            risk_level=risk_level,
            predicted_maintenance_required=predicted_maint,
            decision_threshold=self.decision_threshold,
            top_risk_factors=risk_factors[:4],
            protective_factors=protective_factors[:3],
            model_version=self.metadata.get("model_version", "1.0.0"),
        )

    def predict_batch_proba(self, df: pd.DataFrame) -> np.ndarray:
        """Batch probability inference for evaluation and benchmarking."""
        df_aligned = df[FEATURE_NAMES]
        return self.pipeline.predict_proba(df_aligned)[:, 1]
