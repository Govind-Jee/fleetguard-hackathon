# Architecture Lock: FleetGuard Pulse

**STATUS: ARCHITECTURE LOCKED**

---

## 1. Architecture Governance & Change Management Rule

> **"No technology, service boundary, database, broker, framework, cloud provider, or architecture pattern may be changed after architecture lock without explicitly updating this file and explaining the reason."**

Any future architecture modification requires:
1. **Documented Reason:** Technical justification explaining why the locked decision cannot meet requirements.
2. **Affected Acceptance Requirements:** Enumeration of all impacted IDs from [`docs/ACCEPTANCE_CHECKLIST.md`](file:///Users/govindjee/Downloads/fleetguard-hackathon/docs/ACCEPTANCE_CHECKLIST.md).
3. **Trade-Off Analysis:** Explicit CAP/PACELC, performance, complexity, and resource impact analysis.
4. **Document Update:** Formal amendment to this file (`docs/ARCHITECTURE_LOCK.md`).
5. **Human Approval:** Mandatory human review and authorization before any code or configuration change.

---

## 2. Locked Architecture Decisions Matrix

Every architectural dimension is formally and irrevocably locked as follows:

| Component / Layer | Locked Decision | Status | Notes / Rationale |
| :--- | :--- | :--- | :--- |
| **Selected problem space** | **Connected Vehicle Predictive Maintenance & Vehicle Health Intelligence** | **LOCKED** | Domain exclusively dedicated to mixed-fleet predictive maintenance |
| **Primary user** | **Fleet Maintenance Manager** | **LOCKED** | Focus on maintenance workflows, fault alerts, and asset reliability |
| **Core solution scope** | **FleetGuard Pulse with exactly F-01 through F-05** | **LOCKED** | Strictly bounded five-feature scope |
| **Vehicle types** | **ICE + Hybrid + EV** | **LOCKED** | Mixed commercial fleet with powertrain-specific sensor extensions |
| **Messaging** | **Redpanda** | **LOCKED** | Kafka-compatible, C++ single-binary, zero JVM overhead, partitioned by VIN |
| **Relational** | **PostgreSQL 16** | **LOCKED** | Strict 3NF transactional business entities, ACID compliance, query optimization |
| **NoSQL** | **MongoDB 7** | **LOCKED** | High-volume flexible document storage for raw/semi-structured telemetry |
| **Cache** | **Redis 7** | **LOCKED** | Hot transient vehicle state, active alert bitsets, short-lived dedup cache |
| **Vector** | **pgvector** | **LOCKED** | Embedded HNSW vector similarity search inside PostgreSQL |
| **Batch analytics** | **ClickHouse** | **LOCKED** | Columnar analytical database for historical rollups, MTBF, degradation trends |
| **Backend** | **FastAPI + Python 3.11** | **LOCKED** | High-concurrency async REST, WebSocket push, Pydantic v2 schemas |
| **Stream processing** | **Python async workers / independent consumer groups** | **LOCKED** | Independent consumer groups for detection, MongoDB archive, and ClickHouse ingest |
| **Frontend** | **React + Vite** | **LOCKED** | Client-side SPA with Tailwind CSS, Lucide icons, and Leaflet mapping |
| **ML** | **scikit-learn Logistic Regression + deterministic rule baseline** | **LOCKED** | 7-day failure probability forecasting evaluated against deterministic baseline |
| **Algorithms** | **Counting Bloom Filter, Welford, EWMA, Geohash where required, cosine similarity** | **LOCKED** | Purpose-built algorithms with documented time and space complexity |
| **Identity** | **OIDC/OAuth2 + JWT; Keycloak supporting infrastructure** | **LOCKED** | Centralized token authentication; Keycloak as supporting identity provider |
| **Authorization** | **RBAC + tenant isolation** | **LOCKED** | Roles: Admin, Dispatcher, Technician; fleet-level tenant scoping |
| **Observability** | **Prometheus + Grafana + OpenTelemetry + Loki** | **LOCKED** | Metrics, dashboards, distributed tracing, and centralized logs (supporting infra) |
| **Local orchestration** | **Docker Compose** | **LOCKED** | Single-command local reproduction (`docker compose up`) |
| **CI** | **GitHub Actions** | **LOCKED** | Automated linting, test suites with coverage, security scans, container builds |
| **Cloud/IaC** | **Terraform + AWS initial deployment target** | **LOCKED** | Cloud-agnostic containers; Terraform templates for AWS (ECS/EKS, RDS, MSK) |

---

## 3. Fixed Five-Feature Scope

The product feature scope is strictly locked to these five capabilities:

- **F-01: 100K+ Vehicle Telemetry Simulator**  
  Custom multi-worker generator simulating 100K+ vehicles with deterministic seeds, realistic wear progressions, sensor noise, faults, duplicates, out-of-order events, and burst traffic across mixed powertrains (ICE, Hybrid, EV).
- **F-02: Real-Time Vehicle Health Detection and Critical Alerts**  
  Streaming ingestion pipeline detecting mechanical anomalies and dispatching critical alerts in <5s via Redis Pub/Sub, WebSockets, and durable alert logging.
- **F-03: Diagnostic Signature Vector Search**  
  Vector similarity retrieval via `pgvector` inside PostgreSQL matching multivariate anomaly embeddings against historical failure fingerprints using HNSW approximate nearest-neighbor search.
- **F-04: Fleet Maintenance Intelligence**  
  Authoritative 3NF relational fleet, depot, asset, and work-order management with demonstrable SQL optimization and `EXPLAIN ANALYZE` proof.
- **F-05: Historical Reliability Analytics**  
  Columnar analytical engine in ClickHouse computing fleet-wide MTBF, failure frequencies, and component degradation trends across historical telemetry archives.

---

## 4. Pipeline Paths & Data Flow

### 4.1 Critical Real-Time Path (Decoupled & Non-Blocking)
```
100K Vehicle Simulator
        │
        ▼
Ingestion Gateway (FastAPI)
        │ (Partition Key: VIN)
        ▼
Redpanda ('vehicle.telemetry.raw')
        │
        ▼ (Consumer Group: 'detection-workers')
Real-Time Detection Consumer
  - Schema Validation (Pydantic v2)
  - Counting Bloom Filter Dedup
  - Out-of-Order Sequence Check (vs Redis)
  - Welford Running Variance & Threshold Rules
        │
        ├──► Redis 7 (Hot State Update: HSET vehicle:{vin})
        │
        ▼ (Critical Alert Trigger)
Redis Pub/Sub ──► FastAPI WebSocket Service ──► React Dashboard (<5s Target)
```
*Historical persistence in MongoDB or ClickHouse runs in independent consumer groups and never blocks or delays the critical real-time alert path.*

### 4.2 Historical & Analytical Paths (Independent Consumer Groups)
- **Raw Telemetry Path:** Redpanda $\to$ `mongodb-raw-consumer` $\to$ MongoDB 7 (Flexible JSON document archive).
- **Batch Analytics Path:** Redpanda $\to$ `clickhouse-batch-consumer` $\to$ ClickHouse `MergeTree` (Columnar historical storage for MTBF and reliability queries).

### 4.3 Business Data Path
- **Relational Core:** PostgreSQL 16 (Strict 3NF tables: `fleets`, `depots`, `vehicles`, `work_orders`, `technicians`, `diagnostic_trouble_codes`, `vehicle_alerts`).
- **Access Pattern:** ACID transactional operations via FastAPI REST endpoints.

### 4.4 Diagnostic Vector Path
- Multi-dimensional sensor deviations $\to$ 8-dimensional normalized feature embedding $\to$ `pgvector` inside PostgreSQL $\to$ HNSW approximate nearest-neighbor query (cosine distance `<=>`) $\to$ Root-cause candidate failure profiles returned.

### 4.5 Predictive Maintenance ML Path
- Historical telemetry features computed strictly within past observation window $[T - 14\text{d}, T]$ $\to$ Leakage-free ground-truth label constructed from future prediction window $(T, T + 7\text{d}]$ $\to$ Train **Logistic Regression** model $\to$ Evaluate against deterministic rule-based baseline $\to$ Generate empirical precision, recall, F1, and ROC-AUC metrics upon test execution.

---

## 5. Locked Core Algorithms

Only algorithms directly serving functional components are locked:
1. **Counting Bloom Filter:** Fast streaming event ID deduplication ($\mathcal{O}(k)$ time, $\mathcal{O}(m)$ space).
2. **Welford's Algorithm:** Single-pass streaming mean and sample variance computation for real-time sensor anomaly Z-scores ($\mathcal{O}(1)$ time, $\mathcal{O}(1)$ space).
3. **Exponentially Weighted Moving Average (EWMA):** High-frequency sensor noise smoothing to prevent transient false alerts ($\mathcal{O}(1)$ time, $\mathcal{O}(1)$ space).
4. **Geohash Spatial Indexing:** Hierarchical string prefix mapping for vehicle-to-depot spatial clustering ($\mathcal{O}(L)$ time, $\mathcal{O}(1)$ space).
5. **Vector Cosine Similarity:** Anomaly fingerprint matching via `pgvector` HNSW index (approximate nearest-neighbor; latency and recall to be empirically measured).

---

## 6. Architecture Non-Goals

To prevent scope creep and maintain strict alignment with the problem statement:
- **No Separate Safety Product:** FleetGuard Pulse does not build driver safety scoring, collision liability, or insurance products.
- **No Charging-Optimization Product:** FleetGuard Pulse tracks EV battery health and thermal signals but does not build depot smart-charging grids or energy tariff bidding dispatchers.
- **No Unnecessary AI Agents:** No autonomous LLM agents or conversational assistants will be embedded into the critical operational pipeline.
- **No Real Personal / Vehicle-Owner Data:** The system operates strictly with synthetic VINs, synthetic driver identifiers, and simulated telematics.
- **No Granular Microservice Fragmentation:** Services remain bounded to clear functional domains (Simulator, Ingestion Gateway, Detection Stream Worker, Analytical Batch Ingest, Core API, Frontend). No unnecessary microservice proliferation.
- **Supporting Infrastructure Scope:** Keycloak, Loki, and OpenTelemetry are supporting infrastructure services for auth and observability; they are not user-facing product features.

---

## 7. Performance & Acceptance Governance

- **Target Framing:** All performance figures (100K+ events/s, 3x burst for 5 min, <2s dashboard latency, <5s critical alert latency, p95 < 200ms, p99 < 500ms, 99.9% uptime) remain strictly **engineering targets to be empirically validated**. None are claimed as achieved.
- **Model Evaluation:** ML metrics (precision, recall, F1, ROC-AUC) will be established only through rigorous test runs against held-out test splits.
- **Security & Cloud Validation:** OIDC, RBAC, TLS, and Terraform are design commitments to be proven during implementation and test phases.
- **Acceptance Checklist Integrity:** All 44 acceptance requirements in [`docs/ACCEPTANCE_CHECKLIST.md`](file:///Users/govindjee/Downloads/fleetguard-hackathon/docs/ACCEPTANCE_CHECKLIST.md) remain in `NOT_STARTED` status until verifiable code, test logs, and benchmark artifacts are produced.
