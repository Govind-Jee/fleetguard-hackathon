#!/usr/bin/env python3
"""
FleetGuard Pulse - End-to-End ML Dataset Generation & Model Training Pipeline.
Generates synthetic longitudinal telemetry observations, enforces leakage prevention,
applies purged chronological splitting with 7-day non-overlapping gaps, trains Logistic Regression,
evaluates vs baseline, and serializes artifacts.
"""

import argparse
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd

# Add repo root to python path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.ml.dataset_generator import (
    SyntheticFleetGenerator,
    check_dataset_leakage,
    check_split_leakage,
)
from services.ml.predictor import PredictiveMaintenancePredictor
from services.ml.trainer import train_and_evaluate


def main():
    parser = argparse.ArgumentParser(description="FleetGuard Pulse ML Dataset Generator & Trainer")
    parser.add_argument("--num-vehicles", type=int, default=1000, help="Number of vehicles to simulate")
    parser.add_argument("--sim-days", type=int, default=90, help="Total simulation timeline in days")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    parser.add_argument("--output-csv", type=str, default="data/generated/ml_dataset.csv", help="Dataset output path")
    parser.add_argument("--models-dir", type=str, default="data/models", help="Model artifacts directory")
    args = parser.parse_args()

    print(f"================================================================================")
    print(f"FleetGuard Pulse - Predictive Maintenance ML Pipeline (Seed: {args.seed})")
    print(f"================================================================================")

    # 1. Dataset Generation
    print(f"\n[1/5] Generating longitudinal fleet dataset ({args.num_vehicles} vehicles, {args.sim_days} days)...")
    gen = SyntheticFleetGenerator(seed=args.seed)
    t0 = time.time()
    df = gen.generate_fleet_dataset(num_vehicles=args.num_vehicles, sim_days=args.sim_days)
    gen_time = time.time() - t0

    num_rows = len(df)
    unique_vins = df["vin"].nunique()
    pos_count = int(df["target_7d"].sum())
    neg_count = num_rows - pos_count
    pos_rate = (pos_count / num_rows) * 100.0

    print(f" -> Generation completed in {gen_time:.2f}s")
    print(f" -> Total Observations: {num_rows:,} rows across {unique_vins:,} unique vehicles")
    print(f" -> Target Distribution: Positive (7D Failure): {pos_count:,} ({pos_rate:.2f}%) | Negative: {neg_count:,} ({100.0 - pos_rate:.2f}%)")
    print(f" -> Powertrains: {df['vehicle_type'].value_counts().to_dict()}")

    # 2. Automated Leakage Audit
    print(f"\n[2/5] Running automated row-level temporal leakage audit...")
    is_clean, violations = check_dataset_leakage(df)
    if not is_clean:
        print(f"CRITICAL: Leakage violations detected!")
        for v in violations:
            print(f"  - {v}")
        sys.exit(1)
    print(" -> Row-level Leakage Check PASSED: 0 future features, 0 temporal boundary violations.")

    # 3. Save Dataset
    output_path = REPO_ROOT / args.output_csv
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f" -> Dataset persisted to {output_path} ({output_path.stat().st_size / (1024*1024):.2f} MB)")

    # 4. Train & Evaluate with Purged Temporal Split
    print(f"\n[3/5] Executing purged temporal split and model training...")
    models_dir = REPO_ROOT / args.models_dir
    train_res = train_and_evaluate(df, artifacts_dir=models_dir, seed=args.seed)

    meta = train_res["metadata"]
    sinfo = train_res["split_info"]
    scounts = meta["split_counts"]

    print(f"\n --- Purged Temporal Split Breakdown ---")
    print(f" Timeline Span: {sinfo['timeline_start'][:10]} to {sinfo['timeline_end'][:10]}")
    print(f"  * Train Period:      {sinfo['train_start'][:10]} to {sinfo['train_end'][:10]} ({scounts['train_samples']:,} samples, Pos Rate: {scounts['train_positive_rate']*100:.2f}%)")
    print(f"  * Purge Gap 1:       {sinfo['purge_gap_1_start'][:10]} to {sinfo['purge_gap_1_end'][:10]} ({sinfo['purge_gap_1_duration_days']:.1f} days non-overlapping buffer)")
    print(f"  * Validation Period: {sinfo['val_start'][:10]} to {sinfo['val_end'][:10]} ({scounts['val_samples']:,} samples, Pos Rate: {scounts['val_positive_rate']*100:.2f}%)")
    print(f"  * Purge Gap 2:       {sinfo['purge_gap_2_start'][:10]} to {sinfo['purge_gap_2_end'][:10]} ({sinfo['purge_gap_2_duration_days']:.1f} days non-overlapping buffer)")
    print(f"  * Held-Out Test:     {sinfo['test_start'][:10]} to {sinfo['test_end'][:10]} ({scounts['test_samples']:,} samples, Pos Rate: {scounts['test_positive_rate']*100:.2f}%)")
    print(f"  * Purged Discarded:  {sinfo['purged_rows']:,} observation rows safely dropped from purge gaps")

    # 5. Comparative Evaluation Report
    m_lr = train_res["metrics_lr"]
    m_base = train_res["metrics_base"]

    print(f"\n[4/5] Corrected Held-Out Test Set Performance Comparison:")
    print(f"--------------------------------------------------------------------------------")
    print(f"Metric                  | Rule-Based Baseline    | Logistic Regression Pipeline")
    print(f"--------------------------------------------------------------------------------")
    print(f"Precision               | {m_base['precision']:<22} | {m_lr['precision']:<28}")
    print(f"Recall                  | {m_base['recall']:<22} | {m_lr['recall']:<28}")
    print(f"F1 Score                | {m_base['f1']:<22} | {m_lr['f1']:<28}")
    print(f"ROC-AUC                 | {m_base['roc_auc']:<22} | {m_lr['roc_auc']:<28}")
    print(f"True Positives (TP)     | {m_base['true_positives']:<22} | {m_lr['true_positives']:<28}")
    print(f"False Positives (FP)    | {m_base['false_positives']:<22} | {m_lr['false_positives']:<28}")
    print(f"True Negatives (TN)     | {m_base['true_negatives']:<22} | {m_lr['true_negatives']:<28}")
    print(f"False Negatives (FN)    | {m_base['false_negatives']:<22} | {m_lr['false_negatives']:<28}")
    print(f"--------------------------------------------------------------------------------")

    print(f"\nTop Standardized Feature Coefficients (Logistic Regression):")
    for item in meta["coefficients"][:6]:
        print(f"  {item['direction']:<14} | Coef: {item['coefficient']:>7.4f} | {item['feature']}")

    # 6. Inference Smoke Test & Latency Benchmark
    print(f"\n[5/5] Testing serialized model inference and measuring latency...")
    predictor = PredictiveMaintenancePredictor(
        model_path=models_dir / "predictive_maintenance_model.joblib",
        metadata_path=models_dir / "model_metadata.json",
    )

    pos_samples = df[df["target_7d"] == 1]
    sample_row = pos_samples.iloc[0].to_dict() if len(pos_samples) > 0 else df.iloc[0].to_dict()
    pred_res = predictor.predict_single(vin=sample_row["vin"], features_dict=sample_row)

    print(f" -> Smoke Prediction for {pred_res.vin}:")
    print(f"    7-Day Failure Risk: {pred_res.probability_7d * 100:.1f}% ({pred_res.risk_level})")
    print(f"    Maintenance Action Required: {pred_res.predicted_maintenance_required}")
    print(f"    Top Risk Factors: {[f.feature_name + f' (+{f.contribution:.2f})' for f in pred_res.top_risk_factors]}")

    # Latency benchmark on 1,000 predictions
    batch_records = [df.iloc[idx % len(df)].to_dict() for idx in range(1000)]
    latencies_ms = []
    for r in batch_records:
        t_start = time.perf_counter()
        _ = predictor.predict_single(vin=r["vin"], features_dict=r)
        latencies_ms.append((time.perf_counter() - t_start) * 1000.0)

    p50_lat = np.percentile(latencies_ms, 50)
    p95_lat = np.percentile(latencies_ms, 95)
    mean_lat = np.mean(latencies_ms)

    print(f"\n -> ML Inference Latency Benchmark (1,000 requests):")
    print(f"    p50 Latency: {p50_lat:.3f} ms")
    print(f"    p95 Latency: {p95_lat:.3f} ms")
    print(f"    Avg Latency: {mean_lat:.3f} ms")
    print(f"================================================================================")
    print(f"ML Pipeline execution successful.")


if __name__ == "__main__":
    main()
