# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Tests for `app.engines.hydro.risk`.

The rules enforced here are the difference between a flood warning and a
plausible-looking guess:

* no threshold means no probability is emitted,
* the probability is derived from a *measured* residual spread, never assumed,
* an unapproved threshold is reported as pending, not as a fact,
* the reference engine's demo `8.0` placeholder is not inherited.
"""

from __future__ import annotations

import math

import pytest

from app.engines.hydro.config import RiskPolicy
from app.engines.hydro.risk import (
    RiskAssessment,
    RiskAssessor,
    RiskError,
    classify_risk_level,
    demo_risk_policy,
    exceedance_probability,
    normal_cdf,
    residual_sigma,
)


# --- the normal approximation ------------------------------------------------


def test_normal_cdf_reference_values():
    assert normal_cdf(0.0) == pytest.approx(0.5)
    assert normal_cdf(1.0) == pytest.approx(0.8413, abs=1e-3)
    assert normal_cdf(-1.0) == pytest.approx(0.1587, abs=1e-3)
    assert normal_cdf(1.96) == pytest.approx(0.9750, abs=1e-3)


def test_exceedance_probability_is_the_upper_tail():
    """P(observation > threshold) for a forecast `predicted` with spread `sigma`.

    The forecast being *above* the threshold is what makes exceedance likely, so
    a prediction two sigma above it must read as a high probability, not a low
    one. Getting this sign wrong inverts the entire warning, so the direction is
    pinned in both directions.
    """
    # 1 - Phi(0) == 0.5: forecast sits exactly on the threshold.
    assert exceedance_probability(5.0, 5.0, 1.0) == pytest.approx(0.5)
    # Forecast 2 sigma ABOVE the threshold: the true level is very likely to
    # exceed it -> the classic 97.7% tail.
    assert exceedance_probability(7.0, 5.0, 1.0) == pytest.approx(0.9772, abs=1e-3)
    # Forecast 2 sigma BELOW the threshold: the classic 2.3% tail.
    assert exceedance_probability(3.0, 5.0, 1.0) == pytest.approx(0.0228, abs=1e-3)


def test_exceedance_probability_is_monotonic_in_the_forecast():
    sigma = 0.8
    values = [exceedance_probability(v, 5.0, sigma) for v in (2.0, 4.0, 5.0, 6.0, 9.0)]
    assert values == sorted(values)
    assert all(0.0 <= v <= 1.0 for v in values)


def test_exceedance_probability_approaches_certainty_with_a_tight_spread():
    # A near-zero residual spread means the forecast is far above the threshold
    # in units of its own uncertainty: the probability saturates at 1.
    assert exceedance_probability(6.0, 5.0, 1e-6) == pytest.approx(1.0)


def test_exceedance_probability_rejects_a_non_positive_sigma():
    with pytest.raises(RiskError):
        exceedance_probability(5.0, 5.0, 0.0)
    with pytest.raises(RiskError):
        exceedance_probability(5.0, 5.0, -1.0)


# --- the measured spread -----------------------------------------------------


def test_residual_sigma_is_the_sample_standard_deviation():
    residuals = [0.1, -0.2, 0.3, -0.4, 0.5]
    mean = sum(residuals) / len(residuals)
    expected = math.sqrt(sum((r - mean) ** 2 for r in residuals) / (len(residuals) - 1))
    assert residual_sigma(residuals) == pytest.approx(expected)


def test_residual_sigma_refuses_a_zero_spread():
    """A perfect fit does not give a sigma of 0 — it gives no distribution.

    Returning 0.0 would let `exceedance_probability` produce a confident 0 or 1
    for a perfect fit, which is a fabricated warning. The refusal is the honest
    answer: a zero spread is not a measurement.
    """
    with pytest.raises(RiskError, match="spread is zero"):
        residual_sigma([0.0, 0.0, 0.0])


def test_residual_sigma_needs_at_least_two_observations():
    with pytest.raises(RiskError):
        residual_sigma([0.5])
    with pytest.raises(RiskError):
        residual_sigma([])


def test_residual_sigma_rejects_non_finite_residuals():
    with pytest.raises(RiskError):
        residual_sigma([0.1, float("nan"), 0.2])


# --- band classification -----------------------------------------------------


def test_band_edges_map_to_the_documented_labels():
    """Band edges are inclusive upper bounds, so 0.1 is the top of LOW.

    A probability exactly on an edge belongs to the band it closes, not to the
    next one up; that convention is asserted here so a change to `<=` vs `<`
    cannot silently reclassify every borderline forecast.
    """
    edges = (0.1, 0.3, 0.6, 0.9)
    labels = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert classify_risk_level(0.0, edges, labels) == "LOW"
    assert classify_risk_level(0.1, edges, labels) == "LOW"
    assert classify_risk_level(0.11, edges, labels) == "MEDIUM"
    assert classify_risk_level(0.3, edges, labels) == "MEDIUM"
    assert classify_risk_level(0.31, edges, labels) == "HIGH"
    assert classify_risk_level(0.6, edges, labels) == "HIGH"
    assert classify_risk_level(0.61, edges, labels) == "CRITICAL"
    # Above the last declared edge the top band is still assigned rather than
    # leaving a near-certain flood unclassified.
    assert classify_risk_level(0.95, edges, labels) == "CRITICAL"
    assert classify_risk_level(1.0, edges, labels) == "CRITICAL"


def test_interior_edges_without_a_closed_upper_edge_are_accepted():
    """`len(labels) - 1` interior edges is the other documented spelling."""
    labels = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    edges = (0.1, 0.3, 0.6)
    assert classify_risk_level(0.0, edges, labels) == "LOW"
    assert classify_risk_level(0.2, edges, labels) == "MEDIUM"
    assert classify_risk_level(0.5, edges, labels) == "HIGH"
    assert classify_risk_level(0.99, edges, labels) == "CRITICAL"


def test_bands_that_match_neither_spelling_are_left_unassigned():
    """A configuration that cannot be read yields no band, not a guess.

    Two edges against four labels describes neither supported shape. Raising
    would abort an otherwise servable forecast; returning a wrong band would
    mislabel a flood. Returning `None` and saying so is the safe answer.
    """
    labels = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert classify_risk_level(0.5, (0.2, 0.8), labels) is None
    assert classify_risk_level(0.5, (0.1, 0.2, 0.3, 0.4, 0.5, 0.6), labels) is None


def test_no_edges_or_no_labels_yields_no_band():
    labels = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert classify_risk_level(0.5, (), labels) is None
    assert classify_risk_level(0.5, (0.2, 0.8, 0.9), ()) is None


def test_classification_rejects_unsorted_edges():
    with pytest.raises(RiskError):
        classify_risk_level(0.5, (0.6, 0.2, 0.9), ("LOW", "MEDIUM", "HIGH", "CRITICAL"))


def test_classification_rejects_edges_outside_the_probability_range():
    with pytest.raises(RiskError):
        classify_risk_level(0.5, (-0.1, 0.8, 0.9), ("LOW", "MEDIUM", "HIGH", "CRITICAL"))
    with pytest.raises(RiskError):
        classify_risk_level(0.5, (0.2, 0.8, 1.4), ("LOW", "MEDIUM", "HIGH", "CRITICAL"))


def test_classification_rejects_an_out_of_range_probability():
    with pytest.raises(RiskError):
        classify_risk_level(1.4, (0.2, 0.8), ("LOW", "MEDIUM", "HIGH"))
    with pytest.raises(RiskError):
        classify_risk_level(-0.1, (0.2, 0.8), ("LOW", "MEDIUM", "HIGH"))


# --- policy configuration ----------------------------------------------------


def test_unconfigured_policy_refuses_to_assess():
    """An unusable policy yields an *unavailable* result, not an exception.

    `assess()` returning a blank assessment is what lets `is_ready()` and the
    serving methods agree: both report the same missing configuration rather
    than one raising while the other claims readiness. Nothing is invented.
    """
    assessor = RiskAssessor(RiskPolicy())
    assert assessor.is_configured is False
    assert assessor.missing_configuration()

    result = assessor.assess(4.2, residual_sigma=0.5)
    assert result.is_available is False
    assert result.flood_probability is None
    assert result.risk_level is None
    # The forecast value is echoed so a reader can see what was not assessed.
    assert result.threshold is None
    assert "PENDING" in result.notes or "pending" in result.notes
    assert "HYDRO_FLOOD_THRESHOLD" in result.notes


def test_the_threshold_without_bands_is_still_unusable():
    policy = RiskPolicy(flood_threshold=5.0, threshold_source="doc", band_edges=())
    assessor = RiskAssessor(policy)
    assert assessor.is_configured is False
    assert any("HYDRO_RISK_BANDS" in item for item in assessor.missing_configuration())


def test_band_edges_without_a_threshold_is_unusable():
    """Bands without a threshold have nothing to band against."""
    policy = RiskPolicy(flood_threshold=None, band_edges=(0.5,))
    assert RiskAssessor(policy).is_configured is False


def test_an_unapproved_policy_is_still_usable_but_flagged():
    """Unapproved is a labelling state, not a blocker.

    A configured-but-unapproved policy can still be assessed for a demo; it just
    must never be presented as official. Blocking it would make the synthetic
    pipeline untestable, and presenting it without the flag would be a lie.
    """
    assessor = _assessor(policy_status="pending")
    assert assessor.is_configured is True
    result = assessor.assess(6.0, residual_sigma=0.5)
    assert result.is_available is True
    assert result.policy_approved is False
    assert "NOT official" in result.notes


def test_demo_policy_is_never_officially_approved():
    policy = demo_risk_policy(5.0)
    assert policy.flood_threshold == pytest.approx(5.0)
    assert policy.policy_status == "pending"
    assert "NOT an official flood stage" in policy.threshold_source
    assert "DEMO" in policy.threshold_source


def test_the_reference_engine_placeholder_is_not_inherited():
    """The team reference engine uses 8.0 as a demo placeholder.

    Navya's policy must not silently pick that number up as if it meant
    something. It has to be supplied explicitly, and even then it is labelled a
    demo value.
    """
    assert RiskPolicy().flood_threshold is None
    assert demo_risk_policy(8.0).threshold_source and "NOT an official" in demo_risk_policy(8.0).threshold_source


# --- assessment --------------------------------------------------------------


def _assessor(**overrides) -> RiskAssessor:
    policy = RiskPolicy(
        flood_threshold=5.0,
        threshold_source="unit-test value",
        policy_status="pending",
        band_edges=(0.1, 0.3, 0.6, 0.9),
    )
    if overrides:
        from dataclasses import replace

        policy = replace(policy, **overrides)
    return RiskAssessor(policy)


def test_assessment_reports_every_field_the_contract_needs():
    result = _assessor().assess(6.0, residual_sigma=0.5)
    assert isinstance(result, RiskAssessment)
    assert result.flood_probability is not None
    assert result.risk_level in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert result.risk_score is not None
    assert result.threshold == pytest.approx(5.0)
    assert result.threshold_source == "unit-test value"
    assert result.residual_sigma == pytest.approx(0.5)
    assert result.is_available is True


def test_assessment_without_a_measured_sigma_is_unavailable():
    """No measured spread means no distribution and therefore no probability.

    The result is blank and the reason is recorded, rather than the module
    substituting a plausible sigma and emitting a confident number.
    """
    result = _assessor().assess(6.0, residual_sigma=None)
    assert result.is_available is False
    assert result.flood_probability is None
    assert result.risk_level is None
    assert "no measured residual spread" in result.notes
    # The threshold itself is still reported, so the gap is visibly about the
    # spread and not about the policy.
    assert result.threshold == pytest.approx(5.0)


def test_assessment_with_an_unmeasurable_sigma_is_unavailable():
    """A sigma of zero is a refusal by `residual_sigma()`; reaching the assessor
    with one must not produce a confident probability either."""
    with pytest.raises(RiskError):
        _assessor().assess(6.0, residual_sigma=0.0)


def test_a_supplied_probability_is_recorded_as_such():
    """An exceedance frequency from another method is accepted, but the method
    tag must not claim the normal approximation was used."""
    result = _assessor().assess(4.0, probability=0.42)
    assert result.flood_probability == pytest.approx(0.42)
    assert result.method == "supplied_probability"
    assert result.residual_sigma is None


def test_a_supplied_probability_outside_the_unit_interval_is_refused():
    with pytest.raises(RiskError):
        _assessor().assess(4.0, probability=1.7)


def test_unreadable_bands_leave_the_probability_but_drop_the_band():
    """A probability is a computation; a band is a policy claim. Losing the
    policy must not discard the measured probability."""
    result = _assessor(band_edges=(0.2, 0.8)).assess(6.0, residual_sigma=0.5)
    assert result.flood_probability is not None
    assert result.risk_level is None
    assert "no band assigned" in result.notes


def test_pending_policy_is_reported_as_pending_not_approved():
    result = _assessor().assess(6.0, residual_sigma=0.5)
    assert result.policy_approved is False
    assert result.threshold_policy == "pending"
    assert "pending" in result.notes.lower()
    assert "NOT official" in result.notes


def test_approved_policy_is_reported_as_approved():
    result = _assessor(policy_status="approved").assess(6.0, residual_sigma=0.5)
    assert result.policy_approved is True
    assert result.threshold_policy == "approved"


def test_a_tight_spread_raises_the_probability():
    assessor = _assessor()
    confident = assessor.assess(5.4, residual_sigma=0.1)
    unsure = assessor.assess(5.4, residual_sigma=2.0)
    assert confident.flood_probability > unsure.flood_probability


def test_risk_score_and_probability_are_consistent():
    result = _assessor().assess(5.6, residual_sigma=0.4)
    assert 0.0 <= result.risk_score <= 1.0
    assert result.risk_score == pytest.approx(result.flood_probability)


def test_assessment_is_deterministic():
    assessor = _assessor()
    first = assessor.assess(5.3, residual_sigma=0.6)
    second = assessor.assess(5.3, residual_sigma=0.6)
    assert first.to_dict() == second.to_dict()


def test_assessment_serialises_for_the_provenance_record():
    payload = _assessor().assess(6.0, residual_sigma=0.5).to_dict()
    assert payload["flood_probability"] is not None
    assert payload["threshold"] == pytest.approx(5.0)
    assert payload["method"]


def test_policy_summary_names_what_is_missing():
    summary = RiskAssessor(RiskPolicy()).policy_summary()
    assert "threshold" in summary.lower()
