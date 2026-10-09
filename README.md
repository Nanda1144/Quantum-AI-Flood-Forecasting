# Q-FLARE — Quantum-AI Flood Forecasting & Disaster-Response Platform

A command-center platform that pairs **AI flood forecasting intelligence** with
**quantum optimization** for sensor placement and disaster-response planning.

> Status: early platform scaffolding. The **AI Analytics dashboard**, the
> **AI integration microservice** powering it, and the **quantum optimization
> orchestration stack** (`POST /api/optimization/run` pipeline, job store, the
> `quantum-service` QUBO/QAOA contract) are implemented end-to-end.

---

## Table of Contents

- [Architecture](#architecture)
- [Module ownership](#module-ownership)
- [Directory layout](#directory-layout)
- [Data flow / workflow](#data-flow--workflow)
- [Quick start](#quick-start)
- [Tech stack](#tech-stack)
- [Configuration](#configuration)
- [Related documentation](#related-documentation)

---

## Architecture

Q-FLARE is organised as a set of small microservices plus a single React
frontend. The frontend never computes forecasts itself — it consumes model and
forecast data **only through the service APIs**.

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Frontend (React + TS)                          │
│               AI Analytics · Quantum Optimization                      │
│                                   │                                   │
│                         REST over /api                               │
└───────────────┬──────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────┐        ┌──────────────────────────┐
│          backend (Node/Express)  │        │    quantum-service       │
│  API gateway · analytics API     │◄──────►│  QUBO construction /     │
│  optimization orchestration      │ 8100   │  QAOA execution          │
│  auth · RBAC · validation        │        └──────────────────────────┘
└───────┬──────────────────────────┘
        │ HTTP (ForecastClient contract)
┌───────▼──────────────────────────┐         ┌────────────────────────┐
│   ai-service (FastAPI :8000)     │◄───────►│        PostgreSQL      │
│   forecasting engine contract    │ sync    │ forecasts · models ·   │
│   (the engine plugs in here) │         │ optimization jobs      │
└──────────────────────────────────┘         └────────────────────────┘
```

The **optimization stack** is behind the Node backend: `POST
/api/optimization/run` 202-queues a 15-step pipeline job that the UI polls
(`GET /api/optimization/:id`, `/api/optimization/jobs/:id/{pipeline,result,
qubo,classical,export}`, `/api/optimization/inputs`). The gateway is the only
consumer of `quantum-service` — the browser never talks to it. A failing
executor (hardware down, Aer missing, QUBO error) never takes the platform
down: the configured fallback policy (`retry_simulator` default) keeps every
job finishing against a persisted classical reference benchmark. **No quantum
speedup is ever claimed.**

The `quantum-service` also exposes a **generic QUBO generation + retrieval API**
(consumed by the backend's contract seam and exercised by its contract tests):
`POST /quantum/qubo` accepts a shape-dispatched payload — the original
sensor-placement body (`candidates`) *or* a generic body (`variables` +
explicit `objective` + `constraints` + optional `weights`) — and stores a
clean-JSON QUBO document retrievable via `GET /quantum/qubo/:id`,
`GET /quantum/qubo/:id/variables` (semantic variable→candidate mapping), and
`GET /quantum/qubo/:id/constraints`. See `quantum-service/README.md`.

### How the AI Analytics page gets its data

1. The React page `/` (`AI Analytics`) calls `loadAIAnalytics()` from
   `frontend/src/services/aiService.ts`.
2. In dev, Vite proxies `/api` to `http://localhost:3000` (see
   `frontend/vite.config.ts`) — the **Node `backend` gateway**.
3. The gateway exposes `GET /api/ai/analytics` (plus companion endpoints),
   syncing the latest forecast and model registry from the **AI FastAPI
   service** (`../ai-service`, port `:8000`) into PostgreSQL, then assembling
   a snapshot that matches the frontend contract in `frontend/src/types/ai.ts`.

The dashboard therefore uses **real backend API responses** — values such as
flood probability, water level, timestamps, and model metrics are never
hard-coded in the UI (the React sample-data fallback is opt-in and clearly
flagged as mock).

### How the Model Comparison page gets its data

The `/model-comparison` route (`frontend/src/pages/ModelComparison.tsx`) reads
stored model evaluations — it does **not** compute metrics itself. It calls
`aiApi.getModelsComparison()` against the gateway's
`GET /api/ai/models/comparison` endpoint, which filters/sorts the persisted
`model_versions`/`model_metrics` rows (latest metric per version) and returns
them plus the evaluated-date range and evaluation datasets. The page only
arranges extrema (best R² / lowest RMSE etc.) and never invents values; rows
without stored scores are shown as "—". Version status and production
promotion are managed server-side by the registry — the page offers no
authorization path.

A companion read-only registry contract backs the same page with a formal API:

- `GET /api/ai/models` — paginated, filterable version list.
- `POST /api/ai/models/compare?{model_ids}` — aggregates the requested
  versions' latest stored metrics and applies the documented selection policy
  (primary metric via `MODEL_SELECTION_METRIC`, tie-breaks `rmse → mae →
  inferenceTime`, `rationale` for traceability). See `backend/README.md`
  "Model selection policy".
- `GET /api/ai/models/:id` — full metadata; `GET /api/ai/models/:id/metrics` —
  historical evaluation runs.

All registry endpoints are **read-only**: the API never creates, promotes, or
retires model versions, so a mis-issued request cannot change deployment
state.

---

## Module ownership

Clear ownership boundaries keep the AI and ML concerns separate:

| Area | Owner | Scope |
| --- | --- | --- |
| **AI integration (this work)** | Nanda | `backend` (Node gateway: analytics API, auth/RBAC, validation) + `ai-service` (FastAPI contract service) + `frontend` AI Analytics page, routing, state, components |
| **Forecasting / training pipeline** | Forecasting | Model training, feature engineering, live inference — implemented as a `ForecastEngine` behind `ai-service` (XGBoost/LSTM/GRU swap without touching the API) |
| **Quantum optimization** | Nanda | `backend` (optimization orchestration service, `/api/optimization/*` routes, ownership/fallback policy, job persistence) + `quantum-service` (QUBO construction & QAOA execution contract) |
| **GIS / IoT / database / deployment** | — | Supporting infrastructure modules |

The Node backend and `ai-service` implement **no ML training or forecasting
pipeline**. `ai-service` defines the *integration contract* (a
`ForecastEngine` protocol) that today is satisfied by a deterministic
reference engine. When the pipeline provides an engine, it is registered
in `ai-service` (`FORECAST_ENGINE=<module>:<Class>`), and the REST contract
consumed by the Node backend stays unchanged.

---

## Directory layout

| Path | Description |
| --- | --- |
| `frontend/` | React + TypeScript + Vite + Tailwind command-center UI |
| `backend/` | **Node/Express API gateway** — AI analytics endpoints, auth/RBAC, rate limiting, validation, PostgreSQL persistence |
| `ai-service/` | **FastAPI forecasting service** — stable REST contract + `ForecastEngine` seam for the pipeline |
| `quantum-service/` | **FastAPI QUBO/QAOA service** — deterministic reference executor for `POST /quantum/qubo` (sensor-placement *and* generic payloads), `GET /quantum/qubo/:id`, `/quantum/qubo/:id/variables`, `/quantum/qubo/:id/constraints`, `POST /quantum/optimize`, `GET /quantum/result/:id` |
| `database/` | **Schema & persistence** — reverse migrations, model registry (`model_versions`/`model_metrics`), dev-marked seeds |
| `gis/` | Geospatial data module — contract defined (`/api/optimization/inputs` candidate sites); implementation planned, see `gis/README.md` |
| `iot/` | Sensor/IoT ingestion — contract defined (telemetry → observed water level → forecast chart); implementation planned, see `iot/README.md` |
| `deployment/` | Deployment docs, run topology, and GitHub Pages workflows — see `deployment/README.md` |
| `tests/` | Cross-module QA reports and per-feature test records — see `tests/README.md` and `tests/reports/` |
| `docs/` | Architecture & decision records index — see `docs/README.md` |
| `.github/` | GitHub Actions — frontend Pages deploy on the feature branch (`deploy.yml`) and on `main` (`static.yml`); see `.github/workflows/README.md` |

Each module carries its own `README.md` with setup and API notes.

---

## Data flow / workflow

```
AI Analytics page ──loadAIAnalytics()──► /api/ai/analytics (Node backend :3000)
        │                                        │
        │            snapshot JSON               │ getForecast() · getModels() · health()
        ▼                                        ▼
 KPI row · forecast chart · risk analytics   ForecastClient (src/clients)
 model panel · optimization bridge          (contract to the FastAPI service)
 recent predictions · system state
        │                                        │
 Optimize bridge ──► /api/optimization/from-forecast ──► optimization reference
```

1. Page mounts → `useAIAnalytics` hook fetches the composite snapshot from the
   Node gateway.
2. Every section renders from snapshot slices — no local fake data.
3. "Use Forecast for Optimization" navigates to the Quantum Optimization route
   via router state (forecast ID, risk score, priority); registering the
   optimization handoff is `POST /api/optimization/from-forecast` on the
   gateway.
4. The gateway also exposes `/api/ai/status`, `/api/ai/predictions`,
   `/api/ai/models`, and `/api/ai/models/:modelId/metrics` for finer-grained
   consumers.

### Optimization run flow

```
 Quantum Optimization page ──run()──► POST /api/optimization/run (202 + jobId)
        │                                       │
        │  poll GET /api/optimization/:id       │ OptimizationJobService (15-step)
        ▼                                       │   1 validate_request … 8 construct_qubo
  Live pipeline · summary · result              │   9 classical_benchmark (always stored)
  (jobs/:id/pipeline|result|qubo|classical)     │  10 execute_qaoa ──► quantum-service
                                                │     (simulator|aer|ibm_hardware + fallback)
                                                │  11 decode_bitstring ◄── ∫ result/:id
                                                │  12 validate_constraints (hard gate)
                                                │  13 compare_results 14 persist_result
                                                └ 15 return_response
```

The pipeline is authoritative: weights/budget/cardinality are semantic-validated
on the wire and again in the orchestrator, candidates/constraints stream from
the federated sources, the QUBO is built locally *and* pushed to
`quantum-service`, the classical reference always runs and is always stored,
and the decoded outcome is gated by constraint validation before a result is
ever presented. Jobs are scoped to their owner (or admin) and persist through
`optimization_jobs`; completed runs are normalized into `optimization_results`
(one FK-linked row per job, location IDs only), with large QUBO matrices stored
by reference in `optimization_qubo_artifacts`. Every job also gets a QUBO audit
record in `optimization_qubo_metadata` (small problems inline the full plain-JSON
matrix/terms/penalties/expression; large ones store reference + sha-256 checksum +
dimensions only — never the cells, never raw Qiskit objects), so the experiment
is always reproducible and auditable. Completed research results are
write-once: the `qflare_guard_optimization_delete` trigger blocks hard deletes,
and the API exposes only an audited soft-delete (`optimization_job_audit`) that
requires the `admin` role and a reason (see `database/README.md`). Persistence
falls back to in-memory repositories in dev.

### Quantum Optimization dashboard (`/quantum-optimization`)

The page is a 7-step command center — Problem configuration → Objective
weights → Constraints → Execution → Live pipeline → Result summary → Actions —
backed by a pluggable execution adapter, never by inline logic:

- **Adapter seam** (`frontend/src/services/optimization/adapter.ts`): a single
  `VITE_USE_MOCK_DATA` flag picks the adapter.
  - `VITE_USE_MOCK_DATA != "false"` (default) → **mock adapter**
    (`mockAdapter.ts` + `simulate.ts`): a deterministic, clearly-flagged
    development simulator, loaded only through a dynamic import so it never
    lands in a production bundle.
  - `VITE_USE_MOCK_DATA="false"` → **HTTP adapter** (`httpAdapter.ts`): talks to
    the optimization gateway (`POST /api/optimization/run`,
    `GET /api/optimization/jobs/:id/pipeline|result|qubo|classical|export`,
    `GET /api/optimization/inputs`) implemented by the Node backend +
    `quantum-service`. Authentication is operator-class JWT via the shared
    `aiService` login; any failed request fails loudly, never silently mocks.
- **Transparent pipeline**: every stage (Input → Validation → QUBO →
  Hamiltonian → QAOA → Measurement → Decode → Constraint validation →
  Benchmark → Final) is streamed to the UI with its own status and metadata,
  including a real penalty-based QUBO build, Ising mapping, shot sampling,
  and an honest greedy decode.
- **Operational gate**: if constraint validation fails (sensor limit, budget,
  or coverage floor), the result is labelled exactly
  `INVALID SOLUTION — NOT OPERATIONALLY RECOMMENDED` and is never presented as
  a recommendation. Raising a coverage requirement to an infeasible value is
  the built-in way to exercise this path in the simulator.
- **Extensible problems**: `frontend/src/lib/quantum.ts` catalogs problem
  types + objective axes. `sensor_placement` is enabled today;
  `resource_allocation` is staged as "Planned", so adding it later means
  extending the catalog, not restructuring the page.
- **Federated inputs**: candidate sites (GIS), resource constraints
  (planning), and forecast refs (AI forecasting) arrive via the adapter's
  `getInputs()` — these modules are consumed, not re-implemented on the page.
- **Handoff**: "Use Forecast for Optimization" on the AI Analytics page
  navigates here via router state (forecast ID + priority), pre-filling the
  forecast reference and risk profile.

---

## Quick start

The entire platform is configured via a **single, unified `.env` file located at the project root**.
All services (`backend`, `ai-service`, `quantum-service`, and `frontend`) automatically read from this root `.env`.

Prerequisites: **Node.js >= 20**, npm, and Python 3.12+.

---

### Step-by-Step Execution Process

#### Step 1: Verify the Unified Environment File
Ensure the root `.env` file exists at the project root:
```sh
# The root .env contains all unified configuration parameters for:
# - Backend API Gateway (:3000)
# - PostgreSQL / Supabase connection
# - AI Forecasting Service (:8000)
# - Quantum QAOA Service (:8100)
# - Frontend Command-Center (:5173)
```

#### Step 2: Start the AI Forecasting Service (FastAPI)
In a new terminal window:
```powershell
cd ai-service
python -m venv .venv
.venv\Scripts\Activate.ps1               # On Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000
```
- Endpoint: `http://localhost:8000`
- Health check: `http://localhost:8000/health`

#### Step 3: Start the Quantum Optimization Service (FastAPI)
In a second terminal window (optional but recommended):
```powershell
cd quantum-service
python -m venv .venv
.venv\Scripts\Activate.ps1               # On Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8100
```
- Endpoint: `http://localhost:8100`
- Health check: `http://localhost:8100/health`
- *Note:* If the quantum service is offline, the backend's resilient fallback policy (`retry_simulator`) automatically completes optimization requests against the classical reference benchmark.

#### Step 4: Start the Node.js API Gateway (Backend)
In a third terminal window:
```powershell
cd backend
npm install
npm run dev
```
- API Gateway Endpoint: `http://localhost:3000`
- Health / Analytics check: `http://localhost:3000/api/ai/analytics`
- *Note:* If PostgreSQL is unreachable or `DATABASE_MODE=memory` is specified in `.env`, the backend operates in in-memory mode seamlessly.

#### Step 5: Start the Frontend Command Center (React + Vite)
In a fourth terminal window:
```powershell
cd frontend
npm install
npm run dev
```
- Open browser at: `http://localhost:5173/Quantum-AI-Flood-Forecasting/` (or `http://localhost:5173`)
- The UI automatically communicates with the Node backend gateway via Vite's `/api` proxy.

---

## Tech stack

- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS v4, Recharts,
  react-router-dom, lucide-react.
- **backend:** Node.js, Express 5, TypeScript, Zod, jsonwebtoken,
  express-rate-limit, pg, node:test.
- **ai-service:** FastAPI, Pydantic, uvicorn (Python).
- **quantum-service:** FastAPI, Pydantic, uvicorn (Python); Qiskit Aer / IBM
  runtime adapters degrade to the documented 503 when not installed.
- **Persistence:** PostgreSQL (forecasts, model registry, optimization jobs +
  normalized results/audit/QUBO artifacts).

---

## Configuration

All configuration is managed from the **single root `.env` file** at `/.env`.

### Unified Environment Variables (`/.env`)

| Variable | Default / Example | Purpose / Description |
| --- | --- | --- |
| **System** | | |
| `NODE_ENV` | `development` | Runtime mode (`development`, `production`, `test`). |
| **Backend Gateway** | | |
| `PORT` | `3000` | Gateway HTTP listener port. |
| `DATABASE_MODE` | `postgres` | `postgres` (live DB) or `memory` (in-memory demo/test). |
| `DATABASE_URL` | `postgresql://...` | PostgreSQL connection string. |
| `AUTH_ENABLED` | `true` | JWT authentication required (`true` / `false`). |
| `JWT_SECRET` | *(secret key)* | Signing secret for JSON Web Tokens. |
| `JWT_EXPIRES_IN` | `800h` | Expiration window for issued JWT tokens. |
| `FRESHNESS_STALE_MS` | `90000` | Staleness window (ms) for forecast telemetry. |
| `RATE_LIMIT_WINDOW_MS` | `60000` | Time window for API gateway rate limiter. |
| `RATE_LIMIT_MAX` | `1200` | Maximum requests per IP in the rate-limit window. |
| `MODEL_SELECTION_METRIC` | `r2` | Model registry metric ranker (`r2`, `mae`, `rmse`, `nse`). |
| **AI Service** | | |
| `AI_SERVICE_HOST` | `0.0.0.0` | AI service bind host. |
| `AI_SERVICE_PORT` | `8000` | AI service listener port. |
| `AI_SERVICE_URL` | `http://localhost:8000` | URL used by Node gateway to contact AI service. |
| `FORECAST_ENGINE` | `reference` | Forecasting model engine (`reference` or live class). |
| `AI_SERVICE_CORS_ORIGINS`| `*` | Allowed CORS origins for AI service. |
| **Quantum Service** | | |
| `QUANTUM_SERVICE_HOST` | `0.0.0.0` | Quantum service bind host. |
| `QUANTUM_SERVICE_PORT` | `8100` | Quantum service listener port. |
| `QUANTUM_SERVICE_URL` | `http://localhost:8100` | URL used by Node gateway to contact Quantum service. |
| `OPTIMIZATION_FALLBACK_POLICY` | `retry_simulator` | Fallback policy (`retry_simulator`, `classical_only`, `error`). |
| `OPTIMIZATION_EXECUTION_TIMEOUT_MS` | `120000` | Max job execution timeout (ms). |
| `OPTIMIZATION_EXHAUSTIVE_LIMIT` | `18` | Candidate limit for classical solver. |
| **Frontend UI** | | |
| `VITE_API_BASE_URL` | `''` | API base URL (empty uses Vite `/api` proxy). |
| `VITE_USE_MOCK_DATA` | `false` | Set to `false` for live backend data. |


---

## Related documentation

- **Frontend:** `frontend/README.md`
- **Node backend (API gateway):** `backend/README.md`
- **AI analytics API contract (FastAPI):** `ai-service/README.md`
- Other modules carry their own `README.md` as they are built out.

## License

[Apache-2.0](LICENSE)