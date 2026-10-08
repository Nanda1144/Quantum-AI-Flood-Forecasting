# Phase 1 — Data / Schema Foundation

**Owner:** forecasting module (ForecastingEngine seam) · **Module:** `ai-service` ·
**License:** Apache-2.0

> This source file belongs to the Q-FLARE platform (Nanda Construction — Nanda &
> Navya). It is honest by construction: no fabricated data, no invented metrics,
> every surrogate or fallback is clearly labelled, and no quantum speedup is ever
> claimed.

---

## 1. What Phase 1 is for

Before anything can be forecast, three questions have to have answers:

1. **What shape is a record of this kind of thing?** A water level, a rainfall
   depth, a flood event and a risk assessment are four different things and
   conflating them into one wide frame loses the distinctions that matter.
2. **What is wrong with this batch of records?** Not "fix it" — *tell me*.
3. **What data do we actually have, per domain?** Including the parts we do not.

`preprocessing.py` already answers a fourth question — *is this `DataFrame`
usable for training?* — which is the right question for the wrong moment. A wide
frame silently absorbs everything: a gauge network that reports a level but no
discharge, a catchment with no rainfall record, an event register that does not
exist. The absence is real, and it is invisible.

Phase 1 makes each of those absences **representable and queryable** instead of
implicit. Three modules:

| Module | Question it answers | Reads |
| --- | --- | --- |
| `domains.py` | What is one record of this domain? | `contract`, `provenance` |
| `quality.py` | What is wrong with this payload / batch? | `domains` |
| `datasets.py` | What is this dataset, and which domains does it cover? | `config`, `domains`, `provenance` |

They are **pure stdlib** — importing them loads no NumPy, no pandas and no
scikit-learn. Verified, not assumed: all three import cleanly with those modules
absent, and so do the four they depend on (`config`, `contract`, `provenance`,
and each other). So a schema question never drags a 500 MB dependency graph in
behind it.

> One caveat, stated precisely: importing *through* the package
> (`from app.engines.hydro.domains import ...`) still executes
> `app/engines/hydro/__init__.py`, which imports `synthetic` and therefore
> NumPy. That is **pre-existing** — `__init__` has always imported `synthetic` —
> and Phase 1 neither caused it nor changed it. What is new is that
> `domains`, `quality`, `datasets`, `config`, `contract` and `provenance` are
> independently importable without the training stack.

### Relationship to `preprocessing.py`

They answer different questions, and both are needed. There is no overlap:

| | Phase 1 (`quality`) | Phase 2 (`preprocessing`) |
| --- | --- | --- |
| Question | Is this *shaped* like an observation, and is it self-consistent? | Is this *frame* usable for training? |
| Concerns | Units present, instant qualified, domain matches quantity, provenance declared | Ordering, missing-value policy, chronological splitting, train-fitted scaling |
| Never does | resample, fill, scale, split | inspect provenance |

`test_hydro_quality.py` asserts the boundary through the import graph, so Phase 2
cannot quietly grow into Phase 1's territory (or the reverse).

---

## 2. `domains.py` — the record schemas

### The domains

| Domain | One record is | Canonical quantity | Record type |
| --- | --- | --- | --- |
| `weather` | one instant at one location, any number of declared quantities | open | `Observation` |
| `rainfall` | one measurement interval at one location | `rainfall` | `Observation` |
| `water_level` | one instant at one location | `water_level` | `Observation` |
| `discharge` | one instant at one location | `discharge` | `Observation` |
| `inflow` | one instant at one location | `inflow` | `Observation` |
| `flood_event` | one event at one area | — (no measurement) | `FloodEvent` |
| `risk_score` | one assessed area, optionally tied to a forecast | — | `RiskScoreRecord` |
| `forecast` | **not defined here** | — | `contract.ForecastOutput` already owns it |

`forecast` is deliberately absent. Defining it here would create a second,
divergent forecast record competing with the one the team contract already
defines.

### Honesty invariants enforced by construction

`SchemaError` is raised when a record cannot be built honestly at all:

1. **An explicit timezone.** `parse_instant` refuses a naive timestamp rather
   than assuming UTC. Guessing the zone is how a series silently shifts by an
   offset and every downstream chronological boundary becomes wrong with nothing
   to report it.
2. **`dataset_type` is one of `real` / `synthetic` / `unknown`**, and a non-real
   record always carries the mandatory warning. The warning text is *imported*
   from `provenance.py`, so there is exactly one copy of that sentence in the
   tree, and `test_hydro_domains.py` asserts the two cannot drift.
3. **A real record may not carry a disclaimer.** A genuine observation dismissed
   as fake is its own kind of dishonesty, and the storage constraint in
   `010_hydro_forecast_provenance.up.sql` requires `disclaimer IS NULL` for real
   data. A record the schema accepts but the database rejects is a latent insert
   failure.
4. **A unit must be present** — but is **not** checked against a whitelist. This
   repository has no authority over which units a foreign dataset uses: `cusecs`,
   `ft`, `m3/s` and the deliberately-worded `UNDETERMINED (DEMO — no unit
   assigned)` are all legitimate strings. An unrecognised unit is a quality
   *warning*, never a rejection, and it is never converted.
5. **Values must be finite.** `NaN` is not a measurement and cannot be
   serialised.
6. **`bool` is not a number.** `Measurement(value=True)` is a type error, because
   `True` would otherwise coerce to `1.0` and become a plausible-looking
   measurement of 1.
7. **Nothing invents an identifier, a coordinate, a station or a threshold.** An
   unknown fact is `None`.

### What exists in this repository, per domain

`describe_domains()` prints this; `domain_catalog()` returns it as data.

| Domain | In this repository? |
| --- | --- |
| `weather` | **No.** No temperature / humidity / pressure / wind dataset exists. |
| `rainfall` | SYNTHETIC/DEMO only. Accumulation is Phase 3 and is **not** computed. |
| `water_level` | SYNTHETIC/DEMO only, with a **fictional** vertical datum. No official gauge datum or flood stage has been supplied. |
| `discharge` | **No.** No discharge record and no rating curve exist. |
| `inflow` | SYNTHETIC/DEMO only, with an **UNDETERMINED** unit. |
| `flood_event` | **No.** No event register exists, and none may be invented. |
| `risk_score` | **Schema only.** The risk engine is Phase 6, and no exposure data exists. |

Absences use the project's documented marker verbatim,
`NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED`, so they read the same
here as they do in `docs/architecture/`.

### The flood-event schema creates nothing

`FloodEvent` exists so that "this repository has no event register" is a
queryable fact, and so a future register has a schema to land in without a
redesign. `severity` and `status` are **free text** on purpose: there is no
approved severity scale in this project, and inventing one would present this
project's guess as a standard. Whatever vocabulary a real register uses is
carried verbatim, with `severity_source` naming the authority.

### Handing facts to the forecast contract

`Observation.forecast_inputs()` returns **only real `ForecastOutput` field
names** — `station_reference`, `target`, `target_units`,
`provenance_reference` — and `test_hydro_domains.py` asserts that subset
relation, so Phase 5 cannot quietly invent a differently-spelled one. It is a
mapping of *facts*, not a forecast.

`dataset_type` is **not** there: `ForecastOutput` has no such field. It travels
beside the forecast in `ProvenanceRecord` and in
`forecast_provenance_inputs()`. Mixing them would suggest a field the payload
does not carry, and a reader who believed that would look for it and not find it.

### Splitting a wide source row

`observations_from_row()` turns one CSV row reporting level *and* rainfall at one
instant into **two records**, because the two have different units and a record
with mixed units cannot be compared or converted without the caller re-parsing
it. Columns absent from the row are skipped rather than defaulted to zero — an
absent column is a domain the source does not report, and `quality.py` reports it
that way.

`unknown_columns()` returns columns no binding claims. An unmapped column is
usually a real observation this schema was not told about, and silently ignoring
it is how a domain goes missing without anyone noticing.

---

## 3. `quality.py` — validation that reports and never repairs

> **A validator reports; it does not repair.** No duplicate is silently collapsed,
> no conflicting pair is resolved to a winner, no missing value is filled. A
> source that disagrees with itself produces a conflict report, not a guess.
> Silently choosing one of two disagreeing gauge readings is how a dataset
> acquires a history that never happened.

### Two layers

| Entry point | Input | Purpose |
| --- | --- | --- |
| `validate_observation_payload` | a raw mapping from a source | Report **every** problem in one pass, so an ingest of 10,000 rows does not die on row 3 and hide 9,997 others |
| `validate_observation` | a constructed `Observation` | Cross-field consistency of a record that already satisfies the schema |
| `check_observation_collection` | a sequence of records | Duplicates and conflicting values across records |
| `check_flood_events` / `check_risk_records` | event / risk sequences | The same two questions, per domain |
| `ingest_observations` | an iterable of payloads | Batch entry point: build what can be built, report everything else, never raise |

`validate_observation_payload` is **total**: it returns a report for *any* input,
including `None`, a list, or a mapping of the wrong shape. An ingest must always
learn what was wrong with the rows it could not use.

### Stable issue codes

Codes are written to `hydro_data_quality_report.issues` (JSONB) and are therefore
a query surface: **add, never re-spell.** The full vocabulary is in `quality.py`;
the advisory ones are collected in `NON_BLOCKING_CODES`.

### An error rejects; a warning does not

| Severity | Effect | Examples |
| --- | --- | --- |
| `error` | record is **rejected** | missing location, unparseable instant, non-finite value, no unit, domain/quantity mismatch, non-real data with no disclaimer |
| `warning` | record is usable but **unverified** (`quality_status == "suspect"`) | unrecognised unit, rate with no declared window, absent bound column, unmapped column, no source reference |

### `quality_status`: four states, one of them the honest default

| Value | Meaning |
| --- | --- |
| `ok` | Assessed, and nothing found. |
| `suspect` | Assessed, with at least one warning. Usable, unverified. |
| `missing` | The supplier **declared** the value missing. A declared absence, not an absent fact. |
| `rejected` | At least one error. |
| `unknown` | **No assessment has been performed.** |

`unknown` is the default because asserting `ok` without having checked is a claim
this project cannot support. Distinguishing "no findings" from "nobody looked"
is why `ValidationReport` carries an explicit `assessed` flag rather than
inferring it from an empty issue tuple.

### Duplicates versus conflicts

Keyed by `domain + location + instant`. The dataset reference is deliberately
**excluded** from the key: the same gauge instant reported by two datasets is a
*merge* decision for the dataset owner, and conflating them here would hide the
disagreement.

| Finding | Definition | Severity |
| --- | --- | --- |
| Duplicate | Same key, **identical** values | Reported, not collapsed |
| Conflict | Same key, **different** values | Always an error |

`ConflictReport` deliberately offers **no `resolve`**. Choosing between two
disagreeing readings of the same instant is a dataset owner's decision that
needs a citation — the same reason `preprocessing.resolve_duplicates` requires an
explicit `keep` policy rather than defaulting.

Re-assessing an area at a later instant is legitimate — that is a new forecast —
so two risk records for one area are only a problem when they claim the *same*
instant.

### Range policy is deliberately thin

Only two rules are enforced, because only two are true regardless of datum,
convention or source:

- **rainfall is non-negative.** A negative cell is usually a missing-value
  sentinel (`-999`) rather than a measurement.
- **discharge and inflow are non-negative.** A volumetric flow magnitude has a
  sign convention, not a negative value.

A **negative water level is not judged.** Stage is relative to an unknown datum,
so its sign carries no information this repository has. Range and plausibility
policy beyond this belongs to Phase 2, where an approved datum may exist.

### No domain range policy is invented

`DomainSpec.accumulable` records that rainfall *could* be accumulated as a
capability note. **Accumulation is not computed**, and a rate with no declared
window is flagged (`rate_without_measurement_window`) because it cannot later be
accumulated unambiguously — not because this phase knows how to do it.

---

## 4. `datasets.py` — what a dataset is, and what it is not

### Not a second provenance system

`provenance.py` owns the facts about *where numbers came from*;
`config.DatasetSpec` owns the declared configuration. `datasets.py` adds exactly
one thing neither can express: **domain coverage** — the fact that a given
dataset reports water level but no discharge, or rainfall but no weather.

`DatasetDescriptor` *composes* rather than inherits, so it cannot disagree with
the provenance record it was built from. `with_provenance()` makes the record the
authority: a descriptor cannot claim a different checksum or licence than the
model artifact recorded.

### The empty catalog is the correct state today

`EMPTY_CATALOG` is the default, and `describe()` says so in as many words:
a registry that silently contains nothing reads the same as one that was never
checked.

```
DATASET CATALOG (empty)
  No verified hydrological observation dataset exists in this repository.
  NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED
```

### `available` / `absent` / `unknown`

| Status | Meaning |
| --- | --- |
| `available` | The source provides this domain. |
| `absent` | The source affirmatively does **not** provide it. A real, reportable fact — knowing a gauge network has no discharge telemetry is different from not knowing. |
| `unknown` | Nobody has said either way. The default. |

### The one dataset that exists

`synthetic_sample_descriptor()` describes
`data/synthetic_hydrology_sample.csv` **by reading the file itself** — checksum,
row count and header come from the bytes on disk, so the descriptor cannot drift
from the artefact.

| Fact | Value |
| --- | --- |
| Reference | `synthetic://hydrology/committed-sample` |
| Type | `synthetic` |
| Licence | `none — synthetic data has no license because it is not real data` |
| Rows | 2,160 |
| SHA-256 | `56f4b7c5b4122b5d9b61db256f8d7afcb7e03d4a1cf9e942c013818386e29ac6` |
| Available | `water_level`, `inflow`, `rainfall` |
| Absent | `weather`, `discharge`, `flood_event`, `risk_score` |
| `station_reference` | **`None`** — the file has no station column |
| `source_organisation` | **`None`** — nobody has supplied one |
| `location_kind` | **`None`** |

Three facts in that table are load-bearing:

- **`station_reference` is `None`.** The generator produces no station column.
  `SYNTHETIC-STATION-0001` exists only as a demo value in
  `config.DatasetSpec`, and attaching it here would promote a configuration
  placeholder into a property of the data — i.e. invent a gauge network.
- **The `inflow` unit is recorded as `UNDETERMINED (DEMO — no unit assigned)`.**
  `m3/s` would be a plausible-looking guess, and a guessed unit is a dataset
  analysed in the wrong units forever.
- **The `water_level` unit records that the datum is fictional.** Two gauges are
  not comparable until their datums are, and no datum is invented here.

`coverage_matrix()` renders the dataset × domain grid. `audit_rows()` is the
query an auditor would run: one row per dataset that may **not** be presented as
real observation data.

---

## 5. Storage — migration `011`

`database/migrations/011_hydro_hydro_observation_domains.{up,down}.sql` gives
each domain a table, so a schema that is only enforced in Python can still be
bypassed by a direct `INSERT`.

| Table | Holds |
| --- | --- |
| `hydro_dataset_catalog` | What a dataset is and which domains it covers |
| `hydro_observation` | One domain, one location, one instant |
| `hydro_observation_measurement` | The quantities of one observation |
| `hydro_flood_event` | One flood occurrence at one area |
| `hydro_risk_score` | One assessed area |
| `hydro_data_quality_report` | What `summarise()` found |
| `hydro_domain_availability` (view) | Per-domain audit, derived from the rows |

Design points worth knowing before reading the SQL:

- **Additive only.** Every object is `IF NOT EXISTS` / `OR REPLACE`. The team's
  `forecasts` table is not altered, and migrations 001–009 are untouched. The only
  reference to another owner's object is a foreign key into 010's
  `hydro_forecast_provenance`.
- **Same disclaimer rule as 010**, restated per table: a non-real record must
  carry the mandatory warning; a real record must not. There is no third state.
- **NaN *and* infinity are both refused** for a measurement value. `value <>
  'NaN'` is `TRUE` for ±Infinity, so the range check is a separate and necessary
  half of the rule.
- **A duplicate identity is refused by a UNIQUE index**, not by convention. A
  *conflict* is refused at storage but never resolved: this schema will not pick
  a winner, and `quality.py` reports it as a finding first.
- **An unassessed area is `NULL`, not `0.0`.** A score of zero means "assessed,
  no risk"; `NULL` means "not assessed". An unassessed area is not a safe area.
- **`threshold_policy = 'approved'` requires a threshold AND a source.** Silence
  is not approval.
- **The migration seeds nothing.** No rainfall value, water level, station
  identifier, threshold, coordinate, population figure or flood event is
  inserted. With an empty database, `hydro_domain_availability` reports
  `present_in_repository = FALSE` for every domain, which is the truth.
- **A vocabulary cannot drift.** `risk_level`, `status`, `quality_status` and the
  domain list are asserted equal to the Python vocabularies by
  `tests/test_hydro_phase1_migration.py`. A mismatch fails a test rather than
  producing a risk score the backend cannot read back.

### One PostgreSQL detail, recorded because it is not obvious

"An observation has at least one measurement" **cannot** be a `CHECK`
constraint: PostgreSQL forbids subqueries in `CHECK`, and a `CHECK` runs per-row
with no visibility of child rows. It is a `DEFERRABLE INITIALLY DEFERRED`
constraint trigger, which is also what makes *"insert the parent and its
measurements in one transaction"* the enforced requirement. An incomplete
transaction rolls back as a unit, so nothing partial survives.

Not enforced by the database: deleting a measurement row out from under a stored
observation. An observation is treated as immutable once written. That is stated
in the migration rather than left for a reader to assume.

### Verification status — read this

**Migration 011 has not been executed.** No PostgreSQL server or `psql` binary was
available in the Phase 1 environment. It has been **statically reviewed** by
`tests/test_hydro_phase1_migration.py`, which reads the SQL as text and asserts
things about its content — a typo in a domain name, a `CHECK` that permits NaN, a
constraint that permits the exact dishonesty the project exists to prevent.

That is a **weaker** statement than the one `docs/architecture/ASSUMPTIONS_AND_LIMITATIONS.md`
records for migration 010 ("verified 19/19 against local PostgreSQL 17.10"), and
the header of 011 says so in the same terms. A text assertion cannot prove the
SQL parses. **Anyone applying 011 must run it against a real instance, and that
run — not these tests — is the verification.**

---

## 6. What Phase 1 deliberately does not do

| Not done | Why | Whose job |
| --- | --- | --- |
| Rainfall accumulation | Needs an approved accumulation convention and a real dataset | Phase 3 |
| Resampling, filling, scaling | Different question from "is this shaped right" | Phase 2 (`preprocessing.py`) |
| Domain range / plausibility policy | Only "non-negative magnitude" is true without an approved datum | Phase 2 |
| LSTM / GRU / XGBoost / RF | Explicitly out of scope for this phase | Later |
| Forecasting or risk arithmetic | Phase 5 and 6. `RiskScoreRecord` is a **schema**, not an engine. | Phase 5 / 6 |
| Resolving duplicate or conflicting records | A dataset owner's decision that needs a citation | Dataset owner |
| Converting units | This repository has no authority over a foreign dataset's units | Dataset owner |
| Seeding the new tables | An empty schema is the honest Phase 1 state | — |
| GIS, routing, QUBO, QAOA | Owned by other seams entirely | Team |

---

## 7. Tests

```bash
cd ai-service
python -m pytest tests -q --no-header --tb=short
```

| File | Covers |
| --- | --- |
| `tests/test_hydro_domains.py` | Record schemas, invariants, the domain registry, the contract hand-off |
| `tests/test_hydro_quality.py` | Report mechanics, every issue code, duplicates and conflicts, batch ingest |
| `tests/test_hydro_datasets.py` | The catalog, the committed sample's checksum and coverage, honesty invariants |
| `tests/test_hydro_phase1_migration.py` | Static checks on migration 011's SQL text |

**All payloads in these files are SYNTHETIC/DEMO test data**, deliberately so: they
include malformed, missing and conflicting records on purpose, because testing a
validator means feeding it bad input. No payload describes a real gauge, and none
of the conflicting pairs are real observations that disagree.

`tests/conftest.py` is shared with the team's `tests/test_contract.py` and was
**not** modified by Phase 1. Every new fixture lives inside its own test module,
so team test collection is unaffected.