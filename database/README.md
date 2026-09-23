# database

Persistence layer for Q-FLARE. Canonical, reversible schema lives in
`database/migrations/`; the Node backend applies the `*.up.sql` files at boot
(`ensureSchema` in `backend/src/repositories/postgres/pool.ts`), so the gateway
bootstraps a fresh database automatically.

## Schema & ownership boundary

| Table | Owner | Purpose |
| --- | --- | --- |
| `forecasts` | Backend gateway | AI analytics forecast runs (`forecast_id`, probability, risk, water level, `model_id`/`model_version`, timestamp). **Shared forecast storage — referenced, never duplicated.** `optimization_references.forecast_id` FKs to it. |
| `models` | Backend gateway | Legacy flat model registry (kept for compatibility with the running gateway). |
| `optimization_references` | Backend gateway | Quantum handoff references; `forecast_id` FK → `forecasts`. |
| `model_versions` | **Nanda** | Formal model registry: `model_name`, `algorithm`, `version`, dataset/artifact provenance, `status` (`active`/`retired`/`development`), training/deploy timestamps. |
| `model_metrics` | **Nanda** | Per-version evaluation scores (`rmse`, `mae`, `nse`, `r2`, `accuracy`, `precision`, `recall`, `f1`), latencies, `evaluation_dataset` provenance. FK → `model_versions(id)`. |
| `optimization_jobs` | **Nanda** | Operational optimization record (003) plus 004 exact-configuration scalars (`forecast_reference`, `candidate_reference`, `input_reference`, `variables_count`, `constraints`, `objective_configuration`, `error_message`, `qubo_storage`, `qubo_artifact_reference`, soft-delete columns). |
| `optimization_results` | **Nanda** | One normalized row per completed job — the **source of truth for a final result**. FK `fk_optimization_results_job` → `optimization_jobs(id)`. Stores `bitstring`, `selected_locations` (**location IDs/references only** — the GIS module owns authoritative spatial data), `objective_value`, `constraint_violations`, `validation_status` (`valid`\|`invalid`\|`pending_validation`, 008), `runtime_ms`, `classical_objective`, `quantum_objective`, `approximation_quality`, plus 008 `validation_timestamp`/`validation_details`/`explanation_metadata`. Indexes on `optimization_job_id`, `validation_status`, `created_at`. |
| `optimization_job_audit` | **Nanda** | Write-once delete-protection trail (`action`, `actor`, `reason`); FK → `optimization_jobs(id)`. |
| `optimization_qubo_artifacts` | **Nanda** | QUBO matrices too large to inline, stored by reference (plain JSON, never Qiskit objects); FK → `optimization_jobs(id)`. |
| `optimization_qubo_metadata` | **Nanda** | QUBO metadata **audit record** (005), one row per job (`qubo_id` = `<jobId>-Q1`). Small problems inline the plain-JSON matrix/linear/quadratic/penalty/expression columns; large problems store reference + sha-256 checksum + dimensions + location + summary metadata only — matrix cells are never embedded. Indexes on `optimization_job_id` and `created_at`. FK → `optimization_jobs(id)`. |
| `quantum_jobs` | **Nanda** | Quantum job persistence **operational record** (006), one row per **real** submission the backend drives through the quantum FastAPI service (`id` is the service's own job id). Stores what was asked for (`algorithm`, `backend`, `execution_mode`, `shots`, `layers`), the resolved `qubits`, the lifecycle `status`, audit timestamps (`submitted_at`/`started_at`/`completed_at`) and `error_code`/`error_message`. Indexes on `optimization_job_id`, `status` and `created_at`. FK → `optimization_jobs(id)` ON DELETE CASCADE. |
| `quantum_results` | **Nanda** | One normalized row per **completed** quantum job (006). `id` must equal `<quantum_job_id>-R1` (one row per job). Stores the decoded `bitstring`, plain-JSON `counts`, `objective_value`, `runtime_ms` and an optional artifact `raw_metadata_reference` — raw circuits are never embedded. FK → `quantum_jobs(id)` ON DELETE CASCADE. |

Navya's forecasting/training pipeline owns the model training artifacts and any
pipeline-internal tables. This module *never* recreates them: lineage is traced
through stable references only — `dataset_reference` /
`model_artifact_reference` on `model_versions`, and `forecast_id` on
`optimization_references`. Switching an engine (XGBoost/LSTM/GRU) behind
`ai-service` changes none of these tables.

## Key rules enforced by the schema

- `model_versions`: `model_name` + `version` is unique; at most **one**
  `active` version per model; no blank identifiers; `training_completed_at`
  ≥ `training_started_at`, `deployed_at` ≥ `training_completed_at`;
  `created_at`/`updated_at` auto-maintained.
- `model_metrics`: must FK to an existing `model_versions.id`; every score is
  bounded to its physical range; a row needs **at least one** score; timings
  are non-negative.
- No fake metrics: metric columns are nullable, scores are range-checked, and
  seeded data is `development`-marked with `dev://` provenance. The registry
  seed carries **no** metric rows; the comparison seed adds synthetic
  regression scores under a separate `dev://comparison/` namespace so nothing
  seeded can be presented as real research results (see `seeds/`).
- `optimization_results`: must FK to a real job; `id` must equal
  `<optimization_job_id>-R1` (one row per job by primary key); `validation_status`
  is `valid|invalid|pending_validation` — an **invalid result stays distinguishable
  from a validated one** (and a `pending_validation` row has no verdict yet, so it
  is never a recommendation); `approximation_quality` stays in `[0, 1]`;
  `validation_details`/`explanation_metadata` are JSON objects (or absent), and a
  recorded verdict detail must carry `validation_timestamp`. Location IDs are
  stored by reference only — GIS geometry/name/risk is never duplicated.
- `optimization_qubo_metadata`: must FK to a real job; `qubo_id` must equal
  `<optimization_job_id>-Q1` (one row per job by primary key); `storage_mode` is
  `inline|artifact`; an **inline** row must carry the complete plain-JSON
  representation (matrix + linear + quadratic + penalty + expression), an
  **artifact** row must carry `artifact_reference` + `checksum` +
  `matrix_dimensions` + `storage_location` + `metadata` — never the matrix
  cells. The table never grows a cell-per-row relational dump and never stores
  raw Python/Qiskit objects; the sha-256 checksum lets a stored QUBO be verified
  against the artifact store, so the experiment is always reproducible/auditable.
- `quantum_jobs`: must FK to a real `optimization_job`; `execution_mode` is
  `simulator|aer|ibm_hardware`, `status` is `queued|running|completed|failed|cancelled`,
  and `submitted_at ≤ started_at ≤ completed_at` (timestamps ordered). The
  simulator/hardware distinction is preserved **per row** — a fallback ladder
  records one honest failed row (aer/ibm_hardware) plus one completed row
  (simulator), never a mislabelled single row.
- `quantum_results`: must FK to a real `quantum_job`; `id` must equal
  `<quantum_job_id>-R1` (one row per job by primary key).
- Quantum persistence never stores credentials or raw circuit objects: only
  configuration scalars, plain-JSON counts and artifact references. No backfill
  is performed for jobs created before migration 006 — earlier submission ids
  were never persisted anywhere, so any reconstructed row would fabricate data.
- **Delete protection:** completed research results are **write-once**. The
  `qflare_guard_optimization_delete` trigger rejects hard `DELETE`s of a
  completed job or its result row (SQLSTATE `P0001`) unless the transactional
  escape hatch `app.allow_optimization_delete = 'true'` is set (administrative
  cleanup only — the API soft-deletes with an audit trail instead).

## Migrations

Pair of reversible scripts per step, applied in filename order.

| Step | Up | Down |
| --- | --- | --- |
| `001_core_tables` | `forecasts`, `models`, `optimization_references` (+ indexes) | drops them (FK order) |
| `002_model_versioning` | `model_versions`, `model_metrics` (+ indexes, check/unique/FK constraints, `updated_at` trigger) | drops them |
| `003_optimization_jobs` | `optimization_jobs` operational record (+ status/owner/created indexes) | drops it |
| `004_optimization_persistence` | `optimization_results`, `optimization_job_audit`, `optimization_qubo_artifacts`, the 004 job scalars, required indexes, the delete-protection trigger, and an idempotent backfill | drops triggers/function/tables/indexes/columns (003 base table untouched) |
| `005_optimization_qubo_metadata` | `optimization_qubo_metadata` QUBO audit record (inline full representation for small problems; reference + sha-256 checksum + dimensions + location + metadata only for large ones) + required indexes | drops the table and its indexes |
| `006_quantum_job_persistence` | `quantum_jobs` (per-real-submission lifecycle: algorithm/backend/execution-mode/qubits/shots/layers/status + ordered timestamps + error pair, FK → `optimization_jobs` ON DELETE CASCADE) and `quantum_results` (`<jobId>-R1` id rule, plain-JSON counts + objective + runtime + artifact ref only, FK → `quantum_jobs` ON DELETE CASCADE) + required indexes | drops both tables and their indexes |
| `007_optimization_benchmark_reference` | classical benchmark reference snapshot on `optimization_results` (`classical_solver`, `classical_runtime_ms`, `approximation_ratio`, `approximation_basis`, `approximation_invalid_reason`, `random_seed`) + checks + `created_at` index | drops those columns/checks/index |
| `008_optimization_result_validation` | final-result validation contract on `optimization_results`: `validation_timestamp`, `validation_details`, `explanation_metadata`, the third `pending_validation` state, JSONB/verdict-pairing checks, and idempotent re-assertion of the `optimization_job_id`/`validation_status`/`created_at` indexes | collapses `pending_validation` to `invalid`, restores the two-state check, drops the 008 columns/checks |

All migrations are idempotent (`IF NOT EXISTS` / `CREATE OR REPLACE`) because
`ensureSchema` re-applies every `*.up.sql` at each boot.

Apply manually with `psql`:

```sh
psql "$DATABASE_URL" -f database/migrations/002_model_versioning.up.sql   # up
psql "$DATABASE_URL" -f database/migrations/002_model_versioning.down.sql # down (reversible)
```

Or let the backend apply all `.up.sql` at boot (`npm run dev` in `backend/`).
`applyMigrationFiles('down')` is exported for the migration runner.

## Seeds

`seeds/dev_model_registry.sql` is **development-only** and clearly marked as
such in its header. It inserts `development`-status `model_versions` rows with
`dev://` dataset/artifact references and **no `model_metrics`**, so seeded data
can never be presented as real research results. Never apply it to production.

`seeds/dev_model_comparison.sql` is the companion demo seed for the Model
Comparison page. It is idempotent: it first prunes any rows whose
`dataset_reference` starts with `dev://comparison/`, then inserts ~29 scored
versions (8 model families × 3–4 versions, one `active` per model) with
synthetic `model_metrics` (MAE/RMSE/R²/NSE only, classification columns NULL)
under a dedicated `dev://comparison/` namespace. Apply it only to a dev
database (`psql "$DATABASE_URL" -f database/seeds/dev_model_comparison.sql`).

## Tests

DB integration tests live in `backend/tests/integration/database.test.ts`
(node:test + `pg`) and cover:

- FK / missing-model-version rejection (`23503`)
- unique model/version + single-active-per-model constraints (`23505`)
- invalid metrics / blank identifiers / timestamp-consistency checks (`23514`)
- multi-version support, metric provenance, `created_at`/`updated_at` upkeep
- query performance on populated tables + required index presence
- migration reversibility (002 down/up round-trip) and dev-seed policy (both
  seeds are dev-marked; the comparison seed inserts 29 scored versions, keeps
  one `active` per model, and adds no classification metrics)
- `004` persistence: table/column/index presence, result→job FK (`23503`),
  one-row-per-job via the primary key (`23505`), `validation_status` /
  `approximation_quality` checks (`23514`), write-once delete protection
  (`P0001`) plus the escape hatch, non-completed jobs removable, audit/artifact
  cascade, and a `004` down/up round-trip
- `005` QUBO metadata: table/column/index presence, metadata→job FK (`23503`),
  inline/artifact representation completeness checks (`23514`), the id-format +
  one-row-per-job primary key (`23505`), the repository upsert (`ON CONFLICT
  qubo_id`), job cascade, and a `005` down/up round-trip (plus unit tests for
  checksum determinism and the derive/storage shapes)
- `006` quantum persistence (`backend/tests/integration/quantum-persistence.test.ts`):
  table/column/index presence, job→optimization-job and result→job FKs (`23503`),
  execution-mode/status/timestamp-order checks + the `<jobId>-R1` id rule
  (`23514`), one-result-per-job primary key (`23505`), a completed round-trip
  (objective + plain-JSON counts), both cascades (result with its quantum job,
  jobs with their optimization job), and a `006` down/up round-trip

Tests run against the live `DATABASE_URL` and **skip gracefully when
PostgreSQL is unreachable**; every write happens in a rolled-back transaction,
so the target database is never mutated.

## Related

- [`../backend/README.md`](../backend/README.md) — gateway that applies migrations at boot
- [`../README.md`](../README.md) — repo layout & module ownership