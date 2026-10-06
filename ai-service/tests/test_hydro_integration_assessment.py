# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 8: the integration contract — statuses, chain, provenance, serialization.

Every fixture here is a real Phase 5 `serve`, a real Phase 6 `assess_risk` and a real
Phase 7 `decide_response`, carried through `hydro_phase8_fixtures`. Nothing is
hand-assembled, so a test that passes is a statement about the chain the repository
actually produces.

What is asserted here, and what is asserted in the sibling safety module
-------------------------------------------------------------------

This module asserts *what the contract says*: the four statuses, the order they are
derived in, the three-slot chain, the provenance mapping, the projections and the
serialized form.

`test_hydro_integration_safety.py` asserts *what the contract must never do*: no
recomputation, no clock, no randomness, no composite, no emergency states, no
service, no quantum, no GIS, and no mutation of the three objects it reads.

The split matters because a test that mixes the two tends to end up asserting a
prose claim. A status test should check a status.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import inspect
import json

import pytest

from app.engines.hydro.domains import NOT_AVAILABLE
from app.engines.hydro.forecast_risk import MissingForecastError
from app.engines.hydro.integration_assessment import (
    INTEGRATION_COMPLETE,
    INTEGRATION_CONTRACT_VERSION,
    INTEGRATION_NOT_EVALUABLE,
    INTEGRATION_PARTIAL,
    INTEGRATION_STATES,
    INTEGRATION_WITHHELD,
    LAYER_ORDER,
    ChainMismatchError,
    IntegratedForecastAssessment,
    IntegrationBoundaryError,
    InvalidForecastResultError,
    InvalidIntegrationStatusError,
    InvalidResponseDecisionError,
    InvalidRiskResultError,
    LayerLink,
    LayerSequenceError,
    default_integration_id,
    integrate,
    integrate_safe,
    integration_contract_description,
    integration_from_error,
)
from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER
from app.engines.hydro.response_context import (
    RESPONSE_AVAILABILITY,
    InvalidResponseContextError,
    unavailable_exposure,
)
from app.engines.hydro.response_decision import (
    DECISION_HEIGHTENED_MONITORING,
    DECISION_REVIEW_WARNING,
    DECISION_WITHHELD,
    ResponsePolicy,
    UnsupportedResponseStateError,
)
from app.engines.hydro.risk_context import (
    CONTEXT_EVALUATION_STATES,
    CONTEXT_NOT_EVALUABLE,
    CONTEXT_PARTIALLY_EVALUATED,
    CONTEXT_UNAVAILABLE,
    SIGNAL_AVAILABILITY,
    EntityMismatchError,
    FutureContextError,
)

from hydro_phase8_fixtures import (  # noqa: F401  - fixtures must be parameters
    STATION_A,
    available_population,
    complete_decision,
    complete_exposure,
    context_unavailable_chain,
    decide_for,
    decision_for_entity,
    decision_for_forecast_id,
    decision_for_origin,
    empty_chain,
    empty_context,
    error_risk_result,
    medium_chain,
    mixed_exposure,
    mixed_exposure_chain,
    missing_infrastructure,
    not_evaluable_chain,
    not_evaluable_risk_result,
    partial_context,
    partial_context_chain,
    refused_chain,
    risk_config,
    risk_for_forecast_id,
    risk_result_for_band,
    repository_chain,
    serve_for,
    shared_residuals,
    shared_run,
    shared_served,
    stale_infrastructure,
    station_two,
    unavailable_population,
    withheld_chain,
)


# --------------------------------------------------------------------------- #
# The vocabulary
# --------------------------------------------------------------------------- #


def test_the_four_states_are_exactly_complete_partial_withheld_not_evaluable():
    assert INTEGRATION_STATES == ("COMPLETE", "PARTIAL", "WITHHELD", "NOT_EVALUABLE")


def test_an_unrecognised_integration_status_is_refused_rather_than_reported(repository_chain):
    """A hand-built object must not be able to claim a status Phase 8 cannot derive.

    Reachable only by construction, since `integrate` always derives the status. It is
    still worth failing loudly: an unrecognised status in a serialized artifact is the
    kind of thing a consumer would treat as truth rather than as a defect.
    """
    with pytest.raises(InvalidIntegrationStatusError) as excinfo:
        dataclasses.replace(repository_chain, integration_status="ALL_GOOD")
    assert excinfo.value.reason == "invalid_integration_status"
    assert "ALL_GOOD" in str(excinfo.value)


def test_every_status_phase_8_declares_is_one_it_can_derive(medium_chain, repository_chain,
                                                            withheld_chain, empty_chain):
    """The published vocabulary and the derived vocabulary are the same set."""
    derived = {
        medium_chain.integration_status,
        repository_chain.integration_status,
        withheld_chain.integration_status,
        empty_chain.integration_status,
    }
    assert derived == set(INTEGRATION_STATES)


def test_a_caller_cannot_supply_the_integration_status():
    """The status must be derived, or a caller could paper over an upstream bug."""
    parameters = inspect.signature(integrate).parameters
    assert "integration_status" not in parameters
    assert list(parameters) == ["forecast", "risk", "response", "integration_id"]


def test_the_status_is_a_derived_property_and_never_a_stored_choice():
    """The reason always names a condition; it is never a bare restatement."""
    chain = integrate(shared_served())
    assert chain.integration_status == INTEGRATION_NOT_EVALUABLE
    assert "no Phase 6 risk result" in chain.integration_reason


# --------------------------------------------------------------------------- #
# Case 1: COMPLETE
# --------------------------------------------------------------------------- #


def test_a_complete_chain_reports_complete(medium_chain):
    assert medium_chain.integration_status == INTEGRATION_COMPLETE
    assert medium_chain.is_complete
    assert not medium_chain.is_partial
    assert not medium_chain.is_withheld
    assert not medium_chain.is_not_evaluable


def test_complete_requires_every_declared_contextual_input_to_be_usable(medium_chain):
    assert medium_chain.unusable_context == ()
    assert medium_chain.risk_evaluation_state == "fully_evaluated"


def test_complete_still_says_nothing_about_correctness_or_authority(medium_chain):
    """`COMPLETE` means "assembled completely", not "right"."""
    assert "not a statement that any result is correct" in medium_chain.explain()
    assert medium_chain.operational_authority is False
    assert medium_chain.production_ready_claimed is False


def test_complete_carries_the_response_decision_unchanged(medium_chain):
    assert medium_chain.response_decision == DECISION_HEIGHTENED_MONITORING
    assert medium_chain.response_is_recommendation


def test_repository_data_alone_never_reaches_complete(repository_chain):
    """This repository has no exposure provider, so its own output tops out at PARTIAL."""
    assert repository_chain.integration_status == INTEGRATION_PARTIAL
    assert {record.kind for record in repository_chain.unusable_context} == {
        "population",
        "infrastructure",
    }


def test_complete_exposure_declares_availability_and_supplies_no_value():
    """The only route to COMPLETE is a caller declaring a provider exists."""
    records = complete_exposure()
    assert [record.kind for record in records] == ["population", "infrastructure"]
    assert all(record.usable for record in records)
    assert not any(hasattr(record, "value") for record in records)
    assert all("DEMO" in record.source for record in records)


# --------------------------------------------------------------------------- #
# Case 2: PARTIAL
# --------------------------------------------------------------------------- #


def test_a_repository_chain_is_partial_and_names_every_gap(repository_chain):
    assert repository_chain.integration_status == INTEGRATION_PARTIAL
    assert repository_chain.is_partial
    assert len(repository_chain.unusable_context) == 2
    for record in repository_chain.unusable_context:
        assert record.kind in record.availability or record.availability == "unavailable"
        assert record.reason


def test_partial_preserves_the_upstream_analytical_results_exactly(repository_chain):
    """`PARTIAL` must not cost the caller anything the layers below produced."""
    assert repository_chain.risk_level == "MEDIUM"
    assert repository_chain.risk_score is not None
    assert repository_chain.response_decision == DECISION_HEIGHTENED_MONITORING
    assert repository_chain.forecast_id is not None


def test_partial_context_alone_is_enough_to_be_partial(partial_context_chain):
    """Every exposure input usable, but Phase 6 read only part of its context."""
    assert partial_context_chain.unusable_context == ()
    assert partial_context_chain.risk_evaluation_state == CONTEXT_PARTIALLY_EVALUATED
    assert partial_context_chain.integration_status == INTEGRATION_PARTIAL


def test_one_unusable_exposure_input_is_enough_to_be_partial(mixed_exposure_chain):
    assert mixed_exposure_chain.integration_status == INTEGRATION_PARTIAL
    assert len(mixed_exposure_chain.unusable_context) == 1


# --------------------------------------------------------------------------- #
# Case 3: WITHHELD
# --------------------------------------------------------------------------- #


def test_a_withheld_response_decision_is_preserved_as_withheld(withheld_chain):
    assert withheld_chain.integration_status == INTEGRATION_WITHHELD
    assert withheld_chain.response_decision == DECISION_WITHHELD
    assert withheld_chain.is_withheld


def test_withheld_never_becomes_monitor_because_an_object_had_to_be_returned(withheld_chain):
    """Case 7 of the contract: a withheld decision stays withheld, whatever the status."""
    assert withheld_chain.response_decision != "MONITOR"
    assert withheld_chain.response.decision == DECISION_WITHHELD
    assert withheld_chain.response.rationale in withheld_chain.integration_reason


def test_an_absent_response_decision_is_withheld_not_not_evaluable():
    """The forecast and risk results stand; only the interpretation is withheld."""
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    assessment = integrate(served_forecast, risk)
    assert assessment.integration_status == INTEGRATION_WITHHELD
    assert assessment.response is None
    assert assessment.chain[2].status is None
    assert assessment.risk_level == "MEDIUM"


def test_an_unreadable_context_is_withheld_even_with_a_recommendation_in_hand(
    context_unavailable_chain,
):
    """Case 11: the integration refuses to look complete over an uncorroborated level."""
    assert context_unavailable_chain.integration_status == INTEGRATION_WITHHELD
    assert context_unavailable_chain.risk_evaluation_state == CONTEXT_UNAVAILABLE
    assert context_unavailable_chain.risk_level is not None


def test_a_context_unavailable_status_cannot_be_overridden_by_a_recommendation(
    context_unavailable_chain,
):
    """Declaring every exposure provider available does not conjure readable context.

    The exposure records are all usable in this chain, so a naive implementation would
    look past `evaluation_state` and call this `COMPLETE`. It is `WITHHELD` instead:
    the signal-level context Phase 6 could not read is a different gap from the
    exposure availability Phase 7 recorded, and both have to be present for `COMPLETE`.
    """
    assert context_unavailable_chain.unusable_context == ()
    assert context_unavailable_chain.risk_evaluation_state == CONTEXT_UNAVAILABLE
    assert context_unavailable_chain.integration_status == INTEGRATION_WITHHELD
    assert "could read no context at all" in context_unavailable_chain.integration_reason


# --------------------------------------------------------------------------- #
# Case 4: NOT_EVALUABLE
# --------------------------------------------------------------------------- #


def test_an_absent_forecast_is_not_evaluable(empty_chain):
    assert empty_chain.integration_status == INTEGRATION_NOT_EVALUABLE
    assert empty_chain.forecast is None
    assert empty_chain.entity is None
    assert empty_chain.integrated_at is None


def test_an_absent_risk_result_is_not_evaluable():
    """Case 6: risk unavailable is preserved, never resolved into a low risk."""
    assessment = integrate(shared_served())
    assert assessment.integration_status == INTEGRATION_NOT_EVALUABLE
    assert assessment.risk is None
    assert assessment.risk_status is None
    assert assessment.risk_level is None


def test_a_refused_forecast_is_not_evaluable_and_reports_the_refusal(refused_chain):
    """Case 5 and case 9: Phase 5 refused, and the refusal is reported as such."""
    assert refused_chain.integration_status == INTEGRATION_NOT_EVALUABLE
    assert refused_chain.forecast_status == "artifact_unavailable"
    assert refused_chain.forecast.inference is None
    assert refused_chain.chain[0].present
    assert refused_chain.chain[0].status == "artifact_unavailable"
    assert "refused to serve a forecast" in refused_chain.explain()


def test_a_risk_result_with_no_level_is_not_evaluable(not_evaluable_chain):
    """Case 8's sibling: the risk contract itself produced nothing to integrate."""
    assert not_evaluable_chain.integration_status == INTEGRATION_NOT_EVALUABLE
    assert not_evaluable_chain.risk_level is None
    assert not_evaluable_chain.risk_status == "withheld"
    assert not_evaluable_chain.risk_evaluation_state == CONTEXT_NOT_EVALUABLE


def test_not_evaluable_never_claims_a_zero_risk(empty_chain):
    assert empty_chain.risk_score is None
    assert empty_chain.prediction is None
    assert "not a zero forecast and not a low risk" in empty_chain.explain()


# --------------------------------------------------------------------------- #
# Case 9 / 10: context states are preserved verbatim
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "unusable_record, expected_state",
    [
        (
            lambda: unavailable_exposure(
                "infrastructure",
                "unavailable",
                reason="no infrastructure provider exists in this repository",
                source="demo-adapter",
            ),
            "unavailable",
        ),
        (stale_infrastructure, "stale"),
        (missing_infrastructure, "missing"),
        (
            lambda: unavailable_exposure(
                "infrastructure",
                "not_applicable",
                reason="this catchment has no infrastructure to expose",
                source="demo-adapter",
            ),
            "not_applicable",
        ),
    ],
)
def test_each_unusable_context_state_is_preserved_distinctly(unusable_record, expected_state):
    """Cases 10/11/12: `missing`, `unavailable` and `stale` stay three separate things.

    The assertion is that the *state* survives into the integrated record unchanged.
    Collapsing them into one "not available" bucket would lose the difference between
    "we looked and there was none", "we did not look" and "we looked and what we found
    was too old to use" — and the first of those is not evidence of safety.
    """
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    exposure = (available_population(), unusable_record())
    assessment = integrate(served_forecast, risk, decide_for(risk, exposure=exposure))

    assert assessment.integration_status == INTEGRATION_PARTIAL
    unusable = {record.kind: record for record in assessment.unusable_context}
    assert set(unusable) == {"infrastructure"}
    assert unusable["infrastructure"].availability == expected_state
    assert unusable["infrastructure"].usable is False
    assert unusable["infrastructure"].reason
    # The state is a Phase 6/7 vocabulary word, never one Phase 8 invented.
    assert expected_state in set(SIGNAL_AVAILABILITY)
    assert unusable["infrastructure"].availability in RESPONSE_AVAILABILITY


def test_the_three_unusable_states_are_not_collapsed_into_one_count(
    repository_chain, mixed_exposure_chain, partial_context_chain
):
    """A single "not available" tally would hide which kind of not-available each is.

    All three are `PARTIAL`, for two quite different reasons: an exposure input was
    declared but had no value, versus Phase 6 never finished evaluating its context.
    A reader must be able to tell them apart without re-running Phase 6, so the
    unusable records and the reasons stay distinct rather than collapsing into a tally.
    """
    assert (
        repository_chain.integration_status
        == mixed_exposure_chain.integration_status
        == partial_context_chain.integration_status
        == INTEGRATION_PARTIAL
    )
    # ...and yet they remain distinguishable, which is the point.
    assert len(repository_chain.unusable_context) == 2
    assert len(mixed_exposure_chain.unusable_context) == 1
    assert partial_context_chain.unusable_context == ()
    assert partial_context_chain.risk_evaluation_state == CONTEXT_PARTIALLY_EVALUATED
    assert repository_chain.integration_reason != partial_context_chain.integration_reason


def test_an_unusable_input_is_never_counted_as_zero_and_never_read_as_reassuring():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    assessment = integrate(served_forecast, risk, decide_for(risk, exposure=mixed_exposure()))
    assert assessment.integration_status == INTEGRATION_PARTIAL
    text = assessment.explain()
    assert "not counted as zero" in text
    assert "not read as reassuring" in text


def test_a_stale_context_input_is_named_with_its_reason():
    """A stale input is named as stale, and never quietly counted as usable.

    Worth its own test because freshness is the one state that carries information
    the other four do not: `unavailable` says nothing was found, `stale` says
    something was found and then went out of date. Folding the second into the first
    would hide a data-quality problem behind what looks like an absence.
    """
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    exposure = (available_population(), stale_infrastructure())
    assessment = integrate(served_forecast, risk, decide_for(risk, exposure=exposure))

    stale = [record for record in assessment.unusable_context if record.availability == "stale"]
    assert len(stale) == 1
    assert stale[0].kind == "infrastructure"
    assert stale[0].reason
    assert assessment.integration_status == INTEGRATION_PARTIAL
    assert "infrastructure stale" in assessment.explain()


# --------------------------------------------------------------------------- #
# Case 8: entity safety
# --------------------------------------------------------------------------- #


def test_layers_describing_different_entities_are_refused(station_two):
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    decision = decision_for_entity(station_two, risk)
    with pytest.raises(EntityMismatchError) as excinfo:
        integrate(served_forecast, risk, decision)
    assert STATION_A in str(excinfo.value)
    assert station_two in str(excinfo.value)


def test_an_entity_refusal_names_every_layer_it_compared(station_two):
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    with pytest.raises(EntityMismatchError) as excinfo:
        integrate(served_forecast, risk, decision_for_entity(station_two, risk))
    message = str(excinfo.value)
    assert "forecast=" in message
    assert "risk=" in message
    assert "response=" in message


def test_every_state_is_reachable_and_nothing_else_is_reported(
    medium_chain, repository_chain, withheld_chain, empty_chain
):
    seen = {
        medium_chain.integration_status,
        repository_chain.integration_status,
        withheld_chain.integration_status,
        empty_chain.integration_status,
    }
    assert seen == set(INTEGRATION_STATES)
    """One rule, one taxonomy: no Phase 8 twin of `EntityMismatchError`."""
    from app.engines.hydro.risk_context import EntityMismatchError as PhaseSixError

    assert EntityMismatchError is PhaseSixError
    assert EntityMismatchError.reason == "entity_mismatch"


def test_matching_entities_integrate_without_ceremony(medium_chain):
    assert medium_chain.entity == STATION_A
    assert medium_chain.response.entity == STATION_A
    assert medium_chain.forecast.inference.entity == STATION_A


# --------------------------------------------------------------------------- #
# Case 9: temporal safety
# --------------------------------------------------------------------------- #


def test_layers_naming_different_forecasts_are_refused():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    decision = decision_for_forecast_id("forecast-from-another-evening", risk)
    with pytest.raises(ChainMismatchError) as excinfo:
        integrate(served_forecast, risk, decision)
    assert excinfo.value.reason == "chain_mismatch"


def test_a_risk_result_naming_a_different_forecast_is_refused():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    with pytest.raises(ChainMismatchError):
        integrate(served_forecast, risk_for_forecast_id("other", risk), decide_for(risk))


def test_a_later_origin_is_reported_as_a_temporal_violation():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    later = served_forecast.inference.origin_instant + dt.timedelta(hours=6)
    with pytest.raises(FutureContextError) as excinfo:
        integrate(served_forecast, risk, decision_for_origin(later, risk))
    assert excinfo.value.reason == "future_context"


def test_an_earlier_origin_is_a_mismatch_rather_than_a_future_violation():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    earlier = served_forecast.inference.origin_instant - dt.timedelta(hours=6)
    with pytest.raises(ChainMismatchError):
        integrate(served_forecast, risk, decision_for_origin(earlier, risk))


def test_the_forecast_origin_is_carried_forward_unchanged(medium_chain):
    assert medium_chain.forecast_origin == medium_chain.forecast.inference.origin_instant
    assert medium_chain.integrated_at == medium_chain.forecast.inference.origin_instant


def test_the_forecast_horizon_is_carried_forward_unchanged(medium_chain):
    assert medium_chain.forecast_horizon == medium_chain.forecast.inference.horizon
    assert medium_chain.response.forecast_horizon == medium_chain.forecast_horizon


def test_a_refused_forecast_records_no_instant_at_all(refused_chain):
    assert refused_chain.integrated_at is None
    assert refused_chain.forecast_origin is None


def test_the_temporal_error_is_phase_six_and_sevens_own_class():
    from app.engines.hydro.risk_context import FutureContextError as PhaseSixError

    assert FutureContextError is PhaseSixError


# --------------------------------------------------------------------------- #
# Case 13: provenance chain
# --------------------------------------------------------------------------- #


def test_the_chain_has_three_slots_in_the_fixed_order(medium_chain):
    assert [link.layer for link in medium_chain.chain] == list(LAYER_ORDER)
    assert LAYER_ORDER == ("forecast", "risk", "response")


def test_every_chain_id_is_the_identifier_the_layer_itself_published(medium_chain):
    assert medium_chain.chain[0].layer_id == medium_chain.forecast.forecast_id
    assert medium_chain.chain[1].layer_id == medium_chain.risk.risk_result_id
    assert medium_chain.chain[2].layer_id == medium_chain.response.decision_id


def test_the_chain_is_intact_when_three_layers_are_present(medium_chain):
    assert medium_chain.chain_intact
    assert all(link.present for link in medium_chain.chain)
    assert [link.status for link in medium_chain.chain] == [
        "ready",
        "recorded",
        "recommended",
    ]


def test_an_absent_layer_is_an_empty_slot_and_never_a_shortened_chain():
    served_forecast = shared_served()
    assessment = integrate(served_forecast)
    assert len(assessment.chain) == 3
    assert [link.layer for link in assessment.chain] == list(LAYER_ORDER)
    assert assessment.chain[1].present is False
    assert assessment.chain[2].present is False
    assert assessment.chain_intact


def test_a_refused_forecast_layer_counts_as_present(refused_chain):
    """A refusal is a result, and it is the slot that carries the refusal.

    Keying presence on a status rather than on an id is what keeps "the layer ran and
    said no" distinguishable from "the layer never ran" — different operational
    situations that a reader must be able to tell apart.
    """
    link = refused_chain.chain[0]
    assert link.present
    assert link.status == "artifact_unavailable"
    assert link.contract_version
    assert refused_chain.chain[1].present is False
    assert refused_chain.chain[2].present is False
    assert refused_chain.chain_intact


def test_an_absent_layer_also_has_no_contract_version(refused_chain):
    """A layer that produced nothing cannot claim which generation it would have been."""
    assert refused_chain.chain[1].contract_version is None
    assert refused_chain.chain[2].contract_version is None


def test_a_fourth_layer_is_refused():
    """The chain is exactly three layers, and adding one is not Phase 8's business."""
    with pytest.raises(IntegrationBoundaryError) as excinfo:
        LayerLink(layer="optimization", layer_id="qpu-job-1", status="submitted")
    assert "is not one of" in str(excinfo.value)


def test_a_reordered_or_shortened_chain_is_refused(medium_chain):
    """Reconstructing the record with a two-slot or reordered chain must fail."""
    with pytest.raises(IntegrationBoundaryError) as excinfo:
        dataclasses.replace(medium_chain, chain=medium_chain.chain[:2])
    assert "3" in str(excinfo.value)

    reordered = (medium_chain.chain[1], medium_chain.chain[0], medium_chain.chain[2])
    with pytest.raises(IntegrationBoundaryError) as excinfo:
        dataclasses.replace(medium_chain, chain=reordered)
    assert "chain order is fixed" in str(excinfo.value)


def test_a_chain_slot_with_a_duplicated_layer_is_refused(medium_chain):
    duplicated = (
        medium_chain.chain[0],
        LayerLink(layer="forecast", layer_id="x", status="ready"),
        medium_chain.chain[2],
    )
    with pytest.raises(IntegrationBoundaryError):
        dataclasses.replace(medium_chain, chain=duplicated)


def test_a_chain_of_exactly_the_declared_shape_is_accepted(medium_chain):
    assert len(medium_chain.chain) == 3
    assert dataclasses.replace(medium_chain).chain == medium_chain.chain


def test_the_provenance_mapping_names_the_whole_chain(medium_chain):
    provenance = medium_chain.provenance
    assert provenance["forecast_id"] == medium_chain.forecast.forecast_id
    assert provenance["risk_result_id"] == medium_chain.risk.risk_result_id
    assert provenance["decision_id"] == medium_chain.response.decision_id
    assert provenance["entity"] == STATION_A
    assert provenance["integration_contract_version"] == INTEGRATION_CONTRACT_VERSION


def test_the_provenance_names_the_artifact_and_the_response_policy(medium_chain):
    provenance = medium_chain.provenance
    assert provenance["artifact_id"] == medium_chain.artifact_id
    assert provenance["model_id"] == medium_chain.model_id
    assert provenance["response_policy_version"]
    assert provenance["response_policy_status"] == "pending"


def test_the_provenance_records_every_contract_version(medium_chain):
    provenance = medium_chain.provenance
    assert provenance["serving_contract_version"]
    assert provenance["risk_contract_version"]
    assert provenance["response_contract_version"]
    assert provenance["response_context_version"]


def test_a_provenance_value_is_never_invented_where_the_layer_supplied_none(empty_chain):
    provenance = empty_chain.provenance
    assert provenance["forecast_id"] is None
    assert provenance["risk_result_id"] is None
    assert provenance["decision_id"] is None
    assert provenance["risk_dataset_type"] is None


def test_the_authority_flags_are_always_false(medium_chain, empty_chain):
    for assessment in (medium_chain, empty_chain):
        assert assessment.operational_authority is False
        assert assessment.production_ready_claimed is False
        assert assessment.provenance["operational_authority"] is False
        assert assessment.provenance["production_ready_claimed"] is False


def test_evidence_availability_is_phase_sixs_own_distribution(medium_chain):
    assert dict(medium_chain.evidence_availability) == dict(medium_chain.risk.availability_counts)
    assert set(medium_chain.evidence_availability) <= set(SIGNAL_AVAILABILITY)


def test_available_inputs_are_phase_sixs_own_usable_signals(medium_chain):
    assert list(medium_chain.available_inputs) == [
        signal.name for signal in medium_chain.risk.usable_signals
    ]


# --------------------------------------------------------------------------- #
# Case 14: deterministic identity
# --------------------------------------------------------------------------- #


def test_the_integration_id_is_deterministic(medium_chain):
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    decision = complete_decision(risk)
    first = integrate(served_forecast, risk, decision)
    second = integrate(served_forecast, risk, decision)
    assert first.integration_id == second.integration_id


def test_the_integration_id_names_the_entity_the_status_and_a_digest():
    assessment = integrate(None)
    assert assessment.integration_id.startswith("integration-no-entity-NOT_EVALUABLE@")
    digest = assessment.integration_id.rsplit("@", 1)[1]
    assert len(digest) == 12
    assert all(character in "0123456789abcdef" for character in digest)


def test_the_integration_id_changes_when_the_status_changes():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    complete = integrate(served_forecast, risk, complete_decision(risk))
    partial = integrate(served_forecast, risk, decide_for(risk))
    assert complete.integration_id != partial.integration_id


def test_the_integration_id_changes_when_the_risk_outcome_changes():
    """Phase 6's own id does not distinguish these two, so Phase 8 has to.

    `risk_result_id` is a digest over the assessment's *configuration* — the forecast,
    the threshold policy and the context digest — so a MEDIUM and a HIGH assessment of
    the same forecast under the same policy deliberately share it. The id answers
    "which question was asked", not "what was found". Two records describing
    different risk outcomes must still be distinguishable from each other.
    """
    served_forecast = shared_served()
    medium_risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    high_risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "HIGH")

    medium = integrate(served_forecast, medium_risk, complete_decision(medium_risk))
    high = integrate(served_forecast, high_risk, complete_decision(high_risk))

    assert medium.risk_level != high.risk_level
    # The risk layer's identifier is deliberately the same for both.
    assert medium.chain[1].layer_id == high.chain[1].layer_id
    # The integrated records are not.
    assert medium.integration_id != high.integration_id
    assert medium.to_json() != high.to_json()


def test_a_caller_may_supply_its_own_identifier():
    assessment = integrate(shared_served(), integration_id="integration-supplied")
    assert assessment.integration_id == "integration-supplied"


def test_the_default_id_helper_is_a_pure_function_of_its_inputs(medium_chain):
    rebuilt = default_integration_id(
        integration_status=medium_chain.integration_status,
        chain=medium_chain.chain,
        entity=medium_chain.entity,
        risk=medium_chain.risk,
        unusable_context=medium_chain.unusable_context,
    )
    assert rebuilt == medium_chain.integration_id


# --------------------------------------------------------------------------- #
# Case 15: deterministic serialization
# --------------------------------------------------------------------------- #


def test_the_serialized_form_is_valid_json(medium_chain):
    payload = json.loads(medium_chain.to_json())
    assert payload["integration_status"] == INTEGRATION_COMPLETE


def test_two_identical_integrations_serialize_identically():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    decision = complete_decision(risk)
    assert integrate(served_forecast, risk, decision).to_json() == integrate(
        served_forecast, risk, decision
    ).to_json()


def test_the_serialized_form_answers_every_question_the_contract_promises(medium_chain):
    payload = medium_chain.to_dict()
    for key in (
        "integration_status",
        "forecast_id",
        "forecast_status",
        "risk_status",
        "risk_level",
        "response_decision",
        "provenance",
        "chain",
        "evidence_availability",
        "unavailable_context",
        "disclaimer",
        "explanation",
    ):
        assert key in payload, key
    assert payload["forecast"]["model_id"] == medium_chain.model_id
    assert payload["forecast"]["artifact_id"] == medium_chain.artifact_id
    assert payload["risk"]["threshold_policy"] == medium_chain.risk.threshold_policy
    assert payload["response"]["response_policy"]["policy_status"] == "pending"


def test_the_serialized_form_summarizes_rather_than_duplicates_the_layers(medium_chain):
    """No nested dump of Phase 6's signals or Phase 7's evidence list."""
    payload = medium_chain.to_dict()
    assert "signals" not in payload["risk"]
    assert "evidence" not in payload["response"]
    assert "explanation" not in payload["risk"]
    assert medium_chain.risk.signals  # they are still reachable on the object


def test_the_serialized_form_survives_every_status(repository_chain, withheld_chain,
                                                   not_evaluable_chain, refused_chain):
    for assessment in (repository_chain, withheld_chain, not_evaluable_chain, refused_chain):
        payload = json.loads(assessment.to_json())
        assert payload["integration_status"] in INTEGRATION_STATES
        assert payload["disclaimer"]


def test_an_indented_serialization_round_trips_too(medium_chain):
    payload = json.loads(medium_chain.to_json(indent=2))
    assert payload["integration_id"] == medium_chain.integration_id


def test_the_explanation_is_one_paragraph_when_joined(medium_chain):
    assert medium_chain.explain() == " ".join(medium_chain.explanation)
    assert len(medium_chain.explanation) > 5


# --------------------------------------------------------------------------- #
# Case 16: the synthetic/demo disclaimer
# --------------------------------------------------------------------------- #


def test_the_disclaimer_is_present_on_every_path(
    medium_chain, repository_chain, withheld_chain, not_evaluable_chain, refused_chain, empty_chain
):
    for assessment in (
        medium_chain,
        repository_chain,
        withheld_chain,
        not_evaluable_chain,
        refused_chain,
        empty_chain,
    ):
        assert assessment.disclaimer
        assert "SYNTHETIC/DEMO DATA" in assessment.disclaimer


def test_the_disclaimer_is_the_exact_repository_sentence():
    assert SYNTHETIC_DATA_DISCLAIMER == (
        "THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL "
        "HYDROLOGICAL OBSERVATION DATA."
    )


def test_an_empty_layer_disclaimer_falls_back_to_the_canonical_sentence():
    """Phase 6's error path builds a `RiskResult` with `disclaimer=''`.

    The risk layer has no data to describe, so an empty string is the honest answer
    *there*. Forwarded unchanged it would make the integrated record read as though no
    synthetic-data warning were needed, so the fallback has to happen here.
    """
    served_forecast = shared_served()
    error_result = error_risk_result()
    assert error_result.disclaimer == ""

    assessment = integrate_safe(served_forecast, error_result)
    assert assessment.disclaimer == SYNTHETIC_DATA_DISCLAIMER
    assert "SYNTHETIC/DEMO DATA" in assessment.disclaimer


def test_the_fallback_applies_even_when_a_usable_layer_is_present():
    """A real forecast's disclaimer must not paper over the empty one below it.

    Both layers are consulted; the first *non-empty* one wins. The forecast here does
    carry a disclaimer, and it is the same canonical sentence, so the outcome is
    identical either way — which is the point: the result is correct regardless of
    which layer supplied it.
    """
    served_forecast = shared_served()
    assert served_forecast.inference.disclaimer
    assessment = integrate_safe(served_forecast, error_risk_result())
    assert assessment.disclaimer == SYNTHETIC_DATA_DISCLAIMER


def test_a_record_wrapping_an_error_risk_result_never_reports_complete():
    error_result = error_risk_result()
    assert error_result.risk_level is None
    assert error_result.status == "withheld"
    assert integrate_safe(shared_served(), error_result).integration_status == (
        INTEGRATION_NOT_EVALUABLE
    )


def test_the_disclaimer_is_first_non_empty_across_the_layers():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    decision = complete_decision(risk)
    assert integrate(served_forecast, risk, decision).disclaimer == decision.disclaimer


def test_a_record_with_an_empty_disclaimer_cannot_be_built(repository_chain):
    """The invariant is enforced at construction, not merely documented.

    `integrate` always supplies a disclaimer, so this is only reachable by building a
    record by hand — which is exactly the case worth failing loudly on, because it is
    how a warning gets dropped from a serialized artifact.
    """
    with pytest.raises(IntegrationBoundaryError) as excinfo:
        dataclasses.replace(repository_chain, disclaimer="")
    assert "derived from the layers" in str(excinfo.value)

    with pytest.raises(IntegrationBoundaryError):
        dataclasses.replace(repository_chain, disclaimer="   ")


def test_a_whitespace_disclaimer_is_still_refused_even_if_it_matched(repository_chain):
    """A blank string is not a disclaimer, and must not be accepted as one."""
    with pytest.raises(IntegrationBoundaryError):
        dataclasses.replace(repository_chain, disclaimer="\t\n ")


def test_the_disclaimer_reaches_the_explanation_and_the_serialized_form(medium_chain):
    assert SYNTHETIC_DATA_DISCLAIMER in medium_chain.explain()
    assert medium_chain.to_dict()["disclaimer"] == medium_chain.disclaimer


# --------------------------------------------------------------------------- #
# Case 17: no response downgrade
# --------------------------------------------------------------------------- #


def test_a_recommendation_is_never_rewritten_by_the_integration(medium_chain):
    assert medium_chain.response_decision == medium_chain.response.decision
    assert medium_chain.risk_level == medium_chain.response.risk_level
    assert medium_chain.risk_level == medium_chain.risk.risk_level


def test_the_highest_review_warning_survives_untouched():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "CRITICAL")
    assessment = integrate(served_forecast, risk, complete_decision(risk))
    assert assessment.response_decision == DECISION_REVIEW_WARNING
    assert assessment.integration_status == INTEGRATION_COMPLETE


def test_the_status_and_the_recommendation_are_independent_axes(
    medium_chain, withheld_chain, not_evaluable_chain
):
    """Neither axis leaks into the other, in either direction.

    `NOT_EVALUABLE` does not mean "be more careful, so downgrade the response", and
    `COMPLETE` does not mean "upgrade the response". If either ever did, a status
    field would be silently rewriting the thing an operator actually acts on.
    """
    assert medium_chain.integration_status == INTEGRATION_COMPLETE
    assert medium_chain.response_is_recommendation
    assert medium_chain.response.decision == DECISION_HEIGHTENED_MONITORING

    # WITHHELD status, WITHHELD decision - Phase 7's own word, not Phase 8's.
    assert withheld_chain.integration_status == INTEGRATION_WITHHELD
    assert withheld_chain.response.decision == DECISION_WITHHELD
    assert not withheld_chain.response_is_recommendation

    # A NOT_EVALUABLE status does not upgrade a withheld decision into a
    # recommendation. The refusal stays a refusal.
    assert not_evaluable_chain.integration_status == INTEGRATION_NOT_EVALUABLE
    assert not_evaluable_chain.response.decision == DECISION_WITHHELD
    assert not not_evaluable_chain.response_is_recommendation

    # And the risk level is never rewritten to justify the status either way.
    for chain in (medium_chain, withheld_chain, not_evaluable_chain):
        assert chain.risk_level == chain.risk.risk_level
        assert chain.risk_score == chain.risk.risk_score


def test_phase_8_does_not_produce_a_response_when_there_is_none():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    assessment = integrate(served_forecast, risk)
    assert assessment.response is None
    assert assessment.response_decision is None
    assert assessment.chain[2].layer_id is None


# --------------------------------------------------------------------------- #
# Projections equal their sources
# --------------------------------------------------------------------------- #


def test_every_projection_equals_the_object_it_was_taken_from(medium_chain):
    forecast = medium_chain.forecast
    risk = medium_chain.risk
    response = medium_chain.response
    assert medium_chain.forecast_id == forecast.forecast_id
    assert medium_chain.forecast_status == forecast.status
    assert medium_chain.forecast_status == "ready"
    assert medium_chain.forecast_horizon == forecast.inference.horizon
    assert medium_chain.prediction == forecast.inference.prediction
    assert medium_chain.prediction_units == forecast.inference.target_units
    assert medium_chain.model_id == forecast.inference.model_id
    assert medium_chain.model_version == forecast.inference.model_version
    assert medium_chain.artifact_id == forecast.artifact_id
    assert medium_chain.risk_result_id == risk.risk_result_id
    assert medium_chain.risk_status == risk.status
    assert medium_chain.risk_evaluation_state == risk.evaluation_state
    assert medium_chain.risk_level == risk.risk_level
    assert medium_chain.risk_score == risk.risk_score
    assert medium_chain.risk_score_type == risk.risk_score_type
    assert medium_chain.response_decision == response.decision
    assert medium_chain.response_status == response.status
    assert medium_chain.response_decision_id == response.decision_id
    assert medium_chain.entity == forecast.inference.entity


def test_a_projection_that_disagrees_with_its_source_cannot_be_built(medium_chain):
    """The invariant is enforced at construction, not merely documented.

    If a projection could disagree with the object it was taken from, this record
    would be able to report one thing while holding another - and the whole reason
    for projecting rather than nesting is to prevent that.
    """
    with pytest.raises(IntegrationBoundaryError):
        dataclasses.replace(medium_chain, entity="SOMEWHERE-ELSE")
    with pytest.raises(InvalidRiskResultError):
        dataclasses.replace(medium_chain, risk_level="HIGH")
    with pytest.raises(InvalidRiskResultError):
        dataclasses.replace(medium_chain, risk_score=0.0)
    with pytest.raises(InvalidResponseDecisionError):
        dataclasses.replace(medium_chain, response_decision=DECISION_WITHHELD)
    with pytest.raises(InvalidForecastResultError):
        dataclasses.replace(medium_chain, artifact_id="other-artifact")
    with pytest.raises(IntegrationBoundaryError):
        dataclasses.replace(medium_chain, integrated_at=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc))


# --------------------------------------------------------------------------- #
# Contract violations
# --------------------------------------------------------------------------- #


def test_a_non_forecast_object_is_refused():
    with pytest.raises(InvalidForecastResultError) as excinfo:
        integrate({"forecast_id": "hand-written"})
    assert excinfo.value.reason == "invalid_forecast_result"


def test_a_bare_forecast_inference_is_refused():
    """Phase 8 will not invent a forecast id or a serving status."""
    with pytest.raises(InvalidForecastResultError) as excinfo:
        integrate(shared_served().inference)
    message = str(excinfo.value)
    assert "carries neither" in message
    assert "will not invent them" in message


def test_a_non_risk_object_is_refused_with_phase_sevens_error():
    with pytest.raises(InvalidRiskResultError) as excinfo:
        integrate(shared_served(), object())
    assert excinfo.value.reason == "invalid_risk_result"


def test_a_non_response_object_is_refused():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    with pytest.raises(InvalidResponseDecisionError) as excinfo:
        integrate(served_forecast, risk, "MONITOR")
    assert excinfo.value.reason == "invalid_response_decision"


def test_a_response_state_phase_seven_cannot_emit_is_refused():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    forged = dataclasses.replace(complete_decision(risk), decision="EVACUATE")
    with pytest.raises(InvalidResponseDecisionError):
        integrate(served_forecast, risk, forged)


def test_a_risk_result_without_a_forecast_is_refused():
    risk = risk_result_for_band(shared_run(), shared_served(), shared_residuals(), "MEDIUM")
    with pytest.raises(LayerSequenceError) as excinfo:
        integrate(None, risk, complete_decision(risk))
    assert excinfo.value.reason == "layer_sequence_error"


def test_a_response_decision_without_a_risk_result_is_refused():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    with pytest.raises(LayerSequenceError):
        integrate(served_forecast, None, complete_decision(risk))


def test_every_phase_8_error_is_a_value_error_and_distinguishable():
    for error in (
        InvalidForecastResultError,
        InvalidResponseDecisionError,
        LayerSequenceError,
        ChainMismatchError,
        InvalidIntegrationStatusError,
        IntegrationBoundaryError,
    ):
        assert issubclass(error, IntegrationBoundaryError)
        assert issubclass(error, ValueError)
        assert error.reason


def test_phase_8_does_not_reuse_the_risk_or_response_error_base_classes():
    from app.engines.hydro.forecast_risk import RiskBoundaryError
    from app.engines.hydro.response_context import ResponseBoundaryError as ResponseError

    assert not issubclass(IntegrationBoundaryError, RiskBoundaryError)
    assert not issubclass(IntegrationBoundaryError, ResponseError)


def test_the_risk_result_error_is_phase_sevens_own_class():
    from app.engines.hydro.response_context import InvalidRiskResultError as PhaseSevenError

    assert InvalidRiskResultError is PhaseSevenError


# --------------------------------------------------------------------------- #
# Errors versus states
# --------------------------------------------------------------------------- #


def test_integrate_safe_answers_instead_of_raising():
    assessment = integrate_safe({"not": "a forecast"})
    assert assessment.integration_status == INTEGRATION_NOT_EVALUABLE
    assert assessment.error_reason == "invalid_forecast_result"


def test_integrate_safe_records_the_reason_rather_than_discarding_it(station_two):
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    assessment = integrate_safe(served_forecast, risk, decision_for_entity(station_two, risk))
    assert assessment.error_reason == EntityMismatchError.reason
    assert station_two in assessment.integration_reason


def test_an_unassembled_chain_is_never_reported_as_complete(station_two):
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    assessment = integrate_safe(served_forecast, risk, decision_for_entity(station_two, risk))
    assert assessment.integration_status == INTEGRATION_NOT_EVALUABLE
    assert not assessment.is_complete


def test_the_error_path_still_carries_the_recognisable_layers(station_two):
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    assessment = integrate_safe(served_forecast, risk, decision_for_entity(station_two, risk))
    assert assessment.forecast is served_forecast
    assert assessment.risk is risk
    assert assessment.chain[1].layer_id == risk.risk_result_id


def test_integration_from_error_tolerates_any_exception():
    assessment = integration_from_error(RuntimeError("something else entirely"))
    assert assessment.integration_status == INTEGRATION_NOT_EVALUABLE
    assert assessment.error_reason == "error"
    assert assessment.disclaimer == SYNTHETIC_DATA_DISCLAIMER


def test_integration_from_error_drops_an_unrecognisable_layer():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    assessment = integration_from_error(
        MissingForecastError("no forecast"), forecast=served_forecast, risk=object()
    )
    assert assessment.forecast is served_forecast
    assert assessment.risk is None
    assert assessment.chain[1].present is False


def test_the_error_path_explains_itself(medium_chain):
    assessment = integration_from_error(RuntimeError("boom"), forecast=medium_chain.forecast)
    text = assessment.explain()
    assert "integration refused" in text
    assert "never reported as complete" in text


# --------------------------------------------------------------------------- #
# Carried-forward GIS and history
# --------------------------------------------------------------------------- #


def test_gis_availability_is_carried_forward_with_the_absent_marker(medium_chain):
    assert medium_chain.gis_available is False
    assert medium_chain.gis_reason == NOT_AVAILABLE
    assert NOT_AVAILABLE == "NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED"


def test_historical_availability_is_carried_forward_with_phase_sixs_own_reason(medium_chain):
    """Phase 6's reason is forwarded verbatim rather than replaced with the generic marker.

    Phase 6's reason is more specific than the generic marker and more useful: it says
    *what* is missing (an event register) rather than only that something is. Replacing
    it with `NOT_AVAILABLE` would lose that, so it is carried as-is.
    """
    assert medium_chain.historical_available is False
    assert medium_chain.historical_reason == medium_chain.risk.historical_context["reason"]
    assert medium_chain.historical_reason
    assert "no flood event" in medium_chain.historical_reason


def test_gis_and_history_are_projected_and_never_interpreted(medium_chain):
    """Every spatial field stays None because Phase 6 left it None, not because Phase 8 did."""
    gis = medium_chain.risk.gis_context
    assert gis["available"] is False
    assert gis["provider"] == "none"
    assert gis["elevation_m"] is None
    assert gis["river_distance_m"] is None
    assert medium_chain.to_dict()["risk"] is not None
    # Phase 8 exposes only the availability verdict, never a spatial number.
    assert "elevation_m" not in medium_chain.to_dict()["risk"]


def test_the_explanation_draws_no_spatial_conclusion(medium_chain):
    text = medium_chain.explain()
    assert "no spatial conclusion of any kind" in text
    assert "no flood event was invented" in text


def test_no_spatial_data_is_serialized_even_though_the_words_are_described(refused_chain):
    """The absence of GIS is *described*; no GIS value is ever carried.

    The distinction matters for a naive text scan: the explanation legitimately names
    river distance, elevation and floodplain status to say that Phase 8 computes none
    of them. What must never appear is an actual measurement under any of those names.
    """
    payload = json.loads(refused_chain.to_json())
    # A refused forecast carries no risk summary at all, so nothing spatial can hide in
    # one. The flags still report the absence, which is the whole point of carrying them.
    assert payload["risk"] is None
    assert payload["gis_available"] is False
    assert payload["historical_available"] is False
    assert payload["gis_available"] is False
    assert payload["historical_available"] is False


# --------------------------------------------------------------------------- #
# The contract, described
# --------------------------------------------------------------------------- #


def test_the_contract_description_names_the_architecture():
    description = integration_contract_description()
    assert "Phase 5 ServedForecast" in description["architecture"]
    assert "Phase 6 RiskResult" in description["architecture"]
    assert "Phase 7 ResponseDecision" in description["architecture"]
    assert "Phase 8 IntegratedForecastAssessment" in description["architecture"]


def test_the_contract_description_lists_every_state_with_a_meaning():
    description = integration_contract_description()
    assert description["integration_states"] == list(INTEGRATION_STATES)
    for state in INTEGRATION_STATES:
        assert description["state_meanings"][state]


def test_the_contract_description_publishes_the_derivation_order():
    order = integration_contract_description()["status_derivation_order"]
    assert len(order) == 10
    assert order[0] == "no forecast"
    assert order[-1] == "otherwise COMPLETE"


def test_the_contract_description_records_the_authority_boundaries():
    description = integration_contract_description()
    assert "Phase 6 owns the exceedance probability" in description["risk_authority"]
    assert "sole authority for response classification" in description["response_authority"]
    assert "Phase 5 owns forecast validity" in description["forecast_authority"]
    assert "falls back to no other model" in description["forecast_authority"]
    assert "there is no integration_score" in description["no_composite_score"]
    assert description["no_exposure_values"]
    assert description["service_boundary"].startswith("none")
    assert description["quantum_boundary"].startswith("none")


def test_the_contract_description_names_the_reused_errors():
    description = integration_contract_description()
    assert InvalidRiskResultError.reason in description["reused_errors"]
    assert EntityMismatchError.reason in description["reused_errors"]
    assert FutureContextError.reason in description["reused_errors"]


def test_the_contract_description_records_the_disclaimer_and_determinism_rules():
    description = integration_contract_description()
    assert "empty disclaimer must not survive" in description["disclaimer_rule"]
    assert "integrated_at is the forecast origin" in description["no_clock"]
    assert "sha256" in description["no_randomness"]
    assert "frozen dataclass" in description["immutability"]


def test_the_contract_description_publishes_the_gis_absent_marker():
    assert integration_contract_description()["gis_absent_marker"] == NOT_AVAILABLE


def test_the_module_publishes_everything_it_claims_to():
    from app.engines.hydro import integration_assessment as module

    for name in module.__all__:
        assert hasattr(module, name), name


# --------------------------------------------------------------------------- #
# Phase 7 vocabulary Phase 8 did not reinvent
# --------------------------------------------------------------------------- #


def test_phase_8_reuses_phase_sevens_context_vocabulary():
    assert RESPONSE_AVAILABILITY == SIGNAL_AVAILABILITY


def test_phase_8_reuses_phase_sixes_evaluation_states():
    assert set(CONTEXT_EVALUATION_STATES) >= {
        CONTEXT_PARTIALLY_EVALUATED,
        CONTEXT_UNAVAILABLE,
        CONTEXT_NOT_EVALUABLE,
    }


def test_phase_8_invents_no_availability_state_of_its_own():
    recorded = set()
    for chain in (
        integrate(None),
        integrate(shared_served()),
    ):
        recorded |= set(chain.evidence_availability)
    assert recorded <= set(SIGNAL_AVAILABILITY)


def test_duplicate_exposure_kinds_are_refused_by_phase_7():
    """Phase 8 relies on this, so it is asserted here rather than assumed."""
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    with pytest.raises(InvalidResponseContextError):
        decide_for(risk, exposure=(unavailable_population(), unavailable_population()))


def test_an_empty_response_policy_still_withholds_at_the_integration_boundary():
    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    assessment = integrate(served_forecast, risk, decide_for(risk, policy=ResponsePolicy()))
    assert assessment.integration_status == INTEGRATION_WITHHELD
    assert assessment.response.decision == DECISION_WITHHELD


def test_phase_8_does_not_reimplement_the_empty_context_state():
    """A risk result over an unreadable context is produced by Phase 6, not here."""
    from app.engines.hydro.forecast_risk import assess_risk

    served_forecast = shared_served()
    risk = assess_risk(
        served_forecast,
        config=risk_config(3.5),
        context=empty_context(served_forecast.inference.entity, shared_run().origin),
        residuals=list(shared_residuals()),
    )
    assert risk.evaluation_state == CONTEXT_UNAVAILABLE
    assert integrate(served_forecast, risk, complete_decision(risk)).integration_status == (
        INTEGRATION_WITHHELD
    )


def test_the_unsupported_response_state_error_is_phase_sevens_own():
    """Phase 8 inherits Phase 7's refusal rather than inventing its own."""
    with pytest.raises(UnsupportedResponseStateError):
        ResponsePolicy(risk_level_response={"HIGH": "EVACUATE"})