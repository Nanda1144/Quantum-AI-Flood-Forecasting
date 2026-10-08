# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Shared fixtures for the Phase 7 risk-to-response tests.

Not a test module — a helper. Phase 7 tests need three things over and over: a
*real* Phase 6 `RiskResult` in each of the states that matter, a response policy
that is honestly labelled as DEMO, and contextual availability in each state the
contract distinguishes.

**Everything here is synthetic/demo data**, carried through the Phase 6 fixtures
including their station identities and their disclaimer, so a Phase 7 test cannot
pass against a differently-shaped pipeline than a Phase 5 or Phase 6 one. No test
asserts a hydrological result.

Reuse, not re-implementation
----------------------------

The Phase 5 run, the served forecast, the measured residuals and the derived band
thresholds all come from `hydro_phase6_fixtures`. Phase 7 does not rebuild a
pipeline to test a decision function: `risk_result_for_band` calls the real
`assess_risk`, so the `RiskResult` a test reasons about is one the repository
actually produces.

Thresholds are derived, never guessed
-------------------------------------

`risk_result_for_band` picks the threshold with Phase 6's own
`threshold_for_band`, which inverts the exceedance model by bisection. A
hard-coded threshold would be correct only for the prediction it was chosen
against and would silently become a different test the moment that prediction
moved.

The DEMO policy is labelled, because a mapping is not a warning matrix
-----------------------------------------------------------------------

`demo_response_policy` returns a mapping that is genuinely DEMO: the thresholds it
responds to are demo values chosen for a synthetic pipeline, and the mapping itself
is a demonstration of the mechanism. `policy_status` stays `'pending'` and the
source string says so. No fixture here can produce a policy that looks approved,
because nothing in this repository is.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

import pytest

from app.engines.hydro.config import RiskPolicy
from app.engines.hydro.domains import NOT_AVAILABLE
from app.engines.hydro.forecast_risk import (
    RiskConfiguration,
    assess_risk,
    assess_risk_safe,
)
from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER
from app.engines.hydro.response_context import (
    ExposureAvailability,
    ResponseContext,
    available_exposure,
    unavailable_exposure,
)
from app.engines.hydro.response_decision import (
    DECISION_HEIGHTENED_MONITORING,
    DECISION_MONITOR,
    DECISION_REVIEW_WARNING,
    ResponsePolicy,
    ResponseRule,
)

from hydro_phase6_fixtures import (  # noqa: F401  - re-exported for the phase 7 modules
    BAND_LABELS,
    BAND_PROBABILITY,
    DEMO_THRESHOLD_SOURCE,
    RISK_FAMILY,
    baseline_served,
    dataset,
    empty_context,
    estimators,
    full_context,
    future_context,
    measured_test_residuals,
    origin,
    partial_context,
    phase5_run,
    rainfall_rule,
    residuals,
    risk_config,
    serve_for,
    served,
    sigma,
    spatial_context,
    stale_context,
    station_a,
    station_b,
    store,
    threshold_for_band,
    threshold_for_probability,
)

#: One Phase 5 run, shared by every fixture in this module.
#:
#: Cached at module scope rather than requested from `hydro_phase6_fixtures` as a
#: pytest fixture, because pytest resolves fixtures from the test module's own
#: namespace and does not follow them transitively through a helper module. A
#: fixture here that asked for Phase 6's `run` would fail with "fixture not found";
#: calling the factory once and reusing the result is the same object, at the same
#: cost, with no dependency on how pytest resolves names.
_SHARED_RUN: Any = None
_SHARED_SERVED: Any = None
_SHARED_RESIDUALS: tuple[float, ...] | None = None


def shared_run() -> Any:
    """The fixture's real Phase 5 run, built once per module."""
    global _SHARED_RUN
    if _SHARED_RUN is None:
        _SHARED_RUN = phase5_run()
    return _SHARED_RUN


def shared_served() -> Any:
    """The Phase 5 served forecast for `shared_run()`, built once per module."""
    global _SHARED_SERVED
    if _SHARED_SERVED is None:
        _SHARED_SERVED = serve_for(shared_run(), RISK_FAMILY)
    return _SHARED_SERVED


def shared_residuals() -> tuple[float, ...]:
    """The measured test-split residuals, measured once per module."""
    global _SHARED_RESIDUALS
    if _SHARED_RESIDUALS is None:
        _SHARED_RESIDUALS = measured_test_residuals(shared_run(), RISK_FAMILY)
    return _SHARED_RESIDUALS


#: The mapping the DEMO policy demonstrates. Not a warning matrix: it exists so the
#: decision path can be exercised end to end, and every surface that carries it says
#: so.
DEMO_RESPONSE_MAPPING: Mapping[str, str] = {
    "LOW": DECISION_MONITOR,
    "MEDIUM": DECISION_HEIGHTENED_MONITORING,
    "HIGH": DECISION_REVIEW_WARNING,
    "CRITICAL": DECISION_REVIEW_WARNING,
}

#: The source string every DEMO response policy carries.
DEMO_RESPONSE_SOURCE = (
    "DEMO mapping chosen to exercise the synthetic pipeline; NOT an approved warning "
    "matrix and NOT an official response procedure"
)


# --------------------------------------------------------------------------- #
# The response policy
# --------------------------------------------------------------------------- #


def demo_response_policy(
    mapping: Mapping[str, str] | None = None,
    *,
    status: str = "pending",
    policy_version: str = "navya-phase7-demo-policy/v1",
    policy_reference: str | None = None,
) -> ResponsePolicy:
    """A `ResponsePolicy` over a DEMO mapping, labelled as one."""
    return ResponsePolicy(
        risk_level_response=dict(mapping if mapping is not None else DEMO_RESPONSE_MAPPING),
        policy_status=status,
        policy_source=DEMO_RESPONSE_SOURCE,
        policy_version=policy_version,
        policy_reference=policy_reference,
    )


def partial_mapping_policy(*levels: str) -> ResponsePolicy:
    """A DEMO policy covering only `levels`. Proves an unmapped level withholds."""
    mapping = {level: DEMO_RESPONSE_MAPPING[level] for level in levels}
    return demo_response_policy(mapping)


def demo_rule(
    *,
    rule_id: str = "demo-review-warning",
    at_least: str = "MEDIUM",
    escalate_to: str = DECISION_REVIEW_WARNING,
) -> ResponseRule:
    """A DEMO raise-only rule. Its condition is a risk level, never a signal value."""
    return ResponseRule(
        rule_id=rule_id,
        risk_level_at_least=at_least,
        escalate_to=escalate_to,
        source="DEMO response rule; NOT an approved warning criterion",
    )


# --------------------------------------------------------------------------- #
# Real Phase 6 risk results, one per state that matters
# --------------------------------------------------------------------------- #


def risk_result_for_band(
    run_result: Any,
    served_forecast: Any,
    residuals: Sequence[float],
    band: str,
    *,
    context: Any = None,
    status: str = "pending",
) -> Any:
    """A real `RiskResult` whose Phase 6 band is `band`.

    The threshold is derived by inverting the exceedance model, so the band is a
    consequence of the real prediction and the real measured spread rather than a
    number typed into a fixture.
    """
    if band not in BAND_PROBABILITY:
        raise AssertionError(f"{band!r} is not one of {sorted(BAND_PROBABILITY)}")
    inference = served_forecast.inference
    threshold = threshold_for_band(
        inference.prediction, _measured_sigma(list(residuals)), band
    )
    return assess_risk(
        served_forecast,
        config=risk_config(threshold, status=status),
        context=(
            context
            if context is not None
            else full_context(inference.entity, run_result.origin)
        ),
        residuals=list(residuals),
    )


def risk_result_for_probability(
    run_result: Any,
    served_forecast: Any,
    residuals: Sequence[float],
    probability: float,
    *,
    context: Any = None,
) -> Any:
    """A real `RiskResult` at an exact exceedance probability."""
    inference = served_forecast.inference
    threshold = threshold_for_probability(
        inference.prediction, _measured_sigma(list(residuals)), probability
    )
    return assess_risk(
        served_forecast,
        config=risk_config(threshold),
        context=(
            context
            if context is not None
            else full_context(inference.entity, run_result.origin)
        ),
        residuals=list(residuals),
    )


def withheld_risk_result(run_result: Any, served_forecast: Any) -> Any:
    """A `RiskResult` Phase 6 withheld: no configured threshold.

    The state a caller reaches in this repository today, and the one Phase 7 must
    carry forward as `WITHHELD` rather than resolving to a recommendation.
    """
    return assess_risk_safe(
        served_forecast,
        config=RiskConfiguration(policy=RiskPolicy(), rules=()),
        context=full_context(served_forecast.inference.entity, run_result.origin),
        residuals=None,
    )


def context_unavailable_risk_result(
    run_result: Any, served_forecast: Any, residuals: Sequence[float]
) -> Any:
    """A `RiskResult` whose Phase 6 context was entirely unreadable.

    The band still comes from the forecast and the measured spread, which is exactly
    the case Phase 7 must withhold on: a level with nothing corroborating it is not
    a basis for a response recommendation.
    """
    return assess_risk(
        served_forecast,
        config=risk_config(3.5),
        context=empty_context(served_forecast.inference.entity, run_result.origin),
        residuals=list(residuals),
    )


def not_evaluable_risk_result(
    run_result: Any, served_forecast: Any, residuals: Sequence[float]
) -> Any:
    """A `RiskResult` whose band edges the Phase 6 classifier cannot interpret.

    Produces `evaluation_state == 'not_evaluable'`: a probability was computed but
    no band could be assigned, which is the state Phase 7 must not read as a level.
    """
    policy = RiskPolicy(
        flood_threshold=3.5,
        threshold_source=DEMO_THRESHOLD_SOURCE,
        policy_status="pending",
        band_edges=(0.1, 0.3),
        band_labels=BAND_LABELS,
    )
    return assess_risk_safe(
        served_forecast,
        config=RiskConfiguration(policy=policy, rules=()),
        context=full_context(served_forecast.inference.entity, run_result.origin),
        residuals=list(residuals),
    )


def _measured_sigma(residual_values: Sequence[float]) -> float:
    """Phase 6's measured spread, measured the same way Phase 6 measures it."""
    import statistics

    return statistics.stdev(residual_values)


# --------------------------------------------------------------------------- #
# Response contexts
# --------------------------------------------------------------------------- #


def response_context(risk_result: Any, **kwargs: Any) -> ResponseContext:
    """Project a real `RiskResult` onto a `ResponseContext`."""
    return ResponseContext.from_risk_result(risk_result, **kwargs)


def context_with_exposure(
    risk_result: Any,
    *exposures: ExposureAvailability,
) -> ResponseContext:
    """A context whose exposure records are supplied explicitly, in kind order."""
    return ResponseContext.from_risk_result(risk_result, exposure=exposures)


def available_population() -> ExposureAvailability:
    """A population record that is available.

    Note that no count is supplied, and none can be. Phase 7 records the
    availability of exposure and nothing else.
    """
    return available_exposure("population", source="fixture-exposure-adapter")


def unavailable_population(
    reason: str = NOT_AVAILABLE,
) -> ExposureAvailability:
    return unavailable_exposure("population", "unavailable", reason=reason)


def missing_infrastructure(
    reason: str = "the caller had no asset register",
) -> ExposureAvailability:
    return unavailable_exposure("infrastructure", "missing", reason=reason, source="caller")


def stale_infrastructure() -> ExposureAvailability:
    return unavailable_exposure(
        "infrastructure",
        "stale",
        reason="the asset register predates the most recent survey",
        source="fixture-exposure-adapter",
    )


def not_applicable_population() -> ExposureAvailability:
    return unavailable_exposure(
        "population",
        "not_applicable",
        reason="no reachable population is defined for this entity",
        source="fixture-exposure-adapter",
    )


def all_unusable_exposure() -> tuple[ExposureAvailability, ...]:
    """Population and infrastructure, both unusable in different ways.

    Used to prove that distinct unusable states are all recorded rather than all
    being read as zero, and that none of them changes a response category.
    """
    return (missing_infrastructure(), unavailable_population())


# --------------------------------------------------------------------------- #
# Pytest fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def forecast_band():
    """Build a real Phase 6 result at a named band."""

    def _band(band: str, *, context: Any = None, status: str = "pending") -> Any:
        return risk_result_for_band(
            shared_run(),
            shared_served(),
            shared_residuals(),
            band,
            context=context,
            status=status,
        )

    return _band


@pytest.fixture(scope="module")
def low_risk():
    """A real Phase 6 result in the LOW band."""
    return risk_result_for_band(shared_run(), shared_served(), shared_residuals(), "LOW")


@pytest.fixture(scope="module")
def medium_risk():
    """A real Phase 6 result in the MEDIUM band."""
    return risk_result_for_band(shared_run(), shared_served(), shared_residuals(), "MEDIUM")


@pytest.fixture(scope="module")
def high_risk():
    """A real Phase 6 result in the HIGH band."""
    return risk_result_for_band(shared_run(), shared_served(), shared_residuals(), "HIGH")


@pytest.fixture(scope="module")
def critical_risk():
    """A real Phase 6 result in the CRITICAL band."""
    return risk_result_for_band(shared_run(), shared_served(), shared_residuals(), "CRITICAL")


@pytest.fixture(scope="module")
def risk_withheld():
    """A Phase 6 result withheld for want of a configured threshold."""
    return withheld_risk_result(shared_run(), shared_served())


@pytest.fixture(scope="module")
def risk_context_unavailable():
    """A Phase 6 result whose context could not be read at all."""
    return context_unavailable_risk_result(
        shared_run(), shared_served(), shared_residuals()
    )


@pytest.fixture(scope="module")
def risk_not_evaluable():
    """A Phase 6 result with no assignable band."""
    return not_evaluable_risk_result(shared_run(), shared_served(), shared_residuals())


@pytest.fixture(scope="module")
def run_result():
    """The shared Phase 5 run, for a test that needs to build its own risk result."""
    return shared_run()


@pytest.fixture(scope="module")
def served_forecast():
    """The shared Phase 5 served forecast."""
    return shared_served()


@pytest.fixture(scope="module")
def shared_residual_values():
    """The shared measured residuals."""
    return shared_residuals()


@pytest.fixture
def demo_policy():
    """The DEMO response policy."""
    return demo_response_policy()


@pytest.fixture
def demo_context(medium_risk):
    """A `ResponseContext` over a real MEDIUM risk result."""
    return response_context(medium_risk)


__all__ = [
    "BAND_LABELS",
    "BAND_PROBABILITY",
    "DEMO_RESPONSE_MAPPING",
    "DEMO_RESPONSE_SOURCE",
    "DEMO_THRESHOLD_SOURCE",
    "NOT_AVAILABLE",
    "RISK_FAMILY",
    "SYNTHETIC_DATA_DISCLAIMER",
    "all_unusable_exposure",
    "available_exposure",
    "available_population",
    "baseline_served",
    "context_unavailable_risk_result",
    "context_with_exposure",
    "critical_risk",
    "dataset",
    "demo_context",
    "demo_policy",
    "demo_response_policy",
    "demo_rule",
    "empty_context",
    "estimators",
    "forecast_band",
    "full_context",
    "future_context",
    "high_risk",
    "low_risk",
    "measured_test_residuals",
    "medium_risk",
    "missing_infrastructure",
    "not_applicable_population",
    "not_evaluable_risk_result",
    "origin",
    "partial_context",
    "partial_mapping_policy",
    "phase5_run",
    "rainfall_rule",
    "residuals",
    "response_context",
    "risk_config",
    "risk_context_unavailable",
    "risk_not_evaluable",
    "risk_result_for_band",
    "risk_result_for_probability",
    "risk_withheld",
    "run_result",
    "serve_for",
    "served_forecast",
    "shared_residual_values",
    "shared_residuals",
    "shared_run",
    "shared_served",
    "served",
    "sigma",
    "spatial_context",
    "stale_context",
    "stale_infrastructure",
    "station_a",
    "station_b",
    "store",
    "threshold_for_band",
    "threshold_for_probability",
    "unavailable_exposure",
    "unavailable_population",
    "withheld_risk_result",
]