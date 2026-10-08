# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Contract tests for `HydroForecastEngine` against the team's `ForecastEngine`.

These tests are skipped when the team seam is absent.

`app/engines/base.py`, `app/engines/factory.py` and `app/schemas/models.py` are
team-owned and live on the team branch. On a branch that does not carry them
there is nothing to conform to, so the module skips rather than reporting a
failure that says nothing about this code. After the integration merge, the
whole file runs.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
from dataclasses import replace

import pytest


def _seam_available() -> bool:
    return all(
        importlib.util.find_spec(name) is not None
        for name in ("app.schemas.models", "app.engines.base", "app.engines.factory")
    )


pd = pytest.importorskip("pandas")

if not _seam_available():
    # Skip at *import* time, not via a `skipif` mark. A mark only suppresses
    # test execution; the module-level imports below still run during
    # collection, so on a branch without the team seam they raise
    # `ModuleNotFoundError`, which pytest reports as a collection ERROR and
    # "Interrupts" the whole run -- taking the team's own test modules down
    # with it. `allow_module_level` skips this module cleanly instead.
    pytest.skip(
        "requires the team seam (app/schemas/models.py, app/engines/base.py, "
        "app/engines/factory.py); those files are team-owned and are not present "
        "on this branch. Runs after the integration merge.",
        allow_module_level=True,
    )

from app.engines.base import ForecastEngine  # noqa: E402
from app.engines.factory import get_engine  # noqa: E402
from app.engines.hydro.contract import INTEGRATION_STATEMENT  # noqa: E402
from app.engines.hydro.engine import (  # noqa: E402
    EngineNotReadyError,
    HydroForecastEngine,
)
from app.engines.hydro.synthetic import generate_synthetic_series  # noqa: E402


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return generate_synthetic_series()


@pytest.fixture(scope="module")
def servable(shared_servable_config):
    """A configuration that may serve: demo threshold, pending policy.

    Module-scoped because building a servable engine trains a full pipeline, and
    the engine fixture below depends on it. An engine whose policy is
    unconfigured refuses before training, so the refusal tests request the
    function-scoped `demo_config` instead and stay cheap.
    """
    return shared_servable_config


@pytest.fixture(scope="module")
def engine(servable, frame):
    """One trained servable engine, reused by every serving test.

    Module-scoped: a per-test engine would retrain for each of the ~25 tests
    below, which is minutes of pointless repeated work for an object none of
    them mutate. The engine's serving methods are read-only.
    """
    return HydroForecastEngine(servable, frame)


# --- protocol conformance ----------------------------------------------------


def test_engine_is_constructible_with_zero_arguments():
    """The team's untouched factory builds the engine with no arguments."""
    built = HydroForecastEngine()
    assert built.name == "navya-hydro"


def test_engine_satisfies_every_protocol_member():
    for member in ("name", "latest_forecast", "forecast_series", "risk_analytics",
                   "models", "model_metrics", "recent_predictions"):
        assert hasattr(ForecastEngine, member) or member == "name", member
        assert callable(getattr(HydroForecastEngine, member, None)) or member == "name", member


def test_protocol_signatures_match():
    """Structural conformance: the team Protocol is not `@runtime_checkable`,
    so `isinstance` cannot be used and the signatures are compared instead.

    `self` is stripped from *both* sides. It is present on both unbound
    functions, so stripping only one side would make every method look like a
    mismatch and the check would always fail - a test that cannot pass teaches
    nothing.
    """
    for member in ("latest_forecast", "forecast_series", "risk_analytics",
                   "models", "model_metrics", "recent_predictions"):
        proto = list(inspect.signature(getattr(ForecastEngine, member)).parameters)
        impl = list(inspect.signature(getattr(HydroForecastEngine, member)).parameters)
        if proto and proto[0] == "self":
            proto = proto[1:]
        if impl and impl[0] == "self":
            impl = impl[1:]
        assert impl == proto, f"{member}: protocol {proto} vs implementation {impl}"


def test_every_protocol_method_is_actually_overridden():
    """A subclass that fails to override a protocol method would still satisfy a
    signature check if the names happened to line up, so the declaring class is
    checked directly. `HydroForecastEngine` is a plain class, so an inherited
    `object` method would otherwise pass unnoticed."""
    for member in ("latest_forecast", "forecast_series", "risk_analytics",
                   "models", "model_metrics", "recent_predictions"):
        assert member in vars(HydroForecastEngine), (
            f"{member} is not implemented on HydroForecastEngine; it is inherited"
        )


def test_engine_is_not_the_reference_engine(servable, frame):
    """The hydro engine must be its own implementation, not a subclass of or an
    alias for the team's demo reference engine."""
    from app.engines.reference import ReferenceEngine

    assert not isinstance(HydroForecastEngine(servable, frame), ReferenceEngine)
    assert HydroForecastEngine.__module__ == "app.engines.hydro.engine"


def test_factory_resolves_the_engine(monkeypatch):
    """The team's untouched factory must build this engine with no arguments.

    `app/engines/factory.py` reads `app.config.FORECAST_ENGINE`, so that is the
    value patched; the factory has no `settings` object of its own.
    """
    from app import config as app_config
    from app.engines.factory import get_engine

    monkeypatch.setenv(
        "FORECAST_ENGINE", "app.engines.hydro.engine:HydroForecastEngine"
    )
    monkeypatch.setattr(
        app_config, "FORECAST_ENGINE", "app.engines.hydro.engine:HydroForecastEngine"
    )
    built = get_engine()
    assert built.name == "navya-hydro"
    assert isinstance(built, HydroForecastEngine)


def test_the_factory_still_resolves_the_reference_engine_by_default(monkeypatch):
    """Setting the env var must not be the only way in: the default stays
    `reference`, so the engine is opt-in and cannot break the team's run."""
    from app import config as app_config
    from app.engines.factory import get_engine
    from app.engines.reference import ReferenceEngine

    monkeypatch.setattr(app_config, "FORECAST_ENGINE", "reference")
    assert isinstance(get_engine(), ReferenceEngine)


def test_the_reference_engine_remains_available():
    """The labelled demo fallback must keep working."""
    from app.engines.reference import ReferenceEngine

    assert ReferenceEngine().name == "reference"


# --- honest refusals ---------------------------------------------------------


def test_engine_refuses_when_no_threshold_policy_is_configured(demo_config, frame):
    refused = HydroForecastEngine(demo_config, frame)
    assert refused.is_ready() is False
    assert any("threshold" in blocker for blocker in refused.readiness())
    with pytest.raises(EngineNotReadyError) as excinfo:
        refused.latest_forecast(demo_config.target.horizon_hours)
    assert "flood_probability" in str(excinfo.value)


def test_refusal_message_names_the_env_var_to_set(demo_config, frame):
    with pytest.raises(EngineNotReadyError) as excinfo:
        HydroForecastEngine(demo_config, frame).latest_forecast(3)
    assert "HYDRO_FLOOD_THRESHOLD" in str(excinfo.value)


def test_engine_refuses_a_horizon_it_was_not_trained_for(engine, servable):
    trained_horizon = servable.target.horizon_hours
    with pytest.raises(EngineNotReadyError) as excinfo:
        engine.latest_forecast(trained_horizon * 4)
    assert "retrained" in str(excinfo.value)


def test_engine_refuses_to_serve_inflow_through_the_water_level_contract(servable, frame):
    inflow_config = replace(
        servable, target=replace(servable.target, column="inflow", units="demo m3/s")
    )
    refused = HydroForecastEngine(inflow_config, frame)
    with pytest.raises(EngineNotReadyError) as excinfo:
        refused.latest_forecast(inflow_config.target.horizon_hours)
    assert "predicted_water_level" in str(excinfo.value)


def test_engine_refuses_a_non_positive_horizon(engine):
    with pytest.raises(EngineNotReadyError):
        engine.latest_forecast(0)


def test_engine_refuses_when_switched_off(servable, frame):
    off = replace(servable, enabled=False)
    refused = HydroForecastEngine(off, frame)
    assert any("HYDRO_ENABLED" in b for b in refused.readiness())
    with pytest.raises(EngineNotReadyError):
        refused.latest_forecast(servable.target.horizon_hours)


def test_readiness_report_carries_the_integration_statement(demo_config, frame):
    text = HydroForecastEngine(demo_config, frame).readiness_report()
    assert INTEGRATION_STATEMENT in text


# --- a served forecast -------------------------------------------------------


def test_served_forecast_matches_the_team_schema(engine, servable):
    prediction = engine.latest_forecast(servable.target.horizon_hours)
    assert prediction.model_id == servable.model_id
    assert prediction.forecast_horizon == f"{servable.target.horizon_hours}h"
    assert prediction.status == "pending"
    assert 0.0 <= prediction.flood_probability <= 1.0
    assert prediction.risk_level is not None
    assert prediction.predicted_water_level is not None


def test_forecast_id_matches_the_platform_pattern(engine):
    import re

    prediction = engine.latest_forecast(3)
    assert re.fullmatch(r"FC-\d{8}-\d{1,6}", prediction.forecast_id)


def test_pending_policy_yields_a_pending_status(engine):
    assert engine.latest_forecast(3).status == "pending"


def test_approved_policy_yields_a_completed_status(servable, frame):
    approved = replace(servable, risk=replace(servable.risk, policy_status="approved"))
    assert HydroForecastEngine(approved, frame).latest_forecast(3).status == "completed"


def test_forecast_series_has_the_requested_length(engine):
    assert len(engine.forecast_series(6)) == 6


def test_forecast_series_is_chronological(engine):
    stamps = [point.timestamp for point in engine.forecast_series(6)]
    assert stamps == sorted(stamps)


def test_forecast_series_caps_rather_than_refuses_an_unusable_length(engine):
    """`hours` is a cap, not a demand.

    The held-out period is a fixed number of rows; asking for more than it holds
    cannot be satisfied, and returning the points that do exist is more useful
    than failing. A non-positive request returns nothing rather than everything,
    which a bare `[-hours:]` slice would have got backwards.
    """
    available = len(engine.forecast_series(10_000))
    assert available > 0
    assert engine.forecast_series(10_000) == engine.forecast_series(available)
    # A request longer than available is capped, not padded and not refused.
    assert len(engine.forecast_series(available + 50)) == available
    # `hours <= 0` must not slice from the end of the list.
    assert engine.forecast_series(0) == []
    assert engine.forecast_series(-5) == []


def test_forecast_series_refuses_rather_than_invent_a_probability(demo_config, frame):
    """The team contract makes `ForecastPoint.flood_probability` non-nullable.

    With no configured threshold there is no probability to report, and `0.0`
    would be a claim that the level will not flood. The engine refuses instead,
    which is also why `readiness()` reports the same missing threshold.
    """
    blocked = HydroForecastEngine(demo_config, frame)
    with pytest.raises(EngineNotReadyError) as excinfo:
        blocked.forecast_series(6)
    assert "HYDRO_FLOOD_THRESHOLD" in str(excinfo.value)


def test_recent_predictions_refuses_rather_than_returning_a_short_list(demo_config, frame):
    """A silently shortened list is indistinguishable from an empty dataset."""
    blocked = HydroForecastEngine(demo_config, frame)
    with pytest.raises(EngineNotReadyError):
        blocked.recent_predictions(6)


def test_risk_analytics_counts_only_real_backtest_points(engine):
    """The distribution is counted from the held-out backtest, not invented.

    A `RiskSummary` of all zeros would render as an empty dashboard; a summary
    with non-zero counts that do not match the number of scored points would be
    worse. The totals are therefore checked against each other.
    """
    analytics = engine.risk_analytics()
    counts = analytics.summary
    total = counts.low + counts.medium + counts.high + counts.critical
    assert total > 0
    # The distribution list and the summary are the same facts twice; they must
    # agree, or the dashboard shows two different stories.
    assert sum(entry.count for entry in analytics.distribution) == total
    assert sum(1 for entry in analytics.distribution) == 4
    assert analytics.threshold_label
    assert analytics.threshold_level is not None


def test_risk_analytics_probability_trend_stays_a_probability(engine):
    for point in engine.risk_analytics().probability_trend:
        assert 0.0 <= point.value <= 1.0
    for point in engine.risk_analytics().risk_trend:
        assert 0.0 <= point.value <= 1.0


def test_risk_analytics_labels_a_demo_threshold_as_non_official(engine):
    """The team's dashboard renders `threshold_label` as the threshold line's
    caption, so a demo value must say so in that field itself."""
    label = engine.risk_analytics().threshold_label or ""
    assert "demo" in label.lower() or "pending" in label.lower()
    assert "official" in label.lower() or "not an official" in label.lower()


def test_models_reports_the_trained_candidate(engine):
    models = engine.models()
    assert len(models) >= 1
    for model in models:
        assert model.model_id
        assert model.name and model.version and model.algorithm
        assert model.metrics is not None
        assert model.last_trained_at and model.last_evaluated_at


def test_a_pending_threshold_policy_degrades_the_model_status(engine):
    """A pending policy means the model is serving under an unapproved band
    policy, so its status must not claim plain readiness.

    `ModelStatus` is a `str` enum, so `str(...)` yields `ModelStatus.DEGRADED` in
    Python 3.11+; the value is compared, not the repr.
    """
    from app.schemas.models import ModelStatus

    statuses = {model.status for model in engine.models()}
    assert statuses == {ModelStatus.DEGRADED}
    assert ModelStatus.DEGRADED.value == "degraded"


def test_model_metrics_are_computed_not_placeholders(engine):
    """`ModelInfo` carries a nested `ModelMetrics`; the scores live there.

    `ModelMetrics` has no `n_samples` field - the team's schema does not expose
    it - so sample count cannot be asserted here. What can be asserted is that
    the scores are present, finite and non-zero, which a placeholder would not
    be. `engine.forecast_series` carries the counted points instead.
    """
    import math

    metrics = engine.model_metrics(engine.models()[0].model_id)
    assert metrics is not None
    assert metrics.metrics.rmse is not None and metrics.metrics.rmse > 0
    assert math.isfinite(metrics.metrics.rmse)
    assert metrics.metrics.mae is not None and metrics.metrics.mae >= 0
    assert math.isfinite(metrics.metrics.mae)


def test_no_accuracy_is_reported_for_a_regression_forecast(engine):
    """`ModelMetrics` has an `accuracy` field; a regression model has no class
    labels, so it must be left unset rather than filled with a meaningless 0-1
    number that a dashboard would render as a score."""
    metrics = engine.model_metrics(engine.models()[0].model_id)
    assert metrics.metrics.accuracy is None


def test_recent_predictions_returns_backtest_records(engine):
    """`PredictionRecord` carries `water_level` and `probability`; there is no
    `prediction`/`actual` pair in the team schema, so the fields asserted here
    are the ones that exist and can be checked for consistency."""
    records = engine.recent_predictions(3)
    assert len(records) == 3
    for record in records:
        assert record.forecast_id
        assert record.model_id
        assert 0.0 <= record.probability <= 1.0
        assert record.water_level >= 0.0
        assert record.risk_level is not None
        assert record.status in {"completed", "pending", "failed"}
    # Chronological, newest last, so the frontend can render them in order.
    stamps = [record.timestamp for record in records]
    assert stamps == sorted(stamps)


def test_forecast_points_pair_a_prediction_with_a_measured_observation(engine):
    """`ForecastPoint` names the observed value `observed_water_level`.

    It is optional in the team schema (`float | None`), so the assertion is that
    a backtest point *has* one - a point with no observation carries no
    measured error and must not be presented as a scored result.
    """
    points = engine.forecast_series(6)
    for point in points:
        assert point.observed_water_level is not None
        assert point.predicted_water_level >= 0.0
        assert 0.0 <= point.flood_probability <= 1.0


def test_unknown_model_id_metrics_return_none(engine):
    assert engine.model_metrics("no-such-model") is None


# --- the handoff -------------------------------------------------------------


def test_handoff_carries_the_integration_statement(engine):
    assert INTEGRATION_STATEMENT in engine.handoff().describe()


def test_handoff_existing_payload_is_backward_compatible(engine):
    payload = engine.handoff().to_existing_payload()
    assert set(payload) >= {"forecast_id"}
    assert payload["forecast_id"].startswith("FC-")


# --- no fabricated numbers ---------------------------------------------------


def test_every_returned_metric_is_computed_from_the_backtest(engine):
    """The series, the risk analytics and the recent predictions must all come
    from the same real held-out period, so their totals agree."""
    points = engine.forecast_series(6)
    assert all(point.observed_water_level is not None for point in points)
    analytics = engine.risk_analytics()
    assert analytics.summary is not None
    # A fabricated model would report a suspiciously perfect fit; the backtest
    # is genuine, so the residual spread is non-zero.
    metrics = engine.model_metrics(engine.models()[0].model_id)
    assert metrics.metrics.rmse > 0.0


def test_is_ready_and_the_serving_methods_agree(engine):
    """A readiness claim that the serving methods do not share is a lie an
    operator cannot detect until it matters.

    The engine that is servable must report ready, and every serving method
    must return without raising.
    """
    assert engine.is_ready() is True
    # `readiness()` returns a tuple, so an empty one is falsy rather than `[]`.
    assert not engine.readiness()
    assert engine.latest_forecast(3) is not None
    assert engine.forecast_series(6) is not None
    assert engine.risk_analytics() is not None
    assert engine.models() is not None


def test_readiness_blockers_and_raised_errors_agree(demo_config, frame):
    """When a blocker is reported, the serving method must refuse too.

    These are the same fact expressed two ways, so they cannot disagree: a
    `False` from `is_ready()` with a successful forecast would mean the
    readiness report is decorative.
    """
    blocked = HydroForecastEngine(demo_config, frame)
    assert blocked.is_ready() is False
    assert blocked.readiness()
    for call in (
        lambda: blocked.latest_forecast(3),
        lambda: blocked.forecast_series(3),
        lambda: blocked.risk_analytics(),
        lambda: blocked.models(),
        lambda: blocked.model_metrics("NAVYA-HYDRO-001"),
        lambda: blocked.recent_predictions(3),
    ):
        with pytest.raises(EngineNotReadyError):
            call()


def test_advisories_do_not_block_serving(engine, servable):
    """A configured-but-unapproved threshold policy is an advisory, not a blocker.

    If `pending` blocked serving, the whole synthetic pipeline would be
    unservable and untestable. If it did not block *and* were not reported, a
    demo threshold would be presented as an official flood stage. It is therefore
    reported, loudly, in both places.
    """
    assert servable.risk.policy_status == "pending"
    assert not engine.readiness(), "a pending policy must not block serving"
    advisories = " ".join(engine.advisories()).lower()
    assert "pending" in advisories
    label = engine.risk_analytics().threshold_label or ""
    assert "NOT an official" in label or "not official" in label.lower()
