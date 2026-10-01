# FleetGuard Pulse - 100K+ Vehicle Telemetry Simulator (F-01)

## 1. Overview & Architecture

The **FleetGuard Pulse Simulator** is a high-throughput, deterministic, memory-efficient connected vehicle telemetry generator designed to simulate at least 100,000 unique commercial vehicles. It provides realistic synthetic telematics across mixed powertrains (Internal Combustion Engine [ICE], Hybrid Electric Vehicle [HEV], and Battery Electric Vehicle [BEV]), introducing physical fault progressions, controlled sensor noise, duplicate transmissions, and out-of-order delivery.

```
┌────────────────────────────────────────────────────────┐
│         Vehicle Pool: 100,000 Compact State Slots      │
│     (ICE: 60%, HEV: 20%, BEV: 20% | Memory: ~25 MB)    │
└───────────────────────────┬────────────────────────────┘
                            │ Deterministic Steps
                            ▼
┌────────────────────────────────────────────────────────┐
│               Telemetry Step Simulation                │
│    - Kinematics & Spatial Heading Displacement         │
│    - Health State Machine Correlation (Healthy -> Fail)│
│    - Sensor Noise (Gaussian) & Missing Field Jitter    │
└───────────────────────────┬────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
┌───────────────────────────┐ ┌───────────────────────────┐
│  Duplicate Injector Queue │ │   Bounded Reorder Buffer  │
│  (1% duplicate emission)  │ │  (2% out-of-order shuffle)│
└─────────────┬─────────────┘ └───────────┬───────────────┘
              │                           │
              └─────────────┬─────────────┘
                            │ Pydantic v1.0 Schema Validation
                            ▼
┌────────────────────────────────────────────────────────┐
│             Redpanda / Kafka Producer                  │
│    - Topic: 'vehicle.telemetry.v1' (16 Partitions)     │
│    - Partition Key: VIN (Guarantees Per-VIN Ordering)  │
│    - Async Batching & Delivery Callbacks               │
└────────────────────────────────────────────────────────┘
```

---

## 2. Telemetry Data Model

All telemetry conforms to versioned Pydantic schemas (`schema_version = "1.0"`).

### Common Telemetry Header
| Field | Type | Description |
| :--- | :--- | :--- |
| `schema_version` | `str` | Specification schema version (default `"1.0"`) |
| `event_id` | `str` | Unique UUIDv4 identifier for idempotency & deduplication |
| `vin` | `str` | 17-character standardized synthetic VIN (e.g., `1FLC0000000000001`) |
| `timestamp` | `str` | ISO-8601 UTC timestamp with microsecond resolution |
| `sequence_number` | `int` | Monotonically increasing counter per vehicle |
| `vehicle_type` | `str` | Enum: `ICE`, `HEV`, `BEV` |
| `latitude` | `float` | WGS84 latitude |
| `longitude` | `float` | WGS84 longitude |
| `speed_kmh` | `float` | Ground speed in km/h (0.0 to 120.0 km/h) |
| `odometer_km` | `float` | Cumulative distance traveled |
| `vibration` | `float` | Tri-axial peak acceleration magnitude in G |
| `dtc_codes` | `List[str]` | Active OBD-II / UDS diagnostic trouble codes |

### Powertrain-Specific Extensions
- **ICE Vehicles:** `oil_pressure_kpa`, `coolant_temp_c`, `engine_rpm`, `battery_voltage_v`
- **Hybrid Vehicles (HEV):** `oil_pressure_kpa`, `coolant_temp_c`, `engine_rpm`, `battery_voltage_v`, `soc_pct`
- **Electric Vehicles (BEV):** `motor_rpm`, `pack_voltage_v`, `soc_pct`, `cell_temp_delta_c`

---

## 3. Physical State & Health Progression Model

Vehicles advance through four distinct physical health states:
$$\text{HEALTHY} \longrightarrow \text{DEGRADATION} \longrightarrow \text{WARNING} \longrightarrow \text{FAILURE}$$

### Initial Distribution (Seed = 42)
- **HEALTHY:** 82%
- **DEGRADATION:** 12%
- **WARNING:** 4%
- **FAILURE:** 2%

### Sensor Correlation by Health State
| Metric | Healthy | Degradation | Warning | Failure |
| :--- | :--- | :--- | :--- | :--- |
| **Vibration (G)** | 0.15 – 0.35 G | 0.55 – 1.10 G | 1.20 – 2.10 G | 2.50 – 4.20 G |
| **Coolant Temp (°C)** | 88 – 93 °C | 95 – 102 °C | 103 – 112 °C | 116 – 128 °C |
| **Oil Pressure (kPa)** | 320 – 420 kPa | 210 – 280 kPa | 130 – 190 kPa | 40 – 75 kPa (Loss of pressure) |
| **Cell Temp Delta (°C)**| 0.4 – 1.6 °C | 2.2 – 4.2 °C | 5.0 – 8.5 °C | 11.0 – 18.5 °C |
| **DTC Codes** | `[]` | `["P0420"]` | `["P0117", "P0171"]` | `["P0524", "P0300"]` or `["P0A80", "P0A7F"]` |

---

## 4. Controlled Anomalies & Network Realism

### 4.1 Synthetic Sensor Noise
- Sensor readings incorporate zero-mean Gaussian jitter ($\sigma = 0.4^\circ\text{C}$ for temperature, $\sigma = 3.0\text{ kPa}$ for oil pressure).
- Spatial coordinates incorporate GPS drift ($\approx \pm 1\text{ meter}$).

### 4.2 Duplicate Injection
- Configurable parameter: `duplicate_rate` (default: `0.01` or 1%).
- Generated events are periodically cached in a bounded FIFO queue and re-emitted with identical `event_id` and `sequence_number`.
- Downstream ingestion and stream workers use these duplicates to exercise the Counting Bloom Filter and Redis idempotency logic.

### 4.3 Out-of-Order Injection
- Configurable parameter: `reorder_rate` (default: `0.02` or 2%).
- Generated events pass through a bounded shuffle buffer (size 50). Events are emitted with delays relative to newer sequence numbers while preserving their original generation timestamps.

### 4.4 Bursty Traffic Generation
- The generator supports transitioning from steady generation rate to a 3.0x burst for a configurable duration (`burst_duration_sec`).

---

## 5. Memory & Scale Performance

The simulator utilizes Python `__slots__` within `VehicleState` to maximize cache locality and minimize memory allocation overhead.

### Measured Empirical Scale Metrics (macOS Apple Silicon arm64)
| Vehicle Pool | Startup Time | Net Memory Allocated | Generation Throughput |
| :--- | :--- | :--- | :--- |
| **10,000 Vehicles** | 0.110 s | 5.08 MB | 80,871 events/sec |
| **50,000 Vehicles** | 0.538 s | 20.11 MB | 81,693 events/sec |
| **100,000 Vehicles** | 1.125 s | 24.70 MB | 80,825 events/sec |

*Memory Footprint:* Retains under **25 MB of RAM** for the complete 100,000 vehicle pool.

---

## 6. CLI Usage & Commands

### 6.1 Generate Seed Dataset (100,000 Vehicles)
```bash
python3 scripts/generate_vehicles.py --count 100000 --seed 42 --output data/seed/vehicles.csv
```
Or via module CLI:
```bash
python3 -m services.simulator generate-vehicles --count 100000 --seed 42
```

### 6.2 Run Simulation (Dry-Run / In-Memory Benchmark)
```bash
python3 -m services.simulator run --vehicles 100000 --rate 10000 --max-events 50000 --dry-run
```

### 6.3 Run Simulation Publishing to Redpanda
```bash
.venv/bin/python3 -m services.simulator run \
  --vehicles 100000 \
  --rate 1000 \
  --brokers localhost:9092 \
  --topic vehicle.telemetry.v1 \
  --max-events 10000
```

---

## 7. 100K Vehicle Coverage Evidence

### 7.1 Verification Command & Measured Values
The population coverage test exercises all 100,000 vehicles in the synthetic seed pool, validating that each vehicle generates valid telemetry with 100% unique VIN representation:

```bash
python3 scripts/verify_100k_coverage.py
```

#### Measured Empirical Output:
- **Vehicles Initialized:** 100,000
- **Initialization Time:** 1.330 seconds
- **Events Emitted & Validated:** 100,000 (1 per vehicle)
- **Validation Duration:** 1.456 seconds
- **Unique VIN Coverage:** 100,000 / 100,000 (**100.00%**)
- **Unique Event IDs:** 100,000
- **Invalid Events Detected:** 0
- **Powertrain Breakdown:**
  - ICE: 59,857 (59.9%)
  - HEV: 20,241 (20.2%)
  - BEV: 19,902 (19.9%)
- **Memory Footprint:** Net 61.22 MB allocated during test execution
- **Test Result:** **PASSED**

### 7.2 Live Redpanda Telemetry Publish Test (100K Vehicle Pool)
To confirm operational integration with the messaging layer across a 100K vehicle population:
```bash
.venv/bin/python3 -m services.simulator run \
  --vehicles 100000 \
  --rate 2000 \
  --brokers localhost:9092 \
  --topic vehicle.telemetry.v1 \
  --max-events 5000 \
  --seed 42
```

#### Measured Publish Telemetry:
- **Vehicle Pool Size:** 100,000
- **Pool Init Duration:** 1.357 seconds
- **Events Emitted:** 5,000
- **Events Delivered:** 5,000
- **Failed Deliveries:** 0
- **Duplicates Injected:** 51 (1.02%)
- **Reordered Injected:** 98 (1.96%)
- **Duration:** 2.50 seconds
- **Average Publish Rate:** 2,000.0 events/sec

---

## 8. Technical Distinctions & Performance Boundaries

To prevent any confusion between simulator performance and end-to-end system acceptance criteria, the following boundaries are strictly enforced:

1. **100K Vehicle Population Coverage:** Empirically proven above. Confirms the simulator architecture handles 100,000 distinct vehicle states simultaneously in memory (<25 MB idle state, <62 MB with full event validation) and guarantees 100% unique VIN coverage.
2. **Simulator Generation Rate:** The single-thread synthetic generation speed measured in Python (~80,000 events/sec in memory). This measures generator throughput in isolation.
3. **Final System 100K Events/Sec Benchmark:** The end-to-end system throughput target (REQ-021) spanning distributed producer instances, Redpanda broker ingress, schema validation workers, and datastore sinks. **The simulator generation rate is NOT claimed as evidence for the final hackathon throughput target.** REQ-021 remains `NOT_STARTED` pending the dedicated distributed load benchmark in later phases.

