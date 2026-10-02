# Phase 2 - Data Preprocessing & Temporal Dataset Preparation

Owner: Navya (`ai-service/app/engines/hydro/`) · Branch: `feature/navya-forecast`
· Predecessor: [`PHASE1_DATA_FOUNDATION.md`](PHASE1_DATA_FOUNDATION.md)

> **All data referenced in this phase is SYNTHETIC/DEMO.** The committed sample is
> generated. Nothing in this repository is a real hydrological observation, and
> nothing produced by this phase may be presented as one.

---

## 1. What Phase 2 is for

Phase 1 established what a hydrological record *is*: a schema, a validation
vocabulary, and a dataset descriptor that says what the data does not contain.
Phase 2 takes those validated records and produces the dataset a model can
actually train on — a clean, chronologically ordered, unit-consistent,
duplicate-free, gap-aware, leak-free train/validation/test split — and reports
precisely what it did along the way.

The design principle throughout: **Phase 2 never invents data to make a dataset
tidier.** Every policy that would require inventing something is opt-in, and
opt-in means someone had to name it.

```python
from app.engines.hydro import preprocess, conservative_config

result = preprocess(records, config=conservative_config())
result.train, result.validation, result.test
print(result.report.describe())
```

### What Phase 2 is not

Phase 2 performs **no feature engineering whatsoever**. Specifically, it does not
and must not:

- create lag features;
- create rolling or moving-average windows;
- accumulate rainfall over any window;
- compute any flood-risk arithmetic;
- select, tune or train a model.

Those belong to `features` (Phase 3) and `risk`. The only aggregation Phase 2 can
perform is the resampling of a series onto a coarser grid, and only when a
frequency is explicitly declared and a per-quantity `AggregationRule` is
supplied. There is a test asserting the absence of feature-building symbols in
both the pipeline and temporal modules.

### Relationship to `preprocessing.py`

`app/engines/hydro/preprocessing.py` is a pre-existing 741-line wide-`DataFrame`
preprocessing layer consumed by `training.py`, `engine.py`,
`tests/test_hydro_preprocessing.py` and `tests/test_hydro_leakage.py`. **Phase 2
does not rewrite, replace or deprecate it.** The two coexist:

| | `preprocessing.py` | Phase 2 |
| --- | --- | --- |
| Shape | Wide `DataFrame` (one row per timestamp) | Narrow `Observation` records (one per quantity) |
| Dependencies | NumPy, pandas | Standard library only |
| Schema authority | None — a convenience layer | Composes Phase 1's `domains`/`quality` |
| Role | Training-loop convenience | Auditable preprocessing contract |

Phase 2 is the narrow-record path; `preprocessing.py` remains the wide-frame
convenience path for the existing training loop. Both are covered by the full
suite, and neither is allowed to regress the other.

### The four modules

| Module | Lines | Responsibility |
| --- | --- | --- |
| `preprocess_config.py` | 814 | Every policy, its default, and the rules that refuse a configuration. |
| `preprocess_units.py` | 686 | Exact documented unit conversions. Never guesses. |
| `preprocess_temporal.py` | 1916 | Timestamps, ordering, cadence, grids, gaps, resampling, splitting. |
| `preprocess_pipeline.py` | 1689 | The orchestrator, plus the report. |

Like Phase 1, all four import nothing outside the standard library. The Phase 2
entry points are exposed on the package lazily so that
`from app.engines.hydro import preprocess` keeps that property rather than
dragging NumPy in through `synthetic`.

---

## 2. Timestamp normalisation

### The canonical form

UTC ISO-8601 with a trailing `Z`: `2024-01-01T00:00:00Z`.

**The source's original string is never lost.** Phase 1's `Observation` keeps the
offset the source actually wrote, and Phase 2 appends it to `notes` whenever it
rewrites the instant. `2024-01-01T05:30:00+05:30` and `2024-01-01T00:00:00Z` are
the same instant written two ways; which one is "right" is a fact about the
source that this repository does not have.

### Timezone policy

| Policy | Behaviour |
| --- | --- |
| `require_explicit` | **Default.** An instant with no offset is an error. |
| `source_declared` | Apply `source_timezone` to offset-less instants. |
| `assume_utc` | Treat offset-less instants as UTC. Requires acknowledgement under `strictness='strict'`. |

`require_explicit` is the default because a silently assumed timezone shifts an
entire series while every downstream boundary still looks perfectly
self-consistent. Nothing in this repository can tell a wrong assumption from a
right one, so the assumption must be declared.

Note that Phase 1 already refuses a naive `observed_at` at `Observation.__post_init__`,
so for records constructed in Python the `require_explicit` default cannot fail
inside the pipeline. Stage 2's timestamp work is therefore *canonicalisation and
accounting*, not enforcement. `normalize_timestamp` is the directly tested entry
point for the policies that actually move an instant.

### Fixed offsets only

`source_declared` accepts fixed offsets (`UTC`, `+05:30`, `IST`). Named zones
with a DST rule (`Asia/Kolkata`) are refused. A named zone means a different UTC
offset at a different time of year, which needs a tz database; silently
substituting a fixed offset for it would introduce a seasonal error that is
invisible in every downstream check.

### Accounting is a partition

`TimestampNormalizationReport` reports `considered`, `normalized` (rewritten) and
`already_canonical` (unchanged), with the invariant

```
normalized + already_canonical == considered
```

An earlier version incremented `normalized` for every record and reported
`considered=6480 normalized=6480 already_canonical=0` on a batch where not one
timestamp had changed. The counts are now exact and mutually exclusive.

The kept examples are selected **by content**, not by arrival: the report retains
the five lexicographically smallest examples under `(normalized, original,
timezone_source)`. Keeping the first five seen would make the report a function
of the caller's row order, which is the one property a report an auditor diffs
across runs must have.

---

## 3. Ordering, `entity_key` and `series_key`

Records are ordered by `(entity_key, instant, domain, source, provenance,
observed_at, measurements, dataset_reference)` — a **total** order, so two runs
over the same records in any input order produce byte-identical output. Nothing
in Phase 2 depends on a random seed, and nothing can: there is no `random`
import and no `seed` parameter in any of the four modules, which is asserted over
the AST rather than the source text.

### Two different notions of "same thing"

This split matters more than anything else in the phase.

| Key | Definition | Used for |
| --- | --- | --- |
| `entity_key` | `location_reference` — the reporting entity | Ordering, splitting |
| `series_key` | `location\|domain` — one gauge reporting one quantity | Cadence inference, grids, resampling, gaps |

The reason is Phase 1's invariant that domain and quantity are 1:1. One station
reporting water level, inflow and rainfall hourly therefore yields deltas
`0s, 3600s, 0s` when grouped by station alone. Grouped that way the series looks
irregular, no interval is inferred, no grid is built, and gaps become
undetectable — silently, on the normal case for a real gauge network. Splitting
the key restores cadence detection while keeping the split at station level, so
all variables still share one calendar window.

`describe_series()` renders a key for humans: `SYNTHETIC-STATION-0001 [water_level]`.

### Why splitting stays at station level

`split_strategy='per_entity'` splits each station on its own timeline. With
ragged coverage the three periods then overlap in *absolute* time across
stations — station A's test window can contain station B's training window. That
is a genuine leakage finding and is published as one (see §7), not hidden. The
default is `global`: one cut on the merged timeline, which is always leak-free.

---

## 4. Duplicates and conflicts

### Slot identity

A *measurement slot* is keyed on:

```
domain | entity | canonical instant | quantity | source reference
```

Including the source is deliberate. Two agencies reporting the same gauge at the
same instant are not a duplicate and not a conflict — they are two independent
readings, and merging them is a decision nobody has approved. Phase 2 detects
that situation and surfaces it (below) rather than collapsing it.

Slots are detected at the measurement level and resolved at the whole-record
level.

### Exact duplicates versus conflicts

| Case | Detection | Default |
| --- | --- | --- |
| Two rows, same slot, identical value | `duplicate` | `duplicate_policy='report'` — report, remove nothing |
| Two rows, same slot, different value | `conflict` | `conflict_policy='error'` — raise `PreprocessError` |

Conflict resolution requires a **citation**:

```python
PreprocessConfig(
    conflict_policy="keep_first",
    conflict_policy_source="synthetic://demo/ticket-42",  # who approved, against what
)
```

The config will not construct without it. Choosing between two readings of one
gauge instant is a decision about someone else's data and is treated exactly like
`config.RiskPolicy.threshold_source`.

**No policy ever averages, sums or takes a median.** The module-level constant
makes that checkable rather than a matter of trust:

```python
from app.engines.hydro.preprocess_config import CONFLICT_POLICIES_THAT_FABRICATE
assert CONFLICT_POLICIES_THAT_FABRICATE == ()
```

It is empty, and a test asserts it stays empty.

Conflicts are resolved *before* duplicates are counted. Collapsing a conflicting
pair is not deduplication, and reporting it as a duplicate would understate the
severity.

### Cross-source advisory

Phase 1's `check_observation_collection` keys on gauge-and-instant and omits the
source by design, so it sees the A-versus-B disagreement that Phase 2's
slot identity declines to resolve. Phase 2 always runs it and republishes the
result as `cross_source_advisory`. Two frameworks are therefore *not* in
play: Phase 1's `QualityIssue` remains the single validation vocabulary, its
output is embedded in the Phase 2 report under `phase1_quality`, and Phase 2's own
finding codes are a distinct `PREPROCESS_*` namespace
(`preprocess_pipeline.CODE_PREFIX`).

### Counts are by identity, not equality

`Observation` is a frozen dataclass with value equality. Two genuinely distinct
rows carrying the same reading compare and hash equal, so counting affected
records in a `set` would report "1 record" where two rows exist. Affected-record
counts are keyed on `id()`.

---

## 5. Units

### Never guessed

| Policy | Behaviour |
| --- | --- |
| `preserve_undetermined` | **Default.** Convert what has a documented factor; carry anything else through untouched with its unit reported as `UNDETERMINED`. |
| `require_known` | Refuse an unrecognised unit outright. |

The default exists for a concrete reason. The committed sample's `inflow` column
is declared `UNDETERMINED (DEMO - no unit assigned)`, and assuming `m3/s` for it
would be fabricating a hydrological fact that nobody has established.

### Exact conversions only

Conversions come from a hub of explicitly documented relationships. Results are
**not rounded** — 1 mm/h in m/s is `2.777…e-07` and no decimal length makes it
exact, so callers compare with a tolerance rather than absorbing a small bias.

The module refuses, rather than guessing:

- ambiguous bare symbols: `C` (Celsius or coulomb?), `F`;
- rate → amount (`mm/h` → `mm`): that is aggregation, not conversion;
- cross-dimension pairs (`m3/s` → `mm`);
- non-finite and non-numeric values.

`AMBIGUOUS_UNITS` is distinguished from `UNCONVERTIBLE_UNITS` (`Pa` is a real unit
of a dimension this table does not define) because those two failures deserve
different fixes.

### Original and normalized are both kept

Every `UnitConversion` records `original_unit`, `normalized_unit`,
`original_value`, `value`, `factor` and `offset`. Conversions are affine where
the physics requires it — 0 °C is not a scaled version of 32 °F — so `offset` is
non-zero for exactly the temperature conversions and zero for pure scale factors.

A conversion that changes anything is written into the record's `notes` as
`quantity: original -> normalized`, so a row is self-describing without the
report. A measurement whose unit does not change is left with empty `notes`;
annotating every untouched row would bury the ones that moved.

### The datum caveat

`water_level` conversions carry a note:

> this is a unit change, not a datum change. The vertical datum of the unit `m`
> is not established in this repository, so this stage remains comparable only
> with readings from the same gauge under the same datum.

A vertical datum is a reference surface, not a unit. Converting metres to feet
relabels the number and moves nothing on the ground, so two gauges in different
units remain incomparable exactly as before. No datum has been supplied for any
gauge in this repository.

---

## 6. Gaps, cadence and resampling

### Interval inference: smallest positive delta

`infer_interval()` classifies a series by whether one delta holds 90% dominance
and exports an `irregular` verdict. **The pipeline does not use it.**
`infer_base_interval()` uses the smallest positive delta instead, guarded by
`MAX_GRID_EXPANSION` (500×) and `MIN_GRID_SLOTS` (64).

The reason is concrete: a series with one three-hour hole has deltas of
`3600s, 10800s, 3600s, …`. The modal rule calls that irregular, the missing-value
stage then does nothing, and the single most common condition of a real gauge —
occasional dropout — becomes silently invisible. Smallest-positive-delta finds
the 1 h cadence and the grid then shows the gap.

Inference is never silent. `interval_regularity()` publishes the dominance ratio
alongside it:

```
SYNTHETIC-STATION-0001 [rainfall] = 1h (regularity 86%, inferred)
```

so a reader can see that the cadence is inferred and how confident it is.

### The grid

`build_grid()` expands the series onto its inferred cadence and marks the empty
slots. It hard-caps at `MAX_GRID_SLOTS = 5_000_000` and raises `TemporalError`.
The guard has to live here and not only in inference, because a caller may pass
any interval directly.

### Gap policies

| Policy | Fills? | Causal? | Notes |
| --- | --- | --- | --- |
| `retain` | no | yes | **Default.** Gaps stay visible. |
| `reject` | no | yes | Refuse the batch. |
| `drop` | no | yes | Remove the empty slots. |
| `forward_fill` | yes | yes | Carries an earlier value forward. |
| `linear_causal` | yes | yes | Interpolates from earlier values only. |
| `backward_fill` | yes | **no** | Reads a later instant. |
| `linear_bidirectional` | yes | **no** | Reads both directions. |

Every fill is auditable:

- the record is marked `quality_status='missing'`;
- its notes name the instant the value was carried from;
- `max_fill_gap` bounds how far a fill may reach, because carrying a value across
  three missing hours is a different claim from carrying it across one;
- a **leading gap is never filled** — there is no earlier value to carry, so
  nothing is invented.

`apply_missing_policy` returns new slots; the caller's grid is not mutated.

### Leakage-sensitive policies need both a flag and a name

```python
PreprocessConfig(
    missing_policy="linear_bidirectional",
    allow_leakage_sensitive=True,
    acknowledged_leakage_operations=("missing_policy:linear_bidirectional",),
)
```

The flag permits, and the named acknowledgement records *which* operation was
accepted. `config.is_causal` is the single audit question it answers: "can any
row in the output depend on a value from after it?"

Acknowledging an operation is **not** the same as producing a leak-free result,
and the report does not imply otherwise — the leakage audit re-checks the actual
output either way.

### Resampling

Off by default: nothing in this repository establishes what cadence a real gauge
network reports, so native resolution is preferred and saying so is recorded
(`PREPROCESS_RESAMPLED`).

When enabled:

- **bins are right-labelled** — a day covering hours 0…23 is stamped `23:00`.
  A bin stamped `00:00` would depend on 23 readings taken after it, which is the
  definition of leakage;
- every quantity needs an explicit `AggregationRule`, so rainfall depth summed
  over an hour is not confused with rainfall intensity;
- upsampling is refused (it would require inventing values);
- a frequency that does not divide the cadence is refused;
- mixed units inside one bin are refused;
- an empty bin produces no record — a day with no rain is `0 mm`, a day with no
  *report* is not.

---

## 7. Splitting and leakage prevention

### Chronological, never random

There is no random split anywhere in Phase 2. There is no seed and no shuffle
parameter, asserted over the AST of all four modules.

Fractions are validated as a partition (`train + validation + test == 1`, none
negative) and boundaries are validated rather than assumed:
`train_end < validation_start` and `validation_end < test_start`. Below three
usable records for an entity the split refuses rather than emitting a 1/1/1
partition that means nothing.

### Strategies

| Strategy | Behaviour |
| --- | --- |
| `global` | **Default.** One cut on the merged timeline. Always leak-free, even with ragged stations. |
| `per_entity` | Each station split on its own timeline. |

An entity with too few records is reported (`insufficient_entities`,
`insufficient_reasons`) or refused, depending on
`insufficient_group_policy` — never dropped silently.

### `per_entity` publishes no aggregate boundary

Flattening a `(entity, instant)`-sorted list under `per_entity` produces a
boundary triple in which all six edge fields hold the same span and the three
`*_rows` fields are totals summed across entities. That reads exactly like a
partition and is not one.

So `per_entity` publishes only the per-entity windows, plus an envelope under
the named key `all_entities_envelope` which is explicitly flagged in the
machine-readable payload:

```json
"all_entities_envelope": {
  "is_partition": false,
  "note": "Span of every record, NOT a partition. ...",
  "envelope_train_start": "2024-01-01T00:00:00Z",
  ...
}
```

The edge fields are renamed `envelope_*` so they cannot be read as a partition
boundary even by a consumer that skips the note.

### Cross-entity overlap is a finding

Under `per_entity`, stations with different coverage produce overlapping absolute
windows. `SplitReport.cross_entity_time_overlap` names them,
`leakage_findings` reports them, and `is_leak_free` is `False`.

### The audit re-checks the output

`LeakageAudit` runs independent structural checks on the produced records —
monotonic instants per series, split disjointness, bin boundaries not preceding
their sources — rather than trusting the configuration. Acknowledging a
leakage-sensitive operation does not make the output leak-free, and the report
does not imply that it does.

---

## 8. The report

`PreprocessingReport` is the deliverable as much as the records are. It is
JSON-serialisable, deterministic under input permutation, and separates
`errors` / `warnings` / `infos` using the lower-case severity vocabulary Phase 1
already uses (`error`, `warning`, plus `info`).

### Honest row accounting

Resampling does not "remove" rows — it aggregates them. An earlier version
reported `records_removed=69` for 72 hourly rows becoming 3 daily bins, which
discards no reading and was simply false. The report now separates:

| Field | Meaning |
| --- | --- |
| `records_in` | Records handed in |
| `records_out` | Records handed back |
| `records_discarded` | Records a *policy* deleted (duplicates, conflicts, `drop`) |
| `resampling_delta` | Change caused by resampling, measured |
| `missing.row_delta` | Change caused by the gap policy, measured |

with the invariant `rows_reconciled`:

```
records_in - records_discarded + resampling_delta + missing.row_delta == records_out
```

`missing.row_delta` is measured directly rather than inferred, because a fill
*adds* rows while a drop removes none. An ERROR note is emitted if the invariant
ever fails. Every gap policy reconciles.

### One-line summary

```
PREPROCESSING 6480 record(s) in -> 6480 out (0 discarded by policy, resampling +0, gap policy +0)
TIMESTAMPS considered=6480 rewritten=0 already_canonical=6480 explicit=6480 declared=0 assumed=0 rejected=0
UNITS considered=6480 converted=0 unchanged=4320 undetermined=2160
      2160 x UNDETERMINED (DEMO - no unit assigned) -> UNDETERMINED (no conversion available)
      2160 x m -> m
      2160 x mm -> mm
    UNDETERMINED UNIT for: inflow
DUPLICATES exact_groups=0 records=0 conflicting_groups=0 removed=0 kept=6480
MISSING policy=retain series=3 gaps_before=0 gaps_after=0 imputed=0 beyond_max_gap=0
SPLIT strategy=global train=4536 validation=972 test=972
    all_entities: train 2023-01-01T00:00:00Z -> 2023-03-04T23:00:00Z | validation 2023-03-05T00:00:00Z -> 2023-03-18T11:00:00Z | test 2023-03-18T12:00:00Z -> 2023-03-31T23:00:00Z
LEAKAGE AUDIT 6486 checks, all passed
    WARNING PREPROCESS_STAGE1_ISSUES: Phase 1 structural validation raised 2160 issue(s) across 6480 record(s): unknown_unit=2160. ...
    WARNING PREPROCESS_UNDETERMINED_UNIT: no exact conversion exists for the unit(s) of ['inflow']; those values are carried unchanged with their unit reported as UNDETERMINED. ...
    INFO    PREPROCESS_ORDERED: records ordered by (entity, instant) across 1 entity/entities. ...
    INFO    PREPROCESS_RESAMPLED: no resampling was requested; every series keeps its source resolution ...
DISCLAIMER THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION DATA.
```

Read that summary for what it says about the committed sample: **2160
`unknown_unit` findings carried up from Phase 1** (the deliberately unit-less
`inflow` column), **2160 values left `UNDETERMINED` rather than guessed**, no
duplicates, no gaps, a leak-free chronological split, and 6486 leakage checks
passed.

### Findings never disappear

A `per_entity` run that surfaces a leakage finding is reported as
`completed = False`. Silence is not the same as clean.

---

## 9. Synthetic-data safety

- The disclaimer is defined **once**, in `provenance.SYNTHETIC_DATA_DISCLAIMER`.
  Phase 2 imports it; it does not restate it.
- Every record carries `disclaimer` as a **separate field** from `notes`.
  Provenance notes are appended to `notes` by several stages, and keeping the
  disclaimer elsewhere means no such append can displace it.
- `report.disclaimer` falls back to `UNVERIFIED_DATA_DISCLAIMER` when the dataset
  type is unknown. Unknown is treated as unverified, never as real.
- **No station identifier is invented.** The committed sample has no station
  column, so `synthetic_sample_descriptor().station_reference` is `None`.
  `SYNTHETIC-STATION-0001` is a demo label used in configuration and tests, and
  nothing treats it as a real gauge.
- **No hydrological threshold, rating curve or basin boundary is hard-coded.**
  The only hard-coded numbers are documented unit-conversion factors and grid
  guards, both asserted by tests.
- Metrics are not computed here; there is nothing to claim yet.

---

## 10. Configuration

`PreprocessConfig` has 18 parameters, all validated at construction. Defaults are
conservative:

| Parameter | Default |
| --- | --- |
| `timezone_policy` | `require_explicit` |
| `duplicate_policy` | `report` |
| `conflict_policy` | `error` |
| `missing_policy` | `retain` |
| `unit_policy` | `preserve_undetermined` |
| `resample_frequency` | `None` |
| `split_strategy` | `global` |
| `train_fraction` / `validation_fraction` | `0.7` / `0.15` |
| `allow_leakage_sensitive` | `False` |

Two shipped presets: `conservative_config()` (the defaults) and `strict_config()`,
which additionally rejects every operation that removes rows, imputes values,
assumes a timezone or preserves an undetermined unit.

The config is machine-readable (`to_dict()`), and `is_causal` is the computed
answer to "can any row here depend on a value from after it?"

---

## 11. What Phase 2 deliberately does not do

- **No feature engineering.** No lags, no rolling windows, no rainfall
  accumulation, no flood-risk arithmetic. That is Phase 3 and `risk`.
- **No model training, selection or tuning.** That is Phase 4.
- **No GIS, population or infrastructure exposure.** Out of scope entirely.
- **No quantum optimisation.** QUBO, QAOA and the optimisation handoff are
  untouched; `contract.py` is read-only input.
- **No new database schema.** Phase 2 is entirely application-level. It does not
  assume migration `011` ran, does not add a migration, and does not edit any
  prior migration.
- **No second validation framework.** Phase 1's `QualityIssue` is the
  validation vocabulary; its results are embedded under `phase1_quality`.
- **No second provenance record.** `SYNTHETIC_DATA_DISCLAIMER`,
  `DATASET_TYPE_*` and `SplitBoundaries` keep exactly one definition each.
- **No rewrite of `preprocessing.py`.** Both paths coexist and both are tested.
- **No assumption about a real gauge network's cadence, units or coverage.** Every
  such fact must arrive through configuration.

### Known limitations

1. **Migration `011` remains unverified against a live PostgreSQL server** — no
   `psql` or `docker` is available in this environment. Phase 2 does not depend on
   it, but a database owner still needs to run it.
2. **`ai-service/requirements.txt` does not exist.** Navya's equivalent is
   `requirements-hydro.txt`; the required team change is recorded as `AI-REQ-01`
   in `01_Flood_Forecasting/TEAM_INTEGRATION_REQUIREMENTS.md`.
3. **`timezone_policy='require_explicit'` cannot fail inside the pipeline** for
   records built in Python, because Phase 1 rejects naive timestamps at
   construction. It remains the default, and `normalize_timestamp` is the tested
   entry point for the policies that do move an instant.
4. **`split_strategy='per_entity'` is not leak-free** when stations have ragged
   coverage. This is reported, not fixed, because the fix — a global cut — is the
   other strategy.
5. **The datum of every gauge is unknown**, so water-level conversions never make
   two gauges comparable. No datum has been supplied to this repository.

---

## 12. Tests

```
cd ai-service
python -m pytest tests -q --no-header --tb=short
```

**771 passed, 1 skipped** (baseline before Phase 2: **597 passed, 1 skipped**).
174 new tests across four modules, all in Navya's ownership:

| Module | Tests | Groups |
| --- | --- | --- |
| `tests/test_hydro_preprocess_timestamps.py` | 70 | A timestamps, B ordering, C units |
| `tests/test_hydro_preprocess_cleaning.py` | 42 | D duplicates, E conflicts, F gaps |
| `tests/test_hydro_preprocess_resample_split.py` | 27 | G resampling, H splitting, I leakage |
| `tests/test_hydro_preprocess_pipeline.py` | 35 | J end-to-end, K guarantees |

Group K runs the committed sample end to end and asserts the numbers in §8.

Phase 1's own suites (`test_hydro_preprocessing.py`, `test_hydro_leakage.py`, 68
tests) still pass, as does the pre-existing `preprocessing.py` coverage. No
existing test was weakened or modified.

---

## 13. The Phase 3 contract

What Phase 3 may rely on:

- `PreprocessingResult.train / .validation / .test` — tuples of `Observation`,
  each chronologically ordered within its entity, disjoint from the others.
- `PreprocessingResult.report` — `rows_reconciled`, `is_leak_free`,
  `completed`, `disclaimer`, `is_synthetic`.
- `config.is_causal` — if `False`, the output may contain rows that depend on a
  later instant, and the acknowledged operations are listed.
- Every record's `quality_status`, so a Phase 3 feature builder can exclude
  `missing` rows rather than learning from an imputed one.
- Every record's `notes`, which name any conversion or fill applied to it.

What Phase 3 must still do, and must not expect Phase 2 to have done:

- lag, rolling and calendar feature construction;
- rainfall accumulation over any window;
- forward-time supervision alignment;
- deciding which features a model may see.

Phase 3 must also read `report.leakage.findings` before trusting a split, and
must not treat a feature window that reads backwards as causal merely because
Phase 2's own stages were.

---

## 14. Team boundaries

Files modified by Phase 2, all Navya-owned:

- `ai-service/app/engines/hydro/preprocess_config.py` *(new)*
- `ai-service/app/engines/hydro/preprocess_units.py` *(new)*
- `ai-service/app/engines/hydro/preprocess_temporal.py` *(new)*
- `ai-service/app/engines/hydro/preprocess_pipeline.py` *(new)*
- `ai-service/app/engines/hydro/__init__.py` *(exports and module map only)*
- `ai-service/tests/test_hydro_preprocess_*.py` *(new, four files)*
- `ai-service/app/engines/hydro/PHASE2_PREPROCESSING.md` *(this file)*
- `ai-service/app/engines/hydro/README.md`
- `02_Architecture/Data_Flow/data-flow.md`

**Team-owned files modified: 0.** No file under `backend/src/**` or
`frontend/src/**` outside Navya's directories was touched; no QUBO, optimisation,
GIS, IoT or quantum-service file; no `.github/` file; no team README; no team
test; no migration `001`–`009`; `ai-service/tests/test_contract.py` and the team
AI-service interfaces are untouched. No team dependency file was modified.
`ai-service/tests/conftest.py` is shared with team tests and was not modified.
