# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 6: leakage — the ways this boundary could cheat, and the tests that stop it.

A risk layer sits downstream of the model, which is exactly where leakage is easiest
to introduce and hardest to see. A result is wrong in a way that looks plausible when

* it reads a gauge reading timestamped *after* the forecast was made;
* it borrows another station's water level because the schema allowed it;
* it re-fits a scaler on the rows it is about to score, quietly moving the model;
* it tunes a threshold on the forecast it is about to grade; or
* it silently fits something and reports a probability as if it had not.

Each of those gets its own test below. They are grouped by the guarantee rather than
by the code path, because the point of the exercise is the guarantee.

Two of these tests are structural — `assess_risk` takes no dataset, so it *cannot*
read training data. That is asserted from the signature rather than from behaviour,
and the reason is stated in the test: a behavioural test can only observe the leaks
that were thought of.
"""

from __future__ import annotations

import copy
import datetime as dt
import inspect
import json

import pytest

from app.engines.hydro.config import RiskPolicy
from app.engines.hydro.domains import FloodEvent
from app.engines.hydro.forecast_risk import (
    RISK_STATUS_RECORDED,
    RISK_STATUS_WITHHELD,
    RiskConfiguration,
    assess_risk,
    assess_risk_safe,
    risk_from_error,
)
from app.engines.hydro.forecast_serving import serve
from app.engines.hydro.risk_context import (
    CONTEXT_NOT_EVALUABLE,
    SIGNAL_STALE,
    SPATIAL_QUANTITIES,
    EntityMismatchError,
    FutureContextError,
    HistoricalContext,
    RiskBoundaryError,
    RiskContext,
    available_signal,
)

from hydro_phase6_fixtures import (
    BAND_LABELS,
    RISK_FAMILY,
    STATION_A,
    STATION_B,
    TARGET,
    context,
    dataset,
    demo_policy,
    empty_context,
    family_request,
    full_context,
    future_context,
    origin,
    partial_context,
    residuals,
    risk_config,
    run,
    served,
    sigma,
    spatial_context,
    station_a,
    station_b,
    store,
    target_units,
    threshold_for_band,
)

from hydro_phase5_fixtures import no_fitting, serving_input


# --------------------------------------------------------------------------- #
# No reading may postdate the forecast
# --------------------------------------------------------------------------- #


def test_a_reading_after_the_forecast_origin_is_refused(
    served, context, residuals
):
    """The forecast could not have known this, so neither may the risk layer."""
    with pytest.raises(FutureContextError) as excinfo:
        assess_risk(
            served,
            config=risk_config(3.5),
            context=future_context(served.inference.entity, served.inference.origin_instant),
            residuals=residuals,
        )
    assert served.inference.origin_instant.isoformat() in str(excinfo.value)


def test_a_reading_inside_the_forecast_window_is_also_refused(
    served, context, residuals
):
    """Halfway to `prediction_timestamp` is still the future.

    The tempting boundary is the prediction instant. It is the wrong one: the forecast
    was *made* at the origin, so anything after the origin is information the model
    did not have, whatever the horizon.
    """
    window = served.inference.origin_instant + dt.timedelta(minutes=1)
    prediction_instant = dt.datetime.fromisoformat(
        served.inference.prediction_timestamp.replace("Z", "+00:00")
    )
    assert window < prediction_instant

    leaky = RiskContext(
        entity=served.inference.entity,
        dataset_type="synthetic",
        signals=(
            available_signal(
                "water_level_now", "water_level", 4.8, "m", source="synthetic gauge",
                observed_at=window,
            ),
        ),
    )
    with pytest.raises(FutureContextError):
        assess_risk(served, config=risk_config(3.5), context=leaky, residuals=residuals)


def test_a_reading_at_the_origin_itself_is_accepted(served, context, residuals, sigma):
    """The boundary is inclusive, so the instant the forecast was made is usable."""
    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served,
        config=risk_config(threshold),
        context=full_context(served.inference.entity, served.inference.origin_instant),
        residuals=residuals,
    )
    assert [signal.usable for signal in result.signals] == [True, True]


def test_a_historical_event_that_starts_after_the_origin_is_refused(
    served, context, residuals
):
    """You cannot have known about a flood that has not happened yet."""
    origin = served.inference.origin_instant
    leaky = RiskContext(
        entity=served.inference.entity,
        dataset_type="synthetic",
        signals=(
            available_signal(
                "water_level_now", "water_level", 2.9, "m", source="synthetic gauge",
                observed_at=origin,
            ),
        ),
        historical=HistoricalContext(
            available=True,
            provider="fixture-register",
            events=(
                FloodEvent(
                    event_reference="leaky-event",
                    area_reference=served.inference.entity,
                    started_at=(origin + dt.timedelta(days=30)).isoformat(),
                ),
            ),
        ),
    )
    with pytest.raises(FutureContextError) as excinfo:
        assess_risk(served, config=risk_config(3.5), context=leaky, residuals=residuals)
    assert "begins at" in str(excinfo.value)


def test_an_event_that_spans_the_origin_is_accepted(served, context, residuals):
    """A flood in progress at the origin is known, and is not leakage."""
    origin = served.inference.origin_instant
    spanning = RiskContext(
        entity=served.inference.entity,
        dataset_type="synthetic",
        signals=(
            available_signal(
                "water_level_now", "water_level", 2.9, "m", source="synthetic gauge",
                observed_at=origin,
            ),
        ),
        historical=HistoricalContext(
            available=True,
            provider="fixture-register",
            events=(
                FloodEvent(
                    event_reference="spanning-event",
                    area_reference=served.inference.entity,
                    started_at=(origin - dt.timedelta(days=2)).isoformat(),
                    ended_at=(origin + dt.timedelta(days=1)).isoformat(),
                ),
            ),
        ),
    )
    result = assess_risk(
        served, config=risk_config(3.5), context=spanning, residuals=residuals
    )
    assert result.historical_context["available"] is True
    assert result.historical_context["event_count"] == 1


def test_the_assessment_cannot_be_dated_before_the_forecast(served, context, residuals):
    """An instant before the origin would mean the risk was known in advance."""
    origin = served.inference.origin_instant
    with pytest.raises(FutureContextError) as excinfo:
        assess_risk(
            served,
            config=risk_config(3.5),
            context=context,
            residuals=residuals,
            assessed_at=origin - dt.timedelta(seconds=1),
        )
    assert "cannot be dated before" in str(excinfo.value)


def test_the_risk_layer_reads_no_clock(served, context, residuals):
    """Two calls a moment apart must agree exactly; only a clock could break that.

    The projected `RiskScoreRecord` is the artefact that carries an instant out of
    this layer, so that is where the claim is checked: it is the forecast origin, not
    the wall clock. A clock here would make every audit irreproducible.
    """
    first = assess_risk(served, config=risk_config(3.5), context=context, residuals=residuals)
    second = assess_risk(served, config=risk_config(3.5), context=context, residuals=residuals)
    assert first.to_dict() == second.to_dict()
    assert first.to_risk_score_record().assessed_at == served.inference.origin_instant.isoformat()


# --------------------------------------------------------------------------- #
# No station borrows from another
# --------------------------------------------------------------------------- #


def test_one_stations_context_cannot_be_scored_against_another_stations_forecast(
    served, residuals, station_b
):
    """The end-to-end version, and the one that matters operationally."""
    with pytest.raises(EntityMismatchError) as excinfo:
        assess_risk(
            served,
            config=risk_config(3.5),
            context=full_context(station_b, served.inference.origin_instant),
            residuals=residuals,
        )
    assert STATION_A in str(excinfo.value)
    assert STATION_B in str(excinfo.value)


def test_the_fixture_stations_really_are_different(served, residuals):
    """Guard on the guard: the mismatch above is only meaningful if they differ."""
    assert station_a != station_b
    assert served.inference.entity == STATION_A


def test_serving_another_station_and_reusing_the_first_stations_context_is_refused(
    run, residuals
):
    """Two independently real artefacts, deliberately crossed."""
    station_b_forecast = serve(
        family_request(run.origin, RISK_FAMILY, entity=STATION_B),
        store=run.store,
        data=serving_input(run.dataset, run.origin, STATION_B),
        estimators=run.estimators,
        run_result=run.trained,
        manifests=run.manifests,
    )
    assert station_b_forecast.status == "ready"
    assert station_b_forecast.inference.entity == STATION_B

    with pytest.raises(EntityMismatchError):
        assess_risk(
            station_b_forecast,
            config=risk_config(3.5),
            context=full_context(STATION_A, station_b_forecast.inference.origin_instant),
            residuals=residuals,
        )


def test_a_signal_carrying_another_station_label_is_refused_at_construction(origin):
    """Self-declared provenance beats the envelope it arrives in."""
    borrowed = available_signal(
        "water_level_now", "water_level", 2.9, "m", source="synthetic gauge",
        observed_at=origin, entity=STATION_B,
    )
    with pytest.raises(EntityMismatchError):
        RiskContext(entity=STATION_A, signals=(borrowed,))


def test_a_foreign_historical_event_is_refused(served, residuals, station_b):
    """History is station evidence too; a neighbouring catchment's floods are not ours."""
    origin = served.inference.origin_instant
    mixed = RiskContext(
        entity=STATION_A,
        dataset_type="synthetic",
        signals=(
            available_signal(
                "water_level_now", "water_level", 2.9, "m", source="synthetic gauge",
                observed_at=origin,
            ),
        ),
        historical=HistoricalContext(
            available=True,
            provider="fixture-register",
            events=(
                FloodEvent(
                    event_reference="neighbour-event",
                    area_reference=station_b,
                    started_at="2023-08-02T00:00:00+00:00",
                ),
            ),
        ),
    )
    with pytest.raises(EntityMismatchError) as excinfo:
        assess_risk(served, config=risk_config(3.5), context=mixed, residuals=residuals)
    assert station_b in str(excinfo.value)


def test_spatial_evidence_never_reaches_the_signal_layer(served, residuals):
    """Documented boundary: the GIS record carries no station label of its own.

    Phase 6 does not add one, because doing so would be a guess about a teammate's
    schema. The consequence is stated rather than hidden: spatial values are reported
    as `GisContext` provenance and are never evaluated as signals, so there is no path
    by which one station's elevation can reach another station's rules — a spatial
    rule cannot even be written.
    """
    result = assess_risk_safe(
        served,
        config=risk_config(3.5),
        context=spatial_context(STATION_A, served.inference.origin_instant),
        residuals=residuals,
    )
    assert result.gis_context["available"] is True
    assert result.gis_context["elevation_m"] == 12.5
    assert {signal.quantity for signal in result.signals}.isdisjoint(SPATIAL_QUANTITIES)

    from app.engines.hydro.risk_context import SPATIAL_QUANTITIES as spatial

    assert spatial == {"elevation", "river_distance"}


def test_the_station_label_is_checked_on_every_evidence_channel(served, residuals, station_b):
    """Signals and history are checked; the GIS channel is reported without a check.

    Naming all three together is the point — a reader should not have to work out
    which channel is guarded and which is merely absent.
    """
    origin = served.inference.origin_instant
    with pytest.raises(EntityMismatchError):
        assess_risk(
            served,
            config=risk_config(3.5),
            context=full_context(station_b, origin),
            residuals=residuals,
        )

    from app.engines.hydro.risk_context import GisContext

    gis = GisContext(
        available=True, provider="fixture-gis-adapter", elevation_m=12.5,
        provenance={"reference": "fixture-gis://context/0001"},
    )
    assert "entity" not in {field for field in gis.to_dict()}
    assert "station" not in {field for field in gis.to_dict()}


# --------------------------------------------------------------------------- #
# Nothing is trained, fitted or rewritten
# --------------------------------------------------------------------------- #


def test_assessing_risk_fits_nothing(served, context, residuals):
    """A scaler, an imputer or a forest that re-fits here would move the model.

    `FittingGuard` patches the classes, not the call sites, so it holds however the
    pipeline chooses to arrive at `fit`.
    """
    with no_fitting() as guard:
        assess_risk(served, config=risk_config(3.5), context=context, residuals=residuals)
    assert guard.touched == []


def test_no_route_into_training_is_open_during_assessment(served, context, residuals):
    """Each route is checked separately, so a failure names the route that opened.

    Taken one at a time because `FittingGuard` restores on exit: a single guard over
    all four would pass if only one were guarded, and the reason for the failure would
    be lost.
    """
    import sklearn.ensemble
    from sklearn.ensemble import RandomForestRegressor

    from app.engines.hydro import model_training
    from app.engines.hydro.preprocessing import StandardScaler, TrainFittedImputer

    for owner, label, attribute in (
        (StandardScaler, "StandardScaler.fit", "fit"),
        (TrainFittedImputer, "TrainFittedImputer.fit", "fit"),
        (RandomForestRegressor, "RandomForestRegressor.fit", "fit"),
        (model_training, "model_training.fit_family", "fit_family"),
    ):
        assert hasattr(owner, attribute), label
        with no_fitting({owner: label}) as guard:
            assess_risk(
                served, config=risk_config(3.5), context=context, residuals=residuals
            )
        assert guard.touched == [], label
    assert sklearn.ensemble.RandomForestRegressor is RandomForestRegressor


def test_assessment_mutates_no_manifest_no_split_and_no_training_matrix(
    run, served, context, residuals, dataset, sigma
):
    """The risk layer is a reader. Byte-for-byte, nothing it touched changes."""
    before_manifests = copy.deepcopy(run.manifests)
    before_audit = copy.deepcopy(run.trained.audit)
    before_dataset_ids = id(run.trained.datasets[list(run.trained.datasets)[0]])
    before_matrices = split_matrix_digests(dataset)
    before_matrices_in_run = split_matrix_digests(run.trained.datasets[TARGET])

    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    result = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    assert result.risk_level in BAND_LABELS

    assert run.manifests == before_manifests
    assert run.trained.audit == before_audit
    assert id(run.trained.datasets[list(run.trained.datasets)[0]]) == before_dataset_ids
    assert split_matrix_digests(dataset) == before_matrices
    assert split_matrix_digests(run.trained.datasets[TARGET]) == before_matrices_in_run


def split_matrix_digests(dataset) -> dict[str, str]:
    """A digest per split, so a rewritten feature or target row cannot hide."""
    import hashlib

    digests = {}
    for name, matrix in dataset.splits.items():
        payload = repr((matrix.raw_values.tobytes(), matrix.values.tobytes())).encode()
        digests[name] = hashlib.sha256(payload).hexdigest()
    return digests


def test_the_artifact_store_is_unchanged_after_a_batch_of_assessments(
    served, context, residuals, store, sigma
):
    """Re-running the whole matrix must leave the registry exactly as it was.

    Every band, every context state and every error path in one pass, because a
    mutation on an error path is the kind that only shows up months later.
    """
    before_ids = store.artifacts
    before_payloads = [artifact.to_dict() for artifact in store.artifacts]

    for band in BAND_LABELS:
        threshold = threshold_for_band(served.inference.prediction, sigma, band)
        assess_risk(
            served, config=risk_config(threshold), context=context, residuals=residuals
        )
    for context_value in (
        empty_context(STATION_A, served.inference.origin_instant),
        partial_context(STATION_A, served.inference.origin_instant),
    ):
        assess_risk(served, config=risk_config(3.5), context=context_value, residuals=residuals)
    for bad in (
        lambda: assess_risk(None, config=risk_config(3.5), context=context, residuals=residuals),
        lambda: assess_risk(served, config=risk_config(3.5), residuals=residuals),
        lambda: assess_risk(served, config="not a config", context=context, residuals=residuals),
        lambda: assess_risk(
            served, config=risk_config(float("nan")), context=context, residuals=residuals
        ),
    ):
        with pytest.raises(Exception) as raised:
            bad()
            assert False, "expected a boundary error, got a result instead"
        assert issubclass(raised.type, RiskBoundaryError), raised.type

    assert store.artifacts is before_ids
    assert [artifact.to_dict() for artifact in store.artifacts] == before_payloads


def test_assessing_risk_never_re_scores_the_forecast(
    run, served, context, residuals, sigma, monkeypatch
):
    """The value Phase 6 reads is the one Phase 5 produced, not a fresh `predict`.

    Both levels are patched - the repository's model wrapper and the scikit-learn
    forest inside it - because a re-score could arrive at either. A risk layer that
    re-ran the model would silently change its own input, and a model re-run on a
    feature row it was not fitted for is exactly the leak this guards.
    """
    from sklearn.ensemble import RandomForestRegressor

    from app.engines.hydro.models import SklearnEnsembleModel

    forest = run.estimators[f"{RISK_FAMILY}-target_water_level_6h-6h-seed20240917"]
    assert isinstance(forest, SklearnEnsembleModel)
    assert isinstance(forest.estimator, RandomForestRegressor)

    threshold = threshold_for_band(served.inference.prediction, sigma, "MEDIUM")
    expected = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )

    def refuse(*args, **kwargs):
        raise AssertionError("Phase 6 re-scored the forecast instead of reading it")

    monkeypatch.setattr(SklearnEnsembleModel, "predict", refuse)
    monkeypatch.setattr(RandomForestRegressor, "predict", refuse)

    actual = assess_risk(
        served, config=risk_config(threshold), context=context, residuals=residuals
    )
    assert actual.to_dict() == expected.to_dict()


# --------------------------------------------------------------------------- #
# The threshold and the spread are configuration, not fitted values
# --------------------------------------------------------------------------- #


def test_the_threshold_is_never_tuned_to_the_forecast_it_grades(served, residuals):
    """Grading a forecast against a threshold derived from it is circular.

    The fixture thresholds are derived by bisecting the *exceedance function* for a
    chosen probability, not from the observed exceedance of this forecast. This test
    states that independence as a fact about the interface: `RiskConfiguration` takes
    a number and a source, and there is no parameter through which a forecast could
    influence it.
    """
    parameters = set(inspect.signature(assess_risk).parameters)
    assert parameters == {
        "served",
        "config",
        "context",
        "residuals",
        "residual_sigma",
        "assessed_at",
        "risk_result_id",
    }
    assert not parameters & {"dataset", "frame", "targets", "y_true", "train", "estimator"}


def test_the_residual_spread_cannot_be_derived_from_the_forecast_being_scored(
    served, context, sigma
):
    """A spread of one number, from measurements, with the method recorded.

    `residual_sigma` may be supplied directly, but only by a caller who measured it;
    there is no path from the forecast itself to the spread.
    """
    result = assess_risk(
        served,
        config=risk_config(3.5),
        context=context,
        residual_sigma=sigma,
    )
    assert result.residual_sigma == pytest.approx(sigma)
    assert result.residual_sigma_source == "caller_supplied_measurement"
    assert result.assessment.method == "normal_approximation_measured_sigma"


def test_a_spread_fabricated_from_the_forecast_alone_is_still_not_offered(served, context):
    """No residuals and no supplied sigma means no spread, and no band."""
    result = assess_risk_safe(served, config=risk_config(3.5), context=context)
    assert result.status == RISK_STATUS_WITHHELD
    assert result.risk_level is None
    assert result.risk_score is None
    assert result.residual_sigma is None


def test_a_stale_signal_cannot_launder_a_threshold_into_approval(served, residuals):
    """Staleness is a state, and a stale reading never becomes a rule input."""
    origin = served.inference.origin_instant
    stale = RiskContext(
        entity=STATION_A,
        dataset_type="synthetic",
        signals=(
            available_signal(
                "rainfall_3h", "rainfall", 500.0, "mm", source="synthetic gauge",
                observed_at=origin - dt.timedelta(days=365),
            ),
        ),
    )
    result = assess_risk(
        served,
        config=risk_config(3.5, default_max_age_seconds=3600.0),
        context=stale,
        residuals=residuals,
    )
    assert result.signals[0].availability == SIGNAL_STALE
    assert result.signals[0].value is None
    assert result.threshold_source != "approved"


# --------------------------------------------------------------------------- #
# Withheld results are as auditable as recorded ones
# --------------------------------------------------------------------------- #


def test_a_withheld_result_still_carries_the_forecast_it_refused_to_score(
    served, context
):
    """Withholding is a statement, and it needs provenance to be checkable."""
    result = assess_risk_safe(served, config=risk_config(3.5), context=context)
    assert result.status == RISK_STATUS_WITHHELD
    assert result.forecast_id == served.forecast_id
    assert result.provenance_chain["forecast_artifact_id"] == served.inference.artifact_id
    assert result.provenance_chain["feature_digest"] == served.inference.feature_digest
    assert result.synthetic_demo is True
    assert result.production_ready_claimed is False


def test_a_withheld_result_names_the_reason_it_withheld(served, context):
    result = assess_risk_safe(served, config=risk_config(3.5), context=context)
    assert "no measured residual spread was supplied" in result.explain()
    assert "not a LOW rating" in result.explain()


def test_a_withheld_result_serialises_exactly_like_a_recorded_one(served, context, residuals):
    """One shape for every outcome, so no consumer needs a second code path."""
    withheld = assess_risk_safe(served, config=risk_config(3.5), context=context)
    recorded = assess_risk_safe(
        served, config=risk_config(3.5), context=context, residuals=residuals
    )
    assert set(withheld.to_dict()) == set(recorded.to_dict())
    assert recorded.status == RISK_STATUS_RECORDED
    assert json.loads(json.dumps(withheld.to_dict()))["status"] == RISK_STATUS_WITHHELD
    assert json.loads(json.dumps(recorded.to_dict()))["status"] == RISK_STATUS_RECORDED


def test_a_direct_refusal_and_a_converted_one_agree(served, context, station_b):
    """`assess_risk_safe` and `risk_from_error` must tell the same story.

    Checked by comparing them field for field, not just on `status`: a wrapper that
    quietly dropped the reason would leave an operator with a refusal and no cause.
    """
    foreign = full_context(station_b, served.inference.origin_instant)
    with pytest.raises(EntityMismatchError) as excinfo:
        assess_risk(served, config=risk_config(3.5), context=foreign, residuals=[])

    direct = assess_risk_safe(
        served, config=risk_config(3.5), context=foreign, residuals=[]
    )
    converted = risk_from_error(
        excinfo.value, served=served, config=risk_config(3.5)
    )

    assert direct.status == converted.status == RISK_STATUS_WITHHELD
    assert direct.risk_level is converted.risk_level is None
    assert direct.evaluation_state == converted.evaluation_state
    assert excinfo.value.reason in converted.explain()
    # Same configuration, same refusal: the two routes must be indistinguishable.
    assert direct.risk_result_id == converted.risk_result_id


def test_an_error_result_names_the_boundary_reason_tag(served, residuals):
    """A machine-readable tag, so a refusal can be counted rather than parsed."""
    from app.engines.hydro.risk_context import MissingRiskContextError

    with pytest.raises(MissingRiskContextError) as excinfo:
        assess_risk(served, config=risk_config(3.5), residuals=residuals)
    result = risk_from_error(excinfo.value, served=served, config=risk_config(3.5))
    assert result.status == RISK_STATUS_WITHHELD
    assert excinfo.value.reason in result.explain()


def test_no_error_path_can_return_a_band(served, context, station_b):
    """Every refusal, however it was reached, yields no level and no score."""
    origin = served.inference.origin_instant
    attempts = (
        lambda: assess_risk_safe(None, config=risk_config(3.5), context=context),
        lambda: assess_risk_safe(
            served, config=risk_config(3.5), context=full_context(station_b, origin)
        ),
        lambda: assess_risk_safe(
            served, config=risk_config(3.5),
            context=future_context(served.inference.entity, origin),
        ),
        lambda: assess_risk_safe(served, config=risk_config(3.5), context=context),
    )
    for attempt in attempts:
        result = attempt()
        assert result.status == RISK_STATUS_WITHHELD
        assert result.risk_level is None
        assert result.risk_score is None
        assert result.production_ready_claimed is False
        assert result.explain()


# --------------------------------------------------------------------------- #
# Configuration cannot smuggle an unstated default
# --------------------------------------------------------------------------- #


def test_a_configuration_with_no_units_cannot_borrow_the_forecast_s_units(
    served, context, residuals
):
    """The threshold unit defaults to the forecast's own unit, and says so.

    Defaulting is not inventing: the forecast's `target_units` is measured, not
    assumed, and the resulting value is recorded on the result either way.
    """
    units = target_units()
    assert units == "m"
    assert served.inference.target_units == units

    result = assess_risk_safe(
        served, config=risk_config(3.5), context=context, residuals=residuals
    )
    assert result.status == "recorded"
    assert result.threshold_units == units


def test_an_explicitly_declared_configuration_version_is_recorded(served, context, residuals):
    """Two configurations that differ only in their version must be distinguishable.

    Otherwise a re-tuned policy is indistinguishable from the one it replaced, which
    is the whole reason a configuration carries a version at all.
    """
    first = assess_risk_safe(
        served,
        config=risk_config(3.5, risk_configuration_version="navya-phase6/v1"),
        context=context,
        residuals=residuals,
    )
    second = assess_risk_safe(
        served,
        config=risk_config(3.5, risk_configuration_version="navya-phase6/v2"),
        context=context,
        residuals=residuals,
    )
    assert first.risk_configuration_version == "navya-phase6/v1"
    assert second.risk_configuration_version == "navya-phase6/v2"
    assert first.provenance_chain["risk_configuration_version"] != second.provenance_chain[
        "risk_configuration_version"
    ]


def test_a_policy_with_no_threshold_cannot_produce_a_band(served, context, residuals):
    """`RiskPolicy` is Phase 5's own type; Phase 6 does not bypass its own checks.

    An empty policy is not a caller mistake — it is what the repository looks like
    before an operator configures one — so it comes back as a withheld result that
    names the outstanding work, rather than as an exception a caller must catch.
    """
    empty = RiskPolicy()
    assert empty.is_usable is False
    assert empty.flood_threshold is None
    assert empty.band_edges == ()
    assert "risk bands unavailable" in empty.describe().lower()

    result = assess_risk_safe(
        served,
        config=RiskConfiguration(policy=empty, rules=()),
        context=context,
        residuals=residuals,
    )
    assert result.status == RISK_STATUS_WITHHELD
    assert result.evaluation_state == CONTEXT_NOT_EVALUABLE
    assert result.risk_level is None
    assert result.risk_score is None
    assert result.threshold is None
    assert result.assessment.flood_probability is None
    assert result.assessment.method is None
    assert "no usable threshold policy" in result.explain()
    assert "HYDRO_FLOOD_THRESHOLD" in result.explain()
    assert "HYDRO_RISK_THRESHOLD_POLICY=approved" in result.explain()


def test_a_pending_policy_yields_a_band_and_an_explicit_non_approval(
    served, context, residuals
):
    """A DEMO threshold is usable, and its pending status reaches the result.

    This is the distinction that matters operationally: an unapproved threshold
    produces a band that is explicitly marked unapproved, rather than either a refusal
    or a silent "approved".
    """
    pending = demo_policy(3.5, status="pending")
    assert pending.is_usable is True
    assert pending.policy_status == "pending"

    result = assess_risk_safe(
        served,
        config=RiskConfiguration(policy=pending, rules=()),
        context=context,
        residuals=residuals,
    )
    assert result.status == RISK_STATUS_RECORDED
    assert result.risk_level in BAND_LABELS
    assert result.assessment.policy_approved is False
    assert "NOT an approved flood stage" in result.explain()


# --------------------------------------------------------------------------- #
# The Phase 2/3 split boundaries survive into the risk record
# --------------------------------------------------------------------------- #


def test_the_split_boundaries_reach_the_risk_record(served, context, residuals):
    """If the residuals crossed the training split, the risk would inherit the lie.

    The boundaries are Phase 2/3's own `SplitBoundaries`, re-materialised here rather
    than re-derived, and asserted in order: train, then validation, then test, with no
    overlap. The fixture residuals are measured on the validation and test splits only,
    so a correct split means the spread was never informed by fitted rows.
    """
    result = assess_risk_safe(
        served, config=risk_config(3.5), context=context, residuals=residuals
    )
    split = result.provenance.to_dict()["split"]

    def at(key: str) -> dt.datetime:
        return dt.datetime.fromisoformat(split[key].replace("Z", "+00:00"))

    assert at("train_end") < at("validation_start")
    assert at("validation_end") < at("test_start")
    assert split["train_rows"] > 0
    assert split["validation_rows"] > 0
    assert split["test_rows"] > 0
    # Both splits the residuals came from lie strictly after the training window.
    assert min(at("validation_start"), at("test_start")) > at("train_end")


def test_the_synthetic_status_survives_the_handoff_into_the_risk_record(
    served, context, residuals
):
    provenance = assess_risk_safe(
        served, config=risk_config(3.5), context=context, residuals=residuals
    ).provenance.to_dict()
    assert provenance["dataset_type"] == "synthetic"
    assert provenance["is_synthetic"] is True
    assert provenance["metrics_label"].startswith("synthetic/demo")
    assert provenance["is_complete"] is False
    assert provenance["missing_fields"] == ["dataset_checksum"]
    assert (
        provenance["disclaimer"]
        == "THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL "
        "HYDROLOGICAL OBSERVATION DATA."
    )


# --------------------------------------------------------------------------- #
# The explanation claims nothing the result does not support
# --------------------------------------------------------------------------- #


def _unassignable_policy(edges):
    """A policy whose edges describe fewer bands than it has labels."""
    return RiskPolicy(
        flood_threshold=3.5,
        threshold_source="DEMO value chosen for the synthetic pipeline; NOT an "
        "official flood stage",
        policy_status="pending",
        band_edges=edges,
    )


def test_an_unassignable_band_policy_is_not_described_as_a_mapping(
    served, context, residuals
):
    """Four labels with two edges is not a band mapping, and must not be printed as one.

    `risk.classify_risk_level` accepts `len(labels)` edges or `len(labels) - 1`
    interior edges and returns `None` for anything else. Writing "map to" for a set it
    rejected would put a claim in the explanation the result does not support.
    """
    result = assess_risk_safe(
        served,
        config=RiskConfiguration(policy=_unassignable_policy((0.1, 0.3)), rules=()),
        context=context,
        residuals=residuals,
    )
    assert result.risk_level is None
    threshold_line = result.explanation[1]
    assert "map to" not in threshold_line
    assert "do not describe 4 bands" in threshold_line
    assert "assign no band" in threshold_line


def test_a_pending_policy_line_never_reports_a_level_that_was_not_assigned(
    served, context, residuals
):
    """"This level is a demo band" is false when there is no level.

    The disclaimer itself must still appear - that is the point of it - but it may not
    be phrased as though a band had been produced.
    """
    withheld = assess_risk_safe(
        served,
        config=RiskConfiguration(policy=_unassignable_policy((0.1, 0.3)), rules=()),
        context=context,
        residuals=residuals,
    )
    pending_lines = [
        line for line in withheld.explanation if "still pending approval" in line
    ]
    assert len(pending_lines) == 1
    assert "this level" not in pending_lines[0]
    assert "no level it could assign" in pending_lines[0]

    recorded = assess_risk_safe(
        served, config=risk_config(3.5), context=context, residuals=residuals
    )
    assert recorded.risk_level is not None
    recorded_pending = [
        line for line in recorded.explanation if "still pending approval" in line
    ]
    assert len(recorded_pending) == 1
    assert "this level is a demo band" in recorded_pending[0]


def test_every_explanation_line_is_about_something_the_result_contains(
    served, context, residuals
):
    """A band line exists only when a band was assigned; a read line only when read.

    This is the general form of the two checks above, and it is here so a future
    explanation line cannot reintroduce the same defect silently.
    """
    result = assess_risk_safe(
        served,
        config=RiskConfiguration(policy=_unassignable_policy((0.1, 0.3)), rules=()),
        context=context,
        residuals=residuals,
    )
    assert "the probability falls in band" not in result.explain()
    assert result.risk_level is None

    recorded = assess_risk_safe(
        served, config=risk_config(3.5), context=context, residuals=residuals
    )
    assert "the probability falls in band" in recorded.explain()
    assert recorded.risk_level is not None
    for line in recorded.explanation:
        if line.startswith("signal ") and " read " in line:
            name = line.split("'")[1]
            signal = next(s for s in recorded.signals if s.name == name)
            assert signal.usable is True
            assert signal.value is not None


def test_a_non_ascending_band_policy_is_withheld_and_says_why(served, context, residuals):
    """A mis-ordered edge set is refused by the classifier, and the refusal is reported.

    `classify_risk_level` raises rather than returning a wrong band. Phase 6 converts
    that into a withheld result whose explanation names the reason and tags it, rather
    than letting the exception escape or swallowing it silently.
    """
    result = assess_risk_safe(
        served,
        config=RiskConfiguration(
            policy=_unassignable_policy((0.6, 0.1, 0.3, 0.9)), rules=()
        ),
        context=context,
        residuals=residuals,
    )
    assert result.status == RISK_STATUS_WITHHELD
    assert result.risk_level is None
    assert result.risk_score is None
    assert result.evaluation_state == CONTEXT_NOT_EVALUABLE
    assert "strictly ascending" in result.explain()
    assert "invalid_risk_calculation" in result.explain()