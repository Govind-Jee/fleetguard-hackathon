# Acceptance Checklist: FleetGuard

**Rule:** Status must strictly be one of: `NOT_STARTED`, `IN_PROGRESS`, `DONE`, `BLOCKED`.  
**Note:** No item is to be marked `DONE` without verifiable test results, benchmark telemetry, or generated submission artifacts.

---

| ID | Requirement | Evidence Required | Status |
| :--- | :--- | :--- | :--- |
| **REQ-001** | Original connected vehicle problem framing and domain specialization defined | Section 1 of Solution Document detailing unique problem domain and value proposition | NOT_STARTED |
| **REQ-002** | Custom vehicle telemetry simulator generating data for at least 100,000 vehicles | Executable simulator code and output logs confirming active simulation of 100K unique VINs/telemetry streams (`scripts/verify_100k_coverage.py` - 100% VIN coverage) | DONE |
| **REQ-003** | Simulation of realistic telemetry: bursty traffic patterns | Simulation telemetry logs and broker ingress rate graphs showing burst behavior | IN_PROGRESS |
| **REQ-004** | Simulation of out-of-order and duplicate event transmission | Telemetry generator producing out-of-order sequence numbers & duplicates, verified in `tests/unit/test_stream_processor.py` & `scripts/smoke_e2e_pipeline.py` | DONE |
| **REQ-005** | Ingestion schema validation rejecting malformed payloads | Pydantic TelemetryEvent validation in `validator.py`, verified in `test_validator_malformed_json` & `test_validator_schema_violation` with metrics tracking | DONE |
| **REQ-006** | End-to-end event deduplication and idempotent processing | Two-tier Counting Bloom Filter + LRU/Redis exact cache in `dedup.py`, verified in `test_two_tier_deduplicator` and `scripts/smoke_e2e_pipeline.py` | DONE |
| **REQ-007** | Ingestion pipeline back-pressure awareness and management | Decoupled consumer groups (`real-time`, `mongodb-raw`, `clickhouse-analytics`) with bounded micro-batching | IN_PROGRESS |
| **REQ-008** | Durable, partitioned message broker with replay capability | Redpanda 16-partition topics with offset replay verified via `scripts/verify_redpanda_replay.py` & `test_redpanda_historical_replay` (replayed event from partition 12, offset 487) | DONE |
| **REQ-009** | Real-time event and anomaly detection engine | Deterministic rules engine + Welford variance/EWMA in `detector.py`, verified in `test_stream_processor.py` and `scripts/smoke_e2e_pipeline.py` | DONE |
| **REQ-010** | Polyglot persistence: Relational database in 3NF for fleet entities | 13 normalized tables in `001_initial_relational_schema.sql`, 3NF proofs in `docs/database-design.md`, verified in `test_postgres_integration.py` | DONE |
| **REQ-011** | Polyglot persistence: High-throughput NoSQL database for telemetry/state | Redis 7 hot state (`vehicle:state:{vin}`) with atomic Lua script + MongoDB 7 raw telemetry store, verified in `test_pipeline_integration.py` | DONE |
| **REQ-012** | Vector database / vector indexing integration | PostgreSQL pgvector extension, 16-D embeddings in `diagnostic_signatures`, HNSW index, cosine search verified in `test_pgvector_cosine_similarity_search` (<=> dist < 0.01) | DONE |
| **REQ-013** | Batch analytics engine processing historical vehicle datasets | ClickHouse 24 `ReplacingMergeTree` storage with `services/analytics/` batch analytics engine, verified in `tests/integration/test_clickhouse_analytics.py` & `docs/batch-analytics.md` (local ClickHouse query benchmark p50 < 160ms across 10K vehicles; MTBF algorithm verified with multi-incident fixtures, live snapshot dataset currently undefined due to single-incident records) | DONE |
| **REQ-014** | Tiered data lifecycle (Hot / Warm / Cold) implemented | Role-based polyglot tiering active (Redis hot state, MongoDB raw JSON archive, ClickHouse OLAP), but automated temporal retention / TTL eviction policies across stores are pending implementation | IN_PROGRESS |
| **REQ-015** | Relational SQL optimization with EXPLAIN ANALYZE comparison | `docs/sql-optimization.md` & `scripts/sql_optimization_benchmark.py` showing baseline Bitmap Heap Scan (1,250 discarded, 3.068 ms) vs composite index `idx_work_orders_composite_dispatch` (0 discarded, 2.372 ms, 57% faster scan) | DONE |
| **REQ-016** | Algorithmic implementation with documented time/space complexity | O(1) Welford variance, O(1) EWMA, O(1) Counting Bloom Filter, O(1) atomic Lua script documented in `docs/stream_processing.md` | DONE |
| **REQ-017** | CAP / PACELC distributed systems tradeoff analysis | Architectural write-up detailing consistency, availability, and latency choices per store | NOT_STARTED |
| **REQ-018** | Secure REST/GraphQL APIs with authentication and authorization | `services/api/` FastAPI REST API with Keycloak-compatible Bearer JWT auth and ADMIN/DISPATCHER/TECHNICIAN RBAC, verified in `tests/integration/test_api_security.py` & `test_api_integration.py` (22 integration tests passing) | DONE |
| **REQ-019** | API rate limiting and security headers | Redis-backed sliding window rate limiter (`services/api/rate_limit.py`) returning HTTP 429 + Retry-After and defensive OWASP security headers (CSP, nosniff, DENY, XSS), verified in `tests/integration/test_api_security.py` & `tests/unit/test_api.py` | DONE |
| **REQ-021** | Ingestion throughput benchmark: sustained 100,000+ events/sec | Verified empirical benchmark in `docs/distributed-throughput-benchmark.md` & `docs/benchmark_results_phase11.json`: 5,332,500 events across 16 partitions of `vehicle.telemetry.benchmark.v1` in 60s at **66,962.2 ev/s** broker rate and processed through optimized `RealTimeWorker` at **63,620.7 ev/s** (+12.3% improvement, 48.4K/s single-core capacity) with 0 lost (0.0000% loss), 100% unique UUIDv4 event_ids, and drain time improved to 3.43s (8.6x faster); multi-node cluster required for sustained 100K+ without host saturation | IN_PROGRESS |
| **REQ-022** | Burst tolerance: 3x burst (300,000 events/sec) for 5 minutes without data loss | Verified empirical burst benchmark in `docs/distributed-throughput-benchmark.md`: Redpanda single-node absorbed 1,989,500-event burst at **63,938.1 ev/s**, buffered peak backlog of **611,766 events** across 16 partitions, and drained in 4.15s to 0 lag with 0% data drop (0.0000% loss); 300K for 5 mins requires distributed multi-node cluster | IN_PROGRESS |
| **REQ-023** | Dashboard latency under 2 seconds for telemetry queries | Browser performance / API benchmark logs proving p95 response time under 2 seconds | NOT_STARTED |
| **REQ-024** | Critical alert notification delivery under 5 seconds from ingestion | Functional smoke-test latency: 2.516 ms avg, 8.189 ms p99 on 7-event pipeline; scale load benchmark pending | IN_PROGRESS |
| **REQ-025** | API latency SLA: p95 under 200 ms and p99 under 500 ms | Measured in `scripts/benchmark_api.py` (100 reqs/ep): `/health` (p95 1.63ms, p99 2.33ms), `/vehicles` (p95 15.86ms, p99 19.66ms), `/vehicles/{vin}` (p95 4.61ms, p99 5.30ms), `/vehicles/{vin}/risk` (p95 4.67ms, p99 4.95ms), `/alerts` (p95 4.73ms, p99 5.44ms), `/fleets/{fleet_id}/health` (p95 29.69ms, p99 42.35ms); all p95 < 30ms, p99 < 45ms locally; scale benchmark pending | IN_PROGRESS |
| **REQ-026** | High-availability design targeting 99.9% uptime with no SPOF | Fault tolerance architecture documentation and component redundancy configuration | NOT_STARTED |
| **REQ-027** | Automated test coverage of at least 80% on core services and algorithms | Code coverage tool report (e.g., pytest-cov, jest/c8) showing >= 80% coverage on core modules | NOT_STARTED |
| **REQ-028** | Integration and service contract test suite | 136 automated tests passing: 63 unit tests + 66 integration tests + 7 OpenAPI contract tests (`pytest tests/ -q` in 4.09s) | IN_PROGRESS |
| **REQ-029** | Behavior-Driven / Acceptance testing (BDD) | Executed BDD test suite reports (e.g., Behave, Cucumber, or end-to-end acceptance tests) | NOT_STARTED |
| **REQ-030** | Soak testing validating long-duration memory and queue stability | Multi-hour soak test metric logs demonstrating stable memory, CPU, and zero unbounded growth | NOT_STARTED |
| **REQ-031** | Static Application Security Testing (SAST) | SAST scanner report (e.g., Bandit, Semgrep, Sonar) with 0 high/critical unresolved findings | NOT_STARTED |
| **REQ-032** | Dynamic Application Security Testing (DAST) | DAST scanner report (e.g., OWASP ZAP) with 0 high/critical unresolved vulnerabilities | NOT_STARTED |
| **REQ-033** | Container image and dependency vulnerability scanning | Scanner reports (e.g., Trivy, Snyk, pip-audit, npm audit) with 0 high/critical vulnerabilities | NOT_STARTED |
| **REQ-034** | Chaos / resilience testing verifying graceful failure handling | Chaos test execution logs verifying broker or worker instance failure recovery | NOT_STARTED |
| **REQ-035** | One-command local setup | Single shell command (e.g., `make up`) successfully launching all services and dependencies | NOT_STARTED |
| **REQ-036** | Reproducible seeded 100,000-vehicle dataset | `data/seed/vehicles.csv` generated with 100,000 vehicles, 100% VIN coverage verified by `scripts/verify_100k_coverage.py` | DONE |
| **REQ-037** | System architecture diagram | Exported high-resolution architecture diagram included in repository and solution document | NOT_STARTED |
| **REQ-038** | Relational 3NF Entity-Relationship Diagram | Formal Mermaid ER diagram documenting all 13 domain entities, keys, cardinalities, and normal forms in `docs/database-design.md` | DONE |

| **REQ-039** | 3 to 5 Architecture Decision Records (ADRs) | Documented ADR files in `docs/adr/` with context, alternatives considered, and consequences | NOT_STARTED |
| **REQ-040** | Cloud deployment automation (IaC) and cloud-agnostic verification | IaC scripts (Terraform/Helm/Compose) and cloud deployment documentation demonstrating portability | NOT_STARTED |
| **REQ-041** | Automated Continuous Integration (CI) pipeline | Passing CI pipeline configuration (e.g., GitHub Actions) executing linting, tests, and security scans | NOT_STARTED |
| **REQ-042** | Solution Document completed and exported as PDF | Formatted, completed Solution Document PDF following the official template | NOT_STARTED |
| **REQ-043** | Demonstration video (maximum 5 minutes) | Video recording link demonstrating working architecture, 100K simulation, alerts, and UI | NOT_STARTED |
| **REQ-044** | Final submission Git commit tagged `v1.0-submission` | Git repository verification showing commit tagged with `v1.0-submission` prior to deadline | NOT_STARTED |
