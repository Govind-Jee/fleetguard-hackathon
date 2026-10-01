# Build State: FleetGuard

**PROJECT:** Connected Vehicle Intelligence Hackathon  
**CURRENT PHASE:** 8 - FastAPI API and Security Layer  

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

### IN PROGRESS:
API checkpoint complete; frontend preparation

### BLOCKERS:
None

### NEXT STEP:
Phase 9 - React FleetGuard Pulse Dashboard

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
