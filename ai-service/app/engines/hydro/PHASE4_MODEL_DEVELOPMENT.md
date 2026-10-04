# Phase 4 - Model Development, Training & Evaluation

Owner: Navya (`ai-service/app/engines/hydro/`) · Branch: `feature/navya-forecast`
· Predecessor: [`PHASE3_FEATURE_ENGINEERING.md`](PHASE3_FEATURE_ENGINEERING.md)

> **All data referenced in this phase is SYNTHETIC/DEMO.** The committed sample is
> generated. Nothing in this repository is a real hydrological observation, and
> nothing produced by this phase may be presented as one.
>
> The verbatim source disclaimer is carried by
> `datasets.SYNTHETIC_SAMPLE_PATH` and reproduced in every report and every
> artifact this phase writes:
> `THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL
> HYDROLOGICAL OBSERVATION DATA.`
>
> **No model in this phase is production-ready, and none is claimed to be.**
> `production_ready_claimed` is permanently `False` in every manifest, every run
> record and every handoff result. Training completed; that is all that means.
> Nothing here has been validated against a gauge network, a rating curve, a flood
> threshold, or any operational decision.

---

## 1. What Phase 4 is for

Phase 1 established what a hydrological record *is*. Phase 2 established what a
clean, chronologically split, unit-consistent dataset looks like. Phase 3 turned
that dataset into columns a forecasting model can be fitted on, with every column
a function of the past. Phase 4 fits models on those columns, scores them against
a persistence baseline on the same rows, records what it did in machine-readable
form, and hands a contract to Phase 5.

```python
from app.engines.hydro.model_config import deterministic_config
from app.engines.hydro.model_training import train_models
from app.engines.hydro.model_artifacts import build_manifests

result = train_models(
    feature_result.dataset,
    (deterministic_config("naive"), deterministic_config("random_forest")),
    cadences=feature_result.report.cadence,
)

result.comparison.describe()      # every family, every split, every status
result.audit.verdict               # the eight leakage checks
manifests = build_manifests(result)
```

Eight modules, all in `ai-service/app/engines/hydro/`:

| Module | Responsibility |
| --- | --- |
| `model_config.py` | The frozen, explicit, deterministic configuration object |
| `model_registry.py` | Which families exist, what each needs, whether it is importable here |
| `model_dataset.py` | Targets, splits, matrices, persistence baseline, sequence windows |
| `model_evaluation.py` | Metrics, evaluation outcomes, the comparison table |
| `model_audit.py` | The eight leakage checks and the audit verdict |
| `model_training.py` | Adapters, orchestration, run records, insufficiency records |
| `model_artifacts.py` | Manifests, fingerprints, the weight-storage policy |
| `model_handoff.py` | The Phase 5 request/result contract |

### Phase 4 does NOT

- generate forecasts for arbitrary future instants (Phase 5);
- expose an HTTP route, a handler, or any persistence;
- compute flood risk, flood probability, or a risk score;
- touch GIS, population, or infrastructure exposure;
- place sensors;
- do anything with QUBO, QAOA, or quantum optimisation;
- install a missing dependency or edit a team-owned dependency manifest;
- store fitted weights in this repository;
- claim a model is production-ready, hydrologically validated, or better than a
  baseline unless the numbers on the same rows say so.

---

## 2. The model registry

`model_registry.py` is a static, machine-readable declaration of what Phase 4
knows how to run. It is readable without importing anything:

```python
from app.engines.hydro.model_registry import registry_rows, probe_all

for row in registry_rows():
    row["model_family"]        # naive, random_forest, xgboost, lstm, gru
    row["role"]                # baseline / classical_ml / sequence
    row["implementation"]      # native / scikit_learn / xgboost / keras
    row["available_here"]      # probed in THIS environment, right now
    row["runtime_versions"]    # {} when the family declares no library
    row["blocked_reason"]      # exact symbol + exact ImportError, when unavailable
```

Five families, and each declares the dotted path it needs:

| Family | Role | Implementation | Import symbol probed |
| --- | --- | --- | --- |
| `naive` | `baseline` | `native` | none — no library dependency |
| `random_forest` | `classical_ml` | `scikit_learn` | `sklearn.ensemble.RandomForestRegressor` |
| `xgboost` | `classical_ml` | `xgboost` | `xgboost.XGBRegressor` |
| `lstm` | `sequence` | `keras` | `keras.Sequential` |
| `gru` | `sequence` | `keras` | `keras.Sequential` |

`probe()` imports the symbol and reports the outcome. It does not install
anything, and it does not catch anything but `ImportError` — a library that
imports and then fails on a missing native dependency should surface as a failure,
not as a silent "unavailable".

**Verified in this environment** (Python 3.13.5):

```
naive           impl=native        available=True   rt={}
random_forest   impl=scikit_learn  available=True   rt={'sklearn.ensemble.RandomForestRegressor': '1.9.1'}
xgboost         impl=xgboost       available=False  -> 'xgboost.XGBRegressor' is not importable ... (ModuleNotFoundError)
lstm            impl=keras         available=False  -> 'keras.Sequential' is not importable ... (ModuleNotFoundError)
gru             impl=keras         available=False  -> 'keras.Sequential' is not importable ... (ModuleNotFoundError)
```

Available: numpy 2.5.1, pandas 3.0.3, scikit-learn 1.9.1, scipy 1.18.1,
joblib 1.6.0, pytest 9.1.1. Absent: xgboost, tensorflow, torch, keras.

---

## 3. Model configuration

`ModelConfig` is a frozen dataclass. Every hyperparameter that influences a fit
lives in exactly one place, and nothing is defaulted at the call site.

```python
ModelConfig(
    model_family, target_quantity, horizon_hours, random_seed,
    feature_selection, scaler_policy, impute_policy, split_policy,
    persistence_source, lookback, min_train_rows, min_eval_rows,
    metrics, artifact_policy, training, subject,
)
```

`deterministic_config(family)` returns the frozen default. It **refuses** a
`random_seed` override by raising `ModelConfigError` — the seed is part of the
contract, and a caller who wants a different one should say so with
`dataclasses.replace(config, random_seed=...)`, which is visible at the call
site rather than buried in a factory.

Policy vocabularies, all closed and validated at construction:

- `feature_selection`: `train_present_only` (default) drops columns with no
  finite training value; `all` retains them, and the imputer then raises
  `PreprocessError` **naming the column**. The default hides nothing: it either
  excludes the column or says out loud why it cannot be used.
- `scaler_policy`: `none`, `standard`.
- `impute_policy`: `none`, `median`.
- `split_policy`: `phase3_chronological` — the only value. Phase 4 does not
  invent split percentages.
- `persistence_source`: `same_split_only` (default), `any_past`.
- `artifact_policy`: `metadata_only` (default), `include_parameters`.

There is deliberately **no `hyperparameters` field**. Requested hyperparameters
go in `config.training`; the *effective fitted* values are read back off the
estimator and recorded in the run record, so what is reported is what was used
rather than what was asked for. That distinction mattered: see §11.

---

## 4. Targets

Phase 4 consumes Phase 3's target definitions and never invents or substitutes
one. `TargetBinding` names the column, its units, its horizon in seconds and its
label, and all four travel together to the run record, the manifest and the
handoff result.

If a target is unavailable it is marked unavailable. `target_unavailable` is a
first-class training status, not an error and not a silent fallback to a
similarly-named column.

Verified on the committed fixture: target `target_water_level_6h`, units `m`,
horizon `21600s`, label `6h`.

---

## 5. Horizons

Horizons come from Phase 3 and each is evaluated independently. The alignment is
`features at t → target at t+H`, and features for a sample never contain any
instant in `(t, t+H]`.

`target_horizon_alignment_exact` in the audit re-derives `target − origin` for
every supervised row and requires it to equal the declared horizon exactly, with
no tolerance:

```
all 228 supervised row(s) are aligned to exactly 21600s
```

---

## 6. Temporal splitting

Chronological `TRAIN → VALIDATION → TEST`, never random. The split constants and
boundaries are reused from `feature_pipeline`; Phase 4 does not define its own.

Verified on the fixture:

```
train       2024-01-01T00:00:00Z .. 2024-01-04T11:00:00Z   168 rows
validation  2024-01-04T12:00:00Z .. 2024-01-05T11:00:00Z    48 rows
test        2024-01-05T12:00:00Z .. 2024-01-06T11:00:00Z    48 rows
```

Two audits cover this. `split_origins_chronologically_ordered` checks the
boundaries are non-overlapping and forward-running.
`split_labels_do_not_cross_boundaries` checks every row carries a label from
inside its own split — and, after a fix this phase, also checks that a matrix's
own `split` attribute agrees with the key it is filed under, so a swap between
two splits cannot pass.

### Scored rows are identical across models

A row that cannot be scored for the baseline is excluded from **every** model's
score. Otherwise the baseline and the forest would be measured on different row
sets and the comparison would be meaningless. On the fixture:

```
SCORED POPULATION: every model above is scored on exactly the rows listed here,
so the figures are like-for-like (test: 24 of 48, train: 144 of 168,
validation: 24 of 48).
```

---

## 7. Sequence windows

For `lstm` and `gru`, a sample is a window `[t−L+1 … t]` predicting `t+H`. The
window never contains `t+1 … t+H`, and never mixes entities — a window is
always one station.

`SequenceSet` accounts for every origin row:

```
train       480 rows = 458 windows + 10 no-history + 0 no-target + 12 restricted
validation  120 rows =  96 windows +  0 no-history + 0 no-target + 24 restricted
test        120 rows =  96 windows +  0 no-history + 0 no-target + 24 restricted
```

`restricted_rows` was added this phase because rows dropped by an explicit
`restrict` mask were previously invisible — the accounting simply did not add
up, which is exactly the kind of gap that hides a bug.

`window_entity_sets` was likewise added: the previous entity check read
`entities = {block.window_entities[index]}`, which is a set of one element by
construction and could never fail. It now verifies the recorded entity set and
cross-checks it against the window.

---

## 8. Scaling and imputation

Fitted on **TRAIN only**. Validation and test are transformed with the training
transforms and never contribute a statistic.

The order is impute, then scale. Scaling reuses `preprocessing.StandardScaler`;
imputation reuses `preprocessing.TrainFittedImputer`.

Recorded on every dataset and every manifest:

- `scaler_state`: `{columns, fitted_on, fitted_rows, kind, mean, scale}`
- `imputer_state`: `{kind, columns, values, fitted_rows, fitted_on}`
- the scaler type, the fitted feature names, and the training bounds

Verified: `every fitted statistic reproduces from the 168 training row(s) alone;
2 non-training split(s) were transformed with those same values`.

The audit's check is a **reconstruction**, not a flag. It refits from the
recorded training rows and compares against the recorded values, so a statistic
that had seen a validation row would not reproduce.

On the fixture, 172 absent feature cells were replaced by the training median of
their column, and that count is printed above the comparison table rather than
being left in a log.

---

## 9. The persistence baseline

`prediction(t+H) = latest known target value`, computed on **identical** splits,
horizons, target definition and metrics as every other model.

`NaivePersistenceEstimator` is split-aware: it is bound to one split at a time
and refuses an unbound split or a row count that differs from the bound block.
It also records `source_instants` — the reading instant each value was carried
forward from — so a prediction can be traced back to the observation it came
from.

Policies:

- `same_split_only` (default) — the carried-forward reading must come from the
  same split. This is the stricter, default choice.
- `any_past` — any earlier reading may be used.

There is no third option, and in particular no "use the mean of the training
target", which would be a plausible number that is not a baseline.

---

## 10. Metrics

Delegated to `evaluation.compute_metrics`. Reported set:

```
REPORTABLE_METRICS = ("mae", "rmse", "r2", "nse", "peak_absolute_error", "bias")
```

Validation and test are reported **separately** and never averaged into a single
headline. Every row retains `model, target, horizon, split, metric, value`, and
every table carries the synthetic label.

**MAPE is deliberately not reported.** On a target that can legitimately be zero
— and river stage near zero is not exotic — percentage error is undefined, and
the usual workaround (skipping zeros, adding epsilon) produces a number whose
meaning depends on the workaround. Reporting it would be reporting an artefact of
the denominator guard.

### Verified results — all five families, seed 20240917

Rows scored: 24 validation, 24 test.

| Family | Split | MAE | RMSE | R² | bias | n |
| --- | --- | --- | --- | --- | --- | --- |
| `naive` (baseline) | validation | 0.252724 | 0.312321 | 0.957248 | −0.132539 | 24 |
| `naive` (baseline) | test | 0.233840 | 0.308863 | 0.958368 | −0.088233 | 24 |
| `random_forest` | validation | **0.232386** | **0.273535** | **0.967207** | −0.202017 | 24 |
| `random_forest` | test | 0.409215 | 0.459281 | 0.907944 | −0.409215 | 24 |
| `xgboost` | validation | — | — | — | — | 0 |
| `xgboost` | test | — | — | — | — | 0 |
| `lstm` | validation | — | — | — | — | 0 |
| `lstm` | test | — | — | — | — | 0 |
| `gru` | validation | — | — | — | — | 0 |
| `gru` | test | — | — | — | — | 0 |

`—` means the metric does not exist, not zero. Each blocked row carries the
exact blocker as its note.

### The honest reading of these numbers

On this fixture the random forest is **marginally better than the baseline on
validation and clearly worse on test**:

```
random_forest  validation  Δ MAE = +0.020338 (forest better)
random_forest  test        Δ MAE = −0.175375 (forest worse by 0.175 m)
```

A test asserts that the two splits **disagree**, so this cannot quietly become a
consistent story later.

The gap has an obvious and unflattering explanation: the forest's test-split bias
(−0.409215) equals its test MAE exactly, which means essentially every test
prediction was below its observation by a similar amount — a persistent
under-prediction on the test period that the validation period did not show.
With 144 training rows and 35 features, that is what overfitting looks like.

**No superiority claim is made.** A 6-hour water-level model evaluated on 24
synthetic rows from a generated fixture with no physics says nothing about a real
river. The comparison table exists so the numbers can be read and judged, not so
a winner can be announced.

---

## 11. The random forest, and the seed defect that was in it

`RandomForestEstimator` wraps the pre-existing `models.build_model("random_forest",
...)` rather than replacing it, so the legacy `models.py` / `training.py` /
`evaluation.py` path keeps working unchanged.

**The defect found and fixed this phase.** `models._build_sklearn` did
`kwargs.setdefault("random_state", 0)`. Every forest was therefore fitted with
seed 0, while the run record, the `model_id` and the provenance all said
`seed20240917`. Changing `random_seed` changed nothing about the model — the
recorded seed was a claim about the run that the run did not bear out.

`_seed_estimator()` now rebuilds the estimator through `build_model` whenever its
`get_params()["random_state"]` differs from the requested seed, and
`_effective_parameters()` reads the fitted estimator's real parameters back into
the record.

Verified after the fix:

```
seed=20240917:  validation MAE 0.232386   fitted random_state = 20240917
seed=4242:      validation MAE 0.237966   fitted random_state = 4242
```

The seed now reaches the estimator, and the recorded hyperparameters are the
fitted ones. Figures quoted in earlier drafts of this work under the seed-0
defect (validation MAE 0.2474 / test 0.4339) are **superseded** by the table in
§10.

---

## 12. XGBoost, LSTM and GRU — implemented, and dependency-blocked

All three have real adapters in `model_training.py`. None of them can run here.

| Family | State | Blocker |
| --- | --- | --- |
| `xgboost` | implemented, blocked | `'xgboost.XGBRegressor' is not importable in this environment (ModuleNotFoundError)` |
| `lstm` | implemented, blocked | `'keras.Sequential' is not importable in this environment (keras -> ModuleNotFoundError)` |
| `gru` | implemented, blocked | same |

Each blocked family still appears in the comparison table, with
`training_status=dependency_unavailable`, `evaluation_status=not_evaluated`,
`n_samples=0`, null metrics and the exact blocker as its note. A family that was
attempted and could not run is **not** the same as one that was never tried, and
the table distinguishes them.

Phase 4 does not install a package and does not edit a team-owned dependency
manifest. The required integration action is recorded in
`01_Flood_Forecasting/TEAM_INTEGRATION_REQUIREMENTS.md`.

The `XGBoostEstimator` wraps `models.build_model("xgboost", ...)` and adds
`eval_set` early stopping on the validation split.

---

## 13. Insufficient data

A structured `insufficient_data` status, never fabricated rows and never a
fabricated metric. The record is a dict, not a sentence, so a tool can act on it:

```python
{
  "reason": "fewer supervised training rows than this family requires",
  "required": 10000,
  "available": 156,
  "target": "target_water_level_6h",
  "horizon": "6h",
  "entity": None,
  "model": "random_forest",
}
```

Required, available, target, horizon, entity and model. A reader who wants more
rows knows how many, for what, and at which horizon.

---

## 14. The leakage audit

Eight checks, in `model_audit.py`, each independently reporting `pass`, `fail` or
`skipped` with a detail string:

| Check | What it establishes |
| --- | --- |
| `features_read_at_or_before_origin` | no feature reads an instant after its own origin |
| `target_instant_strictly_after_origin` | every target is strictly in the future |
| `target_horizon_alignment_exact` | `target − origin` equals the declared horizon exactly |
| `feature_columns_disjoint_from_targets` | no feature is a target, by name or by the reserved `target_` prefix |
| `split_origins_chronologically_ordered` | splits run forward in time and do not overlap |
| `split_labels_do_not_cross_boundaries` | every row's label is inside its own split |
| `scaler_and_imputer_fitted_on_train_only` | fitted statistics reproduce from training rows alone |
| `sequence_windows_causal_and_entity_scoped` | windows are causal and never mix stations |

The minimum eight the requirements ask for, one per mutation class: future
feature, target, cross-station, split isolation, scaler isolation, sequence
causality, horizon alignment, feature/target separation.

Verified on the fixture with sequences configured — **8/8 pass, verdict `PASS`**:

```
pass  features_read_at_or_before_origin        all 264 row(s) read only instants at or before their prediction origin
pass  target_instant_strictly_after_origin     all 228 supervised row(s) carry a target strictly after their origin
pass  target_horizon_alignment_exact           all 228 supervised row(s) are aligned to exactly 21600s
pass  feature_columns_disjoint_from_targets    35 feature column(s) share no name with any target
pass  split_origins_chronologically_ordered    chronological and non-overlapping (train=168, validation=48, test=48)
pass  split_labels_do_not_cross_boundaries     all 228 supervised row(s) carry a label from inside their own split
pass  scaler_and_imputer_fitted_on_train_only  reproduces from the 168 training row(s) alone
pass  sequence_windows_causal_and_entity_scoped
```

Without sequence windows configured, the eighth check reports **`skipped`, not
`pass`** — "no sequence windows were configured for this run, so no lookback
window exists to inspect" — and the overall verdict is `PARTIAL`, not `PASS`.

`LeakageAudit` distinguishes three things:

- `ok` — **strict**. True only when every check both ran and passed.
- `verdict` — `FAIL` if anything failed; `PARTIAL` if anything was skipped or
  nothing ran; `PASS` otherwise. A skip never rounds up to a pass.
- `failed()` / `skipped_checks()` — methods, so they read as questions.

The same principle applies inside the checks: `_check_train_fitted_stats`
returns `skipped` when no scaler and no imputer were fitted, because a check that
had nothing to run on has verified nothing, and reporting `pass` would put the
same word on two very different facts.

---

## 15. Artifacts

**Metadata only. No weights are written to this repository.**

`WEIGHT_STORAGE_POLICY`, verbatim in substance: fitted weights are not stored
here. A random forest and a recurrent network are tens of megabytes of binary
that would make every diff unreviewable and every clone slow, while everything a
reviewer actually needs — target, horizon, feature list and version, split
bounds, seed, hyperparameters, library versions, metrics, provenance — is text.
The bytes belong in object storage or a model registry (MLflow, S3, a container
image), addressed by a reference. Loading weights is a Phase 5 / deployment
responsibility and is deliberately not implemented.

Three artifact states, and they mean three different things:

| State | Meaning |
| --- | --- |
| `metadata_only` | fitted or scored; the manifest exists; no bytes were written |
| `with_parameters` | a parameters block was also emitted |
| `not_written` | **the model did not fit** |

Verified:

```
naive           artifact_status=metadata_only   training=trained                  evaluation=evaluated
random_forest   artifact_status=metadata_only   training=trained                  evaluation=evaluated
xgboost         artifact_status=not_written     training=dependency_unavailable  evaluation=not_evaluated
lstm            artifact_status=not_written     training=dependency_unavailable  evaluation=not_evaluated
gru             artifact_status=not_written     training=dependency_unavailable  evaluation=not_evaluated
```

`weight_reference` is `None` whenever `weight_stored_in_repository` is `False`. A
reference string with no object behind it is worse than none.

`write_manifests()` writes one `.manifest.json` per written model plus a
`phase4-artifacts.index.json`. **The index lists the blocked models too**, so an
attempt that produced nothing is still visible in the written record. Only `.json`
is ever written — the policy is checkable, so a test checks it. Writing to an
empty path raises rather than silently succeeding.

### The fingerprint

`TrainingFingerprint` is a SHA-256 digest over the sorted canonical JSON of the
facts that define the experiment: contract versions, target, horizon, feature
columns and digest, split/scaler/impute/feature-selection/persistence policies,
seed, hyperparameters, row counts per split, dataset reference and checksum,
dependency versions.

Two runs of the same configuration produce the same fingerprint. A changed seed
produces a different one. Verified digests differ per family, and the `lstm` and
`gru` fingerprints are identical to each other — correctly, since both are the
same blocked experiment with the same configuration.

---

## 16. Determinism

Recorded on every run and every manifest: seed, model configuration, feature
registry version, dataset fingerprint, train/validation/test row counts,
dependency versions.

`NONDETERMINISTIC_FIELDS = ("created_at", "provenance.created_at")`

These are **paths, not top-level keys**, and that is load-bearing. The manifest
carries a second wall-clock instant inside the provenance block it reuses from
Phase 3. An earlier version of this phase declared only `created_at`, which meant
the manifest claimed a determinism it did not have: two identical runs produced
two documents differing in a field nobody had declared. Declaring the nested path
is what makes the claim true rather than merely stated.

Verified: two runs of the same configuration differ in exactly the two declared
paths and nowhere else, at both the manifest level and inside the embedded
manifest list of the run bundle.

**Framework nondeterminism, stated honestly.** The claim is about configuration,
rows, metrics and metadata — not about byte-identical weights. scikit-learn's
forest is seeded and reproducible for a fixed `random_state` and `n_jobs`, but
Phase 4 does not require byte-identical binary weights across environments,
because that is not a property it can guarantee and should not pretend to. The
seed, the library versions and the full parameter set *are* recorded, so a
mismatch is diagnosable rather than mysterious.

---

## 17. Provenance

**Reuse, not a second scheme.** Phase 4 fills in the existing Phase 1–3
`ProvenanceRecord` and adds two contract versions to its
`software_environment` block: `phase4_model_contract` and the feature contract
version. No parallel provenance system was introduced.

Verified on the fitted forest:

```
dataset_type = synthetic        target = target_water_level_6h
target_units = m                forecast_horizon = 6h
is_synthetic = True             model_version ends with seed20240917
software_environment: phase4_model_contract, random_seed=20240917, python, numpy, sklearn
disclaimer = the full synthetic disclaimer
```

A blocked model still carries provenance, with `evaluation_metrics = None` and a
populated `missing_fields`. A run that was attempted left a record even though it
produced no model.

---

## 18. The model comparison table

Minimum columns, all present:

```
model_id, model_family, target, horizon, split,
training_status, evaluation_status, data_status, synthetic_demo,
n_samples, MAE, RMSE, R2, bias
```

Plus `baseline_delta` — each row's difference from the persistence baseline on
the same split and the same rows — and `notes`.

Five families × two splits = **10 rows**, always. A family that could not run
gets a row with a status, not an absence.

`training_status` and `evaluation_status` are **independent facts**. A model can
fit perfectly well and still fail to evaluate on too few rows, and a table that
conflated the two would call that a failed fit.

```
TRAINING_STATUSES  = trained, dependency_unavailable, target_unavailable,
                    insufficient_data, evaluation_unavailable, failed_training
EVALUATION_STATUSES = evaluated, not_evaluated, insufficient_rows, failed
```

`EvaluationOutcome` enforces the invariant in its constructor: status `evaluated`
requires non-`None` metrics, and every other status requires `metrics is None`.
An unavailable metric is never converted to `0.0`. Zero would mean "perfect",
which is a claim; `None` means "does not exist".

`data_status` is `synthetic_demo` when the data is synthetic, `measured` **only**
when `dataset_type == "real"`, and `unknown` otherwise. There is no path from
this phase that produces `measured`, because there is no measured data here.

---

## 19. The Phase 5 handoff contract

`HANDOFF_CONTRACT_VERSION = "navya-handoff/v1"`. A contract, not a service: no
HTTP route, no handler, no persistence.

**Request** — `target`, `horizon`, `entity`, `origin_instant`, plus an optional
`model_id` **or** `model_family`. Naming both selectors is refused, because two
selectors make it ambiguous which model the caller meant.

**Result** — `status`, `reason`, `model_id`, `model_family`, `target`,
`target_units`, `horizon`, `entity`, `prediction`, `source_timestamp`,
`prediction_timestamp`, `model_version`, `feature_version`, `feature_count`,
`uncertainty`, `provenance`, `artifact_status`, `data_status`, `synthetic_demo`,
`disclaimer`.

Verified, one request per status:

| Request | Status | prediction | prediction_timestamp |
| --- | --- | --- | --- |
| forest, with a prediction | `ready` | 3.5 | 2024-01-05T18:00:00Z |
| forest, no prediction supplied | `no_prediction` | `None` | `None` |
| xgboost | `dependency_unavailable` | `None` | `None` |
| forest, no manifests | `artifact_unavailable` | `None` | `None` |
| unknown model id | `model_unavailable` | `None` | `None` |
| forest, horizon `24h` | `invalid_request` | `None` | `None` |
| forest, target `target_discharge_6h` | `invalid_request` | `None` | `None` |
| forest, horizon `later` | `invalid_request` | `None` | `None` |

Statuses: `ready`, `invalid_request`, `dependency_unavailable`,
`insufficient_data`, `target_unavailable`, `artifact_unavailable`,
`model_unavailable`, `no_prediction`.

### Three guards found and fixed this phase

1. **The target guard crashed.** It passed both `horizon=` explicitly and
   `**common`, which already contained `horizon` — so the "you asked for a target
   this model was not trained on" path raised `TypeError` instead of returning
   `invalid_request`. The guard existed and did not work.

2. **The horizon was not guarded at all.** A 6-hour model answered `ready` for a
   24-hour request, stamping the forecast 24 hours out. A plausible number about
   the wrong instant — harder to catch downstream than an outright refusal,
   because every field is individually well-formed. The target and horizon guards
   are now one check.

3. **Every refusal carried a prediction timestamp.** `prediction_timestamp` was
   derived from the request alone and put on all results, so a
   `dependency_unavailable` response had a well-formed timestamp and no value. It
   is now set only on `ready`. `source_timestamp` stays on every result, because
   the origin instant was genuinely read and it describes the request rather than
   an answer.

### Uncertainty

`uncertainty.value` is populated **only** by `residual_sigma_from()`, which
computes the standard deviation of observed-minus-predicted pairs the caller
supplies. Below two pairs it returns `unavailable` with the pair count in the
reason — a standard deviation over one pair is exactly `0.0`, and `0.0` reads as
"this model makes no error", which is the strongest possible claim and the least
supported.

`is_prediction_interval=True` **always raises**. A past-error spread is not a
coverage guarantee for a future value, and Phase 4 has no interval method. The
caveat travels with every measured sigma.

`to_forecast_output()` converts a ready result into the platform's existing
`contract.ForecastOutput` rather than defining a parallel shape. A non-ready
result becomes `failed` with a null value and the reason carried through.

---

## 20. Tests

Eight focused modules, all on deterministic synthetic fixtures, no network, no
real hydrological data:

Collected counts, from `pytest --collect-only`:

| Module | Tests |
| --- | --- |
| `test_hydro_model_registry.py` | 69 |
| `test_hydro_model_config.py` | 64 |
| `test_hydro_model_dataset.py` | 84 |
| `test_hydro_model_evaluation.py` | 59 |
| `test_hydro_model_audit.py` | 63 |
| `test_hydro_model_training.py` | 63 |
| `test_hydro_model_artifacts_handoff.py` | 113 |
| **Phase 4 total** | **515** |
| `hydro_phase4_fixtures.py` | shared fixtures, no tests |

`test_hydro_models.py` (28 tests) is the pre-Phase-1 legacy module and is not
counted above.

**Full suite: 1507 passed, 2 skipped.** The Phase 1–3 baseline is 993 passed /
1 skipped, so Phase 4 added 514 passing tests and one skip.

Fixtures are not auto-discovered, so each module imports every fixture it uses by
name. All fixtures are self-contained; the two stations carry a constant 3.0 m
offset, which is what makes a cross-station read detectable rather than
theoretical.

Determinism is tested by running equivalent training twice and comparing
configuration, run records, evaluated metrics and artifact metadata with exactly
the declared nondeterministic paths stripped — and a companion test asserts those
two timestamps really did move, so a determinism test cannot pass by stripping a
field that was simply absent.

No test asserts a forecasting result, and none can: there is no measured
hydrological data in this repository.

---

## 21. Source defects found and fixed in Phase 4

Recorded because a reader comparing against earlier output will see different
numbers and deserves to know why.

| Where | Defect | Effect |
| --- | --- | --- |
| `model_training._run_one` | `blocks` used before assignment | `UnboundLocalError` on every run |
| `models._build_sklearn` (legacy, wrapped) | `random_state` forced to 0 | recorded seed did not reach the estimator |
| `model_training` | no comparison rows for blocked families | three of five families invisible |
| `model_evaluation._row_notes` | iterated a `str` as a sequence | one note **per character** in every blocked row |
| `model_evaluation` | unevaluated rows carried no reason | a status with no explanation |
| `model_artifacts` | `parameters_recorded` keyed off policy | `False` beside a populated `hyperparameters` block |
| `model_artifacts` | `NONDETERMINISTIC_FIELDS` omitted the nested timestamp | manifest claimed a determinism it lacked |
| `model_handoff` | `horizon` passed twice | `TypeError` on the target-mismatch path |
| `model_handoff` | horizon not compared to the model's | 6h model answered `ready` for 24h |
| `model_handoff` | timestamp on every status | refusals carried a forecast timestamp |
| `model_audit` | entity check was a tautology | could never detect a mixed window |
| `model_audit` | label check never read the label | a split swap could pass |
| `model_audit` | indices not split-qualified | `3` rather than `train[3]` |
| `model_dataset.SequenceSet` | rows unaccounted for | the identity did not balance |
| `model_audit` | nothing-fitted reported `pass` | a check that ran nothing claimed success |
| `model_audit` | empty audit read as `FAIL` | nothing ran, which is not a leak |

---

## 22. What Phase 4 deliberately does not do

- **No forecast API or production endpoint.** The handoff is a contract.
- **No flood risk engine.** No risk score, no flood probability, no threshold
  policy. That is not this phase's work and there is no hydrology here to do it
  honestly.
- **No GIS, population or infrastructure impact.**
- **No sensor placement.**
- **No QUBO, QAOA or quantum anything.** Phase 4 is classical machine learning.
  No quantum advantage is claimed, because none is involved.
- **No frontend route integration.**
- **No deployment.**
- **No production database migration changes.**

---

## 23. Team boundaries

Files created by this phase, all inside Navya's ownership
(`ai-service/app/engines/hydro/` and Navya tests):

```
app/engines/hydro/model_config.py
app/engines/hydro/model_registry.py
app/engines/hydro/model_dataset.py
app/engines/hydro/model_evaluation.py
app/engines/hydro/model_audit.py
app/engines/hydro/model_training.py
app/engines/hydro/model_artifacts.py
app/engines/hydro/model_handoff.py
app/engines/hydro/PHASE4_MODEL_DEVELOPMENT.md
tests/hydro_phase4_fixtures.py
tests/test_hydro_model_registry.py
tests/test_hydro_model_config.py
tests/test_hydro_model_dataset.py
tests/test_hydro_model_evaluation.py
tests/test_hydro_model_audit.py
tests/test_hydro_model_training.py
tests/test_hydro_model_artifacts_handoff.py
```

Not touched: `ai-service/app/api/`,
`ai-service/app/services/forecast-sync/`, team schema and model files, team
backend/frontend contract files, migrations owned by other teammates, QUBO and
optimisation code, `quantum-service/`, GIS and IoT implementations, deployment
configuration, team tests, team requirements files, and `forecastingMergeupdate/`.

`features.py` was **not** modified for Phase 4's convenience. The legacy
`models.py` / `training.py` / `evaluation.py` layer is reused and wrapped, not
replaced, so the pre-Phase-1 path keeps working.

The only dependency file in the repository is
`ai-service/app/engines/hydro/requirements-hydro.txt`, which is Navya-owned, and
Phase 4 did not add to it.

---

## 24. Verified numbers, in one place

Fixture: 264 rows (132 h × 2 stations), 35 feature columns, target
`target_water_level_6h`, horizon 21600 s / label `6h`, units `m`, 6 cadences at
3600 s, splits 168/48/48, supervised 156/36/36 (228 total), `is_synthetic=True`.

```
registry          5 families, 2 available, 3 dependency-blocked
training run      5 runs, 2 trained, 3 dependency_unavailable
audit             PASS (8/8 with sequences configured)
scored splits     validation, test
baseline family   naive
selection         rmse on validation
comparison        10 rows (5 families x 2 splits)
manifests         5, of which 2 written and 3 not_written

naive             validation MAE 0.252724   test MAE 0.233840
random_forest     validation MAE 0.232386   test MAE 0.409215
                  validation better by 0.020, test worse by 0.175

sequence fixture  360 h, lookback 6, train_until 240, valid_until 300
                  480/120/120 rows, 458/96/96 windows
```

Full suite: **1506 passed, 2 skipped.**

---

## 25. Known limitations

- **Three of five families cannot run here.** xgboost, LSTM and GRU are
  implemented and blocked on absent dependencies. Their adapters have never been
  executed against a working library, so their correctness is unverified — the
  blocker check, the status propagation and the artifact states are tested, but
  no fit has occurred.
- **The dataset is generated.** 264 rows, two stations with a constant 3.0 m
  offset, a 6-hour horizon, no physics, no rating curve, no discharge, no
  rainfall realism. Nothing here supports a statement about a real river.
- **Validation and test have 24 scored rows each.** Enough to compute a metric,
  not enough for one to mean much. The disagreement between the two splits in
  §10 is itself evidence of that.
- **The forest overfits.** Its test bias equals its test MAE exactly. This is
  reported rather than tuned away.
- **No hydrological validation of any kind** — no gauge network, no station
  registry, no thresholds, no rating curves, no GIS or exposure data exists in
  this repository.
- **Migration `011_navya_hydro_observation_domains` cannot be validated** against
  a live PostgreSQL instance; it was reviewed statically only and needs a database
  owner.
- **Team integration seams are absent on this branch**, so backend and frontend
  type-level integration is unverified, and with no root `package.json` those
  TypeScript tests cannot run at all.

### The one-line version

Phase 4 fits two models on generated data, scores them against a persistence
baseline on identical rows, records everything it did in machine-readable form,
and hands Phase 5 a contract. The forest beats the baseline on validation and
loses to it on test. Three families are dependency-blocked. Nothing here is
production-ready and nothing here has been validated against a river.