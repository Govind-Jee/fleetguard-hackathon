# FleetGuard Pulse — Real-Time Stream Processing Architecture & Implementation

**Status**: IMPLEMENTED & VERIFIED  
**Phase**: Phase 5  
**Service**: `services/stream_processor/`  
**Input Topic**: `vehicle.telemetry.v1` (16 partitions, partition key: `VIN`)  
**Alert Topic**: `vehicle.alerts.v1` (16 partitions, partition key: `VIN`)  
**State Store**: Redis 7 (`vehicle:state:{vin}`)  
**Raw Cold Storage**: MongoDB 7 (`fleetguard_telemetry.raw_telemetry`)  
**Historical Analytics**: ClickHouse 24 (`fleetguard_analytics.vehicle_telemetry`)  

---

## 1. Architectural Overview

FleetGuard Pulse implements an asynchronous, horizontally scalable streaming pipeline designed for high-throughput connected vehicle telemetry ingestion, safety-critical anomaly detection, and decoupled storage persistence.

```mermaid
flowchart TD
    RP[Redpanda Topic: vehicle.telemetry.v1] --> RT[Consumer: real-time-detection-consumer-group]
    RP --> MG[Consumer: mongodb-raw-consumer-group]
    RP --> CH[Consumer: clickhouse-analytics-consumer-group]

    subgraph "Real-Time Detection Pipeline"
        RT --> VAL[1. Pydantic Schema Validator]
        VAL --> DEDUP[2. Two-Tier Deduplicator<br/>Counting Bloom Filter + Exact LRU]
        DEDUP --> ORD[3. Out-of-Order Protector<br/>Monotonic Sequence Check]
        ORD --> STATS[4. Streaming Statistics<br/>Welford O(1) Variance + EWMA]
        STATS --> DET[5. Deterministic Anomaly Detector<br/>ICE / HEV / BEV Rules]
        DET -->|In-Order Event| REDIS[(Redis Hot State<br/>vehicle:state:VIN)]
        DET -->|Anomaly Detected| PUB[Alert Publisher]
        PUB --> ALERTS[Redpanda Topic: vehicle.alerts.v1]
    end

    subgraph "Decoupled Persistence"
        MG -->|Micro-Batch Upsert| MONGO[(MongoDB<br/>raw_telemetry)]
        CH -->|Micro-Batch Insert| CLICK[(ClickHouse<br/>vehicle_telemetry)]
    end
```

---

## 2. Pipeline Stages

### Stage 1: Pydantic Schema Validation (`validator.py`)
- Deserializes raw Kafka byte payloads into JSON and validates against `TelemetryEvent`.
- Validates 17-character VIN format, kinematic bounds, and powertrain-specific field requirements:
  - **ICE**: Requires `oil_pressure_kpa`, `coolant_temp_c`, `engine_rpm`.
  - **HEV**: Requires `oil_pressure_kpa`, `coolant_temp_c`, `soc_pct`.
  - **BEV**: Requires `pack_voltage_v`, `soc_pct`, `cell_temp_delta_c`.
- **Fault-Tolerant**: Malformed JSON or invalid schema records are recorded in Prometheus error counters (`telemetry.invalid`) and safely discarded without interrupting consumer polling loops.

### Stage 2: Two-Tier Deduplication (`dedup.py`)
- **Tier 1 (Probabilistic Filter)**: In-memory `CountingBloomFilter` with $m$ counters and $k$ cryptographic hash functions using `hashlib.blake2b` salts. Supports incremental additions and decrements/evictions.
- **Tier 2 (Exact Verification Store)**: Bounded in-memory LRU cache (`OrderedDict`) backed by Redis `SET event:dedup:{event_id} 1 EX 86400 NX`.
- **Zero False-Positive Drops**: If Tier 1 reports a potential duplicate, Tier 2 verifies set membership. True duplicates are dropped; false positives in Tier 1 are passed through and recorded.

### Stage 3: Out-of-Order & Watermark Protection (`ordering.py`)
- Tracks high-water mark tuples `(sequence_number, timestamp)` per VIN.
- Rejects stale/retransmitted sequence numbers (`sequence_number <= cached_seq`) from overwriting real-time state in Redis.
- Permissive to sequence gaps (`sequence_number > cached_seq + 1`) while logging missing frames.
- Reordered events are still processed for cold storage in ClickHouse and MongoDB.

### Stage 4: Streaming Statistics Engine (`statistics.py`)
Implements mathematically rigorous, single-pass algorithms with $\mathcal{O}(1)$ time and memory:
- **Welford's Algorithm**:
  $$\bar{x}_n = \bar{x}_{n-1} + \frac{x_n - \bar{x}_{n-1}}{n}, \quad M_{2,n} = M_{2,n-1} + (x_n - \bar{x}_{n-1})(x_n - \bar{x}_n)$$
  $$s^2 = \frac{M_{2,n}}{n-1}, \quad z = \frac{x_n - \bar{x}_n}{s}$$
  Dynamically tracks baseline variance and flags statistical anomalies (Z-scores $> 2.5\sigma$ or $> 3.5\sigma$) for vibration and thermal signals.
- **Exponentially Weighted Moving Average (EWMA)**:
  $$S_t = \alpha \cdot x_t + (1 - \alpha) \cdot S_{t-1}$$
  Filters transient sensor noise while tracking trend trajectories across vibration, coolant temperature, and battery cell delta.

### Stage 5: Powertrain Health & Anomaly Detector (`detector.py`)
Deterministic rules evaluated across ICE, HEV, and BEV platforms:
| Powertrain | Parameter / Signal | Threshold Condition | Severity | Fault Code |
|---|---|---|---|---|
| **All** | Vibration | $\ge 4.0\text{ G}$ or ($Z \ge 3.5$ and $\ge 2.5\text{ G}$) | `CRITICAL` | `EXCESSIVE_VIBRATION` |
| **All** | Vibration | $\ge 2.0\text{ G}$ or $Z \ge 2.5$ | `WARNING` | `ELEVATED_VIBRATION` |
| **ICE / HEV**| Coolant Temp | $\ge 115.0^\circ\text{C}$ | `CRITICAL` | `ENGINE_OVERHEAT` |
| **ICE / HEV**| Coolant Temp | $\ge 105.0^\circ\text{C}$ | `WARNING` | `COOLANT_TEMP_HIGH` |
| **ICE / HEV**| Oil Pressure | $\le 80\text{ kPa}$ (at RPM $> 500$) | `CRITICAL` | `OIL_PRESSURE_CRITICAL_LOW` |
| **ICE / HEV**| Oil Pressure | $\le 150\text{ kPa}$ (at RPM $> 500$) | `WARNING` | `OIL_PRESSURE_LOW` |
| **BEV / HEV**| Cell Temp Delta | $\ge 8.0^\circ\text{C}$ | `CRITICAL` | `BATTERY_THERMAL_RUNAWAY_RISK` |
| **BEV / HEV**| Cell Temp Delta | $\ge 5.0^\circ\text{C}$ | `WARNING` | `BATTERY_CELL_IMBALANCE` |
| **BEV** | State of Charge | $\le 5.0\%$ SOC | `CRITICAL` | `CRITICAL_LOW_SOC` |
| **BEV** | State of Charge | $\le 15.0\%$ SOC | `WARNING` | `LOW_BATTERY_SOC` |
| **OBD-II** | Critical DTCs | `P0217`, `P0524`, `P0A80`, `P0A78`, `P0300` | `CRITICAL` | `DTC_CRITICAL_{CODE}` |
| **OBD-II** | Warning DTCs | `P0117`, `P0128`, `P0171`, `P0420`, `P0A0F` | `WARNING` | `DTC_WARNING_{CODE}` |

### Stage 6: Redis Hot State Store (`state.py`)
- Key: `vehicle:state:{VIN}` (Redis Hash).
- Active Vehicle Set: `vehicles:active` (Redis Set).
- **Atomic Lua Check-and-Set Script**:
  ```lua
  local current_seq = redis.call('HGET', KEYS[1], 'sequence_number')
  local incoming_seq = tonumber(ARGV[1])
  if not current_seq or incoming_seq > tonumber(current_seq) then
      local data = cjson.decode(ARGV[2])
      for k, v in pairs(data) do
          redis.call('HSET', KEYS[1], k, tostring(v))
      end
      redis.call('SADD', 'vehicles:active', data['vin'])
      return 1
  else
      return 0
  end
  ```
  Guarantees atomic serialization and prevents race conditions from out-of-order worker delivery.

### Stage 7: Alert Publisher (`alert_publisher.py`)
- Emits standardized `CriticalAlert` models to Redpanda topic `vehicle.alerts.v1`.
- Partition key = `VIN.encode('utf-8')` to guarantee per-vehicle partition ordering for downstream notification workers.

---

## 3. Decoupled Persistence Consumer Groups

To strictly satisfy the non-blocking architectural mandate, historical and cold-storage persistence are implemented as completely independent consumer groups:

### 1. MongoDB Raw Telemetry Worker (`mongodb_worker.py`)
- **Consumer Group**: `mongodb-raw-consumer-group`
- **Target**: `fleetguard_telemetry.raw_telemetry`
- **Strategy**: Micro-batch buffered bulk write using `pymongo.UpdateOne({"event_id": doc["event_id"]}, {"$setOnInsert": doc}, upsert=True)`.
- **Properties**: Idempotent redelivery tolerance, zero schema mutation, index on `event_id` and compound `(vin, timestamp desc)`.

### 2. ClickHouse Analytics Worker (`clickhouse_worker.py`)
- **Consumer Group**: `clickhouse-analytics-consumer-group`
- **Target**: `fleetguard_analytics.vehicle_telemetry`
- **Strategy**: Micro-batch buffered inserts using `clickhouse_connect` native client (batch size: 1,000 records or 1.0s timeout).
- **Properties**: Stored on `ReplacingMergeTree`, partitioned monthly `toYYYYMM(timestamp)`, sorted by `(vehicle_type, vin, timestamp, sequence_number)`.

---

## 4. Verification & Smoke Test Evidence

### Test Count Reconciliation (39 Tests Passing)
Full pytest suite execution (`.venv/bin/python3 -m pytest tests/ -v`):
- **32 Unit Tests**:
  - `tests/unit/test_simulator.py`: 14 tests (schema, state degradation, burst/out-of-order generation, coverage)
  - `tests/unit/test_smoke.py`: 3 tests (environment, paths, Python version)
  - `tests/unit/test_stream_processor.py`: 15 tests (validation, Counting Bloom Filter, ordering, Welford/EWMA statistics, powertrain anomaly detection, idempotency audit)
- **7 Integration Tests**:
  - `tests/integration/test_pipeline_integration.py`: 5 tests (real-time worker end-to-end, MongoDB persistence, ClickHouse persistence, Redpanda roundtrip, duplicate alert suppression)
  - `tests/integration/test_redpanda_integration.py`: 2 tests (Redpanda cluster connectivity & topic creation, durable historical offset replay)

### Redpanda Durable Partitioning & Replay Verification (REQ-008)
Empirically verified via standalone script (`scripts/verify_redpanda_replay.py`) and automated integration test (`test_redpanda_historical_replay`):
- **Verification Command**: `.venv/bin/python3 scripts/verify_redpanda_replay.py`
- **Output Record**:
  - Topic: `vehicle.telemetry.v1` (16 partitions)
  - Partition: `12`
  - Historical Offset: `487`
  - Target Event ID: `fcf82dc0-56c0-4690-af3b-abf66b265c6d`
  - First Consumption Pass: `SUCCESS (Offset 487)`
  - Replay Consumption Pass (Consumer Group 2): `SUCCESS (Offset 487)`
  - In-Group Seek Rewind Pass: `SUCCESS (Offset 487)`
- **Conclusion**: Confirms durable, immutable partitioned message log on Redpanda with offset seek and multi-group historical replay capability.

### Alert Idempotency Audit
- Dedicated idempotency test `test_duplicate_event_alert_and_state_idempotency` and integration test `test_worker_duplicate_suppression_and_no_second_alert`:
  - When the exact same `event_id` is delivered twice:
  - Deduplication detects and suppresses the duplicate early.
  - Zero second critical alerts are emitted on `vehicle.alerts.v1`.
  - Zero second state transitions occur in Redis `vehicle:state:{vin}`.
  - Metrics record `events_duplicate` increment.
  - Exactly-once processing is maintained for state transitions and alert emission per `event_id`.

### Smoke Test Event-to-Alert Count Mapping
In `scripts/smoke_e2e_pipeline.py`, 7 events resulted in 8 critical alerts because multiple simultaneous distinct failure modes were intentionally injected into compound fault test vehicles:
1. `vin_normal_ice` (seq 1): NORMAL -> **0 alerts**
2. `vin_fault_ice` (seq 1): Compound mechanical failure -> **4 distinct CRITICAL alerts**:
   - `ENGINE_OVERHEAT` (Coolant 118.5°C >= 115°C)
   - `OIL_PRESSURE_CRITICAL_LOW` (Oil 65 kPa <= 80 kPa at 2900 RPM)
   - `DTC_CRITICAL_P0217` (OBD-II coolant overtemperature)
   - `DTC_CRITICAL_P0524` (OBD-II low oil pressure)
3. `vin_fault_bev` (seq 1): Compound electrical/thermal failure -> **3 distinct CRITICAL alerts**:
   - `BATTERY_THERMAL_RUNAWAY_RISK` (Cell delta 9.2°C >= 8.0°C)
   - `CRITICAL_LOW_SOC` (SOC 4.5% <= 5.0%)
   - `DTC_CRITICAL_P0A80` (OBD-II replace battery pack)
4. `vin_vib_hev` (seq 1): Structural anomaly -> **1 CRITICAL alert**:
   - `EXCESSIVE_VIBRATION` (Vibration 4.8 G >= 4.0 G)
5. `vin_ooo` (seq 10): In-order sequence -> **0 alerts**
6. `duplicate_event` (copy of event 0): Duplicate -> **0 alerts** (suppressed by deduplicator)
7. `stale_event` (vin_ooo seq 5): Stale re-delivery -> **0 alerts**
**Total**: $0 + 4 + 3 + 1 + 0 + 0 + 0 = 8\text{ Critical Alerts}$.

### Performance Benchmark Tier Definitions
To maintain absolute rigor and avoid conflating small-scale verification with final throughput SLAs:
1. **Functional Smoke-Test Latency**: 2.516 ms average, 8.189 ms P99 measured on a 7-event representative pipeline run (`scripts/smoke_e2e_pipeline.py`). Supports functional verification of REQ-024, but final acceptance remains `IN_PROGRESS` pending distributed load testing.
2. **Simulator Generation Benchmark**: Simulator-only throughput of ~80,000 events/sec single-threaded in memory (`services/simulator/`).
3. **Final System Performance Benchmark**: Sustained end-to-end distributed 100,000+ events/sec ingestion requirement across brokers, stream consumers, and datastores (REQ-021: strictly `NOT_STARTED`).
