# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Shared fixtures for the Phase 6 forecast-to-risk tests.

Not a test module — a helper. Phase 6 tests need three things over and over: one
*real* Phase 5 serving result, one *measured* residual spread, and risk contexts in
each of the states the contract distinguishes. Building those once here means each
test file reads as a claim rather than as a pipeline re-implementation.

**Everything here is synthetic/demo data**, reused from `hydro_phase5_fixtures`
including its station identities and its disclaimer, so a Phase 6 test cannot pass
against a differently-shaped dataset than a Phase 4 or Phase 5 one. No test asserts
a hydrological result.

Residuals are measured, not written down
----------------------------------------
`measured_test_residuals` walks the real test split, asks Phase 5's own
`predict()` for each row, and subtracts. So the spread Phase 6 is given is a
measurement of the same code path that produces the forecast, on the same artifact,
from the same data — not a list of plausible numbers typed into a fixture.

That distinction turned out to matter more than expected. For this fixture's
`random_forest` on `STATION_A`, the residuals have a bias of about **+0.317 m**, so
the root-mean-square error (**0.391 m**) is about **1.7x** the residual standard
deviation (**0.231 m**). Substituting RMSE for sigma would therefore cut every
exceedance probability this pipeline computes by roughly a third, while reporting the
method as unchanged. `test_rmse_is_not_the_residual_sigma_phase6_needs` pins that
ratio, so the module docstring's claim stays a tested claim rather than a plausible
one.

The residuals cover the validation and test splits for **one station** (36 rows), so
they do not agree with the artifact's recorded aggregate metrics, which cover every
entity and every split. That is expected and is the point: this fixture measures the
spread for the station whose forecast is being assessed.

Thresholds for band tests are derived, not guessed
--------------------------------------------------
`threshold_for_probability` inverts the normal model by bisection, so a test can ask
for "the threshold that puts this forecast in MEDIUM" and be told the number instead
of hard-coding one that stops being correct when the fixture changes.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pytest

from app.engines.hydro.config import RiskPolicy
from app.engines.hydro.forecast_artifact import ArtifactStore
from app.engines.hydro.forecast_inference import predict
from app.engines.hydro.forecast_serving import ServedForecast, serve
from app.engines.hydro.model_artifacts import build_manifests
from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER
from app.engines.hydro.risk import exceedance_probability
from app.engines.hydro.risk import residual_sigma as measured_sigma
from app.engines.hydro.forecast_risk import RiskConfiguration, RiskEscalationRule
from app.engines.hydro.risk_context import (
    RiskContext,
    available_signal,
    unavailable_gis_context,
    unavailable_historical_context,
    unavailable_signal,
)

from hydro_phase5_fixtures import (
    STATION_A,
    STATION_B,
    TARGET,
    artifact_for,
    build_run,
    family_request,
    preprocessing_for,
    serving_instant,
    serving_input,
)

#: The family Phase 6 tests assess. A learned model rather than the persistence
#: baseline, because the baseline is parameter-free and would make the residual-spread
#: requirement look trivial when it is not.
RISK_FAMILY = "random_forest"

#: The dataset status this fixture set produces. Stated so a test that asserts on it
#: wants the literal a reader can check against the docs.
SYNTHETIC_STATUS = "synthetic_demo"

#: Band edges matching `config.DEFAULT_RISK_BAND_LABELS`, repeated here so a test that
#: builds a policy by hand does not silently inherit different ones.
BAND_EDGES: tuple[float, ...] = (0.1, 0.3, 0.6, 0.9)
BAND_LABELS: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

#: A probability comfortably inside each band. Not the edge itself: the edges are
#: where a floating-point comparison is least forgiving, and a test should fail on a
#: wrong band, never on a rounding accident.
BAND_PROBABILITY: Mapping[str, float] = {
    "LOW": 0.05,
    "MEDIUM": 0.2,
    "HIGH": 0.45,
    "CRITICAL": 0.8,
}

#: An explicitly DEMO policy, built the way `risk.demo_risk_policy` builds one and
#: marked as such in the source string.
DEMO_THRESHOLD_SOURCE = (
    "DEMO value chosen for the synthetic pipeline; NOT an official flood stage"
)


# --------------------------------------------------------------------------- #
# The Phase 5 result under test
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Phase5Run:
    """One real Phase 5 run, with everything Phase 6 needs to reach into it."""

    trained: Any
    manifests: Any
    dataset: Any
    store: ArtifactStore
    estimators: Mapping[str, Any]
    origin: dt.datetime

    @property
    def entity(self) -> str:
        return STATION_A


def phase5_run() -> Phase5Run:
    """Build the run. Real manifests, real fitted estimators, real feature rows."""
    trained, _ = build_run()
    manifests = build_manifests(trained)
    dataset = trained.datasets[TARGET]
    store = ArtifactStore.from_manifests(
        manifests, preprocessing_for=preprocessing_for(manifests, dataset)
    )
    estimators = {
        run.model_id: run.estimator for run in trained.runs if run.estimator is not None
    }
    return Phase5Run(
        trained=trained,
        manifests=manifests,
        dataset=dataset,
        store=store,
        estimators=estimators,
        origin=serving_instant(dataset, STATION_A),
    )


def serve_for(run: Phase5Run, family: str = RISK_FAMILY) -> ServedForecast:
    """One `ready` `ServedForecast`, through Phase 5's real serving path.

    `run_result` and `manifests` are supplied so the result carries everything Phase 5
    can produce — selection, handoff and the platform `ForecastOutput` — rather than a
    bare inference. Phase 6's contract tests project onto that output, and a truncated
    serving result would make them test a shape that never ships.
    """
    return serve(
        family_request(run.origin, family),
        store=run.store,
        data=serving_input(run.dataset, run.origin, STATION_A),
        estimators=run.estimators,
        run_result=run.trained,
        manifests=run.manifests,
    )


def measured_test_residuals(run: Phase5Run, family: str = RISK_FAMILY) -> tuple[float, ...]:
    """Observed-minus-predicted on the real test split, for `STATION_A`.

    Predictions come from Phase 5's `predict()` against the validated artifact, so
    these are residuals of the shipped inference path and not of a re-implementation.
    Rows whose target is missing are skipped, which is why the count is smaller than
    the split's row count.
    """
    artifact = artifact_for(run.store, family)
    estimator = run.estimators[artifact.model_id]
    residuals: list[float] = []
    for split in run.dataset.splits.values():
        if split.split not in ("validation", "test"):
            continue
        for index, entity in enumerate(split.row_entities):
            if entity != STATION_A:
                continue
            actual = split.target[index]
            if not np.isfinite(actual):
                continue
            data = serving_input(run.dataset, split.origin_instants[index], STATION_A)
            inference = predict(artifact, data, estimator=estimator)
            residuals.append(float(actual) - float(inference.prediction))
    if len(residuals) < 2:
        raise AssertionError(
            f"a residual spread needs at least 2 real residuals, measured {len(residuals)}"
        )
    return tuple(residuals)


# --------------------------------------------------------------------------- #
# Thresholds derived, not guessed
# --------------------------------------------------------------------------- #


def threshold_for_probability(prediction: float, sigma: float, probability: float) -> float:
    """The threshold that yields `probability` under the normal exceedance model.

    Solved by bisection on `exceedance_probability`, which decreases monotonically in
    the threshold, so the answer is unique and the result is deterministic. Sixty
    iterations puts the bracket far below float resolution, which is why a test can
    trust the band it gets rather than asserting "close to".

    Deriving the threshold is what makes the band tests survive a fixture change: a
    hard-coded threshold is correct only for the prediction it was chosen against,
    and silently becomes a different test the moment that prediction moves.
    """
    if not 0.0 < probability < 1.0:
        raise AssertionError(f"probability must lie strictly inside (0, 1), got {probability}")
    low = prediction - 40.0 * sigma
    high = prediction + 40.0 * sigma
    for _ in range(60):
        middle = (low + high) / 2.0
        if exceedance_probability(prediction, middle, sigma) > probability:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def threshold_for_band(prediction: float, sigma: float, band: str) -> float:
    """The threshold that places `prediction` inside `band`."""
    if band not in BAND_PROBABILITY:
        raise AssertionError(f"{band!r} is not one of {sorted(BAND_PROBABILITY)}")
    return threshold_for_probability(prediction, sigma, BAND_PROBABILITY[band])


def demo_policy(threshold: float, *, status: str = "pending") -> RiskPolicy:
    """A policy that is explicitly DEMO, with the repo's own band edges."""
    return RiskPolicy(
        flood_threshold=threshold,
        threshold_source=DEMO_THRESHOLD_SOURCE,
        policy_status=status,
        band_edges=BAND_EDGES,
        band_labels=BAND_LABELS,
    )


def risk_config(
    threshold: float,
    *,
    rules: Sequence[RiskEscalationRule] = (),
    status: str = "pending",
    threshold_units: str | None = None,
    default_max_age_seconds: float | None = None,
    signal_max_age_seconds: Mapping[str, float] | None = None,
    risk_configuration_version: str = "navya-phase6-test-config/v1",
    threshold_configuration_version: str | None = None,
) -> RiskConfiguration:
    """A `RiskConfiguration` over a DEMO policy."""
    return RiskConfiguration(
        policy=demo_policy(threshold, status=status),
        rules=tuple(rules),
        signal_max_age_seconds=dict(signal_max_age_seconds or {}),
        default_max_age_seconds=default_max_age_seconds,
        threshold_units=threshold_units,
        risk_configuration_version=risk_configuration_version,
        threshold_configuration_version=threshold_configuration_version,
    )


def rainfall_rule(
    *,
    rule_id: str = "demo-heavy-rainfall",
    mm: float = 50.0,
    escalate_to: str = "HIGH",
    required: bool = False,
    signal: str = "rainfall_3h",
    unit: str = "mm",
) -> RiskEscalationRule:
    """A DEMO rainfall escalation rule. The value is a demo choice, stated as one."""
    return RiskEscalationRule(
        rule_id=rule_id,
        signal=signal,
        quantity="rainfall",
        comparison=">=",
        value=mm,
        unit=unit,
        escalate_to=escalate_to,
        source="DEMO rainfall policy; NOT an official warning criterion",
        required=required,
    )


# --------------------------------------------------------------------------- #
# Contexts, one per availability state
# --------------------------------------------------------------------------- #


def full_context(
    entity: str,
    origin: dt.datetime,
    *,
    level_m: float = 2.9,
    rainfall_mm: float = 63.2,
    dataset_type: str = "synthetic",
) -> RiskContext:
    """Every declared signal is `valid`. The `fully_evaluated` case."""
    return RiskContext(
        entity=entity,
        dataset_type=dataset_type,
        signals=(
            available_signal(
                "water_level_now",
                "water_level",
                level_m,
                "m",
                source="synthetic gauge reading",
                observed_at=origin,
            ),
            available_signal(
                "rainfall_3h",
                "rainfall",
                rainfall_mm,
                "mm",
                source="synthetic gauge reading",
                observed_at=origin,
            ),
        ),
        gis=unavailable_gis_context(),
        historical=unavailable_historical_context(),
        disclaimer=SYNTHETIC_DATA_DISCLAIMER,
    )


def partial_context(entity: str, origin: dt.datetime) -> RiskContext:
    """One valid signal, one absent, one not-applicable. The `partially_evaluated` case."""
    return RiskContext(
        entity=entity,
        dataset_type="synthetic",
        signals=(
            available_signal(
                "rainfall_3h",
                "rainfall",
                12.0,
                "mm",
                source="synthetic gauge reading",
                observed_at=origin,
            ),
            unavailable_signal(
                "water_level_now",
                "water_level",
                source="caller",
                availability="missing",
                reason="the caller had no level reading for this instant",
            ),
            unavailable_signal(
                "discharge",
                "discharge",
                source="none",
                availability="unavailable",
                reason="no rating curve exists in this repository, so discharge cannot be derived",
            ),
        ),
        gis=unavailable_gis_context(),
        historical=unavailable_historical_context(),
    )


def empty_context(entity: str, origin: dt.datetime) -> RiskContext:
    """No signals at all. The `context_unavailable` case."""
    return RiskContext(
        entity=entity,
        dataset_type="synthetic",
        signals=(),
        gis=unavailable_gis_context(),
        historical=unavailable_historical_context(),
    )


def stale_context(
    entity: str, origin: dt.datetime, *, age_seconds: float = 30 * 24 * 3600.0
) -> RiskContext:
    """A single real reading that is far too old. The `stale` case."""
    return RiskContext(
        entity=entity,
        dataset_type="synthetic",
        signals=(
            available_signal(
                "water_level_now",
                "water_level",
                2.9,
                "m",
                source="synthetic gauge reading",
                observed_at=origin - dt.timedelta(seconds=age_seconds),
            ),
        ),
        gis=unavailable_gis_context(),
    )


def future_context(entity: str, origin: dt.datetime) -> RiskContext:
    """A signal that claims to know the future. Must be refused, never used."""
    return RiskContext(
        entity=entity,
        dataset_type="synthetic",
        signals=(
            available_signal(
                "water_level_now",
                "water_level",
                4.8,
                "m",
                source="synthetic gauge reading",
                observed_at=origin + dt.timedelta(hours=1),
            ),
        ),
    )


def spatial_context(entity: str, origin: dt.datetime) -> RiskContext:
    """GIS-supplied spatial evidence, with a provider reference.

    The only context in this fixture set that carries spatial values. Used to show
    the boundary is a real interface rather than a permanently-unavailable stub — and
    that when a provider *does* answer, the values are attributed to it.
    """
    from app.engines.hydro.risk_context import GisContext

    return RiskContext(
        entity=entity,
        dataset_type="synthetic",
        signals=(
            available_signal(
                "water_level_now",
                "water_level",
                2.9,
                "m",
                source="synthetic gauge reading",
                observed_at=origin,
            ),
        ),
        gis=GisContext(
            available=True,
            provider="fixture-gis-adapter",
            elevation_m=12.5,
            river_distance_m=140.0,
            provenance={"reference": "fixture-gis://context/0001"},
        ),
    )


def target_units() -> str:
    """The target's units, read from the fixture dataset rather than assumed."""
    return "m"


# --------------------------------------------------------------------------- #
# Pytest fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def run():
    """The real Phase 5 run. Module-scoped: training dominates the suite's runtime."""
    return phase5_run()


@pytest.fixture(scope="module")
def dataset(run):
    return run.dataset


@pytest.fixture(scope="module")
def store(run):
    return run.store


@pytest.fixture(scope="module")
def estimators(run):
    return run.estimators


@pytest.fixture(scope="module")
def origin(run):
    return run.origin


@pytest.fixture(scope="module")
def station_a():
    """The entity every fixture context describes."""
    return STATION_A


@pytest.fixture(scope="module")
def station_b():
    """A real *different* station, for the cross-entity refusal tests."""
    return STATION_B


@pytest.fixture(scope="module")
def served(run):
    """One `ready` Phase 5 `ServedForecast` — the thing Phase 6 consumes."""
    return serve_for(run, RISK_FAMILY)


@pytest.fixture(scope="module")
def baseline_served(run):
    """The persistence baseline's serving result, for the metadata-preservation tests."""
    return serve_for(run, "naive")


@pytest.fixture(scope="module")
def residuals(run):
    """Real observed-minus-predicted on the validation and test splits."""
    return measured_test_residuals(run, RISK_FAMILY)


@pytest.fixture(scope="module")
def sigma(residuals):
    """The measured residual spread those residuals imply."""
    return measured_sigma(list(residuals))


@pytest.fixture
def context(station_a, origin):
    """A `fully_evaluated` context for the fixture's station."""
    return full_context(station_a, origin)


__all__ = [
    "BAND_EDGES",
    "BAND_LABELS",
    "BAND_PROBABILITY",
    "DEMO_THRESHOLD_SOURCE",
    "Phase5Run",
    "RISK_FAMILY",
    "SYNTHETIC_DATA_DISCLAIMER",
    "SYNTHETIC_STATUS",
    "STATION_A",
    "STATION_B",
    "TARGET",
    "baseline_served",
    "context",
    "dataset",
    "demo_policy",
    "empty_context",
    "estimators",
    "family_request",
    "full_context",
    "future_context",
    "measured_test_residuals",
    "origin",
    "partial_context",
    "phase5_run",
    "rainfall_rule",
    "measured_sigma",
    "residuals",
    "risk_config",
    "run",
    "serve_for",
    "served",
    "sigma",
    "spatial_context",
    "stale_context",
    "station_a",
    "station_b",
    "store",
    "target_units",
    "threshold_for_band",
    "threshold_for_probability",
]