# System Architecture

**Owner:** Navya
**Diagram source:** `system-architecture.mmd`
**Status legend:** see [`README.md`](README.md)

---

## 1. Purpose

This document describes the conceptual end-to-end architecture of the Q-FLARE flood
forecasting platform, and states — for every stage — who owns it and whether it actually
exists. It is written so that a reader who has never seen the repository can tell, without
ambiguity, which parts are real.

The central honesty constraint of this document: **the dataset does not exist.** There is no
approved hydrological dataset in this repository. Every numeric result produced by this work
is therefore synthetic and is labelled as such wherever it appears.

---

## 2. Pipeline

### 2.1 Data Sources

| Source | Status | Notes |
|---|---|---|
| IoT gauge telemetry | `[TEAM IMPLEMENTATION]` | Team-owned ingestion. Not wired to Navya's engine. |
| GIS river-reach geometry | `[TEAM IMPLEMENTATION]` | Team-owned. |
| **Historical hydrological record** | `[NOT CURRENTLY AVAILABLE]` | **Blocking.** No real dataset, licence, schema, sampling regime, or station inventory has been supplied. See `../ASSUMPTIONS_AND_LIMITATIONS.md`. |

Navya's engine reads a CSV-shaped tabular input. A synthetic sample of 2,160 rows is
committed at `ai-service/app/engines/hydro/data/synthetic_hydrology_sample.csv` purely so the
pipeline is executable and testable. It carries a mandatory disclaimer and is checksummed so
it cannot be mistaken for an observation record.

### 2.2 Data Validation and Cleaning — `[MY IMPLEMENTATION]`

Implemented in `ai-service/app/engines/hydro/preprocessing.py` and `config.py`:

- Schema and dtype checking against a declared expected-column contract.
- Range and plausibility checks.
- Explicit missing-value accounting rather than silent imputation.
- **Imputer and scaler are fitted on the training split only**, then applied to validation
  and test. This is enforced in code, not by convention.

### 2.3 Feature Engineering — `[MY IMPLEMENTATION]`

Implemented in `ai-service/app/engines/hydro/features.py`.

Every feature is **strictly causal**: a feature computed at time *t* may only use information
available at or before *t*. Lagged rainfall, rolling rainfall aggregates, antecedent level,
and time-of-day / seasonal encodings are produced with an explicit lag so that no future
value can leak backwards across the split boundary.

The realized run produced **23 features**. That count is a property of the synthetic
generator's configuration, not a finding about any real basin.

### 2.4 Forecasting Models — `[MY IMPLEMENTATION]` (partly)

| Model | Status |
|---|---|
| Ridge regression baseline | `[MY IMPLEMENTATION]` — executable, in the registry |
| XGBoost | `[MY IMPLEMENTATION]` — optional dependency; skipped when the library is absent, and the skip is reported rather than hidden |
| LSTM | `[NOT CURRENTLY AVAILABLE]` — **future work, not implemented** |
| GRU | `[NOT CURRENTLY AVAILABLE]` — **future work, not implemented** |
| Quantum ML | `[NOT CURRENTLY AVAILABLE]` — **research only, not implemented** |

The registry contains only models that can actually execute. LSTM, GRU and QML appear in
`models.py` as explicitly-labelled future entries so that the research in
`01_Flood_Forecasting/Research/` has a documented landing point. **No LSTM, GRU or QML model
has been trained, and no such performance is claimed anywhere.**

### 2.5 Model Selection and Evaluation — `[MY IMPLEMENTATION]`

The discipline enforced by the implementation, and asserted by its tests:

- **Chronological split only.** No shuffle, no random split, no random seed. A shuffled split
  on hydrological time series leaks the future into the past.
- **Model selection uses the validation split only.**
- **The test split is scored exactly once**, by the already-selected model, and never
  influences ranking.
- Metrics are **computed from actual predictions and actual observations**. There are no
  hard-coded or placeholder metric values anywhere in the implementation.
- Every reported metric carries its split, and a metric that is not from the held-out test
  split is refused presentation as a result.

Measured on the **synthetic** 8,760-row dataset, ridge was selected on validation, and the
held-out test produced MAE 0.2779, RMSE 0.3645, R² 0.6359. These are
**synthetic/demo evaluation only — not a production or research result.** They say nothing
about performance on any real river.

### 2.6 Flood Risk Assessment — `[MY IMPLEMENTATION]` (partly)

- Risk banding (LOW / MEDIUM / HIGH / CRITICAL) is implemented and configurable.
- Thresholds are **never hard-coded**. The team's `ReferenceEngine` placeholder of `8.0` is
  deliberately not reused.
- **Official flood stage values are `[NOT CURRENTLY AVAILABLE]`.** No government or official
  threshold source has been supplied, so every threshold in this work is marked
  `pending` and rendered as pending in the UI. A threshold is never displayed as a bare
  approved number.
- Residual sigma is carried through as an uncertainty signal.

### 2.7 Forecast / Decision Handoff — `[MY IMPLEMENTATION]` + `[PROPOSED INTEGRATION]`

Navya owns the forecast contract in both namespaces:

- Backend: `backend/src/navya/forecasting/`
- Frontend: `frontend/src/navya/forecasting/`

The team's existing optimization input accepts **`forecast_id` only**. The running contract
has no slot for provenance, metric split, threshold policy, or residual sigma.

> **Existing optimization currently requires forecast_id. Additional forecast-derived risk
> fields require team-owner integration.**

Navya has therefore shipped a Navya-side contract and adapter
(`toExistingOptimizationPayload`, `toProposedForecastHandoff`) that maps onto the team's
schema without modifying it, plus an explicit list of the fields that cannot be carried
until a team owner extends the schema. See [`../API_Integration/`](../API_Integration/).

### 2.8 Sensor Optimization — `[TEAM IMPLEMENTATION]`

Team-owned. Navya supplies forecast-derived risk information and does not modify the
optimization or QUBO logic.

### 2.9 Quantum / Optimization Layer — `[TEAM IMPLEMENTATION]`

Team-owned.

**This work makes no claim of quantum advantage, quantum speedup, or superior performance.**
No quantum result of any kind has been produced, measured, or estimated by Navya. Any future
comparison of classical against quantum solving is a team-owned activity requiring real
measurement on real workloads.

### 2.10 Disaster Response / Dashboard — `[TEAM IMPLEMENTATION]` + `[MY IMPLEMENTATION]`

- The team owns the application shell, routing, and page composition.
- Navya owns `frontend/src/navya/forecasting/` — 17 files, 109 tests, type-checked,
  lint-clean, and building successfully.
- **The Navya dashboard is NOT mounted into any team route.** Its components are consequently
  tree-shaken out of the production bundle. It is verified in isolation, not running in the
  application.

---

## 3. Ownership boundary

| Namespace | Owner | Navya may modify |
|---|---|---|
| `ai-service/app/engines/hydro/**` | Navya | Yes |
| `ai-service/tests/**` (Navya's own test files) | Navya | Yes |
| `backend/src/navya/forecasting/**` | Navya | Yes |
| `backend/tests/navya/**` | Navya | Yes |
| `frontend/src/navya/forecasting/**` | Navya | Yes |
| `01_Flood_Forecasting/**` | Navya | Yes |
| `02_Architecture/**` | Navya | Yes |
| `database/migrations/010_*` | Navya (additive) | Yes |
| Everything else in `ai-service`, `backend`, `frontend`, `database` | Team | **No** |

Where integration requires a team-owned change, Navya records the requirement instead of
making it. See [`../INTEGRATION_MATRIX.md`](../INTEGRATION_MATRIX.md).

---

## 4. Verification status

| Item | Result | Where |
|---|---|---|
| Navya Python suite | 412 passed, 0 failed | overlay with the team seam present |
| Navya backend TS suite | 129 passed, 0 failed | overlay with the team seam present |
| Team backend TS suite (no Navya files) | 315 tests, 0 failed | regression baseline |
| Team backend TS suite (with Navya files) | 444 tests, 0 failed | no regression introduced |
| Navya frontend suite | 109 passed | **temporary harness** — see note |
| Full frontend suite | 230 passed | **temporary harness** — see note |
| TypeScript | clean, including forced clean build | **temporary harness** |
| Vite production build | exit 0 | **temporary harness** |
| Oxlint | 0 warnings, 0 errors | **temporary harness** |
| Migration 010 | 19/19 checks against PostgreSQL 17.10 | local database |

**Harness note:** the frontend checks above were executed in a temporary directory built from
the team branch, because Navya's working tree does not contain the team's frontend manifests
or dependencies. They are **not** real-worktree results. See
`../ASSUMPTIONS_AND_LIMITATIONS.md`.
