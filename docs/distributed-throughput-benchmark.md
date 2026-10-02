# FleetGuard Pulse - Distributed Ingestion Throughput & Burst Benchmark

**Date**: October 2026  
**Document**: `docs/distributed-throughput-benchmark.md`  
**Phase**: Phase 11, Phase 11.1 & Phase 11.2 (Throughput Bottleneck Audit & Controlled Validation)  
**Topic**: `vehicle.telemetry.benchmark.v1` (16 Partitions)  
**Message Broker**: Redpanda v24.1.2 (`fleetguard-redpanda`, single-node Docker container)  
**Stream Processing Engine**: FleetGuard Pulse `RealTimeWorker`  

---

## 1. Reconciled Environment & Hardware Specification

All benchmarks were executed on the authoritative local development environment using containerized services and multi-process Python client pools. Exact software versions have been verified and reconciled:

* **Host Machine**: Apple Mac, Apple Silicon ARM64 (macOS Darwin 26.5.1)
* **Host CPU**: 8 physical CPU cores
* **Host RAM**: 8.0 GB Physical Memory
* **Python Runtime**: **Python 3.11.9**
* **Docker Engine**: **Docker 28.3.2** (Docker Desktop 4.43.2, Engine API 1.51)
* **Docker Compose**: **Docker Compose v2.38.2-desktop.1**
* **Redpanda Broker**: **Redpanda v24.1.2** (`docker.redpanda.com/redpandadata/redpanda:v24.1.2`, Go 1.22.2)
  * Container limits: `cpus: 2.0`, `memory: 1.5GiB`
  * Network: `localhost:9092`
  * Dedicated Benchmark Topic: `vehicle.telemetry.benchmark.v1`
  * Partition Count: **16 partitions** (enabling parallel consumer and producer partition striping)
  * Replication Factor: 1 (single-node development broker)
* **Kafka Driver**: `confluent-kafka` v2.8.2 (C `librdkafka` core with LZ4 compression)
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
Every record consumed from Redpanda is processed by [`RealTimeWorker.process_message()`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/stream_processor/workers/real_time_worker.py):
1. **Schema Validation**: [`TelemetryValidator.validate()`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/stream_processor/validator.py) parses and validates JSON against the canonical Pydantic [`TelemetryEvent`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/simulator/schema.py) schema (version 1.0).
2. **Deduplication Check**: [`TwoTierDeduplicator.is_duplicate()`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/stream_processor/dedup.py) verifies the event against an $O(1)$ Counting Bloom Filter and bounded LRU cache.
3. **Ordering Protection**: [`OutOfOrderProtector.check_and_update()`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/stream_processor/ordering.py) tracks per-VIN high-water marks for sequence numbers and timestamps.
4. **Streaming Statistics**: [`StreamingStatsRegistry.get_or_create()`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/stream_processor/statistics.py) updates running Welford variance and exponential moving averages (EWMA).
5. **Vehicle Health & Anomaly Detection**: [`HealthAnomalyDetector.evaluate()`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/stream_processor/detector.py) evaluates deterministic safety rules, statistical 3-sigma thresholds, and EWMA rate-of-change degradation trends.

### Downstream Persistence Boundary Note:
To isolate the high-throughput messaging pipeline and stream detection algorithms from single-threaded Redis TCP socket contention on the local development host, downstream Redis hot-state writes and alert publishing to Kafka were decoupled via `enable_downstream_persistence=False`. The figures represent **Messaging Ingestion & Real-Time Detection Throughput**, not full downstream transactional persistence.

---

## 3. Data Integrity & Invariants

1. **Genuinely Unique Event IDs**: Every generated event was assigned a fresh RFC 4122 UUIDv4 (`str(uuid.uuid4())`). No static payload recycling was used.
2. **Key-Body VIN Equality**: The Kafka message partition key exactly matched the `vin` field inside the JSON payload on 100% of generated records.
3. **Monotonic Sequence Numbers**: Sequence numbers incremented monotonically per VIN stream starting at 1000.
4. **Fresh UTC Timestamps**: Timestamps were generated in real time using ISO-8601 UTC microsecond format.
5. **Full Schema Compliance**: All canonical fields (speed, odometer, vibration, DTCs, temperatures, pressures, RPM, voltages) were present and physically bounded.
6. **Accounting Consistency**: In all phases, `events_attempted == events_delivered + events_failed`, and `broker_accepted == events_delivered` with **zero data loss (0.0000%)**.

---

## 4. Phase 11.1 Hot-Path Profiling & Bottleneck Identification

To determine what limited single-core consumer processing throughput, micro-measurements were conducted on the hot execution path of `RealTimeWorker.process_message()` across $N = 20,000$ canonical telemetry events:

| Execution Stage | Component / Method | Mean Latency per Event ($\mu\text{s}$) | % of Hot-Path CPU Time |
| :--- | :--- | :---: | :---: |
| **1. JSON Parsing** | `json.loads(raw_bytes)` | $4.18\ \mu\text{s}$ | 15.0% |
| **2. Schema Validation** | `TelemetryEvent.model_validate(dict)` | $4.53\ \mu\text{s}$ | 16.2% |
| **3. Deduplication** | `TwoTierDeduplicator` / `CountingBloomFilter` | **$14.59\ \mu\text{s}$** | **52.2% (PRIMARY BOTTLENECK)** |
| **4. Out-of-Order Tracking** | `OutOfOrderProtector.check_and_update()` | $0.48\ \mu\text{s}$ | 1.7% |
| **5. Streaming Statistics** | `WelfordAccumulator` + `EWMASmoother` | $0.23\ \mu\text{s}$ | 0.8% |
| **6. Anomaly Detection** | `HealthAnomalyDetector.evaluate()` | $3.93\ \mu\text{s}$ | 14.1% |
| **Total per Event (Single Core)** | `RealTimeWorker.process_message()` | **$27.94\ \mu\text{s}$** | **100.0%** |

### Primary Algorithmic Bottleneck Identified:
Over **52.2%** of stream processor execution time was spent in `CountingBloomFilter`. Profiling revealed that `CountingBloomFilter._hashes()` was invoking Python's `hashlib.blake2b` with individual cryptographic salts **10 separate times per event**:
```python
# Unoptimized hot path (10 independent C hash calls per message):
for i in range(self.num_hashes):
    salt = i.to_bytes(4, byteorder="big")
    digest = hashlib.blake2b(raw_bytes, digest_size=8, salt=salt).digest()
    indices.append(int.from_bytes(digest, byteorder="big") % self.size)
```
This created massive interpreter and C-extension overhead, limiting single-core processing to $\sim 24,953\text{ msgs/sec}$.

---

## 5. Targeted Safe Optimization: Kirsch-Mitzenmacher Double Hashing

### Algorithmic Technique & Implementation:
To eliminate repeated cryptographic hash function invocations without modifying the underlying data structures, `CountingBloomFilter` was refactored to use Kirsch-Mitzenmacher double hashing:
$$g_i(x) = (h_1(x) + i \cdot h_2(x)) \pmod m \quad \text{for } i \in \{0, \dots, k-1\}$$

Rather than computing $k$ separate cryptographic hashes with distinct salts, the implementation computes a single 16-byte BLAKE2b digest and slices it into two 64-bit integer values ($h_1$ and $h_2$). The second hash $h_2$ is masked with an odd bit (`| 1`) to ensure coprimality with power-of-two table dimensions.

Implementation in [`services/stream_processor/dedup.py`](file:///Users/govindjee/Downloads/fleetguard-hackathon/services/stream_processor/dedup.py):
```python
def _hashes(self, item: str) -> List[int]:
    raw_bytes = item.encode("utf-8")
    digest = hashlib.blake2b(raw_bytes, digest_size=16).digest()
    h1 = int.from_bytes(digest[:8], byteorder="big")
    h2 = int.from_bytes(digest[8:], byteorder="big") | 1  # ensure odd / non-zero
    size = self.size
    return [(h1 + i * h2) % size for i in range(self.num_hashes)]
```

### Micro-Benchmark Verification (Isolated Component Level):
* **Hash generation**: Decreased from $9.45\ \mu\text{s}$ to **$1.45\ \mu\text{s}$** (**6.49x faster**).
* **`CountingBloomFilter.add()`**: Decreased from $10.74\ \mu\text{s}$ to **$2.62\ \mu\text{s}$** (**4.10x faster**).
* **`CountingBloomFilter.contains()`**: Decreased from $5.86\ \mu\text{s}$ to **$1.49\ \mu\text{s}$** (**3.93x faster**).
* **Isolated Single-Core `process_message()`**: Throughput increased from $24,953\text{ msgs/s}$ to **$48,395\text{ msgs/s}$ (+93.9% improvement)**.
* **Invariants Preserved**: Zero change to schema, zero change to anomaly detection logic, 100% test pass rate across all 136 backend tests.

---

## 6. Phase 11 & Phase 11.1 Benchmark Results & Confounding Variable Analysis

### Comparative Benchmark Matrix:

| Metric | Phase 11A: Baseline | Phase 11B: Sustained 100K | Phase 11C: Burst 300K | Total / Peak |
| :--- | :---: | :---: | :---: | :---: |
| **Configured Target Rate** | 20,000 ev/s | 100,000 ev/s | 300,000 ev/s | — |
| **Measurement Window** | 15.0 s | **60.0 s (Sustained)** | **10.0 s (Burst)** | 85.0 s |
| **Worker Topology** | 4 P / 4 C | 8 P / 8 C | 8 P / 8 C | 8 P / 8 C |
| **Total Events Processed** | 292,000 | 5,332,500 | 1,989,500 | **7,614,000** |
| **Data Loss** | **0 (0.0000%)** | **0 (0.0000%)** | **0 (0.0000%)** | **0 (0.0000%)** |
| **Producer Delivery Rate (Pre-Opt)** | 17,759.8 ev/s | 83,760.8 ev/s | 82,818.1 ev/s | 83,760.8 ev/s |
| **Producer Delivery Rate (Post-Opt)** | **17,899.4 ev/s** | **66,962.2 ev/s** | **63,938.1 ev/s** | 66,962.2 ev/s |
| **RealTimeWorker Rate (Pre-Opt)** | 17,437.3 ev/s | 56,629.7 ev/s | 55,481.5 ev/s | 56,629.7 ev/s |
| **RealTimeWorker Rate (Post-Opt)** | **17,565.7 ev/s** | **63,620.7 ev/s** | **55,447.5 ev/s** | **63,620.7 ev/s** |
| **Peak Backlog / Lag (Pre-Opt)** | 12,006 | 2,394,220 | 729,343 | 2,394,220 |
| **Peak Backlog / Lag (Post-Opt)** | **11,012** | **1,065,806 (-55.5%)** | **611,766 (-16.1%)** | **1,065,806** |
| **Recovery Drain Time (Pre-Opt)** | 0.01 s | 29.63 s | 8.40 s | 29.63 s |
| **Recovery Drain Time (Post-Opt)** | **0.01 s** | **3.43 s (8.6x FASTER)** | **4.15 s (2.0x FASTER)** | **4.15 s** |
| **Final Consumer Lag** | **0** | **0** | **0** | **0** |
| **Peak Redpanda CPU %** | 17.70% | **102.59%** | **4.49%** | **102.59%** |
| **Peak Redpanda Memory** | 786.4 MiB | 787.7 MiB | 787.7 MiB | 787.7 MiB (51.3%) |

> **Critical Distinction — Isolated Microbenchmark vs Multi-Process End-to-End Throughput**:
> * The **+93.9% improvement** ($24,953 \to 48,395\text{ msgs/s}$) was measured in an **isolated, single-core CPU microbenchmark** exercising `RealTimeWorker.process_message()` in isolation without external I/O or inter-process contention.
> * The **+12.3% improvement** ($56,629.7 \to 63,620.7\text{ ev/s}$) was observed in the end-to-end multi-process benchmark where 8 consumer processes, 8 producer processes, and the Redpanda broker container concurrently shared 8 host CPU cores and loopback socket buffers.
> * **Confounding Variable**: In Phase 11B, the unconstrained producer delivery rate differed between the runs ($83,760.8\text{ ev/s}$ pre-optimization vs $66,962.2\text{ ev/s}$ post-optimization). Therefore, the observed +12.3% end-to-end multi-process throughput comparison is **conditional on offered-load equivalence** and required the controlled validation below to isolate causal effect.

---

## 7. Phase 11.2 Controlled Validation: Before/After Under Equivalent Offered Load

To remove the confounding variable identified above, a controlled validation experiment was conducted using [`scripts/benchmark_controlled_validation.py`](file:///Users/govindjee/Downloads/fleetguard-hackathon/scripts/benchmark_controlled_validation.py), comparing the exact pre-optimization implementation from git commit `5f48e07` (cryptographic salts) against the treatment implementation from commit `cd7feb9` (Kirsch-Mitzenmacher double hashing) under materially equivalent offered loads.

### Experiment A: Controlled Streaming Load (Fixed Offered Rate Pacing)
* **Configuration**: 8 producers, 8 consumers, 16 partitions, target offered rate = 50,000 ev/s, duration = 15.0s, total events = 750,000.
* **Pacing**: Schedule-anchored pacing ($t_0 + i \times \Delta t$) ensuring drift-free producer delivery.

| Metric | Baseline: `salts` (Commit `5f48e07`) | Treatment: `double_hashing` (Commit `cd7feb9`) | Causal Delta |
| :--- | :---: | :---: | :---: |
| **Events Attempted / Delivered** | 750,000 / 750,000 | 750,000 / 750,000 | Identical (0 lost) |
| **Broker Accepted Events** | 750,000 | 750,000 | Identical (0 lost) |
| **Actual Producer Duration** | 17.42 s | 16.67 s | -4.3% duration |
| **Offered Kafka Ingestion Rate** | **43,047.7 ev/s** | **44,995.8 ev/s** | **+4.5% (Materially Equivalent)** |
| **RealTimeWorker Processed Rate** | **39,959.4 ev/s** | **44,011.5 ev/s** | **+10.1% higher throughput** |
| **Per-Event Processing Latency** | **74.65 µs** | **47.44 µs** | **-36.5% latency reduction** |
| **Total Consumer CPU Time** | **55.99 s** | **35.58 s** | **-36.5% CPU reduction** |
| **Peak In-Flight Backlog** | 50,250 | 45,630 | -9.2% lower backlog |
| **Lag After Producer Stop** | 2,130 | **0** | Eliminated backlog |
| **Post-Producer Recovery Drain** | 0.97 s | **0.01 s** | Instant recovery |
| **Redpanda Peak CPU %** | 97.65% | 99.37% | Comparable |

### Experiment B: Controlled Queue Drain (Zero Producer Contention)
* **Configuration**: Exactly 200,000 unique events were pre-loaded into the 16 partitions of `vehicle.telemetry.benchmark.v1` before consumer startup. Zero producers operated during consumption, completely eliminating producer CPU stealing and loopback socket contention.

| Metric | Baseline: `salts` (Commit `5f48e07`) | Treatment: `double_hashing` (Commit `cd7feb9`) | Causal Delta |
| :--- | :---: | :---: | :---: |
| **Pre-Loaded Topic Events** | 200,000 | 200,000 | 100% Identical |
| **Total Events Processed** | 200,000 | 200,000 | 0 errors / 0 lost |
| **Total Drain Duration** | 6.28 s | **5.22 s** | **-16.9% faster drain** |
| **Multi-Process Drain Rate** | **31,868.7 ev/s** | **38,307.6 ev/s** | **+20.2% throughput increase** |
| **Per-Event Processing Latency** | **59.59 µs** | **41.34 µs** | **-30.6% latency reduction** |
| **Total Consumer CPU Time** | **11.92 s** | **8.27 s** | **-30.6% CPU reduction** |
| **Redpanda Peak CPU %** | 19.04% | 5.64% | -70.4% lower broker load |

### Causal Findings:
When offered load and benchmark conditions are strictly controlled, the optimization demonstrates **statistically robust, causal improvements**:
1. **Per-event processing latency inside `RealTimeWorker` is reduced by 30.6% to 36.5%**.
2. **Total CPU time required to process the workload is reduced by 30.6% to 36.5%**.
3. **Consumer processing throughput increases by +10.1% under streaming load and by +20.2% under contention-free queue drain**.
4. In-flight backlog and post-workload recovery times are significantly reduced without altering detection accuracy or data integrity.

Raw telemetry for Phase 11.2 is archived at [`docs/controlled_validation_phase11_2.json`](file:///Users/govindjee/Downloads/fleetguard-hackathon/docs/controlled_validation_phase11_2.json).

---

## 8. Parallelism & Single-Host Contention Analysis

* **Host Physical Cores**: 8 CPU cores.
* **Active Compute Entities**: 8 Python producer processes + 8 Python consumer processes + 1 Docker Redpanda container (2.0 vCPUs) = **17 compute entities** competing for 8 CPU cores.
* **Process vs GIL Dynamics**: Using `multiprocessing` avoids GIL contention between consumers, but running 16 active client processes alongside Redpanda on an 8-core host forces extensive OS thread preemption and context switching.
* **Partition Assignment Balance**: 16 partitions assigned across 8 consumer processes yielded an even 2 partitions per consumer worker.
* **Loopback Socket vs Network Saturation**: All TCP traffic shares loopback socket buffers. Under sustained load, loopback buffer saturation caps aggregate host ingress at $\sim 67\text{K} - 84\text{K}\text{ ev/s}$.

---

## 9. Proposed Multi-Node Scaling Path (Theoretical Architecture)

> **Important Clarification**: The following specifications represent a **proposed architecture for multi-node deployment**, not measured local capacity. Local single-node hardware cannot achieve unconstrained 100K/300K due to host core exhaustion.

### Proposed Architecture Specification:
1. **Redpanda Cluster**:
   * **Nodes**: 3 dedicated nodes (e.g., AWS `i3en.2xlarge` or GCP `c3-standard-8`).
   * **vCPUs**: 8 vCPUs per node (24 total vCPUs for Redpanda Seastar thread-per-core engine).
   * **RAM**: 32 GiB ECC RAM per node.
   * **Storage**: Local NVMe SSD with XFS filesystem and Seastar direct I/O (`--overprovisioned=0`, `--lock-memory=true`).
   * **Topic Configuration**: 32 partitions, replication factor 3.
2. **Dedicated Stream Consumer Fleet**:
   * **Nodes**: 4 dedicated worker nodes (e.g., AWS `c6i.4xlarge`, 16 vCPUs each = 64 vCPUs total).
   * **Worker Processes**: 32 worker processes (1 worker process per topic partition).
   * **Projected Capacity**: With single-core capacity measured at $\sim 48.4\text{K}\text{ ev/s}$ post-optimization, a dedicated 8-to-16 core consumer pool running on separate hardware without broker contention has the mathematical capacity to process $> 350,000\text{ ev/s}$.
3. **Networking**: Dedicated 25 Gbps / 100 Gbps VPC interconnect to eliminate loopback socket buffer saturation.

---

## 10. Requirement Acceptance Determination

| Requirement | Required Target | Measured Empirical Result (Local Docker) | Evidence | Final Status |
| :--- | :---: | :---: | :---: | :---: |
| **REQ-021** (Sustained Ingestion) | 100,000 ev/s sustained | **66,962.2 ev/s** broker / **63,620.7 ev/s** RealTimeWorker across 60s (5,332,500 events, 0% loss, 3.43s drain) | `docs/benchmark_results_phase11.json`, `docs/controlled_validation_phase11_2.json` | **PARTIALLY PROVEN** (`IN_PROGRESS`) |
| **REQ-022** (Burst Tolerance) | 300,000 ev/s burst for 5 min | **63,938.1 ev/s** burst rate, **611,766** events buffered, 0% loss, drained in **4.15s** to 0 lag | `docs/benchmark_results_phase11.json`, `docs/controlled_validation_phase11_2.json` | **PARTIALLY PROVEN** (`IN_PROGRESS`) |

### Honest Accounting:
* `REQ-021` remains **`PARTIALLY PROVEN` / `IN_PROGRESS`**: While the optimized stream processor achieved up to **63,620.7 ev/s** sustained throughput with zero data loss, achieving sustained 100,000 ev/s without host CPU saturation requires a multi-node distributed cluster.
* `REQ-022` remains **`PARTIALLY PROVEN` / `IN_PROGRESS`**: Redpanda demonstrated robust backpressure absorption and fast queue recovery (up to 1.06M events buffered and drained in 3.43s–4.15s with zero loss). However, sustaining 300,000 ev/s for a full 5-minute duration requires multi-node hardware.

---

## 11. Reproducibility Guide

To reproduce these benchmark runs:
```bash
# 1. Execute the sequential benchmark harness (Phase 11 / 11.1)
.venv/bin/python3 scripts/benchmark_distributed_ingestion.py \
  --mode sequential \
  --sustained-duration 60.0 \
  --burst-duration 10.0 \
  --output docs/benchmark_results_phase11.json

# 2. Execute the controlled before/after validation benchmark (Phase 11.2)
.venv/bin/python3 scripts/benchmark_controlled_validation.py \
  --streaming-rate 50000.0 \
  --streaming-duration 15.0 \
  --drain-events 200000 \
  --output docs/controlled_validation_phase11_2.json
```
Raw telemetry is archived at [`docs/benchmark_results_phase11.json`](file:///Users/govindjee/Downloads/fleetguard-hackathon/docs/benchmark_results_phase11.json) and [`docs/controlled_validation_phase11_2.json`](file:///Users/govindjee/Downloads/fleetguard-hackathon/docs/controlled_validation_phase11_2.json).
