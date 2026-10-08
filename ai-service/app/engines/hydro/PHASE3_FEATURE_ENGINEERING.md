# Phase 3 - Feature Engineering & Forecast-Ready Feature Datasets

Owner: forecasting module (`ai-service/app/engines/hydro/`) · Branch: `feature/forecast`
· Predecessor: [`PHASE2_PREPROCESSING.md`](PHASE2_PREPROCESSING.md)

> **All data referenced in this phase is SYNTHETIC/DEMO.** The committed sample is
> generated. Nothing in this repository is a real hydrological observation, and
> nothing produced by this phase may be presented as one.
>
> The verbatim source disclaimer is carried verbatim by
> `datasets.SYNTHETIC_SAMPLE_PATH` and reproduced in every report:
> `THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL
> HYDROLOGICAL OBSERVATION DATA.` Features derived from it remain labelled
> synthetic throughout, including in `FeatureRow.to_dict()` output.

---

## 1. What Phase 3 is for

Phase 1 established what a hydrological record *is*. Phase 2 established what a
clean, chronologically split, unit-consistent dataset *looks like*. Phase 3 turns
that dataset into columns a forecasting model can be fitted on — and, just as
importantly, into a dataset in which **every column is a function of the past**.

```python
from app.engines.hydro import preprocess, build_features

pre = preprocess(records)
result = build_features(pre, FeatureConfig())

result.dataset.feature_columns   # 56 names, in registry order
result.dataset.rows              # one row per (entity, origin instant)
result.report.describe()
result.contract.to_dict()        # the Phase 4 contract
```

The design principle throughout: **Phase 3 never invents a value to make a
matrix tidier.** Every feature is either computed from observations at or before
its own prediction instant, or it is absent with a recorded reason. There is no
third category.

### PHASE 3 DOES NOT TRAIN MODELS

Stated plainly, and enforced by tests:

- no model is selected, fitted, tuned or evaluated;
- no RMSE, MAE, R², accuracy or information criterion is computed or reported;
- no scaler, imputer or encoder is fitted on these rows;
- no algorithm is named as a recommendation.

Fitting an imputer belongs to Phase 4, **after** the split, on training rows only.
Fitting one here — even on the whole dataset — would put test-period statistics
into the model's inputs, which is the same class of error as training on the test
split.

### Relationship to `features.py`

`app/engines/hydro/features.py` is the pre-Phase-1 wide-`DataFrame` feature layer
consumed by `training.py`, `engine.py`, `tests/test_hydro_features.py` and
`tests/test_hydro_leakage.py`. **Phase 3 does not modify, replace or deprecate
it.** The two coexist:

| | `features.py` | Phase 3 (`feature_*.py`) |
| --- | --- | --- |
| Shape | Wide `DataFrame` | Narrow `Observation` records |
| Dependencies | NumPy, pandas | Standard library only |
| Window convention | `shift(1).rolling(w)` | `(cutoff - w, cutoff]` |
| Coverage rule | Not asserted | `accumulation_min_coverage`, `rolling_min_coverage` |
| Missing values | Imputed downstream | Preserved, with a reason |
| Lineage | None | Per feature and per target |
| Leakage evidence | Test-only assertions | 8 runtime checks + behavioural deletion probe |

Both are covered by the full suite. Neither is allowed to regress the other.

### The four modules

| Module | Lines | Responsibility |
| --- | --- | --- |
| `feature_registry.py` | 1006 | The vocabulary: definitions, naming, scopes, lineage, and the catalogue of features that cannot honestly be built. |
| `feature_config.py` | 764 | Every policy, its default, and the rules that refuse a configuration. |
| `feature_temporal.py` | 931 | Causal window arithmetic. One dispatch point. |
| `feature_pipeline.py` | 1986 | The orchestrator, the quality report, the leakage audit and the Phase 4 contract. |

Like Phases 1 and 2, all four import **nothing outside the standard library**. The
purity claim is verified with `ast` rather than by inspecting `sys.modules`,
because importing any `hydro` submodule runs the package `__init__`, which
already loads NumPy through the pre-Phase-1 `synthetic` generator — a runtime
check would flag that pre-existing behaviour as a Phase 3 regression.

---

## 2. The feature registry

### One definition per column

A feature is declared once, as a `FeatureDefinition`, and the declaration is the
authority for its name, source, operation, window, unit, scope and lineage.
Nothing downstream may recompute any of those. The registry refuses to compile a
definition that is incomplete: `__post_init__` checks the operation, the entity
scope, the availability requirement, and the operation-specific combinations
(a rolling feature with no statistic, a calendar feature with a non-`global`
scope), and raises rather than emitting a column whose meaning is ambiguous.

Column order is **registry order** — an ordered tuple, never a `dict`, `set` or
AST-visit order — so `dataset.feature_columns == dataset.registry.names` always
holds and is asserted.

### Naming is deterministic and never positional

```
rainfall_lag_1h          rainfall_change_3h       rainfall_rolling_mean_6h
rainfall_accum_3h        rainfall_accum_24h       rainfall_intensity_3h
water_level_lag_1h       water_level_change_1h    water_level_rolling_max_6h
calendar_hour_sin        calendar_doy_cos
```

Every name is built from declared fields only. No name contains a row index, a
random identifier, a timestamp or `id()`. `window_label` prefers hours and falls
back cleanly — 86400 s is `24h`, 604800 s is `168h`, never `1w`, because the
first form is unambiguous and the second is a unit change at a threshold.

### Three-level measurement keys

`measurement_key(record)` is `location|domain|quantity`; Phase 2's two-level
`series_key` (`location|domain`) is too coarse to keep a rainfall lag off a water
level. Both quantities live at one station on the same instants, so nothing but the
key stands between them.

```python
"G1|rainfall|rainfall"        # rainfall at G1
"G1|water_level|water_level"  # water level at G1 — a different series entirely
```

### Entity scope

| Scope | Reaches | Used by |
| --- | --- | --- |
| `measurement` | One `location\|domain\|quantity` series | **Every** temporal feature |
| `entity` | One location, all of its quantities | Reserved — no built feature needs it |
| `global` | The timestamp alone | Calendar terms |

`measurement` is narrower than isolation strictly requires, and that is the
point: it is narrower than it needs to be. No feature reads across quantities, so
a rainfall lag cannot become a water-level lag by accident. The `entity` scope
exists in the vocabulary and is unused, and a test asserts it stays unused.

### Lineage

Every feature carries a `Lineage` naming its source domain, source quantity,
window, statistic, unit and the observations it is derived from. Every **target**
carries a `TargetLineage` with `available_at_prediction_time=False` recorded
explicitly, because that is the single fact a consumer of the Phase 4 contract most
needs and the one least visible from a column name.

---

## 3. Point-in-time correctness

**This is the requirement Phase 3 exists to satisfy.** `Feature(T)` depends only
on observations at or before `T`. No future value, no future aggregate, no future
rolling window, no future imputation, no target.

### Structural enforcement

Every operation is a slice ending at a **cutoff** that is never later than the
origin. There is no code path that can read forward, because `resolve_cutoff` is
the only thing that produces a cutoff and it is checked in one place.

### Does the rolling window include `T`?

**Yes, and this is stated rather than left to be inferred.**

Accumulation and rolling windows are `(cutoff - window, cutoff]` — **open on the
left, closed on the right**. The reading stamped exactly at `cutoff` is inside the
window; the reading stamped exactly at `cutoff - window` is not.

Two consequences worth being explicit about:

- A window of width `w` at base cadence `b` holds exactly `w/b` readings. This is
  what makes coverage assessable.
- It agrees with `pandas.Series.rolling(w)` slot for slot. This is verified in the
  test suite against a `pandas.Series` built independently of this codebase, for
  every window width and every origin in a 48-hour series, not a hand-picked few.
  One agreeing value shows the arithmetic works; agreeing on all of them shows the
  boundary is in the same place throughout, which is where a window convention
  actually goes wrong.

`op_change` is the exception and uses an explicit instant pair
(`value(cutoff) - value(cutoff - span)`), because a difference is defined at two
points rather than over an interval.

### Warm-up decided by slots, not by edges

A series whose first reading sits *after* a window's left edge is often still fine:
a 6-hour window ending at 05:00 on hourly data starts at 23:00 the previous day,
but its six hourly slots land on 00:00–05:00, every one of them observed.

Warm-up is therefore decided by **what the window actually holds**, not by
comparing the window edge to the series start. The second test is simpler and is
wrong twice: it rejects a window that is already full, and it reports
`observations=0` for a window that plainly holds readings. An earlier draft of this
code made exactly that mistake and discarded one complete accumulation per series
per window width.

The exact warm-up counts on the committed sample:

| Feature | Warm-up rows | Why |
| --- | --- | --- |
| `rainfall_accum_24h` | 23 | The first complete 24-slot window ends at hour 23. |
| `rainfall_intensity_3h` | 2 | The first complete 3-slot window ends at hour 2. |
| `water_level_lag_1h` | 1 | The `one_step_back` cutoff steps once more, reaching past the first reading. |

### Cutoffs by quantity class

| Class | Quantities | Policy | Meaning |
| --- | --- | --- | --- |
| Forcing | `rainfall`, `temperature`, `humidity` | `at_prediction_instant` | Observed at `T`, so reading it is not leakage. |
| State | `water_level`, `discharge`, `inflow` | `one_step_back` | `T` is what is being predicted; read `T - 1`. |

`strict_causality=True` collapses both to `one_step_back`.

### The unknown-cadence fallback, which differs by class

With no established cadence there is no "one step back" to go to, and guessing
one — the usual answer being an hour — would be inventing a quantity out of a
convention. So each class falls back to something already known:

- a **forcing** falls back to `origin`, which is conservative in the causal
  direction: it can only ever read less, never more;
- a **state** falls back to `previous_instant` — the newest reading strictly
  before the origin, supplied by the caller from the series itself.

The second branch is not a refinement. Falling back to `origin` for a state would
put the water level at `T` inside a window labelled "the mean level over the six
hours before `T`" — the quantity being predicted, wearing a feature's name. When
there is no earlier reading either, the feature is **absent**
(`cutoff_undefined`) rather than evaluated. There is no correct value there, only
a wrong one.

This was found by `audit_point_in_time`, which truncates the data at each origin
and watches for a feature that changes. A truncated series has no resolvable
cadence, so that is precisely the branch it exercised.

---

## 4. Target alignment

`target = value(T + H)`. Features use `<= T`. The two are separated structurally:
each `FeatureRow` carries `values`, `targets`, `absent_reasons`, `target_instants`
and `source_instants` as distinct fields, and `feature_matrix()` cannot reach a
target.

| Alignment | Behaviour |
| --- | --- |
| `exact` (default) | The reading at exactly `T + H`, or absent. |
| `at_or_before` | The newest reading at or before `T + H` **within `target_tolerance_seconds`**. Requires that tolerance to be named; configuring the alignment without it raises. |

`at_or_before` exists because some real series are irregularly sampled. The
tolerance is a bound on how wrong the instant may be, not a licence to take
whatever reading is nearest — a reading 5 hours early is not a 6-hour-ahead
forecast, and Phase 3 refuses rather than quietly approximating.

Multi-horizon targets each get their own column with its own explicit alignment.
No duplicated future information is reused across horizons.

A target past the end of the series is **absent, not clamped**. Clamping would put
the last observed value under a column that claims to be six hours ahead of
something — the quietest and worst version of target leakage.

### Targets and split boundaries

Rows are assigned to splits by their **origin** instant. A row whose *target*
instant falls in a different split has that target **withheld**: the row is
retained (the feature grid at that instant is real and a forecaster wants it) and
the target is set to `None`. On the committed sample that is 18 rows out of 2160,
reported as `FEATURE_TARGET_CROSSES_SPLIT`.

---

## 5. Features with no source

A feature is either computed or **declared unavailable with a reason**. An absent
column is invisible; a declared-unavailable column is a gap a reviewer can ask
about. The column exists, its value is `None`, and
`dataset.unavailable[name]` says why.

On the committed sample, **32 of 56 features are built**. The 24 that are not:
`discharge_*` (8), `temperature_*` (8) and `humidity_*` (8) — the sample carries
`water_level`, `inflow` and `rainfall` only. The message is explicit that no
substitute was invented.

### The unbuildable catalogue

Nine features Phase 3 will **not** build for any input, declared in
`UNAVAILABLE_STATIC_CATALOGUE`:

| Feature | Status | Why |
| --- | --- | --- |
| `static_elevation` | `no_source_series` | No elevation field exists in the repository. |
| `static_latitude` | `no_source_series` | Same. |
| `static_longitude` | `no_source_series` | Same. |
| `static_river_distance` | `no_source_series` | Same. |
| `static_basin_identifier` | `no_source_series` | No basin registry exists. |
| `static_catchment_area` | `no_source_series` | No catchment geometry exists. |
| `derived_discharge_from_water_level` | `no_approved_relationship` | Would need a rating curve. None exists. |
| `derived_inflow_from_rainfall` | `no_approved_relationship` | No infiltration or catchment-response relationship is established. |
| `derived_water_level_datum_offset` | `no_approved_relationship` | Datum compatibility between gauges is unverified. |

The rating-curve entry is the important one. Inferred discharge from a water level
would look exactly like data and would be a fabrication. It is **declared**, so a
reader learns the capability is deliberately absent rather than merely missing.
`UNAVAILABLE_STATIC_COUNT` (6) and `UNAVAILABLE_FEATURE_COUNT` (9) are kept apart
because they call for different responses: one needs new data, the other needs an
approved method.

Every one of these declares `source_domain` as
`NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED` rather than leaving the
field blank, so the omission reads as a known gap and not an oversight.

---

## 6. Units

**Phase 3 performs no unit conversion.** The unit in the output is the unit in the
input, character for character: `mm` stays `mm`. Conversions belong to Phase 2's
`preprocess_units`, which performs only exact documented conversions and never
guesses. Duplicating them would give two answers to one question.

What Phase 3 *does* do is refuse operations whose units it cannot interpret:

| Situation | Behaviour |
| --- | --- |
| Accumulation over a quantity with `UNDETERMINED` unit | Blocked under `UNIT_REQUIRE_KNOWN`; values still copied under the permissive default, with the fact recorded. |
| **Intensity** (amount ÷ time) with `UNDETERMINED` unit | **Refused outright.** Dividing an amount of unstated units by an hour yields a quantity whose units nobody can name, and a model will fit it as confidently as any other column. |
| Lag over an `UNDETERMINED` unit | Allowed. A lag is a copy; it does not claim to be a number of anything. |
| Change across two different units | **Refused** (`unit_mismatch`). A difference between metres and centimetres is not a small error, it is a number with no meaning. |
| `UNKNOWN` / `UNDETERMINED` | Never silently converted, never claimed physically comparable. |

### Rates and intensities

An intensity is computed **only** when both the amount unit and the elapsed time
are known. The elapsed time comes from Phase 2's inferred cadence; Phase 3 never
divides by an assumed one-hour interval unless Phase 2 explicitly established
hourly cadence.

### Datum

Water-level datum compatibility between locations is **unverified**. No datum
conversion is applied and none is invented, so `water_level_*` features are
comparable **within one location only**. This is reported as
`FEATURE_DATUM_COMPARABILITY_LIMITATION` on every run rather than left for the
reader to notice.

The reason `water_level_change_*` features exist despite this: a *difference*
cancels any vertical datum, so two gauges on different datums have levels that
cannot be compared and changes that can.

---

## 7. Missing data, warm-up and imputation

**Phase 3 imputes nothing.** Eight distinct causes are declared, and every absent
value carries exactly one:

| Cause | Meaning |
| --- | --- |
| `warmup` | The series had not started when the window opened. |
| `missing_source` | The series was running; the reading is absent. |
| `insufficient` | Coverage unassessable, or a statistic needs more observations than exist. |
| `undetermined_unit` | The operation needs an interpretable unit. |
| `unit_mismatch` | The operation needs comparable units. |
| `not_applicable` | The operation does not apply to this quantity. |
| `no_source_series` | The dataset never had this quantity. |
| `cutoff_undefined` | A `one_step_back` cutoff could not be placed. |

Warm-up and `missing_source` are kept apart deliberately: warm-up is fixed by
collecting more history, a hole is fixed by fixing the sensor or the gap policy.
Reporting the first as the second sends an operator to debug a gauge that was
working perfectly. A window reaching past the **end** of a series is
`missing_source`, not warm-up — warm-up is a statement about the beginning of a
record.

Row policies are conservative by default and **opt-in** to change:

| Policy | Default | Effect |
| --- | --- | --- |
| `missing_policy` | `retain` | Rows with absent values are kept. |
| `warmup_policy` | `retain` | Warm-up rows are kept. |

Dropping is irreversible, so it is never the default, and what was dropped is
counted with its reason. If a policy combination retains nothing,
`build_features` **raises** and names both policies rather than returning an empty
matrix — a refusal with a reason beats an empty dataset without one.

**Forward-fill is never applied.** Carrying the last observation forward until a
lag becomes satisfiable is leakage with a clean-looking column name. A hole in the
middle of a series stays a hole, and a test cuts one deliberately to prove it.

**Gap-filled slots are excluded.** A slot Phase 2's gap policy filled is a policy
decision, not an observation. Feeding it to an accumulation would inflate a
rainfall total by an invented amount, so `build_timelines` drops
`quality_status == "missing"` readings by default and reports how many.

---

## 8. Entity isolation

Features are computed only from the entity's own history, and the isolation is
**structural** rather than promised:

1. `build_timelines` groups records into one timeline per measurement key.
2. A feature resolves its source by key lookup, not by search.
3. Rows are keyed by entity, and the report carries `entity_counts`.

The test is a perturbation, not an inspection: station B is added with completely
different values and every feature value at station A must be **byte-identical**. A
filter applied after the fact would pass a structural test — the keys are right,
the scopes are right — while still letting the wrong reading in. Only a
perturbation test can tell the difference.

A wide `weather` record carrying both temperature and humidity yields **two**
timelines. Keyed on the domain's canonical quantity instead — and `weather` has no
canonical quantity, so `Observation.quantity()` returns `None` — it would yield
zero, and the temperature and humidity columns would sit permanently empty while
the report claimed the features were built. That was a real defect in an earlier
draft.

---

## 9. The leakage audit

Eight checks, recorded **by name** so a reader can see which ones ran. An audit
that reports `ok` without saying what it checked is an assertion, not evidence.

| Check | Question |
| --- | --- |
| `features_read_at_or_before_origin` | Did any feature read an instant later than its own origin? |
| `targets_strictly_after_origin` | Is every target instant strictly later than its row's origin? |
| `target_columns_disjoint_from_features` | Is any name both a feature and a target? |
| `retained_target_instants_carry_a_split_label` | Does every retained target sit in a known split? |
| `targets_inside_own_split` | Is a row's target in the same split as the row? |
| `row_order_is_entity_then_instant` | Is row order canonical? |
| `column_order_is_registry_order` | Is column order the declared order? |
| `imputation_absent` | **By construction** — the check states its own limit rather than claiming a detection it cannot perform. |

### The behavioural probe

`audit_point_in_time` is the stronger check and does not rely on any of the above.
It builds the dataset twice — once intact, once with every record after an origin
instant **deleted** — and reports any feature whose value changed. A feature that
changes has read the future, whatever the window arithmetic says.

This catches a bug class that introspection of the code cannot, because the class
is defined by what the value *depends on*. It is how the unknown-cadence state
cutoff defect in §3 was found.

Phase 2's audit checks *split* leakage on records. Phase 3's checks *feature*
leakage on produced rows — a different question, because a split can be perfectly
disjoint while a rolling window still reaches forward.

---

## 10. Determinism

The same input and configuration produce the same values, ordering, names,
metadata, report, warnings and errors — including the *order* of the warnings,
which is what makes two runs diffable.

- Rows are sorted by `(entity, instant)` after canonicalisation.
- Columns are registry order.
- Notes are sorted worst-first, then by code, subject and message.
- Timeline keys and their readings are sorted at construction.
- `dedupe_windows` preserves first-seen order and does **not** sort, because
  sorting would silently reorder a declared configuration.

Input permutation changes nothing, verified over three permutations including one
no sort would produce (all even indices, then all odd). Permuted *within* each
split, deliberately: re-partitioning the records would change which instants belong
to which split, and a different split is a different dataset. The boundary claim is
tested separately.

---

## 11. Configuration

```python
from app.engines.hydro import FeatureConfig

FeatureConfig(strictness="strict")            # == strict_feature_config()
FeatureConfig(accumulation_min_coverage=0.8)  # opt in to partial accumulation
```

| Setting | Default | Meaning |
| --- | --- | --- |
| `quantities` | all six | Which quantities to build for. |
| `lag_hours`, `change_hours`, `rolling_hours`, `accumulation_hours`, `intensity_hours` | see registry | Window widths, in hours. |
| `rolling_statistics` | `mean, min, max` | Deliberately **not** `sum` (routed through accumulation) and not `count`. |
| `target_hours` | `6.0` | Forecast horizon. |
| `target_alignment` | `exact` | See §4. |
| `target_tolerance_seconds` | `None` | Required by `at_or_before`; refused under `exact` rather than silently ignored. |
| `forcing_cutoff` / `state_cutoff` | `at_prediction_instant` / `one_step_back` | See §3. |
| `strict_causality` | `False` | Collapse both to `one_step_back`. |
| `accumulation_min_coverage` | `1.0` | A sum over a window with a hole is *smaller than the truth* and still looks like a total. |
| `rolling_min_coverage` | `0.0` | A mean over what was observed is a mean of what was observed, and the count travels with it. |
| `missing_policy`, `warmup_policy` | `retain` | See §7. |
| `unit_policy` | `flag_undetermined` | See §6. |
| `calendar_components`, `calendar_encodings` | `hour, doy` × `sin, cos` | See below. |

### Strictness

Two tables, because two different things are going on:

- **`STRICT_NARROWINGS`** — permissive → strict is applied **silently**. A field
  still at its permissive default under `strictness="strict"` is promoted, because
  asking for strict and naming the permissive word is still asking for strict.
- **`STRICT_REQUIREMENTS`** — deliberate deviations are **refused** with a message
  naming the field. `missing_policy="drop_rows"` under strict is not a preference,
  it is the loss of information the strictness was requested to prevent.

`FeatureConfig(strictness="strict") == strict_feature_config()` holds exactly.

### Calendar terms

Only `hour` and `day_of_year`, each as `sin` and `cos`. `day_of_year` is 1-based
(`tm_yday`) to match the pre-Phase-1 pandas layer, which is what makes
cross-checking the two worth anything.

`EXCLUDED_CALENDAR_COMPONENTS` documents the two that were considered and
rejected:

- **`day_of_week`** — no hydrological mechanism is established here for a weekly
  cycle. It is defensible for catchments dominated by weekday abstractions or
  weekday traffic, and no catchment in this repository has been characterised.
- **`month_of_year`** — a coarser quantisation of the same annual cycle, so it
  adds a collinear duplicate of what the annual harmonic already carries.

---

## 12. The Phase 4 contract

`ModelReadyDataset` is the hand-off. It is a frozen dataclass of exactly
`{dataset, contract_version}` and holds **no fitted state** — no scaler, no
imputer, no encoder — verified by checking its identifiers.

```python
payload = result.contract.to_dict()
payload["contract_version"]   # "navya-features/v1"
payload["feature_columns"]    # 56 names, registry order
payload["target_columns"]     # ("target_water_level_6h",)
payload["lineage"]            # per feature
payload["target_lineage"]     # per target, available_at_prediction_time=False
payload["disclaimer"]         # the synthetic-data statement
payload["samples"]            # real rows from this dataset, per split
```

The samples are built from the dataset, not hand-written, so a consumer checking
the contract is checking the real shape and a contract cannot drift from the data
it describes. The whole payload is JSON-serializable; a contract that cannot be
serialized is not a contract.

---

## 13. Tests

```
cd ai-service
python -m pytest tests -q --no-header --tb=short
```

**993 passed, 1 skipped** (baseline before Phase 3: **771 passed, 1 skipped**).
222 new tests across four modules, all in the ownership:

| Module | Tests | Lines |
| --- | --- | --- |
| `tests/test_hydro_feature_registry.py` | 42 | 354 |
| `tests/test_hydro_feature_config.py` | 60 | 380 |
| `tests/test_hydro_feature_temporal.py` | 55 | 770 |
| `tests/test_hydro_feature_pipeline.py` | 65 | 924 |

The seven mandatory leakage tests are numbered `test_leakage_1` …
`test_leakage_7` in the pipeline suite, and each is asserted **behaviourally**
where that is possible. The static scope guards read the four modules with `ast`
and refuse a forbidden import or a call to a fitting routine — matched against
identifiers, not against file text, because `resolve_cadence`'s own docstring says
"Phase 3 never resamples" and a substring search would fail on the sentence
documenting the guarantee it checks for.

The `pandas.Series.rolling(w)` cross-check lives in the temporal suite.

Phase 1's and Phase 2's suites still pass, as does the pre-existing
`features.py` coverage. No existing test was weakened or modified.

### Verified numbers on the committed sample

| Quantity | Value |
| --- | --- |
| Phase 1 records in | 6480 |
| Phase 2 split | train 4536 / validation 972 / test 972 |
| Phase 3 rows | 2160 (train 1512 / validation 324 / test 324) |
| Features built | 32 of 56 declared |
| Rows without a target | 18 |
| Leakage audit | 8 of 8 pass, 0 errors / 35 warnings |
| Unknown or irregular cadence | none |
| `audit_point_in_time` | no findings |

---

## 14. Team boundaries

Files created or modified by Phase 3, all forecasting-module-owned:

- `ai-service/app/engines/hydro/feature_registry.py` *(new)*
- `ai-service/app/engines/hydro/feature_config.py` *(new)*
- `ai-service/app/engines/hydro/feature_temporal.py` *(new)*
- `ai-service/app/engines/hydro/feature_pipeline.py` *(new)*
- `ai-service/app/engines/hydro/__init__.py` *(module map and lazy exports only)*
- `ai-service/tests/test_hydro_feature_*.py` *(new, four files)*
- `ai-service/app/engines/hydro/PHASE3_FEATURE_ENGINEERING.md` *(this file)*
- `ai-service/app/engines/hydro/README.md`
- `docs/architecture/Data_Flow/data-flow.md`
- `docs/forecasting/TEAM_INTEGRATION_REQUIREMENTS.md` *(new — see below)*

**Team-owned files modified: 0.** No file under `backend/src/**` or
`frontend/src/**` outside the directories; no QUBO, optimisation, GIS, IoT or
quantum-service file; no `.github/` file; no team README; no team test; no
migration `001`–`009`; `ai-service/tests/test_contract.py` and the team AI-service
interfaces are untouched. No team dependency file was modified.
`ai-service/tests/conftest.py` is shared with team tests and was **not** modified
— every Phase 3 fixture is module-local for that reason.

Migration `011` was reviewed statically only; no `psql` or `docker` is available
in this environment, so it needs a database owner to verify.

---

## 15. What Phase 3 deliberately does not do

- It does not train, tune, select or evaluate any model, and reports no accuracy
  metric.
- It does not fit an imputer or scaler — that belongs to Phase 4, after the split.
- It does not resample, interpolate, forward-fill or choose a cadence. Phase 2
  owns all of that; Phase 3 reads `preprocess_temporal.infer_base_interval` on
  Phase 2's own records rather than parsing Phase 2's prose report.
- It does not convert units. Phase 2's `preprocess_units` owns that.
- It does not re-validate schema, re-handle duplicates or re-split.
- It does not invent discharge from a water level, or any other derived quantity
  whose relationship has not been established.
- It does not create a second feature-engineering system alongside `features.py`.

### Known limitations

- **Code correctness is not hydrological validation.** Everything verified here was
  verified on synthetic/demo fixtures. Nothing in this phase has been validated
  against a real gauge network, and no such network, station registry, rating
  curve, official threshold, basin boundary, elevation, river distance,
  population or infrastructure dataset exists in this repository. A feature that
  is arithmetically correct on generated data says nothing about whether its
  definition is scientifically appropriate for a real catchment.
- **`doy` uses 365.25**, so the annual harmonic drifts slightly against a leap
  calendar. This is the conventional choice and matches the legacy layer.
- **A `std` statistic needs two readings.** A one-reading window is reported
  `insufficient` rather than `0.0`, which would claim two identical readings.
- **Entity-scoped features are declared but unused.** If a future feature needs to
  combine two quantities at one station, the `entity` scope exists and is
  currently empty.
- **Four files in this repository reference
  `docs/forecasting/TEAM_INTEGRATION_REQUIREMENTS.md`, which did not exist.**
  It is created here.