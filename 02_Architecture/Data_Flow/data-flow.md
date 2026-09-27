# Data Flow

**Owner:** Navya
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

### Stage 2 — Validation `[MY IMPLEMENTATION]`

`ai-service/app/engines/hydro/preprocessing.py`

- Column presence and dtype conformance against the declared contract
- Range and plausibility checks
- Explicit missing-value accounting — missingness is reported, never silently absorbed
- Timestamps parsed and ordered; monotonicity enforced

A validation failure **stops the run**. It does not fall back to a partial dataset, because a
partial dataset presented as a complete one is a silent lie.

### Stage 3 — Preprocessing `[MY IMPLEMENTATION]`

The three rules that matter, each enforced in code and asserted by tests:

1. **Chronological split only.** Ordered by time, then cut. No shuffle, no random split, no
   random seed. Shuffling a hydrological series leaks the future into the past and inflates
   every metric.
2. **Imputer and scaler are fitted on the training split only**, then applied to validation
   and test. Fitting on the full series is leakage through the scaler.
3. **Target is never an input feature.** The target is excluded from the feature matrix by
   construction, not by convention.

### Stage 4 — Feature engineering `[MY IMPLEMENTATION]`

`ai-service/app/engines/hydro/features.py`

Every feature is **strictly causal**: a feature at time *t* uses only information available at
or before *t*. Rainfall lags, rolling rainfall aggregates, antecedent level, and cyclical
time encodings are all produced with an explicit lag.

The realized synthetic run produced **23 features**. This is a property of the synthetic
generator's configuration — it is not a statement about any real basin.

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

`database/migrations/010_navya_forecast_provenance.{up,down}.sql`

- **Additive only** — no team column is altered, renamed, or dropped
- **Reversible** — the down migration restores the team schema byte-identically
- Verified 19/19 against local PostgreSQL 17.10, including idempotent re-run and full
  round-trip

---

## 3. Data provenance carried end to end

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

**Station-to-GIS candidate mapping remains `[NOT CURRENTLY AVAILABLE]`.** No authoritative
station or reach identifier list, and no station-to-GIS crosswalk, has been supplied.
`backend/src/navya/forecasting/candidate-risk.ts` models the mapping as an explicit,
validatable specification with declared blockers — it does not invent station identifiers or
coordinates, and it does not fabricate the provenance of `CandidateLocation.floodRisk`.
