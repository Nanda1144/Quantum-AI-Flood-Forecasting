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

## Migrations

Pair of reversible scripts per step, applied in filename order.

| Step | Up | Down |
| --- | --- | --- |
| `001_core_tables` | `forecasts`, `models`, `optimization_references` (+ indexes) | drops them (FK order) |
| `002_model_versioning` | `model_versions`, `model_metrics` (+ indexes, check/unique/FK constraints, `updated_at` trigger) | drops them |

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

Tests run against the live `DATABASE_URL` and **skip gracefully when
PostgreSQL is unreachable**; every write happens in a rolled-back transaction,
so the target database is never mutated.

## Related

- [`../backend/README.md`](../backend/README.md) — gateway that applies migrations at boot
- [`../README.md`](../README.md) — repo layout & module ownership