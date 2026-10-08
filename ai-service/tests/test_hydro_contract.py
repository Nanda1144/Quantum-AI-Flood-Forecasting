# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Tests for `app.engines.hydro.contract`.

The contract is the boundary between the forecasting work and the team's
optimization work, so its tests are mostly about honesty:

* the required integration statement is present verbatim,
* the payload the running optimizer accepts today is separated from the fields
  that would need a team owner to add,
* a missing probability stays `None` rather than becoming a number,
* a candidate-risk mapping that is not backed by an authoritative station
  geometry is declared synthetic rather than presented as real.
"""

from __future__ import annotations

import pytest

from app.engines.hydro.contract import (
    FORECAST_CONTRACT_VERSION,
    INTEGRATION_STATEMENT,
    SYNTHETIC_MAPPING_DISCLAIMER,
    UNVERIFIED_INPUT_NOTICES,
    CandidateRiskAttribution,
    CandidateRiskMappingSpec,
    ContractError,
    ForecastOutput,
    OptimizationHandoff,
    normalize_candidate_risk,
    priority_for_risk_level,
)


def _output(**overrides) -> ForecastOutput:
    values = {
        "forecast_id": "FC-20240101-060",
        "forecast_timestamp": "2024-01-01T06:00:00Z",
        "forecast_horizon": "6h",
        "model_id": "NAVYA-HYDRO-001",
        "model_version": "ridge-hydro-forecast-v1",
        "status": "pending",
        "station_reference": "SYNTHETIC-STATION-0001",
        "target": "water_level",
        "target_units": "m (demo assumption — NOT datum verified)",
        "predicted_value": 5.6,
        "predicted_water_level": 5.6,
        "flood_probability": 0.71,
        "risk_level": "HIGH",
        "risk_score": 0.71,
        "threshold": 5.5,
        "threshold_policy": "pending",
        "residual_sigma": 0.4,
        "lead_time_rows": 6,
        "provenance_reference": "synthetic://unit-test/hydro",
        "contract_version": FORECAST_CONTRACT_VERSION,
    }
    values.update(overrides)
    return ForecastOutput(**values)


# --- the integration statement ----------------------------------------------


def test_integration_statement_is_verbatim():
    assert INTEGRATION_STATEMENT == (
        "Existing optimization currently requires forecast_id. "
        "Additional forecast-derived risk fields require team-owner integration."
    )


def test_every_description_carries_the_statement():
    handoff = OptimizationHandoff(forecast=_output())
    assert INTEGRATION_STATEMENT in handoff.describe()
    assert handoff.to_proposed_payload()["integration_statement"] == INTEGRATION_STATEMENT


# --- forecast output ---------------------------------------------------------


def test_available_fields_lists_the_derived_risk_fields():
    fields = _output().available_fields()
    for expected in (
        "station_reference",
        "target",
        "target_units",
        "predicted_value",
        "flood_probability",
        "risk_level",
        "risk_score",
        "threshold",
        "residual_sigma",
    ):
        assert expected in fields


def test_available_fields_omits_what_was_not_produced():
    """A field with no value is reported as absent, not sent as null."""
    bare = _output(
        flood_probability=None,
        risk_level=None,
        residual_sigma=None,
        threshold=None,
        target=None,
        target_units=None,
        predicted_value=None,
        predicted_water_level=None,
        risk_score=None,
        station_reference=None,
        reach_reference=None,
        lead_time_rows=None,
        provenance_reference=None,
    )
    assert bare.available_fields() == ()


def test_a_missing_probability_is_allowed_and_stays_none():
    """`None` means "not produced", which is honest. Inventing 0.0 is not."""
    bare = _output(flood_probability=None, risk_level=None)
    assert bare.flood_probability is None
    assert bare.risk_level is None
    assert bare.to_dict()["flood_probability"] is None


def test_output_rejects_a_blank_forecast_id():
    with pytest.raises(ContractError, match="forecast_id"):
        _output(forecast_id="   ")


def test_output_rejects_a_probability_outside_zero_one():
    with pytest.raises(ContractError, match="flood_probability"):
        _output(flood_probability=1.4)
    with pytest.raises(ContractError, match="flood_probability"):
        _output(flood_probability=-0.1)


def test_output_rejects_an_unknown_risk_level():
    with pytest.raises(ContractError, match="risk_level"):
        _output(risk_level="CATASTROPHIC")


def test_output_rejects_an_unknown_status():
    with pytest.raises(ContractError, match="status"):
        _output(status="probably-fine")


@pytest.mark.parametrize("status", ["completed", "pending", "failed"])
def test_every_supported_status_is_accepted(status):
    assert _output(status=status).status == status


def test_target_specific_fields_are_independent():
    """A water-level forecast does not populate inflow, and vice versa.

    The engine sets these explicitly; a shared field would let an inflow number
    be read as a stage.
    """
    level = _output(target="water_level", predicted_water_level=5.6)
    assert level.predicted_inflow is None
    inflow = _output(
        target="inflow", predicted_value=120.0, predicted_inflow=120.0, predicted_water_level=None
    )
    assert inflow.predicted_inflow == pytest.approx(120.0)
    assert inflow.predicted_water_level is None


def test_location_reference_prefers_the_station():
    both = _output(station_reference="ST-1", reach_reference="REACH-1")
    assert both.location_reference == "ST-1"
    reach_only = _output(station_reference=None, reach_reference="REACH-1")
    assert reach_only.location_reference == "REACH-1"
    neither = _output(station_reference=None, reach_reference=None)
    assert neither.location_reference is None


def test_serialising_keeps_the_status():
    assert _output().to_dict()["status"] == "pending"
    assert _output(status="completed").to_dict()["status"] == "completed"


# --- the handoff -------------------------------------------------------------


def test_existing_payload_carries_only_contract_fields():
    """This is the minimum the running optimizer accepts today."""
    payload = OptimizationHandoff(forecast=_output()).to_existing_payload()
    assert set(payload) == {
        "forecast_id",
        "risk_score",
        "priority",
        "candidate_locations_available",
        "resource_constraints_available",
    }
    assert payload["forecast_id"] == "FC-20240101-060"
    assert payload["priority"] == "high"
    assert payload["risk_score"] == pytest.approx(0.71)


def test_availability_flags_are_sent_as_false_by_default():
    """The running service reads them as `?? true`.

    Omitting them would make the platform persist "candidate locations
    available: true", which nothing in this repository supports.
    """
    payload = OptimizationHandoff(forecast=_output()).to_existing_payload()
    assert payload["candidate_locations_available"] is False
    assert payload["resource_constraints_available"] is False


def test_availability_flags_can_be_overridden_when_actually_sourced():
    handoff = OptimizationHandoff(
        forecast=_output(),
        candidate_locations_available=True,
        resource_constraints_available=True,
    )
    payload = handoff.to_existing_payload()
    assert payload["candidate_locations_available"] is True


def test_candidate_locations_are_declared_unavailable_not_invented():
    handoff = OptimizationHandoff(forecast=_output())
    assert handoff.candidate_locations_available is False
    assert handoff.resource_constraints_available is False


def test_proposed_payload_lists_the_derived_fields():
    proposed = OptimizationHandoff(forecast=_output()).to_proposed_payload()
    for field in (
        "flood_probability",
        "risk_level",
        "predicted_water_level",
        "forecast_horizon",
        "threshold",
        "threshold_policy",
    ):
        assert field in proposed


def test_fields_requiring_integration_names_the_unavailable_ones():
    fields = OptimizationHandoff(forecast=_output()).fields_requiring_integration()
    assert "flood_probability" in fields
    assert "risk_level" in fields
    # These ARE accepted today, so they must not be listed as pending.
    assert "forecast_id" not in fields
    assert "risk_score" not in fields


def _minimal() -> ForecastOutput:
    """A forecast carrying nothing the optimizer does not already accept."""
    return _output(
        flood_probability=None,
        risk_level=None,
        residual_sigma=None,
        threshold=None,
        station_reference=None,
        reach_reference=None,
        lead_time_rows=None,
        provenance_reference=None,
        predicted_water_level=None,
        predicted_value=None,
        risk_score=None,
        target=None,
        target_units=None,
    )


def test_only_the_always_present_fields_still_need_integration():
    """`forecast_horizon` and `forecast_timestamp` are structural, so they can
    never be dropped and are always pending a team-owner slot."""
    assert OptimizationHandoff(forecast=_minimal()).fields_requiring_integration() == (
        "forecast_horizon",
        "forecast_timestamp",
    )


# --- priority ----------------------------------------------------------------


def test_priority_matches_the_platform_mapping():
    assert priority_for_risk_level("LOW") == "low"
    assert priority_for_risk_level("MEDIUM") == "medium"
    assert priority_for_risk_level("HIGH") == "high"
    assert priority_for_risk_level("CRITICAL") == "critical"


def test_an_unrecognised_level_maps_conservatively_to_low():
    """Not a throw: the optimizer still receives an explicit risk_score, so the
    right failure mode is a conservative priority rather than a dead request."""
    assert priority_for_risk_level("EXTREME") == "low"
    assert priority_for_risk_level(None) == "low"
    assert priority_for_risk_level("") == "low"


# --- candidate risk ----------------------------------------------------------


def test_normalize_candidate_risk_clamps_and_preserves_none():
    assert normalize_candidate_risk(0.5) == pytest.approx(0.5)
    assert normalize_candidate_risk(-1.0) == pytest.approx(0.0)
    assert normalize_candidate_risk(2.0) == pytest.approx(1.0)
    # None stays None: a missing risk must not become a zero risk, which would
    # make an unassessed site look safe.
    assert normalize_candidate_risk(None) is None


def test_normalize_candidate_risk_rejects_nan():
    with pytest.raises(ContractError, match="NaN"):
        normalize_candidate_risk(float("nan"))


def _attribution(**overrides) -> CandidateRiskAttribution:
    values = {
        "candidate_location_id": "CANDIDATE-0001",
        "forecast_id": "FC-20240101-060",
        "station_reference": "SYNTHETIC-STATION-0001",
        "reach_reference": None,
        "forecast_risk_score": 0.71,
        "derived_flood_risk": None,
        "mapping_provenance": "SYNTHETIC/demo mapping; NOT an authoritative station-to-reach map",
        "is_synthetic": True,
        "notes": "no station-to-candidate mapping exists",
    }
    values.update(overrides)
    return CandidateRiskAttribution(**values)


def test_a_synthetic_attribution_is_flagged_and_disclaimed():
    payload = _attribution().to_dict()
    assert payload["is_synthetic"] is True
    assert payload["disclaimer"] == SYNTHETIC_MAPPING_DISCLAIMER


def test_a_verified_attribution_carries_no_disclaimer():
    payload = _attribution(is_synthetic=False, derived_flood_risk=0.55).to_dict()
    assert payload["disclaimer"] is None


def test_derived_risk_must_be_in_the_band_the_optimizer_expects():
    """`CandidateLocation.floodRisk` is consumed as a [0,1] float; anything else
    would silently distort the QUBO linear term."""
    with pytest.raises(ContractError, match=r"\[0, 1\]"):
        _attribution(derived_flood_risk=1.4)


def test_a_blank_candidate_id_is_refused():
    with pytest.raises(ContractError, match="candidate_location_id"):
        _attribution(candidate_location_id="  ")


def test_an_unmapped_candidate_carries_no_derived_risk():
    assert _attribution().derived_flood_risk is None


def test_mapping_spec_defaults_to_synthetic():
    spec = CandidateRiskMappingSpec(forecast_id="FC-20240101-060", attributions=(_attribution(),))
    spec.validate()
    assert spec.to_dict()["synthetic"] is True


def test_an_empty_mapping_validates():
    spec = CandidateRiskMappingSpec(forecast_id="FC-20240101-060")
    spec.validate()  # must not raise
    assert spec.to_dict()["attributions"] == []


def test_a_mapping_may_not_mix_synthetic_and_verified_rows():
    spec = CandidateRiskMappingSpec(
        forecast_id="FC-20240101-060",
        attributions=(
            _attribution(candidate_location_id="A"),
            _attribution(candidate_location_id="B", is_synthetic=False, derived_flood_risk=0.4),
        ),
    )
    with pytest.raises(ContractError, match="mix"):
        spec.validate()


def test_duplicate_candidate_ids_are_refused():
    spec = CandidateRiskMappingSpec(
        forecast_id="FC-20240101-060",
        attributions=(_attribution(candidate_location_id="A"), _attribution(candidate_location_id="A")),
    )
    with pytest.raises(ContractError, match="duplicate"):
        spec.validate()


def test_mapping_payload_names_the_unverified_inputs():
    payload = CandidateRiskMappingSpec(forecast_id="FC-20240101-060").to_dict()
    assert payload["unverified_inputs"] == list(UNVERIFIED_INPUT_NOTICES)
    assert any("stand-in generator" in notice for notice in UNVERIFIED_INPUT_NOTICES)


def test_mapping_payload_states_the_integration_requirement():
    payload = CandidateRiskMappingSpec(forecast_id="FC-20240101-060").to_dict()
    assert "CandidateLocation.floodRisk" in payload["integration_statement"]
    assert "team-owner" in payload["integration_statement"]
