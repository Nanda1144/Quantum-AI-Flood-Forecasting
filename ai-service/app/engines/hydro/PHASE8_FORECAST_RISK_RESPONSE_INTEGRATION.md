# Phase 8 — Forecast → Risk → Response Integration

**Module:** `ai-service/app/engines/hydro/integration_assessment.py`
**Contract version:** `navya-phase8-integration/v1`
**Owner:** Navya (ForecastingEngine seam)
**License:** Apache-2.0
**Branch:** `feature/navya-forecast`
**Builds on:** Phases 1–7 (commits `fb28e5c`, `9f66802`, `fcd407b`, `a55bcd5`, `4fd40e4`, `908a970`, `a1f2c52`)

---

## 1. What this phase is

Phase 8 is the boundary where three already-produced results become one auditable
record.

```
Phase 5  ServedForecast
     v
Phase 6  RiskResult
     v
Phase 7  ResponseDecision
     v
Phase 8  IntegratedForecastAssessment
     v
Deterministic serialized analytical result
```

`IntegratedForecastAssessment` answers, from a single object: what forecast was
produced, which model and artifact produced it, what risk assessment followed, what
response decision followed that, what evidence was available, what evidence was not,
why the response was produced or withheld, and how the three layers are chained
together.

Everything in this document is verified against a live run of the module. The
numbers quoted in sections 9, 10, 15 and 19 are the actual output, not illustrations.

## 2. What this phase is not

It is not a second forecast engine, a second risk engine, or a second response engine.
There is no threshold arithmetic, no normal CDF, no sigma estimation, no band
classification, no policy mapping and no rule evaluation here. Every one of those
belongs to the layer that already owns it.

That is enforced structurally rather than by intention. `integrate` accepts only
already-built layer results and has nothing to compute with. There is no function in
the module that takes a prediction and returns a probability. If a future editor needs
a new field, they must go and ask the owning layer for it.

It is not a downgrade path. A `ResponseDecision` of `WITHHELD` enters as `WITHHELD`
and leaves as `WITHHELD`; a `REVIEW_WARNING` leaves as `REVIEW_WARNING`. The
integration status is a separate axis and never rewrites the decision it reports. The
one place Phase 8 is deliberately *more* conservative than the layers below it is the
status, never the recommendation.

It is not a service. This branch has no HTTP boundary — `app/api/`, `app/core/` and
`app/schemas/` are empty directories — so this is a pure domain contract with
deterministic serialization. Manufacturing a web framework here because another branch
has one would be inventing infrastructure, not integrating.

## 3. The data contract

`IntegratedForecastAssessment` is a frozen dataclass with **47 fields**:

| Group | Count | Notes |
| --- | --- | --- |
| Identity and status | 4 | `integration_id`, `integration_status`, `integration_reason`, `error_reason` |
| Layer results | 4 | `forecast`, `risk`, `response`, `chain` |
| Provenance and evidence | 4 | `provenance`, `evidence_availability`, `available_inputs`, `unusable_context` |
| Explanation | 1 | `explanation` |
| Forecast projections | 11 | id, status, origin, horizon, prediction, units, model, version, artifact |
| Risk projections | 7 | result id, status, evaluation state, level, score, score type, result id |
| Response projections | 3 | decision, status, decision id |
| GIS and history | 4 | carried forward verbatim |
| Timing | 1 | `integrated_at` |
| Authority flags | 2 | permanently `False` |
| Data provenance | 3 | `synthetic_demo`, `data_status`, `disclaimer` |
| Contract versions | 5 | integration, serving, risk, response, response context |

The module exports **27 public names**.

The three layer results are held **by reference**, as the objects their own layers
produced. Nothing is copied out of them, so no projection can drift from its source and
no upstream object has to be duplicated to be recorded.

## 4. Why `COMPLETE` is hard to reach, on purpose

`COMPLETE` requires that every declared contextual input be usable. In this repository,
population and infrastructure exposure have **no provider at all**, so an integration
built from repository data alone tops out at `PARTIAL`.

That is not a limitation of this module; it is the state of the platform. Reaching
`COMPLETE` requires a caller to supply both exposure providers explicitly, which is a
claim the caller then owns. The alternative — treating absent exposure as "nothing to
report" — would let a result with no exposure data claim to be the most complete one
available, which is exactly backwards.

Verified: `_build_repository_chain()` returns `PARTIAL` with two unusable exposure
records. Only `complete_exposure()` reaches `COMPLETE`.

Nothing here invents an exposure value. `ExposureAvailability` has no value field and
Phase 8 does not add one, so `risk × population` cannot be written here at all.

## 5. The four statuses

There is deliberately no `FAILED` and no `ERROR`. A failure is a raised exception or a
recorded `error_reason`, never a status a caller could mistake for an analytical
outcome. There is also no `COMPLETE_WITH_ERRORS`: an integration that hit a problem and
calls itself complete is how a broken chain gets shipped.

| Status | Meaning |
| --- | --- |
| `COMPLETE` | Every layer produced a valid result and every declared contextual input was usable. |
| `PARTIAL` | The analytical chain is valid, but at least one declared contextual input was not usable. The upstream results are preserved as they are, with the gaps named. |
| `WITHHELD` | A valid chain exists, but no response interpretation may be made from it — because Phase 7 withheld, because Phase 6 read no context at all, or because Phase 7 produced no decision. |
| `NOT_EVALUABLE` | The forecast or risk contract itself cannot be evaluated from what was supplied: no forecast, a refused forecast, no risk result, or a risk result carrying no level. |

`WITHHELD` is the only word shared with `RESPONSE_STATES`, and it means the same thing
in both. That is asserted as a test.

## 6. Status is derived, never supplied

`integrate` accepts **no** `integration_status` argument. A caller cannot assert that
its chain is `COMPLETE`, so no bug in an upstream layer can be papered over by
declaring the integration fine.

The derivation order is fixed and tested — first unmet condition wins, exactly as
Phase 7's withholding order does. There are **10 steps**:

1. no forecast
2. forecast status is not `ready`
3. `ready` forecast carrying no inference
4. no risk result
5. risk result with no level, not recorded, or not evaluable
6. no response decision
7. response decision withheld
8. risk `context_unavailable`
9. risk `partially_evaluated` or any unusable contextual input
10. otherwise `COMPLETE`

Two properties are load-bearing. Nothing is ever downgraded into `COMPLETE`, because
the only route to `COMPLETE` is step 10, reachable only after every earlier condition
has passed. And the status never rewrites a response decision: step 8 reports
`WITHHELD` while leaving the `ResponseDecision` exactly as Phase 7 built it.

Note the ordering of step 8 against the exposure checks in step 9. A chain over a
`context_unavailable` risk result is `WITHHELD` **even when both exposure providers
were declared available**, because an unreadable signal context is a different gap from
unavailable exposure, and `COMPLETE` requires both to be clear.

## 7. Why repository data tops out at `PARTIAL`

There is no population provider and no infrastructure provider in this repository. A
chain built from repository data alone therefore always carries two unusable exposure
records and lands in `PARTIAL`.

That is the honest result and it is asserted as such:
`test_repository_data_alone_never_reaches_complete`.

`PARTIAL` is reached for two quite different reasons — a declared exposure input had no
value, versus Phase 6 never finished evaluating its context — and a reader must be able
to tell them apart without re-running Phase 6. The unusable records and the reasons
stay distinct rather than collapsing into a single tally.

## 8. Errors

`IntegrationBoundaryError(ValueError)` is the new base. It is deliberately **not** a
`RiskBoundaryError` or a `ResponseBoundaryError`: a caller that catches the risk
taxonomy to handle "the risk layer refused" must not silently swallow "the integration
refused".

**Five new errors**, each with a stable `reason` tag:

| Error | `reason` |
| --- | --- |
| `InvalidForecastResultError` | `invalid_forecast_result` |
| `InvalidResponseDecisionError` | `invalid_response_decision` |
| `LayerSequenceError` | `layer_sequence_error` |
| `ChainMismatchError` | `chain_mismatch` |
| `InvalidIntegrationStatusError` | `invalid_integration_status` |

**Three errors reused verbatim**, because they encode rules identical to Phase 8's own
and there is no reason to have two of them:

| Error | `reason` | Source |
| --- | --- | --- |
| `InvalidRiskResultError` | `invalid_risk_result` | Phase 7 |
| `EntityMismatchError` | `entity_mismatch` | Phase 6 |
| `FutureContextError` | `future_context` | Phase 6 |

One taxonomy, one set of strings. Two classes with the same reason tag would make
`except` clauses ambiguous.

Only `integrate_safe` catches broadly, and it records the reason rather than
discarding it. A test asserts there is exactly **one** broad handler in the module and
that it delegates to `integration_from_error`.

## 9. `integrate` accepts only `ServedForecast | None`

A bare `ForecastInference` is refused on purpose. It carries no forecast id and no
serving status, so accepting it would force this module to invent the two facts the
chain is built on. A caller holding only an inference has a forecast and should ask
Phase 5 to serve it.

The risk layer is validated by duck typing over the seven attributes Phase 8 reads,
listed once in `_RISK_LAYER_FIELDS` so validation and the error path's acceptance
cannot drift apart. The response layer is validated by `isinstance`, since
`ResponseDecision` is the sole authority for its own shape.

## 10. The three-slot chain

The chain is always three slots in the order `("forecast", "risk", "response")`,
whether or not a layer produced anything.

An absent layer is a slot with `status is None`, **not** a missing slot. That is the
point: a chain that simply omits the response because none was produced looks identical
to a chain that never had one, and the second is the kind of bug this module exists to
make visible. Three fixed slots mean "Phase 7 produced nothing" is assertable in one
comparison.

Presence is keyed on `status`, not on `layer_id`. A refused Phase 5 serving **is** a
result: it produced `status='artifact_unavailable'` and no forecast id. Keying presence
on the id would report "no forecast layer ran" when the layer in fact ran and refused.

`chain_intact` is `True` when the first absent slot ends the chain. `integrate` refuses
to build a chain with a hole in the middle, so a consumer can assert on this without
trusting that.

Verified on the repository chain: all three slots present, ids copied verbatim from the
layers that published them —

```
forecast  SYNTHETIC-STATION-0001-target_water_level_6h-6h-2024-01-04T05:00:00Z-random_forest
risk      risk-SYNTHETIC-STATION-0001-...-random_forest@a2cdb10a05ae
response  response-SYNTHETIC-STATION-0001-MEDIUM-navya-phase7-demo-policy/v1@da1c357f9202
```

## 11. Projections, not copies

The flat fields that repeat a value already on a layer exist so a reader can answer
"which forecast, which risk, which response" without walking three nested structures —
including on a `NOT_EVALUABLE` chain where there is no nested structure to walk.

They are **projections, and `__post_init__` proves it**. Each one is checked against
the object it came from at construction time, so a projection cannot disagree with its
source. This is not a defensive check for its own sake: if a projection could disagree,
the record would be able to report one thing while holding another.

A test builds each projection by hand with a wrong value and confirms the constructor
refuses — `entity`, `risk_level`, `risk_score`, `response_decision`, `artifact_id` and
`integrated_at` all raise.

The four derived flags — `disclaimer`, `synthetic_demo`, `data_status` and
`integrated_at` — are validated as a group, since they are all derived from the layers
and a record that disagreed about one of them had not been built by this module at all.

## 12. Entity safety

Phase 6 checks the request against the forecast, and Phase 7 checks the request against
the risk result. Phase 8's check is different in kind: it verifies that the three
results assembled into one object agree **with each other**, which neither of them can
do because neither can see the whole chain.

If `forecast.entity != risk.entity` or `risk.entity != response.entity`, the
integration is refused with `EntityMismatchError`. The refusal names every layer it
compared.

There is **no nearest-station rule and no geographic inference here.** If the names are
not the same string, the answer is a refusal — because deciding that Station A and
Station B are probably the same catchment is a guess about the physical world made by
an integration layer, on a repository with no station registry to ground it in. No
entity is ever overwritten to make a mismatch disappear.

## 13. Temporal safety

Three facts must match across layers: the forecast id, the origin instant and the
horizon. Any disagreement means the chain stitches together results from two different
forecasts, and an object reporting them together would look self-consistent while
describing a mixture.

An origin that is **later** than the forecast's is reported as `FutureContextError`;
an origin that is **earlier** is reported as `ChainMismatchError`. That split is
deliberate — the first is the temporal-violation case and deserves the same reason tag
Phases 6 and 7 use for it.

Naive datetimes are refused. An instant with no offset cannot be compared against the
forecast origin it must match.

No horizon, origin or target is recomputed, rounded or reinterpreted anywhere.

## 14. No clock, no randomness

`integrated_at` is the forecast origin, or `None` when there is no forecast. It is never
a reading of the current time. With no forecast there is no instant to attribute the
integration to, and `None` says that rather than substituting an arbitrary one.

An integration is attributed to the instant its forecast was made, so re-running the
integration over unchanged evidence produces an unchanged timestamp. A test runs the
integration twice and compares both `integrated_at` and the full `to_json()`.

`integration_id` is a readable prefix plus a sha256 over the chain's own content:
`integration-{entity}-{status}@{12 hex digits}`. No uuid, no counter, no clock.

**One finding worth recording.** Phase 6's `risk_result_id` is a digest over the
assessment's *configuration* — forecast, threshold policy, context digest — so a MEDIUM
and a HIGH assessment of the same forecast under the same policy deliberately share it.
The id answers "which question was asked", not "what was found". That is correct on
Phase 6's part.

It does mean the layer ids alone cannot distinguish the two outcomes. The Phase 7
`decision_id` happens to embed the risk level, so integration ids differed anyway — but
an identity that is correct by luck is not an identity. `default_integration_id`
therefore hashes the risk outcome (level, score, evaluation state, status) explicitly.
A test asserts the risk-layer ids are equal for MEDIUM and HIGH while the integration
ids are not, so the distinction cannot be reintroduced by accident.

## 15. Verified integration output

Every row below is real output from the module, built through the real Phase 5 `serve`,
real Phase 6 `assess_risk` and real Phase 7 `decide_response`.

| Chain | Status | Risk level | Response decision | Unusable inputs |
| --- | --- | --- | --- | --- |
| Both exposure providers declared | `COMPLETE` | MEDIUM | `HEIGHTENED_MONITORING` | 0 |
| Repository data only | `PARTIAL` | MEDIUM | `HEIGHTENED_MONITORING` | 2 |
| One usable, one not | `PARTIAL` | MEDIUM | `HEIGHTENED_MONITORING` | 1 |
| `partially_evaluated` context | `PARTIAL` | MEDIUM | `HEIGHTENED_MONITORING` | 0 |
| Empty response policy | `WITHHELD` | MEDIUM | `WITHHELD` | 2 |
| `context_unavailable` risk result | `WITHHELD` | MEDIUM | `WITHHELD` | 0 |
| Risk result with no level | `NOT_EVALUABLE` | `None` | `WITHHELD` | 2 |
| Refused Phase 5 forecast | `NOT_EVALUABLE` | `None` | `None` | 0 |
| No layers at all | `NOT_EVALUABLE` | `None` | `None` | 0 |

The repository chain in detail:

```
integration_id      integration-SYNTHETIC-STATION-0001-PARTIAL@5639a65c2860
prediction          3.2393323679390944 m
forecast_origin     2024-01-04T05:00:00+00:00
forecast_horizon    6h
model_id            random_forest-target_water_level_6h-6h-seed20240917
model_version       random_forest/navya-model/v1/navya-features/v1/seed20240917
artifact_id         random_forest-target_water_level_6h-6h-seed20240917@28efb1fd998e
risk_level          MEDIUM
risk_score          0.1999999999999995 (normal_approximation_exceedance_probability)
threshold_policy    pending
evidence            valid=2, missing=0, unavailable=0, not_applicable=0, stale=0
available_inputs    rainfall_3h, water_level_now
data_status         synthetic_demo
```

Note `threshold_policy='pending'`. The risk level above is a demo value with no official
meaning, and the explanation says so on every record that carries it.

## 16. The availability vocabulary is preserved verbatim

Phase 6's states — `valid`, `missing`, `unavailable`, `not_applicable`, `stale` — are
reused unchanged through Phase 7's exposure records and are never mapped to `0`,
`False`, `safe`, `low` or `none`.

They are not collapsed into each other. `missing`, `unavailable` and `stale` stay three
separate things, because they say different things: "we did not look", "we looked and
there was none", and "we looked and what we found was too old to use". The first and
the third are not evidence of safety, and `stale` carries data-quality information the
other two do not.

Every unusable record carries a reason, and the explanation states that an unavailable
input is "absent from the assessment, not counted as zero and not read as reassuring".

**A limitation worth recording.** `ExposureAvailability` has no `observed_at` or
`as_of` field, so freshness cannot be expressed on the record itself. That is why
`stale` must be declared **upstream** by whoever holds the provider — Phase 8 cannot
derive it and does not pretend to. This limitation is carried forward from Phase 7
unchanged.

## 17. No composite score, no exposure values

There is **no** `integration_score`, `final_risk_score`, `danger_score`, `severity_score`
or `response_score` field. Phases 6 and 7 already declined to invent a weighted
composite, and a third layer that added one would have to invent it again — with less
justification, sitting furthest from the evidence. A consumer wanting a single number
must decide how to weigh risk against exposure, and that decision belongs to them,
visibly.

The guarantee is structural rather than aspirational: the module imports no
`numpy`, `scipy`, `statistics` or `math`, and calls no `sum`, `mean`, `weighted_sum`,
`np.dot` or `np.average`. There is nothing here that could compute a composite.

For exposure, the structural guarantee is the same: `ExposureAvailability` has no
`value` field and Phase 8 adds none, so `risk × population` has nowhere to be written
even by accident.

## 18. No GIS, no quantum, no service

**GIS and historical availability are carried forward from Phase 6 verbatim.** No
spatial conclusion is drawn anywhere in this module. The repository has no GIS
implementation, so `gis_reason` reads as the absent marker
`NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED`, and `historical_reason`
carries Phase 6's more specific wording — *"no flood event register exists in this
repository, and none may be invented"*.

Both specific reasons are forwarded rather than replaced with the generic marker,
because they say *what* is missing, which is more useful than saying only that something
is.

The module imports no geospatial or ML-GIS package, and computes no `haversine`,
`elevation`, `river_distance`, `floodplain` or `nearest_station`.

**No quantum and no optimisation.** No QUBO, no quantum-service call, no sensor
placement, no combinatorial optimisation. Choosing what to do about a catchment remains
the optimisation layer's job, on the far side of this one.

**No service boundary.** `app/api/`, `app/core/` and `app/schemas/` are empty
directories on this branch, so Phase 8 is a pure domain contract. No framework, router
or endpoint is created here, and no database driver is imported. The explanation says
so on every record, so a serialized artifact carries the limitation with it.

## 19. The disclaimer survives every path

The rule that is easy to get wrong.

`risk_from_error` builds a `RiskResult` with `disclaimer=""`, because an error path has
no data to describe and an empty string is the honest answer *there*. Left alone, an
integration wrapping that result would carry an empty disclaimer and read as though no
synthetic-data warning were needed.

So the disclaimer is resolved by taking the **first non-empty** one from response, then
risk, then the forecast, and falling back to the canonical sentence when all of them
are empty:

```
THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION DATA.
```

The warning survives **every** path. Verified present and identical to the canonical
sentence on all seven representative chains plus the empty chain, in the record, in
`to_dict()` and in the explanation. The constructor refuses an empty or whitespace-only
disclaimer outright.

`synthetic_demo` defaults to `True`, not `False`: an integration whose layers carry no
data status has not established that its data is real, and reporting `False` would be a
claim about the world that no layer made.

## 20. Determinism and serialization

`to_json()` uses `sort_keys=True` and deliberately omits `default=`, so an unserialisable
value fails loudly instead of being quietly stringified into something that looks like
data.

What is serialized is chosen deliberately. The full layer objects stay reachable on the
record; what goes into the serialized form is each layer's **summary** plus every fact
the contract promises to answer. Dumping the nested objects whole would triple the size
of every record and reproduce Phase 6's signal list and Phase 7's evidence list inside
a third contract that owns none of them — so those are referenced, not inlined.

Two identical integrations serialize to byte-identical text. An empty chain serializes
to 5,110 characters of valid JSON.

## 21. Test coverage

**196 Phase 8 tests**, all passing, in two modules:

| Module | Tests | Focus |
| --- | --- | --- |
| `test_hydro_integration_assessment.py` | 126 | The contract: statuses, derivation order, chain, projections, provenance, serialization, disclaimer, errors |
| `test_hydro_integration_safety.py` | 70 | The guarantees: no clock, no randomness, no recomputation, no composite, no downgrade, no GIS, no quantum, no service, immutability |

The split is deliberate: a test that mixes the two tends to end up asserting a prose
claim. A status test should check a status.

The safety module checks most guarantees by parsing the module's own AST rather than
observing its output, because **absence is not demonstrable at runtime**. If Phase 8 read
a clock, a behavioural test could only catch it by freezing time and comparing two runs
— which passes anyway if the read lands outside the compared field. If it imported
FastAPI, an output test would see a working function. If it invented a composite, a
test would have to already know the formula to notice the number.

Scans collect **code identifiers and code strings only**, excluding docstrings. Several
guarantees are about words — `EVACUATE`, `MONITOR`, `emergency` — and this module's
explanation legitimately contains them in order to say that Phase 8 emits none of them.
A raw text scan would flag that honesty as a violation, which is exactly backwards.

Every fixture is a real `serve`, a real `assess_risk` and a real `decide_response`. There
is no fixture that builds a layer result field by field, because a hand-built stand-in
would let a test pass against an object shape the repository never produces.

**One design limitation found while writing the tests.** The record is a frozen
dataclass, which normally makes Python generate a `__hash__` from the fields — but that
generated hash then fails on the read-only mappings, because a `MappingProxyType` is
unhashable. The result is a record that looks hashable and raises `TypeError` when used
as a dictionary key. That is asserted rather than left to surprise a consumer who
reasoned "frozen implies hashable"; key on `integration_id`, which is a string and is the
identity the contract publishes.

## 22. What remains open

Phase 8 introduces no new blocker. The pre-existing ones are unchanged:

- XGBoost, Keras and PyTorch are unavailable on Python 3.13.5, recorded in
  `01_Flood_Forecasting/TEAM_INTEGRATION_REQUIREMENTS.md`
- Migration `011_navya_hydro_observation_domains.*.sql` is unvalidated against live
  PostgreSQL (`DB-MIG-02`)
- Team integration seams are absent on this branch
- There is no real gauge network, no discharge or inflow observations, no station
  registry, no approved thresholds, no rating curves, no GIS and no exposure data

The last item is the one that matters most for this phase. It is why the repository's
own output tops out at `PARTIAL`, and why reaching `COMPLETE` requires a caller to
declare a provider that does not yet exist.

Two carried-forward limitations worth naming explicitly:

- `ExposureAvailability` cannot express freshness, so `stale` must be declared upstream
- A GIS implementation is still required, and `NOT FOUND IN REPOSITORY — HUMAN / TEAM
  INPUT REQUIRED` remains the correct answer to where it would live

**Not claimed:** `production_ready_claimed` is `False` and `operational_authority` is
`False`, permanently, in every record. Phase 8 is not an authority and inherits no
authority from the layers it integrates.