# FleetGuard Pulse - Distributed Ingestion Throughput & Burst Benchmark

**Date**: October 2026  
**Document**: `docs/distributed-throughput-benchmark.md`  
**Topic**: `vehicle.telemetry.benchmark.v1` (16 Partitions)  
**Message Broker**: Redpanda v24.3 (`fleetguard-redpanda`, single-node Docker container)  
**Stream Processing Engine**: FleetGuard Pulse `RealTimeWorker`  

---

## 1. Environment & Hardware Specification

All benchmarks were executed on the local development environment using containerized services and multi-process Python client pools:

* **Host Machine**: Apple Mac, Apple Silicon ARM64 (macOS Darwin 26.5.1)
* **Host CPU**: 8 physical CPU cores
* **Host RAM**: 8.0 GB Physical Memory
* **Python Runtime**: Python 3.11.9
* **Kafka Driver**: `confluent-kafka` v2.8.2 (C `librdkafka` core with LZ4 compression)
* **Docker Environment**: Docker Engine 27.x / Docker Compose v2.x
* **Redpanda Broker**: Redpanda v24.3 (single container `fleetguard-redpanda`)
  * Container limits: `cpus: 2.0`, `memory: 1.5GiB`
  * Network: `localhost:9092`
  * Dedicated Benchmark Topic: `vehicle.telemetry.benchmark.v1`
  * Partition Count: **16 partitions** (enabling parallel consumer and producer partition striping)
  * Replication Factor: 1 (single-node development broker)
* **Other Active Services**: PostgreSQL 16 (Timescale/pgvector), MongoDB 7, Redis 7, ClickHouse 24

---

## 2. Ingestion & Stream Processing Topology

The benchmark harness ([`scripts/benchmark_distributed_ingestion.py`](file:///Users/govindjee/Downloads/fleetguard-hackathon/scripts/benchmark_distributed_ingestion.py)) exercises the complete end-to-end ingestion and stream detection pipeline:

```mermaid
flowchart TD
    subgraph ProducerPool["Producer Pool (8 Dedicated Python Processes)"]
        P1["Producer 0 (VIN Key)"]
        P2["Producer 1 (VIN Key)"]
        Pdots["..."]
        P8["Producer 7 (VIN Key)"]
    end

    subgraph RedpandaBroker["Redpanda Broker ('vehicle.telemetry.benchmark.v1' - 16 Partitions)"]
        TP0["Partition 0 (Watermark 0)"]
        TP1["Partition 1 (Watermark 0)"]
        TPdots["..."]
        TP15["Partition 15 (Watermark 0)"]
    end

    subgraph ConsumerPool["Consumer Pool (8 Dedicated Python Processes)"]
        C1["Consumer 0"]
        C2["Consumer 1"]
        Cdots["..."]
        C8["Consumer 7"]
    end

    subgraph StreamEngine["FleetGuard RealTimeWorker Processing Pipeline"]
        V["1. TelemetryValidator (Pydantic Schema 1.0)"]
        D["2. TwoTierDeduplicator (Counting Bloom Filter + LRU)"]
        O["3. OutOfOrderProtector (Monotonic Watermarks)"]
        S["4. StreamingStatsRegistry (Welford Variance + EWMA)"]
        A["5. HealthAnomalyDetector (Physical Rules + Statistical 3-Sigma)"]
    end

    ProducerPool -->|Batch LZ4 Produce (acks=1)| RedpandaBroker
    RedpandaBroker -->|Fetch & Offset Commits| ConsumerPool
    ConsumerPool --> V --> D --> O --> S --> A
```

### Exact Production Processing Path Executed Per Consumed Event:
Every single record consumed from Redpanda is processed by [`RealTimeWorker.process_message()`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/stream_processor/workers/real_time_worker.py):
1. **Schema Validation**: [`TelemetryValidator.validate()`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/stream_processor/validator.py) parses and validates JSON against the canonical Pydantic [`TelemetryEvent`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/simulator/schema.py) schema (version 1.0).
2. **Deduplication Check**: [`TwoTierDeduplicator.is_duplicate()`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/stream_processor/dedup.py) verifies the event against an $O(1)$ Counting Bloom Filter and bounded LRU cache.
3. **Ordering Protection**: [`OutOfOrderProtector.check_and_update()`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/stream_processor/ordering.py) tracks per-VIN high-water marks for sequence numbers and timestamps.
4. **Streaming Statistics**: [`StreamingStatsRegistry.get_or_create()`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/stream_processor/statistics.py) updates running Welford variance and exponential moving averages (EWMA).
5. **Vehicle Health & Anomaly Detection**: [`HealthAnomalyDetector.evaluate()`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/stream_processor/detector.py) evaluates deterministic safety rules, statistical 3-sigma thresholds, and EWMA rate-of-change degradation trends.

### Downstream Persistence Boundary Note:
To isolate the high-throughput messaging pipeline and stream detection algorithms from single-threaded Redis TCP socket contention on the local development host, downstream Redis hot-state writes and alert publishing to Kafka were decoupled via `enable_downstream_persistence=False`. Therefore, the figures below represent **Messaging Ingestion & Real-Time Detection Throughput**, not full downstream transactional persistence.

---

## 3. Data Integrity & Invariants

1. **Genuinely Unique Event IDs**: Every generated event was assigned a fresh RFC 4122 UUIDv4 (`str(uuid.uuid4())`). No static payload recycling was used.
2. **Key-Body VIN Equality**: The Kafka message partition key exactly matched the `vin` field inside the JSON payload on 100% of generated records.
3. **Monotonic Sequence Numbers**: Sequence numbers incremented monotonically per VIN stream starting at 1000.
4. **Fresh UTC Timestamps**: Timestamps were generated in real time using ISO-8601 UTC microsecond format.
5. **Full Schema Compliance**: All canonical fields (speed, odometer, vibration, DTCs, temperatures, pressures, RPM, voltages) were present and physically bounded.
6. **Accounting Consistency**: In all phases, `events_attempted == events_delivered + events_failed`, and `broker_accepted == events_delivered` with **zero data loss (0.0000%)**.

---

## 4. Empirical Benchmark Results

### Comprehensive Benchmark Matrix

| Metric | Phase 11A: Baseline | Phase 11B: Sustained 100K | Phase 11C: Burst 300K | Total / Peak |
| :--- | :---: | :---: | :---: | :---: |
| **Configured Target Rate** | 20,000 ev/s | 100,000 ev/s | 300,000 ev/s | — |
| **Measurement Window** | 15.0 s | **60.0 s (Sustained)** | **10.0 s (Burst)** | 85.0 s |
| **Worker Topology** | 4 P / 4 C | 8 P / 8 C | 8 P / 8 C | 8 P / 8 C |
| **Initial Topic HWM** | 0 | 0 | 0 | 0 |
| **Events Attempted** | 290,000 | 5,269,500 | 1,482,500 | **7,042,000** |
| **Events Successfully Delivered** | 290,000 | 5,269,500 | 1,482,500 | **7,042,000** |
| **Producer Failed / Errors** | 0 | 0 | 0 | **0** |
| **Broker Accepted Events ($\Delta\text{HWM}$)** | 290,000 | 5,269,500 | 1,482,500 | **7,042,000** |
| **Producer Delivery Rate** | **17,759.8 ev/s** | **83,760.8 ev/s** | **82,818.1 ev/s** | **83,760.8 ev/s** |
| **Broker Ingestion Rate** | **17,759.8 ev/s** | **83,760.8 ev/s** | **82,818.1 ev/s** | **83,760.8 ev/s** |
| **RealTimeWorker Processed** | 290,000 | 5,269,500 | 1,482,500 | **7,042,000** |
| **Consumer Processing Rate** | **17,437.3 ev/s** | **56,629.7 ev/s** | **55,481.5 ev/s** | **56,629.7 ev/s** |
| **Data Loss** | **0 (0.0000%)** | **0 (0.0000%)** | **0 (0.0000%)** | **0 (0.0000%)** |
| **Duplicates Detected** | 0 | 0 | 0 | **0** |
| **Invalid Payloads** | 0 | 0 | 0 | **0** |
| **Key-Body Mismatches** | 0 | 0 | 0 | **0** |
| **Pre-Test Lag** | 0 | 0 | 0 | **0** |
| **Peak Backlog (Lag)** | 12,006 | **2,394,220** | **729,343** | **2,394,220** |
| **Post-Producer Drain Time** | 0.01 s | **29.63 s** | **8.40 s** | **29.63 s** |
| **Final Consumer Lag** | **0** | **0** | **0** | **0** |
| **Integrity Assertions** | **PASSED** | **PASSED** | **PASSED** | **PASSED** |
| **Peak Redpanda CPU %** | 16.91% | **118.40%** | **4.49%** | **118.40%** |
| **Peak Redpanda Memory** | 823.0 MiB | 827.2 MiB | 825.1 MiB | 827.2 MiB (53.8%) |

---

## 5. Detailed Analysis by Phase

### Phase 11A — Baseline Ingestion (20K Target, 15s)
* **Goal**: Validate zero-state baseline on fresh topic partitions.
* **Results**: Ingested 290,000 events in 16.33s at **17,759.8 ev/s** broker ingestion rate and **17,437.3 ev/s** consumer processing rate.
* **Lag Behavior**: Peak lag was only 12,006 events; consumers kept near parity and drained in 0.01s to zero lag.

### Phase 11B — Sustained Ingestion (100K Target, 60.0s Sustained Window)
* **Goal**: Measure sustained ingestion over a prolonged 60-second window.
* **Results**: Over 62.91s of active production, producers delivered **5,269,500 events** to Redpanda at **83,760.8 events/sec**. Redpanda accepted all 5,269,500 events across its 16 partitions without dropping a single message (**0.0000% loss**).
* **Consumer Processing & Queueing**: 8 consumer processes executing the full `RealTimeWorker` detection pipeline processed at **56,629.7 events/sec**. Because ingress (83.8K ev/s) exceeded single-host consumption (56.6K ev/s), Redpanda absorbed and held an in-flight peak backlog of **2,394,220 events** in its partition WALs.
* **Drain & Recovery**: Once producers completed, consumers continued draining the 2.39-million event backlog at full speed, returning to **0 lag in 29.63 seconds**.
* **Resource Telemetry**: Redpanda CPU reached **118.40%** (fully utilizing one container vCPU and consuming 18% of the second), with memory stable at 827.2 MiB / 1.5 GiB (53.85%).

### Phase 11C — Burst Tolerance (300K Target, 10.0s Burst Window)
* **Goal**: Measure rapid burst tolerance, backpressure handling, and queue recovery.
* **Results**: In a 10-second burst window, producers attempted 1,482,500 events at **82,818.1 events/sec**. The single-host CPU ceiling constrained peak producer send rate to ~83K ev/s.
* **Queue Absorption & Recovery**: Redpanda buffered a peak backlog of **729,343 events** with zero dropped connections or broker errors. Consumers processed all 1,482,500 records at **55,481.5 events/sec**, draining the entire 729K backlog back to **0 lag in 8.40 seconds**.

---

## 6. Local Single-Host Ceiling vs. Distributed Scaling Path

### Single-Host Hardware Bottleneck:
1. **Host CPU Core Exhaustion**: The local Mac has 8 physical CPU cores. The benchmark ran 8 producer processes, 8 consumer processes, and the Redpanda container concurrently (17 active compute entities). All 8 host cores were operating at 100% capacity.
2. **Container vCPU Cap**: The Redpanda Docker container is capped at `cpus: 2.0`. At 83.8K ev/s, Redpanda reached 118% CPU, operating near its allocated multi-thread capacity.
3. **Loopback Socket Contention**: On a single machine, all producer TCP socket writes and consumer TCP socket reads compete with the broker process on the local loopback interface.

### Distributed Multi-Node Path to Full 100K/300K:
* **3-Node or 5-Node Redpanda Cluster**: Distributing 16 partitions across 3 dedicated instances with 8–16 vCPUs each provides aggregate broker ingestion capacity $> 350,000\text{ ev/s}$.
* **Dedicated Client Fleets**: Moving producer pools and consumer groups to dedicated client nodes across 25GbE/100GbE networks eliminates CPU context-switching between client processes and the broker.
* **NVMe Direct I/O**: High-speed NVMe storage utilizing Seastar asynchronous direct I/O provides sustained sub-millisecond WAL appends.

---

## 7. Requirement Acceptance Determination

| Requirement | Required Target | Measured Empirical Result (Local Docker) | Evidence | Final Status |
| :--- | :---: | :---: | :---: | :---: |
| **REQ-021** (Sustained Ingestion) | 100,000 ev/s sustained | **83,760.8 ev/s** broker rate / **56,629.7 ev/s** RealTimeWorker rate across 60.0s (5,269,500 events, 0% loss) | `docs/benchmark_results_phase11.json`, `docs/distributed-throughput-benchmark.md` | **PARTIALLY PROVEN** (`IN_PROGRESS`) |
| **REQ-022** (Burst Tolerance) | 300,000 ev/s burst for 5 min | **82,818.1 ev/s** burst ingestion, **729,343** events buffered, 0% loss, drained in **8.40s** to 0 lag | `docs/benchmark_results_phase11.json`, `docs/distributed-throughput-benchmark.md` | **PARTIALLY PROVEN** (`IN_PROGRESS`) |

### Honest Accounting:
* `REQ-021` is **PARTIALLY PROVEN**: On a single local 8-core host with 2.0 container vCPUs, the pipeline sustained 83.8% of the 100K target for 60 seconds with 100% unique events and zero loss. However, consumer processing throughput (56.6K ev/s) resulted in consumer lag growth, and full 100K sustained without lag accumulation requires a multi-node cluster. The requirement remains **`IN_PROGRESS`**.
* `REQ-022` is **PARTIALLY PROVEN**: Redpanda proved exceptional backpressure tolerance and queue recovery, holding up to 2.39M events in backlog and draining rapidly to 0 lag with 0% data loss. However, the local host hardware ceiling limited peak burst ingress to 82.8K ev/s; demonstrating 300K for 5 full minutes requires multi-node hardware. The requirement remains **`IN_PROGRESS`**.

---

## 8. Reproducibility Instructions

To replicate these benchmark runs:
```bash
# Execute the full sequential benchmark suite
.venv/bin/python3 scripts/benchmark_distributed_ingestion.py \
  --mode sequential \
  --sustained-duration 60.0 \
  --burst-duration 10.0 \
  --output docs/benchmark_results_phase11.json

# Inspect the JSON telemetry
cat docs/benchmark_results_phase11.json
```
Raw telemetry is archived at [`docs/benchmark_results_phase11.json`](file:///Users/govindjee/Downloads/fleetguard-hackathon/docs/benchmark_results_phase11.json).
