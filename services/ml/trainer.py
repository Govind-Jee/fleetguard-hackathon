"""
FleetGuard Pulse - Predictive Maintenance ML Trainer with Purged Temporal Splitting.
Implements non-overlapping purged temporal splitting, scikit-learn Logistic Regression
Pipeline training, validation-based threshold selection, held-out test evaluation against rule baseline,
and model artifact serialization.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from services.ml.baseline import RuleBasedRiskBaseline
from services.ml.dataset_generator import check_split_leakage
from services.ml.schema import FEATURE_NAMES


def purged_time_aware_split(
    df: pd.DataFrame,
    horizon_days: float = 7.0,
    train_ratio: float = 0.55,
    val_ratio: float = 0.20,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict]:
    """
    Split dataset chronologically with explicit 7-day purge gaps between splits.
    Guarantees:
    - For every train sample t: t + 7 days < min(val observation time)
    - For every val sample t:   t + 7 days < min(test observation time)
    """
    df_sorted = df.copy()
    df_sorted["_obs_dt"] = pd.to_datetime(df_sorted["observation_time"])
    df_sorted = df_sorted.sort_values(by="_obs_dt").reset_index(drop=True)

    t_min = df_sorted["_obs_dt"].min()
    t_max = df_sorted["_obs_dt"].max()
    total_duration = t_max - t_min

    # Purge gap must strictly exceed horizon_days
    purge_gap = timedelta(days=horizon_days + 0.0001)
    min_required_duration = 2 * purge_gap + timedelta(days=2.0)
    if total_duration < min_required_duration:
        raise ValueError(
            f"Timeline duration ({total_duration.days} days) too short for 2 purge gaps of {horizon_days} days."
        )

    available_duration = total_duration - (2 * purge_gap)
    train_duration = available_duration * train_ratio
    val_duration = available_duration * val_ratio

    t_train_end = t_min + train_duration
    t_val_start = t_train_end + purge_gap
    t_val_end = t_val_start + val_duration
    t_test_start = t_val_end + purge_gap

    df_train = df_sorted[df_sorted["_obs_dt"] <= t_train_end].drop(columns=["_obs_dt"]).copy()
    df_val = df_sorted[(df_sorted["_obs_dt"] >= t_val_start) & (df_sorted["_obs_dt"] <= t_val_end)].drop(columns=["_obs_dt"]).copy()
    df_test = df_sorted[df_sorted["_obs_dt"] >= t_test_start].drop(columns=["_obs_dt"]).copy()

    split_info = {
        "timeline_start": t_min.isoformat(),
        "timeline_end": t_max.isoformat(),
        "train_start": t_min.isoformat(),
        "train_end": t_train_end.isoformat(),
        "purge_gap_1_start": t_train_end.isoformat(),
        "purge_gap_1_end": t_val_start.isoformat(),
        "purge_gap_1_duration_days": round((t_val_start - t_train_end).total_seconds() / 86400.0, 4),
        "val_start": t_val_start.isoformat(),
        "val_end": t_val_end.isoformat(),
        "purge_gap_2_start": t_val_end.isoformat(),
        "purge_gap_2_end": t_test_start.isoformat(),
        "purge_gap_2_duration_days": round((t_test_start - t_val_end).total_seconds() / 86400.0, 4),
        "test_start": t_test_start.isoformat(),
        "test_end": t_max.isoformat(),
        "total_rows": len(df),
        "train_rows": len(df_train),
        "val_rows": len(df_val),
        "test_rows": len(df_test),
        "purged_rows": len(df) - (len(df_train) + len(df_val) + len(df_test)),
    }

    # Verify split leakage invariant
    is_valid, violations = check_split_leakage(df_train, df_val, df_test, horizon_days=horizon_days)
    if not is_valid:
        raise ValueError(f"Split leakage invariant violated: {violations}")

    return df_train, df_val, df_test, split_info


def time_aware_split(
    df: pd.DataFrame,
    train_ratio: float = 0.55,
    val_ratio: float = 0.20,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compatibility wrapper executing purged temporal split."""
    df_train, df_val, df_test, _ = purged_time_aware_split(
        df, horizon_days=7.0, train_ratio=train_ratio, val_ratio=val_ratio
    )
    return df_train, df_val, df_test


def build_logistic_regression_pipeline(
    random_state: int = 42,
    class_weight: str = "balanced",
    C: float = 1.0,
) -> Pipeline:
    """
    Construct reproducible scikit-learn Pipeline:
    1. SimpleImputer (median for powertrain missing values)
    2. StandardScaler (z-score normalization)
    3. LogisticRegression (lbfgs solver, balanced class weights)
    """
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(
            C=C,
            class_weight=class_weight,
            random_state=random_state,
            max_iter=1000,
            solver="lbfgs",
        )),
    ])


def select_validation_threshold(
    pipeline: Pipeline,
    X_val: pd.DataFrame,
    y_val: np.ndarray,
    candidates: Optional[List[float]] = None,
) -> Tuple[float, float]:
    """
    Select optimal decision threshold on the validation set by maximizing F1 score.
    Does NOT touch the test set.
    """
    if candidates is None:
        candidates = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]

    val_proba = pipeline.predict_proba(X_val)[:, 1]
    best_thresh = 0.50
    best_f1 = -1.0

    for thresh in candidates:
        pred = (val_proba >= thresh).astype(int)
        score = f1_score(y_val, pred, zero_division=0)
        if score > best_f1:
            best_f1 = score
            best_thresh = thresh

    return best_thresh, round(best_f1, 4)


def evaluate_predictions(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_proba: np.ndarray,
) -> Dict[str, float]:
    """Compute standard classification metrics on test data."""
    prec = precision_score(y_true, y_pred, zero_division=0)
    rec = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    try:
        auc = roc_auc_score(y_true, y_proba)
    except Exception:
        auc = 0.5

    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()

    return {
        "precision": float(round(prec, 4)),
        "recall": float(round(rec, 4)),
        "f1": float(round(f1, 4)),
        "roc_auc": float(round(auc, 4)),
        "true_positives": int(tp),
        "false_positives": int(fp),
        "true_negatives": int(tn),
        "false_negatives": int(fn),
        "total_test_samples": int(len(y_true)),
        "positive_support": int(sum(y_true)),
    }


def train_and_evaluate(
    df: pd.DataFrame,
    artifacts_dir: Path = Path("data/models"),
    seed: int = 42,
) -> Dict:
    """
    End-to-end execution of purged temporal split, training, validation threshold tuning,
    baseline vs model evaluation on held-out test set, coefficient extraction, and artifact persistence.
    """
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # 1. Purged Chronological Split
    df_train, df_val, df_test, split_info = purged_time_aware_split(df, horizon_days=7.0)

    X_train = df_train[FEATURE_NAMES]
    y_train = df_train["target_7d"].values

    X_val = df_val[FEATURE_NAMES]
    y_val = df_val["target_7d"].values

    X_test = df_test[FEATURE_NAMES]
    y_test = df_test["target_7d"].values

    # 2. Train Logistic Regression Pipeline on Training Set Only
    pipeline = build_logistic_regression_pipeline(random_state=seed)
    pipeline.fit(X_train, y_train)

    # 3. Select Decision Threshold Strictly on Validation Set
    optimal_thresh, val_f1 = select_validation_threshold(pipeline, X_val, y_val)

    # 4. Model Predictions on Held-Out Test Set
    test_proba_lr = pipeline.predict_proba(X_test)[:, 1]
    # Primary evaluation at validation-selected threshold
    test_pred_lr = (test_proba_lr >= optimal_thresh).astype(int)
    metrics_lr = evaluate_predictions(y_test, test_pred_lr, test_proba_lr)

    # Also compute uncalibrated threshold 0.50 for full comparison
    test_pred_lr_50 = (test_proba_lr >= 0.50).astype(int)
    metrics_lr_50 = evaluate_predictions(y_test, test_pred_lr_50, test_proba_lr)

    # 5. Baseline Evaluation on Same Held-Out Test Set (Threshold 0.50)
    baseline = RuleBasedRiskBaseline(decision_threshold=0.50)
    test_proba_base = baseline.predict_proba(X_test)[:, 1]
    test_pred_base = baseline.predict(X_test)
    metrics_base = evaluate_predictions(y_test, test_pred_base, test_proba_base)

    # 6. Extract Interpretable Standardized Coefficients
    classifier: LogisticRegression = pipeline.named_steps["classifier"]
    coefficients = classifier.coef_[0]
    intercept = float(classifier.intercept_[0])

    coef_list = []
    for feat_name, coef in zip(FEATURE_NAMES, coefficients):
        direction = "INCREASES_RISK" if coef > 0 else "REDUCES_RISK"
        coef_list.append({
            "feature": feat_name,
            "coefficient": float(round(coef, 4)),
            "abs_impact": float(round(abs(coef), 4)),
            "direction": direction,
        })
    coef_list.sort(key=lambda x: x["abs_impact"], reverse=True)

    # 7. Save Serialized Model and Comprehensive Metadata
    model_path = artifacts_dir / "predictive_maintenance_model.joblib"
    joblib.dump(pipeline, model_path)

    metadata = {
        "model_version": "1.1.0",
        "model_type": "LogisticRegression (sklearn Pipeline with Purged Temporal Split)",
        "training_timestamp": datetime.utcnow().isoformat(),
        "random_seed": seed,
        "feature_names": FEATURE_NAMES,
        "intercept": round(intercept, 4),
        "coefficients": coef_list,
        "threshold_selection": {
            "method": "Validation set F1 maximization (test set untouched)",
            "selected_threshold": optimal_thresh,
            "validation_f1": val_f1,
        },
        "split_info": split_info,
        "split_counts": {
            "train_samples": len(df_train),
            "train_positive_rate": float(round(y_train.mean(), 4)),
            "val_samples": len(df_val),
            "val_positive_rate": float(round(y_val.mean(), 4)),
            "test_samples": len(df_test),
            "test_positive_rate": float(round(y_test.mean(), 4)),
        },
        "evaluation": {
            "baseline_rule_model": metrics_base,
            "logistic_regression_validation_threshold": metrics_lr,
            "logistic_regression_default_50": metrics_lr_50,
        },
    }

    metadata_path = artifacts_dir / "model_metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    return {
        "pipeline": pipeline,
        "baseline": baseline,
        "metrics_lr": metrics_lr,
        "metrics_lr_50": metrics_lr_50,
        "metrics_base": metrics_base,
        "optimal_threshold": optimal_thresh,
        "metadata": metadata,
        "split_info": split_info,
        "model_path": str(model_path),
        "metadata_path": str(metadata_path),
    }
