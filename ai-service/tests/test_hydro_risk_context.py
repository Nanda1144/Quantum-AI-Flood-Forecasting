# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 6: context availability, units, escalation rules, and the explanation.

The claim under test here is the one that makes a risk result trustworthy:
**every piece of evidence carries its source, its units, its availability state and
its observation instant, and nothing that was not read can appear in the output.**

The four availability states are distinguished on purpose. `missing`, `unavailable`,
`not_applicable` and `stale` are different facts about the world, and collapsing
them into one "no data" is how a catchment with no rain gauge comes to look like a
dry one. Each has its own test here.

Spatial context is tested in both states — absent, and supplied by a provider — so
the GIS boundary is shown to be a real interface rather than a stub that can only say
"unavailable". The provider used for the positive case is a test double named as
one; no GIS engine is implemented and none is imported.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest

from app.engines.hydro import risk_context
from app.engines.hydro.config import RiskPolicy
from app.engines.hydro.domains import CANONICAL_QUANTITY, FloodEvent, SchemaError
from app.engines.hydro.preprocess_units import DIM_LENGTH, DIM_VOLUME_FLOW
from app.engines.hydro.forecast_risk import (
    RISK_STATUS_WITHHELD,
    RiskConfiguration,
    RiskEscalationRule,
    StaleContextRuleError,
    assess_risk,
    context_digest,
)
from app.engines.hydro.risk_context import (
    CONTEXT_CONTRACT_VERSION,
    CONTEXT_EVALUATION_STATES,
    CONTEXT_FULLY_EVALUATED,
    CONTEXT_NOT_EVALUABLE,
    CONTEXT_PARTIALLY_EVALUATED,
    CONTEXT_UNAVAILABLE,
    RISK_QUANTITIES,
    QUANTITY_DIMENSIONS,
    SIGNAL_AVAILABILITY,
    SIGNAL_MISSING,
    SIGNAL_NOT_APPLICABLE,
    SIGNAL_STALE,
    SIGNAL_UNAVAILABLE,
    SIGNAL_VALID,
    EntityMismatchError,
    FutureContextError,
    GisContext,
    HistoricalContext,
    InvalidRiskConfigurationError,
    InvalidUnitsError,
    MissingRiskContextError,
    RiskContext,
    RiskSignal,
    SIGNAL_UNUSABLE,
    UnsupportedContextError,
    availability_counts,
    available_signal,
    context_contract_description,
    evaluate_context,
    evaluation_state,
    unavailable_gis_context,
    unavailable_historical_context,
    unavailable_signal,
    unusable_signals,
)

from hydro_phase6_fixtures import (
    BAND_EDGES,
    BAND_LABELS,
    STATION_A,
    context,
    demo_policy,
    empty_context,
    full_context,
    origin,
    partial_context,
    rainfall_rule,
    residuals,
    risk_config,
    run,
    served,
    sigma,
    spatial_context,
    stale_context,
    station_a,
    station_b,
    threshold_for_band,
)


# --------------------------------------------------------------------------- #\n
# Availability is explicit
# --------------------------------------------------------------------------- #


def test_the_availability_vocabulary_is_closed():
    """A caller cannot declare a state this module does not implement."""
    assert SIGNAL_AVAILABILITY == (
        SIGNAL_VALID,
        SIGNAL_MISSING,
        SIGNAL_UNAVAILABLE,
        SIGNAL_NOT_APPLICABLE,
        SIGNAL_STALE,
    )
    assert SIGNAL_UNUSABLE == (
        SIGNAL_MISSING,
        SIGNAL_UNAVAILABLE,
        SIGNAL_NOT_APPLICABLE,
        SIGNAL_STALE,
    )


def test_an_unknown_availability_state_is_refused():
    with pytest.raises(UnsupportedContextError) as excinfo:
        RiskSignal(
            name="x",
            quantity="water_level",
            value=1.0,
            unit="m",
            source="s",
            availability="probably fine",
        )
    assert "probably fine" in str(excinfo.value)


def test_a_valid_signal_cannot_be_declared_without_a_value():
    """`valid` with no number is a missing signal wearing the wrong label."""
    with pytest.raises(UnsupportedContextError) as excinfo:
        RiskSignal(
            name="x", quantity="water_level", value=None, unit="m", source="s",
            availability=SIGNAL_VALID,
        )
    assert "missing signal wearing the wrong label" in str(excinfo.value)


def test_a_valid_signal_cannot_be_declared_without_an_instant():
    """Evidence with no timestamp cannot be checked for leakage, so it is refused."""
    with pytest.raises(UnsupportedContextError) as excinfo:
        RiskSignal(
            name="x", quantity="water_level", value=1.0, unit="m", source="s",
            availability=SIGNAL_VALID,
        )
    assert "cannot be checked for leakage" in str(excinfo.value)


def test_a_naive_instant_is_refused_rather_than_assumed_utc():
    """Assuming an offset is how a +05:30 gauge reading lands on the wrong side of origin."""
    with pytest.raises(FutureContextError) as excinfo:
        available_signal(
            "x", "water_level", 1.0, "m", source="s",
            observed_at=dt.datetime(2024, 1, 4, 5, 0),
        )
    assert "timezone-aware" in str(excinfo.value)


def test_an_unavailable_signal_must_carry_its_reason():
    """A gap that cannot say what kind of gap it is forces the reader to guess."""
    with pytest.raises(UnsupportedContextError):
        unavailable_signal(
            "x", "water_level", source="s", availability=SIGNAL_MISSING, reason=""
        )


def test_unavailable_signal_refuses_to_build_a_valid_one():
    """The factory for an absence cannot be used to smuggle in a presence."""
    with pytest.raises(UnsupportedContextError):
        unavailable_signal(
            "x", "water_level", source="s", availability=SIGNAL_VALID, reason="because"
        )


def test_an_unknown_quantity_is_refused():
    with pytest.raises(UnsupportedContextError):
        available_signal(
            "x", "soil_moisture", 1.0, "m", source="s",
            observed_at=dt.datetime(2024, 1, 4, 5, 0, tzinfo=dt.timezone.utc),
        )


def test_duplicate_signal_names_are_refused(station_a, origin):
    """Two readings of one quantity with no stated precedence is a coin toss."""
    signal = available_signal(
        "level", "water_level", 1.0, "m", source="s", observed_at=origin
    )
    with pytest.raises(UnsupportedContextError) as excinfo:
        RiskContext(entity=station_a, signals=(signal, signal))
    assert "coin toss" in str(excinfo.value)


def test_signals_are_ordered_by_name_regardless_of_construction_order(station_a, origin):
    """Two callers building the same context differently get the same evaluation order."""
    first = available_signal("aaa", "water_level", 1.0, "m", source="s", observed_at=origin)
    second = available_signal("zzz", "rainfall", 1.0, "mm", source="s", observed_at=origin)
    forward = RiskContext(entity=station_a, signals=(first, second))
    backward = RiskContext(entity=station_a, signals=(second, first))
    assert forward.names() == backward.names() == ("aaa", "zzz")


# --------------------------------------------------------------------------- #
# A missing signal is never zero
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("availability", list(SIGNAL_UNUSABLE))
def test_no_unusable_signal_ever_carries_a_number(availability):
    """The rule that stops "no rainfall record" from reading as "rainfall = 0"."""
    signal = unavailable_signal(
        "x", "rainfall", source="s", availability=availability, reason="no record exists"
    )
    assert signal.value is None
    assert signal.has_value is False
    assert signal.is_valid is False


@pytest.mark.parametrize("availability", list(SIGNAL_UNUSABLE))
def test_an_unusable_signal_is_never_usable_after_evaluation(
    availability, station_a, origin
):
    signal = unavailable_signal(
        "x", "rainfall", source="s", availability=availability, reason="no record exists"
    )
    context = RiskContext(entity=station_a, signals=(signal,))
    evaluations = evaluate_context(
        context, forecast_entity=station_a, forecast_origin=origin
    )
    assert evaluations[0].usable is False
    assert evaluations[0].value is None


def test_a_stale_reading_keeps_its_value_in_the_signal_but_not_in_the_evaluation(
    station_a, origin
):
    """The explanation can say "held 2.9 m but too old to use", which is more useful."""
    context = stale_context(station_a, origin, age_seconds=3600.0 * 48)
    evaluations = evaluate_context(
        context, forecast_entity=station_a, forecast_origin=origin,
        default_max_age_seconds=3600.0,
    )
    evaluation = evaluations[0]

    assert evaluation.availability == SIGNAL_STALE
    assert evaluation.usable is False
    assert evaluation.value is None
    assert evaluation.observed_at is not None
    assert "beyond the configured" in evaluation.reason


# --------------------------------------------------------------------------- #
# Evaluation state
# --------------------------------------------------------------------------- #


def test_every_valid_signal_is_fully_evaluated(station_a, origin, context):
    evaluations = evaluate_context(
        context, forecast_entity=station_a, forecast_origin=origin
    )
    assert evaluation_state(evaluations) == CONTEXT_FULLY_EVALUATED
    assert availability_counts(evaluations)["valid"] == len(evaluations)


def test_a_mix_of_states_is_partially_evaluated(station_a, origin):
    evaluations = evaluate_context(
        partial_context(station_a, origin), forecast_entity=station_a, forecast_origin=origin
    )
    assert evaluation_state(evaluations) == CONTEXT_PARTIALLY_EVALUATED
    counts = availability_counts(evaluations)
    assert counts[SIGNAL_VALID] == 1
    assert counts[SIGNAL_MISSING] == 1
    assert counts[SIGNAL_UNAVAILABLE] == 1


def test_no_usable_signal_is_context_unavailable(station_a, origin):
    context = RiskContext(
        entity=station_a,
        signals=(
            unavailable_signal(
                "level", "water_level", source="s", availability=SIGNAL_MISSING,
                reason="no reading",
            ),
        ),
    )
    evaluations = evaluate_context(
        context, forecast_entity=station_a, forecast_origin=origin
    )
    assert evaluation_state(evaluations) == CONTEXT_UNAVAILABLE
    assert len(unusable_signals(evaluations)) == 1


def test_no_declared_signal_at_all_is_context_unavailable(station_a, origin):
    evaluations = evaluate_context(
        empty_context(station_a, origin), forecast_entity=station_a, forecast_origin=origin
    )
    assert evaluations == ()
    assert evaluation_state(evaluations) == CONTEXT_UNAVAILABLE


def test_the_counts_report_every_state_even_at_zero(station_a, origin, context):
    """An omitted `stale` cannot be told apart from staleness never being considered."""
    evaluations = evaluate_context(
        context, forecast_entity=station_a, forecast_origin=origin
    )
    counts = availability_counts(evaluations)
    assert set(counts) == set(SIGNAL_AVAILABILITY)
    assert counts[SIGNAL_STALE] == 0


def test_not_evaluable_is_a_state_the_context_layer_never_reports(station_a, origin):
    """`not_evaluable` is a verdict on the risk, not on the evidence.

    The context layer answers "what could be read", and any of its answers is either a
    real reading or an honest absence. Deciding that no band could be assigned at all
    is `forecast_risk`'s job, because only it knows the threshold and the spread.
    """
    assert CONTEXT_NOT_EVALUABLE in CONTEXT_EVALUATION_STATES
    for context_value in (
        full_context(station_a, origin),
        partial_context(station_a, origin),
        empty_context(station_a, origin),
    ):
        evaluations = evaluate_context(
            context_value, forecast_entity=station_a, forecast_origin=origin
        )
        assert evaluation_state(evaluations) != CONTEXT_NOT_EVALUABLE


def test_not_evaluable_is_reachable_through_the_risk_layer(served, station_a, origin):
    """The fourth state is a real verdict, not decoration in a contract description."""
    result = assess_risk(served, config=risk_config(3.5), context=full_context(station_a, origin))
    assert result.evaluation_state == CONTEXT_NOT_EVALUABLE
    assert result.status == RISK_STATUS_WITHHELD
    assert result.risk_level is None


def test_the_evaluation_state_appears_on_the_risk_result(
    served, context, sigma, residuals
):
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(served, config=risk_config(threshold), context=context, residuals=residuals)
    assert result.evaluation_state == CONTEXT_FULLY_EVALUATED
    assert result.evaluation_state in CONTEXT_EVALUATION_STATES


def test_a_level_from_an_empty_context_is_reported_as_context_unavailable(
    served, station_a, origin, sigma, residuals
):
    """The band came from the forecast alone. That is a real claim, stated as itself."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served,
        config=risk_config(threshold),
        context=empty_context(station_a, origin),
        residuals=residuals,
    )
    assert result.risk_level == "MEDIUM"
    assert result.evaluation_state == CONTEXT_UNAVAILABLE
    assert "no escalation rules are configured" in result.explain()


# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #


def test_a_water_level_in_millimetres_is_accepted_as_a_length(station_a, origin):
    """`mm` and `m` are both depths; the unit is recorded, not rejected."""
    context = RiskContext(
        entity=station_a,
        signals=(
            available_signal(
                "level", "water_level", 2900.0, "mm", source="s", observed_at=origin
            ),
        ),
    )
    evaluation = evaluate_context(
        context, forecast_entity=station_a, forecast_origin=origin
    )[0]
    assert evaluation.usable is True
    assert evaluation.unit == "mm"
    assert evaluation.dimension == "length"


def test_a_rainfall_intensity_is_not_a_rainfall_accumulation(station_a, origin):
    """A depth and a depth-per-time are different quantities and are not reconciled."""
    context = RiskContext(
        entity=station_a,
        signals=(
            available_signal(
                "rain", "rainfall", 12.0, "mm/h", source="s", observed_at=origin
            ),
        ),
    )
    # `mm/h` is a legal rainfall unit, so the signal itself is fine.
    evaluation = evaluate_context(
        context, forecast_entity=station_a, forecast_origin=origin
    )[0]
    assert evaluation.dimension == "length_per_time"


def test_a_depth_per_time_is_refused_for_a_water_level(station_a, origin):
    """The rule that catches `mm/h` checked against a metre threshold."""
    context = RiskContext(
        entity=station_a,
        signals=(
            available_signal(
                "level", "water_level", 12.0, "mm/h", source="s", observed_at=origin
            ),
        ),
    )
    with pytest.raises(InvalidUnitsError) as excinfo:
        evaluate_context(context, forecast_entity=station_a, forecast_origin=origin)
    assert "depth-per-time" in str(excinfo.value)


def test_an_unrecognised_unit_is_refused(station_a, origin):
    context = RiskContext(
        entity=station_a,
        signals=(
            available_signal(
                "level", "water_level", 12.0, "bananas", source="s", observed_at=origin
            ),
        ),
    )
    with pytest.raises(InvalidUnitsError) as excinfo:
        evaluate_context(context, forecast_entity=station_a, forecast_origin=origin)
    assert "not a unit this repository recognises" in str(excinfo.value)


def test_inflow_is_measured_with_no_unit_constraint(station_a, origin):
    """`domains` records inflow's unit as UNDETERMINED, so Phase 6 does not guess one.

    An unconstrained quantity is not an unvalidated one: whatever unit arrives must
    still be a unit this repository recognises, and the dimension that was found is
    recorded so a rule can still ask about it.
    """
    context = RiskContext(
        entity=station_a,
        signals=(
            available_signal(
                "inflow", "inflow", 40.0, "m3/s", source="s", observed_at=origin
            ),
        ),
    )
    evaluation = evaluate_context(
        context, forecast_entity=station_a, forecast_origin=origin
    )[0]
    assert evaluation.usable is True
    assert evaluation.dimension == "volume_flow"


def test_an_unconstrained_quantity_still_refuses_an_unrecognised_unit(
    station_a, origin
):
    """`inflow` has no allowed dimensions, which is not a licence to accept nonsense."""
    context = RiskContext(
        entity=station_a,
        signals=(
            available_signal(
                "inflow", "inflow", 40.0, "bananas", source="s", observed_at=origin
            ),
        ),
    )
    with pytest.raises(InvalidUnitsError) as excinfo:
        evaluate_context(context, forecast_entity=station_a, forecast_origin=origin)
    assert "not a unit this repository recognises" in str(excinfo.value)


def test_inflow_declares_no_allowed_dimensions():
    """The reason it is unconstrained is recorded in the contract, not inferred."""
    assert QUANTITY_DIMENSIONS["inflow"] == ()
    assert QUANTITY_DIMENSIONS["water_level"] == (DIM_LENGTH,)
    assert QUANTITY_DIMENSIONS["discharge"] == (DIM_VOLUME_FLOW,)


def test_the_quantity_vocabulary_comes_from_the_repository():
    """`water_level`, `rainfall`, `inflow` and `discharge` are `domains`' own names."""
    for quantity in CANONICAL_QUANTITY.values():
        assert quantity in RISK_QUANTITIES
    assert "water_level_change" in RISK_QUANTITIES
    assert "elevation" in RISK_QUANTITIES
    assert "river_distance" in RISK_QUANTITIES


# --------------------------------------------------------------------------- #
# Freshness
# --------------------------------------------------------------------------- #


def test_a_signal_older_than_its_limit_goes_stale(station_a, origin):
    config = risk_config(3.5, default_max_age_seconds=3600.0)
    evaluations = evaluate_context(
        stale_context(station_a, origin),
        forecast_entity=station_a,
        forecast_origin=origin,
        default_max_age_seconds=3600.0,
    )
    assert evaluations[0].availability == SIGNAL_STALE
    assert evaluations[0].usable is False
    assert config.is_usable  # a stale context does not invalidate the threshold


def test_a_per_signal_limit_overrides_the_default(station_a, origin):
    evaluations = evaluate_context(
        stale_context(station_a, origin),
        forecast_entity=station_a,
        forecast_origin=origin,
        max_age_seconds={"water_level_now": 3600.0 * 24 * 30},
        default_max_age_seconds=3600.0,
    )
    assert evaluations[0].availability == SIGNAL_VALID


def test_no_configured_limit_means_nothing_goes_stale(station_a, origin):
    """Phase 6 will not invent an age limit nobody configured."""
    evaluations = evaluate_context(
        stale_context(station_a, origin), forecast_entity=station_a, forecast_origin=origin
    )
    assert evaluations[0].availability == SIGNAL_VALID
    assert evaluations[0].usable is True


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf"), "3600"])
def test_an_unusable_age_limit_is_a_configuration_error(station_a, origin, limit):
    context = full_context(station_a, origin)
    with pytest.raises(InvalidRiskConfigurationError):
        evaluate_context(
            context,
            forecast_entity=station_a,
            forecast_origin=origin,
            default_max_age_seconds=limit,
        )


# --------------------------------------------------------------------------- #
# Escalation rules
# --------------------------------------------------------------------------- #


def assess_with_rule(
    served, context, residuals, measured_sigma, *, config_kwargs=None, **rule_kwargs
):
    threshold = threshold_for_band(served.inference.prediction, measured_sigma, "LOW")
    config = risk_config(
        threshold, rules=(rainfall_rule(**rule_kwargs),), **(config_kwargs or {})
    )
    return assess_risk(served, config=config, context=context, residuals=residuals)


def test_a_rule_raises_the_band_and_records_the_value_that_fired_it(
    served, context, residuals, sigma
):
    result = assess_with_rule(served, context, residuals, sigma, mm=50.0)
    fired = result.fired_rules

    assert result.risk_level == "HIGH"
    assert [rule.rule_id for rule in fired] == ["demo-heavy-rainfall"]
    assert fired[0].observed_value == pytest.approx(63.2)
    assert fired[0].observed_units == "mm"
    assert fired[0].configured_value == 50.0
    assert fired[0].configured_units == "mm"
    assert fired[0].escalate_to == "HIGH"
    assert fired[0].source == "DEMO rainfall policy; NOT an official warning criterion"


def test_a_rule_that_does_not_fire_is_still_recorded(
    served, station_a, origin, residuals, sigma
):
    """A reader must be able to tell "no rule fired" from "no rule was configured"."""
    dry = full_context(station_a, origin, rainfall_mm=3.0)
    result = assess_with_rule(served, dry, residuals, sigma, mm=50.0)

    assert result.fired_rules == ()
    assert len(result.escalations) == 1
    assert result.escalations[0].fired is False
    assert "does not satisfy" in result.escalations[0].reason


def test_no_rules_configured_says_so_in_the_explanation(
    served, context, sigma, residuals
):
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(served, config=risk_config(threshold), context=context, residuals=residuals)
    assert result.escalations == ()
    assert "no escalation rules are configured" in result.explain()
    assert "could not change the band" in result.explain()


def test_a_rule_only_ever_raises_the_band(served, context, residuals, sigma):
    """A contextual rule has no business overriding a computed probability."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "CRITICAL")
    config = risk_config(threshold, rules=(rainfall_rule(escalate_to="LOW", mm=1.0),))
    result = assess_risk(served, config=config, context=context, residuals=residuals)

    assert result.risk_level == "CRITICAL"
    assert result.fired_rules  # it fired, and was still not applied
    assert "already at or above" in result.explain()


def test_the_highest_fired_rule_wins(served, context, residuals, sigma):
    """Two rules fire; the more serious band is the one reported."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "LOW")
    config = risk_config(
        threshold,
        rules=(
            rainfall_rule(rule_id="a-moderate", escalate_to="MEDIUM", mm=50.0),
            rainfall_rule(rule_id="z-severe", escalate_to="CRITICAL", mm=50.0),
        ),
    )
    result = assess_risk(served, config=config, context=context, residuals=residuals)

    assert result.risk_level == "CRITICAL"
    assert len(result.fired_rules) == 2
    assert "superseded by CRITICAL" in result.explain()


def test_rules_are_evaluated_in_a_stable_order(served, context, residuals, sigma):
    """Two callers listing the rules differently get the same assessment."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "LOW")
    forward = rainfall_rule(rule_id="a-moderate", escalate_to="MEDIUM", mm=50.0)
    backward = rainfall_rule(rule_id="z-severe", escalate_to="CRITICAL", mm=50.0)

    first = assess_risk(
        served, config=risk_config(threshold, rules=(forward, backward)),
        context=context, residuals=residuals,
    )
    second = assess_risk(
        served, config=risk_config(threshold, rules=(backward, forward)),
        context=context, residuals=residuals,
    )
    assert [rule.rule_id for rule in first.escalations] == ["a-moderate", "z-severe"]
    assert first.to_dict() == second.to_dict()


def test_a_required_rule_refuses_when_its_signal_is_absent(
    served, station_a, origin, residuals, sigma
):
    """A rule that says it needs a signal is told, rather than quietly not firing."""
    context = RiskContext(
        entity=station_a,
        signals=(
            available_signal(
                "water_level_now", "water_level", 2.9, "m", source="gauge",
                observed_at=origin,
            ),
        ),
    )
    with pytest.raises(MissingRiskContextError) as excinfo:
        assess_with_rule(served, context, residuals, sigma, required=True)
    assert "requires signal 'rainfall_3h'" in str(excinfo.value)


def test_a_required_rule_refuses_when_its_signal_is_stale(
    served, station_a, origin, residuals, sigma
):
    """A stale reading cannot quietly lower a band the policy intended to raise."""
    context = RiskContext(
        entity=station_a,
        signals=(
            available_signal(
                "rainfall_3h", "rainfall", 63.2, "mm", source="gauge",
                observed_at=origin - dt.timedelta(days=9),
            ),
        ),
    )
    with pytest.raises(StaleContextRuleError) as excinfo:
        assess_with_rule(
            served,
            context,
            residuals,
            sigma,
            required=True,
            config_kwargs={"default_max_age_seconds": 3600.0},
        )
    assert "beyond the configured 3600s limit" in str(excinfo.value)


def test_a_stale_signal_does_not_fire_an_optional_rule(
    served, station_a, origin, residuals, sigma
):
    """Without `required`, an old reading is reported stale and simply not used."""
    context = RiskContext(
        entity=station_a,
        signals=(
            available_signal(
                "rainfall_3h", "rainfall", 63.2, "mm", source="gauge",
                observed_at=origin - dt.timedelta(days=9),
            ),
        ),
    )
    result = assess_with_rule(
        served,
        context,
        residuals,
        sigma,
        config_kwargs={"default_max_age_seconds": 3600.0},
    )
    assert result.fired_rules == ()
    assert result.signals[0].availability == SIGNAL_STALE
    assert result.signals[0].usable is False
    assert result.signals[0].value is None
    assert "stale" in result.escalations[0].reason


def test_an_optional_rule_tolerates_its_signal_being_absent(
    served, station_a, origin, residuals, sigma
):
    context = RiskContext(
        entity=station_a,
        signals=(
            available_signal(
                "water_level_now", "water_level", 2.9, "m", source="gauge",
                observed_at=origin,
            ),
        ),
    )
    result = assess_with_rule(served, context, residuals, sigma, required=False)
    assert result.fired_rules == ()
    assert "not declared by the risk context" in result.escalations[0].reason
    assert result.evaluation_state == CONTEXT_FULLY_EVALUATED


def test_a_rule_never_overrides_the_computed_band_without_saying_so(
    served, station_a, origin, residuals, sigma
):
    """Fired-but-not-applied is reported, so no rule's firing goes unnoticed."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "CRITICAL")
    config = risk_config(threshold, rules=(rainfall_rule(escalate_to="LOW", mm=1.0),))
    result = assess_risk(
        served, config=config, context=full_context(station_a, origin), residuals=residuals
    )
    assert result.risk_level == "CRITICAL"
    assert result.fired_rules[0].fired is True
    assert "already at or above LOW" in result.explain()


def test_a_rule_converts_a_convertible_unit_explicitly(
    served, station_a, origin, residuals, sigma
):
    """`63.2 mm` against a rule in metres, converted and the conversion recorded."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "LOW")
    config = risk_config(
        threshold, rules=(rainfall_rule(mm=0.05, unit="m", escalate_to="HIGH"),)
    )
    result = assess_risk(
        served, config=config, context=full_context(station_a, origin), residuals=residuals
    )
    fired = result.fired_rules[0]
    assert fired.fired is True
    assert fired.converted_from == "mm"
    assert fired.observed_value == pytest.approx(0.0632)
    assert "converted from mm" in fired.reason


def test_a_rule_refuses_a_dimension_mismatch_it_cannot_convert(
    served, station_a, origin, residuals, sigma
):
    """A millimetre accumulation and a `mm/h` intensity have no factor between them."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "LOW")
    config = risk_config(
        threshold, rules=(rainfall_rule(mm=1.0, unit="mm/h"),)
    )
    context = RiskContext(
        entity=station_a,
        signals=(
            available_signal(
                "rainfall_3h", "rainfall", 63.2, "mm", source="gauge",
                observed_at=origin,
            ),
        ),
    )
    result = assess_risk(served, config=config, context=context, residuals=residuals)
    assert result.fired_rules == ()
    assert "not convertible" in result.escalations[0].reason


def test_a_rule_that_mislabels_its_signal_does_not_fire(
    served, station_a, origin, residuals, sigma
):
    """Comparing a rainfall signal as if it were a discharge reading is a configuration bug."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "LOW")
    rule = RiskEscalationRule(
        rule_id="wrong-quantity",
        signal="rainfall_3h",
        quantity="discharge",
        comparison=">=",
        value=1.0,
        unit="m3/s",
        escalate_to="HIGH",
        source="DEMO",
    )
    result = assess_risk(
        served, config=risk_config(threshold, rules=(rule,)),
        context=full_context(station_a, origin), residuals=residuals,
    )
    assert result.fired_rules == ()
    assert "is a rainfall, not the discharge" in result.escalations[0].reason


def test_duplicate_rule_ids_are_refused():
    """A rule that cannot be named in an explanation cannot be audited."""
    rule = rainfall_rule()
    with pytest.raises(InvalidRiskConfigurationError) as excinfo:
        RiskConfiguration(policy=demo_policy(3.5), rules=(rule, rule))
    assert "appear more than once" in str(excinfo.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("rule_id", ""),
        ("comparison", "~="),
        ("escalate_to", "MODERATE"),
        ("quantity", "soil_moisture"),
        ("value", float("nan")),
    ],
)
def test_an_invalid_rule_is_refused_at_configuration_time(field, value):
    settings = {
        "rule_id": "r",
        "signal": "rainfall_3h",
        "quantity": "rainfall",
        "comparison": ">=",
        "value": 50.0,
        "unit": "mm",
        "escalate_to": "HIGH",
        "source": "DEMO",
    }
    settings[field] = value
    with pytest.raises(InvalidRiskConfigurationError):
        RiskEscalationRule(**settings)


def test_a_rule_may_only_escalate_to_a_band_the_policy_produces():
    """A band the policy cannot classify into cannot be escalated into."""
    policy = RiskPolicy(
        flood_threshold=3.5,
        threshold_source="DEMO",
        policy_status="pending",
        band_edges=(0.5,),
        band_labels=("LOW", "HIGH"),
    )
    with pytest.raises(InvalidRiskConfigurationError) as excinfo:
        RiskConfiguration(policy=policy, rules=(rainfall_rule(escalate_to="CRITICAL"),))
    assert "not among the policy's band labels" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# The explanation
# --------------------------------------------------------------------------- #


def test_the_explanation_names_only_signals_that_were_actually_read(
    served, station_a, origin, sigma, residuals
):
    """The load-bearing honesty property: no invented contributors."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=partial_context(station_a, origin),
        residuals=residuals,
    )
    text = result.explain()

    assert "signal 'rainfall_3h' read 12.0 mm" in text
    assert "signal 'water_level_now' (water_level) not evaluated: missing" in text
    assert "signal 'discharge' (discharge) not evaluated: unavailable" in text
    # The absent ones are named as absent, never as contributing.
    assert "water_level_now" in text
    assert "not evaluated" in text


def test_the_explanation_reports_availability_counts(served, station_a, origin, sigma, residuals):
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=partial_context(station_a, origin),
        residuals=residuals,
    )
    assert "partially_evaluated" in result.explain()
    assert "missing=1" in result.explain()
    assert "unavailable=1" in result.explain()


def test_the_explanation_states_the_forecast_it_used(served, context, sigma, residuals):
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(served, config=risk_config(threshold), context=context, residuals=residuals)
    text = result.explain()

    assert f"forecast {served.inference.prediction!r}" in text
    assert served.inference.entity in text
    assert served.inference.model_family in text
    assert served.inference.artifact_id in text
    assert served.inference.horizon in text


def test_an_absent_level_is_explained_as_an_absence_not_a_low_rating(
    served, context
):
    """The most dangerous sentence this module could emit is "risk: low"."""
    result = assess_risk(served, config=risk_config(3.5), context=context)
    text = result.explain()
    assert result.risk_level is None
    assert "no risk band could be assigned" in text
    assert "not a LOW rating" in text
    assert "no measured residual spread was supplied" in text


def test_the_explanation_says_why_rmse_cannot_replace_the_spread(served, context):
    """The refusal explains itself, so an operator knows what to supply next."""
    result = assess_risk(served, config=risk_config(3.5), context=context)
    text = result.explain()
    assert "aggregate metrics (mae, rmse, r2, bias) but not the residuals" in text
    assert "about their mean" in text
    assert "Supply residuals" in text


def test_the_explanation_reports_a_convertible_threshold_unit(
    served, context, sigma, residuals
):
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    config = risk_config(threshold * 1000.0, threshold_units="mm")
    result = assess_risk(served, config=config, context=context, residuals=residuals)
    assert "threshold" in result.explain()
    assert " mm " in result.explain()


# --------------------------------------------------------------------------- #
# The GIS boundary
# --------------------------------------------------------------------------- #


def test_gis_context_is_unavailable_by_default_and_says_why():
    """The default carries the repository's own reason string, not a paraphrase."""
    gis = unavailable_gis_context()
    assert gis.available is False
    assert gis.elevation_m is None
    assert gis.river_distance_m is None
    assert gis.population_exposed is None
    assert gis.infrastructure_exposed is None
    assert gis.reason == (
        "NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED"
    )


def test_the_gis_unavailable_reason_is_the_repositorys_own_string():
    from app.engines.hydro.domains import NOT_AVAILABLE

    assert unavailable_gis_context().reason == NOT_AVAILABLE


def test_an_unavailable_gis_context_must_carry_a_reason():
    with pytest.raises(UnsupportedContextError) as excinfo:
        GisContext(available=False, provider="x", reason="  ")
    assert "we did not look" in str(excinfo.value)


def test_an_available_gis_context_must_carry_a_measurement():
    """`available=True` with nothing measured is an absence with the wrong label."""
    with pytest.raises(UnsupportedContextError) as excinfo:
        GisContext(available=True, provider="x")
    assert "wrong label" in str(excinfo.value)


def test_a_fractional_population_is_not_a_count():
    with pytest.raises(UnsupportedContextError) as excinfo:
        GisContext(available=True, provider="x", population_exposed=1.5)
    assert "fractional" in str(excinfo.value)


def test_spatial_evidence_is_attributed_to_its_provider(
    served, station_a, origin, sigma, residuals
):
    """When a provider answers, the values are attributed to it and reported."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=spatial_context(station_a, origin),
        residuals=residuals,
    )
    gis = result.gis_context

    assert gis["available"] is True
    assert gis["provider"] == "fixture-gis-adapter"
    assert gis["elevation_m"] == 12.5
    assert gis["river_distance_m"] == 140.0
    assert result.provenance_chain["gis_context_provenance"] == "fixture-gis://context/0001"
    assert result.provenance_chain["gis_context_available"] is True
    # An available GIS context has nothing to apologise for.
    assert "spatial exposure context unavailable" not in result.explain()


def test_no_spatial_evidence_is_ever_invented(served, station_a, origin, sigma, residuals):
    """A plausible-looking elevation would survive every downstream check."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=full_context(station_a, origin),
        residuals=residuals,
    )
    gis = result.gis_context
    assert gis["available"] is False
    for field in ("elevation_m", "river_distance_m", "population_exposed", "infrastructure_exposed"):
        assert gis[field] is None
    assert result.provenance_chain["gis_context_available"] is False
    assert "spatial exposure context unavailable" in result.explain()


def test_no_spatial_quantity_is_a_signal_in_the_evaluation(
    served, station_a, origin, sigma, residuals
):
    """Elevation and river distance are not comparable against a threshold, so they
    are reported as GIS context and not as signals a rule could fire on."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=spatial_context(station_a, origin),
        residuals=residuals,
    )
    quantities = {signal.quantity for signal in result.signals}
    assert "elevation" not in quantities
    assert "river_distance" not in quantities


# --------------------------------------------------------------------------- #
# The historical boundary
# --------------------------------------------------------------------------- #


def test_historical_context_is_unavailable_by_default():
    historical = unavailable_historical_context()
    assert historical.available is False
    assert historical.events == ()
    assert "none may be invented" in historical.reason


def test_historical_events_reuse_the_phase1_schema():
    """`domains.FloodEvent` is reused rather than a parallel event schema."""
    event = FloodEvent(
        event_reference="fixture-event-0001",
        area_reference=STATION_A,
        started_at="2023-08-02T00:00:00+00:00",
        ended_at="2023-08-05T00:00:00+00:00",
        severity="unknown",
        dataset_type="synthetic",
    )
    historical = HistoricalContext(available=True, provider="fixture-register", events=(event,))
    assert historical.events[0] is event
    assert historical.to_dict()["event_count"] == 1


def test_a_non_flood_event_record_is_refused():
    """A dict that happens to have an `event_reference` is not a flood event."""
    with pytest.raises(UnsupportedContextError) as excinfo:
        HistoricalContext(
            available=True,
            provider="x",
            events=({"event_reference": "not-a-flood-event"},),
        )
    assert "reuses domains.FloodEvent" in str(excinfo.value)


def test_an_available_historical_context_must_carry_an_event():
    with pytest.raises(UnsupportedContextError) as excinfo:
        HistoricalContext(available=True, provider="x")
    assert "wrong label" in str(excinfo.value)


def test_a_historical_event_for_another_station_is_refused(station_a, station_b, origin):
    """Cross-station historical evidence is exactly the mixing that must not happen."""
    event = FloodEvent(
        event_reference="fixture-event-0002",
        area_reference=station_b,
        started_at="2023-08-02T00:00:00+00:00",
    )
    context = RiskContext(entity=station_a, historical=HistoricalContext(
        available=True, provider="fixture-register", events=(event,)
    ))
    with pytest.raises(EntityMismatchError) as excinfo:
        evaluate_context(context, forecast_entity=station_a, forecast_origin=origin)
    assert station_b in str(excinfo.value)


def test_a_historical_event_from_the_future_is_refused(station_a, origin):
    """You cannot have known about a flood that has not happened yet."""
    event = FloodEvent(
        event_reference="fixture-event-0003",
        area_reference=station_a,
        started_at="2030-01-01T00:00:00+00:00",
    )
    context = RiskContext(entity=station_a, historical=HistoricalContext(
        available=True, provider="fixture-register", events=(event,)
    ))
    with pytest.raises(FutureContextError) as excinfo:
        evaluate_context(context, forecast_entity=station_a, forecast_origin=origin)
    assert "begins at" in str(excinfo.value)


def test_an_unreadable_event_timestamp_is_refused_by_the_phase1_schema(station_a):
    """Phase 1 already refuses an unparseable instant, so no such event can reach us.

    The check belongs to `domains.FloodEvent`, which is why Phase 6 reuses it rather
    than writing a second date parser. Asserted here because re-using a schema is only
    worth anything if the schema actually holds.
    """
    with pytest.raises(SchemaError) as excinfo:
        FloodEvent(
            event_reference="fixture-event-0004",
            area_reference=station_a,
            started_at="last tuesday",
        )
    assert "not a parseable ISO-8601 instant" in str(excinfo.value)


def test_an_event_that_ends_before_it_starts_is_refused_by_the_phase1_schema(
    station_a,
):
    with pytest.raises(SchemaError) as excinfo:
        FloodEvent(
            event_reference="fixture-event-0005",
            area_reference=station_a,
            started_at="2023-08-05T00:00:00+00:00",
            ended_at="2023-08-02T00:00:00+00:00",
        )
    assert "precedes started_at" in str(excinfo.value)


def test_a_naive_event_timestamp_is_refused_by_the_phase1_schema(station_a):
    """A naive date is an unreadable one; no offset is assumed."""
    with pytest.raises(SchemaError):
        FloodEvent(
            event_reference="fixture-event-0007",
            area_reference=station_a,
            started_at="2023-08-02T00:00:00",
        )


def test_a_past_event_for_this_station_is_accepted(station_a, origin):
    event = FloodEvent(
        event_reference="fixture-event-0006",
        area_reference=station_a,
        started_at="2023-08-02T00:00:00+00:00",
        ended_at="2023-08-05T00:00:00+00:00",
    )
    context = RiskContext(entity=station_a, historical=HistoricalContext(
        available=True, provider="fixture-register", events=(event,)
    ))
    assert evaluate_context(context, forecast_entity=station_a, forecast_origin=origin) == ()


# --------------------------------------------------------------------------- #
# Cross-contract refusals
# --------------------------------------------------------------------------- #


def test_a_context_for_another_station_is_refused(station_b, origin, context):
    with pytest.raises(EntityMismatchError) as excinfo:
        evaluate_context(context, forecast_entity=station_b, forecast_origin=origin)
    assert "transfer one station's evidence" in str(excinfo.value)


def test_a_signal_naming_another_station_is_refused_at_construction(origin, station_b):
    signal = available_signal(
        "level", "water_level", 2.9, "m", source="s", observed_at=origin, entity=station_b
    )
    with pytest.raises(EntityMismatchError) as excinfo:
        RiskContext(entity="SOMEWHERE", signals=(signal,))
    assert "one station's reading to another" in str(excinfo.value)


def test_a_naive_origin_is_refused(context, station_a):
    with pytest.raises(FutureContextError):
        evaluate_context(
            context,
            forecast_entity=station_a,
            forecast_origin=dt.datetime(2024, 1, 1),
        )


def test_an_assessment_earlier_than_the_origin_is_refused(context, station_a, origin):
    with pytest.raises(FutureContextError) as excinfo:
        evaluate_context(
            context,
            forecast_entity=station_a,
            forecast_origin=origin,
            assessed_at=origin - dt.timedelta(seconds=1),
        )
    assert "cannot be dated before" in str(excinfo.value)


def test_a_non_context_object_is_refused():
    with pytest.raises(MissingRiskContextError):
        evaluate_context({"signals": []}, forecast_entity="X",
                         forecast_origin=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc))


def test_a_context_of_the_wrong_element_type_is_refused(context, station_a, origin):
    with pytest.raises(UnsupportedContextError):
        RiskContext(entity=station_a, signals=("not-a-signal",))


# --------------------------------------------------------------------------- #
# Determinism of the context layer
# --------------------------------------------------------------------------- #


def test_the_context_digest_depends_on_the_values(served, station_a, origin, sigma, residuals):
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    dry = full_context(station_a, origin, rainfall_mm=1.0)
    wet = full_context(station_a, origin, rainfall_mm=90.0)
    first = assess_risk(served, config=risk_config(threshold), context=dry, residuals=residuals)
    second = assess_risk(served, config=risk_config(threshold), context=wet, residuals=residuals)
    assert context_digest(first.signals) != context_digest(second.signals)


def test_the_context_digest_ignores_construction_order(
    served, station_a, origin, sigma, residuals
):
    """The same evidence assembled differently is the same evidence."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    forward = full_context(station_a, origin)
    backward = dataclasses.replace(forward, signals=tuple(reversed(forward.signals)))
    assert backward.signals == forward.signals  # the context itself sorts

    first = assess_risk(served, config=risk_config(threshold), context=forward, residuals=residuals)
    second = assess_risk(served, config=risk_config(threshold), context=backward, residuals=residuals)
    assert context_digest(first.signals) == context_digest(second.signals)
    assert first.to_dict() == second.to_dict()
    assert first.risk_result_id == second.risk_result_id


# --------------------------------------------------------------------------- #
# The contract
# --------------------------------------------------------------------------- #


def test_the_context_contract_publishes_its_vocabularies():
    description = context_contract_description()
    assert description["context_version"] == CONTEXT_CONTRACT_VERSION
    assert description["signal_availability"] == SIGNAL_AVAILABILITY
    assert description["evaluation_states"] == CONTEXT_EVALUATION_STATES
    assert description["missing_is_not_zero"].startswith("an unusable signal carries no value")
    assert "interface only" in description["gis_context"]
    assert "interface only" in description["historical_context"]


def test_the_contract_lists_every_error_it_can_raise():
    for name in context_contract_description()["errors"]:
        assert hasattr(risk_context, name), name
        assert issubclass(getattr(risk_context, name), risk_context.RiskBoundaryError)


def test_every_declared_error_has_a_stable_reason_tag():
    reasons = {
        name: getattr(getattr(risk_context, name), "reason")
        for name in context_contract_description()["errors"]
    }
    assert len(set(reasons.values())) == len(reasons), reasons
    assert all(reason and " " not in reason for reason in reasons.values()), reasons


def test_the_bands_used_by_the_contract_are_the_platforms():
    """Phase 6 adds no risk vocabulary of its own."""
    assert BAND_LABELS == ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert BAND_EDGES == (0.1, 0.3, 0.6, 0.9)