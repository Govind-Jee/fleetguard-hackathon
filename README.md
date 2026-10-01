# FleetGuard Pulse

> **Connected Vehicle Predictive Maintenance & Vehicle Health Intelligence**

FleetGuard Pulse is an enterprise-scale connected vehicle intelligence platform designed to ingest, monitor, predict, and analyze vehicle health telemetry across 100,000+ commercial vehicles in real time. It supports mixed powertrains (Internal Combustion Engine [ICE], Hybrid Electric Vehicle [HEV], and Battery Electric Vehicle [BEV]), providing streaming anomaly detection, sub-5-second critical mechanical alerting, vector-similarity diagnostic matching, 3NF relational fleet management, and columnar historical reliability analytics.

---

## 1. Current Project Status

- **Phase:** **Phase 4 — 100K Vehicle Simulator (Feature F-01 Implemented)**
- **Status:** Feature F-01 implemented and verified. Seed dataset of 100,000 vehicles generated in `data/seed/vehicles.csv`. Streaming simulator tested with Redpanda.
- **Architecture Governance:** Formally locked in [`docs/ARCHITECTURE_LOCK.md`](docs/ARCHITECTURE_LOCK.md).
- **Acceptance Tracking:** 44 items tracked in [`docs/ACCEPTANCE_CHECKLIST.md`](docs/ACCEPTANCE_CHECKLIST.md).

---

## 2. System Architecture Overview

FleetGuard Pulse employs a polyglot persistence and decoupled streaming architecture:

- **Message Broker:** **Redpanda** (Kafka-compatible, partitioned by VIN)
- **Relational Core:** **PostgreSQL 16** (3NF transactional schema for fleets, vehicles, and work orders)
- **Vector Search:** **pgvector** (HNSW approximate nearest-neighbor search for diagnostic failure signatures)
- **Raw Telemetry Archive:** **MongoDB 7** (High-throughput flexible document store)
- **Hot Transient State:** **Redis 7** (Sub-millisecond vehicle state, deduplication cache, active alert flags)
- **Batch Analytics:** **ClickHouse** (Columnar warehouse for historical rollups, MTBF, and component degradation)
- **Application Services:** Telemetry Simulator (Implemented), FastAPI API (Planned), Python Stream Workers (Planned), React Frontend (Planned)
- **ML / AI:** Scikit-Learn Logistic Regression (7-day future failure forecasting) + deterministic baseline (Planned)

---

## 3. Repository Structure

```
.
├── services/
│   ├── api/                 # Core REST & WebSocket API service
│   ├── ingestion/           # High-throughput ingestion gateway
│   ├── stream_processor/    # Real-time anomaly detection stream workers
│   ├── simulator/           # 100K+ multi-worker vehicle telemetry generator
│   ├── ml/                  # 7-day predictive maintenance models & feature pipelines
│   └── analytics/           # Batch analytical jobs & historical aggregations
├── frontend/                # React + Vite web dashboard
├── infra/
│   ├── docker/              # Container definitions and initialization scripts
│   └── terraform/           # Cloud deployment blueprints (AWS)
├── tests/
│   ├── unit/                # Unit test suites for algorithms and utilities
│   ├── integration/         # Service-to-service integration tests
│   ├── contract/            # API contract tests
│   ├── acceptance/          # BDD / acceptance test suites
│   ├── performance/         # Load and throughput benchmarks
│   ├── security/            # SAST, DAST, and secret scan configurations
│   └── chaos/               # Broker/worker resilience failure injection tests
├── docs/                    # Authoritative specifications and architecture controls
├── scripts/                 # Operations, database migration, and seed scripts
├── data/                    # Seed datasets, raw payloads, and synthetic outputs
├── .github/workflows/       # CI/CD pipeline automation
├── docker-compose.yml       # Infrastructure orchestration
├── .env.example             # Environment variable template
├── Makefile                 # Developer lifecycle commands
├── pyproject.toml           # Python 3.11 dependencies and tool configuration
└── README.md                # Project documentation
```

---

## 4. Prerequisites

- **Operating System:** macOS, Linux, or WSL2
- **Docker & Docker Compose:** Docker version 24+ and Docker Compose v2+
- **Python:** Python 3.11+
- **Node.js:** Node.js 20+ (for future frontend development)
- **Make:** GNU Make

---

## 5. Getting Started (Infrastructure Foundation)

### 5.1 Environment Configuration
Create a local environment file from the provided template:
```bash
cp .env.example .env
```

### 5.2 Launch Infrastructure Containers
Start the core storage and messaging infrastructure:
```bash
make up
```
Or directly with Docker Compose:
```bash
docker compose up -d
```

### 5.3 Verify Service Health
Check the operational status of all running infrastructure containers:
```bash
make ps
```

The following infrastructure endpoints will be available:
- **Redpanda (Kafka Broker):** `localhost:9092` (Admin API: `localhost:9644`)
- **PostgreSQL 16 (with pgvector):** `localhost:5433`
- **MongoDB 7:** `localhost:27017`
- **Redis 7:** `localhost:6380`
- **ClickHouse:** `localhost:8123` (HTTP) / `localhost:9000` (Native)

### 5.4 Stop Infrastructure
To stop all containers:
```bash
make down
```

To stop containers and wipe persistent data volumes:
```bash
make down-v
```

---

## 6. Testing

Run all unit and integration test suites:
```bash
.venv/bin/python3 -m unittest discover -s tests -p "test_*.py" -v
```

---

## 7. Vehicle Telemetry Simulator (F-01)

Detailed design and benchmark documentation is located in [`docs/simulator.md`](docs/simulator.md).

### 7.1 Generate 100K Seed Vehicle Dataset
```bash
python3 scripts/generate_vehicles.py --count 100000 --seed 42 --output data/seed/vehicles.csv
```

### 7.2 Run Simulator Benchmark (In-Memory / Dry-Run)
```bash
python3 -m services.simulator run --vehicles 100000 --rate 10000 --max-events 50000 --dry-run
```

### 7.3 Run Simulator Publishing to Redpanda
Ensure Redpanda is running (`make up`), then execute:
```bash
.venv/bin/python3 -m services.simulator run \
  --vehicles 100000 \
  --rate 1000 \
  --brokers localhost:9092 \
  --topic vehicle.telemetry.v1 \
  --max-events 10000
```
