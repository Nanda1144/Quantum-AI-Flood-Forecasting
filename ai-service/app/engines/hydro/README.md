# Navya's hydrological forecasting pipeline (`app/engines/hydro`)

**Owner:** Navya (ForecastingEngine seam) · **Module:** `ai-service` · **License:** Apache-2.0

> This source file belongs to the Q-FLARE platform (Nanda Construction — Nanda &
> Navya). It is honest by construction: no fabricated data, no invented metrics,
> every surrogate or fallback is clearly labelled, and no quantum speedup is ever
> claimed.

> **The only dataset in this repository is SYNTHETIC/DEMO.** Its exact wording:
>
> `THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION DATA.`
>
> Its single source is `provenance.SYNTHETIC_DATA_DISCLAIMER`; do not restate or
> reword it. Every record carries it in its own `disclaimer` field, and every
> report repeats it.

Everything in this directory is **new**. Nothing the team owns is modified,
removed or re-implemented. These files are read-only inputs:

| Team-owned file | How this package uses it |
| --- | --- |
| `app/engines/base.py` | The `ForecastEngine` Protocol that `HydroForecastEngine` satisfies. |
| `app/engines/factory.py` | The zero-argument resolver that constructs the engine. |
| `app/engines/reference.py` | The labelled demo engine; left available as a fallback. |
| `app/schemas/models.py` | The Pydantic contract every payload must satisfy. |

---

## 1. What this is

A modular, auditable hydrological forecasting pipeline that plugs into the
platform's existing `ForecastEngine` seam without touching it. The design goal
was not "the best score" — it was **a result you can defend line by line**.

Three properties drive every decision below.

1. **A metric is computed, never asserted.** `evaluation.py` has no constants.
   Every MAE, RMSE, R² and NSE in a report comes from `compute_metrics` applied
   to a `(y_true, y_pred)` pair. There is no code path that can emit a score it
   did not measure.
2. **Unknown stays unknown.** There is no default flood threshold, no default
   unit, no default dataset source. `config.py` defaults every one of them to
   `None`/`unknown` and treats a missing value as a blocker or an advisory, never
   as something to guess.
3. **Refuse rather than fabricate.** When the contract needs a value this
   pipeline cannot honestly produce, the engine raises `EngineNotReadyError`
   instead of inventing it. See §6.

---

## 2. Module map

| Module | Responsibility |
| --- | --- |
| `config.py` | Environment-driven, validated configuration. Every dataset-dependent fact is declared, never guessed. |
| `domains.py` | **Phase 1.** Record schemas for every data domain, plus the domain registry. Pure stdlib. |
| `quality.py` | **Phase 1.** Structural validation, stable issue codes, duplicate and conflict detection. Reports; never repairs. Pure stdlib. |
| `datasets.py` | **Phase 1.** Dataset descriptors and the domain-coverage matrix. Pure stdlib. |
| `preprocess_config.py` | **Phase 2.** Every preprocessing policy, its default, and the rules that refuse a configuration. Pure stdlib. |
| `preprocess_units.py` | **Phase 2.** Exact documented unit conversions. Guesses nothing. Pure stdlib. |
| `preprocess_temporal.py` | **Phase 2.** Timestamps, ordering, cadence, gap grids, gap policy, right-labelled resampling, chronological splitting. Pure stdlib. |
| `preprocess_pipeline.py` | **Phase 2.** The orchestrator, returning records plus a machine-readable report. Pure stdlib. |
| `feature_registry.py` | **Phase 3.** The feature vocabulary: definitions, naming, entity scopes, lineage, and the catalogue of features that cannot honestly be built. Pure stdlib. |
| `feature_config.py` | **Phase 3.** Every feature policy and its refusal rules — cutoffs, coverage, missing, warm-up, units, targets, strictness. Pure stdlib. |
| `feature_temporal.py` | **Phase 3.** Causal window arithmetic: lags, changes, accumulation, intensity, rolling statistics, calendar terms and target alignment. Pure stdlib. |
| `feature_pipeline.py` | **Phase 3.** The orchestrator: records in, a model-ready feature dataset plus a quality report out. Pure stdlib. |
| `preprocessing.py` | Validation, timestamp parsing, ordering, duplicate handling, missing-value policy, chronological split, train-fitted scaler/imputer. |
| `features.py` | Strictly-causal lag / rolling / rainfall / calendar features, and forward-time supervision alignment. |
| `models.py` | The executable model registry (NumPy linear + ridge; optional scikit-learn ensembles) and the documented-but-unimplemented roadmap. |
| `evaluation.py` | MAE / RMSE / R² / NSE / peak error / bias, comparison reports, and the selection-vs-held-out protocol check. |
| `risk.py` | Configurable flood-risk assessment. |
| `contract.py` | `ForecastOutput`, the forecast → optimization handoff, and the candidate-risk attribution spec. |
| `provenance.py` | Dataset / split / model provenance records and disclaimers. |
| `artifacts.py` | JSON artifact store with checksums, atomic writes and an opt-in pickle path. |
| `synthetic.py` | The deterministic SYNTHETIC/DEMO generator. |
| `training.py` | End-to-end train → compare → artifact, plus the CLI entrypoint. |
| `engine.py` | `HydroForecastEngine` behind the team's `ForecastEngine` Protocol. |

The first three modules are the **Phase 1 data / schema foundation** and are
documented separately in [`PHASE1_DATA_FOUNDATION.md`](PHASE1_DATA_FOUNDATION.md).
Importing them loads nothing outside the standard library — no NumPy, no pandas,
no scikit-learn — and they consume `config`, `contract` and `provenance` rather
than restating them.

The four `preprocess_*` modules are **Phase 2**, documented in
[`PHASE2_PREPROCESSING.md`](PHASE2_PREPROCESSING.md). Like Phase 1 they are pure
standard library, and for the same reason: a preprocessing question should not
require the training stack. They add no second validation framework (Phase 1's
`QualityIssue` stays the vocabulary; its results are embedded under
`phase1_quality`) and no second provenance record.

**Phase 2 does no feature engineering at all.** No lags, no rolling windows, no
rainfall accumulation, no flood-risk arithmetic — those belong to `features` and
the Phase 3 modules below, and to `risk`.

The four `feature_*` modules are **Phase 3**, documented in
[`PHASE3_FEATURE_ENGINEERING.md`](PHASE3_FEATURE_ENGINEERING.md). Like Phases 1
and 2 they are pure standard library, for the same reason. They consume Phase 2's
`PreprocessingResult` as the sole input contract and add no second validation,
quality, provenance, unit or splitting framework.

**Phase 3 does not train models.** It selects, fits, tunes and evaluates nothing
and reports no accuracy metric. It fits no imputer or scaler either — that belongs
after the split, and fitting either on the full series would put test-period
statistics into the model's inputs.

`features.py` above is the **pre-Phase-1** wide-`DataFrame` feature layer still
consumed by `training.py`, `engine.py` and two existing test modules. Phase 3
neither modifies nor replaces it: the two coexist, both are covered by the full
suite, and the window conventions are cross-checked against each other.

`engine` is imported **lazily** by `__init__.py`, so the factory stays the only
path that constructs it and tooling can import `config` without pulling in the
team Pydantic contract. The Phase 2 and Phase 3 entry points are lazy for the
same effect: eagerly importing `preprocess` or `build_features` here would drag
NumPy in through `synthetic` and make the standard-library-only claim reachable
only by importing the submodule directly.

---

## 3. Wiring

The service starts from the `ai-service/` directory (`uvicorn app.main:app`), so
`app` is the top-level package and the resolver value is:

```bash
FORECAST_ENGINE=app.engines.hydro.engine:HydroForecastEngine
```

Verified against the live team ref: `get_engine()` returns
`HydroForecastEngine` with `name == "navya-hydro"`.

> The string `ai_service.app...` suggested in some notes is **not** importable:
> `ai-service` is not a valid Python identifier.

`ReferenceEngine` remains available and is the default when `FORECAST_ENGINE` is
unset. Selecting this engine does not remove it.

### Dependencies

`numpy >= 1.26` and `pandas >= 2.1` are required. `scikit-learn >= 1.3` is
optional and unlocks two extra candidates; without it the pipeline still runs and
`models.unavailable_models()` reports exactly what is missing. See
`requirements-hydro.txt`.

**These are not in the team's `ai-service/requirements.txt`.** That file is
team-owned and is deliberately untouched by this branch. The required change is
recorded as team-owner action `AI-REQ-01` in
`01_Flood_Forecasting/TEAM_INTEGRATION_REQUIREMENTS.md`.

---

## 4. Configuration

All configuration is environment-driven and validated. A malformed value raises
rather than falling back to a default, because a silently-defaulted threshold is
how a demo number becomes a production number.

| Variable | Meaning | Default |
| --- | --- | --- |
| `HYDRO_ENABLED` | Master switch. | `true` |
| `HYDRO_DATASET_PATH` | CSV/Parquet input. | *(unset)* |
| `HYDRO_DATASET_TYPE` | `real` / `synthetic` / `unknown`. | `unknown` |
| `HYDRO_DATASET_REFERENCE` | Provenance URI for the source. | *(unset)* |
| `HYDRO_DATASET_LICENSE` | Source license. | *(unset)* |
| `HYDRO_STATION_REFERENCE` | Station or gauge id. | *(unset)* |
| `HYDRO_TIMESTAMP_COLUMN` | Timestamp column name. | `timestamp` |
| `HYDRO_ID_COLUMNS` | Per-entity id columns. | *(unset)* |
| `HYDRO_TARGET` | `water_level` or `inflow`. | `water_level` |
| `HYDRO_TARGET_UNITS` | Units of the target. | *(unset)* |
| `HYDRO_FORECAST_HORIZON_HOURS` | Lead time. | `6` |
| `HYDRO_MAX_LAG` | Number of lag features. | `12` |
| `HYDRO_ROLLING_WINDOWS` | Rolling window sizes. | `6,24` |
| `HYDRO_EXOGENOUS_COLUMNS` | Extra strictly-causal drivers. | *(unset)* |
| `HYDRO_RAINFALL_COLUMN` | Rainfall column. | *(unset)* |
| `HYDRO_MISSING_POLICY` | `ffill` / `drop` / `error`. | `ffill` |
| `HYDRO_MAX_FILL_GAP` | Max consecutive gap to fill. | `3` |
| `HYDRO_SCALER` | `standard` / `none`. Fitted on train only. | `standard` |
| `HYDRO_SPLIT_TRAIN` / `_VALIDATION` | Split fractions. | `0.6` / `0.2` |
| `HYDRO_MODEL` | Default estimator key. | `ridge` |
| `HYDRO_RIDGE_ALPHA` | L2 strength. | `1.0` |
| `HYDRO_MODEL_ID` | Model id in the payload. | `NAVYA-HYDRO-001` |
| `HYDRO_CONTRACT_VERSION` | Version tag in the payload. | `navya-forecast/v1` |
| `HYDRO_ARTIFACT_DIR` | Where artifacts are written. | *(unset)* |
| `HYDRO_FLOOD_THRESHOLD` | Flood threshold in target units. | *(unset — no default exists)* |
| `HYDRO_RISK_BANDS` | Probability band edges. | *(unset)* |
| `HYDRO_RISK_THRESHOLD_POLICY` | `pending` / `approved`. | `pending` |
| `HYDRO_RISK_THRESHOLD_SOURCE` | Citation for the threshold. | *(unset)* |

### Readiness vs. advisories

`HydroConfig.readiness()` returns only **blockers** — things that would force the
engine to fabricate a value. `HydroConfig.advisories()` returns **notes** that do
not block serving but must colour how the output is read.

A threshold that is *configured but not approved* is an advisory, not a blocker:
the engine serves it with `status="pending"` and labels the bands as configured
rather than official. That is honest, so it must not be reported as a blocker —
and keeping the two lists separate is what guarantees `is_ready()` and the serving
methods can never disagree.

---

## 5. Leakage controls

The pipeline is chronological throughout. There is no shuffle, no random split,
and no random seed in the data path.

| Control | Where | How it is enforced |
| --- | --- | --- |
| No target leakage | `features.build_supervised` | A plan containing the target as a feature is rejected. |
| Strict causality | `features` | Every feature is a function of `t-1…t-k`. Proven by perturbation in `test_hydro_leakage.py`, not by reading the code. |
| Train-only transforms | `preprocessing.StandardScaler`, `TrainFittedImputer` | `fit()` refuses any `split_label` other than `train`. |
| Forward fill only | `preprocessing.apply_missing_policy` | A leading gap is **dropped**, never filled from the future. |
| Non-overlapping splits | `preprocessing.assert_no_overlap` | Contiguous, ordered periods; a leaky split raises. |
| Forward-time targets | `features.build_supervised` | `target_timestamp > origin_timestamp` for every row. |
| Held-out test split | `evaluation.ModelComparison` | Ranking on the test split raises; the held-out report must belong to the selected model. |

### The selection protocol

Selection is a **two-pass** process, and the order matters:

1. Every candidate is fitted on **train** and scored on **validation**.
2. The best validation score wins.
3. **Only then** is the winner scored once on **test**.

Ranking candidates across both splits at once would let the test period pick the
winner, which turns the test score into a selection statistic and inflates it.
`ModelComparison.assert_selection_is_clean()` rejects that arrangement, and
`training.py` uses the `SELECTION_SPLIT` / `HELD_OUT_SPLIT` constants so the
order is not a caller's choice.

The practical consequence: the validation figure is optimistic by construction.
`TrainedModel.best_report` returns the **held-out** report, because that is the
one a reader should be shown.

---

## 6. Honest refusal

`EngineNotReadyError` is raised — never a fabricated payload — when:

| Situation | Why it refuses |
| --- | --- |
| No usable threshold / band policy | The contract requires `flood_probability` and `risk_level`; the pipeline will not invent them. |
| Fewer than 2 backtest points | An exceedance probability needs a **measured** residual spread. |
| Residual sigma is zero or unmeasurable | Same: a probability from an assumed sigma is a guess. |
| Requested horizon ≠ trained horizon | The lead time is baked into the supervised alignment; another horizon needs a retrained model. |
| Target is `inflow` | The running `ForecastPrediction` contract has only `predicted_water_level`. Serving inflow through it would be a unit error. |
| `HYDRO_ENABLED=false` | The engine is switched off. |

The reference engine's demo threshold of `8.0` is **deliberately not inherited**.
If you want a threshold, set `HYDRO_FLOOD_THRESHOLD` yourself and cite it in
`HYDRO_RISK_THRESHOLD_SOURCE`.

---

## 7. Risk model

`risk.py` computes `P(level > threshold)` from a normal approximation using a
residual standard deviation **measured on the held-out backtest**, not assumed.

- `exceedance_probability(v, t, σ) = 1 − Φ((v − t) / σ)`
- `residual_sigma` is the sample standard deviation (`ddof=1`) of the observed
  errors, and requires at least two observations.
- `classify_risk_level` maps a probability onto `LOW / MEDIUM / HIGH / CRITICAL`
  using the configured band edges.

**This is a stated modelling assumption, not a validated flood model.** The
normal approximation ignores skew and fat tails that real stage data exhibits,
and the threshold itself is unvalidated until a hydrologist supplies one. The
threshold and its band policy are reported in every payload
(`threshold`, `threshold_source`, `threshold_policy`) so a reader can always see
what the number was derived against.

---

## 8. Running it

```bash
cd ai-service

# 1. Write a labelled SYNTHETIC/DEMO dataset.
python -m app.engines.hydro.training --write-synthetic ./data/synthetic_hydrology_sample.csv

# 2. Train and compare on it (synthetic results are labelled as such).
python -m app.engines.hydro.training \
  --dataset ./data/synthetic_hydrology_sample.csv --dataset-type synthetic

# 3. List which models can actually run here.
python -m app.engines.hydro.training --describe-registry
```

## 9. Tests

```bash
cd ai-service
python -m pytest tests -q
```

`tests/conftest.py` is shared with the team's `tests/test_contract.py`, so it is
defensive by design: if `numpy`/`pandas` are absent it sets
`collect_ignore_glob = ["test_hydro_*.py"]`, which makes these modules **skip**
rather than error. The team's own tests are never touched.

`tests/test_hydro_engine_contract.py` additionally skips when the team seam
(`app/schemas/models.py`, `app/engines/base.py`, `app/engines/factory.py`) is
absent, because on a branch without them there is nothing to conform to. After
the integration merge, the whole file runs.

Phase 2 adds 174 tests across four modules, all named `test_hydro_preprocess_*`
and therefore covered by the same skip guard:

| Module | Groups |
| --- | --- |
| `tests/test_hydro_preprocess_timestamps.py` | timestamps, ordering, units |
| `tests/test_hydro_preprocess_cleaning.py` | duplicates, conflicts, gaps |
| `tests/test_hydro_preprocess_resample_split.py` | resampling, splitting, leakage |
| `tests/test_hydro_preprocess_pipeline.py` | end-to-end and guarantees |

Phase 3 adds 222 tests across four modules, all named `test_hydro_feature_*` and
therefore covered by the same skip guard:

| Module | Groups |
| --- | --- |
| `tests/test_hydro_feature_registry.py` | definitions, naming, scopes, lineage, the unbuildable catalogue |
| `tests/test_hydro_feature_config.py` | every policy, its default, and its refusal rules |
| `tests/test_hydro_feature_temporal.py` | window arithmetic, cutoffs, warm-up, and a `pandas.Series.rolling` cross-check |
| `tests/test_hydro_feature_pipeline.py` | leakage 1–7, determinism, availability, the Phase 4 contract, AST scope guards |

Current full-suite result: **993 passed, 1 skipped** (771 passed before Phase 3,
597 before Phase 2).

No existing test was weakened, modified or deleted in Phases 2 or 3.

---

## 10. What is deliberately not here

- **No real hydrological data, and no dataset claiming to be one.**
  `datasets.committed_sample_catalog()` holds exactly one entry, the committed
  SYNTHETIC/DEMO sample, and `EMPTY_CATALOG` is the default. No rainfall value,
  water level, discharge, inflow, station identifier, official threshold,
  coordinate, population figure or flood event has been invented anywhere in this
  package. Where a fact is unknown it is `None` or the project's
  `NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED` marker.
- **No LSTM / GRU / QML regressor.** They appear in
  `models.FUTURE_MODEL_ROADMAP` as unimplemented future work. A test asserts
  that no roadmap key is selectable, so the registry cannot claim a model that
  was never trained.
- **No live telemetry feed.** The engine forecasts from the tail of the loaded
  dataset. A gauge feed needs a station source, which this repository does not
  contain.
- **No default threshold, unit, datum, or horizon.** All are configuration, and
  the defaults are `None`/`unknown`.
- **No classification metrics.** Accuracy / precision / recall / F1 are absent by
  design: a regression forecast has no class labels, and a test asserts they stay
  out of `EvaluationMetrics.as_dict()`.
- **No production-ready claim for synthetic data.** `ArtifactRecord.production_ready`
  is `False` for anything that is not `real` data without a disclaimer, and a
  test pins that behaviour.
