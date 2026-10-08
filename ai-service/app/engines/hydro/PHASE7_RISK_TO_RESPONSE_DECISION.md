# Phase 7 - Risk to Response Decision Boundary

Owner: forecasting module (`ai-service/app/engines/hydro/`) · Branch: `feature/forecast`
· Predecessor: [`PHASE6_FORECAST_TO_RISK_INTEGRATION.md`](PHASE6_FORECAST_TO_RISK_INTEGRATION.md)

> **All data referenced in this phase is SYNTHETIC/DEMO.** The committed sample is
> generated. Nothing in this repository is a real hydrological observation, and
> nothing produced by this phase may be presented as one.
>
> The verbatim source disclaimer is carried by
> `provenance.SYNTHETIC_DATA_DISCLAIMER` and reproduced in every response decision,
> every response context, every explanation, every provenance chain and every
> configuration this phase reads:
> `THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION DATA.`
>
> **Nothing here is an emergency authority, and nothing is production-ready.**
> `operational_authority` and `production_ready_claimed` are permanently `False` in
> every `ResponseDecision`, every explanation, every provenance chain and every
> contract description. No code path sets either true.
>
> **No response policy in this repository is approved.** There are no official flood
> warning criteria, no signed-off response matrix, and no population or
> infrastructure data with which to justify one. `ResponsePolicy()` is therefore
> unusable by default and every decision made under it is `WITHHELD`. The mapping
> the tests exercise is a DEMO mapping in a test fixture, labelled as one on every
> surface it reaches.
>
> **There are no numerical boundaries in this phase.** A response category is
> selected by matching a Phase 6 risk *level* against a configured mapping. This
> module contains no threshold, no probability, no sigma, no band edge and no score
> of its own, and it will not invent one.

---

## 1. What Phase 7 is for

Phase 6 turned a validated forecast into an auditable risk band. It stopped at the
band: a band is a classification of hydrological severity, and a classification is
not an instruction to anyone. Phase 7 is the seam between the two.

```python
from app.engines.hydro.response_decision import ResponsePolicy, decide_response

policy = ResponsePolicy(
    risk_level_response={
        "LOW": "MONITOR",
        "MEDIUM": "HEIGHTENED_MONITORING",
        "HIGH": "REVIEW_WARNING",
        "CRITICAL": "REVIEW_WARNING",
    },
    policy_status="pending",                     # nothing here is approved
    policy_source="DEMO mapping; NOT an approved warning matrix",
)

decision = decide_response(risk_result, policy=policy)
decision.decision                # 'HEIGHTENED_MONITORING'
decision.operational_authority   # False
decision.production_ready_claimed # False
```

**That mapping is the DEMO fixture's, not a warning matrix.** It is here because it
is the mapping the tests exercise, and it is labelled `policy_status='pending'` with
a `policy_source` that says so. No such matrix exists in this repository. Remove it
and the same call returns `WITHHELD` — which is the honest default, and the only
mapping this codebase can actually stand behind.

Two modules, both in `ai-service/app/engines/hydro/`:

| Module | Responsibility | Exports |
| --- | --- | --- |
| `response_context.py` | The typed response-context contract; exposure *availability*; temporal and entity validation; the read-only projection of a Phase 6 `RiskResult` | 27 |
| `response_decision.py` | The risk-to-response decision boundary; policy and rules; explanation; provenance chaining; structured errors | 28 |

The chain those two modules implement, end to end:

```
Phase 6 RiskResult  (forecast_risk.RiskResult)
        |
        v
Response context projection  (ResponseContext.from_risk_result - copies, adds nothing)
        |
        v
Exposure availability  (ExposureAvailability - kind, availability, reason, source)
        |
        v
Withholding checks  (in a fixed order, first unmet precondition wins)
        |
        v
Policy mapping lookup  (risk level -> response category; WITHHELD if unmapped)
        |
        v
Raise-only rule evaluation  (bounded by the policy's own ceiling)
        |
        v
Response explanation  (derived only from what was actually read)
        |
        v
Auditable response decision  (ResponseDecision, to_dict)
```

### Phase 7 does NOT

- compute an exceedance probability, a residual spread, a threshold or a band edge;
- call `risk.exceedance_probability`, `risk.classify_risk_level` or
  `risk.residual_sigma` — Phase 6 owns those and Phase 7 reads their output;
- fit, refit, calibrate, select, or serve any model;
- re-read a Phase 6 signal value or apply a threshold of its own to one;
- produce `EVACUATE`, `MANDATORY_EVACUATION` or `EMERGENCY_DECLARED`, or any
  approximation of them;
- produce a composite, weighted, or aggregate score of any kind;
- place a population count, an infrastructure count, or any other number into a
  decision — see §4;
- implement a GIS engine, a spatial calculation, or an elevation or floodplain
  lookup;
- invent a flood event, a gauge reading, an asset register, or a response policy;
- accept a signal observed after the forecast origin, whatever its timestamp says;
- accept a context whose entity does not match the risk result's;
- touch QUBO, QAOA, quantum optimisation, sensor placement, or IoT ingestion;
- expose an HTTP route, a handler, persistence, auth, or a deployment artefact;
- read a clock, or use randomness or a UUID.

---

## 2. What Phase 7 reuses, and why it does not duplicate it

The most important decision in this phase is the one that produced the *fewest* new
types. The repository already had a risk surface; Phase 7 did not build a second one
beside it.

| Concern | Existing owner | Phase 7's use |
| --- | --- | --- |
| Exceedance probability | `risk.exceedance_probability` | **Not called.** Phase 7 reads the value Phase 6 computed and applies no arithmetic to it. |
| Band classification | `risk.classify_risk_level`, `contract.SUPPORTED_RISK_LEVELS` | Reads the level Phase 6 assigned; may only name levels from the same tuple. |
| Residual spread | `risk.residual_sigma` | **Not called.** Carried as `residual_sigma_source` for disclosure only. |
| Risk status vocabulary | `forecast_risk.RISK_STATUS_RECORDED`, `RISK_CONTRACT_VERSION` | `ResponseContext.risk_is_available` tests the same constant. |
| Threshold configuration | `config.RiskPolicy` | Read as `risk_threshold_policy` / `risk_threshold_configuration`; never constructed here. |
| Band vocabulary | `contract.SUPPORTED_RISK_LEVELS` | The only policy keys and rule triggers Phase 7 accepts. |
| Priority ordering | `contract.priority_for_risk_level` | `ResponseDecision.priority`. |
| Availability vocabulary | `risk_context.SIGNAL_AVAILABILITY`, `SIGNAL_UNUSABLE` | Reused verbatim: `RESPONSE_AVAILABILITY = SIGNAL_AVAILABILITY`. |
| Context evaluation states | `risk_context.CONTEXT_EVALUATION_STATES`, `CONTEXT_UNAVAILABLE`, `CONTEXT_NOT_EVALUABLE` | The two withholding conditions Phase 7 adds. |
| Entity / temporal errors | `risk_context.EntityMismatchError`, `FutureContextError` | Reused verbatim — same rules, one taxonomy. |
| GIS provider shape | `risk_context.GisContext` | `population_exposed` / `infrastructure_exposed` presence is read; the counts are not copied. |
| GIS absence marker | `domains.NOT_AVAILABLE` = `NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED` | Used verbatim on every unavailable GIS and exposure record. |
| Flood event schema | `domains.FloodEvent` | **Not used.** Historical context is carried as an availability flag and a count, never a synthesised event. |
| Synthetic disclaimer | `provenance.SYNTHETIC_DATA_DISCLAIMER` | Carried onto every context and every decision. |
| Production claim flag | `forecast_risk`'s `production_ready_claimed = False` | `PRODUCTION_READY_CLAIMED = False`, same mechanism. |

The consequence worth stating plainly: there is exactly one `RiskPolicy`, one band
vocabulary, one availability vocabulary, one absence marker, one
`SYNTHETIC_DATA_DISCLAIMER` and one risk classifier in this repository after
Phase 7. A reader who wants to know what a band means, or what "unavailable" means,
follows one reference, not two that may disagree.

---

## 3. The response-context contract

`ResponseContext` is a frozen dataclass of 31 fields. Every field is a fact Phase 6
already established: nothing here is fetched, inferred or estimated.

`from_risk_result` is the only constructor meant to be used. A context assembled
field by field is a context nobody has checked against the result it claims to
describe, which is why the dataclass validates what it can and refuses the rest.

Copied across, read-only:

- identity and provenance — `entity`, `risk_result_id`, `provenance`, `data_status`,
  `synthetic_demo`, `disclaimer`;
- the Phase 6 verdict — `risk_status`, `risk_evaluation_state`, `risk_level`,
  `risk_score`, `risk_score_type`;
- the Phase 6 configuration — `risk_threshold_policy`,
  `risk_threshold_configuration`, `risk_configuration_version`,
  `residual_sigma_source`;
- the forecast — `forecast_id`, `forecast_origin`, `forecast_horizon`, `prediction`,
  `prediction_units`;
- availability, summarised — `risk_availability_counts`, `usable_signal_names`,
  `gis_available` / `gis_reason`, `historical_available` / `historical_reason` /
  `historical_event_count`;
- exposure availability — `exposure`, a tuple of `ExposureAvailability`.

Validated on the way in:

| Check | Error |
| --- | --- |
| the object is not `None` | `MissingRiskResultError` |
| it carries a forecast with an `origin_instant` | `InvalidRiskResultError` |
| the origin is timezone-aware | `FutureContextError` (reused) |
| it names an entity | `InvalidRiskResultError` |
| a caller-supplied `entity` equals the risk result's | `EntityMismatchError` (reused) |
| `risk_level` is one of `SUPPORTED_RISK_LEVELS` | `InvalidRiskResultError` |
| `risk_evaluation_state` is a Phase 6 state | `InvalidRiskResultError` |
| `risk_score` is `None` or a real number in `[0, 1]` | `InvalidRiskResultError` |
| `decided_at`, when given, is aware and not before the origin | `FutureContextError` (reused) |
| exposure records are `ExposureAvailability`, one per kind | `InvalidResponseContextError` |

Three properties are derived rather than stored:

| Property | True when |
| --- | --- |
| `risk_is_available` | `risk_status == RISK_STATUS_RECORDED` **and** `risk_level is not None` |
| `risk_context_is_available` | `risk_evaluation_state != CONTEXT_UNAVAILABLE` |
| `risk_is_evaluable` | `risk_evaluation_state != CONTEXT_NOT_EVALUABLE` |

`resolved_decided_at` returns `decided_at` when supplied and the **forecast
origin** otherwise. Nothing in this module or in `response_decision` calls a clock.

---

## 4. Exposure availability has no value field

This is the load-bearing design decision of the phase.

`ExposureAvailability` has four fields:

```python
kind: str          # 'population' | 'infrastructure'
availability: str  # Phase 6's SIGNAL_AVAILABILITY, verbatim
reason: str        # required whenever availability != 'valid'
source: str        # who answered, or 'none'
```

There is **no `value` field.** Not an optional one, not a `None`-defaulted one. The
field does not exist.

Phase 6's `GisContext` already carries `population_exposed` and
`infrastructure_exposed` as counts, and already refuses to expose them as
`RiskSignal`s, for a reason recorded in `risk_context.py`: a population count is not
comparable against a threshold, so a rule firing on one would be asserting a hazard
relationship nobody in this repository has evidence for.

Phase 7 is where that temptation is strongest, because a response category is
exactly the thing someone would want to weight by how many people are downstream. So
the option is not offered. `risk × population_weight` cannot be written — not as a
policy we declined to configure, but as code that does not compile. That is a
stronger guarantee than a documented intention.

Consequences that are actually tested:

- `test_no_field_anywhere_in_the_module_carries_an_exposure_count` walks
  `dataclasses.fields` of every type in `response_context.py` and asserts no field
  name matches a count-shaped pattern;
- `ResponseDecision` has no score field at all, so there is nothing downstream to
  weight either — §10;
- the module contains no multiplication operator, asserted from the AST, so no
  weighted sum can be assembled by a later edit either.

Two factories build records, and neither takes a value:

```python
available_exposure("population", source="exposure-adapter")          # no count argument
unavailable_exposure("population", "unavailable", reason=NOT_AVAILABLE)
```

`available_exposure` deliberately has no count parameter. A factory that accepted
the number and dropped it would invite the next reader to add it back.

---

## 5. Availability is a vocabulary, not a null

Phase 6 defined an availability vocabulary. Phase 7 reuses it verbatim rather than
defining a second dialect:

```python
RESPONSE_AVAILABILITY == risk_context.SIGNAL_AVAILABILITY
# ('valid', 'missing', 'unavailable', 'not_applicable', 'stale')
RESPONSE_UNUSABLE     == risk_context.SIGNAL_UNUSABLE
# ('missing', 'unavailable', 'not_applicable', 'stale')
```

The four unusable states are kept distinct because they support different
conclusions. `missing` is a gap the caller knew about; `unavailable` means no
provider exists at all; `not_applicable` means the concept does not apply to this
entity; `stale` means an answer exists but is too old to rely on. Collapsing them
into "no data" would discard the only information that distinguishes "we did not
look" from "we looked and there was nothing".

None of them carries a number, and none of them defaults:

- `EXPOSURE_DEFAULT_AVAILABILITY` is `unavailable`, used when a risk result says
  nothing about a kind at all — a stronger and more honest statement than "a caller
  forgot";
- an unusable record **must** carry a `reason`. An empty reason raises
  `InvalidResponseContextError`, because "no data" and "we did not look" are
  different facts and a decision has to be able to tell them apart;
- an unknown availability state raises rather than being coerced to `unavailable`.

`response_unavailable_context(context)` returns exactly the records that
contributed nothing, and a decision surfaces them in
`ResponseDecision.unavailable_context`.

---

## 6. The response policy

`ResponsePolicy` is a frozen dataclass. A **mapping is required**, and it must be
supplied by whoever holds the authority to decide what a risk level means
operationally.

| Field | Default | Purpose |
| --- | --- | --- |
| `risk_level_response` | `{}` | Risk level → response category. **There is no default mapping**, because a default would be this module inventing a warning matrix. |
| `policy_status` | `'pending'` | Recorded verbatim. Phase 7 never sets it. |
| `policy_source` | `''` | Who decided this mapping. |
| `policy_version` | `'navya-phase7-response-policy/v1'` | For the decision id. |
| `policy_reference` | `None` | A document reference, if any. |
| `reviewed_by` / `reviewed_at` | `None` | Absent, because no review happened. |
| `notes` | `''` | Free text. |

`ResponsePolicy()` with no mapping is **unusable**, and `decide_response` on one
returns `WITHHELD` with the reason stated in the explanation. This is not a stub
waiting to be filled in with something plausible; it is the honest state of a
repository with no approved warning criteria.

Validation in `__post_init__`:

| Condition | Error |
| --- | --- |
| not a `Mapping` | `InvalidResponsePolicyError` |
| a key outside `SUPPORTED_RISK_LEVELS` | `InvalidResponsePolicyError` |
| a value outside `RESPONSE_STATES` | `UnsupportedResponseStateError` |
| a value of `WITHHELD` | `InvalidResponsePolicyError` |
| `policy_status` / `policy_version` not non-empty text | `InvalidResponsePolicyError` |
| `policy_source` given but blank | `InvalidResponsePolicyError` |
| `reviewed_at` not a datetime | `InvalidResponsePolicyError` |
| `reviewed_at` naive | `FutureContextError` (reused) |

`WITHHELD` is excluded as a *mapping target* deliberately. "Map LOW to WITHHELD"
would be a policy asserting that a low risk deserves no attention — a claim, not an
absence, and not one this repository can make.

Three derived properties:

- `is_usable` — at least one level mapped. A partial mapping is usable but
  incomplete: an unmapped level yields `WITHHELD` naming the fact, rather than
  defaulting to the nearest mapped level.
- `mapped_levels` — sorted keys.
- `highest_mapped_state` — the most severe state the policy can produce, or `None`.
  This is the rule ceiling, §8.

The mapping is sorted and frozen into a `MappingProxyType` in `__post_init__`, so
input order cannot reach the output.

---

## 7. The response vocabulary, and what is deliberately absent

```python
RESPONSE_STATES = ('WITHHELD', 'MONITOR', 'HEIGHTENED_MONITORING', 'REVIEW_WARNING')
```

Four states. `WITHHELD` is the absence of a recommendation, not a severity — it is
what a caller reaches when the evidence or the policy could not support one. The
other three are ordered by how much attention they ask for, via
`RESPONSE_SEVERITY`.

There is **no `EVACUATE`, no `MANDATORY_EVACUATION` and no `EMERGENCY_DECLARED`.**
They are not merely discouraged:

- `ResponsePolicy` raises `UnsupportedResponseStateError` when asked to map a level
  onto one;
- `ResponseRule` raises it when asked to escalate to one;
- `decide_response` refuses a policy that somehow carries one;
- `response_contract_description()["deliberately_absent_states"]` names all three,
  so a consumer can assert on the absence rather than trust it.

**The refusal does not degrade to the nearest available state.** Mapping `EVACUATE`
onto `REVIEW_WARNING` would be the most dangerous single behaviour available at this
boundary: a caller who asked for evacuation and received heightened monitoring
would have been told something different from what they requested, in the direction
of doing less.

The reason they are absent is not caution, it is evidence: there are no approved
warning criteria, no population or infrastructure data, and no signed-off response
matrix in this repository. Naming such a state would imply a capability that does
not exist, so the vocabulary refuses it rather than the documentation disclaiming it.

Every recommendation line carries this, whenever a category was recommended:

> this is a recommendation about attention on synthetic/demo evidence; it is not a
> flood warning, not an evacuation instruction, and carries no operational or
> government authority

and every decision — recommended or withheld — carries:

> no evacuation, mandatory evacuation, or emergency declaration is provided by this
> layer, and none was requested; those are not response categories this repository is
> able to justify

---

## 8. Rules: raise-only, never above the ceiling

`ResponseRule` has four required fields: `rule_id`, `risk_level_at_least`,
`escalate_to`, `source`, plus an optional `note`.

**The condition is a risk level, not a signal value.** This is the single most
consequential line in the file. Phase 6 already owns signal-threshold comparison —
unit conversion, availability, staleness, the raise-only guarantee — through
`RiskEscalationRule`. A signal-based rule here would be a second implementation of
the same machinery with a different set of bugs. The risk level is the one thing
Phase 6 has definitively evaluated and Phase 7 is entitled to read.

**Rules may only raise.** A rule that could lower a category would be a second,
silent risk classifier.

**Rules may never exceed the policy's own ceiling** (`highest_mapped_state`). A rule
that could raise a category past the maximum the configured mapping can produce
would be a rule overriding the policy that authorised it. When that happens the
evaluation is recorded as `fired=True, applied=False` with the reason:

```
rule 'demo-review-warning' fired, not applied:
  target REVIEW_WARNING is beyond the configured ceiling HEIGHTENED_MONITORING;
  a rule may not exceed the policy that authorised it
```

**Non-fired rules are recorded too.** `RuleEvaluation` exists for both cases, because
"no rule fired" and "no rule was configured" support completely different
conclusions about the same decision. An empty rule set says so explicitly.

**There is no `required` flag.** Phase 6 needed one because a rule there can depend
on a signal that might be missing or stale. This rule depends on the risk level, and
by the time rules are evaluated the withholding checks have already confirmed a level
exists. A `required` flag here would be a knob that cannot change any outcome, which
is worse than no knob: it would look like a safety control while doing nothing. The
dead flag and its `UncheckableRuleError` were removed from the first draft for this
reason.

Rules are validated for type, then for duplicate `rule_id`, then **sorted by
`rule_id`**, so input order cannot reach the output. A duplicate id raises, because
a rule that cannot be named unambiguously in an explanation cannot be audited.

---

## 9. Withholding conditions, in a fixed order

The order is fixed and tested. A decision names *one* reason, and the first unmet
precondition is the one a caller has to fix.

| # | Condition | Decision | Rationale, in short |
| --- | --- | --- | --- |
| 1 | `not context.risk_is_available` and state is `not_evaluable` | `WITHHELD` | Phase 6 could not assign a band. An exceedance probability without a band is not a level, and Phase 7 will not choose one. |
| 2 | `not context.risk_is_available` (any other state) | `WITHHELD` | Phase 6 recorded no usable level. There is nothing for a response to respond to. |
| 3 | `risk_evaluation_state == context_unavailable` | `WITHHELD` | Phase 6 read no context at all, so the level rests on the forecast alone with nothing corroborating it. |
| 4 | `not policy.is_usable` | `WITHHELD` | No mapping is configured, and this repository has no approved criteria to fall back on. |
| 5 | `risk_level not in policy.risk_level_response` | `WITHHELD` | An unmapped level is not defaulted to the nearest mapped one. |

If none of the five is unmet, the mapped category is produced, with rules applied
within the ceiling.

Two properties hold on every withheld path:

- **no withheld decision carries a category.** `decision` is always `WITHHELD`,
  `status` is always `'withheld'`, and `is_withheld` is true. A withheld decision
  that also said `MONITOR` would be two answers to one question;
- **a withheld decision carries no evidence.** `evidence == ()`, because nothing
  decided it. A "contributor" on a withheld decision would be a contributor to
  nothing.

The reason string is the audit record, so it states the fact and not a euphemism.
"no response mapping is configured, and this repository has no approved warning
criteria to fall back on" is a sentence a caller can act on. "Insufficient data" is
not.

---

## 10. The decision

`ResponseDecision` is a frozen dataclass of 28 fields. Two of them are structural
safety properties rather than data:

```python
operational_authority: bool = OPERATIONAL_AUTHORITY      # False, permanently
production_ready_claimed: bool = PRODUCTION_READY_CLAIMED  # False, permanently
```

Both are module constants as well as dataclass defaults, and no code path assigns
either true. They exist so a consumer can *assert* on the absence of a claim rather
than have to trust it.

There is **no score field**, and that is the load-bearing omission: with nothing to
weight, no composite can be assembled downstream either.

| Group | Fields |
| --- | --- |
| Identity | `decision_id`, `entity`, `risk_result_id`, `forecast_id`, `forecast_horizon` |
| The decision | `decision`, `status`, `rationale`, `explanation` |
| What it read | `evidence`, `rules`, `unavailable_context` |
| What it rests on | `risk_level`, `risk_score`, `risk_score_type`, `priority` |
| The policy | `response_policy` (the whole `ResponsePolicy.to_dict()`) |
| Time | `decided_at`, `forecast_origin` |
| Disclosure | `provenance`, `synthetic_demo`, `data_status`, `disclaimer` |
| Flags and versions | `operational_authority`, `production_ready_claimed`, `response_contract_version`, `response_context_version`, `risk_contract_version` |

`risk_score` appears because Phase 6 computed it and a decision that dropped it
would be harder to audit. It is evidence with `contributed=False`; §11.

`status` is `'recommended'` or `'withheld'` — the Phase 6 `RiskResult.status` shape,
reused.

Derived properties: `is_withheld`, `is_recommendation`, `evidence_read`,
`fired_rules`, `applied_rules`, and `explain()` (the explanation joined into one
paragraph for a log line).

`to_dict()` returns plain JSON types only: strings, numbers, booleans, lists and
dicts. `Evidence`, `RuleEvaluation`, `ExposureAvailability` and `ResponsePolicy` are
each flattened through their own `to_dict`.

---

## 11. Evidence, and the `contributed` flag

`DecisionEvidence` is what makes "missing is not zero" checkable rather than merely
intended.

| Field | Purpose |
| --- | --- |
| `name` | What was read. |
| `value` | What it said, or `None`. |
| `units` | Where meaningful. |
| `source` | Who produced it. |
| `availability` | A Phase 6 availability state. |
| `contributed` | **Whether it actually moved the decision.** |
| `reason` | Why, in words. Required, never empty. |

An input that was read but did not decide carries `contributed=False` and a reason.
An input the decision never read does not appear in `evidence` at all — it appears in
`unavailable_context`. That distinction is the whole point: "we looked and it was not
decisive" and "we did not look" must never look alike.

A recommendation builds evidence in `_build_evidence`:

| Evidence | `contributed` | Why |
| --- | --- | --- |
| `risk_level` | `True` | The configured policy maps this level to a category. |
| `risk_score` | `False` | Carried for traceability; Phase 7 applies no numeric threshold of its own, so the score informs the explanation and not the category. |
| `risk_evaluation_state` | `True` | `partially_evaluated` still supports a category; `context_unavailable` and `not_evaluable` do not. |
| `threshold_policy_status` | `False` | Recorded so the demo nature of the underlying level is visible. |
| `phase6_signal:<name>` per usable signal | `False` | Read by Phase 6 and already reflected in the level. Phase 7 does not re-read the value and applies no rule of its own to it. |

Two consequences worth naming:

- **Phase 7 carries no signal values at all.** A `phase6_signal:*` record has
  `value=None` unconditionally. That is what makes §12 true by construction rather
  than by test: there is no value for a post-origin reading to hide in.
- **A withheld decision builds no evidence at all**, because nothing decided it.

`DecisionEvidence.__post_init__` requires a name, a source, a non-empty reason and a
known availability state. An evidence record that cannot be explained is refused at
construction.

---

## 12. Temporal safety

The forecast origin is the boundary. **No clock is read anywhere in this phase** —
no `datetime.now`, no `utcnow`, no `time.time`, no `monotonic`, asserted from module
source and again from the AST import list (`random`, `uuid`, `secrets` and `time` are
all absent from both modules).

| Rule | Behaviour |
| --- | --- |
| `decided_at` defaults to the forecast origin | Two decisions over the same inputs cannot differ for a reason that has nothing to do with the evidence. |
| A `decided_at` before the origin raises `FutureContextError` | Silently clamping to the origin would hide the caller's mistake. |
| A naive `decided_at` raises `FutureContextError` | An instant with no offset cannot be compared against an origin that has one. |
| A later `decided_at` is accepted | Stating an instant explicitly is allowed; *reading* one is not. |
| A risk result with no forecast raises `InvalidRiskResultError` | A decision with no origin cannot be checked against temporal leakage. |

The last one is worth a note: `RiskResult` validates its own forecast, so a result
with no forecast cannot be built through its constructor at all — Phase 6 refuses it
first. Phase 7's guard exists for a caller holding an older or hand-assembled record,
and is tested with a stand-in rather than a `dataclasses.replace` that would never
reach it.

**Post-origin evidence cannot enter, by any route.** Phase 6 refuses a signal
observed after the origin, and an event starting after it. Phase 7 adds nothing to
that machinery because it re-reads no signal value: `phase6_signal:*` evidence
carries `value=None` (§11). The end-to-end path is tested — a post-origin signal is
refused at `assess_risk`, and the resulting decision's `decided_at` is exactly the
forecast origin.

### The one real gap, stated rather than hidden

`ExposureAvailability` has **no timestamp field**. Phase 7 records *whether*
exposure was available, not *when*. A caller who needs freshness must establish it
upstream and express it as `stale`, because this boundary has no field in which an
observation time could be compared against the origin.

This is a genuine limitation of the design, tested and documented rather than
quietly omitted: there is no `observed_at` and no `as_of` on an exposure record, and
asserting their absence is part of the test suite.

---

## 13. Entity safety

Phase 7 has **no station registry, no mapping table, no nearest-station rule and no
geographic inference.** Two different entity names are a refusal.

`ResponseContext.from_risk_result(risk_result, entity=...)` takes the caller's
independent statement of which station the decision is about and **checks it against
the risk result rather than overwriting it.** A mismatch raises `EntityMismatchError`,
the Phase 6 class, reused verbatim — the rule is identical, so there is no reason to
have two of them.

Without that check, a caller who assembled Station A's forecast with Station B's
exposure would get a context labelled Station B containing Station A's evidence, and
every later field would look consistent while describing the wrong place.

A risk result naming no entity raises `InvalidRiskResultError`: a response decision
is about a place, and one without a place is not a decision.

No decision can claim an entity other than its risk result's, and a decision built
from Station A's risk result does not mention Station B anywhere in its
serialisation — Station B is present in the same Phase 5 run, so its name is a
realistic thing for a mixing bug to leak.

---

## 14. Missing is not zero; unavailable is not safe

This phase has no `None`-means-zero path, and no unavailable-means-safe path. Both
halves are tested.

**Nothing defaults to zero.**

| Field | On a withheld decision |
| --- | --- |
| `risk_score` | `None` |
| `risk_level` | `None` |
| `priority` | `None` |
| `evidence` | `()` |

**No exposure record holds a number at all.** Not a zero, not a count, not a
default. The test asserts that no value in `ExposureAvailability.to_dict()` is a
non-boolean `int` or `float`.

**An unavailable input is absent from the decision, not counted as zero and not read
as reassuring.** Unusable exposure appears in `unavailable_context` and in the
explanation as *"population unavailable (NOT FOUND IN REPOSITORY — HUMAN / TEAM
INPUT REQUIRED)"*, with the explicit note that it did not contribute.

**Absent history is not absence of flooding.** When `historical_available` is false
the explanation says so, and says why the absence is not evidence:

> historical flood context was unavailable (no flood event register exists in this
> repository, and none may be invented); this absence is not evidence that this
> location has never flooded

**Unavailable GIS is not safe geography.** When `gis_available` is false the
explanation says so and records that no spatial conclusion was drawn. And when a
provider *does* answer, Phase 7 still draws none: the spatial line is emitted only
in the unavailable case, so an available provider produces **no** spatial sentence
at all, and neither `elevation` nor `river-distance` appears in the rationale. The
reason is that there is nothing here that could consume a spatial conclusion — no
rule conditions on one, no evidence carries one, and no score exists to weight it.

**A missing threshold does not become a low risk.** This is the state a caller
reaches in this repository today — `RiskPolicy()` has no threshold, Phase 6
withholds, and Phase 7 withholds. It does not resolve the absence to `MONITOR`, which
would read as "low risk" and is the single most dangerous default available at this
boundary. The explanation is explicit that withholding "is not the same as
recommending that nothing be done".

**The absence marker is verbatim.** Where GIS or exposure is unavailable, the reason
is `domains.NOT_AVAILABLE`:

> `NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED`

Phase 7 does not paraphrase it, and it is the same string Phase 6 uses.

---

## 15. Explanation

Every line of `explanation` is derived. No template can describe a contributor that
was not read, because there is nothing to interpolate it from.

| Line | Condition |
| --- | --- |
| Header: entity, risk result id, risk status / evaluation state, level, score, score type, and that Phase 6 owns the classification | Always |
| `no response category is recommended: <reason>; withholding … is not the same as recommending that nothing be done` | Withheld |
| `response category <X> is recommended because <rationale>` | Recommended |
| `<n> input(s) were read: …` or `no input was read; a decision made from nothing is recorded as such` | Always |
| `context that was unavailable and did not contribute …: an unavailable input is absent from the decision, not counted as zero and not read as reassuring` | Any unusable exposure |
| `no contextual input was declared unavailable for this decision` | None |
| `historical flood context was unavailable (<reason>); this absence is not evidence that this location has never flooded` | No historical context |
| `spatial context was unavailable (<marker>); no elevation, river-distance, floodplain or accessibility conclusion was drawn` | No GIS |
| `phase 6 evaluated the context at state <state> with valid=<n>; phase 7 read that state and did not re-evaluate any signal` | Any availability counts |
| The policy: mapping, source, status | Always |
| `raised by <rule>; rules may only raise a response category, never lower one` | Any applied rule |
| `configured but not applied: <rule>: <reason>` | Any fired-but-not-applied rule |
| `no response rules are configured, so no rule contributed to this decision` | No rules |
| `the underlying risk score rests on no measured residual spread …, so this decision inherits an unquantified spread and is not a confidence statement` | Sigma source unavailable |
| `the underlying threshold policy is '<status>' (<source>); the risk level this decision responds to is a demo value with no official meaning` | Policy status not `approved` |
| `this is a recommendation about attention on synthetic/demo evidence; …` | Recommended only |
| `no evacuation, mandatory evacuation, or emergency declaration is provided by this layer …` | Always |
| `SYNTHETIC_DATA_DISCLAIMER` | `synthetic_demo` |

Three rendering rules that matter:

- **`value=None` renders as "no value carried", never as a bare `None`.** A bare
  `None` next to a signal name reads as a *missing measurement*, when the truth is
  that Phase 7 deliberately did not carry the value at all. One is a data gap; the
  other is a scope boundary. They must never look alike.
- **Non-contributing evidence is suffixed `(read, did not decide)`.**
- **The recommendation disclaimer appears only on a recommendation.** A withheld
  decision has nothing to disclaim.

`explain()` joins the tuple into one paragraph. Every line is tested for what it
claims, not merely for its presence — for example that the explanation never claims
an unavailable context contributed, and that the number of evidence items quoted in
the explanation matches `len(decision.evidence)`.

---

## 16. Provenance and determinism

`ResponseDecision.provenance` is a flat mapping chaining the whole line of descent:

| Key | Source | On the withheld path too? |
| --- | --- | --- |
| `response_contract_version` | `navya-phase7-response/v1` | Yes |
| `risk_contract_version` | Phase 6's, imported | Yes |
| `risk_result_id`, `forecast_id`, `entity` | Phase 6 | Yes |
| `risk_evaluation_state` | Phase 6 | Yes |
| `risk_threshold_policy`, `risk_configuration_version` | Phase 6's configuration | Yes |
| `response_policy_version`, `response_policy_status` | The policy applied | Yes |
| `risk_level`, `risk_score`, `risk_score_type` | Phase 6's verdict | No — omitted on a withheld decision, which is why a withheld decision never carries a level |
| `response_policy_source` | The policy applied | No — recorded only where the policy actually produced a category |
| `operational_authority`, `production_ready_claimed` | `False` | Yes |
| `response_context_disclaimer` | The verbatim disclaimer | Yes |
| `error_reason` | `error.reason`, on the `response_from_error` path with no context | That path only |

The three contract versions are also top-level `ResponseDecision` fields —
`response_contract_version`, `response_context_version` and `risk_contract_version` —
so a serialised decision names all three without unpacking the provenance.

`response_policy` carries the entire `ResponsePolicy.to_dict()` — mapping, mapped
levels, usability, status, source, version, reference, reviewer, review instant,
`operational_authority` and notes — so the mapping that produced the decision can be
read back out of the decision itself.

The Phase 6 `provenance` object itself is carried on `ResponseContext.provenance`,
serialised through its own `to_dict()` when it is a dataclass and copied when it is
a mapping.

**Determinism.** Identical context + identical policy ⇒ byte-identical
decision-relevant output.

- Exposure records are emitted in the fixed `EXPOSURE_KINDS` order.
- `risk_availability_counts` is sorted; `usable_signal_names` is sorted.
- Rules are sorted by `rule_id`; the policy mapping is sorted on construction.
- `ResponseContext.digest` is sha256 over the decision-relevant fields, truncated to
  12 hex characters. The same evidence assembled in a different order digests the
  same. It is an integrity handle, not a security primitive.
- `decision_id` is a readable prefix plus sha256 over the contract version, entity,
  risk result id, context digest, policy version, policy status and the mapping
  itself:

  ```
  response-{entity}-{risk_level}-{policy_version}@{sha256[:12]}
  ```

  No uuid, no counter, no clock. A random id would make two identical decisions look
  like two different events.
- `decided_at` defaults to the forecast origin. **No clock is read**, so the only way
  two decisions over the same inputs could differ is if the inputs did.

`response_from_error` without a context has no origin to attribute anything to, so
it uses the Unix epoch (`1970-01-01T00:00:00+00:00`) explicitly rather than reading
a clock. That is visible in the serialisation and is not a plausible forecast origin.

---

## 17. Errors versus states

The same split Phase 6 uses, for the same reason. A contract violation is something
the caller did wrong and should be told about; an availability condition is a fact
about the world that belongs in the result.

**Raised** — `decide_response` refuses:

| Error | `reason` | Raised when |
| --- | --- | --- |
| `MissingRiskResultError` | `missing_risk_result` | The context is `None`. |
| `InvalidRiskResultError` | `invalid_risk_result` | No forecast, no origin, no entity, an unknown risk level, an unknown evaluation state, an out-of-range score. |
| `InvalidResponseContextError` | `invalid_response_context` | A self-contradictory context, a malformed evidence or exposure record. |
| `InvalidResponsePolicyError` | `invalid_response_policy` | A non-`ResponsePolicy`, an unknown policy key, a `WITHHELD` mapping target, a malformed rule, a non-`ResponseRule` in `rules`, a duplicate `rule_id`. |
| `UnsupportedResponseStateError` | `unsupported_response_state` | A response state outside `RESPONSE_STATES` was configured — including every evacuation or emergency state. |
| `EntityMismatchError` | `entity_mismatch` | *Reused from Phase 6.* A caller's entity is not the risk result's. |
| `FutureContextError` | `future_context` | *Reused from Phase 6.* A naive instant, or a `decided_at` / `reviewed_at` before the origin. |

All of them derive from `ResponseBoundaryError(ValueError)`, which is deliberately
**not** a `RiskBoundaryError`. A caller that catches the risk taxonomy to handle "the
risk layer refused" would otherwise silently swallow "the response layer refused",
and the two failures need different responses.

**Returned** — `decide_response` yields a `WITHHELD` decision:

Every condition in §9. Plus, for the caller who must answer rather than fail,
`decide_response_safe`, which converts any contract violation into a withheld
decision naming the error's `reason` tag, and `response_from_error`, which does the
same for an already-caught exception and tolerates any `ValueError`.

Three invariants on every error path, all tested:

- **no error path returns `MONITOR`, or any recommendation.** Every one returns
  `WITHHELD`;
- **no error path returns `0`, `None`-as-zero, or a low-risk reading**;
- **the disclaimer survives every one of them.** `response_from_error` appends
  `SYNTHETIC_DATA_DISCLAIMER` even when there is no context to carry it from.

Two robustness details in the error paths, both of which were defects in the first
draft:

- `_reportable_policy` substitutes an empty `ResponsePolicy` for a non-policy. A
  non-policy is refused by `_require_policy` on the way in, and reporting the
  original object would raise *inside the error handler* — the one place that must
  not fail;
- `response_from_error` catches a failure to project a context and proceeds with
  `context=None` rather than propagating, because the contract is to withhold.

---

## 18. Tests

Two modules, **155 tests**, all behavioural — no weakened assertions, no mocks of
the code under test, and no skips.

| Module | Tests | Covers |
| --- | --- | --- |
| `test_hydro_response_decision.py` | 95 | The state vocabulary, what is deliberately absent, policy validation, per-band decisions, all five withholding conditions, rules and the ceiling, exposure records, the evidence model, explanation derivation, provenance, the contract descriptions, the safe wrapper and the error paths. |
| `test_hydro_response_safety.py` | 60 | Temporal, entity, no-second-risk-engine, no-composite, missing-≠-zero, determinism, authority flags and the disclaimer. |

Shared fixtures live in `tests/hydro_phase7_fixtures.py`. The Phase 5 run, served
forecast, measured residuals and band thresholds all come from
`hydro_phase6_fixtures`; `risk_result_for_band` calls the **real** `assess_risk`, so
the `RiskResult` a test reasons about is one the repository actually produces. The
thresholds are derived by inverting Phase 6's exceedance model, never hard-coded.

One practical note about the fixture module: the shared Phase 5 run is built once at
module scope by `shared_run()` / `shared_served()` / `shared_residuals()` rather
than requested as a pytest fixture. Pytest resolves fixtures from the test module's
own namespace and does not follow them transitively through a helper module, so a
fixture in `hydro_phase7_fixtures.py` that asked for Phase 6's `run` would fail with
"fixture not found". Calling the factory once and reusing the result is the same
object at the same cost.

### Structural tests, and why they are structural

Several tests read module source or parse it into an AST rather than exercising
behaviour. That is deliberate: a behavioural test can only prove that the *current*
inputs do not trigger a behaviour, and the point of these claims is that a *future
edit* must not be able to introduce one either.

- `decide_response`'s signature and `ResponseDecision`'s field list, asserted
  directly — that is what structurally prevents a score from being added;
- every dataclass `response_context` defines is walked for a count-shaped field name
  (`exposed`, `count`, `headcount`, `persons`, `residents`, `weight`, `value`,
  `total`), with an explicit two-name allow-list for the Phase 6 signal- and
  event-counts that are copied for traceability;
- the module contains **no multiplication operator** (`ast.BinOp` with `ast.Mult`),
  so no weighted sum can be assembled by a later edit;
- neither module imports `random`, `uuid`, `secrets` or `time`;
- neither module references a clock function;
- `response_decision`'s import list contains no last-dotted-component of `risk`,
  `exceedance_probability`, `classify_risk_level` or `residual_sigma`, so a second
  implementation cannot be added without deleting an import line;
- no async function is defined in either module, and neither performs I/O;
- the identifier set of *executable code* — attribute accesses, imports, local
  names, definitions — is checked by group:

| Group | Forbidden in executable code |
| --- | --- |
| Phase 6 arithmetic | `exceedance_probability`, `classify_risk_level`, `band_edges`, `erf`, `norm` |
| Model work | `train`, `fit`, `predict`, `estimators`, `select_model`, `ArtifactStore`, `ForecastInference`, `pickle`, `joblib`, `unpickle`, `np`, `numpy`, `pd`, `pandas`, `sklearn` |
| Quantum / optimisation | `quantum`, `QUBO`, `qiskit`, `dwave`, `optimize`, `optimizer`, `sensor_placement`, `cplex`, `gurobi` |
| GIS | `elevation`, `elevation_m`, `river_distance`, `river_distance_m`, `floodplain`, `shapefile`, `geopandas`, `raster`, `shapely`, `pyproj`, `gdal` |
| Network / subprocess | `requests`, `httpx`, `urllib`, `aiohttp`, `socket`, `http`, `subprocess` |
| Service app | `fastapi`, `APIRouter`, `uvicorn`, `pydantic`, `BaseModel`, `async` |
| Composite score | `population_weight`, `infrastructure_weight`, `weight`, `weighted`, `severity` |

The composite-score and quantum/optimisation checks cover **both** Phase 7 modules,
because a count could equally have been dropped into `response_context`.

That identifier scan started as a raw substring search over module source, and it
failed — on the modules' own prose. `response_decision` *discusses* elevation
thresholds, QUBO, weighted composites and `exceedance_probability` in order to
record that it does none of them. A test that cannot tell the difference between a
name in a docstring and a name in a call is not testing a boundary, so the scan now
parses the AST and ignores docstrings and comments. The test is strictly stronger
than the one it replaced: it checks what the module can *evaluate*, not what it can
say.

### The guarantees, each with its own test

**Vocabulary**

- `RESPONSE_STATES` is exactly the four states, and `WITHHELD` is in it;
- `EVACUATE`, `MANDATORY_EVACUATION` and `EMERGENCY_DECLARED` are not
  representable, and neither are the nine other spellings a caller might plausibly
  try — `EVACUATION`, `WARNING`, `MANDATORY EVACUATION`, `EMERGENCY`, `EVACUATING`,
  `EVACUATION_ORDER`, `ALERT`, `DISASTER`, `FLOOD_WARNING`;
- a policy cannot configure one, a rule cannot escalate to one, and the refusal does
  not degrade to the nearest available state;
- a policy cannot map to `WITHHELD`, and a rule cannot target `WITHHELD`;
- a policy cannot key on a risk level Phase 6 cannot emit.

**Decisions**

- each band reaches the category the DEMO mapping assigns, and `REVIEW_WARNING` is
  reachable from configuration alone;
- `partially_evaluated` still yields a recommendation;
- all four withholding conditions, and that every withheld decision explains itself
  and never carries a recommended category;
- an unmapped level withholds rather than defaulting to the nearest mapped one.

**Rules**

- a rule raises within the ceiling, may not exceed it, does not fire below its
  trigger, and non-fired rules are still recorded;
- duplicate `rule_id` is refused; rule order does not change the decision;
- rules holding a non-`ResponseRule` are refused by type, before evaluation.

**Context**

- available exposure is recorded with no value, and no field anywhere in the module
  carries a count;
- each unusable state is kept distinct, and none of them becomes zero;
- unavailable GIS carries the verbatim marker and never becomes safe geography;
- available GIS is recorded and produces no spatial sentence and no spatial term in
  the rationale;
- unavailable history is not read as never-flooded;
- an unusable exposure must state a reason; an unknown kind or state is refused.

**Explanation**

- it names the risk result it consumed, lists what was evaluated, and marks inputs
  that did not decide;
- it never claims unavailable context contributed;
- it states the policy that produced the category, the demo nature of the
  underlying level, the synthetic status, and that no emergency state is available;
- a recommendation is labelled a recommendation, and a withheld decision carries no
  recommendation line;
- a `None` value is never rendered as a bare `None`.

**Provenance and determinism**

- the chain forecast → risk → response, the absence of authority, the Phase 6
  threshold and configuration;
- `decision_id` is deterministic, readable, not a UUID and not a counter, and changes
  when the policy changes;
- the serialised decision is plain JSON types.

**Safety**

- temporal: `decided_at` defaults to the origin, refuses an earlier or naive instant,
  accepts a later one; a post-origin signal is refused end to end;
- entity: a mismatched entity is refused with the Phase 6 class, a matching one is
  accepted, an empty one is refused, and two stations produce independent decisions
  with no cross-mention;
- no composite: the score field set contains none, `risk_score` is evidence with
  `contributed=False`, and the module evaluates no weighted sum;
- missing ≠ zero: no decision field defaults to zero, unavailable population is not
  zero population, a missing threshold does not become a low risk;
- determinism: repeated decisions serialise identically;
- disclosure: the disclaimer survives every path including both error wrappers, and
  `production_ready_claimed` / `operational_authority` are false on the object, in
  `to_dict()` and in the provenance chain.

---

## 19. Source defects found and fixed

Six defects were found while writing this phase and fixed before any of them reached
a commit. They are listed because each one was a place where the module would have
misled a reader or crashed a caller.

### 1. `entity` silently overwrote instead of checking

`from_risk_result(..., entity=...)` assigned the caller's string to the context's
`entity` field. A caller assembling Station A's forecast with Station B's exposure
would have got a context labelled Station B containing Station A's evidence, with
every later field looking consistent.

Fixed: the supplied entity is compared against `risk_result.forecast.entity`, and a
mismatch raises `EntityMismatchError` — the Phase 6 class, reused. The argument's
whole purpose is the check.

### 2. Duplicate exposure kinds were silently de-duplicated

`_exposure_records` built a `dict` keyed by kind, so supplying two `population`
records kept the last one and discarded the other without a word. A kind that appears
twice has two availability states and no way to choose between them, and silently
keeping one would misreport the other.

Fixed: duplicates are detected before the mapping is built and raise
`InvalidResponseContextError` naming the kinds. The same check was added to
`ResponseContext.__post_init__`, for a context assembled directly.

### 3. `decide_response_safe` raised from inside its own error handler

`_reportable_policy` did not exist; the safe wrapper passed the caller's original
policy straight to `response_from_error`, which called `policy.to_dict()`. For any
non-`ResponsePolicy` — which is exactly the input `_require_policy` rejects — that
raised a *new* `AttributeError` from inside the handler, so the caller got a
traceback instead of a withheld decision, from a function whose entire contract is to
answer rather than fail.

Fixed: `_reportable_policy` substitutes an empty `ResponsePolicy` for anything that
is not one, and `response_from_error` uses it. Covered by
`test_the_safe_wrapper_turns_a_contract_violation_into_a_withheld_decision` with a
plain mapping as the policy.

### 4. A non-`ResponseRule` crashed before the type check

Rule validation ran `_evaluate_rules`-adjacent field access on each rule before
checking its type, so `decide_response(..., rules=["REVIEW_WARNING"])` raised
`AttributeError` on a string's `.risk_level_at_least` rather than the intended
`InvalidResponsePolicyError`.

Fixed: every rule is type-checked before any field is read, with a message naming
the type that was supplied.

### 5. A dead `required` flag and a dead `UncheckableRuleError`

The first draft of `ResponseRule` carried `required: bool` and raised
`UncheckableRuleError` when a rule's condition could not be evaluated. Phase 6 needed
such a flag, because a rule there can depend on a signal that might be missing or
stale. This rule depends on the risk level, and by the time rules are evaluated the
withholding checks have already confirmed a level exists — so the branch was
unreachable and the flag could not change any outcome.

Both were removed rather than kept as dead code. A `required` flag that looks like a
safety control and does nothing is worse than no flag.

### 6. `None` values rendered as a bare `None`

The evidence renderer interpolated `value` directly, so a Phase 6 signal Phase 7
deliberately does not carry rendered as `phase6_signal:rainfall_3h: None`. Beside a
signal name that reads as a *missing measurement*, when the truth is that Phase 7
never carried the value at all. One is a data gap; the other is a scope boundary.

Fixed: `_render_evidence` renders `value is None` as "no value carried", and
appends `(read, did not decide)` for non-contributing evidence.

### Two test defects, fixed the same way

- Four source-scanning tests failed on the modules' own docstrings — see §18. The
  scan was replaced with an AST parse, which is a stronger test, not a weaker one.
- One test asserted `"0" not in json.dumps(record.to_dict())`. `json.dumps` escapes
  the em dash in `NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED` as
  `—`, whose digits satisfy the search. The test was reading its own
  punctuation. Replaced with an assertion that *no value in the record is a number*,
  plus `ensure_ascii=False` on the serialisation.

---

## 20. Verified numbers, in one place

From this phase's fixture: the same real Phase 5 `random_forest` run Phase 6
documented, served at `2024-01-04T05:00:00+00:00`, scored on held-out residuals,
with the DEMO response mapping
`LOW→MONITOR, MEDIUM→HEIGHTENED_MONITORING, HIGH→REVIEW_WARNING,
CRITICAL→REVIEW_WARNING`.

| Quantity | Value |
| --- | --- |
| Entity | `SYNTHETIC-STATION-0001` |
| Prediction | `3.2393323679390944` m |
| Target / units / horizon | `target_water_level_6h` / `m` / `6h` |
| Forecast origin | `2024-01-04T05:00:00+00:00` |
| Forecast id | `SYNTHETIC-STATION-0001-target_water_level_6h-6h-2024-01-04T05:00:00Z-random_forest` |
| Residual spread | 36 measured residuals from the Phase 5 test split |
| Response contract version | `navya-phase7-response/v1` |
| Response policy version | `navya-phase7-response-policy/v1` |
| Response context version | `navya-phase7-response-context/v1` |
| Policy version (DEMO fixture) | `navya-phase7-demo-policy/v1` |
| `operational_authority` | `False` |
| `production_ready_claimed` | `False` |

Per-band decisions, with the derived threshold that resolves each band. The
probability column is Phase 6's, reproduced here only so the mapping is traceable;
Phase 7 never computes it:

| Band | Phase 6 probability | Phase 6 level | Phase 7 decision | Priority |
| --- | --- | --- | --- | --- |
| LOW | `0.050000000000000044` | `LOW` | `MONITOR` | `low` |
| MEDIUM | `0.1999999999999995` | `MEDIUM` | `HEIGHTENED_MONITORING` | `medium` |
| HIGH | `0.4499999999999995` | `HIGH` | `REVIEW_WARNING` | `high` |
| CRITICAL | `0.8000000000000005` | `CRITICAL` | `REVIEW_WARNING` | `critical` |

Decision ids, deterministic and readable:

| Band | `decision_id` |
| --- | --- |
| LOW | `response-SYNTHETIC-STATION-0001-LOW-navya-phase7-demo-policy/v1@515e066ae03c` |
| MEDIUM | `response-SYNTHETIC-STATION-0001-MEDIUM-navya-phase7-demo-policy/v1@da1c357f9202` |
| HIGH | `response-SYNTHETIC-STATION-0001-HIGH-navya-phase7-demo-policy/v1@60d76c2503f0` |
| CRITICAL | `response-SYNTHETIC-STATION-0001-CRITICAL-navya-phase7-demo-policy/v1@a41ba299b207` |

The four withholding paths, each from a real Phase 6 result:

| Phase 6 status / evaluation state | Level | Phase 7 decision |
| --- | --- | --- |
| `withheld` / `not_evaluable` | `None` | `WITHHELD` |
| `recorded` / `context_unavailable` | `MEDIUM` | `WITHHELD` |
| `withheld` / `not_evaluable` (probability retained, no band) | `None` | `WITHHELD` |
| `recorded` / `fully_evaluated`, `ResponsePolicy()` with no mapping | `MEDIUM` | `WITHHELD` |

The rule ceiling, verified: a policy mapping only `MEDIUM → HEIGHTENED_MONITORING`
with a rule escalating to `REVIEW_WARNING` produces

```
decision          HEIGHTENED_MONITORING
rule 'demo-review-warning'  fired=True  applied=False
reason  target REVIEW_WARNING is beyond the configured ceiling HEIGHTENED_MONITORING;
        a rule may not exceed the policy that authorised it
```

and, with a policy whose ceiling is `REVIEW_WARNING`, the same rule does apply:
`LOW → MONITOR` becomes `REVIEW_WARNING` with the rationale *"the configured policy
maps risk level LOW to MONITOR, and rule 'r1' raised it to REVIEW_WARNING"*.

Test counts:

| Scope | Result |
| --- | --- |
| `test_hydro_response_decision.py` | 95 passed |
| `test_hydro_response_safety.py` | 60 passed |
| **Phase 7 total** | **155 passed** |
| Phases 1–6 regression | 1988 passed, 2 skipped |
| **`ai-service/tests` full suite** | **2143 passed, 2 skipped** |

---

## 21. Known limitations, team boundaries, and the one-line version

### Known limitations

1. **The default answer is a withheld decision.** No approved response policy exists,
   so `ResponsePolicy()` is unusable and every decision made under it is `WITHHELD`.
   That is correct behaviour, and it means the end-to-end path is demonstrated on a
   DEMO mapping only.
2. **There are no numerical boundaries in this phase at all.** A category is selected
   by matching a Phase 6 level against a configured mapping. Anyone needing a
   probability, a threshold or a spread must read Phase 6.
3. **Exposure availability cannot be dated.** `ExposureAvailability` has no
   `observed_at` and no `as_of`. Freshness must be expressed upstream as `stale`.
   §12.
4. **Historical context is an availability flag, not an event list.** `domains.FloodEvent`
   exists; no register does. Phase 7 carries `historical_available` and
   `historical_event_count` and synthesises nothing.
5. **`GisContext` still has no station label** — the Phase 6 limitation, unchanged.
   Spatial context is reported and never evaluated.
6. **The temporal boundary is the origin, which is conservative.** Evidence taken
   shortly *after* the origin is refused. That is the right default for an auditable
   offline decision and the wrong one for an operational system; an operational
   deployment would need a different, explicitly declared contract.
7. **Phase 7 is a domain layer.** No HTTP route, no persistence, no schema, no
   migration, no deployment artefact. Those are team boundaries, not omissions.
8. **The explanation is prose in a tuple.** It is derived and tested, but it is not a
   localisation or templating facility.

### Team boundaries

| Seam | Status on this branch |
| --- | --- |
| `ai-service/app/schemas/models.py` | Absent — team-owned integration point. |
| `ai-service/app/engines/base.py`, `factory.py` | Absent — team-owned engine registry. |
| `backend/src/types/contract.ts`, `optimization.ts` | Absent — team-owned platform types. |
| `frontend/src/types/ai.ts`, `services/aiService.ts` | Absent — team-owned frontend contract. |
| `ai-service/requirements.txt` | Absent — team-owned dependency manifest. |
| `backend/package.json`, `frontend/package.json` | Absent — team-owned. |
| `docs/forecasting/` | Absent — team-owned. |
| `forecastingMergeupdate/`, `forcastingMergeupdate/` | Untouched, and deliberately untracked. |

GIS, IoT, quantum-service, QUBO/optimisation, deployment and `.github/` were not
modified. Pre-existing blockers from earlier phases are unchanged: XGBoost,
Keras/TensorFlow and PyTorch are unavailable in this environment; migration
`011_hydro_hydro_observation_domains.*.sql` is unvalidated against live PostgreSQL
(`DB-MIG-02`); and this branch has no team integration seams.

### The one-line version

Phase 7 turns a risk band into a labelled response recommendation using one
configured mapping and no arithmetic of its own — and it refuses every question it
cannot answer honestly, including the one everybody eventually asks.

### The disclaimer, one final time

`THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION DATA.`
