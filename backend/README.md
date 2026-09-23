# backend — Q-FLARE API Gateway (Node.js + Express)

The **Node.js backend** that sits between the React command center and the
platform services:

```
React ── REST /api ──> backend (Node/Express :3000) ──> ai-service (FastAPI :8000)
                              │
                              └──> PostgreSQL (forecasts, models, optimization)
```

It owns the **AI Analytics Dashboard** API surface, the **quantum optimization
orchestration** API (`POST /api/optimization/run` and product), plus
authentication/RBAC, validation, and rate limiting. It is the *only* consumer
of the AI FastAPI service (`../ai-service`) and of the quantum-service
(`../quantum-service`), and the *only* client the browser talks to — the
frontend never reaches those services or the database directly, so no secrets
leave the server.

> **Status:** implemented. Core `ai-service` integration is live via the
> `ForecastClient` seam; forecasts and the model registry persist to
> PostgreSQL, with a graceful in-memory fallback for local demos and tests.

---

## Ownership

| Concern | Owner | Notes |
| --- | --- | --- |
| Node gateway, API surface, auth, RBAC, rate limiting | Nanda | This module |
| Forecasting models (XGBoost / LSTM / GRU) | Navya | Implemented behind the `ForecastEngine` protocol in `../ai-service`; swapped independently of this module |
| Quantum optimization orchestration | Nanda | This module — `/api/optimization/*` pipeline, job store, fallback policy, plus the `../quantum-service` executor contract it is the only consumer of |

## Quick start

Prerequisites: **Node.js >= 20**, npm. The AI service should be running on
`:8000` (see its README) and optionally PostgreSQL on `:5432`.

```sh
cp .env.example .env      # adjust values as needed
npm install
npm run dev               # http://localhost:3000  (Vite proxy forwards /api here)
npm run build             # typecheck + emit dist/
npm start                 # run the built server
```

`AUTH_ENABLED=true` (default) requires a JWT for every `/api` route; log in via
`POST /api/auth/login` with the demo users below.

### Demo users (defaults — override with `AUTH_USERS`)

| Username | Password | Role |
| --- | --- | --- |
| `admin` | `qflare-admin` | `admin` (all actions) |
| `operator` | `qflare-operator` | `operator` (includes optimization handoff) |
| `viewer` | `qflare-viewer` | `viewer` (read-only) |

## Endpoint reference

All responses use the shared envelope — success:
`{ "success": true, "data": {...}, "timestamp": "..." }`; errors:
`{ "success": false, "error": { "code", "message", "details?" }, "timestamp": "..." }`.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Gateway liveness. |
| `POST` | `/api/auth/login` | JWT login (rate-limited). |
| `GET` | `/api/ai/analytics` | Latest AI analytics summary snapshot for the dashboard. |
| `GET` | `/api/ai/predictions` | Paginated predictions (`page`, `limit`, `from`, `to`, `risk`, `model`). |
| `GET` | `/api/ai/models` | Paginated, filterable model-version registry (`page`, `limit`, `status`, `algorithm`, `dataset`). |
| `GET` | `/api/ai/models/comparison` | Legacy comparison list (sorted/filtered latest evaluations), still used by the current UI. |
| `POST` | `/api/ai/models/compare` | Compare selected versions — latest stored metrics + documented best-model selection. |
| `GET` | `/api/ai/models/:id` | Complete metadata for one registry version. |
| `GET` | `/api/ai/models/:id/metrics` | Historical evaluation scores for a version (newest first). |
| `GET` | `/api/ai/status` | AI availability, latency, last prediction, data freshness. |
| `POST` | `/api/optimization/from-forecast` | Create an optimization-ready reference from an existing forecast (no quantum execution here). |
| `POST` | `/api/optimization/run` | Validate and queue a full pipeline job (202 + `jobId`); requires `operator`. |
| `GET` | `/api/optimization/inputs` | Federated GIS candidates + planner constraints (`candidateCount`, `forecast`, `risk`). |
| `GET` | `/api/optimization/:id` | Job detail — summary (status, problem type, execution mode, algorithm) plus the integrity-audited `result` (null until persisted). |
| `GET` | `/api/optimization/:id/result` | Final result read model — selection, bitstring, objective, violations, validation, runtime, classical + quantum comparison, experiment metadata, backend integrity audit. |
| `GET` | `/api/optimization/:id/export` | Structured, auditable result export (summary, result, integrity, recommendation, experiment, disclaimer); the sensitive action is audit-logged. |
| `GET` | `/api/optimization/jobs` | Experiment ledger — every visible job as a summary, newest first (benchmark page). |
| `GET` | `/api/optimization/jobs/:id/pipeline` | Aggregated 10-stage pipeline progress for the UI. |
| `GET` | `/api/optimization/jobs/:id/result` | Legacy alias of `/api/optimization/:id/result` (same audited read model). |
| `GET` | `/api/optimization/jobs/:id/qubo` | Served QUBO document. |
| `GET` | `/api/optimization/jobs/:id/classical` | Persisted classical reference benchmark. |
| `GET` | `/api/optimization/jobs/:id/export` | Legacy alias of `/api/optimization/:id/export`. |

`GET /api/ai/models` — the registry routes CRT these records from the DB-owning
`model_versions`/`model_metrics` tables. The gateway **never computes or
invented metrics**; it only aggregates what was stored by the training/
evaluation pipeline. `status` filters on the registry status (`development`,
`active`, `retired`), while `algorithm`/`dataset` do case-insensitive substring
matching. `page`/`limit` paginate with `total`/`totalPages` in the envelope.

`POST /api/ai/models/compare` — body `{ "model_ids": ["1", "2"] }`. Ids are the
numeric registry ids and the whole request is rejected (404 `MODEL_NOT_FOUND`)
if any id is unknown; duplicates are deduplicated in request order. Responses
carry each requested version's latest stored metrics, the selection policy and
the `bestModel` verdict (see below). Ids that are not positive integers are
rejected with 422 `VALIDATION_ERROR`.

### Model selection policy

`POST /api/ai/models/compare` reports which version the documented policy would
promote, so deployments follow an explicit, auditable rule instead of a
dashboard judgment call.

1. **Primary metric** — `MODEL_SELECTION_METRIC` (default `r2`). A version is a
   candidate only when it has a **finite stored value** for that metric — no
   scores are extrapolated or defaulted.
2. **Direction** — higher is better for `r2`/`nse`; lower is better for
   `mae`/`rmse`/`inferenceTime` (mirrors the Postgres CHECK bounds).
3. **Minimum size** — `bestModel` requires at least `minCandidates` (2) scored
   candidates; otherwise it is `null` (no basis for a decision).
4. **Tie-breaks** — candidates equal on the primary metric fall back to the
   exclusively-regression chain `rmse → mae → inferenceTime`, then model name
   for determinism.
5. **Traceability** — `bestModel.rationale` states the deciding metric,
   direction, score, tie count, and any tie-break used.

Example best-policy payload:

```json
{
  "models": [],
  "bestModel": {
    "modelId": "3",
    "name": "QEnhanced-LSTM",
    "version": "v1.1-dev",
    "metric": "r2",
    "score": 0.97,
    "rationale": "selected by policy metric 'R²' (higher is better) with score 0.970; from 2 scored candidates; tied on 'R²' with 'Deep-Transformer'; resolved by 'RMSE' (0.140 vs 0.170)."
  },
  "policy": { "primaryMetric": "r2", "higherIsBetter": true, "tieBreakers": ["rmse", "mae", "inferenceTime"], "minCandidates": 2 }
}
```

The registry endpoints are read-only. There is no mutation surface here —
deployment/status changes are owned by the training pipeline, not this API.

### Example — latest analytics summary

`GET /api/ai/analytics` returns the dashboard snapshot, including the forecast:

```json
{
  "success": true,
  "data": {
    "forecast": {
      "forecastId": "FC-20260916-422",
      "floodProbability": 0.42,
      "riskLevel": "MEDIUM",
      "predictedWaterLevel": 7.606,
      "forecastHorizon": "24h",
      "modelId": "MODEL001",
      "modelName": "GRU FloodNet Ensemble",
      "modelVersion": "v1.14.0",
      "predictionTimestamp": "2026-09-16T...+00:00",
      "status": "completed",
      "priority": "medium",
      "createdAt": "..."
    },
    "forecastSeries": [],
    "riskAnalytics": {},
    "activeModel": {},
    "recentPredictions": [],
    "optimizationReadiness": {},
    "systemHealth": {},
    "updatedAt": "..."
  },
  "timestamp": "..."
}
```

The camelCase body matches `frontend/src/types/ai.ts` verbatim, so the
dashboard renders directly from the response without client-side translation.

### Optimization orchestration

`POST /api/optimization/run` is the single entry point. The body is
**snake_case** on the wire (the frontend HTTP adapter converts from its
camelCase model):

```json
{
  "problem_type": "sensor_placement",
  "candidate_count": 24,
  "max_sensors": 6,
  "budget_k": null,
  "forecast_reference": "FC-20260916-422",
  "risk_profile": "MEDIUM",
  "execution_mode": "simulator",
  "hardware_enabled": false,
  "backend": "qflare_simulator_statevector",
  "shots": 1024,
  "layers": 2,
  "weights": { "risk": 0.3, "populationCoverage": 0.3, "infrastructureCoverage": 0.2, "communication": 0.1, "cost": 0.1, "redundancy": 0 },
  "normalize_weights": true,
  "coverage_requirements": [],
  "candidate_locations_reference": "gis://candidates/24"
}
```

Semantic checks that need candidate geometry happen in the orchestrator, not
the schema: at least one weight > 0, `max_sensors ≤ candidate_count`, and if a
budget is given it must at least cover the cheapest site
(`INFEASIBLE_BUDGET`). The job runs the 15-step pipeline (validate → inputs →
constraint defaults → QUBO construction → Hamiltonian → classical benchmark →
QAOA execution → measurement → decode → constraint validation → compare →
persist), returning `QOP-…` job ids.

**Fallback policy** (`OPTIMIZATION_FALLBACK_POLICY`) decides what happens when
an executor fails: `retry_simulator` (default) falls back to the simulator for
`aer`/`ibm_hardware` failures, `classical_only` skips the quantum step and
completes the job against the classical reference, `error` fails the job with
the executor's error code. Failures surfaced by the executor map to stable
codes: `QUBO_GENERATION_FAILED`, `QAOA_EXECUTION_FAILED`, `AER_UNAVAILABLE`,
`HARDWARE_UNAVAILABLE`, `QUANTUM_UNAVAILABLE`, `DECODING_FAILED`,
`EXECUTION_TIMEOUT`. Job reads are **ownership-scoped**: a job is only visible
to its owner or an admin (unknown → 404 `JOB_NOT_FOUND`, no existence leak).
A result labelled `INVALID SOLUTION — NOT OPERATIONALLY RECOMMENDED` (invalid
constraint validation) is never presented as a recommendation. **No quantum
speedup is ever claimed** — every result carries
`quantumAdvantageClaimed: false` and is always paired with the persisted
classical reference benchmark.

### Optimization persistence layer

Completed jobs are normalized into the `004_optimization_persistence` schema
(Nanda's ownership):

| Table | Purpose |
| --- | --- |
| `optimization_jobs` | Operational record (003) plus scalar **exact-configuration** columns added in 004: `forecast_reference`, `candidate_reference`, `input_reference`, `variables_count`, `constraints`, `objective_configuration`, `error_message`, soft-delete columns, and QUBO placement (`qubo_storage`/`qubo_artifact_reference`). |
| `optimization_results` | One row per completed job (FK `fk_optimization_results_job`): `bitstring`, `selected_locations` (location **IDs only**, never GIS geometry), `objective_value`, `constraint_violations`, `validation_status`, `runtime_ms`, `classical_objective`, `quantum_objective`, `approximation_quality`. Migration 007 adds the **classical benchmark reference snapshot**: `classical_solver`, `classical_runtime_ms`, `approximation_ratio`, `approximation_basis`, `approximation_invalid_reason`, `random_seed`. |
| `optimization_job_audit` | Write-once trail for delete-protection events (`action`, `actor`, `reason`). |
| `optimization_qubo_artifacts` | QUBO matrices too large to inline. Small demonstrative QUBOs (≤ `OPTIMIZATION_QUBO_INLINE_LIMIT` variables) stay inline; larger ones are stored here and referenced from the job row. |
| `optimization_qubo_metadata` | QUBO metadata **audit record** (migration 005), one row per job (`qubo_id` = `<jobId>-Q1`). Small problems inline the matrix, linear/quadratic terms, penalty configuration and objective expression as plain JSON; large problems store only `artifact_reference` + sha-256 `checksum` + `matrix_dimensions` + `storage_location` + `metadata` — the cells are never embedded and no raw Python/Qiskit objects are persisted. |
| `quantum_jobs` | One row per **real quantum submission** (migration 006). Only configuration scalars and plain-JSON counts are stored — never credentials, never raw circuit objects. Each submission — including every failed attempt on a fallback ladder — gets its own honest row so the simulator/hardware distinction is preserved. |
| `quantum_results` | One normalized result row per completed quantum job (migration 006), `id` = `<quantum_job_id>-R1`. |

Required indexes: `optimization_jobs(status, problem_type, created_at)`,
`optimization_results(optimization_job_id, validation_status, created_at)`,
`optimization_qubo_metadata(optimization_job_id, created_at)`, plus the 006 set
(`quantum_jobs(optimization_job_id)`, `quantum_jobs(status)`,
`quantum_jobs(created_at)`, `quantum_results(quantum_job_id)`,
`quantum_results(created_at)`).

**Classical benchmark reference (migration 007).** The benchmark contract is
persisted in `optimization_results` rather than a redundant benchmark table:
every contract field already had a home in the results model — `classical_objective`,
`quantum_objective`, `constraint_violations`, problem size and the exact
experiment configuration (`optimization_jobs.request` / `variables_count`),
`quantum_runtime_ms` (`quantum_results.runtime_ms`, 006) and `created_at` — so
migration 007 only adds the six values without a normalized home:
`classical_solver`, `classical_runtime_ms`, `approximation_ratio`,
`approximation_basis`, `approximation_invalid_reason` and `random_seed`. The
snapshot is computed once at pipeline completion
(`OptimizationJobService.toResultRecord`) from the stored measurements and is
**write-once**: the repository upsert preserves any existing snapshot via
`COALESCE`, so a rerun never overwrites historical benchmark results. The
`approximation_ratio` is the raw direction-aware quotient (never clamped; NULL
only with a known `approximation_invalid_reason` code) and `approximation_basis`
records whether it was measured against the `exhaustive` optimum or the `greedy`
heuristic. `GET /:id/benchmark` returns the stored snapshot verbatim; rows
recorded before 007 fall back to read-time computation.

**Quantum submission persistence (migration 006).** The orchestrator best-effort
persists real quantum work when it sees the service's `job_id`: a `queued` row
on the accepted `optimize()` result, then `completed` + result (or `failed`
with code/message) for the attempt that produced the outcome. Persistence is
guarded (`repo` + `jobId` present) and never breaks the pipeline — a storage
error is logged and the run continues. `quantum_jobs` enforces `execution_mode`
and `status` CHECK bounds and `submitted_at ≤ started_at ≤ completed_at`;
`quantum_results` is one row per job (`PRIMARY KEY`, `id` = `<job_id>-R1`), both
FK `ON DELETE CASCADE` from `optimization_jobs` / `quantum_jobs`. There is no
backfill: only real submissions are recorded.

**Delete protection.** Completed research results are write-once. The
`qflare_guard_optimization_delete` trigger rejects any hard `DELETE` of a
completed job or its result row (SQLSTATE `P0001`) unless the administrative
escape hatch `app.allow_optimization_delete` is set. The API never hard-deletes:
`DELETE /api/optimization/jobs/:id` (operator, ownership-scoped) is a **soft
delete** that requires an auditable `reason`; completed results additionally
require the `admin` role, otherwise `403 DELETE_PROTECTED`. The row is retained
with `deleted_at`/`deleted_by`/`delete_reason` and the event is written to
`optimization_job_audit`.

Persistence read/write surfaces: `GET /api/optimization/jobs/:id/results`
(normalized row, 404 `RESULT_NOT_FOUND`), `GET /api/optimization/jobs/:id/audit`
(delete-protection trail), and `GET /api/optimization/jobs/:id/qubo` (returns
`storage`, `inline`, and `artifactReference`).

### Quantum benchmarking read-out

`GET /api/optimization/:id/benchmark` (viewer, ownership-scoped) assembles a
read-only **benchmark document** from the stored result. It restates only raw,
write-once measurements — the greedy/exhaustive classical reference, the quantum
outcome (objective, executor runtime), constraint violations, and reproducibility
metadata — and makes **no quantum speedup claim**. The benchmark document
contains:

- `problem` size/type and `classical` reference: solver (`exhaustive` when the
  instance is ≤ `OPTIMIZATION_EXHAUSTIVE_LIMIT` and ≤ 24 candidates, else
  `greedy`), summed utility objective, `optimal`, and runtime.
- `quantum`: algorithm (`qaoa`), objective, `runtimeMs` read from the persisted
  `quantum_results.runtime_ms` (`runtimeSource:
  "quantum_results.runtime_ms"`), device notes, or the removal reason when no
  real quantum execution happened.
- `approximationRatio`: `direction: "maximize"` and a direction-aware ratio
  (`quantum / reference`, only when the reference is positive and the quantum
  objective is non-negative; never blind-divisioned, never clamped). `basis` is
  `"exact_optimal"` (exhaustive) or `"greedy_reference"` and is stated honestly;
  a ratio above 1.0 against a greedy reference is not an optimality claim.
  When no ratio exists, `value` is `null` with an `invalidReason`
  (`MISSING_CLASSICAL_REFERENCE`, `MISSING_QUANTUM_OBJECTIVE`,
  `OBJECTIVE_NOT_POSITIVE`, `QUANTUM_OBJECTIVE_NEGATIVE`). The migration 007
  snapshot is returned verbatim — it is never recomputed over a stored row.
- `reproducibility`: the seed persisted with the result (migration 007) — the
  actual `seedFrom(job.id, forecastReference, candidateCount)` value passed to the
  QAOA driver (recomputed only for pre-007 rows), plus QAOA layers/shots and
  backend; variational angles are deliberately absent (the executor does not
  expose them).
- `quantumAdvantageClaimed: false` and a disclaimer; the frontend explains how to
  read the results.

`POST /api/optimization/:id/benchmark` (operator) is the idempotent
execute-or-retrieve entry point: the classical reference is computed at pipeline
run time and its measurements are write-once, so POST returns the stored document
when the job produced a result, and `409 JOB_NOT_COMPLETE` when it did not.
`GET /api/optimization/benchmarks` (viewer, ownership-scoped) is a filterable
ledger (`problem_type`, `algorithm`, `execution_mode`, `from`/`to` on the job's
creation date), newest first.

### Final result API (integrity-audited)

`GET /api/optimization/:id` returns the job summary plus the audited `result`
document; `GET /api/optimization/:id/result` returns that document on its own;
`GET /api/optimization/:id/export` wraps it in a structured export. All three are
`viewer` routes, ownership-scoped (a foreign job is `404 JOB_NOT_FOUND`, never a
`403` leak), and require a persisted result (`404 RESULT_NOT_FOUND` otherwise).

The **database / optimization service is the source of truth**: the API never
recalculates a result from client-supplied values. Before a result is served it
is re-derived from stored measurements and the deterministic inputs the pipeline
consumed (`src/lib/optimization/result-validation.ts`):

| Check | What it proves |
| --- | --- |
| `result_status` | The job completed and the recorded `valid`/`invalid` verdict is well-formed and consistent (`pending_validation` has no verdict, so it can never be attested). |
| `candidate_source` | The candidate set is reproducible from the stored reference (fails closed if not). |
| `bitstring_maps_to_variables` | The bitstring is well-formed and one-to-one with the known variables. |
| `selected_candidates_exist` | Every selected location id exists and matches the decoded bitstring. |
| `constraints_satisfied` | Re-validating the decoded solution finds no violation AND the row does not hide one. |
| `objective_consistent` | The stored objective matches the recomputed objective (tolerance `1e-3`). |

A failed audit **never deletes or hides** the record — it is preserved for
debugging/research — but `recommendation.eligible` is `false` with a `reason`,
so an invalid result is never exposed as an operational recommendation. The
document also carries `quantumComparison`, the direction-aware
`approximationRatio` and the exact `experiment` metadata (problem, mode/backend,
fallback, references, reproducibility seed) — all restated, never invented.
Sensitive result actions (`result_viewed`, `result_exported`) are appended to the
write-once `optimization_job_audit` trail, and no quantum speedup is ever claimed
(`quantumAdvantageClaimed: false`).

The normalized `optimization_results` row (migration 008) is the persisted
contract behind the read model: `validation_status` is `valid` | `invalid` |
`pending_validation` — so an **invalid result is never conflated with a validated
one** — with `validation_timestamp`, `validation_details` (the verdict summary +
violations) and `explanation_metadata` (objective breakdown + coverage). Location
IDs/references only are stored; the GIS module stays the owner of spatial data.

### Error codes

`VALIDATION_ERROR` (422), `UNAUTHORIZED` (401), `FORBIDDEN` (403),
`AI_SERVICE_UNAVAILABLE` (503), `FORECAST_NOT_FOUND` (404),
`MODEL_NOT_FOUND` (404), `RATE_LIMITED` (429), `INTERNAL_ERROR` (500),
plus the optimization codes: `JOB_NOT_FOUND` (404), `RESULT_NOT_FOUND` (404),
`DELETE_PROTECTED` (403), `JOB_NOT_COMPLETE` (409), `NO_CANDIDATES` (422),
`INVALID_OBJECTIVE_WEIGHTS` (422), `INFEASIBLE_BUDGET` (422),
`UNSUPPORTED_PROBLEM_TYPE` (422), `QUBO_GENERATION_FAILED` (503),
`QAOA_EXECUTION_FAILED` (503), `QUANTUM_UNAVAILABLE` (503),
`DECODING_FAILED` (500), `EXECUTION_TIMEOUT` (500).

## Security model

- **Authentication** — `authenticate` middleware verifies JWT Bearer tokens;
  skips enforcement only when `AUTH_ENABLED=false` is set explicitly for local
  demos.
- **RBAC** — `authorize(role)` ranks `viewer < operator < admin`. The
  optimization handoff and `POST /api/optimization/run` require at least
  `operator`. Optimization job reads require `viewer` and are additionally
  ownership-scoped (owner or admin only). Deleting a **completed** research
  result requires `admin` (plus an auditable reason); only soft deletes are
  ever performed.
- **Rate limiting** — `express-rate-limit` guards all `/api` traffic, a
  stricter limiter guards `/api/auth/login`, and `optimizationRunLimiter`
  (window × `OPTIMIZATION_RUN_LIMIT_MAX`, default 10) guards the expensive
  `POST /api/optimization/run`.
- **Input validation** — Zod schemas on params/query/body. Invalid input is
  rejected with 422 (`VALIDATION_ERROR`); values are never silently coerced.
  Forecast ids must match `FC-YYYYMMDD-NNN`; probabilities must be finite and
  within `[0, 1]`; `page`/`limit` ranges are enforced.
- **Secrets** — `JWT_SECRET`, `DATABASE_URL`, and demo passwords live only in
  server-side configuration. Nothing is shipped to the browser; there are no
  API keys in the React bundle.

## Integration contract (Navya's seam)

This gateway depends only on the **payload shapes** of the FastAPI service
(`src/types/contract.ts`), reached through the single
`ForecastClient` interface (`src/clients/ai-service.client.ts`). Navya can
swap XGBoost → LSTM → GRU in `../ai-service` — or point `AI_SERVICE_URL` at a
different deployment — without touching this module or the frontend.

The FastAPI service persists nothing; this gateway stores the synced forecast
and the model registry in PostgreSQL (`src/repositories/postgres/`). When the
database is unreachable, `DATABASE_MODE=memory` (or the automatic fallback)
keeps the API testable with in-memory repositories.

## Tests

```sh
npm test                # all tests (node:test + tsx + supertest)
npm run test:unit       # unit: auth, envelope, schemas, sync, optimization, status
npm run test:integration # integration: full HTTP flow via supertest + fake AI client
npm run lint            # oxlint
npm run build           # tsc typecheck + emit
```

Tests use a controllable `FakeForecastClient`, a `FakeQuantumServiceClient`, and
in-memory repositories, so no live Python service, database, or network is
required. Coverage includes successful forecast retrieval, invalid forecasts,
missing models, AI service unavailability, stale data, authorization failures,
pagination, the optimization handoff, and the full optimization orchestration
surface: the 10 documented pipeline scenarios (weight/budget validation, no
candidates, QUBO/QAOA/hardware fallbacks, decoding failure, constraint
violation, benchmark persistence), job summaries, subresource reads, ownership
scoping, and route-level auth/RBAC. Persistence tests cover the 004 schema
(results/audit/artifact tables, FK and delete-protection trigger, down/up
round-trip) as well as the API-level normalized result read, the
`DELETE_PROTECTED` gate, and the audited soft-delete trail. The
`../quantum-service` contract tests run against that FastAPI app directly
(needs its own `pip install`).

## Source layout

```
src/
├── app.ts                    # Express app wiring (routes, security, errors)
├── container.ts              # dependency container (postgres|memory repos)
├── config.ts                 # zod-validated env config (server-side only)
├── envelope.ts               # shared success/error envelope + error codes
├── clients/ai-service.client.ts  # the ONLY coupling to the FastAPI service
├── clients/quantum-service.client.ts  # the ONLY coupling to quantum-service
├── middleware/               # authenticate, authorize, validate, rate-limit, schemas, errors
├── repositories/             # persistence seam: memory/ + postgres/ impls
├── routes/                   # auth, ai, optimization routers
├── services/                 # analytics, forecast-sync, predictions, models-comparison, models-registry, status, optimization, optimization-orchestrator, gis (candidate/constraint sources), auth
├── lib/optimization/         # qubo.ts (QUBO build + greedy decode, mirrored by ../quantum-service)
├── types/                    # contract.ts (FastAPI payloads) + domain.ts (frontend contract) + optimization.ts
└── utils/errors.ts           # EnvelopeError helper
```

## Configuration (`backend/.env`)

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `3000` | HTTP port (Vite proxies `/api` here). |
| `DATABASE_MODE` | `postgres` | `postgres` or `memory`. |
| `DATABASE_URL` | `postgresql://qflare:qflare@localhost:5432/qflare` | Postgres connection string. |
| `AUTH_ENABLED` | `true` | `false` only for no-auth local demos. |
| `JWT_SECRET` | dev default | Min 16 chars; change in production. |
| `JWT_EXPIRES_IN` | `8h` | Token lifetime. |
| `AUTH_USERS` | demo users | JSON map of `{ "user": { "password", "role" } }`. |
| `AI_SERVICE_URL` | `http://localhost:8000` | FastAPI forecasting service. |
| `AI_REQUEST_TIMEOUT_MS` | `5000` | Timeout for AI service requests. |
| `FRESHNESS_STALE_MS` | `90000` | Forecasts older than this are reported stale/degraded. |
| `QUANTUM_SERVICE_URL` | `http://localhost:8100` | QUBO/QAOA FastAPI service. |
| `QUANTUM_REQUEST_TIMEOUT_MS` | `10000` | Timeout for quantum-service requests. |
| `OPTIMIZATION_FALLBACK_POLICY` | `retry_simulator` | Executor-failure policy: `retry_simulator` · `classical_only` · `error`. |
| `OPTIMIZATION_EXECUTION_TIMEOUT_MS` | `120000` | Wall-clock cap on one optimization job. |
| `OPTIMIZATION_EXHAUSTIVE_LIMIT` | `18` | Candidate cap for the exhaustive classical reference solver. |
| `OPTIMIZATION_QUBO_INLINE_LIMIT` | `12` | QUBOs with at most this many variables are persisted inline; larger matrices go to `optimization_qubo_artifacts` by reference. |
| `OPTIMIZATION_RUN_LIMIT_MAX` | `10` | Per-window cap on `POST /api/optimization/run`. |
| `MODEL_SELECTION_METRIC` | `r2` | Primary metric for `POST /api/ai/models/compare` policy (`mae`, `rmse`, `r2`, `nse`, `inferenceTime`). |
| `RATE_LIMIT_WINDOW_MS` | `60000` | Rate-limit window. |
| `RATE_LIMIT_MAX` | `120` | Max requests per window per IP. |

## Related

- [`../ai-service/README.md`](../ai-service/README.md) — FastAPI forecasting contract (Navya's engine seam)
- [`../frontend/README.md`](../frontend/README.md) — React command center that consumes this API