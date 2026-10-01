# FleetGuard Pulse — Enterprise React Dashboard Demo & Evaluation Guide

## 1. Executive Summary

The **FleetGuard Pulse Web Dashboard** is a responsive, single-page enterprise web application built with **React 18**, **Vite**, **Tailwind CSS**, and **Leaflet**. It connects to the FastAPI backend service layer, Redis transient cache, PostgreSQL relational datastore, pgvector semantic similarity search, and Redpanda Kafka event streams.

The dashboard fulfills **REQ-020** of the FleetGuard technical specification, enabling dispatchers, fleet managers, and maintenance technicians to monitor vehicle health in real time, inspect CAN-bus telemetry, interrogate probabilistic 7-day failure risks with local feature explanations, match high-dimensional fault signatures, and dispatch 3NF work orders.

---

## 2. Technical Stack & Governance Alignment

In strict accordance with `docs/ARCHITECTURE_LOCK.md`:
- **UI Framework**: React 18 + TypeScript + Vite (`frontend/`)
- **Styling**: Tailwind CSS (dark mode optimized, slate/cyan theme)
- **Mapping**: Leaflet + `react-leaflet` with OpenStreetMap raster tiles and custom colored SVG pins
- **Icons**: Lucide React
- **Client Protocol**: REST API via Fetch API + Reconnecting WebSocket (`/ws/alerts`)
- **Testing**: Vitest + React Testing Library + `@testing-library/jest-dom`
- **Zero Scope Expansion**: No extra databases, no auxiliary backend frameworks, no unverified ML models.

---

## 3. Launch & Demo Execution Guide

### 3.1 Prerequisites
Ensure the underlying datastores and backend services are active:
- PostgreSQL 16 on port 5433
- Redis 7 on port 6380
- Redpanda Kafka on port 9092
- ClickHouse on port 8123

### 3.2 Starting the FastAPI Backend
```bash
# From workspace root
.venv/bin/uvicorn services.api.main:app --host 0.0.0.0 --port 8000
```
API endpoints are available at `http://localhost:8000` (OpenAPI Swagger docs at `http://localhost:8000/docs`).

### 3.3 Launching the Frontend Development Server
```bash
cd frontend
npm install
npm run dev
```
The development server boots at `http://localhost:3000`. Vite automatically proxies `/api` requests to `http://localhost:8000` and `/ws` to `ws://localhost:8000`.

### 3.4 Production Build Verification
```bash
cd frontend
npm run build
npm run preview
```
Build output completes in ~1.6s producing optimized, gzipped bundles in `dist/`.

---

## 4. Comprehensive Page & Feature Walkthrough

### 4.1 Fleet Overview Dashboard (`/`)
*Route: `http://localhost:3000/`*

#### Key Capabilities & Controls:
1. **Fleet Division Switcher**: Dropdown filtering metrics and vehicle lists by fleet division (e.g. Metro Transit - Downtown Rapid, Regional Logistics - North).
2. **KPI Metric Row**:
   - **Total Monitored Vehicles**: Count of active assets in the selected division.
   - **Operational Availability**: Percentage of vehicles currently in active service.
   - **Active Critical Alerts**: Real-time count of unresolved critical events.
   - **High 7-Day Risk Vehicles**: Count of vehicles exceeding the predictive maintenance dispatch threshold.
3. **Geospatial Fleet Positioning (Leaflet Map)**:
   - Interactive OpenStreetMap canvas rendering current vehicle locations.
   - Health status pins: Green (Nominal), Amber (Warning), Pulsing Red (Critical Breakdown Risk).
   - Auto-bounding map updater adjusting coordinates when filtering.
   - Interactive popups displaying VIN, model, fleet, speed in km/h, and a direct "View Vehicle Telemetry" navigation action.
4. **Filterable, Paginated Vehicle Inventory**:
   - Filter by fleet division, powertrain type (`ICE`, `HEV`, `BEV`), and operational status (`ACTIVE`, `MAINTENANCE`, `INACTIVE`).
   - Instant client-side text search by VIN, license plate, make, or model.
   - Server-side pagination controls (Previous, Next, page indicator).
   - Direct "Inspect" link navigating to `/vehicles/:vin`.

---

### 4.2 Vehicle Details & Real-Time CAN Gauges (`/vehicles/:vin`)
*Route: `http://localhost:3000/vehicles/1HGCR2F83HA000001`*

#### Key Capabilities:
1. **Vehicle Identity Banner**:
   - Monospace VIN, license plate, make, model, manufacture year, powertrain badge (`ICE (Diesel)`, `HEV (Hybrid)`, `BEV (Electric)`), and current health badge.
   - Direct "Dispatch Work Order" modal trigger button.
2. **Live CAN-Bus Telemetry Stream Card**:
   - Real-time gauge cards displaying current state cached in Redis:
     - Speed (km/h)
     - Vibration amplitude (g)
     - Cumulative Odometer (km)
   - **Powertrain-adaptive instrumentation**:
     - *ICE / HEV*: Coolant Temperature (°C), Oil Pressure (kPa), Engine RPM.
     - *BEV / HEV*: High-Voltage Battery SOC (%), Pack Voltage (V), Cell Temperature Delta (Δ°C).
   - **Active Diagnostic Trouble Codes (DTC)**: Monospace pill badges for active DTCs (e.g. `P0115`, `P0300`) or "None (Healthy)".
   - Sequence number, last update timestamp, and GPS coordinates.
3. **Authoritative 3NF Relational Specifications**:
   - Fleet assignment, home depot location, initial baseline odometer, engine displacement (L), battery capacity (kWh), and curb weight (kg).
4. **Recent Vehicle Alerts**: Bounded table of historical alert events specifically flagged for this vehicle.

---

### 4.3 Predictive Maintenance 7-Day Failure Risk Panel
*Located on `/vehicles/:vin` (right column)*

#### Domain Alignment & Transparency:
1. **Estimated 7-Day Risk Metric**:
   - Displayed strictly as an **Estimated 7-day maintenance risk probability** (e.g. `38.4%`), never as a guaranteed mechanical failure.
   - Decision threshold marker (e.g. `35%`) indicating whether maintenance dispatch is probabilistic warranted.
   - Model version indicator: `logreg-v1-purged` (purged cross-validation logistic regression model).
2. **Local Factor Attribution**:
   - **Top Risk-Increasing Factors**: Visual cards detailing feature names, observed values, standardized z-scores, logistic regression coefficients, and directional contributions (e.g. `coolant_temp_c`, `vibration_std`).
   - **Top Protective Factors**: Mitigating variables reducing failure risk (e.g. `oil_pressure_kpa`).
3. **Mandatory Probabilistic Disclaimer**:
   - Displayed in a highlighted notice box:
     > *"Estimated 7-day maintenance risk probability based on historical telemetry patterns. This prediction is probabilistic and does not constitute a guaranteed mechanical failure."*
4. **Dispatch Work Order Modal**:
   - Clicking "Dispatch Work Order" opens an interactive modal.
   - Fields: Service Type (Inspection, Oil Renewal, Brake Service, Battery Diagnostic, Engine Overhaul), Priority (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`), Target Date/Time, and contextual Technician Notes pre-populated with the risk factor explanation.
   - Form submission performs an authenticated `POST /maintenance/work-orders` directly persisting the order into the 3NF relational schema.

---

### 4.4 Diagnostic Signature Vector Search (`/diagnostics`)
*Route: `http://localhost:3000/diagnostics`*

#### pgvector Cosine Distance Search:
1. **Pre-Loaded Diagnostic Presets**:
   - 1-click preset buttons allowing evaluators to immediately test high-dimensional vector search without manually typing vectors:
     - *Engine Overheating (ICE)*: Thermal variance and oil pressure drop pattern.
     - *Inverter Thermal Stress (BEV)*: High cell delta and voltage oscillation.
     - *Severe Bearing Vibration (ICE/HEV)*: Harmonic vibration anomaly.
     - *Battery Cell Degradation (BEV)*: Internal resistance signature.
     - *Nominal Operating Profile*: Healthy baseline vector.
2. **Custom 16-D JSON Vector Input**:
   - Text area accepting raw 16-element floating-point arrays `[0.1, 0.2, ...]`.
   - Client-side validation enforcing exact 16-dimension length and numeric validity.
3. **Filter & Top-K Controls**:
   - Filter by vehicle type (`ICE`, `HEV`, `BEV`, or All).
   - Top-K selector (3, 5, or 10 nearest neighbors).
4. **Nearest Match Cards**:
   - Displays candidate signatures from PostgreSQL `diagnostic_signatures` table.
   - Metrics: Cosine distance (e.g. `0.0421`), similarity score percentage (`95.8%`), vehicle type, fault type, descriptive symptoms, and feature schema version.

---

### 4.5 Live Ingestion WebSocket Monitor (`/alerts`)
*Route: `http://localhost:3000/alerts`*

#### Real-Time Telemetry Push:
1. **WebSocket Status Pill**: Indicates `STREAMING ACTIVE` (green) or `RECONNECTING` (amber/red) for `/ws/alerts`.
2. **Live Ingestion Feed**:
   - Bounded sliding buffer (up to 50 events) receiving real-time `CRITICAL_ALERT` frames pushed over WebSocket.
   - Client-side deduplication via Set preventing duplicate display of identical `alert_id`s.
   - Heartbeat PING frames transmitted every 25 seconds to keep long-lived TCP connections alive.
3. **Global Live Alert Notification Banner**:
   - Whenever an unacknowledged critical alert arrives over WebSocket, a prominent banner appears at the top of the entire dashboard across all pages.
   - Displays fault type, vehicle VIN, and message, with an instant "Inspect Vehicle" 1-click navigation button and dismiss control.
4. **Historical Relational Registry**:
   - Server-side paginated table querying PostgreSQL `alerts` table.
   - Filterable by severity (`CRITICAL`, `WARNING`, `INFO`).

---

## 5. Automated Verification & Test Results

### 5.1 Frontend Unit & Component Tests (`vitest`)
All 6 test suites and 22 unit tests pass cleanly:
```bash
cd frontend && npm test
```
```
 ✓ src/__tests__/WebSocketDeduplication.test.ts (2)
 ✓ src/__tests__/ApiClient.test.ts (3)
 ✓ src/__tests__/Badge.test.tsx (6)
 ✓ src/__tests__/WorkOrderModal.test.tsx (3)
 ✓ src/__tests__/PredictiveRiskPanel.test.tsx (5)
 ✓ src/__tests__/VehicleTelemetryCard.test.tsx (3)

 Test Files  6 passed (6)
      Tests  22 passed (22)
   Duration  1.39s
```

### 5.2 Frontend Production Bundle Build
```bash
cd frontend && npm run build
```
```
✓ 1534 modules transformed.
dist/index.html                   0.80 kB │ gzip:   0.52 kB
dist/assets/index-DQB8LRr6.css   49.31 kB │ gzip:  12.77 kB
dist/assets/index-Cn3Yt59K.js   421.16 kB │ gzip: 121.78 kB
✓ built in 1.63s
```

### 5.3 Backend Integration & Contract Tests (`pytest`)
All 113 backend unit, integration, and contract tests pass with 100% success rate:
```bash
.venv/bin/python3 -m pytest tests/ -q
```
```
........................................................................ [ 63%]
.........................................                                [100%]
113 passed, 2 warnings in 3.65s
```

---

## 6. Summary of Phase 9 Deliverables

| Deliverable | Location | Description |
| :--- | :--- | :--- |
| **Frontend Project** | `frontend/` | Complete Vite + React 18 + Tailwind SPA |
| **API Client** | `frontend/src/services/api.ts` | Fully typed client aligned with FastAPI OpenAPI schemas |
| **Auth Subsystem** | `frontend/src/services/auth.ts` | Bearer JWT resolver with role claims for Metro Transit |
| **WebSocket Hook** | `frontend/src/hooks/useAlertsWebSocket.ts` | Reconnecting hook with deduplication and 25s heartbeat |
| **Leaflet Map** | `frontend/src/components/vehicles/VehicleMap.tsx` | Health-status colored pin markers and auto-bounding |
| **Predictive Risk Panel** | `frontend/src/components/vehicles/PredictiveRiskPanel.tsx` | 7-day failure risk, decision threshold, local feature factors, disclaimer |
| **Vector Diagnostic Search** | `frontend/src/components/diagnostics/DiagnosticSimilarityPanel.tsx` | 16-D pgvector cosine similarity search with 5 presets |
| **Work Order Modal** | `frontend/src/components/maintenance/WorkOrderModal.tsx` | 3NF work order creation with validation |
| **Demo Guide** | `docs/ui-demo.md` | Complete UI walkthrough, architectural notes, and test evidence |

---

## 7. Phase 9.1 Browser Acceptance Walkthrough & Audit Evidence

### 7.1 Real Browser Automated Walkthrough
An automated end-to-end browser acceptance walkthrough was executed via Playwright Headless Chromium against live running services:
- **FastAPI Backend**: `http://localhost:8000` (PID / Uvicorn daemon)
- **Vite React Frontend**: `http://localhost:3000` (PID / Vite dev daemon)
- **Datastores**: PostgreSQL 16 (`localhost:5433`), Redis 7 (`localhost:6380`), ClickHouse (`localhost:8123`), Redpanda Kafka (`localhost:9092`)

Execution script: `scripts/browser_acceptance_walkthrough.py`

### 7.2 Walkthrough Journey Results

| Journey | Target | Verified Behavior | Status |
| :--- | :--- | :--- | :--- |
| **A. Fleet Overview** | `/` | Real KPIs rendered from `/fleets/{id}/health`: 10,003 monitored vehicles, 90.0% availability, 1 critical alert, 1 high-risk vehicle. Leaflet map rendered with 25 vehicle markers. Inventory table loaded 20 vehicles on page 1. First VIN: `1HGCR2F83HA000001`. | **PASS** |
| **B. Vehicle Details** | `/vehicles/1HGCR2F83HA000001` | Authoritative 3NF relational specifications and telemetry stream components rendered without layout shift. | **PASS** |
| **C. Predictive Risk** | `/vehicles/1HGCR2F83HA000001` | Estimated 7-day maintenance risk probability displayed (2.0%), advisory threshold (35%), model version `logreg-v1-purged`. Mandatory probabilistic advisory notice displayed directly from backend schema. | **PASS** |
| **D. Diagnostics** | `/diagnostics` | 16-D pgvector cosine search executed against PostgreSQL. Top match `EXCESSIVE_VIBRATION` returned with 31.0% similarity score (cosine distance 0.6904). | **PASS** |
| **E. Alerts Overview** | `/alerts` | WebSocket status verified `STREAMING ACTIVE`. Historical PostgreSQL alerts table loaded. | **PASS** |
| **F. Live Alert Push** | `/ws/broadcast` → Browser | Injected critical alert (`COOLANT_THERMAL_RUNAWAY`, VIN `1HGCR2F83HA000001`) via backend broadcast endpoint. Connected browser received frame over WebSocket without page refresh; `LiveAlertBanner` rendered at top of UI. | **PASS** |
| **G. Direct Routing** | Live Banner → `/vehicles/:vin` | Clicking "Inspect Vehicle" on live alert banner navigated directly to `/vehicles/1HGCR2F83HA000001`. | **PASS** |
| **H. 3NF Work Order** | UI Modal → PostgreSQL | Dispatched maintenance work order from modal (priority: `HIGH`, notes: `"Browser acceptance walkthrough verified dispatch"`). Created order ID: `fb20f3a8-3279-4787-abdb-4b6243080e8f`. Verified directly in PostgreSQL `work_orders` table (`status=PENDING`, `priority=HIGH`). | **PASS** |
| **Responsive Check** | Tablet (768x1024) | Viewport 768px tested: document `scrollWidth` exactly equals 768px (zero horizontal page overflow). | **PASS** |
| **UI Error State** | `/vehicles/VIN_NONEXISTENT_9999` | Handled 404 gracefully with user-friendly alert banner ("Operation Failed / Vehicle with VIN ... not found"). | **PASS** |

### 7.3 Screenshot Evidence Catalog
All high-resolution browser screenshots are preserved in `docs/screenshots/`:

1. `docs/screenshots/01_fleet_overview.png` — Fleet Overview KPIs and Leaflet map markers
2. `docs/screenshots/02_vehicle_details.png` — 3NF relational metadata and telemetry stream card
3. `docs/screenshots/03_predictive_risk.png` — 7-Day failure risk, factor attribution, and disclaimer
4. `docs/screenshots/04_diagnostics_similarity.png` — pgvector 16-D nearest neighbor search matches
5. `docs/screenshots/05_alerts_overview.png` — Live WebSocket indicator and historical alerts table
6. `docs/screenshots/06_live_critical_alert.png` — Dynamic real-time critical alert banner received over WebSocket
7. `docs/screenshots/07_work_order_dispatched.png` — Confirmed 3NF work order dispatch dialog
8. `docs/screenshots/08_tablet_viewport.png` — Tablet viewport (768x1024) responsive layout
9. `docs/screenshots/09_error_state.png` — Clean non-existent resource error alert

### 7.4 Credential & Secret Hygiene Audit
A full repository audit was conducted:
- **No hardcoded secrets or JWTs**: All development tokens and credentials removed from tracked source files.
- **Environment-driven**: Auth token resolution in `frontend/src/services/auth.ts` strictly uses `localStorage` or `import.meta.env.VITE_AUTH_TOKEN`.
- **Token Generation Tooling**: Added `scripts/generate_dev_token.py` to securely mint HMAC dev tokens for local testing.
- **Git Hygiene**: Verified `.env` and `frontend/.env` are ignored by git (`.gitignore`). Tracked files contain zero secret leakage.

