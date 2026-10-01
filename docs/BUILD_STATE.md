# Build State: FleetGuard

**PROJECT:** Connected Vehicle Intelligence Hackathon  
**CURRENT PHASE:** 11 - Distributed 100K/300K Performance Benchmark  

---

## Task Progress

### COMPLETED:
- Phase 0 - Specification Lock
- Phase 1 - Problem and Architecture Design
- Phase 2 - Architecture Locked
- Phase 2.1 - Architecture Lock Consistency Fix
- Phase 3 - Repository Foundation
- Phase 4 - 100K Vehicle Simulator
- Phase 4.1 - Simulator Evidence
- Phase 5 - Real-Time Processing Pipeline
- Phase 5.1 - Evidence Audit
- Phase 5.2 - Replay Evidence
- Phase 5.3 - Verified Checkpoint
- Phase 6 - PostgreSQL 3NF + pgvector
- Phase 6.1 - Database Audit
- Phase 6.2 - Verified Database Checkpoint
- Phase 7 - Predictive Maintenance ML
- Phase 7.1 - ML Temporal Leakage and Evaluation Validation
- Phase 7.2 - Verified ML Checkpoint Commit
- Phase 8 - FastAPI API Layer
- Phase 8.1 - API Evidence and Contract-Test Audit
- Phase 8.2 - ML Serving Feature-Parity Audit
- Phase 8.3 - Verified API/ML Serving Checkpoint
- Phase 9 - React FleetGuard Pulse Dashboard
- Phase 9.1 - UI Browser Acceptance and Credential Hygiene Audit
- Phase 9.2 - Verified Dashboard Checkpoint Commit
- Phase 10 - Historical Batch Analytics and Reliability Intelligence
- Phase 10.1 - ClickHouse Analytics Semantic Consistency Audit
- Phase 10.2 - Batch Analytics Acceptance Evidence Finalization
- Phase 10.3 - Verified Historical Analytics Checkpoint
- Phase 11 - Distributed 100K/300K Performance Benchmark

### IN PROGRESS:
Phase 11 distributed performance benchmark verified and archived

### BLOCKERS:
None

### NEXT STEP:
Phase 12 - Distributed Architecture Tradeoffs, Resilience, and Cloud Deployment Verification

---

## Phase 8, 8.1 & 8.2 Implementation & Evidence Summary

### 1. Production-Oriented FastAPI Architecture (`services/api/`)
- Implemented modular architecture separating app creation, configuration, database pooling, schemas, services, routers, auth, and metrics:
  - `config.py`: Environment-based settings for PostgreSQL, Redis, ClickHouse, Keycloak JWT, and ML models.
  - `db.py`: Thread-safe connection pooling via `psycopg2.pool.ThreadedConnectionPool`, Redis connection manager, and ClickHouse client.
  - `exceptions.py`: Structured error models preventing sensitive information leakage (no stack traces, credentials, or raw SQL exposed).
  - `metrics.py`: In-memory Prometheus-compatible collector exporting text exposition format at `GET /metrics`.
  - `security.py`: Middleware enforcing OWASP defensive headers (CSP, nosniff, DENY, XSS, Referrer-Policy, Permissions-Policy) and correlation request IDs.
  - `rate_limit.py`: Redis-backed atomic sliding-window rate limiter returning HTTP 429 and `Retry-After`.
  - `auth/`: Keycloak/OIDC-compatible JWT validator (`verify_jwt_token`), token creation helper, and RBAC dependency guards for `ADMIN`, `DISPATCHER`, and `TECHNICIAN`.

### 2. Comprehensive Endpoint Suite
- **Public & System Probes:**
  - `GET /health`: Liveness probe (HTTP 200).
  - `GET /ready`: Readiness probe verifying PostgreSQL, Redis, and ClickHouse connectivity.
  - `GET /metrics`: Standard Prometheus exposition metrics.
- **Vehicle Domain:**
  - `GET /vehicles`: Paginated vehicle list with tenant scoping, fleet filter, and powertrain filters (uses SQL `COUNT(*) OVER()`).
  - `GET /vehicles/{vin}`: Returns authoritative 3NF relational metadata and live Redis hot state.
  - `GET /vehicles/{vin}/health`: Operational health combining telemetry and durable alert counts.
  - `GET /vehicles/{vin}/risk`: Connects to `PredictiveMaintenancePredictor` for 7-day failure risk, local factor explainability, and short-lived Redis caching.
- **Operational Alerts & Fleets:**
  - `GET /alerts` & `GET /alerts/{alert_id}`: Durable alert records with tenant isolation.
  - `GET /fleets` & `GET /fleets/{fleet_id}/health`: Consolidated fleet health metrics computed via 2 optimized SQL aggregate queries (zero N+1 queries).
- **Diagnostics & Work Orders:**
  - `GET /diagnostics/similar`: 16-D pgvector cosine distance nearest-neighbor search (`embedding <=> %s::vector`).
  - `POST /maintenance/work-orders`: Validates vehicle and technician tenant ownership, creates normalized 3NF work orders.
- **Real-Time Push & Analytics:**
  - `GET /analytics/summary`: Lightweight fleet historical summary.
  - `WS /ws/alerts`: WebSocket alert push channel with heartbeat ping/pong support, multi-tenant scoping, and Redis-backed 120s idempotency deduplication (`AlertDispatcher`).

### 3. API Performance Benchmark (`scripts/benchmark_api.py`)
Measured across 100 requests per endpoint (macOS Apple Silicon, local sequential benchmark on warm connections):
- `GET /health`: Mean: **0.92 ms** | p50: **0.82 ms** | p95: **1.63 ms** | p99: **2.33 ms**
- `GET /vehicles`: Mean: **13.13 ms** | p50: **12.81 ms** | p95: **15.86 ms** | p99: **19.66 ms**
- `GET /vehicles/{vin}`: Mean: **3.56 ms** | p50: **3.47 ms** | p95: **4.61 ms** | p99: **5.30 ms**
- `GET /vehicles/{vin}/risk`: Mean: **3.39 ms** | p50: **3.19 ms** | p95: **4.67 ms** | p99: **4.95 ms**
- `GET /alerts`: Mean: **3.39 ms** | p50: **3.44 ms** | p95: **4.73 ms** | p99: **5.44 ms**
- `GET /fleets/{fleet_id}/health`: Mean: **21.97 ms** | p50: **20.98 ms** | p95: **29.69 ms** | p99: **42.35 ms**
- **SLA Result:** Every endpoint achieves **p95 < 30 ms** (target: $< 200\text{ ms}$) and **p99 < 45 ms** (target: $< 500\text{ ms}$) in local benchmark.
- **Scope Disclaimer:** Strictly a local sequential single-client benchmark; distributed scale load testing is reserved for Phase 11.

### 4. Automated Test Suite (113 Passing Tests)
- Total test suite count increased to **113 passing tests** (`pytest tests/ -q` in 3.65s):
  - 53 unit tests
  - 53 integration tests across API, security, ML serving consistency, ML pipeline, PostgreSQL 3NF, and stream processor
  - 7 OpenAPI 3.1 runtime contract tests (`tests/contract/test_api_contracts.py`)

### 5. ML Serving Feature-Parity Audit (Phase 8.2)
- Audited training feature semantics across all 26 model features.
- Eliminated all 8 unjustified fixed statistical defaults (`speed_std=12.5`, `vibration_std=0.08`, `odometer_delta=350.0`, `coolant_temp_std=2.5`, `coolant_temp_trend=0.15`, `oil_pressure_trend=-0.05`, `engine_rpm_std=250.0`, `soc_drop_rate=0.04`) and fabricated multipliers (`* 1.5`, `* 0.85`, `* 0.7`, `* 1.8`).
- Integrated ClickHouse 14-day backward window aggregates for historical features when $\ge 2$ observations are present.
- When historical or live telemetry is absent, features are cleanly set to `None`, allowing the scikit-learn pipeline's `SimpleImputer(strategy="median")` to substitute empirical training-set medians.
- Enforced strict vehicle-type powertrain masking (ICE vs BEV vs HEV) and schema ordering guards.
- Added comprehensive train/serve parity suite in `tests/integration/test_ml_serving_consistency.py` (6 tests).

---

## Phase 9 Implementation & Evidence Summary: React Dashboard

### 1. Locked Stack & Architecture Compliance
- Implemented React 18 single-page application in `frontend/` powered by Vite, Tailwind CSS, Leaflet (`react-leaflet`), and Lucide icons.
- Strictly adheres to `docs/ARCHITECTURE_LOCK.md`: no additional brokers, databases, or frameworks added.
- Development proxy configured in `vite.config.ts` mapping `/api` to `http://localhost:8000` and `/ws` to `ws://localhost:8000`.

### 2. Implemented Views & Subsystems
- **Fleet Overview (`/`)**: Fleet division switcher, 4 KPI cards (Monitored Vehicles, Availability %, Critical Alerts, High-Risk Assets), interactive Leaflet map with health-status colored pin markers, and a filterable/paginated vehicle table (by fleet, powertrain, and operational status).
- **Vehicle Details (`/vehicles/:vin`)**: Authoritative 3NF relational specifications (engine, battery, depot, fleet), live CAN-bus telemetry gauge card (speed, vibration, odometer, engine RPM, coolant temp, oil pressure, SOC %, pack voltage, cell temp delta), active DTC trouble codes, sequence number, GPS coordinates, and historical vehicle alert log.
- **Predictive Maintenance Risk Panel**: Prominent estimated 7-day maintenance risk probability (e.g., 38.4%), decision threshold marker (35%), model version (`logreg-v1-purged`), top risk factor contributions with z-scores/coefficients, protective factors, and mandatory probabilistic disclaimer notice. Integrated with 3NF maintenance work order dispatch modal (`POST /maintenance/work-orders`).
- **pgvector Diagnostic Signature Search (`/diagnostics`)**: 16-D cosine similarity nearest-neighbor search with 5 pre-loaded failure signature presets (engine overheat, inverter stress, bearing vibration, battery degradation, nominal baseline) and raw 16-D JSON vector input.
- **Live Ingestion WebSocket Monitor (`/alerts`)**: Reconnecting WebSocket stream hooked to `/ws/alerts` with bounded 50-event buffer, sliding set deduplication, 25s heartbeat PING/PONG, global dismissible `LiveAlertBanner`, and historical PostgreSQL alerts table.

### 3. Automated Test Evidence
- **Frontend Unit & Component Tests (`vitest`)**: All 6 test suites and 22 tests pass cleanly:
  - `Badge.test.tsx` (6 tests)
  - `PredictiveRiskPanel.test.tsx` (5 tests)
  - `VehicleTelemetryCard.test.tsx` (3 tests)
  - `WorkOrderModal.test.tsx` (3 tests)
  - `ApiClient.test.ts` (3 tests)
  - `WebSocketDeduplication.test.ts` (2 tests)
- **Frontend Production Build**: `npm run build` succeeds cleanly in 1.63s (`dist/index.html`, `dist/assets/index-DQB8LRr6.css`, `dist/assets/index-Cn3Yt59K.js`).
- **Backend Test Suite (`pytest`)**: All 113 backend unit, integration, and contract tests pass with 100% success rate (`pytest tests/ -q` in 3.65s).

### 4. Phase 9.1 Browser Acceptance Walkthrough & Audit Results
- **Automated Playwright Walkthrough (`scripts/browser_acceptance_walkthrough.py`)**: All 8 user journeys verified against live FastAPI and Vite servers:
  - **Fleet Overview (`/`)**: Real KPIs loaded from backend (10,003 monitored vehicles, 90.0% availability, 1 active critical alert, 1 high-risk asset). Leaflet map rendered with 25 vehicle markers. Inventory table loaded 20 vehicles on page 1. First VIN: `1HGCR2F83HA000001`.
  - **Vehicle Details (`/vehicles/:vin`)**: Authoritative 3NF relational specifications and telemetry components loaded.
  - **Predictive Risk**: 7-day failure risk probability (2.0%), advisory threshold (35%), model version `logreg-v1-purged`, and real backend disclaimer displayed.
  - **pgvector Diagnostics (`/diagnostics`)**: Executed 16-D nearest-neighbor cosine search returning `EXCESSIVE_VIBRATION` (31.0% match).
  - **Alerts & Real-Time Push (`/alerts`)**: Verified `STREAMING ACTIVE` WebSocket status. Broadcasted critical alert (`COOLANT_THERMAL_RUNAWAY`, VIN `1HGCR2F83HA000001`) via backend path; connected browser received alert in real time without page refresh, rendering `LiveAlertBanner`.
  - **Alert Direct Navigation**: Clicking banner navigated directly to `/vehicles/1HGCR2F83HA000001`.
  - **3NF Work Order Persistence**: Dispatched work order via modal (priority `HIGH`), generated UUID `fb20f3a8-3279-4787-abdb-4b6243080e8f`, verified directly in PostgreSQL `work_orders` table (`status=PENDING`, `priority=HIGH`).
  - **Responsive Layout**: Tablet viewport (768x1024) verified: body `scrollWidth = 768px` (zero horizontal overflow).
  - **Error Handling**: Graceful 404 alert rendered for `/vehicles/VIN_NONEXISTENT_9999`.
- **Screenshot Evidence Catalog**: 9 high-resolution screenshots saved to `docs/screenshots/` (`01_fleet_overview.png` to `09_error_state.png`).
- **Credential Hygiene Audit**: Complete repository scan verified zero hardcoded JWTs or secrets in tracked git repository. All authentication is environment-driven via `frontend/.env.example` and `scripts/generate_dev_token.py`.

---

## Phase 10 Implementation & Evidence Summary: Historical Batch Analytics and Reliability Intelligence

### 1. Architectural Demarcation & Datastore Invariants
Strict separation of concerns maintained per `docs/ARCHITECTURE_LOCK.md`:
- **ClickHouse (`fleetguard_analytics.vehicle_telemetry`)**: Authoritative columnar analytical datastore for historical OLAP queries, fleet-level MTBF, fault distributions, temporal reliability trends, and degradation rankings across 10K+ assets.
- **PostgreSQL 3NF**: Authoritative multi-tenant relational metadata (`tenants`, `fleets`, `vehicles`, `work_orders`, `users`). Scopes analytical queries by resolving tenant-authorized VIN lists before querying ClickHouse. Correlates completed maintenance work orders with historical trends.
- **pgvector**: Diagnostic signature cosine distance similarity search (16-D).
- **Redis 7**: Live hot CAN state cache and 120s sliding-window deduplication.
- **Logistic Regression (`logreg-v1-purged`)**: Forward-looking 7-day failure risk estimation (unaffected by historical OLAP calculations).
- **Redpanda**: Real-time event log and broker replay.

### 2. Analytical Engine Architecture (`services/analytics/`)
- `models.py`: Strongly validated Pydantic models with strict ISO 8601 parsing (`TimeWindow` ensures `start_time < end_time` and maximum 90-day analytical query window).
- `queries.py`: Highly optimized ClickHouse OLAP queries utilizing `ReplacingMergeTree FINAL` and columnar aggregations:
  - `FLEET_RELIABILITY_SUMMARY_SQL`: Computes monitored vehicle count, total events, critical/warning fault totals, and fault rate ($F / E$).
  - `FAULT_FREQUENCY_SQL`: Unrolls DTC arrays via `arrayJoin(dtc_codes)` and correlates physical threshold breaches (`ENGINE_OVERHEAT`, `OIL_PRESSURE_CRITICAL_LOW`, etc.).
  - `MTBF_SQL`: Evaluates window lag `lagInFrame(timestamp)` with a 30-minute (1,800s) debounce window to partition consecutive distinct failure events, computing empirical operating hours divided by distinct failure incidents.
  - `RELIABILITY_TREND_DAY_SQL` & `RELIABILITY_TREND_WEEK_SQL`: Chronological time-series aggregations with event volume and fault rate.
  - `DEGRADATION_RANKING_SQL`: Ranks top-N deteriorating assets using historical degradation score $S_{\text{deg}} \in [0, 100]$ computed from empirical telemetry signals prior to cutoff.
- `service.py`: `BatchAnalyticsService` resolving tenant-authorized VINs from PostgreSQL, validating fleet ownership, applying query execution settings (`max_query_size: 10485760`), and correlating completed work orders with reliability trends.

### 3. FastAPI Analytics API Endpoints (`services/api/routers/analytics.py`)
- `GET /analytics/summary`: PostgreSQL 3NF operational summary (guarded by `ADMIN`, `DISPATCHER`).
- `GET /analytics/reliability`: ClickHouse fleet reliability overview.
- `GET /analytics/faults`: ClickHouse DTC and physical fault frequency breakdown.
- `GET /analytics/mtbf`: ClickHouse empirical Mean Time Between Failures.
- `GET /analytics/trends`: ClickHouse daily/weekly reliability time series with PostgreSQL work order correlation.
- `GET /analytics/degradation`: ClickHouse asset degradation ranking.

### 4. ClickHouse Analytical Performance Benchmark (`scripts/benchmark_clickhouse_analytics.py`)
Measured over 20 iterations across 10,007 tenant-scoped vehicles on ClickHouse 24 (`vehicle_telemetry` table):
- **Fleet Reliability Summary**: Mean: **54.67 ms** | p50: **50.88 ms** | p95: **96.97 ms**
- **Fault Frequency Breakdown**: Mean: **134.54 ms** | p50: **106.88 ms** | p95: **422.00 ms**
- **MTBF Metrics**: Mean: **128.68 ms** | p50: **114.61 ms** | p95: **225.61 ms**
- **Reliability Daily Trend**: Mean: **90.36 ms** | p50: **56.34 ms** | p95: **275.31 ms**
- **Vehicle Degradation Ranking**: Mean: **84.47 ms** | p50: **77.30 ms** | p95: **170.78 ms**
- *Scope Note: ClickHouse analytical execution benchmark across 10K assets; distinct from distributed 100K events/sec ingestion benchmark (Phase 11).*

### 5. Automated Verification & Security Evidence
- **Backend Test Suite**: **136/136 tests passing** (`pytest tests/ -q` in 4.09s):
  - 63 unit tests (including 10 analytics unit tests in `test_analytics.py`)
  - 66 integration tests (including 7 ClickHouse OLAP tests in `test_clickhouse_analytics.py` and 6 security tests in `test_analytics_security.py`)
  - 7 OpenAPI 3.1 contract tests in `test_api_contracts.py`
- **Frontend Test Suite**: **22/22 tests passing** (`vitest run` in 1.70s) and production build succeeds cleanly (`npm run build` in 1.76s).
- **Tenant Isolation**: Verified negative isolation—cross-tenant fleet filters return 404, queries strictly scope to vehicles owned by caller's tenant, and unauthorized tenants see 0 records.
- **Deduplication Semantics**: Verified `ReplacingMergeTree FINAL` collapses identical duplicate events across multiple insertion batches on read.

---

## Phase 11 Implementation & Evidence Summary: Distributed 100K/300K Ingestion Benchmark

### 1. Empirical Test Harness Architecture (`scripts/benchmark_distributed_ingestion.py`)
- Built an automated multi-process benchmark harness driving the real Redpanda messaging layer on dedicated topic `vehicle.telemetry.benchmark.v1` (16 partitions):
  - Multiprocessing producer pool (up to 8 worker processes) distributing payloads across 16 partitions using VIN keying (`1HGCR2F83HA...`).
  - 100% unique UUIDv4 `event_id` generation per message with exact key-body VIN equality, monotonic sequence numbers, fresh UTC timestamps, and canonical TelemetryEvent schema version 1.0.
  - Multiprocessing consumer pool (up to 8 worker processes) executing the actual FleetGuard stream processing pipeline via `RealTimeWorker.process_message()`: `TelemetryValidator`, `TwoTierDeduplicator` (Counting Bloom Filter), `OutOfOrderProtector` (monotonic watermarks), `StreamingStatsRegistry` (Welford variance + EWMA), and `HealthAnomalyDetector` (deterministic rules + 3-sigma statistical anomalies).
  - Partition High-Water Mark (HWM) tracking measuring broker-side accepted writes across all 16 partitions via `get_watermark_offsets`.
  - In-flight consumer lag sampling and peak backlog tracking.
  - Automated post-burst recovery drain time measurement.
  - Docker container resource telemetry sampling before, during peak, and after workload (`docker stats --no-stream`).

### 2. Empirical Benchmark Results (`docs/benchmark_results_phase11.json` & `docs/distributed-throughput-benchmark.md`)
Across all 3 benchmark phases, **7,042,000 telemetry events** were generated, ingested, and processed through the real `RealTimeWorker` with **0 dropped messages (0.0000% loss)** and 100% data integrity:
- **Phase 11A — Baseline Ingestion (20K Target, 15.0s Window)**:
  - Events Attempted: 290,000 | Events Delivered: 290,000 | Broker Accepted: 290,000
  - Achieved Producer Rate: **17,759.8 ev/s** | Broker Ingestion Rate: **17,759.8 ev/s**
  - RealTimeWorker Processed: 290,000 | Consumer Rate: **17,437.3 ev/s**
  - Loss: **0 events (0.0000%)** | Peak Backlog: 12,006 | Final Lag: 0 | Integrity: PASSED
- **Phase 11B — Sustained 100K Target (60.0s Measurement Window)**:
  - Events Attempted: 5,269,500 | Events Delivered: 5,269,500 | Broker Accepted: 5,269,500
  - Achieved Producer Rate: **83,760.8 ev/s** | Broker Ingestion Rate: **83,760.8 ev/s**
  - RealTimeWorker Processed: 5,269,500 | Consumer Rate: **56,629.7 ev/s**
  - Loss: **0 events (0.0000%)** | Peak Backlog Absorbed: **2,394,220 events** | Drain Time: **29.63s** | Final Lag: 0 | Integrity: PASSED
  - Peak Redpanda Resource: **118.40% CPU** (exceeding 1.0 container vCPU), 827.2 MiB RAM (53.8% of 1.5 GiB cap).
- **Phase 11C — Burst 300K Target (10.0s Burst Window)**:
  - Events Attempted: 1,482,500 | Events Delivered: 1,482,500 | Broker Accepted: 1,482,500
  - Achieved Producer Rate: **82,818.1 ev/s** | Broker Ingestion Rate: **82,818.1 ev/s**
  - RealTimeWorker Processed: 1,482,500 | Consumer Rate: **55,481.5 ev/s**
  - Loss: **0 events (0.0000%)** | Peak Backlog Absorbed: **729,343 events** | Drain Time: **8.40s** | Final Lag: 0 | Integrity: PASSED

### 3. Acceptance Invariants & Scope Boundaries
- **No Extrapolation / Zero Overclaiming**: Local single-node hardware ceiling (8-core host, 2.0 container vCPUs) reached at ~83.8K ev/s ingestion and 56.6K ev/s full `RealTimeWorker` processing.
- `REQ-021` categorized as **`PARTIALLY PROVEN`** / `IN_PROGRESS` (empirically sustained 83.8% of target across 60s with 0% loss; distributed multi-node cluster required for sustained 100K+ without consumer lag growth).
- `REQ-022` categorized as **`PARTIALLY PROVEN`** / `IN_PROGRESS` (empirically absorbed 2.39M sustained backlog and 729K burst backlog, 0% loss, and drained in 8.40s; 300K for 5 minutes requires multi-node cluster).
- `REQ-023`, `REQ-026`, `REQ-040` remain `NOT_STARTED`.
- `REQ-024`, `REQ-025` remain `IN_PROGRESS`.

---

## Operational Constraints

**DO NOT:**
- Change locked architecture
- Replace Logistic Regression with another model
- Implement RUL prediction or add an AI agent
- Claim 100K events/sec benchmark without running the final distributed load test
- Touch `docs/HACKATHON_SPEC.md` or `docs/ARCHITECTURE_LOCK.md`

---

## Project Control Rule

> **"Every future task must update this file to reflect the active phase, completed items, in-progress work, blockers, and next immediate steps."**
