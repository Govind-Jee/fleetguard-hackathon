# FleetGuard Pulse — Predictive Maintenance Machine Learning Design

**Status:** APPROVED & IMPLEMENTED (Audited with Purged Temporal Split)  
**Decision Supported:** Estimate the probability that a vehicle will require maintenance or experience an unscheduled failure within the next 7 days: $P(\text{TARGET\_7D} = 1 \mid \mathcal{F}_t)$  
**Primary Model:** Scikit-Learn `LogisticRegression` Pipeline with median imputation and standard scaling  
**Baseline Model:** Deterministic Rule-Based Sensor Threshold Baseline  
**Artifact Path:** `data/models/predictive_maintenance_model.joblib`  
**Metadata Path:** `data/models/model_metadata.json`  

---

## 1. Problem Formulation & Scope

### 1.1 Core Decision Objective
In fleet operations, reactive maintenance results in costly roadside breakdowns, emergency towing, and schedule disruption. Conversely, scheduled maintenance based purely on calendar intervals risks servicing healthy assets prematurely while missing acute mechanical failures.

FleetGuard Pulse formulates predictive maintenance as a **7-Day Binary Risk Estimation Problem**:
$$\text{TARGET\_7D}_t = \begin{cases} 1 & \text{if a maintenance or failure event occurs in } (t, t + 7\text{ days}] \\ 0 & \text{otherwise} \end{cases}$$

The objective is to produce a well-calibrated posterior probability:
$$\hat{p}_t = \sigma(\beta_0 + \sum_{i=1}^{M} \beta_i \tilde{x}_{i,t}) \in [0.0, 1.0]$$
enabling fleet managers to prioritize workshop inspections before physical roadside breakdown occurs.

### 1.2 Evaluation Objective & Vehicle Generalization Scope
- **Evaluation Type:** **Temporal Future Prediction on a Monitored Fleet Population**.
- **Scope Clarification:** The model is deployed on an active monitored commercial fleet, observing vehicles over time to forecast which specific vehicles will require maintenance over the next 7 days based on their recent telemetry degradation trajectories.
- **Unseen Vehicle Boundary:** This evaluation measures temporal generalization into the future for monitored assets. It is **not** an out-of-sample zero-shot generalization claim for completely unmonitored vehicle models or unobserved external fleets.

### 1.3 Boundary Clarifications
- **No Remaining Useful Life (RUL) Regression:** RUL estimation introduces severe survival bias and high variance under sparse failure telemetry. Fleet managers operate on weekly dispatch schedules; a 7-day binary risk horizon matches real dispatch decision cycles.
- **pgvector Vector Search vs ML Distinction:**
  - **F-03 (pgvector):** Real-time diagnostic signature template matching (cosine distance against cataloged failure vectors).
  - **F-04 (ML Component):** Forward-looking 7-day risk probability estimation across longitudinal historical features.
  The two systems are completely decoupled.

---

## 2. Temporal Windowing & Purged Splitting Architecture

### 2.1 The Label Horizon Overlap Problem
In standard time-series splits, observations are partitioned strictly by cutoff timestamp:
$$\text{Train: } [T_0, T_1], \quad \text{Validation: } [T_1, T_2], \quad \text{Test: } [T_2, T_3]$$
However, when predicting a forward-looking 7-day target $\text{TARGET\_7D}_t$, a training sample at $t = T_1 - 1\text{ day}$ queries outcomes up to $T_1 + 6\text{ days}$. This means ground truth outcomes from the **validation period** directly determine the label of training observations.

### 2.2 Purged Temporal Splitting Architecture
To completely eliminate temporal label-horizon overlap, FleetGuard Pulse implements **Purged Temporal Splitting** with two explicit 7-day non-overlapping purge buffers:

```
Timeline:  Day 14                               Day 44.5          Day 51.5          Day 60.5          Day 67.5           Day 83
            [======================================|*****************|=================|*****************|====================]
            <--------- TRAIN PERIOD -------------->|  PURGE GAP 1    |<-- VAL PERIOD ->|  PURGE GAP 2    |<--- HELD-OUT TEST ->
                                                   | (7.0 Days Drop) |                 | (7.0 Days Drop) |
```

### 2.3 Exact Mathematical Boundary Rules
Let $H = 7.0001\text{ days}$ be the forward label horizon.
1. **Train Set:**
   $$\mathcal{D}_{\text{train}} = \{ (x_k, t_k, y_k) \mid t_k \le T_{\text{train\_end}} \}$$
2. **Purge Gap 1 (Excluded from training & validation):**
   $$\mathcal{G}_1 = \{ (x_k, t_k, y_k) \mid T_{\text{train\_end}} < t_k < T_{\text{val\_start}} \}$$
   where $T_{\text{val\_start}} = T_{\text{train\_end}} + H$.
3. **Validation Set:**
   $$\mathcal{D}_{\text{val}} = \{ (x_k, t_k, y_k) \mid T_{\text{val\_start}} \le t_k \le T_{\text{val\_end}} \}$$
4. **Purge Gap 2 (Excluded from validation & test):**
   $$\mathcal{G}_2 = \{ (x_k, t_k, y_k) \mid T_{\text{val\_end}} < t_k < T_{\text{test\_start}} \}$$
   where $T_{\text{test\_start}} = T_{\text{val\_end}} + H$.
5. **Held-Out Test Set:**
   $$\mathcal{D}_{\text{test}} = \{ (x_k, t_k, y_k) \mid t_k \ge T_{\text{test\_start}} \}$$

### 2.4 Mathematical Invariant Guarantees
- **Train-to-Val Invariant:** For every training observation $t \in \mathcal{D}_{\text{train}}$:
  $$t + 7.0\text{ days} \le T_{\text{train\_end}} + 7.0\text{ days} < T_{\text{val\_start}} \le \min_{t' \in \mathcal{D}_{\text{val}}} t'$$
  *The entire 7-day future outcome window of every training observation concludes before the earliest validation observation takes place.*
- **Val-to-Test Invariant:** For every validation observation $t \in \mathcal{D}_{\text{val}}$:
  $$t + 7.0\text{ days} \le T_{\text{val\_end}} + 7.0\text{ days} < T_{\text{test\_start}} \le \min_{t'' \in \mathcal{D}_{\text{test}}} t''$$
  *The entire 7-day future outcome window of every validation observation concludes before the earliest test observation takes place.*

---

## 3. Feature Engineering & Synthetic Shortcut Audit

All 26 features represent backward aggregations strictly over $[t_{\text{obs}} - 14\text{ days}, t_{\text{obs}}]$:

| Feature Name | Powertrain | Type | Mathematical Formula / Extraction | Domain Justification | Synthetic Shortcut Audit |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `speed_mean` | All | Float | $\frac{1}{N} \sum v_k$ | Average operating speed | Independent duty cycle metric |
| `speed_std` | All | Float | $\sqrt{\frac{1}{N} \sum (v_k - \bar{v})^2}$ | Driving speed volatility | Independent duty cycle metric |
| `vibration_mean` | All | Float | $\frac{1}{N} \sum G_k$ | Baseline structural vibration | Progressive mechanical signal |
| `vibration_std` | All | Float | $\sigma(G)$ | Vibration dispersion | Progressive mechanical signal |
| `vibration_max` | All | Float | $\max(G_k)$ | Peak mechanical impact shock | Progressive mechanical signal |
| `odometer_delta` | All | Float | $\text{odo}(t) - \text{odo}(t - 14\text{d})$ | Distance accumulated in window | Independent fleet mileage |
| `dtc_count` | All | Integer | $\sum \mathbf{1}(\text{DTC logged})$ | Diagnostic trouble codes logged | **Audited:** Ambient 4% noise on healthy assets; not a zero-noise proxy |
| `anomaly_count` | All | Integer | $\sum \mathbf{1}(\text{Anomaly flagged})$ | Real-time sensor threshold trips | **Audited:** Ambient 12% noise on healthy assets; progressive escalation |
| `telemetry_event_count` | All | Integer | $N$ | Data transmission frequency | Uptime metric |
| `coolant_temp_mean` | ICE / HEV | Float | $\frac{1}{N} \sum T_{\text{coolant}}$ | Thermal equilibrium temperature | Physical thermal measurement |
| `coolant_temp_std` | ICE / HEV | Float | $\sigma(T_{\text{coolant}})$ | Thermal stability | Physical thermal measurement |
| `coolant_temp_trend` | ICE / HEV | Float | $\bar{T}_{3\text{d}} - \bar{T}_{14\text{d}}$ | Recent thermal drift | Leading degradation indicator |
| `oil_pressure_mean` | ICE / HEV | Float | $\frac{1}{N} \sum P_{\text{oil}}$ | Average lubrication pressure | Physical hydraulic measurement |
| `oil_pressure_min` | ICE / HEV | Float | $\min(P_{\text{oil}})$ | Critical low lubrication dips | Physical hydraulic measurement |
| `oil_pressure_trend` | ICE / HEV | Float | $\bar{P}_{3\text{d}} - \bar{P}_{14\text{d}}$ | Pressure loss trajectory | Leading degradation indicator |
| `engine_rpm_mean` | ICE / HEV | Float | $\frac{1}{N} \sum \text{RPM}$ | Average engine operating speed | Independent engine duty cycle |
| `engine_rpm_std` | ICE / HEV | Float | $\sigma(\text{RPM})$ | RPM volatility | Independent engine duty cycle |
| `battery_voltage_mean` | ICE / HEV | Float | $\frac{1}{N} \sum V_{12}$ | 12V auxiliary alternator health | Physical electrical measurement |
| `soc_mean` | HEV / BEV | Float | $\frac{1}{N} \sum \text{SOC}$ | High-voltage battery state of charge | Physical battery measurement |
| `soc_min` | HEV / BEV | Float | $\min(\text{SOC})$ | Deep discharge severity | Physical battery measurement |
| `soc_drop_rate` | HEV / BEV | Float | $\Delta\text{SOC} / \Delta\text{km}$ | Battery energy efficiency degradation | Battery degradation indicator |
| `pack_voltage_mean` | HEV / BEV | Float | $\frac{1}{N} \sum V_{\text{pack}}$ | Traction pack voltage stability | Physical electrical measurement |
| `cell_temp_delta_mean` | HEV / BEV | Float | $\frac{1}{N} \sum \Delta T_{\text{cell}}$ | Average cell thermal divergence | Physical battery sensor metric |
| `cell_temp_delta_max` | HEV / BEV | Float | $\max(\Delta T_{\text{cell}})$ | Peak cell imbalance | Leading pack failure indicator |
| `days_since_last_maintenance` | All | Float | $(t - t_{\text{maint}}) / 86400$ | Elapsed time since last service | Historical maintenance registry |
| `km_since_last_maintenance` | All | Float | $\text{odo}(t) - \text{odo}(t_{\text{maint}})$ | Distance driven since last service | Historical maintenance registry |

### 3.1 Synthetic Shortcut Prevention
To prevent synthetic telemetry features from becoming artificial shortcuts:
1. **Ambient Background Noise:** Healthy vehicles have a 12% probability of logging transient anomaly events (e.g. road potholes, transient CAN latency) and a 4% probability of logging minor informational DTCs.
2. **Smooth Gradual Degradation:** Degradation trajectories progress over 3.5 to 9 days prior to failure. Observations taken early in degradation exhibit subtle, sub-threshold signal shifts rather than binary step-functions.
3. **Absence of Future Columns:** No target column or future timestamp exists in the feature matrix passed to scikit-learn.

---

## 4. Missing-Value Imputation Strategy

Because the fleet consists of mixed powertrains (ICE, HEV, and BEV):
- **BEVs** do not have internal combustion engines (`coolant_temp`, `oil_pressure`, `engine_rpm` are `NaN`).
- **ICEs** do not have high-voltage traction battery packs (`soc`, `pack_voltage`, `cell_temp_delta` are `NaN`).
- **HEVs** possess both hybrid battery and ICE subsystems.

### Principled Pipeline Imputation
The scikit-learn pipeline applies a **Median Imputation Strategy**:
```python
SimpleImputer(strategy='median')
```
- **Rationale**: For an engine feature absent on a BEV, replacing `NaN` with the training fleet median represents a neutral, uninformative baseline value. Coupled with subsequent z-score standardization (`StandardScaler`), the standardized value $\tilde{x}_i \approx 0.0$, contributing zero net log-odds change ($\beta_i \cdot 0 = 0$) to the BEV prediction.
- BEV risk is driven by battery and universal features (`anomaly_count`, `vibration`, `cell_temp_delta`), while ICE risk is driven by thermal and lubrication signals.

---

## 5. Model Architecture & Pipeline Design

```
Input Raw Feature Dict
         |
         v
+-----------------------------------+
|  1. Schema Alignment              | --> Aligns 26 canonical FEATURE_NAMES (coerces nulls)
+-----------------------------------+
         |
         v
+-----------------------------------+
|  2. SimpleImputer (median)        | --> Replaces powertrain NaNs with training medians
+-----------------------------------+
         |
         v
+-----------------------------------+
|  3. StandardScaler                | --> Transforms features: (x - mean) / std
+-----------------------------------+
         |
         v
+-----------------------------------+
|  4. LogisticRegression            | --> Computes log-odds z = beta_0 + sum(beta_i * z_i)
|     (class_weight='balanced')     | --> Applies sigmoid: P(target_7d = 1) = 1 / (1 + e^-z)
+-----------------------------------+
         |
         v
Output: Probability, Risk Level, and Linear Local Explanations
```

### 5.1 Hyperparameters
- `solver`: `lbfgs`
- `max_iter`: 1000
- `class_weight`: `balanced` (adjusts loss weights inversely proportional to class frequencies: $w_j = \frac{N}{2 \cdot N_j}$)
- `random_state`: 42
- `decision_threshold`: Configured via validation set F1 maximization ($0.85$), with default high-recall screening option ($0.50$).
