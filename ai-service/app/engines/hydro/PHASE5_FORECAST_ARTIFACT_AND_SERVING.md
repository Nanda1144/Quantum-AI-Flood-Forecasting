# Phase 5 - Forecast Artifact & Serving Integration

Owner: Navya (`ai-service/app/engines/hydro/`) · Branch: `feature/navya-forecast`
· Predecessor: [`PHASE4_MODEL_DEVELOPMENT.md`](PHASE4_MODEL_DEVELOPMENT.md)

> **All data referenced in this phase is SYNTHETIC/DEMO.** The committed sample is
> generated. Nothing in this repository is a real hydrological observation, and
> nothing produced by this phase may be presented as one.
>
> The verbatim source disclaimer is carried by
> `datasets.SYNTHETIC_SAMPLE_PATH` and reproduced in every forecast result and every
> artifact this phase reads:
> `THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL
> HYDROLOGICAL OBSERVATION DATA.`
>
> **No forecast from this phase is production-ready, and none is claimed to be.**
> `production_ready_claimed` is permanently `False` in every artifact, every
> `ForecastInference` and every served result. A forecast was produced; that is all
> that means. Nothing here has been validated against a gauge network, a rating curve,
> a flood threshold, or any operational decision.

---

## 1. What Phase 5 is for

Phase 4 fitted models, scored them, audited them, and wrote manifests. It stopped at
the manifest on purpose: a file describing a model is not a model you can ask a
question. Phase 5 is the seam between the two.

```python
from app.engines.hydro.forecast_artifact import ArtifactStore, load_artifact_directory
from app.engines.hydro.forecast_inference import ForecastInput
from app.engines.hydro.forecast_serving import serve

store = ArtifactStore.from_directory("artifacts/")          # or from_manifests(...)
request = ForecastRequest.build(
    entity="SYNTHETIC-STATION-0001",
    target="target_water_level_6h",
    horizon="6h",
    origin_instant=datetime(2024, 1, 4, 5, tzinfo=timezone.utc),
)

served = serve(request, store=store, data=forecast_input, estimators=weights)
served.status          # 'ready'
served.inference.prediction
```

Four modules, all in `ai-service/app/engines/hydro/`:

| Module | Responsibility | Exports |
| --- | --- | --- |
| `forecast_artifact.py` | The artifact contract, the preprocessing record, the store, the loader | 37 |
| `forecast_selection.py` | Eligibility, deterministic ranking, the baseline comparison | 10 |
| `forecast_inference.py` | Input validation and the prediction rule | 23 |
| `forecast_serving.py` | The request-in / forecast-or-refusal-out boundary | 12 |

The ordering across those four modules *is* the design, and `forecast_serving` exists
mostly to hold that ordering in one readable function.

### Phase 5 does NOT

- fit, refit, or fine-tune anything, ever, during a request;
- expose an HTTP route, a handler, serialization, or persistence;
- fetch or rebuild features for an instant the caller did not name;
- substitute a different model than the one asked for, or the one selected;
- store fitted weights (Phase 4's weight-storage policy, unchanged);
- return zero, null, or a fallback number in place of a refusal;
- compute flood risk, flood probability, or a risk score;
- touch GIS, population, infrastructure, sensor placement, QUBO, QAOA, or quantum
  optimisation;
- install a missing dependency or edit a team-owned dependency manifest.

---

## 2. The artifact contract

`ForecastArtifact` is a frozen dataclass built from a Phase 4 `ArtifactManifest` plus
the fitted preprocessing record. Every field on it is a claim someone may act on, so
every field is either recorded or refused.

| Group | Fields |
| --- | --- |
| Identity | `artifact_id`, `model_id`, `model_family`, `model_version`, `role` |
| Versions | `artifact_schema_version`, `manifest_version`, `artifact_format_version`, `feature_contract_version`, `model_contract_version` |
| Problem | `target`, `target_units`, `horizon` |
| Features | `feature_names`, `declared_feature_count`, `feature_digest`, `fingerprint_digest` |
| Preprocessing | `scaler_policy`, `impute_policy`, `preprocessing` (+ derived `uses_trained_parameters`) |
| Splits | `split_policy`, `split_bounds`, `row_counts` |
| Evidence | `metrics_by_split`, `evaluation_status_by_split`, `hyperparameters`, `training_status`, `artifact_status`, `insufficiency` |
| Provenance | `provenance` (a Phase 1 `ProvenanceRecord` payload), `random_seed` |
| Honesty | `synthetic_demo`, `data_status`, `disclaimer`, `production_ready_claimed` |
| Weights | `weight_reference`, `weight_stored_in_repository` |
| State | `state`, `reason`, `dependency_versions` |
| Time | `created_at` |

`uses_trained_parameters` is a derived property rather than a field, because it is a
question about the family (`naive` reads only the target history) and a stored answer
would be a second opinion about the same thing.

Three of those deserve their own note.

**`artifact_id` is content-addressed.** It is
`<model_id>@<digest-prefix>`, so two runs that produce byte-identical metadata produce
the same id and a metadata change produces a different one. `model_id` alone would not
do: it names a model *slot*, not a model, and the whole point of an artifact is that a
caller can tell which one they were handed.

**`feature_digest` is over the ordered `feature_names`.** The order matters and is part
of what is hashed. A sorted digest would have been satisfied by a feature list shuffled
into the wrong positions, which is the same failure as a misaligned CSV: no error, a
plausible number, no way to tell afterwards.

**`reason` normalises `''` to `None`.** An empty string reads as "something was
recorded" in a rendered report, so it is stored as absent.

### Refusals at construction

`ForecastArtifact.__post_init__` raises rather than repairing: `ForecastArtifactError`
for an unusable shape, `ArtifactFamilyMismatchError` for a family the registry does
not define, `ArtifactMalformedError` for a missing required field,
`ArtifactContractMismatchError` for a declared feature count that disagrees with the
list, and `ArtifactContractMismatchError` again when the recorded
`feature_digest` does not equal `feature_digest(feature_names)`.

That last one is the reason the digest is worth having, and it is also why it is not
sufficient. A digest proves a file was not edited *after* it was written; it says
nothing about whether the content is right. A manifest rewritten consistently with a
leaky feature list passes the digest — which is why the checks in §7 are not
redundant with it.

---

## 3. Artifact states

Five states, and a deployment can always tell which one it is holding:

```python
state_counts(store)   # {'available': 2, 'dependency_blocked': 1, ...}
```

| State | Meaning | Can it serve? |
| --- | --- | --- |
| `available` | The artifact is internally consistent and servable as metadata | Yes |
| `dependency_blocked` | The family's library is not importable here | No |
| `artifact_missing` | Training did not write a manifest for this model | No |
| `invalid` | The artifact failed its own consistency checks | No |
| `not_evaluable` | It carries no validated evaluation result for any split | No |

`state` is derived, never stored as an independent opinion, and the derivation checks
`dependency_blocked` **before** it checks `artifact_status == not_written`. That order
matters: an xgboost run writes no manifest *because xgboost is not installed*, and
checking for the missing file first would report "no artifact" for a model whose
artifact was never written at all. The information is the same in both cases; the
remedy is not, and only one of them is fixable by installing a package.

`handoff_status_for_state` maps each state onto Phase 4's existing handoff status, so
there is one vocabulary for "why there is no value" rather than two. `available` maps
to `ready`, `dependency_blocked` to `dependency_unavailable`, `artifact_missing` to
`artifact_unavailable`, and `invalid` and `not_evaluable` both to `invalid_request` —
the handoff vocabulary has no separate word for "never evaluable". That collapse is
acceptable only because the exact state travels on the refusal itself
(`ServedForecast.artifact.state`), which is asserted in the tests.

### A dependency-blocked model is never faked

There is no code path that loads a blocked model, fabricates weights for it, quotes it
metrics from another family, or quietly substitutes a model that does work. Given a
blocked artifact, `serve` returns `dependency_unavailable` and a reason naming the
exact missing import.

---

## 4. Preprocessing at serving time

Phase 4's weight-storage policy keeps fitted parameters out of the repository. The
fitted scaler and imputer are fitted parameters, so a learned artifact read from a
directory carries its *policies* (`scaler_policy="standard"`,
`impute_policy="median"`) and no values. That is a real limitation of serving from a
manifest alone and is stated as such in §13.

The record itself is `PreprocessingSpec`: a frozen dataclass holding `feature_names`,
a `scaler` state and an `imputer` state, each carrying `kind`, `columns`, `fitted_on`
and `fitted_rows`.

**It exposes `transform` and nothing else.** No `fit`, no `fit_transform`, no
`partial_fit`. There is no route by which a serving request can refit the
transformation, which is the shape most preprocessing leakage takes.

**It refuses a record fitted on anything but the training split.** `fitted_on` is the
whole point of the field, so `__post_init__` raises `ArtifactPreprocessingMismatchError`
when it is anything other than `"train"`. A record *missing* `fitted_on` is refused
too: a record that cannot be shown to be train-only is not assumed to be.

**`require_preprocessing` refuses the identity-transform trap.** If the artifact's
recorded policies say a scaler or an imputer was fitted and no fitted record reached
the artifact, serving through an identity transform would hand a scaled model an
unscaled vector — the call would succeed and the number would mean nothing. The one
exemption is a family whose prediction rule reads nothing but the target history (the
persistence baseline): its manifest records the same policies as every other model
because they were fitted once for the shared feature matrix, but persistence never sees
that matrix, so there is nothing in it that a missing scaler could mis-scale. Refusing
the baseline there would leave no servable model at all in an environment where no
weights exist, and the failure it protects against cannot occur.

The record is attached with `ArtifactStore.with_preprocessing(...)`, which returns a
**new** store. `ArtifactStore` is frozen; the method that carries the fitted values
cannot mutate the store that does not have them.

---

## 5. Model selection

Selection is deterministic and uses validated evaluation results only. Nothing is
selected because it is newer, larger, or higher on a list.

```python
candidates = candidates_from_artifacts(store.artifacts, target=..., horizon=...)
decision = select_model(candidates, metric="rmse", split="validation")
```

**Eligibility first.** `candidates_from_artifacts` filters to artifacts that are
`available`, trained on the requested target and horizon, and carry a recorded metric
for the requested split. A dependency-blocked model is rejected on its state, and the
rejection reason reproduces the artifact's own recorded reason — including the exact
`ModuleNotFoundError` chain and the fact that the integration action is written down in
`01_Flood_Forecasting/TEAM_INTEGRATION_REQUIREMENTS.md`.

**The baseline is not a candidate.** The persistence baseline is the yardstick. A run
that selected it has learned that nothing beat "assume no change", which is a finding,
not a deployment target — so it is excluded from candidacy and its value is recorded
separately as the comparison.

**Metric direction is preserved.** This is the requirement most easily got wrong, so
it is worth being explicit about what Phase 5 owns versus what Phase 4 owns:

| | Owner | Content |
| --- | --- | --- |
| `direction_table()` | Phase 5 | reporting view: every metric including `bias` as `"unrankable"` |
| `metric_direction(m)` | Phase 4 | ranking view: raises `ModelEvaluationError` for `bias` |

`mae`, `rmse`, `peak_absolute_error` rank lower-is-better; `r2`, `nse` rank
higher-is-better. Ranking a higher-is-better metric as if it were lower-is-better does
not produce an error — it produces the *worst* model, confidently. `bias` is refused
outright rather than ranked, because there is no ordering on signed error that
generalises, and a plausible-looking wrong choice there is worse than no choice.

**Ties break on `model_id`.** Two artifacts with identical metric values are a real
possibility, and picking between them by anything other than a stable key would make
the result depend on dictionary order. `tied_model_ids` records the tie so a caller can
see that the choice between the tied models was not made on their merits.

**The reason is recorded, and it says when selection is not evidence.**

> `random_forest-target_water_level_6h-6h-seed20240917 was the only eligible candidate,
> so it was selected on rmse=0.273535 (lower is better) over the validation split.
> Being the only option is not evidence that it is any good; read its scores, not the
> fact of its selection. This is a ranking on synthetic/demo data and supports no claim
> about any real river.`

**The baseline comparison is preserved verbatim**, including when it is unflattering:

> `the selected model beat the persistence baseline on rmse by 0.0387856 (baseline
> 0.312321, selected 0.273535) on this split`

When the comparison cannot be made — the baseline has no value for that metric and
split — `beats_baseline` is `None` rather than `True`. The three states are distinct:
beat it, fail to beat it, and cannot tell are three different statements about a model,
and collapsing the third into the first would be the most flattering possible bug.

### What selection does with an empty candidate set

It refuses, and the refusal explains what the store *does* hold. "no eligible
candidates" is true and useless on its own: a store holding three artifacts, all
trained at `6h`, being asked for `24h` needs a longer-horizon model trained, while an
empty store needs the artifact directory pointed at. The inventory is reported
alongside the refusal.

### `nse` is rankable but not recorded

A concrete, verified illustration of the two separate questions. `metric_direction("nse")`
returns `"higher"`, so ranking is well-defined — but Phase 4's fixture records only
`['bias', 'mae', 'r2', 'rmse']`, so no candidate carries an `nse` value and selection
returns no model, with each rejection naming the metric that is absent:

> `'nse' is not present in the recorded 'validation' metrics ['bias', 'mae', 'r2', 'rmse']`

Refusing to rank on an absent number is the whole point. Filling it in — with a
default, with the test-split value, with the metric computed at serving time from data
the model was not selected on — would each be a different fabrication.

---

## 6. The inference boundary

`ForecastInput` is the caller's data as a validated object. It holds `entity`,
`origin_instant`, the parallel triple `feature_names` / `values` / `feature_instants`,
and `target_history` of `TargetObservation`. Three constructors —
`from_sequence`, `from_mapping`, and the dataclass initialiser — all coerce to the same
shape, and type coercion happens at construction rather than at prediction, so a bad
value cannot sit in a "valid" object waiting for a later failure.

`serving_contract_description()["validation_order"]` is the contract, in order:

```text
resolve artifact
check family / target / horizon
require servable state
validate feature names, order and types
check causality and entity
predict
express in the Phase 4 handoff and the platform forecast output
```

Each step can refuse, and the ordering decides which refusal a caller sees. Resolving
the artifact first means a blocked family reports `dependency_unavailable` rather than
complaining that a feature vector was missing for a model that will never run.

### What is validated

- **Required features present.** The refusal names the missing column.
- **Ordering.** A position-by-position comparison, and the refusal names the first
  disagreement and both column names.
- **Types and finiteness.** A non-numeric value is a `FeatureTypeError`. `NaN` is
  imputable and passes; `inf` is not a measurement anything produced, so it is a
  `NonFiniteFeatureError`. That asymmetry is deliberate — `NaN` means "no reading",
  which the imputer handles, and `inf` means the value is corrupt.
- **Vector length** against the artifact, not against the batch — a model with 35
  coefficients and a 34-element vector would raise inside the estimator in a way that
  depends on the estimator.
- **One column too many is reported as extra, not as missing.** Reporting "one column
  missing" when the caller supplied one too many sends them to remove a column they had
  not added.
- **Entity / station identity.** `check_entity` compares the request's entity to the
  input's and raises `EntityMismatchError` naming both.
- **Timestamp.** `check_causal` requires every feature instant to be at or before the
  origin, and refuses a *partial* instant list — an unchecked feature is exactly the
  one that leaks.
- **Horizon** against the artifact.
- **Model compatibility** — family, target, horizon, feature contract version.

### The result

`ForecastInference` carries `prediction`, `origin_instant`, `prediction_timestamp`,
`carried_from_instant`, `entity`, `target`, `target_units`, `horizon`, `model_id`,
`model_family`, `model_version`, `artifact_id`, `strategy`, `feature_version`,
`feature_count`, `feature_digest`, `imputed_features`, `preprocessing_applied`,
`uncertainty`, `synthetic_demo`, `data_status`, `disclaimer` and
`production_ready_claimed`.

`imputed_features` is not cosmetic. An imputation is an assertion that a value was
*not* observed and was filled in, and a reader of a forecast who does not know that
cannot weigh it. The count travels with the number.

`strategy` is `"persistence"` or `"estimator"`, which is what makes the baseline
distinguishable from a model in a result at all.

### Weights are the caller's to supply

```python
serve(request, store=store, data=data, estimators={"<model_id>": fitted})
```

Phase 4's weight policy keeps those bytes out of the repository, so `serve` cannot load
them and does not try. A missing entry is `artifact_unavailable` with
`EstimatorUnavailableError` naming the model — never a fallback to a model that does
have weights. Falling back would return a number from a model nobody asked for, and the
result would still carry a `status` of `ready`.

The baseline is servable from a manifest and a target history with nothing loaded. That
is not a convenience: it is the only path to `available` that is exercisable in an
environment where no weights exist, and the tests use it as such.

---

## 7. Temporal safety at the serving boundary

Phase 4 audits the dataset once, when it is built. A serving boundary has its own ways
to leak that a dataset audit cannot see, so `test_hydro_forecast_leakage.py` asks the
questions a dataset audit does not answer.

| Concern | How it is enforced | How it is tested |
| --- | --- | --- |
| Target leakage | No artifact's `feature_names` contains its own target, or the predicted quantity un-prefixed | The check, plus a *forged but internally consistent* artifact whose feature list contains the target — refused, with the digest recomputed first so the refusal is about the leak rather than the checksum |
| A poisoned input | The model reads features, not the target | Every water-level-derived column set to `9999.0`; the forecast must remain a model prediction and must not become the poison |
| Future-derived preprocessing | `PreprocessingSpec.__post_init__` requires `fitted_on == "train"` | Forged `fitted_on` of `validation`, `test`, `all` and `""`, on the scaler and the imputer, each refused with a message naming what was wrong; a record *missing* `fitted_on` refused; no `fit` on the object |
| Preprocessing saw only training rows | The recorded `fitted_rows` | Asserted equal to `row_counts["train"]` and strictly less than the whole series — an independent check against the artifact's own numbers, not a restatement of the audit's finding |
| Recorded means are what is used | The transform subtracts the artifact's means | The forecast changes when the recorded means change, and does not become zero for an all-zero vector |
| Train/val/test contamination | Split bounds and row counts travel on the artifact | Bounds partition the series with no overlap; an origin inside the training window is still served, and the comparison needed to detect that is one subtraction away |
| Invalid sequence windows | `check_causal` is non-partial | A read at `origin + 2h` refused through `serve` as a status, not an exception; a read exactly at the origin accepted — the boundary is inclusive on purpose and the two cases are asserted together so the line cannot move |
| Prediction instant | `origin + horizon` | Strictly after the origin, and exactly one `horizon_seconds(HORIZON)` after it, parsed through Phase 4's own exported function |
| Cross-station leakage | `check_entity` | Station B's request with station A's data refused, naming both stations; a frame holding both stations is *filtered* to the requested one, and the carried value is checked to be the requested station's |
| Tampered artifact | The digest | A renamed column with the digest left stale is refused, with both digests in the message; and a *consistently* recomputed digest loads cleanly, which is what proves the digest is necessary and not sufficient |
| Weight policy | `weight_stored_in_repository` | A manifest directory round-trip still refuses to serve a learned model, and says `artifact_unavailable` |

### The one place Phase 5 does not enforce station binding

An artifact trained on station A **will** serve a request for station B, and this is
deliberate. What happens is a *transfer*: the feature vector comes from station B's own
readings, and the artifact supplies only fitted parameters — a decision surface. No
station A reading reaches a forecast labelled station B, which is what "cross-station
leakage" means, and `check_entity` enforces exactly that.

What Phase 5 cannot do is judge whether a model fitted at one gauge is *valid* at
another. Nothing in Phase 4's manifest says so, and inventing a rule would be
inventing hydrological policy rather than serving it. So the artifact records the
station it was fitted on — `provenance["station_reference"]`, carried by the Phase 1
`ProvenanceRecord` — and a cross-station deployment is a decision a reader can see
rather than a silent one. Stated as a limitation in §13, and pinned by a test that
asserts both halves: the station is recorded, and it is not enforced.

---

## 8. Provenance and the disclaimer

There is one provenance system. Phase 5 reads Phase 1's `ProvenanceRecord` and does not
define a competing model.

The record is **authoritative for the data status**. `parse_artifact` *derives*
`synthetic_demo`, `data_status` and `disclaimer` from the `ProvenanceRecord.dataset_type`
when a record is present, with the record winning over the manifest's own triple; it
falls back to the manifest fields only when no record exists. A `DataStatus` the
platform does not define is refused rather than coerced into one that it does.

The exact disclaimer string travels with the result. It appears in:

- `ForecastArtifact.disclaimer`
- `ForecastInference.disclaimer`, and in `ForecastInference.describe()`
- `ServedForecast`'s `forecast` block, and in `ServedForecast.describe()` — including
  when the result is a refusal and an artifact is present but no inference exists, which
  is the case where a reader is most likely to be looking at a status and least likely
  to look for the data caveat
- `SelectionDecision`, appended to the selection reason when `synthetic_demo` is true
- `serving_contract_description()["data_status_statement"]`

`production_ready_claimed` is `False` on every path. It is not a flag anyone can set;
there is no code that sets it to anything else.

---

## 9. Determinism

Identical artifact + identical input + identical config ⇒ identical forecast value and
identical decision-relevant metadata. Nothing in the serving path reads a clock, a
random source, or the environment:

- `forecast_id` is derived from the request's fields — entity, target, horizon, origin
  instant, model id — not from `uuid4()` and not from a clock. Two identical requests
  produce the same id, which is what makes a log line correlatable across a retry.
- Selection sorts by `(metric value, model_id)`. Never by set or dict iteration order.
- `serve` takes no hidden state. Module-level names are constants and pure functions;
  there is no cache, no memo, and no global that a test cannot reset.
- A `RunResult` supplied at serving time changes the *handoff*, not the forecast. There
  is a test for exactly this, because if `serve` reached into the run for weights then
  the same artifact plus the same input could answer differently depending on whether
  the caller happened to pass one — which would make the artifact an incomplete
  statement of what produced the number.
- `serve_many` preserves the caller's order rather than sorting, and serves each request
  independently: one refusal does not stop a batch, because a batch that aborted would
  report fewer forecasts than were asked for without saying why.

---

## 10. Statuses and structured errors

`SERVING_STATUSES` is Phase 4's handoff vocabulary, unchanged:

```text
ready  invalid_request  dependency_unavailable  insufficient_data
target_unavailable  artifact_unavailable  model_unavailable  no_prediction
```

Every non-`ready` status names its cause in `reason`, and `prediction` is `None` on all
of them. There is no code path that returns a value alongside a failure: a caller that
checks the status is not the only reader, and the one who reads only the number is
exactly the one this pipeline would mislead.

`status_for_error` walks a fixed, ordered table. `ForecastInferenceError` is a
superclass of every input error, so the general entry has to come last or the specific
entries would be unreachable — hence a tuple rather than a dict keyed by class. An
error with no entry raises `ForecastServiceError` rather than being defaulted; giving
`KeyError` the status `invalid_request` would file a server bug as the caller's fault,
and the caller would go looking for a malformed request that does not exist. A test
walks the whole `ForecastArtifactError` and `ForecastInferenceError` hierarchies and
asserts every subclass resolves, so a new error cannot be added without someone
deciding what a caller sees.

`DependencyBlockedError` is deliberately **not** a subclass of `ArtifactMissingError`.
The two look alike to an operator — "I asked for xgboost and got nothing" — and they
call for opposite responses: a missing artifact means the training run wrote no
manifest, while a blocked one means the manifest is on disk and cannot be executed.
Collapsing them sends whoever is on call to the wrong place, and it does so quietly,
because the refusal still reads as a refusal either way.

### When Phase 5 refuses rather than downgrading

If a caller asks for `random_forest` and no weights are supplied, the answer is
`artifact_unavailable`. It is not the baseline. The baseline *would* have answered, it
would have been a plausible number with the right units at the right instant, and
nothing in the result would have said it was not the model that was asked for. That is
the specific failure Phase 5 exists to make impossible.

The same rule applies to the family selector. `serve` honours
`request.model_family` — a real Phase 4 selector that Phase 5 was initially ignoring:

- exactly one match ⇒ use it;
- zero matches ⇒ `artifact_unavailable`, listing the inventory;
- several matches ⇒ refused as ambiguous, saying the family "does not identify one"
  and asking for the `model_id` instead.

In every case `decision` stays `None` for an explicit selector. An explicit request is
never overridden by selection: a caller who asked for a family is entitled to that
family, and quietly substituting a better-scoring one would make the served model
unnameable in the caller's own logs.

---

## 11. The handoff and the platform forecast output

`ServedForecast` is Phase 5's own answer: it works from a loaded artifact alone, which
is what a deployment has. When a Phase 4 `RunResult` happens to be in scope, the same
prediction is *also* expressed as Phase 4's `HandoffResult` and then as the platform's
`contract.ForecastOutput`, so existing consumers read it without a second format.

Neither is required, and neither is faked when absent.

The handoff is handed the *resolved* request — `model_id` only, no family — so Phase 4
cannot disagree with Phase 5 about which model answered. `prediction_timestamp` comes
from the handoff when present, and is otherwise computed through Phase 4's own exported
`horizon_seconds`, made public for exactly this. A second parser in Phase 5 would be a
second thing that can disagree about what `6h` means.

If the handoff refuses — most plausibly because no manifest bundle was supplied, since
Phase 4 uses it to report artifact status and Phase 5 does not synthesise one — the
refusal is reported rather than papered over. The caller sees `ready` with no timestamp:
there is a value, and there is no instant to say it is about.

### `ServedForecast.to_dict()`

```text
serving_contract_version  forecast_id        request   status    reason
state        artifact_id  selection    prediction    prediction_timestamp
forecast     handoff      forecast_output
```

The `forecast` block carries the full inference, including `strategy`, `origin_instant`,
`carried_from_instant`, `feature_digest`, `imputed_features`, `preprocessing_applied`,
`synthetic_demo`, `data_status`, `disclaimer` and `production_ready_claimed` — so a
consumer reading only the serialized form still sees the data status.

`default_forecast_id` is exported so a caller generating its own batch ids can match
Phase 5's derivation exactly.

---

## 12. Tests

Six Phase 5 modules, 274 tests, all passing:

| Module | Tests | Covers |
| --- | --- | --- |
| `test_hydro_forecast_artifact.py` | 69 | The contract, construction refusals, the digest, the store, the loader, the directory round trip, the index |
| `test_hydro_forecast_selection.py` | 42 | Eligibility, direction, ties, the baseline comparison, rejection reasons |
| `test_hydro_forecast_inference.py` | 55 | Every validation, the prediction rule, the persistence baseline, the preprocessing transform |
| `test_hydro_forecast_serving.py` | 47 | Statuses, the selectors, determinism, the handoff, `serve_many` |
| `test_hydro_forecast_provenance.py` | 28 | The record, the disclaimer, data-status derivation, the readiness claim |
| `test_hydro_forecast_leakage.py` | 33 | §7 |
| `hydro_phase5_fixtures.py` | — | Shared fixtures, plus `FittingGuard` / `no_fitting` |

`FittingGuard` is worth mentioning because it is the only way the "training and
inference are separate" requirement is actually *tested* rather than asserted in a
docstring. It snapshots every fitted-estimator attribute in the process, runs a
serving request, and fails if any of them changed — and it dispatches on
`inspect.ismodule` so it catches an inherited `RandomForestRegressor.fit` as well as an
own-attribute `fit`, and restores the snapshots in reverse order on the way out.

Every skip has a documented reason. Phase 5 adds none; the two in the suite are both
pre-existing Phase 1–4:

- `test_hydro_engine_contract.py:46` — requires the team seam (`app/schemas/models.py`,
  `app/engines/base.py`, `app/engines/factory.py`); those files are team-owned and are
  not present on this branch. Runs after the integration merge.
- `test_hydro_model_artifacts_handoff.py:1975` — the run result does not carry the
  Phase 3 report.

XGBoost, Keras/TensorFlow and PyTorch remain unavailable on this branch (Python 3.13.5;
numpy 2.5.1, pandas 3.0.3, scikit-learn 1.9.1, scipy 1.18.1, joblib 1.6.0,
pytest 9.1.1). Those families stay optional adapters and are exercised through their
dependency-blocked path, which is itself tested. The manifests recording them are
team-owned and were not edited; the integration action is written down in
`01_Flood_Forecasting/TEAM_INTEGRATION_REQUIREMENTS.md`. **This needs a dependency
owner.**

---

## 13. Source defects found and fixed

Phase 5 found six real defects in code it inherited. All are fixed; the fixes are
listed because a fix with no explanation is a change nobody can review.

### In Phase 4

**1. `LOWER_IS_BETTER` contained `nse`.** NSE is Nash–Sutcliffe efficiency, where
higher is better. Listing it among the lower-is-better metrics inverted its ranking.

**2. `_select` always sorted ascending.** With `r2` in the metric set and ascending
order, the *lowest* R² won. This is the dangerous class of bug: it produces a number,
not an exception, and the number is plausible. Fixed by adding `HIGHER_IS_BETTER`,
`metric_direction()`, `METRIC_DIRECTIONS`, a direction branch in `_select`, and a
`model_id` tie-break so the winner does not depend on input order.

**3. `model_artifacts.py` omitted ordered `feature_columns` from both
`to_canonical()`s, and stored `sorted(feature_columns)` in the digest.** So the digest
did not actually depend on feature order, which is the property the digest exists for.
Fixed; `ARTIFACT_MANIFEST_VERSION` bumped to `"navya-phase4-manifest/v2"` with
`LEGACY_MANIFEST_VERSION = "navya-phase4-manifest/v1"` still readable.

### In Phase 5, found by the tests

**4. `_rank_key` negation inverted lower-is-better ranking.** It took `ranked[0]`, which
under the inverted key was the *worst* model.

**5. The unrankable-metric guard leaked `bias` to `ModelEvaluationError`.** It was
checking membership in the wrong direction, so an unrankable metric reached the
ranking code. Now `METRIC_DIRECTIONS.get(metric) not in ("lower", "higher")`.

**6. `tied_model_ids` included the winner.** So "these models tied" listed the model
that was selected, which is not a tie.

**7. `DependencyBlockedError` did not exist**, and `dependency_blocked` and
`artifact_missing` both raised `ArtifactMissingError` — so a blocked family reported
`artifact_unavailable` while the module docstring promised
`dependency_unavailable`. The docstring described the intended behaviour and the code
did not implement it. Fixed, and the error→status table now puts the dependency entry
first so no future subclass relationship can hide it.

Eight further inference defects were found and fixed while writing
`test_hydro_forecast_inference.py`: a `FittingGuard` that missed inherited `fit`
methods; `NaN` and `inf` treated identically; `FeatureOrderError` and
`MissingFeatureError` messages that did not name the offending columns;
`require_preprocessing` refusing the baseline; `check_against` reporting extras as
missing; Phase 4's `horizon_seconds` returning a span for a non-positive horizon; and a
missing disclaimer line in `ForecastInference.describe()`.

---

## 14. Verified numbers, in one place

All from the committed synthetic fixture, seed `20240917`, target
`target_water_level_6h`, horizon `6h`, origin `2024-01-04T05:00:00+00:00`. **Every one
of these is synthetic/demo output and supports no claim about any real river.**

Validation-split metrics, from the recorded manifests:

| Family | rmse | mae | r2 | State |
| --- | --- | --- | --- | --- |
| `naive` (persistence) | 0.312321 | 0.252724 | 0.957248 | `available` |
| `random_forest` | 0.273535 | 0.232386 | 0.967207 | `available` |
| `xgboost` | — | — | — | `dependency_blocked` |

The forest beats the baseline on all three, which is recorded rather than asserted
elsewhere: `beats_baseline=True`, margin `0.0387856` on rmse.

Selection on the same store:

| Metric | Selected | Beats baseline | Note |
| --- | --- | --- | --- |
| `rmse` | `random_forest` | `True` | margin `0.0387856` |
| `mae` | `random_forest` | `True` | |
| `r2` | `random_forest` | `True` | margin `0.00995895` |
| `nse` | *none* | `None` | rankable, but not recorded by Phase 4 on this fixture |
| `bias` | *refused* | — | `ModelEvaluationError`: not rankable |

Served forecasts at the origin above:

| Request | Status | Prediction | Strategy |
| --- | --- | --- | --- |
| family `naive` | `ready` | `2.7954458166615406` | `persistence` |
| family `random_forest` | `ready` | `3.2393323679390944` | `estimator` |
| family `xgboost` | `dependency_unavailable` | — | — |
| family `random_forest`, no weights | `artifact_unavailable` | — | — |

Both ready results carry `synthetic_demo=True`, `data_status="synthetic_demo"`,
`production_ready_claimed=False`, the exact disclaimer, and
`prediction_timestamp = 2024-01-04T11:00:00Z`.

Artifact states for the fixture store: `{'available': 2, 'dependency_blocked': 1}`.

Test counts:

| Suite | Result |
| --- | --- |
| Phase 5 (6 modules) | 274 passed |
| Phase 1–4 hydro regression (32 modules) | 1507 passed, 2 skipped |
| Full `tests/` suite | 1781 passed, 2 skipped |

The Phase 1–4 regression is unchanged from its pre-Phase-5 baseline of 1507 passed /
2 skipped, and the full suite is exactly baseline + the 274 Phase 5 tests, with no
new skips and no failures.

---

## 15. Known limitations

**A learned model cannot be served from a manifest directory alone.** The fitted
scaler and imputer are fitted parameters, and Phase 4's weight-storage policy keeps
fitted parameters out of the repository. A deployment must supply them itself, via
`ArtifactStore.with_preprocessing(...)`. The baseline needs nothing and is the
testable `available` path; the forest and xgboost do.

**Cross-station transfer is not enforced.** An artifact trained at one gauge will serve
another, and the artifact records the station it was fitted on so the deployment is
visible rather than silent. Phase 5 has no basis for refusing, because nothing in Phase
4's manifest says whether a model is valid at another station. See §7.

**No fitted weights exist anywhere in this repository**, so no artifact in it can
produce a learned forecast on its own. `production_ready_claimed` is permanently
`False`.

**Correctness is only validatable on synthetic/demo data.** There is no real gauge
network, no discharge, inflow, temperature or humidity observation, no station
registry, no threshold, no rating curve, no GIS and no exposure data. Every number in
§14 is a statement about a pipeline on generated data, not about any river.

**`serve` is a function, not a service.** No route, no handler, no serialization, no
persistence, no authentication. Who calls it and how is a deployment decision for
whoever owns the service layer.

**Migration `011_navya_hydro_observation_domains.*.sql` is unvalidated against a live
PostgreSQL instance.** Recorded as `DB-MIG-02`. **This needs a database owner.**

**The team integration seams are absent on this branch**, so the backend and frontend
TypeScript contracts cannot be type-checked against this implementation:

```text
ai-service/app/schemas/models.py        ai-service/app/engines/base.py
ai-service/app/engines/factory.py       ai-service/requirements.txt
backend/src/types/contract.ts           backend/src/types/optimization.ts
backend/package.json                    frontend/src/types/ai.ts
frontend/src/services/aiService.ts      frontend/src/App.tsx
frontend/package.json                   docs/navya-forecast/
```

---

## 16. Team boundaries

Modified, all within `ai-service/app/engines/hydro/` and `ai-service/tests/`:

```text
forecast_artifact.py    forecast_selection.py
forecast_inference.py   forecast_serving.py
PHASE5_FORECAST_ARTIFACT_AND_SERVING.md

model_artifacts.py   model_evaluation.py   model_handoff.py   (Phase 4 defect fixes)

hydro_phase5_fixtures.py
test_hydro_forecast_artifact.py     test_hydro_forecast_selection.py
test_hydro_forecast_inference.py    test_hydro_forecast_serving.py
test_hydro_forecast_provenance.py   test_hydro_forecast_leakage.py
```

`model_artifacts.py`, `model_evaluation.py` and `model_handoff.py` are Phase 4 modules
that Navya owns, changed only for the three defects in §13.

`features.py` was **not** touched. GIS, IoT, the quantum service, QUBO and the
optimization layer, deployment infrastructure, `.github/`, team-owned tests, and the
team-owned dependency manifests were **not** touched. `forecastingMergeupdate/` and
`forcastingMergeupdate/` were **not** touched.

### The one-line version

Phase 5 can serve a forecast or it can refuse with a name, and on synthetic data with
no production-readiness claim anywhere in the result — which learned models need
weights the repository does not hold, and which is the honest state of a forecasting
engine that has not met a river yet.