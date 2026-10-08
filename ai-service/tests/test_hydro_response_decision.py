# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 7 tests: what the decision boundary decides, and what it refuses.

Every test here reasons about a `RiskResult` the repository actually produced
through Phase 5's serving and Phase 6's `assess_risk`. No test asserts a
hydrological result, and no test hard-codes a threshold: bands are reached by
inverting the exceedance model with the measured residual spread, so these tests
break if the model's arithmetic changes rather than quietly passing against a
number that no longer means anything.

The tests are grouped by claim. A group exists because that claim is load-bearing
for the phase; where a claim is *refused* rather than honoured, the refusal is the
test.
"""

from __future__ import annotations

import dataclasses
import inspect
import re

import pytest

from app.engines.hydro.contract import SUPPORTED_RISK_LEVELS
from app.engines.hydro.forecast_risk import RiskResult
from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER
from app.engines.hydro.response_context import (
    EXPOSURE_KINDS,
    NOT_AVAILABLE,
    RESPONSE_AVAILABILITY,
    RESPONSE_UNUSABLE,
    ExposureAvailability,
    InvalidResponseContextError,
    MissingRiskResultError,
    ResponseContext,
    available_exposure,
    context_contract_description,
    response_unavailable_context,
    unavailable_exposure,
)
from app.engines.hydro.response_decision import (
    DECISION_HEIGHTENED_MONITORING,
    DECISION_MONITOR,
    DECISION_REVIEW_WARNING,
    DECISION_WITHHELD,
    OPERATIONAL_AUTHORITY,
    POLICY_TARGET_STATES,
    PRODUCTION_READY_CLAIMED,
    RECOMMENDATION_DISCLAIMER,
    RESPONSE_CONTRACT_VERSION,
    RESPONSE_STATES,
    DecisionEvidence,
    InvalidResponsePolicyError,
    ResponseDecision,
    ResponsePolicy,
    ResponseRule,
    UnsupportedResponseStateError,
    decide_response,
    decide_response_safe,
    default_decision_id,
    response_contract_description,
    response_from_error,
)
from hydro_phase7_fixtures import (  # noqa: F401  - fixtures must be parameters
    DEMO_RESPONSE_MAPPING,
    DEMO_RESPONSE_SOURCE,
    all_unusable_exposure,
    available_population,
    context_with_exposure,
    critical_risk,
    demo_context,
    demo_policy,
    demo_response_policy,
    demo_rule,
    high_risk,
    low_risk,
    medium_risk,
    missing_infrastructure,
    not_applicable_population,
    partial_mapping_policy,
    response_context,
    risk_context_unavailable,
    risk_not_evaluable,
    risk_withheld,
    run_result,
    served_forecast,
    shared_residual_values,
    stale_infrastructure,
    unavailable_population,
)


# --------------------------------------------------------------------------- #
# The vocabulary
# --------------------------------------------------------------------------- #


def test_response_states_are_exactly_the_four_recommendation_boundaries():
    assert RESPONSE_STATES == (
        "WITHHELD",
        "MONITOR",
        "HEIGHTENED_MONITORING",
        "REVIEW_WARNING",
    )


@pytest.mark.parametrize(
    "forbidden",
    [
        "EVACUATE",
        "MANDATORY_EVACUATION",
        "EMERGENCY_DECLARED",
        "EVACUATION",
        "WARNING",
        "MANDATORY EVACUATION",
        "EMERGENCY",
        "EVACUATING",
        "EVACUATION_ORDER",
        "ALERT",
        "DISASTER",
        "FLOOD_WARNING",
    ],
)
def test_no_emergency_state_is_representable(forbidden):
    """The absence is structural, not a documentation promise.

    Membership, not substring: `"WARNING"` is absent from the tuple even though
    `REVIEW_WARNING` contains it. Phase 7 can only produce the four exact states, and
    the eleven spellings a caller might plausibly try are all outside them.
    """
    assert forbidden not in RESPONSE_STATES


def test_policy_cannot_configure_an_evacuation():
    """The strongest safety property in the phase, asserted directly.

    A policy that asks for `EVACUATE` is refused. It is *not* mapped to the nearest
    state Phase 7 can provide, because a silently-downgraded evacuation request
    would leave a caller believing something acted on it.
    """
    with pytest.raises(UnsupportedResponseStateError) as caught:
        ResponsePolicy(risk_level_response={"CRITICAL": "EVACUATE"}, policy_source="a caller")

    assert "EVACUATE" in str(caught.value)
    assert "evacuation" in str(caught.value)


def test_policy_cannot_configure_a_mandatory_evacuation():
    with pytest.raises(UnsupportedResponseStateError):
        ResponsePolicy(risk_level_response={"CRITICAL": "MANDATORY_EVACUATION"}, policy_source="x")


def test_rule_cannot_escalate_to_an_evacuation():
    with pytest.raises(UnsupportedResponseStateError):
        ResponseRule(
            rule_id="r",
            risk_level_at_least="LOW",
            escalate_to="EVACUATE",
            source="x",
        )


def test_policy_cannot_map_to_withheld():
    """`WITHHELD` is the absence of a recommendation, not one."""
    with pytest.raises(InvalidResponsePolicyError) as caught:
        ResponsePolicy(risk_level_response={"LOW": "WITHHELD"}, policy_source="x")

    assert "absence of a recommendation" in str(caught.value)


def test_rule_cannot_target_withheld():
    with pytest.raises(InvalidResponsePolicyError):
        ResponseRule(rule_id="r", risk_level_at_least="LOW", escalate_to="WITHHELD", source="x")


def test_policy_cannot_key_on_an_unknown_risk_level():
    with pytest.raises(InvalidResponsePolicyError) as caught:
        ResponsePolicy(risk_level_response={"CATASTROPHIC": "MONITOR"}, policy_source="x")

    assert "CATASTROPHIC" in str(caught.value)


def test_policy_keys_are_phase6_risk_levels():
    """The mapping vocabulary is Phase 6's, borrowed rather than re-invented."""
    assert set(SUPPORTED_RISK_LEVELS) == {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert set(DEMO_RESPONSE_MAPPING) == set(SUPPORTED_RISK_LEVELS)


def test_authority_flags_are_permanently_false():
    """Not configuration - constants. Nothing in this repository can grant them."""
    assert OPERATIONAL_AUTHORITY is False
    assert PRODUCTION_READY_CLAIMED is False
    assert OPERATIONAL_AUTHORITY is ResponseDecision.__dataclass_fields__[
        "operational_authority"
    ].default
    assert PRODUCTION_READY_CLAIMED is ResponseDecision.__dataclass_fields__[
        "production_ready_claimed"
    ].default


# --------------------------------------------------------------------------- #
# Basic decisions, one per state the phase can reach
# --------------------------------------------------------------------------- #


def test_low_evaluated_risk_is_monitor(low_risk, demo_policy):
    assert low_risk.risk_level == "LOW"

    decision = decide_response(low_risk, policy=demo_policy)

    assert decision.decision == DECISION_MONITOR
    assert decision.status == "recommended"
    assert decision.is_recommendation
    assert not decision.is_withheld


def test_elevated_evaluated_risk_is_heightened_monitoring(medium_risk, demo_policy):
    assert medium_risk.risk_level == "MEDIUM"

    decision = decide_response(medium_risk, policy=demo_policy)

    assert decision.decision == DECISION_HEIGHTENED_MONITORING
    assert decision.status == "recommended"


def test_high_evaluated_risk_reaches_review_warning(high_risk, demo_policy):
    assert high_risk.risk_level == "HIGH"

    decision = decide_response(high_risk, policy=demo_policy)

    assert decision.decision == DECISION_REVIEW_WARNING
    assert decision.status == "recommended"


def test_critical_evaluated_risk_reaches_review_warning(critical_risk, demo_policy):
    assert critical_risk.risk_level == "CRITICAL"

    decision = decide_response(critical_risk, policy=demo_policy)

    assert decision.decision == DECISION_REVIEW_WARNING


def test_review_warning_is_reachable_from_configuration_alone(critical_risk):
    """A mapping may reach `REVIEW_WARNING` with no rule configured at all."""
    policy = demo_response_policy({"CRITICAL": DECISION_REVIEW_WARNING})

    decision = decide_response(critical_risk, policy=policy)

    assert decision.decision == DECISION_REVIEW_WARNING
    assert decision.rules == ()


def test_unavailable_risk_is_withheld(risk_withheld, demo_policy):
    """Phase 6 withheld for want of a threshold; Phase 7 must not resolve that."""
    assert risk_withheld.status == "withheld"
    assert risk_withheld.risk_level is None

    decision = decide_response(risk_withheld, policy=demo_policy)

    assert decision.decision == DECISION_WITHHELD
    assert decision.status == "withheld"
    assert decision.is_withheld
    assert not decision.is_recommendation


def test_non_evaluable_risk_is_withheld(risk_not_evaluable, demo_policy):
    """A probability exists, but no band was assigned. There is no level to act on."""
    assert risk_not_evaluable.evaluation_state == "not_evaluable"
    assert risk_not_evaluable.risk_level is None
    assert risk_not_evaluable.risk_score is not None

    decision = decide_response(risk_not_evaluable, policy=demo_policy)

    assert decision.decision == DECISION_WITHHELD
    assert "could not assign a risk band" in decision.rationale
    assert "no response category can be derived from it" in decision.rationale


def test_unavailable_risk_context_is_withheld(risk_context_unavailable, demo_policy):
    """A recorded level resting on the forecast alone, with nothing corroborating it."""
    assert risk_context_unavailable.status == "recorded"
    assert risk_context_unavailable.risk_level is not None
    assert risk_context_unavailable.evaluation_state == "context_unavailable"

    decision = decide_response(risk_context_unavailable, policy=demo_policy)

    assert decision.decision == DECISION_WITHHELD
    assert "could read no context" in decision.rationale


def test_partially_evaluated_risk_still_yields_a_recommendation(
    run_result, served_forecast, shared_residual_values, demo_policy
):
    """`partially_evaluated` is not `context_unavailable`, and must not withhold."""
    from hydro_phase7_fixtures import partial_context, risk_result_for_band

    risk = risk_result_for_band(
        run_result,
        served_forecast,
        shared_residual_values,
        "HIGH",
        context=partial_context(served_forecast.inference.entity, run_result.origin),
    )
    assert risk.evaluation_state == "partially_evaluated"

    decision = decide_response(risk, policy=demo_policy)

    assert decision.decision == DECISION_REVIEW_WARNING
    assert decision.status == "recommended"


def test_missing_policy_is_withheld(medium_risk):
    """No configured mapping: the default is to recommend nothing."""
    decision = decide_response(medium_risk, policy=ResponsePolicy())

    assert decision.decision == DECISION_WITHHELD
    assert "no response mapping is configured" in decision.rationale
    assert "no approved warning criteria" in decision.rationale


def test_unmapped_risk_level_is_withheld_not_defaulted(medium_risk):
    """A policy covering LOW only must not silently answer about MEDIUM."""
    decision = decide_response(medium_risk, policy=partial_mapping_policy("LOW"))

    assert decision.decision == DECISION_WITHHELD
    assert "does not cover risk level 'MEDIUM'" in decision.rationale
    assert "not defaulted to the nearest mapped one" in decision.rationale


def test_invalid_policy_is_refused_not_answered(medium_risk):
    """An unusable policy is a contract violation, raised rather than withheld.

    `decide_response` raises; `decide_response_safe` converts. Neither invents a
    category, and neither returns `MONITOR` for a policy that cannot be read.
    """
    with pytest.raises(InvalidResponsePolicyError) as caught:
        decide_response(medium_risk, policy="not a policy")

    assert "ResponsePolicy" in str(caught.value)

    decision = decide_response_safe(medium_risk, policy="not a policy")
    assert decision.decision == DECISION_WITHHELD
    assert "invalid_response_policy" in decision.rationale


def test_a_non_policy_mapping_is_refused(medium_risk):
    """Phase 7 reuses `ResponsePolicy` rather than accepting an arbitrary dict.

    A bare mapping would carry no source, no status and no version, and a decision
    made under it could not be audited afterwards.
    """
    with pytest.raises(InvalidResponsePolicyError) as caught:
        decide_response(medium_risk, policy={"MEDIUM": "MONITOR"})

    assert "reuses that policy" in str(caught.value)


def test_rules_holding_a_non_rule_are_refused(medium_risk, demo_policy):
    with pytest.raises(InvalidResponsePolicyError) as caught:
        decide_response(medium_risk, policy=demo_policy, rules=["not a rule"])

    assert "not a ResponseRule" in str(caught.value)


def test_missing_risk_result_is_refused(demo_policy):
    with pytest.raises(MissingRiskResultError) as caught:
        decide_response(None, policy=demo_policy)

    assert "does not assess risk itself" in str(caught.value)


def test_every_withheld_decision_explains_itself(risk_withheld, risk_not_evaluable, demo_policy):
    """No refusal may be silent. Each names a reason a caller can act on."""
    for risk in (risk_withheld, risk_not_evaluable):
        decision = decide_response(risk, policy=demo_policy)

        assert decision.decision == DECISION_WITHHELD
        assert decision.rationale.strip()
        assert "no response category is recommended" in decision.explain()
        assert "not the same as recommending that nothing be done" in decision.explain()


def test_withheld_decisions_never_carry_a_recommended_category(
    risk_withheld, risk_not_evaluable, risk_context_unavailable
):
    for risk in (risk_withheld, risk_not_evaluable, risk_context_unavailable):
        decision = decide_response(risk, policy=demo_response_policy())

        assert decision.decision == DECISION_WITHHELD
        assert decision.status == "withheld"
        assert decision.decision in RESPONSE_STATES


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #


def test_a_rule_raises_a_category_within_the_policy_ceiling(medium_risk):
    """MEDIUM maps to MONITOR; the rule lifts it to REVIEW_WARNING, which the policy allows."""
    policy = demo_response_policy(
        {"MEDIUM": DECISION_MONITOR, "CRITICAL": DECISION_REVIEW_WARNING}
    )

    decision = decide_response(medium_risk, policy=policy, rules=[demo_rule()])

    assert decision.decision == DECISION_REVIEW_WARNING
    assert [rule.rule_id for rule in decision.applied_rules] == ["demo-review-warning"]
    assert decision.applied_rules[0].fired


def test_a_rule_may_not_exceed_the_configured_ceiling(medium_risk):
    """A rule cannot produce a category the policy that authorised it cannot produce."""
    policy = demo_response_policy({"MEDIUM": DECISION_MONITOR})

    decision = decide_response(medium_risk, policy=policy, rules=[demo_rule()])

    assert decision.decision == DECISION_MONITOR
    assert decision.rules[0].fired is True
    assert decision.rules[0].applied is False
    assert "beyond the configured ceiling" in decision.rules[0].reason


def test_a_rule_below_its_trigger_does_not_fire(medium_risk, demo_policy):
    rule = demo_rule(at_least="CRITICAL")

    decision = decide_response(medium_risk, policy=demo_policy, rules=[rule])

    assert decision.decision == DECISION_HEIGHTENED_MONITORING
    assert decision.rules[0].fired is False
    assert "below the trigger CRITICAL" in decision.rules[0].reason


def test_non_fired_rules_are_still_recorded(medium_risk, demo_policy):
    """"No rule fired" and "no rule was configured" support different conclusions."""
    decision = decide_response(
        medium_risk, policy=demo_policy, rules=[demo_rule(at_least="CRITICAL")]
    )

    assert len(decision.rules) == 1
    assert decision.fired_rules == ()
    assert "configured but not applied" not in decision.explain()


def test_no_rules_configured_is_stated_explicitly(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    assert decision.rules == ()
    assert "no response rules are configured" in decision.explain()


def test_duplicate_rule_ids_are_refused(medium_risk, demo_policy):
    rule = demo_rule()
    with pytest.raises(InvalidResponsePolicyError) as caught:
        decide_response(medium_risk, policy=demo_policy, rules=[rule, rule])

    assert "appear more than once" in str(caught.value)
    assert "cannot be named in an explanation" in str(caught.value)


def test_rule_order_does_not_change_the_decision(critical_risk, demo_policy):
    """Rules are sorted by id, so input order cannot reach the output."""
    first = demo_rule(rule_id="a-rule", at_least="MEDIUM")
    second = demo_rule(rule_id="z-rule", at_least="HIGH", escalate_to=DECISION_REVIEW_WARNING)

    forward = decide_response(critical_risk, policy=demo_policy, rules=[first, second])
    reverse = decide_response(critical_risk, policy=demo_policy, rules=[second, first])

    assert forward.decision == reverse.decision
    assert forward.to_dict() == reverse.to_dict()


# --------------------------------------------------------------------------- #
# Context availability
# --------------------------------------------------------------------------- #


def test_available_exposure_is_recorded_but_carries_no_value(medium_risk):
    """The load-bearing claim: there is no field in which a count could be placed."""
    context = context_with_exposure(medium_risk, available_population())

    record = context.exposure[0]
    assert record.kind == "population"
    assert record.usable
    assert [f.name for f in dataclasses.fields(record)] == [
        "kind",
        "availability",
        "reason",
        "source",
    ]
    assert "value" not in record.to_dict()
    assert record.to_dict() == {
        "kind": "population",
        "availability": "valid",
        "reason": "",
        "source": "fixture-exposure-adapter",
        "usable": True,
    }


def test_no_field_anywhere_in_the_module_carries_an_exposure_count():
    """A structural check rather than a behavioural one.

    If a future edit adds a `value` field to `ExposureAvailability` — or a
    `population` count to any other type this module defines — this fails before any
    test starts depending on the new shape.

    Every dataclass the module defines is walked, not just the one that currently
    holds counts, because the type that would gain the field is the one that does not
    exist yet.
    """
    from app.engines.hydro import response_context as module

    count_shaped = re.compile(
        r"exposed|count|headcount|persons|residents|weight|value|total",
        re.IGNORECASE,
    )
    # Phase 6 facts copied for traceability. Both are counts of *signals* and
    # *events*, not of people or assets, and neither can be weighted into anything:
    # nothing in Phase 7 combines them.
    allowed = {
        "ResponseContext.risk_availability_counts",
        "ResponseContext.historical_event_count",
    }

    offenders: list[str] = []
    for name, obj in vars(module).items():
        if not (inspect.isclass(obj) and dataclasses.is_dataclass(obj)):
            continue
        if getattr(obj, "__module__", None) != module.__name__:
            continue
        for field in dataclasses.fields(obj):
            label = f"{name}.{field.name}"
            if count_shaped.search(field.name) and label not in allowed:
                offenders.append(label)

    assert offenders == [], f"count-shaped fields appeared: {offenders}"


def test_missing_context_is_recorded_as_missing_not_zero(medium_risk):
    context = context_with_exposure(medium_risk, missing_infrastructure())

    record = next(r for r in context.exposure if r.kind == "infrastructure")
    assert record.availability == "missing"
    assert not record.usable
    assert "value" not in record.to_dict()
    assert record.reason == "the caller had no asset register"


@pytest.mark.parametrize(
    "builder,state",
    [
        (unavailable_population, "unavailable"),
        (missing_infrastructure, "missing"),
        (stale_infrastructure, "stale"),
        (not_applicable_population, "not_applicable"),
    ],
)
def test_each_unusable_state_is_kept_distinct(medium_risk, builder, state):
    """Four different reasons for not having data, four different records.

    Both kinds are always reported, so the supplied one appears alongside a
    defaulted one - which is itself the point: the reader cannot tell "population
    was missing" from "infrastructure was missing" by counting records.
    """
    context = context_with_exposure(medium_risk, builder())
    supplied = builder().kind

    unusable = response_unavailable_context(context)
    states = {record.kind: record.availability for record in unusable}
    assert states[supplied] == state
    assert all(not record.usable for record in unusable)
    assert all(record.reason.strip() for record in unusable)


def test_missing_is_not_zero_across_every_unusable_state(medium_risk, demo_policy):
    """Four unusable states produce four identical decisions - and no zero anywhere.

    None of them may turn into a contributor with a value of 0, which is what a
    weighted sum would have produced.
    """
    baseline = decide_response(medium_risk, policy=demo_policy)

    for exposure in all_unusable_exposure():
        context = context_with_exposure(medium_risk, exposure)
        decision = decide_response(context, policy=demo_policy)

        assert decision.decision == baseline.decision
        kinds = {record.kind: record.availability for record in decision.unavailable_context}
        assert kinds[exposure.kind] == exposure.availability

    rendered = baseline.to_dict()
    for forbidden in ("response_score", "severity_score", "danger_score", "community_score"):
        assert forbidden not in rendered
        assert forbidden not in ResponseDecision.__dataclass_fields__
    unavailable = [record.to_dict() for record in baseline.unavailable_context]
    for record in unavailable:
        assert "value" not in record
        assert record["usable"] is False


def test_unavailable_gis_is_recorded_with_the_repository_marker(demo_context):
    """The exact marker Phase 6 uses must survive into Phase 7 unchanged."""
    assert not demo_context.gis_available
    assert demo_context.gis_reason == NOT_AVAILABLE
    assert NOT_AVAILABLE == "NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED"


def test_unavailable_gis_never_becomes_safe_geography(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    assert decision.unavailable_context
    text = decision.explain()
    assert "spatial context was unavailable" in text
    assert "no elevation, river-distance, floodplain or accessibility conclusion was drawn" in text


def test_unavailable_history_is_not_read_as_never_flooded(demo_context, demo_policy):
    decision = decide_response(demo_context, policy=demo_policy)

    assert not demo_context.historical_available
    assert "historical flood context was unavailable" in decision.explain()
    assert "not evidence that this location has never flooded" in decision.explain()


def test_available_gis_is_recorded_without_spawning_a_spatial_conclusion(
    run_result, served_forecast, shared_residual_values
):
    """GIS being available does not make Phase 7 reason about space."""
    from hydro_phase7_fixtures import risk_result_for_band, spatial_context

    risk = risk_result_for_band(
        run_result,
        served_forecast,
        shared_residual_values,
        "HIGH",
        context=spatial_context(served_forecast.inference.entity, run_result.origin),
    )
    context = response_context(risk)
    assert context.gis_available

    decision = decide_response(context, policy=demo_response_policy())

    assert decision.decision == DECISION_REVIEW_WARNING
    assert "elevation" not in decision.rationale
    assert "river-distance" not in decision.rationale
    assert "spatial context was unavailable" not in decision.explain()


def test_exposure_kind_must_be_one_of_the_two_known_kinds():
    """A kind Phase 7 does not know about is refused, not recorded as a third thing.

    Accepting an arbitrary kind would let a caller introduce an exposure dimension
    with no contract behind it - no definition of what "available" means for it, and
    no guarantee that anything downstream treats it consistently.
    """
    with pytest.raises(InvalidResponseContextError) as caught:
        available_exposure("livestock", source="a fixture")

    assert "livestock" in str(caught.value)


def test_unknown_exposure_kind_is_refused_when_supplied_directly():
    with pytest.raises(InvalidResponseContextError):
        ExposureAvailability(kind="livestock", availability="unavailable", reason="because")


def test_unusable_exposure_must_state_a_reason():
    with pytest.raises(InvalidResponseContextError) as caught:
        ExposureAvailability(kind="population", availability="unavailable", reason="")

    assert "must say why" in str(caught.value)


def test_unusable_exposure_states_are_phase6_states():
    """Phase 7 does not extend the availability vocabulary.

    The four unusable states are borrowed; `valid` is the only usable one and
    `unavailable_exposure` refuses it, because a record labelled "not usable" while
    carrying `valid` is a contradiction rather than a state.
    """
    assert set(RESPONSE_AVAILABILITY) == {
        "valid",
        "missing",
        "unavailable",
        "not_applicable",
        "stale",
    }
    assert set(RESPONSE_UNUSABLE) == set(RESPONSE_AVAILABILITY) - {"valid"}
    for state in RESPONSE_UNUSABLE:
        assert unavailable_exposure("population", state, reason="a reason").availability == state
    with pytest.raises(InvalidResponseContextError):
        unavailable_exposure("population", "valid", reason="a reason")


def test_duplicate_exposure_kinds_are_refused(medium_risk):
    with pytest.raises(InvalidResponseContextError) as caught:
        context_with_exposure(medium_risk, available_population(), available_population())

    assert "were supplied more than once" in str(caught.value)
    assert "silently keeping one would misreport the other" in str(caught.value)


def test_all_exposure_kinds_are_reported(medium_risk):
    """A reader can always answer "was exposure considered?" - for both kinds."""
    context = response_context(medium_risk)

    assert {record.kind for record in context.exposure} == set(EXPOSURE_KINDS)


# --------------------------------------------------------------------------- #
# Explanation
# --------------------------------------------------------------------------- #


def test_explanation_names_the_risk_result_it_consumed(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    assert medium_risk.risk_result_id in decision.explain()
    assert "phase 6 owns the risk classification" in decision.explain()
    assert "phase 7 did not recompute it" in decision.explain()


def test_explanation_lists_what_was_actually_evaluated(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    names = {item.name for item in decision.evidence}
    assert "risk_level" in names
    assert "risk_score" in names
    assert decision.evidence_read
    text = decision.explain()
    assert "input(s) were read" in text
    for name in names:
        assert name in text


def test_explanation_marks_inputs_that_did_not_decide(medium_risk, demo_policy):
    """A risk score that was read but did not move the category says so."""
    decision = decide_response(medium_risk, policy=demo_policy)

    score = next(item for item in decision.evidence if item.name == "risk_score")
    assert score.contributed is False
    assert "read, did not decide" in decision.explain()
    assert "applies no numeric threshold of its own" in score.reason


def test_explanation_never_claims_unavailable_context_contributed(medium_risk, demo_policy):
    """The BAD/GOOD pair from the phase brief, asserted on real output."""
    decision = decide_response(medium_risk, policy=demo_policy)

    text = decision.explain()
    assert "did not contribute to this decision" in text
    assert "not counted as zero" in text
    assert "not read as reassuring" in text
    for record in decision.unavailable_context:
        contributing = [item for item in decision.evidence if item.contributed]
        assert all(item.name != record.kind for item in contributing)


def test_explanation_states_the_policy_that_produced_the_category(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    assert DEMO_RESPONSE_SOURCE in decision.explain()
    assert "policy status 'pending'" in decision.explain()
    assert decision.rationale in decision.explain()


def test_explanation_states_the_demo_nature_of_the_underlying_level(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    text = decision.explain()
    assert "demo value with no official meaning" in text
    assert "DEMO" in medium_risk.threshold_configuration


def test_explanation_states_synthetic_demo_status(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    assert decision.synthetic_demo is True
    assert SYNTHETIC_DATA_DISCLAIMER in decision.explain()
    assert decision.data_status == medium_risk.data_status


def test_explanation_states_that_no_emergency_state_is_available(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    text = decision.explain()
    assert "no evacuation, mandatory evacuation, or emergency declaration" in text
    assert "none was requested" in text


def test_recommendation_is_labelled_a_recommendation(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    assert RECOMMENDATION_DISCLAIMER in decision.explain()
    assert "not a flood warning" in decision.explain()
    assert "no operational or government authority" in decision.explain()


def test_withheld_explanation_does_not_carry_the_recommendation_line(risk_withheld, demo_policy):
    decision = decide_response(risk_withheld, policy=demo_policy)

    assert RECOMMENDATION_DISCLAIMER not in decision.explain()


def test_explanation_when_no_input_was_read(risk_withheld, demo_policy):
    decision = decide_response(risk_withheld, policy=demo_policy)

    assert decision.evidence == ()
    assert "a decision made from nothing is recorded as such" in decision.explain()


def test_explain_is_the_joined_explanation(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    assert decision.explain() == " ".join(decision.explanation)
    assert len(decision.explanation) >= 5


def test_evidence_requires_a_name_source_and_reason():
    with pytest.raises(InvalidResponseContextError):
        DecisionEvidence(
            name="risk_level",
            value="MEDIUM",
            units=None,
            source="",
            availability="valid",
            contributed=True,
            reason="because",
        )


def test_evidence_availability_must_be_a_known_state():
    with pytest.raises(InvalidResponseContextError):
        DecisionEvidence(
            name="risk_level",
            value="MEDIUM",
            units=None,
            source="phase 6",
            availability="probably fine",
            contributed=True,
            reason="because",
        )


def test_a_none_value_is_not_rendered_as_a_bare_none(medium_risk, demo_policy):
    """`None` next to a signal name reads as a missing measurement.

    Phase 7 deliberately does not carry signal values, which is a scope boundary -
    not a data gap - and the two must not look alike.
    """
    decision = decide_response(medium_risk, policy=demo_policy)

    signal_evidence = [item for item in decision.evidence if item.name.startswith("phase6_signal:")]
    assert signal_evidence
    for item in signal_evidence:
        assert item.value is None
    text = decision.explain()
    assert "no value carried" in text
    assert "=None" not in text


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


def test_provenance_chains_forecast_to_risk_to_response(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)
    provenance = decision.provenance

    assert provenance["forecast_id"] == medium_risk.forecast_id
    assert provenance["risk_result_id"] == medium_risk.risk_result_id
    assert provenance["risk_contract_version"] == medium_risk.risk_contract_version
    assert provenance["response_contract_version"] == RESPONSE_CONTRACT_VERSION
    assert provenance["entity"] == medium_risk.forecast.entity
    assert provenance["risk_level"] == medium_risk.risk_level
    assert provenance["response_policy_version"] == demo_policy.policy_version
    assert provenance["response_policy_status"] == "pending"


def test_provenance_records_the_absence_of_authority(medium_risk, demo_policy):
    provenance = decide_response(medium_risk, policy=demo_policy).provenance

    assert provenance["operational_authority"] is False
    assert provenance["production_ready_claimed"] is False


def test_provenance_carries_the_phase6_threshold_and_configuration(medium_risk, demo_policy):
    provenance = decide_response(medium_risk, policy=demo_policy).provenance

    assert provenance["risk_threshold_policy"] == medium_risk.threshold_policy
    assert provenance["risk_configuration_version"] == medium_risk.risk_configuration_version


def test_decision_identifies_the_forecast_and_its_horizon(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    assert decision.forecast_id == medium_risk.forecast_id
    assert decision.forecast_horizon == medium_risk.forecast.horizon
    assert decision.forecast_origin == medium_risk.forecast.origin_instant


def test_decision_id_is_deterministic_and_readable(medium_risk, demo_policy):
    decision = decide_response(medium_risk, policy=demo_policy)

    assert decision.decision_id.startswith("response-")
    prefix, _, digest = decision.decision_id.partition("@")
    assert prefix
    assert digest
    assert len(digest) == 12
    assert all(char in "0123456789abcdef" for char in digest)
    assert medium_risk.forecast.entity in decision.decision_id
    assert "MEDIUM" in decision.decision_id


def test_decision_id_is_not_a_uuid_or_a_counter(medium_risk, demo_policy):
    first = decide_response(medium_risk, policy=demo_policy)
    second = decide_response(medium_risk, policy=demo_policy)

    assert first.decision_id == second.decision_id
    assert len({first.decision_id}) == 1


def test_decision_id_changes_when_the_policy_changes(medium_risk):
    one = decide_response(medium_risk, policy=demo_response_policy())
    two = decide_response(medium_risk, policy=demo_response_policy(policy_version="other/v1"))

    assert one.decision_id != two.decision_id
    assert default_decision_id(
        response_context(medium_risk), demo_response_policy()
    ) != default_decision_id(
        response_context(medium_risk), demo_response_policy(policy_version="other/v1")
    )


def test_policy_provenance_is_carried_whole(medium_risk):
    policy = demo_response_policy(policy_reference="demo-ref-001")

    decision = decide_response(medium_risk, policy=policy)

    assert decision.response_policy == policy.to_dict()
    assert decision.response_policy["policy_reference"] == "demo-ref-001"
    assert decision.response_policy["operational_authority"] is False


def test_serialised_decision_is_plain_json_types(medium_risk, demo_policy):
    import json

    decision = decide_response(medium_risk, policy=demo_policy)
    payload = decision.to_dict()

    assert json.loads(json.dumps(payload)) == payload
    assert payload["disclaimer"] == SYNTHETIC_DATA_DISCLAIMER
    assert payload["synthetic_demo"] is True
    assert payload["production_ready_claimed"] is False
    assert payload["operational_authority"] is False


# --------------------------------------------------------------------------- #
# Contract descriptions
# --------------------------------------------------------------------------- #


def test_response_contract_description_states_the_deliberate_absences():
    description = response_contract_description()

    assert description["response_states"] == list(RESPONSE_STATES)
    assert description["deliberately_absent_states"] == [
        "EVACUATE",
        "MANDATORY_EVACUATION",
        "EMERGENCY_DECLARED",
    ]
    assert description["default_decision"] == DECISION_WITHHELD
    assert description["composite_score"] is None
    assert description["operational_authority"] is False
    assert description["production_ready_claimed"] is False
    assert "EVACUATE" in description["deliberately_absent_states_reason"]
    assert "emergency authority" in description["deliberately_absent_states_reason"]
    assert "phase 6 owns" in description["risk_authority"]
    assert "not on a signal value" in description["risk_authority"]
    assert description["gis_absent_marker"] == NOT_AVAILABLE


def test_context_contract_description_states_that_exposure_carries_no_values():
    description = context_contract_description()

    assert description["exposure_carries_values"] is False
    assert description["exposure_kinds"] == list(EXPOSURE_KINDS)
    assert description["gis_absent_marker"] == NOT_AVAILABLE
    assert description["no_clock"]
    assert description["no_composite_score"]


def test_both_contracts_reuse_the_phase6_errors():
    described = set(context_contract_description()["reused_phase6_errors"]) | set(
        response_contract_description()["reused_phase6_errors"]
    )

    assert described == {"entity_mismatch", "future_context"}


# --------------------------------------------------------------------------- #
# Errors versus states
# --------------------------------------------------------------------------- #


def test_safe_wrapper_turns_a_contract_violation_into_a_withheld_decision(demo_policy):
    decision = decide_response_safe(None, policy=demo_policy)

    assert decision.decision == DECISION_WITHHELD
    assert decision.status == "withheld"
    assert "missing_risk_result" in decision.rationale
    assert "nothing be done" in decision.explain()


def test_response_from_error_names_the_reason(medium_risk):
    error = InvalidResponsePolicyError("a specific policy failure")

    decision = response_from_error(error, policy=demo_response_policy(), context=medium_risk)

    assert decision.decision == DECISION_WITHHELD
    assert "invalid_response_policy" in decision.rationale
    assert "a specific policy failure" in decision.rationale


def test_response_from_error_without_a_context_still_withholds():
    decision = response_from_error(InvalidResponsePolicyError("no context to attach"))

    assert decision.decision == DECISION_WITHHELD
    assert decision.entity == "unknown"
    assert SYNTHETIC_DATA_DISCLAIMER in decision.disclaimer
    assert decision.operational_authority is False


def test_response_from_error_tolerates_a_non_boundary_exception():
    decision = response_from_error(ValueError("something else entirely"))

    assert decision.decision == DECISION_WITHHELD
    assert "something else entirely" in decision.rationale


def test_no_error_path_returns_a_recommendation(demo_policy, medium_risk):
    """Every refusal is `WITHHELD`. None is `MONITOR`."""
    for call in (
        lambda: decide_response_safe(None, policy=demo_policy),
        lambda: response_from_error(InvalidResponsePolicyError("x"), context=medium_risk),
        lambda: response_from_error(ValueError("x")),
    ):
        assert call().decision == DECISION_WITHHELD


