# Data Flow

**Owner:** forecasting module
**Diagram source:** `data-flow.mmd`
**Status legend:** see [`README.md`](README.md)

---

## 1. Summary

Ten stages take a row of observations and produce a forecast with attached provenance and a
risk band, then hand a `forecast_id` to team-owned optimization.

> ## The governing limitation
>
> **Stage 1 has no real input.** No approved hydrological dataset, licence, schema, sampling
> regime, or station inventory exists in this repository. Every stage below has been executed
> only against a committed **synthetic** sample that carries a mandatory disclaimer.
>
> The pipeline is real and tested. The data is not. No output described in this document
> describes any real river, and no metric in this document is a real-world result.

---

## 2. Stage-by-stage

### Stage 1 — Raw / historical data `[NOT CURRENTLY AVAILABLE]`

**Required and absent:**

- A real historical hydrological record
- Source and licence
- Column schema and types
- Provenance and custody
- Sampling interval and timezone
- Missingness characterisation
- Quality-control rules
- Station identifiers and locations

**What exists instead:** `ai-service/app/engines/hydro/data/synthetic_hydrology_sample.csv`
— 2,160 rows, deterministic generator, SHA-256
`56f4b7c5b4122b5d9b61db256f8d7afcb7e03d4a1cf9e942c013818386e29ac6`. It is committed so the
pipeline is executable and so tests have a stable input. It is **synthetic/demo data** and
must never be presented as hydrological observation data.

**Phase 1 — the record and coverage schemas `[MY IMPLEMENTATION]`**

The absence above is real but was *invisible*: a wide frame silently absorbs a gauge network
that reports a level but no discharge, and a catchment with no rainfall record. Phase 1 makes
each absence representable and queryable instead of implicit.

- `ai-service/app/engines/hydro/domains.py` — one record schema per domain: `weather`,
  `rainfall`, `water_level`, `discharge`, `inflow` (`Observation`), plus `FloodEvent` and
  `RiskScoreRecord`. Timestamps must carry an explicit timezone; units must be declared but
  are deliberately **not** whitelisted or converted; `NaN` is refused; nothing invents a
  station, a datum or a threshold.
- `ai-service/app/engines/hydro/quality.py` — structural validation with stable issue codes.
  **A validator reports; it never repairs.** A duplicate is reported, not collapsed; two
  disagreeing readings of one instant are a conflict to be resolved by the dataset owner, not
  by this repository. No missing value is ever filled.
- `ai-service/app/engines/hydro/datasets.py` — per-domain coverage: `available`, `absent` or
  `unknown`. The default catalog is empty and says so in words. The one descriptor that exists
  describes the committed sample by reading the file's own bytes, and reports
  `station_reference: None` because that file has no station column.
- `database/migrations/011_hydro_hydro_observation_domains.{up,down}.sql` — additive,
  idempotent, reversible storage for the same schemas. **Not yet executed against a live
  PostgreSQL instance**; see §4.

Coverage of the committed synthetic sample, as reported by
`datasets.coverage_matrix()`: `water_level`, `inflow` and `rainfall` are **available**;
`weather`, `discharge`, `flood_event` and `risk_score` are **absent**. Nothing in Phase 1
resolves any of those absences, and no flood event register was invented to fill one.

### Stage 2 — Validation `[MY IMPLEMENTATION]`

`ai-service/app/engines/hydro/preprocessing.py`

- Column presence and dtype conformance against the declared contract
- Range and plausibility checks
- Explicit missing-value accounting — missingness is reported, never silently absorbed
- Timestamps parsed and ordered; monotonicity enforced

A validation failure **stops the run**. It does not fall back to a partial dataset, because a
partial dataset presented as a complete one is a silent lie.

### Stage 3 — Preprocessing `[MY IMPLEMENTATION]`

Two paths exist and both are tested; neither replaces the other.

**Phase 2 path — `preprocess_pipeline.py` + `preprocess_temporal.py` + `preprocess_units.py` +
`preprocess_config.py`** (narrow `Observation` records, pure standard library, full report).
This is the auditable contract. It is summarised below and documented in full in
`ai-service/app/engines/hydro/PHASE2_PREPROCESSING.md`.

**Pre-existing path — `preprocessing.py`** (wide `DataFrame`, used by `training.py` and
`engine.py`). Untouched by Phase 2; Phase 2 does not rewrite, replace or deprecate it.

What the Phase 2 path does, in order:

| Step | Behaviour | Default |
| --- | --- | --- |
| Timestamps | Canonical UTC ISO-8601 with a trailing `Z`; the source's original string is preserved in `notes`. No silent timezone assumption. | `require_explicit` |
| Ordering | Total order on `(entity, instant, domain, source, provenance, …)` — byte-identical output for any input order. | always |
| Duplicates | Keyed on domain, entity, canonical instant, quantity **and source**. Reported, nothing removed. | `report` |
| Conflicts | Two readings of one instant that disagree. **Refused** — no policy ever averages, sums or takes a median. | `error` |
| Units | Exact documented factors only. An unrecognised unit becomes `UNDETERMINED` and the value is kept untouched. | `preserve_undetermined` |
| Gaps | Cadence inferred from the smallest positive delta; empty slots made visible on a grid. Gaps stay visible unless a fill is explicitly requested. | `retain` |
| Resampling | **Off.** Nothing establishes what cadence a real gauge network reports. Bins, when enabled, are right-labelled. | `None` |
| Split | Chronological, never random. Validated `train_end < validation_start` and `validation_end < test_start`. | `global` |

Resolving a conflict requires a **citation** (`conflict_policy_source`) naming who
approved it and against what document — choosing between two readings of one gauge
instant is a decision about someone else's data.

A backward-looking fill requires both `allow_leakage_sensitive=True` **and** a
per-operation acknowledgement. `config.is_causal` answers the single audit question:
"can any row in the output depend on a value from after it?"

**Phase 2 performs no feature engineering.** No lags, no rolling or moving-average windows,
no rainfall accumulation, no flood-risk arithmetic. Those belong to stage 4. The only
aggregation Phase 2 can perform is resampling onto a coarser grid, and only with an
explicitly declared frequency and a per-quantity `AggregationRule`.

Every decision is reported. `PreprocessingReport` is JSON-serialisable and deterministic
under input permutation, and separates `errors` / `warnings` / `infos`. Resampling is
accounted as a measured `resampling_delta`, never as rows "removed", and the invariant

```
records_in - records_discarded + resampling_delta + missing.row_delta == records_out
```

is published as `rows_reconciled`. Every finding carries a stable `PREPROCESS_*` code.

The three rules that matter, each enforced in code and asserted by tests:

1. **Chronological split only.** Ordered by time, then cut. No shuffle, no random split, no
   random seed. Shuffling a hydrological series leaks the future into the past and inflates
   every metric.
2. **Imputer and scaler are fitted on the training split only**, then applied to validation
   and test. Fitting on the full series is leakage through the scaler.
3. **Target is never an input feature.** The target is excluded from the feature matrix by
   construction, not by convention.

### Stage 4 — Feature engineering `[MY IMPLEMENTATION]`

`ai-service/app/engines/hydro/feature_registry.py` · `feature_config.py` ·
`feature_temporal.py` · `feature_pipeline.py`
(documented in `ai-service/app/engines/hydro/PHASE3_FEATURE_ENGINEERING.md`)

Stage 3's output — validated, deduplicated, unit-aware, chronologically split records —
becomes a feature dataset whose every column is a function of the past.

Every feature is **strictly causal**: `Feature(T)` depends only on observations at or before
`T`. Accumulation and rolling windows are `(cutoff - window, cutoff]` — open on the left,
closed on the right — so a window of width `w` holds exactly `w / base_interval` readings,
and it agrees with `pandas.Series.rolling(w)` slot for slot. Windows are **never centered and
never reach forward**. Forcings (rainfall, temperature, humidity) are read at `T`; state
quantities (water level, discharge, inflow) are read at `T - 1`, because `T` is what is being
predicted.

Targets are separated structurally from features: `target = value(T + H)`, features use
`<= T`, and each row carries `values`, `targets`, `absent_reasons` and `target_instants` as
distinct fields, so `feature_matrix()` cannot reach a target.

**A feature is either computed or declared unavailable with a recorded reason.** There is no
third category, and nothing is ever imputed: a hole in a series stays a hole, and Phase 3
applies no forward-fill. Warm-up (the series had not started when the window opened) is
reported separately from `missing_source` (the series was running; the reading is absent),
because the first is fixed by collecting more history and the second by fixing a sensor.

A feature is computed only from its own entity's history and only from its own
`location|domain|quantity` measurement key, so a rainfall lag cannot become a water-level
lag. Nine features are declared unbuildable for any input and are never fabricated — six
static ones with no source field anywhere, and three derived ones needing a relationship
nobody has established, including **discharge inferred from a water level**, which would
require a rating curve that does not exist in this repository.

The default registry declares **56 features**. The realized synthetic run built **32 of
them**; the other 24 — `discharge_*`, `temperature_*`, `humidity_*` — have no source in the
committed sample, which carries water level, inflow and rainfall only. This is a property of
the synthetic generator's configuration, not a statement about any real basin.

Every feature carries lineage naming its source, window, statistic and unit; every target
carries lineage recording `available_at_prediction_time = False`. Column order is registry
order and row order is `(entity, instant)`, so the dataset is byte-identical under input
permutation.

An eight-check leakage audit runs on every build, plus `audit_point_in_time`, which rebuilds
the dataset with all post-origin data deleted and reports any feature whose value changed. A
feature that changes has read the future, whatever the window arithmetic says.

**Stage 4 does not train a model.** No model is selected, fitted, tuned or evaluated; no
accuracy metric is reported; no scaler, imputer or encoder is fitted on these rows. That
belongs after the split.

All data at this stage remains **SYNTHETIC/DEMO** and is labelled as such throughout.

### Stage 5 — Model input matrix `[MY IMPLEMENTATION]`

Assembled from the three splits produced in stage 3. Feature ordering is persisted with the
model artifact so that inference cannot silently drift from training.

### Stage 6 — Forecasting `[MY IMPLEMENTATION]`

Ridge regression baseline, plus XGBoost when its optional dependency is installed. When the
dependency is absent the run **reports the skip** rather than quietly substituting another
model or reporting a score for a model that did not run.

### Stage 7 — Forecast output `[MY IMPLEMENTATION]`

Carries: predicted value, forecast timestamp, horizon, model identifier and version, plus a
`flood_probability` and residual sigma. Metrics that accompany a forecast are always
**split-labelled**, so a fit statistic can never be presented as a held-out result.

### Stage 8 — Flood risk `[MY IMPLEMENTATION]`, threshold source `[NOT CURRENTLY AVAILABLE]`

- Bands LOW / MEDIUM / HIGH / CRITICAL, **configurable**, never hard-coded.
- The team's `ReferenceEngine` placeholder of `8.0` is deliberately not reused.
- **No official flood stage values exist.** Every threshold is therefore marked `pending` and
  is never displayed as an approved number.
- Residual sigma is propagated as an uncertainty signal, not converted into a confidence
  interval that was never computed.

### Stage 9 — Optimization handoff `[PROPOSED INTEGRATION]`

> **Existing optimization currently requires forecast_id. Additional forecast-derived risk
> fields require team-owner integration.**

Navya ships the adapter and the contract. The team's schema is not modified. See
[`../API_Integration/`](../API_Integration/).

### Stage 10 — Persistence `[MY IMPLEMENTATION]` (additive only)

`database/migrations/010_hydro_forecast_provenance.{up,down}.sql`

- **Additive only** — no team column is altered, renamed, or dropped
- **Reversible** — the down migration restores the team schema byte-identically
- Verified 19/19 against local PostgreSQL 17.10, including idempotent re-run and full
  round-trip

`database/migrations/011_hydro_hydro_observation_domains.{up,down}.sql` (Phase 1)

- **Additive only** — six forecasting-module-owned tables and one audit view; the team's `forecasts`
  table is not altered, and migrations 001–009 are untouched. The only reference to another
  owner's object is a foreign key into 010's `hydro_forecast_provenance`.
- **Reversible** — the down migration drops children before parents and touches nothing
  outside this migration
- **Seeds nothing.** With an empty database, `hydro_domain_availability` reports
  `present_in_repository = false` for every domain, which is the truth.
- **Static-checked only.** See §3.

---

## 3. Verification status — read this

Migration `010` was **executed** against a local PostgreSQL instance and the result is
recorded above.

Migration `011` has **not been executed**. No PostgreSQL server or `psql` binary was
available in the environment where Phase 1 was implemented. It has been **statically
reviewed** — `ai-service/tests/test_hydro_phase1_migration.py` reads the SQL as text and
asserts its content: additive-only DDL, reversibility, no team table mutated, the NaN *and*
infinity rules on a measurement value, the duplicate-identity index, and that the SQL
vocabularies match the Python ones.

That is a **weaker** claim than 010's and is not to be read as equivalent. A text assertion
cannot prove the SQL parses. **Anyone applying 011 must run it against a real instance, and
that run — not the test suite — is the verification.** Until then, treat 011 as unexecuted.

**Phase 2 adds no migration and does not assume 011 ran.** It is entirely
application-level: it operates on `Observation` records in memory and changes no schema, so
its correctness does not depend on the state of the database. That dependency, if it ever
arises, is for a database owner to resolve rather than for a new migration to paper over.

### Phase 2 verification status

| Claim | How verified |
|---|---|
| 174 Phase 2 tests pass | `python -m pytest tests -q --no-header --tb=short` from `ai-service/` — **771 passed, 1 skipped** (597 passed, 1 skipped before Phase 2) |
| No Phase 1 or `preprocessing.py` regression | `tests/test_hydro_preprocessing.py` and `tests/test_hydro_leakage.py` (68 tests) still pass unmodified |
| Determinism | Report and output records compared byte-for-byte across shuffled inputs |
| Row accounting | `rows_reconciled` asserted for every gap policy, including under resampling |
| Standard-library-only | `tests/test_hydro_preprocess_pipeline.py` asserts no `random` / `numpy` import and no `seed` / `shuffle` keyword over the AST of all four modules |
| End to end on the committed sample | 2160 CSV rows → 6480 `Observation` records → 3 series at 1 h → 4536 / 972 / 972 split, 6486 leakage checks passed |
| No fabricated domain facts | Tests assert no station identifier, threshold, rating curve or basin boundary is asserted anywhere in the phase |

Phase 2 has **not** been run against a real gauge network, because no real
dataset exists in this repository. Every number it produces is from SYNTHETIC/DEMO
data and is labelled as such.

---

## 4. Data provenance carried end to end

| Field | Purpose |
|---|---|
| `datasetReference` | What the data is |
| `datasetType` | `real` / `synthetic` / `unknown` — drives every honesty guard |
| `datasetLicense` | Whether use is even permitted |
| `datasetChecksum` | Identity of the exact bytes evaluated |
| `samplingInterval` | Temporal resolution |
| `stationReference` | Which gauge |
| `forecastHorizonHours` | How far ahead |
| `contractVersion` | Which contract shape |

`datasetType` is the load-bearing field: the UI, the guards, and the storage check all branch
on it. A record whose `datasetType` is `unknown` is **not** treated as real.

Phase 2 preserves this rather than restating it. The synthetic-data disclaimer has exactly one
definition, `provenance.SYNTHETIC_DATA_DISCLAIMER`, whose wording is:

`THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION DATA.`

Every record carries it in a `disclaimer` field kept separate from `notes` — so a stage
appending a provenance note cannot displace it. A dataset of unknown type falls back to
`UNVERIFIED_DATA_DISCLAIMER`: unknown is treated as unverified, never as real. Split
boundaries reuse the existing `provenance.SplitBoundaries` type.

**Station-to-GIS candidate mapping remains `[NOT CURRENTLY AVAILABLE]`.** No authoritative
station or reach identifier list, and no station-to-GIS crosswalk, has been supplied.
`backend/src/features/forecasting/candidate-risk.ts` models the mapping as an explicit,
validatable specification with declared blockers — it does not invent station identifiers or
coordinates, and it does not fabricate the provenance of `CandidateLocation.floodRisk`.
