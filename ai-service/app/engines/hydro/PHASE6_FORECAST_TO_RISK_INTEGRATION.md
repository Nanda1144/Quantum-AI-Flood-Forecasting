# Phase 6 - Forecast to Risk Integration & Risk Assessment Boundary

Owner: Navya (`ai-service/app/engines/hydro/`) · Branch: `feature/navya-forecast`
· Predecessor: [`PHASE5_FORECAST_ARTIFACT_AND_SERVING.md`](PHASE5_FORECAST_ARTIFACT_AND_SERVING.md)

> **All data referenced in this phase is SYNTHETIC/DEMO.** The committed sample is
> generated. Nothing in this repository is a real hydrological observation, and
> nothing produced by this phase may be presented as one.
>
> The verbatim source disclaimer is carried by
> `provenance.SYNTHETIC_DATA_DISCLAIMER` and reproduced in every risk result, every
> explanation, every provenance chain and every configuration this phase reads:
> `THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL
> HYDROLOGICAL OBSERVATION DATA.`
>
> **No risk assessment from this phase is production-ready, and none is claimed to
> be.** `production_ready_claimed` is permanently `False` in every `RiskResult`,
> every explanation, every projected record and every platform output. A band was
> computed from synthetic data against a demo threshold; that is all that means.
>
> **No threshold used here is an official flood stage.** The only threshold this
> repository can name is a DEMO value chosen for the synthetic pipeline, and it is
> labelled as one on every surface it reaches. Phase 6 will not invent an official
> one, and there is no code path that marks a threshold `approved`, `official`,
> `government`, `validated` or `operational`.

---

## 1. What Phase 6 is for

Phase 5 turned a manifest into a validated, auditable forecast. It stopped at the
forecast on purpose: a number in metres is not a risk, and a risk nobody can trace
back to the evidence behind it is worse than no risk at all. Phase 6 is the seam
between the two.

```python
from app.engines.hydro.forecast_risk import RiskConfiguration, assess_risk
from app.engines.hydro.risk_context import RiskContext, available_signal

config = RiskConfiguration(policy=policy, rules=())
context = RiskContext(
    entity="SYNTHETIC-STATION-0001",
    signals=(available_signal(
        "water_level_now", "water_level", 2.9, "m",
        source="synthetic gauge reading", observed_at=origin_instant,
    ),),
)

result = assess_risk(served, config=config, context=context, residuals=held_out_errors)
result.risk_level            # 'MEDIUM'
result.evaluation_state      # 'fully_evaluated'
result.production_ready_claimed
# False
```

Two modules, both in `ai-service/app/engines/hydro/`:

| Module | Responsibility | Exports |
| --- | --- | --- |
| `risk_context.py` | The typed, validated risk-context contract; availability; temporal, entity and unit validation; the GIS and historical provider interfaces | 53 |
| `forecast_risk.py` | The forecast-to-risk boundary; configuration; classification; explanation; provenance chaining; structured errors | 25 |

The chain those two modules implement, end to end:

```
Validated Phase 5 forecast   (forecast_serving.ServedForecast)
        |
        v
Forecast context validation  (entity, temporal, units, freshness)
        |
        v
Risk feature / context assembly  (RiskContext -> SignalEvaluation)
        |
        v
Risk assessment  (exceedance probability, measured residual spread)
        |
        v
Risk classification  (LOW / MEDIUM / HIGH / CRITICAL)
        |
        v
Risk explanation  (derived only from what was actually evaluated)
        |
        v
Auditable risk output  (RiskResult, to_dict / to_forecast_output / to_risk_score_record)
```

### Phase 6 does NOT

- compute flood probability from anything other than a caller-measured residual
  spread; it never substitutes `rmse` for one, and never invents a sigma;
- fit, refit, calibrate, or fine-tune anything, ever;
- re-score the forecast, or fetch a feature for an instant the caller did not name;
- classify into a band the configured policy cannot produce;
- invent a threshold, a source for a threshold, or a unit for a threshold;
- accept a signal observed after the forecast origin, whatever its timestamp says;
- accept a context whose station does not match the forecast's;
- fabricate a flood event, a gauge reading, a rating curve, or a spatial attribute;
- implement a GIS engine, a spatial database, or a population/exposure service;
- touch QUBO, QAOA, quantum optimisation, sensor placement, or IoT ingestion;
- expose an HTTP route, a handler, persistence, auth, or a deployment artefact;
- install a missing dependency or edit a team-owned dependency manifest.

---

## 2. What Phase 6 reuses, and why it does not duplicate it

The most important decision in this phase is the one that produced the *fewest* new
types. The repository already had a risk surface; Phase 6 did not build a second one
beside it.

| Concern | Existing owner | Phase 6's use |
| --- | --- | --- |
| Probability and band edges | `risk.exceedance_probability`, `risk.classify_risk_level` | Called directly. Phase 6 owns no arithmetic. |
| Residual spread | `risk.residual_sigma` | Called on caller-supplied residuals only. |
| Threshold configuration | `config.RiskPolicy` (`flood_threshold`, `threshold_source`, `policy_status`, `band_edges`, `band_labels`, `is_usable`) | Wrapped, never redefined. |
| Band vocabulary | `contract.SUPPORTED_RISK_LEVELS` = `LOW, MEDIUM, HIGH, CRITICAL` | The only bands Phase 6 can produce. |
| Output projection | `contract.ForecastOutput`, `contract.priority_for_risk_level` | `RiskResult.to_forecast_output(base)`. |
| Persisted risk record | `domains.RiskScoreRecord`, `domains.RISK_STATUSES` | `RiskResult.to_risk_score_record()`. |
| Flood event schema | `domains.FloodEvent` | `HistoricalContext.events` is a tuple of these. |
| Observation quantities | `domains.CANONICAL_QUANTITY` | `risk_context.CANONICAL_SIGNAL_QUANTITIES`. |
| Provenance | `provenance.ProvenanceRecord`, `provenance.SplitBoundaries` | `RiskResult.provenance`; the chain re-materialises the split as typed `SplitBoundaries`. |
| Units | `preprocess_units.dimension_of`, `normalize_unit`, `DIM_LENGTH`, `DIM_LENGTH_PER_TIME`, `DIM_VOLUME_FLOW` | The only unit authority in Phase 6. |
| Threshold disclaimer | `provenance.PENDING_THRESHOLD_DISCLAIMER` | Appears in the explanation whenever a policy is pending. |
| Synthetic disclaimer | `provenance.SYNTHETIC_DATA_DISCLAIMER` | Carried onto every result, explanation, chain and projection. |

The consequence worth stating plainly: there is exactly one `RiskPolicy`, one band
vocabulary, one `ProvenanceRecord`, one `FloodEvent` and one unit module in this
repository after Phase 6. A reader who wants to know what a band means follows one
reference, not two that may disagree.

---

## 3. The risk-context contract

`RiskContext` is a frozen dataclass. Signals are sorted by name in `__post_init__`,
so two contexts built from the same evidence in different orders are equal.

| Field | Meaning |
| --- | --- |
| `entity` | The station this context describes. Required. |
| `dataset_type` | Inherited vocabulary, defaulting to the forecast's own `data_status`. |
| `signals` | A sorted tuple of `RiskSignal`. |
| `gis` | A `GisContext`, or `None`. |
| `historical` | A `HistoricalContext`, or `None`. |
| `dataset_reference` | Where the context itself came from, when known. |
| `disclaimer` | Defaults to the synthetic/demo disclaimer. |

`RiskSignal` carries, per signal: `name`, `quantity`, `value`, `unit`, `source`,
`entity`, `observed_at`, `availability`, `note`, and an optional
`max_age_seconds` override.

### Refusals at construction

`RiskContext.__post_init__` raises before a context can exist if:

- `entity` is empty or not a string (`EntityMismatchError`);
- a signal names a different `entity` than the context does;
- a signal uses a quantity outside `RISK_QUANTITIES`;
- a duplicate signal name appears;
- `gis` or `historical` is neither the right type nor `None`.

### Two constructors, not one boolean

```python
available_signal(name, quantity, value, unit, source=..., observed_at=...)
unavailable_signal(name, quantity, availability, source=..., note=...)
```

An unusable signal always carries `value=None`. There is no way to declare
"missing" and pass a number, which removes the most likely way this contract could
be quietly violated.

---

## 4. Availability is a vocabulary, not a null

```
valid             a reading, a unit, a source, an instant, and it is fresh enough to use
missing           the quantity was looked for and there is none
unavailable       a provider exists but did not answer
not_applicable    the quantity does not apply to this entity or situation
stale             a real reading, older than the configured limit
```

`SIGNAL_UNUSABLE == (missing, unavailable, not_applicable, stale)`.

The load-bearing rule: **the risk layer branches on `usable`, never on `value`.**
`SignalEvaluation.value` is `None` for every unusable signal, and a `stale` reading
keeps its number in the `RiskSignal` — where the explanation can say "held 2.9 m but
too old to use" — while contributing `None` to the evaluation. An absent reading
therefore cannot be read as a zero reading, because there is nothing to read.

The four states are derived from the availability counts, never declared:

```
evaluation_state(signals)
    fully_evaluated     every declared signal is usable
    partially_evaluated some are, some are not
    context_unavailable no signal was usable at all
```

`not_evaluable` is a fourth state, but it is a verdict on the *risk*, not on the
evidence, and it is only ever set by `forecast_risk` when no band could be assigned.
The context layer cannot produce it. There is a test for exactly that, because a
state in a contract that nothing can reach is decoration.

### The six evidence channels

Every signal carries a source, a unit, an availability state and a validation status,
and the requirement to name all four applies to each channel:

| Channel | Quantity | Carried in | Availability today |
| --- | --- | --- | --- |
| Forecast | `water_level` | The Phase 5 `ForecastInference` | `valid` — it is the thing being assessed |
| Current state | `water_level` | `RiskSignal` | `valid` if supplied, else declared absent |
| Trend | `water_level_change` | `RiskSignal` | `valid` if derived by the caller, else declared absent |
| Rainfall | `rainfall` | `RiskSignal` | `valid` if supplied, else declared absent |
| Historical | — | `HistoricalContext.events` (`domains.FloodEvent`) | `unavailable` — no register exists |
| Spatial | `elevation`, `river_distance` | `GisContext` | `unavailable` — no spatial data exists |

The validation status is `SignalEvaluation.usable` — the same flag that decides
whether a rule may read the signal — so "what was validated" and "what may be used"
cannot drift apart. A missing reading is `usable=False, value=None`; it is never
`0`, and it is never quietly counted as evidence that conditions are fine.

Three of the six are unavailable in this repository, and they say so rather than
being filled in. `domains.DOMAIN_SPECS` reports:

| Domain | `present_in_repository` | Note, verbatim in `domains` |
| --- | --- | --- |
| `weather` | `False` | No weather dataset (temperature, humidity, pressure, wind) exists. |
| `rainfall` | `True` | Only SYNTHETIC/DEMO values from the committed generator exist. |
| `water_level` | `True` | Only SYNTHETIC/DEMO values, and their vertical datum is fictional. |
| `inflow` | `True` | Only SYNTHETIC/DEMO values, with an **UNDETERMINED unit**. |
| `discharge` | `False` | No discharge record and no rating curve exist. |
| `flood_event` | `False` | No flood event register exists, and none may be invented. |
| `risk_score` | `False` | Schema only; no exposure data (population, assets, elevation) exists. |

Each of those notes ends with the same
`NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED` marker that Phase 6's GIS
unavailability reason reuses, so a reader meets one consistent signal for "a human
has to supply this" anywhere in the repository.

---

## 5. Unit safety

Unit validation reuses Phase 2's module and never converts silently.

```
QUANTITY_DIMENSIONS
    water_level        -> (length,)
    water_level_change -> (length,)
    elevation          -> (length,)
    river_distance     -> (length,)
    rainfall           -> (length, length_per_time)
    discharge          -> (volume_flow,)
    inflow             -> ()            recorded, never converted
```

`inflow` is unconstrained for a reason recorded in the code: `domains` lists its unit
as UNDETERMINED, so constraining it here would invent a unit the repository does not
have. An unconstrained quantity is not an unvalidated one — the unit must still be
one this repository recognises, and the dimension that was found is recorded so a
rule can still ask about it.

Three refusals, all tested:

- an unrecognised unit — `bananas` — is refused, for every quantity including
  `inflow` (`InvalidUnitsError`, "not a unit this repository recognises");
- a recognised unit of the wrong dimension — a rainfall intensity checked as a depth
  — is refused ("A depth and a depth-per-time are not the same quantity and will not
  be silently reconciled");
- a `valid` signal with no unit at all is refused.

The **threshold** unit defaults to the forecast's own `target_units`, and the
defaulting is recorded on the result either way. Defaulting is not inventing: the
forecast's unit is measured, not assumed. A configured threshold unit is validated
against the same table, and a convertible one is converted through Phase 2's
`normalize_unit` with the conversion recorded in the explanation ("converted from
mm"), never applied silently.

---

## 6. Temporal safety

The boundary is the **forecast origin**, not the prediction instant.

```
signal.observed_at  >  forecast_origin_instant   ->  FutureContextError
```

The tempting boundary is the prediction instant. It is the wrong one: the forecast
was *made* at the origin, so a reading timestamped one minute after the origin is
information the model did not have, whatever the horizon. The boundary is
inclusive, so the origin instant itself is usable.

Four temporal rules, in the order they run:

1. `observed_at` must be a timezone-aware `datetime`. A naive instant is an
   unreadable one; no offset is assumed (`FutureContextError`).
2. `observed_at` must not be after the origin (`FutureContextError`).
3. `assessed_at` may not be earlier than the origin (`FutureContextError`). It
   defaults to the origin, so **nothing in this layer reads a clock**.
4. Freshness is a *state*, not a refusal. A signal older than its limit — the
   per-signal override, else the configured default, else no limit at all — becomes
   `stale`, with `usable=False` and `value=None`. With no configured limit, nothing
   goes stale, because Phase 6 will not invent an age limit nobody configured.

Historical events are checked the same way: same station, and not from the future. A
flood in progress at the origin is known and is not leakage.

---

## 7. Entity safety

No evidence crosses a station boundary, on any channel.

- The context's `entity` must equal the forecast's `entity`.
- Each signal's own `entity`, when declared, must equal the context's. A
  self-declared label is checked rather than trusted.
- Each historical event's `area_reference` must equal the context's.

A violation is `EntityMismatchError`, and the message names both stations so a
mis-wired context can be found by reading one line:

> risk context describes 'SYNTHETIC-STATION-0002' but the forecast describes
> 'SYNTHETIC-STATION-0001'; combining them would transfer one station's evidence to
> another

There is no station mapping in this repository, and Phase 6 does not invent one.
Cross-station use requires an explicit, validated mapping that a data owner
supplies; until then the only permitted relationship is equality.

**The one documented gap:** the `GisContext` record carries no station label of its
own. Adding one would be a guess about a teammate's schema. The consequence is
stated rather than hidden — spatial values are reported as `GisContext` provenance
and are **never evaluated as signals**, so a spatial escalation rule cannot even be
written and there is no path by which one station's elevation reaches another's
rules.

---

## 8. The residual spread is measured, never assumed

This is the single most consequential decision in the phase.

`risk.exceedance_probability(prediction, threshold, sigma)` needs a residual spread.
Phase 4 artifacts carry aggregate metrics only — `mae`, `rmse`, `r2`, `bias` — and
**not the residuals**. So the sigma has to come from the caller, or not at all.

**RMSE is not sigma.** RMSE is the root-mean-square error about zero; sigma is the
standard deviation of residuals about their mean. They differ whenever the model is
biased, and they are not close. Measured on this phase's own held-out fixture
(36 residuals):

```
bias  +0.31713755857904724
rmse   0.3906092880928549
sigma  0.23126841892889116      ratio rmse/sigma = 1.689
```

Substituting `rmse` here would inflate sigma by 69% and cut every probability
roughly in half. A `HIGH` band would read as `MEDIUM`. That is not a rounding
difference; it is a different answer, and it would be wrong in the direction that
makes a flood look safer than it is.

So `assess_risk` accepts either `residuals` (measured, sigma computed with
`risk.residual_sigma`) or `residual_sigma` (a measurement the caller made), and with
neither it **withholds the level** rather than guessing:

> no measured residual spread was supplied, and none is invented: a Phase 4
> artifact records aggregate metrics (mae, rmse, r2, bias) but not the residuals
> they were computed from. rmse is the root-mean-square error about zero, not the
> standard deviation of residuals about their mean, and the two differ whenever the
> model is biased. Supply residuals from a held-out split, or a sigma measured from
> them.

`residual_sigma_source` records which route was taken: `measured_residuals`,
`caller_supplied_measurement`, or `unavailable`. There is no fourth option.

Note also that the *default* configuration in this repository has no threshold, so
the default answer today is an **unavailable** risk assessment. That is correct
behaviour, not a defect: no approved flood stage exists to assess against.

---

## 9. Thresholds

A threshold arrives only through `config.RiskPolicy`, Phase 5's own type. Phase 6
adds no second policy class and no way to bypass `RiskPolicy.is_usable`.

| Field | Meaning |
| --- | --- |
| `flood_threshold` | The DEMO threshold, in the configured or forecast's units. |
| `threshold_source` | Where it came from, in words a reader can check. |
| `policy_status` | `pending` until an owner signs it off. |
| `band_edges` | Ascending probability edges, `(0.1, 0.3, 0.6, 0.9)`. |
| `band_labels` | `LOW, MEDIUM, HIGH, CRITICAL`. |

Refusals, all tested:

- a threshold that is not a real number, or is `NaN` or `inf`
  (`InvalidThresholdError`);
- band labels outside `SUPPORTED_RISK_LEVELS`, so a policy cannot introduce a
  vocabulary the platforms do not share;
- an `escalate_to` the policy cannot produce;
- a rule id that appears twice, an unknown comparison operator, a non-finite rule
  value, or a freshness limit that is not a positive finite number.

Deliberately **not** imposed:

- **Positivity of the threshold.** A river level datum can legitimately be negative,
  and a threshold of `0.0` gives `P = 1.0` and `CRITICAL` — arithmetically correct.
  Whether a given datum is plausible is the operator's judgement, carried by
  `threshold_source` and `policy_status`, not a rule Phase 6 can justify.
- **Any re-validation of the band edges.** `risk.classify_risk_level` is the
  authority on whether an edge set describes a band mapping; it accepts
  `len(labels)` edges or `len(labels) - 1` interior edges, requires them strictly
  ascending and inside `[0, 1]`, and returns `None` for any other shape. Repeating
  those rules in `RiskConfiguration` would be a second, inevitably divergent copy of
  them, so Phase 6 calls the classifier and reports what it says:

  | Edge set | Behaviour |
  | --- | --- |
  | Non-ascending, or outside `[0, 1]` | `classify_risk_level` raises; the result is `withheld`, `risk_level=None`, `risk_score=None`, and the explanation names the reason and tags it `invalid_risk_calculation`. |
  | Neither arity | `classify_risk_level` returns `None`; the result is `withheld`, `risk_level=None`, and the probability is retained, because it *was* computed — what is missing is the band. |
  | Short or long enough | `recorded`, with the band. |

  In the first two rows the explanation says the edges *do not* describe a mapping,
  rather than printing "map to" for a mapping the classifier rejected.

Nothing here marks a threshold `official`, `approved`, `government`, `validated` or
`operational`. The DEMO source string is
`"DEMO value chosen for the synthetic pipeline; NOT an official flood stage"`, and
`policy_approved` is carried on the assessment so a consumer can see the difference
between "usable" and "signed off".

---

## 10. Classification and escalation

The band is assigned by exactly one classifier — `risk.classify_risk_level` — and
Phase 6 adds no second rule that can move it. That is the whole design decision.

An earlier draft of this phase proposed a weighted composite score over forecast,
current state, trend, rainfall, history and spatial evidence. It was dropped, for a
reason worth recording: a weighted composite needs weights, and there are none to
have. Any weight set here would be invented, and a composite score invites a
reader to believe it has a meaning the repository cannot support. One classifier,
whose inputs are all measured, is defensible. Six invented weights are not.

Context therefore influences the outcome in exactly four ways:

1. **Availability** — what could be read, recorded per signal and summarised in
   `evaluation_state`.
2. **Escalation rules** — a `RiskEscalationRule` compares one named signal against a
   configured value and can only ever **raise** the band.
3. **Explanation** — every read, every non-read, and every refusal to read.
4. **Evaluation state** — `partially_evaluated` instead of `fully_evaluated`.

`RiskEscalationRule` is fully explicit: `rule_id`, `signal`, `quantity`,
`comparison`, `value`, `unit`, `escalate_to`, `source`, `required`. There are no
escalation rules in the default configuration.

The rules that keep this honest:

- **raise only** — a rule can never lower a band. A rule that fires for a band
  already at or above its target is recorded as `fired, not applied`, so no rule's
  firing goes unnoticed.
- **unit validated** — a convertible unit is converted and the conversion recorded;
  an inconvertible one does not fire.
- **quantity checked** — a rule that mislabels a rainfall signal as a discharge does
  not fire, and says so.
- **`required=True` refuses** — if a rule declares that it needs a signal and that
  signal is absent or stale, the result is a refusal (`StaleContextRuleError`), not a
  silent non-escalation. A stale reading cannot quietly lower a band the policy
  intended to raise.
- **`required=False` reports** — the same conditions produce a recorded reason
  instead, and the band is unchanged.

---

## 11. The risk result

`RiskResult` is a frozen, fully typed dataclass. There is no arbitrary dict in it,
and `to_dict()` is JSON-serialisable.

| Field | Meaning |
| --- | --- |
| `risk_result_id` | Readable prefix plus `@` plus a sha256 digest of (risk configuration version, threshold configuration, context digest). |
| `status` | `recorded` or `withheld` — `domains.RISK_STATUSES`, reused. |
| `evaluation_state` | `fully_evaluated` / `partially_evaluated` / `context_unavailable` / `not_evaluable`. |
| `risk_level` | One of `LOW, MEDIUM, HIGH, CRITICAL`, or `None`. |
| `risk_score` | The exceedance probability, or `None`. |
| `risk_score_type` | `normal_approximation_measured_sigma`. |
| `assessment` | The `risk.RiskAssessment` Phase 1/2 already defined. |
| `threshold`, `threshold_units`, `threshold_source`, `threshold_policy` | The threshold and its declared status. |
| `threshold_configuration`, `risk_configuration_version` | Which configuration produced this. |
| `band_edges`, `band_labels` | Copied from the policy, so a classification is auditable. |
| `residual_sigma`, `residual_sigma_source` | The measured spread and how it arrived. |
| `forecast_id`, `forecast` | The Phase 5 forecast this was computed from. |
| `signals` | The evaluated `SignalEvaluation` set. |
| `escalations` | One `EscalationEvaluation` per rule, fired or not. |
| `explanation` | The lines, all derived. |
| `uncertainty` | Phase 5's, or absent. |
| `provenance` | A Phase 1 `ProvenanceRecord`. |
| `provenance_chain` | The flattened cross-phase chain. |
| `gis_context`, `historical_context` | Serialised, including unavailability. |
| `context_digest` | sha256 over the evaluated signals. |
| `synthetic_demo`, `data_status`, `disclaimer` | Inherited and never downgraded. |
| `production_ready_claimed` | Always `False`. |
| `risk_contract_version` | `navya-phase6-risk/v1`. |

Two projections reuse existing platform types rather than adding a third shape:

- `to_forecast_output(base)` → `contract.ForecastOutput`, Phase 5's platform
  forecast, with the band and priority filled in from
  `contract.priority_for_risk_level`.
- `to_risk_score_record()` → `domains.RiskScoreRecord`, with `assessed_at` set to the
  **forecast origin**, not the wall clock.

---

## 12. Errors versus states

This is the distinction the whole boundary turns on.

**Raised** — a contract violation. A mistake in what the caller passed. A caller
that is told is better than a caller that gets a plausible number.

**Returned** — an availability condition. An honest state of the world.

```
assess_risk          raises RiskBoundaryError subclasses; returns RiskResult
                     with status='withheld' for availability conditions
assess_risk_safe     converts the former into the latter
risk_from_error      builds the withheld result from a caught error,
                     naming error.reason
```

All twelve errors carry a stable, machine-readable `reason` tag with no spaces, so a
refusal can be counted rather than parsed:

| Error | `reason` | Raised when |
| --- | --- | --- |
| `MissingForecastError` | `missing_forecast` | No forecast was supplied. |
| `InvalidForecastError` | `invalid_forecast` | Not a `ServedForecast`/`ForecastInference`; not `ready`; `production_ready_claimed`; no inference. |
| `MissingRiskContextError` | `missing_risk_context` | No context. |
| `InvalidUnitsError` | `invalid_units` | Unrecognised unit, wrong dimension, or a `valid` signal with no unit. |
| `InvalidThresholdError` | `invalid_threshold` | Non-finite or non-positive threshold. |
| `EntityMismatchError` | `entity_mismatch` | Context, signal, or event names another station. |
| `FutureContextError` | `future_context` | A reading or event after the origin; a naive instant; `assessed_at` before the origin. |
| `StaleContextError` | `stale_context` | A stale reading where staleness is not permitted. |
| `UnsupportedContextError` | `unsupported_context` | An unknown quantity, availability state, or a non-`FloodEvent` in the event register. |
| `InvalidRiskConfigurationError` | `invalid_risk_configuration` | Duplicate rule ids, bad comparison, non-ascending edges, foreign band labels, unusable policy. |
| `GisContextUnavailableError` | `gis_context_unavailable` | *Declared, not raised* — see below. |
| `InvalidRiskCalculationError` | `invalid_risk_calculation` | The probability could not be computed from what was supplied. |
| `StaleContextRuleError` | `stale_rule_signal` | A `required=True` rule whose signal is stale. |

Two of the thirteen are **declared but not currently raised**, and saying so is the
honest description rather than a way round it:

- `GisContextUnavailableError` — GIS context unavailability is represented as a
  *state* (`GisContext.available is False`, with its reason string on the result and
  the explanation), not as a refusal. A future caller who requires spatial evidence
  before a risk may be issued has the error class ready; Phase 6 itself does not
  impose that requirement.
- `StaleContextError` — staleness is a state, so a stale reading becomes
  `usable=False` with `value=None` and the result is `partially_evaluated`, not
  refused. The one place staleness *is* fatal is a `required=True` escalation rule,
  which raises `StaleContextRuleError`.

Both carry stable `reason` tags and both are covered by the contract-description
test, which asserts that every declared error exists, is a `RiskBoundaryError`, and
has a unique reason tag — so they cannot rot unnoticed.

No error path returns `0`, `null`, or `low risk`. There is a test that walks every
refusal route and asserts `status == 'withheld'`, `risk_level is None`,
`risk_score is None`, and `production_ready_claimed is False` for each.

---

## 13. Explanation

Every line of the explanation is derived from a value that was actually evaluated.
There are no templates, no canned strings, and no line that can describe a signal
the assessment did not read.

A real explanation, from this phase's fixture:

```
forecast 3.2393323679390944 m for target_water_level_6h at SYNTHETIC-STATION-0001,
origin 2024-01-04T05:00:00+00:00, horizon 6h, prediction instant
2024-01-04T11:00:00Z, from random_forest/random_forest-target_water_level_6h-6h-
seed20240917 (version random_forest/navya-model/v1/navya-features/v1/seed20240917,
artifact random_forest-target_water_level_6h-6h-seed20240917@28efb1fd998e)
threshold 3.5 m from DEMO value chosen for the synthetic pipeline; NOT an official
flood stage; band edges [0.1, 0.3, 0.6, 0.9] map to ['LOW', 'MEDIUM', 'HIGH',
'CRITICAL']; policy status 'pending' (NOT an approved flood stage - bands are demo
values)
residual spread 0.2312684189288912 taken from measured_residuals(n=36); exceedance
probability P(target > threshold) = 0.12984553446633207 under method
'normal_approximation_measured_sigma'
the probability falls in band MEDIUM (of ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'])
context evaluated at state fully_evaluated with 2 declared signal(s): missing=0,
not_applicable=0, stale=0, unavailable=0, valid=2
signal 'rainfall_3h' read 63.2 mm (rainfall, synthetic gauge reading) at
2024-01-04T05:00:00+00:00
signal 'water_level_now' read 2.9 m (water_level, synthetic gauge reading) at
2024-01-04T05:00:00+00:00
spatial exposure context unavailable: NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT
REQUIRED
historical flood context unavailable: no flood event register exists in this
repository, and none may be invented
no escalation rules are configured, so the context informed the explanation and the
evaluation state but could not change the band
no uncertainty is available for this forecast, and none is invented: Phase 5
produces one value and has no observed counterpart for it. A residual spread would
describe past errors on a split, not a bound on this value.
the threshold policy is still pending approval, so this level is a demo band and
carries no official meaning
THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL
OBSERVATION DATA.
```

A signal that could not be read gets a different line, naming the state:

> signal 'inflow' not evaluated: unavailable — the inflow telemetry provider did not
> answer; a zero is not a reading

### Uncertainty

If Phase 5 supplies an `Uncertainty`, it is carried through and referenced. If it
does not — as in this repository — `uncertainty.status` stays `unavailable` and the
explanation says so with Phase 5's own reason:

> no uncertainty is available for this forecast, and none is invented: Phase 5
> produces one value and has no observed counterpart for it. A residual spread would
> describe past errors on a split, not a bound on this value.

There is no confidence percentage anywhere in this phase, because there is nothing
measured to put one behind.

---

## 14. Provenance

`RiskResult.provenance` is a Phase 1 `ProvenanceRecord`, rebuilt from the forecast's
provenance so the risk record carries the same dataset claims the forecast did —
including `is_synthetic`, `metrics_label`, `missing_fields` and the disclaimer. The
split is re-materialised as typed `SplitBoundaries`, which is what lets the Phase 2/3
causal guarantees survive into the risk record: train, then validation, then test,
no overlap.

`RiskResult.provenance_chain` is the flattened cross-phase chain, one level deep, so
a single serialised object answers "where did this come from" without walking five
classes:

```json
{
  "risk_contract_version": "navya-phase6-risk/v1",
  "serving_contract_version": "navya-phase5-serving/v1",
  "risk_configuration_version": "navya-phase6-test-config/v1",
  "threshold_configuration": "DEMO value chosen for the synthetic pipeline; NOT an official flood stage",
  "threshold_policy_status": "pending",
  "threshold_source": "DEMO value chosen for the synthetic pipeline; NOT an official flood stage",
  "risk_score_type": "normal_approximation_measured_sigma",
  "forecast_artifact_id": "random_forest-target_water_level_6h-6h-seed20240917@28efb1fd998e",
  "model_family": "random_forest",
  "model_id": "random_forest-target_water_level_6h-6h-seed20240917",
  "model_version": "random_forest/navya-model/v1/navya-features/v1/seed20240917",
  "feature_digest": "28eeb72bbf31a3a90afb772b25fa6bf1a15f820a1998a6f16536aa8c08ad9d9d",
  "forecast_timestamp": "2024-01-04T11:00:00Z",
  "forecast_horizon": "6h",
  "entity": "SYNTHETIC-STATION-0001",
  "gis_context_provenance": null,
  "gis_context_available": false,
  "historical_context_provenance": null,
  "historical_context_available": false,
  "risk_context_disclaimer": "THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION DATA."
}
```

Every required provenance item is present: forecast artifact id, model family and
version, feature digest, forecast timestamp and horizon, entity, risk configuration
version, threshold configuration, GIS provenance, historical provenance, and
synthetic/demo status. Unavailable contexts appear as `null` with an explicit
`available: false` flag — never as an empty string or an omitted key.

### Unavailability is represented, not omitted

```python
GisContext(available=False, provider="...", provenance=None, reason="NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED")
HistoricalContext(available=False, provider="...", events=(), reason="no flood event register exists in this repository, and none may be invented")
```

The GIS reason is the same string `feature_registry` already uses for every missing
attribute, so a reader sees one consistent marker for "a human has to supply this".

---

## 15. Determinism

Identical forecast + context + configuration + threshold configuration ⇒
byte-identical decision-relevant output.

- Signals are sorted by name; rules are sorted by `rule_id`.
- `context_digest` is sha256 over the evaluated signals, so the same evidence
  assembled in a different order digests the same.
- `risk_result_id` is a readable prefix plus `@` plus sha256 of (risk configuration
  version, threshold configuration, context digest) — short enough to read, unique
  enough to cite.
- `assessed_at` defaults to the forecast origin. **No clock is read**, so the only
  way two assessments of the same inputs could differ is if the inputs did.

Tested three ways: repeated calls, reversed construction order, and two
configurations differing only in their version string.

---

## 16. Tests

Three modules, 207 tests, all behavioural — no weakened assertions, no mocks of the
code under test, and no skips.

| Module | Tests | Covers |
| --- | --- | --- |
| `test_hydro_forecast_risk.py` | 67 | Forecast integration, classification per band, threshold validation, provenance, determinism, production safety, uncertainty, platform projections, the safe wrapper, the contract description. |
| `test_hydro_risk_context.py` | 101 | Availability vocabulary, unit safety, temporal safety, entity safety, freshness, escalation rules, explanation derivation, GIS and historical boundaries, the contract description. |
| `test_hydro_forecast_risk_leakage.py` | 39 | The leakage, no-training and explanation-honesty guarantees below. |

Shared fixtures live in `tests/hydro_phase6_fixtures.py`. Every threshold used in a
test is **derived**, never hard-coded: `threshold_for_probability` bisects
`risk.exceedance_probability` for a chosen probability, and `threshold_for_band` uses
a probability comfortably inside each band (LOW 0.05, MEDIUM 0.2, HIGH 0.45,
CRITICAL 0.8). The edges are where floating-point comparison is least forgiving, and
a test should fail on a wrong band, never on a rounding accident.

### Leakage guarantees, each with its own test

- a reading after the origin is refused, and so is one minute *inside* the forecast
  window;
- an event that starts after the origin is refused; one that spans it is accepted;
- one station's context cannot be scored against another station's forecast, and two
  independently served forecasts are deliberately crossed to prove it;
- a signal carrying a foreign station label is refused at construction;
- a foreign historical event is refused;
- `no_fitting` over the assessment reports `touched == []` — with each route into
  training checked separately, so a failure names the route that opened;
- manifests, the training audit, the dataset registry and every split matrix are
  digested before and after: unchanged, including on every error path;
- the artifact store's tuple identity and payloads are unchanged after a batch
  covering all four bands, all three context states and four error routes;
- `RandomForestRegressor.predict` and the model wrapper's `predict` are both replaced
  with refusals: the assessment is unchanged, so Phase 6 reads the forecast rather
  than re-scoring it;
- `assess_risk`'s parameter set is asserted, which is what structurally prevents it
  from reading training data at all;
- the split boundaries are asserted non-overlapping on the risk record, and the
  residuals come from the validation and test splits only.

Two of these are structural rather than behavioural, and the module says so: a
behavioural test can only catch the leaks somebody thought of. `assess_risk` takes no
dataset, no frame, no targets and no estimator, so it *cannot* read training data —
that is checked from the signature because it is a stronger claim than any
behavioural test could make.

### The explanation-honesty guarantees

The same module carries four tests on a rule that no test in the repository
previously enforced: **an explanation line may not claim something the result does not
contain.**

- a band line exists only when a band was assigned;
- a "signal … read …" line exists only for a signal that was read, and the test
  re-derives that from `SignalEvaluation.usable` rather than trusting the prose;
- the pending-threshold disclaimer is phrased as "this level" only when there is a
  level, and otherwise says no level it could assign would carry official meaning;
- the threshold line says the edges "do not describe" the bands when the classifier
  rejected the arity, rather than printing "map to" for a mapping that does not
  exist.

These four were added after the first two of them were found by inspection while
writing §9, and the fixes they cover are described next.

---

## 17. Source defects found and fixed

### In Phase 1, found while building Phase 6

`provenance.ProvenanceRecord.to_dict()` called `dataclasses.asdict(self.split)`.
That raises `TypeError` when `split` is a plain mapping — which is exactly what a
Phase 5 result carries after serialisation and reloading. Phase 6 hits that path on
every risk result, so the defect was latent, not hypothetical.

The fix is the minimal widening:

```python
"split": asdict(self.split) if is_dataclass(self.split) else dict(self.split)
```

The typed path is unchanged; the mapping path now serialises instead of crashing.
Phase 6 additionally re-materialises the mapping as typed `SplitBoundaries` via
`_rebuild_split`, matching on key set only — it does not trust the values it did not
produce.

Verified against the affected Phase 1 tests before and after the change.

### In Phase 6, found by writing §9

Inspecting what the explanation prints for a policy whose band edges the classifier
cannot interpret turned up two false statements:

1. the threshold line asserted `band edges [0.1, 0.3] map to ['LOW', 'MEDIUM',
   'HIGH', 'CRITICAL']` — a mapping of four labels that two edges do not describe;
2. the pending-policy line read "so this level is a demo band" on a result with
   `risk_level is None`.

Both are the failure mode the requirements single out: an explanation claiming a
contributor that did not contribute. Both are now conditional on what the result
actually contains, and both have tests.

---

## 18. Verified numbers, in one place

From this phase's fixture: a real Phase 5 `random_forest` run, served at
`2024-01-04T05:00:00+00:00`, scored on held-out residuals.

| Quantity | Value |
| --- | --- |
| Prediction | `3.2393323679390944` m |
| Target / units / horizon | `target_water_level_6h` / `m` / `6h` |
| Prediction instant | `2024-01-04T11:00:00Z` |
| Model version | `random_forest/navya-model/v1/navya-features/v1/seed20240917` |
| Feature digest | `28eeb72bbf31a3a90afb772b25fa6bf1a15f820a1998a6f16536aa8c08ad9d9d` (35 features) |
| Residual spread | `0.23126841892889116` (n=36, `measured_residuals`) |
| Residual bias | `+0.31713755857904724` |
| RMSE (for contrast) | `0.3906092880928549` |
| RMSE / sigma | `1.689` |
| Threshold | `3.5` m, DEMO, policy status `pending` |
| Probability | `0.12984553446633207` |
| Band | `MEDIUM` |
| Evaluation state | `fully_evaluated` (2 valid signals) |
| Uncertainty | `unavailable`, with Phase 5's own reason |
| `production_ready_claimed` | `False` |

Derived thresholds that resolve each band for this prediction and spread:

| Band | Probability | Threshold (m) |
| --- | --- | --- |
| LOW | 0.05 | `3.6197350656136136` |
| MEDIUM | 0.2 | `3.4339727799644857` |
| HIGH | 0.45 | `3.2683938689467427` |
| CRITICAL | 0.8 | `3.044691955913703` |

---

## 19. Known limitations

1. **The default answer is an unavailable assessment.** No approved flood threshold
   exists, so `config.RiskPolicy` has nothing usable. That is correct behaviour, and
   it means the end-to-end path is currently demonstrated on DEMO thresholds only.
2. **No real residual spread reaches production code.** The caller must supply
   residuals from a held-out split. Phase 4 writes aggregate metrics, not residuals,
   and Phase 6 will not read them backwards out of a summary statistic.
3. **The context layer cannot influence the band without configured rules.** No
   rules ship by default, so context currently contributes availability, explanation
   and evaluation state only.
4. **The temporal boundary is the origin, which is conservative.** A reading taken
   shortly *after* the origin is refused even though a live system would have it. That
   is the right default for an auditable offline assessment and the wrong one for an
   operational one; an operational deployment would need a different, explicitly
   declared contract.
5. **`GisContext` has no station label.** Documented in §7. Spatial context is
   reported but never evaluated.
6. **Historical context is an interface.** `domains.FloodEvent` exists; no register
   does. No flood event is invented.
7. **No uncertainty is available.** Phase 5 produces one value with no observed
   counterpart. Phase 6 reports that rather than manufacturing a confidence.
8. **Only `random_forest` and `naive` are exercised.** XGBoost, Keras/TensorFlow and
   PyTorch are unavailable in this environment, so those families cannot be served
   and cannot be risk-assessed here.
9. **Learned models cannot be served from a manifest directory alone.** A fitted
   scaler/imputer must be supplied via `ArtifactStore.with_preprocessing`. Documented
   Phase 5 limitation, unchanged.

---

## 20. Team boundaries

| Seam | Status on this branch |
| --- | --- |
| `ai-service/app/schemas/models.py` | Absent — team-owned integration point. |
| `ai-service/app/engines/base.py`, `factory.py` | Absent — team-owned engine registry. |
| `backend/src/types/contract.ts`, `optimization.ts` | Absent — team-owned platform types. |
| `frontend/src/types/ai.ts`, `services/aiService.ts` | Absent — team-owned frontend contract. |
| `ai-service/requirements.txt` | Absent — team-owned dependency manifest. XGBoost, Keras/TensorFlow and PyTorch are blocked on a dependency owner. |
| `backend/package.json`, `frontend/package.json` | Absent — team-owned. |
| `docs/navya-forecast/` | Absent — team-owned. |
| `forecastingMergeupdate/`, `forcastingMergeupdate/` | Untouched, and deliberately untracked. |

GIS, IoT, quantum-service, QUBO/optimisation, deployment and `.github/` were not
modified.

### The one-line version

Phase 6 turns a validated forecast into an auditable risk band, using one existing
classifier, caller-measured residuals, and a typed context that says out loud what it
could not read — and it refuses every question it cannot answer honestly.

### The disclaimer, one final time

`THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL
OBSERVATION DATA.`