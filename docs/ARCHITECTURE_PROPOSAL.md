# Architecture Proposal: FleetGuard Pulse

**Status:** REVISED ARCHITECTURE PROPOSAL (FINAL REVIEW — PENDING LOCK)  
**Selected Problem Space:** Connected Vehicle Predictive Maintenance & Vehicle Health Intelligence  
**Product Name:** FleetGuard Pulse  
**Primary User:** Fleet Maintenance Manager  
**Fleet Scope:** Mixed Powertrains (Internal Combustion Engine [ICE], Hybrid Electric Vehicle [HEV], Battery Electric Vehicle [BEV])  

---

## 1. Executive Summary & Problem Framing

Commercial fleet operations managing tens of thousands of mixed-powertrain assets suffer from catastrophic, preventable mechanical breakdowns, excessive roadside downtime, and spiraling maintenance costs. Traditional telematics systems either poll at coarse intervals—missing rapid thermal and pressure transients—or produce overwhelming alert noise without actionable diagnostic context or forward-looking prognostic intelligence.

**FleetGuard Pulse** is an enterprise-scale connected vehicle intelligence platform engineered to ingest, process, detect, predict, and analyze vehicle health telemetry across 100,000+ commercial vehicles in real time. The solution is strictly focused on **predictive maintenance and vehicle health intelligence** across mixed fleets (ICE, Hybrid, EV). It unifies:
1. High-throughput telemetry ingestion over partitioned streaming message queues.
2. Independent fan-out stream consumers ensuring decoupled critical alerting and historical persistence.
3. Sub-5-second critical mechanical fault detection and dispatch.
4. Machine-learning-driven **7-day failure probability forecasting** alongside diagnostic signature vector matching.
5. 3NF relational fleet maintenance and work-order management with demonstrable SQL optimization.
6. Columnar batch analytics for fleet-wide component reliability and Mean Time Between Failures (MTBF).

*Note: Safety intelligence has been removed from the product scope; FleetGuard Pulse is exclusively dedicated to vehicle health and predictive maintenance.*

---

## 2. Architecture Goals & Non-Functional Targets

All performance metrics listed below represent **engineering targets to be empirically validated**, rather than claimed results. Acceptance strictly requires benchmark logs and empirical test evidence generated during subsequent phases.

- **Ingestion Throughput Target:** Sustained 100,000+ events/second across 100,000+ simulated vehicles.
- **Burst Tolerance Target:** Sustain a 3x burst (300,000 events/second) for 5 continuous minutes without data loss.
- **Critical Alert Latency Target:** Critical mechanical alerts detected and delivered via WebSocket/push in under 5 seconds from initial event ingestion.
- **Dashboard Latency Target:** Fleet health overview and telemetry drill-downs resolve in under 2 seconds.
- **API Performance Target:** API latency p95 under 200 ms and p99 under 500 ms under baseline operating load.
- **Availability Target:** 99.9% uptime design target with zero Single Point of Failure (SPOF) on critical ingestion and alerting paths.

### Planned Benchmark Validations
To prove these targets empirically, two distinct benchmark test suites will be implemented and measured:
- **Benchmark Suite A: End-to-End Realistic Simulator Test:** A full-stack integration run with 100,000 simulated vehicles exhibiting gradual mechanical wear, noise, out-of-order packets, duplicates, and periodic critical faults, evaluating end-to-end alert latency and pipeline stability.
- **Benchmark Suite B: Maximum-Throughput Load Benchmark:** A dedicated load generator (e.g., Locust/k6) executing sustained 100K+ events/s and 300K events/s 3x burst traffic directly against the ingestion gateway, evaluating broker back-pressure, drop rate, and consumer lag.

---

## 3. Core Product Scope

The product scope is strictly bounded to five core features:

- **F-01: 100K+ Vehicle Telemetry Simulator**  
  A custom-built, multi-worker telemetry generator simulating at least 100,000 unique vehicles using deterministic seeds. Simulates normal operation, progressive degradation curves, transient sensor noise, severe mechanical faults, duplicate payloads, out-of-order timestamps, and burst traffic across mixed powertrains (ICE, Hybrid, EV).
- **F-02: Real-Time Vehicle Health Detection and Critical Alerts**  
  A streaming ingestion and processing pipeline that evaluates live telemetry streams against threshold models and statistical anomaly algorithms, generating prioritized alerts (Warning, Critical) with sub-5-second dispatch.
- **F-03: Diagnostic Signature Vector Search**  
  A vector similarity retrieval subsystem utilizing `pgvector` inside PostgreSQL to compare multi-dimensional sensor anomaly embeddings against a catalog of verified historical failure signatures to identify probable root causes.
- **F-04: Fleet Maintenance Intelligence**  
  A 3NF relational management subsystem tracking fleets, depots, vehicle assets, diagnostic trouble codes (DTC), technician assignments, and maintenance work orders, featuring demonstrable SQL query optimization with `EXPLAIN ANALYZE`.
- **F-05: Historical Reliability Analytics**  
  A columnar analytical subsystem powered by ClickHouse computing fleet-wide MTBF, component degradation trends, failure frequencies by make/model, and preventative maintenance schedules across historical event archives.

---

## 4. Telemetry Data Model

The telemetry schema represents mixed fleets with unified common headers and powertrain-specific signals:

### 4.1 Common Telemetry Header
- `event_id`: UUIDv4 (Unique event identifier for idempotency/dedup)
- `vin`: String (17-character standardized Vehicle Identification Number)
- `timestamp`: ISO-8601 UTC timestamp (Microsecond precision)
- `sequence_number`: Int64 (Monotonically increasing sequence number per VIN)
- `vehicle_type`: Enum (`ICE`, `HYBRID`, `EV`)
- `latitude`: Float64 (Geographic latitude)
- `longitude`: Float64 (Geographic longitude)
- `speed_kph`: Float32 (Vehicle speed in km/h)
- `odometer_km`: Float64 (Cumulative distance traveled)
- `vibration_g`: Float32 (Tri-axial accelerometer peak magnitude in G)
- `dtc_codes`: Array[String] (Active Diagnostic Trouble Codes, e.g., `["P0117", "P0524"]`)

### 4.2 Powertrain-Specific Signals
- **ICE Vehicles:**
  - `engine_rpm`: Float32 (Engine rotational speed)
  - `coolant_temp_c`: Float32 (Engine coolant temperature in Celsius)
  - `oil_pressure_kpa`: Float32 (Engine oil pressure in kPa)
  - `fuel_level_pct`: Float32 (Fuel tank level percentage)
- **Hybrid Vehicles (HEV):**
  - `engine_rpm`: Float32
  - `coolant_temp_c`: Float32
  - `oil_pressure_kpa`: Float32
  - `battery_voltage_v`: Float32 (High-voltage traction battery voltage)
  - `battery_soc_pct`: Float32 (State of Charge percentage)
  - `battery_temp_c`: Float32 (Battery pack temperature)
- **Electric Vehicles (EV):**
  - `motor_rpm`: Float32 (Electric drive motor rotational speed)
  - `battery_voltage_v`: Float32 (High-voltage pack voltage)
  - `battery_soc_pct`: Float32 (State of Charge percentage)
  - `battery_temp_c`: Float32 (Pack cell temperature)
  - `cell_temp_delta_c`: Float32 (Max-to-min cell temperature differential)

### 4.3 Severity Classification
- **Ordinary Telemetry:** Normal operational ranges (e.g., Coolant 85–95°C, Oil Pressure 250–450 kPa, Vibration < 0.5G, Battery SoC 20–90%, No active DTCs).
- **Warning Conditions:** Threshold deviations indicating progressive wear (e.g., Coolant 100–108°C, Oil Pressure 150–200 kPa, Vibration 0.8–1.5G, Battery Temp 45–55°C, non-critical DTCs such as P0420 catalyst efficiency).
- **Critical Faults:** Severe mechanical failure risks requiring immediate shutdown (<5s alert target) (e.g., Catastrophic Oil Pressure Drop < 70 kPa under load, Severe Coolant Overheat > 115°C, Structural Vibration Spike > 3.0G, EV Cell Temp Anomaly > 65°C / Delta > 15°C, Engine Misfire / Mechanical Seizure DTCs P0300/P0524).

---

## 5. Predictive Maintenance Machine Learning Component

Rather than relying solely on retrospective threshold alarms or treating vector search as the predictive model, FleetGuard Pulse defines a dedicated, forward-looking machine learning capability.

### 5.1 Prediction Target
$$\text{Target } Y \in \{0, 1\} = \mathbb{P}(\text{Component Failure or Unplanned Maintenance Event within the next 7 days})$$
The model outputs a continuous calibrated risk probability score $p \in [0.0, 1.0]$. A vehicle with $p \ge \tau$ (e.g., $\tau = 0.65$) triggers preventative work-order scheduling before an on-road breakdown occurs.

### 5.2 Synthetic Data-Generation Strategy (Leakage-Free Wear Progression)
To ensure machine learning models can be trained and evaluated without synthetic data leakage:
1. **Four-Phase Vehicle Lifecycle Simulation:** Every simulated vehicle advances through a physical state machine:
   $$\text{Healthy} \longrightarrow \text{Degradation} \longrightarrow \text{Warning} \longrightarrow \text{Failure}$$
   - *Healthy (Days 0–60):* Standard sensor readings with stochastic Gaussian noise.
   - *Degradation (Days 61–85):* Subtle linear/exponential drift (e.g., oil pressure baseline dropping 1.5 kPa/day, coolant temperature rising 0.4°C/day, vibration increasing).
   - *Warning (Days 86–92):* Frequent threshold excursions, intermittent warning DTCs, high variance under load.
   - *Failure (Day 93):* Critical fault event (loss of oil pressure, engine seizure, coolant rupture).
2. **Strict Temporal Feature Extraction (No Lookahead Leakage):**
   - Features are computed exclusively from telemetry within an observation window $[T - 14\text{ days}, T]$.
   - Ground-truth label $Y$ is defined solely by whether a failure event occurs within the future prediction horizon $(T, T + 7\text{ days}]$.
   - No features contain information from after timestamp $T$.

### 5.3 Candidate Feature Set
- **Thermal Features:** Mean coolant temp, max coolant temp, slope of coolant temp over 7 days, coolant-to-ambient differential.
- **Pressure Features:** Mean oil pressure under load (>1500 RPM), oil pressure decay slope, minimum observed oil pressure.
- **Kinematic & Mechanical Features:** RPM variance, load factor, tri-axial peak vibration RMS magnitude, vibration frequency shifts.
- **Electrical Features (EV/HEV):** Battery voltage sag under acceleration, cell temperature differential ($\Delta T$), pack resistance proxy.
- **Operational History:** Odometer reading, cumulative operating hours, days since last preventative maintenance service.
- **Diagnostic Signal Counts:** Count of distinct DTCs in the last 7 days, count of streaming Z-score anomaly triggers in the last 48 hours.

### 5.4 Model Selection & Baseline Comparison
- **Baseline 1 (Simple Rule-Based Heuristic):** A deterministic threshold rule: Flag failure if $(\text{oil\_pressure} < 180\text{ kPa} \land \text{temp} > 102^\circ\text{C}) \lor (\text{count}(\text{DTCs}) \ge 2)$.
- **Baseline 2 (Primary ML Model):** **Logistic Regression** with L2 regularization (Scikit-Learn).
  - *Rationale:* Highly interpretable, well-calibrated probabilistic output, low computational footprint, robust against overfitting on structured tabular features.
  - *Secondary Candidate:* Random Forest / Gradient Boosting Classifier for non-linear feature interactions if warranted.
- **Evaluation Metrics (To Be Measured Later):** Precision, Recall, F1-Score, ROC-AUC, and PR-AUC. The ML model must demonstrate statistically significant recall improvements over the rule-based baseline while maintaining actionable precision.
- **Distinction from Vector Search:** Diagnostic signature vector search (`pgvector`) is a **supporting root-cause categorization capability** that matches an active anomaly fingerprint to historical failure archetypes. It is **not** the predictive 7-day failure forecasting model.

---

## 6. Decoupled Real-Time Streaming Pipeline

A single monolithic worker must never synchronously write to every datastore. FleetGuard Pulse utilizes **Redpanda fan-out with independent, isolated consumer groups** to guarantee that slow downstream analytical writes or database locks never block the critical alerting path.

```
                    ┌────────────────────────────────────────────────────────┐
                    │      100K+ Vehicle Telemetry Simulator (F-01)          │
                    └───────────────────────────┬────────────────────────────┘
                                                │ HTTP POST Batches
                                                ▼
                    ┌────────────────────────────────────────────────────────┐
                    │        Ingestion Gateway (FastAPI / Uvicorn)           │
                    │   - High-concurrency async I/O                         │
                    │   - Back-pressure aware broker buffering               │
                    └───────────────────────────┬────────────────────────────┘
                                                │ Partition Key: VIN
                                                ▼
                    ┌────────────────────────────────────────────────────────┐
                    │       Message Broker: Redpanda (Kafka-Compatible)      │
                    │      Topic: 'vehicle.telemetry.raw' (16 Partitions)    │
                    └───────┬───────────────────┬────────────────────┬───────┘
                            │                   │                    │
          Fan-out to        │                   │                    │
          Independent       │                   │                    │
          Consumer Groups   │                   │                    │
                            ▼                   ▼                    ▼
┌──────────────────────────────────────┐ ┌──────────────┐ ┌───────────────────┐
│ Real-Time Detection Consumer Group   │ │ MongoDB Raw  │ │ ClickHouse Batch  │
│ - Schema Validation (Pydantic v2)    │ │ Consumer     │ │ Analytics Consumer│
│ - Counting Bloom Filter Dedup        │ │ Group        │ │ Group             │
│ - Out-of-Order Seq Check (vs Redis)  │ │              │ │                   │
│ - Welford Variance & Threshold Rules │ │ Micro-batch  │ │ Micro-batch       │
│ - CRITICAL ALERT PATH (<5s)          │ │ bulk inserts │ │ columnar inserts  │
└──────────────────┬───────────────────┘ └──────┬───────┘ └─────────┬─────────┘
                   │                            │                   │
                   ▼                            ▼                   ▼
           ┌──────────────┐             ┌──────────────┐    ┌───────────────┐
           │   Redis 7    │             │  MongoDB 7   │    │  ClickHouse   │
           │  - Hot State │             │  - Raw Event │    │  - Columnar   │
           │  - Dedup Set │             │    Archive   │    │    Analytics  │
           │  - Alert Pub │             │  - Flexible  │    │  - MTBF/Rollup│
           └───────┬──────┘             │    Docs      │    └───────┬───────┘
                   │                            └──────────────┘            │
                   │ Pub/Sub Notification                                   │
                   ▼                                                        │
┌──────────────────────────────────────────────────────────────┐            │
│             FleetGuard API & Alert Service (FastAPI)         │            │
│    - WebSocket push to active dashboard clients              │◄───────────┘
│    - Diagnostic Signature Vector Search (pgvector) (F-03)    │
│    - Fleet Maintenance Intelligence (3NF SQL) (F-04)         │
│    - Historical Analytics Endpoints (F-05)                   │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│           PostgreSQL 16 + pgvector (Relational Core)         │
│    - 3NF Schema: fleets, vehicles, depots, work_orders       │
│    - pgvector: HNSW diagnostic anomaly signature embeddings  │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│             Web Dashboard (React + Vite + Leaflet)           │
│    - Sub-5s critical alert ticker via WebSocket              │
│    - Real-time fleet health & geospatial view (<2s)          │
│    - Diagnostic signature root-cause modal                   │
│    - Historical reliability & MTBF analytics views           │
└──────────────────────────────────────────────────────────────┘
```

### 6.1 Critical Alert Path (Decoupled from Historical Persistence)
1. **Redpanda Ingestion:** Ingestion gateway accepts telemetry batches and produces to `vehicle.telemetry.raw` partitioned strictly by `vin`.
2. **Real-Time Detection Consumer:** Reads from its dedicated consumer group:
   - Validates schema via compiled `Pydantic v2`.
   - Checks the in-memory Counting Bloom Filter for event duplicate suppression.
   - Evaluates incoming sequence number and timestamp against Redis latest state.
   - Runs Welford's running variance algorithm and threshold rules.
   - On critical fault: Emits a structured alert to Redis Pub/Sub and commits an alert record to PostgreSQL.
   - Updates vehicle hot state in Redis (`HSET vehicle:{vin}`).
3. **Alert Dispatch:** The API service receives the Redis Pub/Sub event and broadcasts it over open WebSockets to subscribed React dashboard clients.
4. **Zero Blocking:** Because MongoDB and ClickHouse are managed by separate consumer groups, an analytical slow query or database bulk write in ClickHouse **never delays or blocks the critical alert path**.

### 6.2 Stream Processing Resilience Mechanisms
- **Back-Pressure Awareness:** Redpanda acts as a shock absorber. Ingestion Gateways reject requests (HTTP 429/503) only when broker connection limits are saturated. Stream consumers pull messages in batches configured to match worker processing capacity.
- **Consumer Group Offset Management:** Each consumer group independently manages its offsets. Consumer restarts resume from the last committed offset without message loss.
- **Partitioning by VIN:** All telemetry for a given VIN routes to the same Redpanda partition, guaranteeing strict per-vehicle ordering within the stream.
- **Durable Replayability:** Redpanda retains the commit log, enabling downstream consumers to replay streams from specific timestamps for testing, re-indexing, or disaster recovery.
- **Idempotency & Duplicate Handling:** Duplicate `event_id` payloads (e.g., from network retries) are intercepted by the Counting Bloom Filter and Redis short-lived idempotency set, logged as duplicate metrics, and discarded before state mutation.
- **Out-of-Order Handling:** If an event arrives with a timestamp or sequence number older than the vehicle's cached state in Redis:
  - It is **blocked** from overwriting the live vehicle state in Redis (preventing dashboard state regression).
  - It **is forwarded** to MongoDB and ClickHouse where true event timestamps maintain historical data integrity.

---

## 7. Polyglot Persistence & Data Flow Architecture

PostgreSQL is strictly protected as the transactional relational core and is **never used as the high-volume raw telemetry sink**.

```
[Redpanda Stream Ingestion]
        │
        ├──► [MongoDB 7] ──────────► Flexible raw telemetry event documents & unstructured payload archive
        │
        ├──► [ClickHouse] ─────────► High-volume columnar historical telemetry, MTBF & reliability aggregates
        │
        ├──► [Redis 7] ────────────► Hot vehicle operational state, active alerts, Bloom filter bitsets, cache
        │
        └──► [PostgreSQL 16] ──────► Authoritative 3NF business entities (fleets, vehicles, work orders, audits)
                   └── [pgvector] ─► Diagnostic failure signature vectors & HNSW similarity search
```

### 7.1 Store Responsibilities

| Datastore | Primary Role | Data Stored | Access Pattern | Consistency Requirement |
| :--- | :--- | :--- | :--- | :--- |
| **PostgreSQL 16** | Authoritative 3NF business core | Fleets, depots, vehicles, maintenance schedules, work orders, technicians, durable alert audit logs. | Low-to-medium volume transactional CRUD, relational joins, foreign-key enforcement. | **Strict ACID** (Serializable / Read Committed). |
| **pgvector** (In Postgres) | Diagnostic signature search | 8-dimensional normalized sensor anomaly embeddings, historical failure library. | Vector similarity queries via cosine distance (`<=>`). | **Strict ACID** (Integrated directly within PostgreSQL transactions). |
| **MongoDB 7** | High-volume flexible document store | Raw telemetry payloads, varying sensor configurations across OEM models, audit documents. | High-volume append-only writes, ad-hoc single-vehicle document lookups. | **Tunable Consistency** (`w:1` or `w:majority`), eventual consistency across secondaries. |
| **Redis 7** | Hot transient state & cache | Latest vehicle position (`lat`, `lon`), speed, current sensor values per VIN, active alert bitsets, dedup cache. | Extreme-low-latency sub-millisecond key-value reads/writes (`HGETALL`, `HSET`). | **Transient In-Memory**; eventual consistency with optional background persistence. |
| **ClickHouse** | Columnar analytical warehouse | Historical telemetry time-series, pre-aggregated reliability rollups, MTBF summaries, fault trends. | Micro-batch bulk inserts, parallel columnar scans, analytical group-by queries. | **Analytical Eventual Consistency**; block-level atomicity in MergeTree tables. |

---

## 8. CAP & PACELC Distributed Systems Analysis

Rather than applying broad, generic labels, the distributed systems tradeoffs for each storage and messaging component are analyzed against their specific role:

### 8.1 Redpanda (Messaging Broker)
- **CAP Classification:** **CP** (Consistency & Partition Tolerance).
- **PACELC Classification:** **PC/EC** (Under partition: Consistency over Availability; Else: Consistency over Latency).
- **Analysis:** Redpanda relies on the Raft consensus algorithm. In the event of a network partition, minority broker partitions refuse writes to prevent split-brain inconsistencies and message loss. This guarantees strict partition ordering and durable replayability.

### 8.2 PostgreSQL 16 & pgvector (Relational & Vector Store)
- **CAP Classification:** **CP** (Consistency & Partition Tolerance).
- **PACELC Classification:** **PC/EC**.
- **Analysis:** Serves as the single source of truth for business-critical entities (work orders, asset assignments, user permissions). Enforces ACID transactional guarantees and foreign key constraints. In a partition event, primary-node consistency is strictly preserved over cross-partition write availability.

### 8.3 MongoDB 7 (Raw Telemetry Document Store)
- **CAP Classification:** **CP** (Configured with replica sets and automatic failover).
- **PACELC Classification:** **PC/EC** (or **PA/EL** under unacknowledged writes `w:1`).
- **Analysis:** With primary-secondary replica sets, MongoDB maintains consistency by routing writes to the elected primary. For high-volume raw telemetry archiving, write concerns can be tuned to balance throughput against durability without impacting transactional business entities.

### 8.4 Redis 7 (In-Memory Hot State & Cache)
- **CAP Classification:** **AP** (Availability & Partition Tolerance).
- **PACELC Classification:** **PA/EL** (Under partition: Availability over Consistency; Else: Latency over Consistency).
- **Analysis:** Redis prioritizes sub-millisecond response latency and extreme availability. Transient vehicle coordinates and hot alert states tolerate minor replication lag between Redis primary and replica, as stale state is quickly overwritten by the next telemetry ping.

### 8.5 ClickHouse (Columnar Batch Analytics)
- **CAP Classification:** **AP** (Availability & Partition Tolerance).
- **PACELC Classification:** **PA/EL**.
- **Analysis:** Analytical queries operate across millions of historical rows where millisecond replication consistency is unnecessary. ClickHouse accepts bulk appends and merges them asynchronously via `MergeTree` engines, prioritizing parallel scan throughput and query availability over immediate transactional consistency.

---

## 9. Diagnostic Signature Vector Search (`pgvector`)

### 9.1 Problem Solved
When a vehicle exhibits multi-sensor deviations (e.g., slight coolant elevation, moderate oil pressure decline, and high-frequency vibration) without throwing an unambiguous DTC code, rule-based systems fail to categorize the root cause. Vector similarity search enables matching the vehicle's multivariate sensor state against cataloged historical failure fingerprints.

### 9.2 Vector Representation
Each diagnostic anomaly vector consists of an 8-dimensional normalized embedding representing the mechanical operating point:
$$\vec{v} = [\tilde{rpm}, \tilde{coolant\_temp}, \tilde{oil\_press}, \tilde{vibration}, \tilde{battery\_volt}, \tilde{battery\_temp}, \Delta_{press\_rpm}, \Delta_{temp\_load}]$$
All features are scaled to $[0.0, 1.0]$ based on operating envelopes.

### 9.3 Vector Indexing & Search Rationale
- **Index Engine:** `pgvector` inside PostgreSQL.
- **Index Type:** Hierarchical Navigable Small World (**HNSW**).
- **Distance Metric:** Cosine Distance (`<=>` operator in pgvector).
- **Index Configuration Plan:**
  - `m = 16` (Number of bidirectional links per node)
  - `ef_construction = 64` (Size of dynamic candidate list during construction)
  - Query parameter: `hnsw.ef_search = 40`
- **Complexity and Measurement Notice:**  
  *No theoretical logarithmic complexity is claimed as a guarantee.* In practice, HNSW provides approximate nearest-neighbor retrieval whose query latency, recall quality, and index construction duration depend on dataset distribution and graph parameters. **Actual query latency and top-k recall will be empirically benchmarked and documented during test execution.**

---

## 10. Core Algorithms & Data Structures

Every algorithm in FleetGuard Pulse solves a specific problem within the pipeline:

### 10.1 Counting Bloom Filter (Event Deduplication)
- **Problem Solved:** Rapidly detecting duplicate telemetry event IDs transmitted due to cellular network retries or simulator duplicate generation at 100K+ events/s without performing high-latency database lookups.
- **Rationale:** A standard Bloom Filter cannot handle deletions or sliding-window expiration; a Counting Bloom Filter uses small counters (e.g., 4 bits) per bucket, allowing time-decay or element eviction.
- **Pseudocode:**
  ```python
  def check_and_add(event_id: str) -> bool:
      hashes = [hash_k(event_id) for hash_k in HASH_FUNCTIONS]
      if all(counters[h] > 0 for h in hashes):
          return True  # Potential duplicate
      for h in hashes:
          counters[h] += 1
      return False  # Definitely not seen
  ```
- **Complexity:**
  - Time Complexity: $\mathcal{O}(k)$ where $k$ is the number of hash functions (constant time $\mathcal{O}(1)$ relative to stream volume).
  - Space Complexity: $\mathcal{O}(m)$ bits where $m$ is the bit-array length.
- **Measurement Plan:** Benchmark false-positive rate and lookup latency against 1,000,000 injected keys in pytest performance suite.

### 10.2 Welford's Algorithm (Streaming Variance & Running Z-Score)
- **Problem Solved:** Computing real-time mean and sample variance over continuous sensor signals (e.g., vibration, oil pressure) to detect statistical drift without storing historical samples in memory.
- **Rationale:** Standard variance formulas require two passes or suffer from numerical instability in single-pass implementations due to catastrophic floating-point cancellation.
- **Pseudocode:**
  ```python
  class WelfordAccumulator:
      def __init__(self):
          self.count = 0
          self.mean = 0.0
          self.M2 = 0.0

      def update(self, x: float):
          self.count += 1
          delta = x - self.mean
          self.mean += delta / self.count
          delta2 = x - self.mean
          self.M2 += delta * delta2

      def variance(self) -> float:
          return self.M2 / (self.count - 1) if self.count > 1 else 0.0
  ```
- **Complexity:**
  - Time Complexity: $\mathcal{O}(1)$ per update.
  - Space Complexity: $\mathcal{O}(1)$ state per sensor per vehicle.
- **Measurement Plan:** Measure execution time per 100,000 updates in isolation; verify numerical precision against numpy sample variance.

### 10.3 Exponentially Weighted Moving Average (EWMA) (Signal Smoothing)
- **Problem Solved:** Smoothing high-frequency sensor noise (e.g., vibration spikes caused by road potholes rather than engine bearing failures) to prevent false-positive alarms.
- **Rationale:** EWMA applies a decay weight $\alpha$ to prioritize recent readings while damping high-frequency transient spikes with negligible computation.
- **Pseudocode:**
  ```python
  def update_ewma(prev_ewma: float, current_val: float, alpha: float) -> float:
      return alpha * current_val + (1.0 - alpha) * prev_ewma
  ```
- **Complexity:**
  - Time Complexity: $\mathcal{O}(1)$ per signal.
  - Space Complexity: $\mathcal{O}(1)$ per vehicle signal state.
- **Measurement Plan:** Verify noise suppression curve on synthetic dirty telemetry in unit tests.

### 10.4 Geohash Spatial Indexing (Depot & Service Region Tracking)
- **Problem Solved:** Mapping 100,000 vehicle GPS coordinates into geographical maintenance depot clusters and service regions without expensive continuous polygon collision calculations.
- **Rationale:** Base32 Geohashing converts 2D (latitude, longitude) coordinates into hierarchical string prefixes, enabling spatial proximity lookups via string prefix matches.
- **Complexity:**
  - Time Complexity: $\mathcal{O}(L)$ where $L$ is geohash character precision length (constant time $\mathcal{O}(1)$).
  - Space Complexity: $\mathcal{O}(1)$ string representation.
- **Measurement Plan:** Evaluate depot allocation lookup speed across 100K vehicle positions.

---

## 11. Identity, Security & Governance Architecture

The security architecture establishes zero-trust boundaries across edge, ingestion, compute, and data layers:

```
[Vehicle Simulator / Edge Clients]
       │
       ▼ (mTLS / Token Auth)
[API Ingestion Gateway (FastAPI)] ◄─── Rate Limiting / Schema Validation
       │
       ▼
[Keycloak / OIDC Provider] ──────────► OAuth2 / OIDC Token Issuance & JWKS Verification
       │
       ▼
[FastAPI Core API Service] ──────────► JWT Validation & Role-Based Access Control (RBAC)
                                       ├── Admin: Full access, seed management, config
                                       ├── Dispatcher: Live fleet view, alert triage
                                       └── Technician: Work order updates, diagnostic inspect
```

- **Authentication & OIDC:** Centralized identity management via **Keycloak / OpenID Connect (OIDC)** provider issuing signed JWTs.
- **Role-Based Access Control (RBAC):** Granular permissions enforced at the FastAPI dependency layer (`Admin`, `Dispatcher`, `Technician`).
- **Tenant Isolation:** Fleet-level data scoping ensuring maintenance personnel only access assets within their assigned organizational hierarchy.
- **Transport & Storage Encryption:** Mandatory TLS 1.3 in transit; encryption at rest across PostgreSQL, MongoDB, Redis, and ClickHouse volumes.
- **Audit Logging:** Security-critical operations (work-order closure, alert silencing, user modifications) committed to an append-only audit log in PostgreSQL.
- **Least Privilege:** Internal services utilize distinct database credentials with minimal required privileges (e.g., analytics consumer has read/write on ClickHouse but zero access to PostgreSQL user credentials).
- **Device Identity:** Architecture accommodates future mutual TLS (mTLS) certificate-based authentication for vehicle edge clients.
- *Notice: These security controls represent architectural designs to be implemented and verified in subsequent development phases.*

---

## 12. Observability & Monitoring Architecture

Observability is engineered to provide end-to-end operational visibility across the distributed ingestion, streaming, and storage pipeline:

```
[All Services & Datastores]
       │
       ├──► Metrics ────────► [Prometheus] ──────► [Grafana Dashboards]
       │
       ├──► Traces  ────────► [OpenTelemetry] ───► Distributed Trace Visualizer
       │
       └──► Logs    ────────► [Promtail / Loki] ─► Centralized Log Inspection
```

### Monitored Key Performance Indicators (KPIs)
- **Ingress Rate:** Total incoming telemetry events per second.
- **Consumer Lag:** Pending uncommitted message count per Redpanda partition across each independent consumer group.
- **Critical Alert Latency:** Duration from event generation timestamp to WebSocket client delivery (Target <5s).
- **API Latency Distribution:** Real-time p50, p95, and p99 response times (Targets: p95 <200ms, p99 <500ms).
- **Processing Latency:** Time spent per event in schema validation, anomaly detection, and state mutation.
- **Pipeline Drop & Error Rates:** HTTP 4xx/5xx responses, malformed schema DLQ count, broker produce failures.
- **Duplicate & Out-of-Order Rates:** Counting Bloom Filter hit count, out-of-order sequence detections.

---

## 13. Cloud Portability & Infrastructure as Code (IaC)

FleetGuard Pulse is architected for strict cloud portability:

- **Containerization:** All services packaged as lightweight multi-stage Docker images.
- **12-Factor Configuration:** All configuration injected through environment variables (`DATABASE_URL`, `BROKER_BOOTSTRAP_SERVERS`, `REDIS_URL`, `CLICKHOUSE_HOST`). Zero hardcoded connection parameters.
- **Zero Cloud-Specific Application Code:** Applications interact strictly via open-source protocols (Kafka protocol, Postgres wire protocol, MongoDB wire protocol, ClickHouse native protocol).
- **Local Orchestration:** One-command reproducible local environment via `docker compose up`.
- **Cloud Infrastructure (Terraform):** Modular Terraform templates targeting AWS:
  - AWS ECS Fargate or EKS for compute containers.
  - Amazon MSK or EC2-hosted Redpanda cluster.
  - Amazon RDS for PostgreSQL with `pgvector`.
  - Amazon DocumentDB or EC2-hosted MongoDB.
  - Amazon ElastiCache for Redis.
  - Self-hosted ClickHouse on EBS-backed EC2.
- **Portability Assurance:** Cloud infrastructure manifests may differ across providers (AWS vs GCP vs Azure vs on-premises Kubernetes), but **application container images and source code remain 100% identical and portable**.

---

## 14. Relational 3NF Schema & Demonstrable SQL Optimization

### 14.1 3NF Normalized Schema (PostgreSQL)
The operational relational schema strictly enforces Third Normal Form (3NF) to eliminate update anomalies:
- `organizations`: `(org_id PK, name, created_at)`
- `fleets`: `(fleet_id PK, org_id FK, name, region)`
- `depots`: `(depot_id PK, fleet_id FK, name, latitude, longitude, capacity)`
- `vehicles`: `(vin PK, fleet_id FK, depot_id FK, vehicle_type, make, model, year, status)`
- `diagnostic_trouble_codes`: `(dtc_code PK, description, severity, system_category)`
- `vehicle_alerts`: `(alert_id PK, vin FK, dtc_code FK, severity, trigger_value, created_at, resolved_at)`
- `work_orders`: `(work_order_id PK, alert_id FK, vin FK, assigned_technician_id, priority, status, created_at)`
- `technicians`: `(technician_id PK, depot_id FK, name, certification_level, email)`
- `diagnostic_signatures`: `(signature_id PK, fault_name, category, embedding vector(8), created_at)`

### 14.2 SQL Optimization & `EXPLAIN ANALYZE` Demonstration Plan
To satisfy **REQ-015** with verifiable evidence:
1. **Target Query:** High-frequency maintenance dashboard query joining `vehicles`, `vehicle_alerts`, and `work_orders` over 100,000+ vehicle records, filtering by active critical status and depot region.
2. **Unoptimized Baseline:** Query executed on unindexed foreign keys and non-partitioned tables, resulting in sequential table scans (`Seq Scan`) with high execution duration. `EXPLAIN ANALYZE` execution plans will be recorded and captured.
3. **Optimized Implementation:**
   - Addition of composite B-Tree indexes on `(vin, created_at DESC)` and `(fleet_id, status)`.
   - Table range partitioning on `vehicle_alerts` by `created_at`.
   - Elimination of correlated subqueries.
4. **Deliverable Evidence:** Side-by-side `EXPLAIN ANALYZE` query plans demonstrating reduction in planning time, execution time, and total disk page fetches will be published in the technical write-up.

---

## 15. Acceptance Requirement Governance Mapping

To ensure absolute adherence to project governance:
- **Architecture Coverage:** The architecture described herein is explicitly designed to address all 44 requirements in [`docs/ACCEPTANCE_CHECKLIST.md`](file:///Users/govindjee/Downloads/fleetguard-hackathon/docs/ACCEPTANCE_CHECKLIST.md) (`REQ-001` through `REQ-044`).
- **Implementation State:** All requirements currently remain `NOT_STARTED`. No application code has been written.
- **Evidence Requirement:** No requirement will be transitioned to `DONE` without empirical test execution logs, benchmark reports, scan outputs, and submission artifacts.

---

## 16. Implementation Risks & Mitigation Strategies

1. **Local Host Resource Contention:** Concurrently running Redpanda, PostgreSQL, MongoDB, Redis, ClickHouse, and Python workers on a local development laptop could saturate memory.  
   *Mitigation:* Apply strict container memory reservations and limits in `docker-compose.yml` (e.g., constraining ClickHouse buffer pools and MongoDB cache size for local development).
2. **100K Vehicle Simulation Throughput:** Emitting 100,000+ events/sec from Python generators on a single host machine can be limited by the Global Interpreter Lock (GIL).  
   *Mitigation:* Engineer the custom simulator using multi-process batched generators emitting compressed multi-event payloads.
3. **Synthetic Progression Realism without Data Leakage:** Modeling believable degradation curves across 100K vehicles while strictly preventing lookahead bias in ML feature extraction.  
   *Mitigation:* Enforce a strict state-machine simulation model where ML training sets are generated with separated observation windows and future prediction horizons.
