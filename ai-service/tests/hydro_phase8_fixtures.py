# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Shared fixtures for the Phase 8 forecast -> risk -> response integration tests.

Not a test module — a helper. Phase 8 needs one fully-built chain per integration
state, and a full chain is three objects deep: a served forecast, a risk assessment
and a response decision, each produced by the layer that owns it.

**Everything here is synthetic/demo data**, carried through the Phase 5, 6 and 7
fixtures including their station identities and their disclaimer. No Phase 8 test
asserts a hydrological result; they assert that the integration layer reports what
the three layers below it produced, and reports nothing else.

Nothing is assembled by hand
----------------------------

There is no fixture that builds a `ServedForecast`, a `RiskResult` or a
`ResponseDecision` field by field. Every layer result comes from calling the real
Phase 5 `serve`, the real Phase 6 `assess_risk` and the real Phase 7
`decide_response`. A hand-built stand-in would let a Phase 8 test pass against an
object shape the repository never produces, which is exactly the kind of green that
turns out to mean nothing.

The one thing Phase 8 adds on top is exposure availability, and that is a
*declaration* rather than a value: `complete_exposure()` returns two
`ExposureAvailability` records with no counts, because Phase 7 has nowhere to put a
count and Phase 8 does not add a field for one.

Why COMPLETE needs a caller-supplied provider
---------------------------------------------

This repository has no population provider and no infrastructure provider. So a
chain built from repository data alone always carries two unusable exposure records
and tops out at `PARTIAL` — which is the honest result, and is asserted as such by
`test_repository_data_alone_never_reaches_complete`.

`complete_exposure()` lets a test declare both providers supplied so the `COMPLETE`
branch is reachable at all. That is a claim the *caller* makes and owns; the fixture
labels its source `demo-exposure-adapter` so it cannot be mistaken for a real
provider, and the resulting record still carries `synthetic_demo=True`.

Nothing here is cached across modules
-------------------------------------

Every helper builds its own `RiskResult` and `ResponseDecision` through the real
factory functions, and the module-level `integrate_*` helpers memoize the *integrated*
records so the immutable-snapshot and determinism tests can compare them cheaply. A
fresh chain per test would cost a Phase 6 assessment each time; the assessment is
deterministic, so one shared instance is the same object with the same contents.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Any, Mapping, Sequence

import pytest

from app.engines.hydro.config import RiskPolicy
from app.engines.hydro.forecast_risk import (
    MissingForecastError,
    RiskConfiguration,
    risk_from_error,
)
from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER
from app.engines.hydro.response_context import (
    ExposureAvailability,
    ResponseContext,
    available_exposure,
)
from app.engines.hydro.response_decision import (
    ResponseDecision,
    ResponsePolicy,
    decide_response,
)

from hydro_phase5_fixtures import STATION_A, STATION_B
from hydro_phase7_fixtures import (  # noqa: F401  - re-exported for the phase 8 modules
    BAND_LABELS,
    BAND_PROBABILITY,
    DEMO_RESPONSE_MAPPING,
    DEMO_RESPONSE_SOURCE,
    DEMO_THRESHOLD_SOURCE,
    NOT_AVAILABLE,
    RISK_FAMILY,
    all_unusable_exposure,
    available_population,
    baseline_served,
    context_unavailable_risk_result,
    context_with_exposure,
    critical_risk,
    dataset,
    demo_context,
    demo_policy,
    demo_response_policy,
    demo_rule,
    empty_context,
    estimators,
    forecast_band,
    full_context,
    future_context,
    high_risk,
    low_risk,
    measured_test_residuals,
    medium_risk,
    missing_infrastructure,
    not_applicable_population,
    not_evaluable_risk_result,
    origin,
    partial_context,
    partial_mapping_policy,
    phase5_run,
    rainfall_rule,
    residuals,
    response_context,
    risk_config,
    risk_context_unavailable,
    risk_not_evaluable,
    risk_result_for_band,
    risk_result_for_probability,
    risk_withheld,
    run_result,
    serve_for,
    served,
    served_forecast,
    shared_residual_values,
    shared_residuals,
    shared_run,
    shared_served,
    sigma,
    spatial_context,
    stale_context,
    stale_infrastructure,
    station_a,
    station_b,
    store,
    threshold_for_band,
    threshold_for_probability,
    unavailable_population,
    withheld_risk_result,
)

#: The family whose artifact is absent from the store, used to produce a *real*
#: Phase 5 refusal. Phase 5 refuses rather than falling back to a different model,
#: which is the whole point: the refusal is the state Phase 8 has to carry forward.
MISSING_FAMILY = "no_such_family"

#: The source string every demo exposure provider carries. There is no real provider
#: in this repository, so any available-exposure record has to say where it came from.
DEMO_EXPOSURE_SOURCE = (
    "DEMO exposure adapter declared by the test caller; this repository has no real "
    "population or infrastructure provider"
)


# --------------------------------------------------------------------------- #
# Exposure availability
# --------------------------------------------------------------------------- #


def available_infrastructure() -> ExposureAvailability:
    """An infrastructure record that is available.

    Note again that no asset count is supplied, and that none can be:
    `ExposureAvailability` has no value field. Declaring the input available is a
    statement about a provider existing, never about how much infrastructure there is.
    """
    return available_exposure("infrastructure", source=DEMO_EXPOSURE_SOURCE)


def complete_exposure() -> tuple[ExposureAvailability, ...]:
    """Both exposure kinds, both usable. The only route to `COMPLETE`.

    This is a declaration by the caller that two providers exist. It supplies no
    counts, because there is nowhere in the contract to put one and because inventing
    a population figure is precisely the fabrication this repository forbids.
    """
    return (
        available_exposure("population", source=DEMO_EXPOSURE_SOURCE),
        available_exposure("infrastructure", source=DEMO_EXPOSURE_SOURCE),
    )


def mixed_exposure() -> tuple[ExposureAvailability, ...]:
    """One usable, one not. `PARTIAL` with a named gap rather than a silent zero.

    The two records must name *different* kinds. Phase 7 refuses a pair of records
    for the same kind, and it is right to: one kind with two availability states has
    no way to choose between them, so keeping either would misreport the other. The
    fixture that proves it is `test_duplicate_exposure_kinds_are_refused_by_phase_7`.
    """
    return (available_population(), missing_infrastructure())


# --------------------------------------------------------------------------- #
# Decisions over real risk results
# --------------------------------------------------------------------------- #


def decide_for(
    risk_result: Any,
    *,
    policy: ResponsePolicy | None = None,
    exposure: Sequence[ExposureAvailability] | None = None,
    rules: Sequence[Any] = (),
) -> ResponseDecision:
    """A real Phase 7 decision over a real Phase 6 risk result.

    `exposure` is forwarded to `ResponseContext.from_risk_result` when given, so a
    test can declare provider availability and reach the `COMPLETE` branch without
    Phase 8 ever seeing a count.
    """
    context: ResponseContext = (
        ResponseContext.from_risk_result(risk_result)
        if exposure is None
        else ResponseContext.from_risk_result(risk_result, exposure=tuple(exposure))
    )
    return decide_response(
        context,
        policy=demo_response_policy() if policy is None else policy,
        rules=tuple(rules),
    )


def complete_decision(risk_result: Any, *, policy: ResponsePolicy | None = None) -> ResponseDecision:
    """A decision taken with both exposure providers declared available."""
    return decide_for(risk_result, policy=policy, exposure=complete_exposure())


# --------------------------------------------------------------------------- #
# Real chains, one per integration state
# --------------------------------------------------------------------------- #


def refused_forecast() -> Any:
    """A real Phase 5 refusal: `status='artifact_unavailable'`, no inference.

    Produced by asking Phase 5 for a family its store does not hold. Phase 5 refuses
    and says why rather than falling back to a model it was not asked for, so this is
    the genuine "forecast unavailable" state and not a synthetic stand-in for one.
    """
    return serve_for(shared_run(), MISSING_FAMILY)


def error_risk_result() -> Any:
    """A `RiskResult` built by Phase 6's own error path.

    Notable for Phase 8 because its `disclaimer` is the empty string: `risk_from_error`
    has no data to describe, and an empty string is the honest answer *there*. Phase 8
    must replace it rather than forward it, or an integration wrapping a failed risk
    assessment would read as though no synthetic-data warning were needed.
    """
    return risk_from_error(MissingForecastError("no forecast was available to assess"))


def decision_for_entity(entity: str, risk_result: Any) -> ResponseDecision:
    """A real decision re-labelled for another station.

    Used only by the entity-safety tests. Phase 6 and Phase 7 each check a request
    against their own input, but neither can see the whole chain, so neither can catch
    a decision whose entity disagrees with the forecast it is being integrated with.
    That check belongs to Phase 8 and needs a pair that individually pass and jointly
    disagree.
    """
    return dataclasses.replace(decide_for(risk_result), entity=entity)


def decision_for_forecast_id(forecast_id: str, risk_result: Any) -> ResponseDecision:
    """A real decision re-labelled with a different forecast id.

    The other half of the chain-integrity problem: two layers that agree on the
    station but describe different forecasts cannot be reported as one event.
    """
    return dataclasses.replace(decide_for(risk_result), forecast_id=forecast_id)


def decision_for_origin(origin_instant: dt.datetime, risk_result: Any) -> ResponseDecision:
    """A real decision re-labelled with a different forecast origin."""
    return dataclasses.replace(decide_for(risk_result), forecast_origin=origin_instant)


def risk_for_forecast_id(forecast_id: str, risk_result: Any) -> Any:
    """A real risk result re-labelled with a different forecast id."""
    return dataclasses.replace(risk_result, forecast_id=forecast_id)


# --------------------------------------------------------------------------- #
# Memoized integrated records
# --------------------------------------------------------------------------- #

#: Integrated records are immutable and deterministic, so building each one once and
#: handing the same instance to many tests costs nothing in coverage and a great deal
#: in runtime. The alternative - a fresh Phase 6 assessment per test - would be slower
#: and would not assert anything extra, because the chain is a pure function of the
#: three layer results.
_INTEGRATED: dict[str, Any] = {}


def integrated(key: str, builder: Any) -> Any:
    """Memoize one integrated record under `key`."""
    if key not in _INTEGRATED:
        _INTEGRATED[key] = builder()
    return _INTEGRATED[key]


# --------------------------------------------------------------------------- #
# Pytest fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def station_one() -> str:
    """The entity every fixture chain describes."""
    return STATION_A


@pytest.fixture(scope="module")
def station_two() -> str:
    """A real *different* station, for the cross-entity refusal tests."""
    return STATION_B


@pytest.fixture(scope="module")
def medium_chain():
    """A real Phase 5/6/7 chain with both exposure providers declared available."""
    return integrated(
        "complete",
        lambda: _build_complete_chain(),
    )


@pytest.fixture(scope="module")
def repository_chain():
    """A real chain built from repository data alone, with no exposure providers."""
    return integrated("partial", lambda: _build_repository_chain())


@pytest.fixture(scope="module")
def mixed_exposure_chain():
    """A chain with one usable exposure input and one not."""
    return integrated("mixed_exposure", lambda: _build_mixed_exposure_chain())


@pytest.fixture(scope="module")
def partial_context_chain():
    """A chain whose Phase 6 context was only partially evaluated."""
    return integrated("partial_context", lambda: _build_partial_context_chain())


@pytest.fixture(scope="module")
def withheld_chain():
    """A chain whose Phase 7 decision was withheld for want of a response mapping."""
    return integrated("withheld", lambda: _build_withheld_chain())


@pytest.fixture(scope="module")
def context_unavailable_chain():
    """A chain over a Phase 6 result that read no context at all."""
    return integrated("context_unavailable", lambda: _build_context_unavailable_chain())


@pytest.fixture(scope="module")
def not_evaluable_chain():
    """A chain over a Phase 6 result that recorded no level."""
    return integrated("not_evaluable", lambda: _build_not_evaluable_chain())


@pytest.fixture(scope="module")
def refused_chain():
    """A chain that begins with a real Phase 5 refusal."""
    return integrated("refused", lambda: _build_refused_chain())


@pytest.fixture(scope="module")
def empty_chain():
    """A chain with no layers at all."""
    from app.engines.hydro.integration_assessment import integrate

    return integrated("empty", lambda: integrate(None))


def _build_complete_chain() -> Any:
    from app.engines.hydro.integration_assessment import integrate

    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    return integrate(served_forecast, risk, complete_decision(risk))


def _build_repository_chain() -> Any:
    """Exactly what the repository produces on its own: no exposure provider at all."""
    from app.engines.hydro.integration_assessment import integrate

    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    return integrate(served_forecast, risk, decide_for(risk))


def _build_mixed_exposure_chain() -> Any:
    from app.engines.hydro.integration_assessment import integrate

    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    return integrate(served_forecast, risk, decide_for(risk, exposure=mixed_exposure()))


def _build_partial_context_chain() -> Any:
    from app.engines.hydro.integration_assessment import integrate

    run = shared_run()
    served_forecast = shared_served()
    risk = risk_result_for_band(
        run,
        served_forecast,
        shared_residuals(),
        "MEDIUM",
        context=partial_context(served_forecast.inference.entity, run.origin),
    )
    return integrate(served_forecast, risk, decide_for(risk, exposure=complete_exposure()))


def _build_withheld_chain() -> Any:
    from app.engines.hydro.integration_assessment import integrate

    served_forecast = shared_served()
    risk = risk_result_for_band(shared_run(), served_forecast, shared_residuals(), "MEDIUM")
    return integrate(served_forecast, risk, decide_for(risk, policy=ResponsePolicy()))


def _build_context_unavailable_chain() -> Any:
    from app.engines.hydro.integration_assessment import integrate

    risk = context_unavailable_risk_result(shared_run(), shared_served(), shared_residuals())
    return integrate(shared_served(), risk, decide_for(risk, exposure=complete_exposure()))


def _build_not_evaluable_chain() -> Any:
    from app.engines.hydro.integration_assessment import integrate

    risk = not_evaluable_risk_result(shared_run(), shared_served(), shared_residuals())
    return integrate(shared_served(), risk, decide_for(risk))


def _build_refused_chain() -> Any:
    from app.engines.hydro.integration_assessment import integrate

    return integrate(refused_forecast())


@pytest.fixture
def unconfigured_risk_config():
    """A Phase 6 configuration with no threshold, which yields a withheld result."""
    return RiskConfiguration(policy=RiskPolicy(), rules=())


__all__ = [
    "BAND_LABELS",
    "BAND_PROBABILITY",
    "DEMO_EXPOSURE_SOURCE",
    "DEMO_RESPONSE_MAPPING",
    "DEMO_RESPONSE_SOURCE",
    "DEMO_THRESHOLD_SOURCE",
    "MISSING_FAMILY",
    "NOT_AVAILABLE",
    "RISK_FAMILY",
    "STATION_A",
    "STATION_B",
    "SYNTHETIC_DATA_DISCLAIMER",
    "all_unusable_exposure",
    "available_infrastructure",
    "available_population",
    "baseline_served",
    "complete_decision",
    "complete_exposure",
    "context_unavailable_risk_result",
    "context_with_exposure",
    "decide_for",
    "decision_for_entity",
    "decision_for_forecast_id",
    "decision_for_origin",
    "demo_policy",
    "demo_response_policy",
    "demo_rule",
    "empty_context",
    "error_risk_result",
    "estimators",
    "full_context",
    "future_context",
    "integrated",
    "mixed_exposure",
    "missing_infrastructure",
    "not_applicable_population",
    "not_evaluable_risk_result",
    "origin",
    "partial_context",
    "partial_mapping_policy",
    "phase5_run",
    "rainfall_rule",
    "refused_forecast",
    "residuals",
    "response_context",
    "risk_config",
    "risk_for_forecast_id",
    "risk_result_for_band",
    "risk_result_for_probability",
    "serve_for",
    "shared_residuals",
    "shared_run",
    "shared_served",
    "sigma",
    "spatial_context",
    "stale_context",
    "stale_infrastructure",
    "store",
    "threshold_for_band",
    "threshold_for_probability",
    "unavailable_population",
]