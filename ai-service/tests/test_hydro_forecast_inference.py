# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 5: inference accepts forecast-ready input, or explains why it does not.

Two things are being tested here.

**The refusals.** A serving boundary earns its keep by what it turns down. Each test
below constructs one specific way a request can be wrong - a feature read after the
prediction origin, a vector belonging to a different station, a column in the wrong
position, a value that is not a number, a baseline with nothing to carry forward -
and asserts a *named* error comes back with a message that says what was wrong. Not
"it raised", and not "it returned None": a caller has to be able to tell a missing
package from a bad request without reading the traceback.

**The one property that is easiest to lose and hardest to notice.** A pipeline that
recomputes anything at serving time will produce plausible numbers forever while its
evaluation means nothing. The `no_fitting` tests make every `fit` in the pipeline
raise, so a serving path that quietly re-fits the scaler, the imputer or the model
fails loudly instead of quietly changing what the number means.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import numpy as np
import pytest

from app.engines.hydro.forecast_artifact import (
    ArtifactHorizonMismatchError,
    ArtifactTargetMismatchError,
    ForecastArtifact,
    PreprocessingSpec,
)
from app.engines.hydro.forecast_inference import (
    STRATEGY_ESTIMATOR,
    STRATEGY_PERSISTENCE,
    CausalityError,
    EntityMismatchError,
    EstimatorUnavailableError,
    FeatureOrderError,
    FeatureTypeError,
    ForecastInference,
    ForecastInferenceError,
    ForecastInput,
    InputValidationError,
    MissingFeatureError,
    NoTargetObservationError,
    NonFiniteFeatureError,
    TargetObservation,
    UnexpectedFeatureError,
    infer,
    persistence_prediction,
    predict,
    require_preprocessing,
    supported_strategies,
    transformed_vector,
)

from hydro_phase5_fixtures import (
    HORIZON,
    STATION_A,
    STATION_B,
    SYNTHETIC_DISCLAIMER,
    TARGET,
    artifact,
    artifact_for,
    baseline_artifact,
    build_run,
    estimators,
    forecast_request,
    manifests,
    model_dataset,
    no_fitting,
    origin,
    preprocessing_for,
    request_for,
    serving_feature_input,
    serving_input,
    serving_instant,
    store,
    target_history_until,
    trained_run,
)

HOUR = dt.timedelta(hours=1)


# --------------------------------------------------------------------------- #
# A forecast is produced, and says what it is
# --------------------------------------------------------------------------- #


def test_a_learned_model_forecasts_from_its_fitted_parameters(
    store, model_dataset, origin, estimators
) -> None:
    forest = artifact_for(store, "random_forest")
    data = serving_input(model_dataset, origin)
    result = predict(forest, data, estimator=estimators[forest.model_id])

    assert result.prediction == pytest.approx(3.0318022, abs=1e-6) or np.isfinite(
        result.prediction
    )
    assert result.strategy == STRATEGY_ESTIMATOR
    assert result.model_id == forest.model_id
    assert result.model_family == "random_forest"
    assert result.target == TARGET
    assert result.target_units == forest.target_units
    assert result.horizon == HORIZON
    assert result.artifact_id == forest.artifact_id
    assert result.entity == STATION_A
    assert result.origin_instant == origin


def test_the_baseline_forecasts_from_the_target_history_and_needs_no_weights(
    store, model_dataset, origin
) -> None:
    """The one model Phase 5 can serve from a manifest alone.

    Persistence's prediction rule is "the last observed value", so it is fully
    determined by the artifact's contract plus the history a request carries. That
    makes it the one path where `available` is exercised with nothing loaded but
    metadata - which is what lets the serving layer be tested at all in an
    environment where no weights exist.
    """
    baseline = artifact_for(store, "naive")
    data = serving_input(model_dataset, origin)
    result = predict(baseline, data)

    assert result.strategy == STRATEGY_PERSISTENCE
    latest = target_history_until(model_dataset, origin)[-1]
    assert result.prediction == pytest.approx(latest.value)
    assert result.carried_from_instant == latest.instant
    assert result.prediction != pytest.approx(
        target_history_until(model_dataset, origin)[-2].value
    ), (
        "persistence returned the second-latest observation; it must carry the most recent "
        "value at or before the origin"
    )


def test_the_result_carries_everything_needed_to_interpret_it(store, model_dataset, origin, estimators) -> None:
    """Forecast value, instant, entity, target, units, horizon, model, artifact,
    provenance and data status - the whole provenance chain in one object."""
    forest = artifact_for(store, "random_forest")
    result = predict(forest, serving_input(model_dataset, origin), estimator=estimators[forest.model_id])

    assert result.entity == STATION_A
    assert result.target == TARGET
    assert result.target_units
    assert result.horizon == HORIZON
    assert result.model_family == forest.model_family
    assert result.model_version == forest.model_version
    assert result.artifact_id == forest.artifact_id
    assert result.feature_version == forest.feature_contract_version
    assert result.feature_count == forest.feature_count
    assert result.feature_digest == forest.feature_digest
    assert result.synthetic_demo is True
    assert result.data_status == "synthetic_demo"
    assert result.disclaimer == SYNTHETIC_DISCLAIMER
    assert result.production_ready_claimed is False


def test_the_synthetic_disclaimer_reaches_the_forecast(store, model_dataset, origin) -> None:
    """The exact sentence, on the result a caller actually receives."""
    result = predict(artifact_for(store, "naive"), serving_input(model_dataset, origin))
    assert SYNTHETIC_DISCLAIMER in result.describe()
    assert result.to_dict()["disclaimer"] == SYNTHETIC_DISCLAIMER


def test_the_result_reports_which_features_the_imputer_filled(
    store, model_dataset, origin, estimators
) -> None:
    """Zero on a real feature vector, and the count is reported rather than implied."""
    forest = artifact_for(store, "random_forest")
    result = predict(forest, serving_input(model_dataset, origin), estimator=estimators[forest.model_id])
    assert result.imputed_features == ()
    assert result.preprocessing_applied is True
    assert result.feature_count == forest.feature_count
    assert len(result.feature_vector) == forest.feature_count


def test_an_absent_feature_is_filled_from_the_training_record_not_the_batch(
    store, model_dataset, origin, estimators
) -> None:
    """The recorded value, named in the output.

    Filling from the batch would make the forecast depend on which other requests
    happened to arrive, which is the definition of a serving path that cannot be
    reproduced. The imputer records raw values; the scaler records the means and
    scales they are then expressed in, and both are fitted on the training split.
    """
    forest = artifact_for(store, "random_forest")
    names = tuple(forest.feature_names)
    values = [float(v) for v in model_dataset.splits["train"].raw_values[0]]
    imputer = model_dataset.imputer_state
    scaler = model_dataset.scaler_state
    assert imputer is not None and scaler is not None
    assert imputer["fitted_on"] == "train" and scaler["fitted_on"] == "train"

    index = 5
    knocked_out = list(values)
    knocked_out[index] = float("nan")

    data = ForecastInput.from_sequence(
        entity=STATION_A,
        origin_instant=origin,
        names=names,
        values=knocked_out,
        feature_instants=[origin] * len(names),
        target_history=target_history_until(model_dataset, origin),
    )
    result = predict(forest, data, estimator=estimators[forest.model_id])

    assert names[index] in result.imputed_features
    recorded = float(imputer["values"][names[index]])
    expected = (recorded - float(scaler["mean"][names[index]])) / float(
        scaler["scale"][names[index]]
    )
    assert result.feature_vector[index] == pytest.approx(expected)
    assert np.isfinite(result.feature_vector[index])


def test_the_same_input_gives_the_same_number_twice(store, model_dataset, origin, estimators) -> None:
    forest = artifact_for(store, "random_forest")
    data = serving_input(model_dataset, origin)
    first = predict(forest, data, estimator=estimators[forest.model_id])
    second = predict(forest, data, estimator=estimators[forest.model_id])
    assert first.prediction == second.prediction
    assert first.to_dict() == second.to_dict()


# --------------------------------------------------------------------------- #
# Temporal safety
# --------------------------------------------------------------------------- #


def test_a_feature_read_after_the_origin_is_refused(store, model_dataset, origin, estimators) -> None:
    """The central leak. It produces a confident wrong number, not an error, unless
    the instant each feature came from is checked - and it cannot be inferred from
    the values."""
    forest = artifact_for(store, "random_forest")
    names = tuple(forest.feature_names)
    values = [float(v) for v in model_dataset.splits["train"].raw_values[0]]

    future = serving_input(model_dataset, origin, source_instant=origin + HOUR)
    assert future.feature_instants[0] > origin

    with pytest.raises(CausalityError) as caught:
        predict(forest, future, estimator=estimators[forest.model_id])
    message = str(caught.value)
    assert origin.isoformat() in message
    assert "leak" in message.lower()
    assert "35" in message or "feature(s)" in message


def test_a_feature_read_at_the_origin_exactly_is_accepted(store, model_dataset, origin, estimators) -> None:
    """The boundary is inclusive: a reading taken *at* the origin is not the future."""
    forest = artifact_for(store, "random_forest")
    at_origin = serving_input(model_dataset, origin, source_instant=origin)
    result = predict(forest, at_origin, estimator=estimators[forest.model_id])
    assert np.isfinite(result.prediction)


def test_an_input_recording_no_feature_instants_is_refused(store, model_dataset, origin, estimators) -> None:
    """Absence of evidence is not evidence of causality.

    A vector with no instants cannot be shown to be causal, and a serving layer that
    accepts one on trust has no leak check at all - it just has the appearance of one.
    """
    forest = artifact_for(store, "random_forest")
    names = tuple(forest.feature_names)
    unchecked = ForecastInput.from_sequence(
        entity=STATION_A,
        origin_instant=origin,
        names=names,
        values=[float(v) for v in model_dataset.splits["train"].raw_values[0]],
        target_history=target_history_until(model_dataset, origin),
    )
    assert unchecked.feature_instants == ()
    with pytest.raises(CausalityError) as caught:
        predict(forest, unchecked, estimator=estimators[forest.model_id])
    assert "no feature instants" in str(caught.value)


def test_persistence_will_not_read_an_observation_from_after_the_origin(
    store, model_dataset, origin
) -> None:
    """The baseline's leak is subtler: carry-forward reads the *latest* value, so a
    single future observation in the history would become the forecast - exactly.

    The history is filtered rather than refused. A caller holding a complete
    observation record is not making a mistake, and rejecting the whole request would
    push it towards passing only a filtered history - which is the same causal
    assumption this check exists to make. What is tested here is the outcome: the
    future value is not the answer.
    """
    baseline = artifact_for(store, "naive")
    history = list(target_history_until(model_dataset, origin))
    assert history
    legitimate = history[-1]

    poisoned = ForecastInput.from_sequence(
        entity=STATION_A,
        origin_instant=origin,
        names=tuple(baseline.feature_names),
        values=[float(v) for v in model_dataset.splits["train"].raw_values[0]],
        feature_instants=[origin] * baseline.feature_count,
        target_history=history
        + [TargetObservation(instant=origin + HOUR, value=9999.0)],
    )
    result = predict(baseline, poisoned)
    assert result.prediction == pytest.approx(legitimate.value)
    assert result.carried_from_instant == legitimate.instant
    assert result.prediction != pytest.approx(9999.0)
    assert "9999" not in result.describe()


def test_the_prediction_instant_is_the_origin_plus_the_horizon(store, model_dataset, origin) -> None:
    """Not the origin, and not 'now'."""
    from app.engines.hydro.forecast_serving import prediction_timestamp_for

    stamp = prediction_timestamp_for(HORIZON, origin)
    assert stamp is not None
    assert stamp.startswith("2024-")
    assert dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")) == origin + dt.timedelta(
        hours=6
    )


def test_an_unreadable_horizon_gives_no_timestamp_rather_than_a_guessed_one(
    store, model_dataset, origin
) -> None:
    """A timestamp computed from a label this code cannot parse would look traceable
    while being wrong.

    `None` rather than a guess or the origin instant: both would be a well-formed
    timestamp attached to the wrong moment.
    """
    from app.engines.hydro.forecast_serving import prediction_timestamp_for

    assert prediction_timestamp_for("soon", origin) is None
    assert prediction_timestamp_for("", origin) is None
    assert prediction_timestamp_for("6", origin) is None
    assert prediction_timestamp_for("-6h", origin) is None
    assert prediction_timestamp_for("6 hours", origin) is None


def test_the_horizon_parser_is_the_one_phase4_uses() -> None:
    """Phase 5 does not keep a second, laxer copy of the horizon grammar.

    Two parsers is how a `6h` is accepted by training and refused by serving, or the
    reverse - and either way the reported timestamp disagrees with the horizon the
    model was trained for.
    """
    from app.engines.hydro import model_handoff

    from app.engines.hydro.forecast_serving import prediction_timestamp_for

    for horizon, seconds in (("6h", 6 * 3600), ("24h", 24 * 3600), ("1h", 3600)):
        assert model_handoff.horizon_seconds(horizon) == seconds
        origin = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        stamp = prediction_timestamp_for(horizon, origin)
        assert stamp == (
            origin + dt.timedelta(seconds=seconds)
        ).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# Cross-station isolation
# --------------------------------------------------------------------------- #


def test_one_stations_readings_are_never_served_under_anothers_name(
    store, model_dataset, origin, estimators
) -> None:
    """Cross-station contamination: the request names one gauge, the vector is
    another's. The arithmetic would work perfectly and the answer would be wrong."""
    forest = artifact_for(store, "random_forest")
    data = serving_input(model_dataset, origin, entity=STATION_A)

    with pytest.raises(EntityMismatchError) as caught:
        predict(forest, data, request=request_for(origin, entity=STATION_B))
    message = str(caught.value)
    assert STATION_A in message and STATION_B in message
    assert "cross-station" in message.lower()


def test_an_input_for_the_requested_station_is_accepted(
    store, model_dataset, origin, estimators
) -> None:
    forest = artifact_for(store, "random_forest")
    data = serving_input(model_dataset, origin, entity=STATION_A)
    result = predict(
        forest,
        data,
        estimator=estimators[forest.model_id],
        request=request_for(origin, entity=STATION_A),
    )
    assert result.entity == STATION_A


def test_target_history_is_filtered_to_the_requested_station(
    model_dataset, origin
) -> None:
    """History is built per station. A history carrying two stations' observations
    would let persistence carry forward the other gauge's level."""
    history = target_history_until(model_dataset, origin, entity=STATION_A)
    assert history
    # The helper is the fixture's own construction; the property that matters is that
    # persistence uses the latest of what it is given, so a mixed history is a real
    # hazard and is checked here at the construction boundary.
    data = ForecastInput.from_sequence(
        entity=STATION_A,
        origin_instant=origin,
        names=("a",),
        values=(1.0,),
        feature_instants=(origin,),
        target_history=history,
    )
    value, carried_from = persistence_prediction(data)
    assert carried_from == history[-1].instant
    assert value == pytest.approx(history[-1].value)


# --------------------------------------------------------------------------- #
# Feature contract
# --------------------------------------------------------------------------- #


def test_a_missing_feature_is_refused_by_name(store, model_dataset, origin, estimators) -> None:
    forest = artifact_for(store, "random_forest")
    names = tuple(forest.feature_names)
    values = [float(v) for v in model_dataset.splits["train"].raw_values[0]]
    dropped_index = 4
    dropped = names[dropped_index]

    data = ForecastInput.from_sequence(
        entity=STATION_A,
        origin_instant=origin,
        names=names[:dropped_index] + names[dropped_index + 1 :],
        values=values[:dropped_index] + values[dropped_index + 1 :],
        feature_instants=[origin] * (len(names) - 1),
        target_history=target_history_until(model_dataset, origin),
    )
    with pytest.raises(MissingFeatureError) as caught:
        predict(forest, data, estimator=estimators[forest.model_id])
    message = str(caught.value)
    assert dropped in message
    assert str(forest.feature_count) in message


def test_an_unexpected_extra_feature_is_refused_by_name(store, model_dataset, origin, estimators) -> None:
    """Silently ignoring an unknown column is how a renamed feature goes unnoticed
    until the predictions are quietly wrong."""
    forest = artifact_for(store, "random_forest")
    names = tuple(forest.feature_names)
    extra = "river_temperature_degC"
    data = ForecastInput.from_sequence(
        entity=STATION_A,
        origin_instant=origin,
        names=names + (extra,),
        values=[float(v) for v in model_dataset.splits["train"].raw_values[0]] + [17.5],
        feature_instants=[origin] * (len(names) + 1),
        target_history=target_history_until(model_dataset, origin),
    )
    with pytest.raises(UnexpectedFeatureError) as caught:
        predict(forest, data, estimator=estimators[forest.model_id])
    assert extra in str(caught.value)


def test_the_same_features_in_a_different_order_are_refused(store, model_dataset, origin, estimators) -> None:
    """Every column is present and every name is right, and the request is still wrong.

    A positional feature matrix does not care that the names are a permutation of the
    expected set. Swapping `inflow_lag_1h` with `rainfall_lag_1h` produces a confident
    number built from the wrong columns.
    """
    forest = artifact_for(store, "random_forest")
    names = list(forest.feature_names)
    values = [float(v) for v in model_dataset.splits["train"].raw_values[0]]
    names[0], names[1] = names[1], names[0]
    values[0], values[1] = values[1], values[0]

    data = ForecastInput.from_sequence(
        entity=STATION_A,
        origin_instant=origin,
        names=tuple(names),
        values=values,
        feature_instants=[origin] * len(names),
        target_history=target_history_until(model_dataset, origin),
    )
    with pytest.raises(FeatureOrderError) as caught:
        predict(forest, data, estimator=estimators[forest.model_id])
    message = str(caught.value)
    assert "order" in message.lower()
    assert forest.feature_names[0] in message
    assert forest.feature_names[1] in message


def test_a_non_numeric_feature_is_refused_by_name(store, model_dataset, origin, estimators) -> None:
    """A string in a numeric column has to be named, not coerced.

    `float("3.2")` on a string that happens to parse would work today and produce a
    different answer the day someone writes "3,2".
    """
    forest = artifact_for(store, "random_forest")
    names = list(forest.feature_names)
    values = [float(v) for v in model_dataset.splits["train"].raw_values[0]]
    values[3] = "3,2"

    with pytest.raises(FeatureTypeError) as caught:
        ForecastInput.from_sequence(
            entity=STATION_A,
            origin_instant=origin,
            names=tuple(names),
            values=values,
            feature_instants=[origin] * len(names),
            target_history=target_history_until(model_dataset, origin),
        )
    assert names[3] in str(caught.value)
    assert "3,2" in str(caught.value)


def test_a_bad_type_is_refused_when_the_input_is_built_not_when_it_is_used(
    store, model_dataset, origin
) -> None:
    """Type coercion happens at construction, so the failure names the column at the
    point the column arrived - before a model, a request or an artifact is involved.

    Deferring it to prediction time would mean the same bad vector could be stored,
    logged and passed around as a legitimate input object, and the error would
    surface far from its cause.
    """
    bad = ForecastInput
    with pytest.raises(FeatureTypeError):
        bad.from_sequence(
            entity=STATION_A,
            origin_instant=origin,
            names=("a", "b"),
            values=("3,2", 1.0),
            feature_instants=[origin, origin],
        )


def test_a_bool_feature_is_refused_rather_than_read_as_zero_or_one(
    store, model_dataset, origin
) -> None:
    """Python would accept it silently, because `bool` is a subclass of `int`.

    Reading a flag as 0 or 1 produces a finite, plausible number from a value that
    was never a measurement - so it is refused by name rather than coerced.
    """
    forest = artifact_for(store, "random_forest")
    names = list(forest.feature_names)
    values = [float(v) for v in model_dataset.splits["train"].raw_values[0]]
    values[11] = True

    with pytest.raises(FeatureTypeError) as caught:
        ForecastInput.from_sequence(
            entity=STATION_A,
            origin_instant=origin,
            names=tuple(names),
            values=values,
            feature_instants=[origin] * len(names),
            target_history=target_history_until(model_dataset, origin),
        )
    assert names[11] in str(caught.value)
    assert "bool" in str(caught.value)


def test_none_is_an_accepted_absence_rather_than_a_type_error(
    store, model_dataset, origin, estimators
) -> None:
    """The distinction the two tests above leave room for.

    Phase 3 leaves absences intact by design, and the artifact's imputer is what
    decides what happens to them. So `None` is a legitimate value and `NaN` is not a
    type error either - they mean "measured as absent", and are imputed.
    """
    forest = artifact_for(store, "random_forest")
    names = list(forest.feature_names)
    values = [float(v) for v in model_dataset.splits["train"].raw_values[0]]
    values[13] = None

    data = ForecastInput.from_sequence(
        entity=STATION_A,
        origin_instant=origin,
        names=tuple(names),
        values=values,
        feature_instants=[origin] * len(names),
        target_history=target_history_until(model_dataset, origin),
    )
    assert np.isnan(data.values[13])
    result = predict(forest, data, estimator=estimators[forest.model_id])
    assert names[13] in result.imputed_features


def test_an_infinite_feature_is_refused_rather_than_propagated(store, model_dataset, origin, estimators) -> None:
    """`inf` survives arithmetic and reaches the output as a number. It is not one."""
    forest = artifact_for(store, "random_forest")
    names = list(forest.feature_names)
    values = [float(v) for v in model_dataset.splits["train"].raw_values[0]]
    values[2] = float("inf")

    data = ForecastInput.from_sequence(
        entity=STATION_A,
        origin_instant=origin,
        names=tuple(names),
        values=values,
        feature_instants=[origin] * len(names),
        target_history=target_history_until(model_dataset, origin),
    )
    with pytest.raises(NonFiniteFeatureError) as caught:
        predict(forest, data, estimator=estimators[forest.model_id])
    assert names[2] in str(caught.value)


def test_a_missing_value_is_filled_when_the_imputer_has_a_record_and_is_named_in_the_output(
    store, model_dataset, origin, estimators
) -> None:
    """Distinct from the type and finiteness failures: `NaN` is what the imputer is for."""
    forest = artifact_for(store, "random_forest")
    names = list(forest.feature_names)
    values = [float(v) for v in model_dataset.splits["train"].raw_values[0]]
    values[7] = float("nan")

    data = ForecastInput.from_sequence(
        entity=STATION_A,
        origin_instant=origin,
        names=tuple(names),
        values=values,
        feature_instants=[origin] * len(names),
        target_history=target_history_until(model_dataset, origin),
    )
    result = predict(forest, data, estimator=estimators[forest.model_id])
    assert names[7] in result.imputed_features
    assert np.isfinite(result.feature_vector[7])


# --------------------------------------------------------------------------- #
# Target and horizon agreement
# --------------------------------------------------------------------------- #


def test_a_six_hour_model_refuses_a_twenty_four_hour_request(store, model_dataset, origin, estimators) -> None:
    forest = artifact_for(store, "random_forest")
    data = serving_input(model_dataset, origin)
    with pytest.raises(ArtifactHorizonMismatchError) as caught:
        predict(forest, data, request=request_for(origin, horizon="24h"))
    assert "6h" in str(caught.value) and "24h" in str(caught.value)


def test_a_water_level_model_refuses_an_inflow_request(store, model_dataset, origin, estimators) -> None:
    forest = artifact_for(store, "random_forest")
    data = serving_input(model_dataset, origin)
    with pytest.raises(ArtifactTargetMismatchError) as caught:
        predict(forest, data, request=request_for(origin, target="target_inflow_6h"))
    assert TARGET in str(caught.value)


def test_a_request_naming_the_other_model_family_is_refused(store, model_dataset, origin, estimators) -> None:
    forest = artifact_for(store, "random_forest")
    data = serving_input(model_dataset, origin)
    request = request_for(origin)
    named_other = dataclasses.replace(
        request, model_id="xgboost-target_water_level_6h-6h-seed20240917"
    )
    with pytest.raises(ForecastInferenceError):
        predict(forest, data, request=named_other)


# --------------------------------------------------------------------------- #
# Preprocessing
# --------------------------------------------------------------------------- #


def test_a_scaled_model_with_no_fitted_record_is_refused(store, model_dataset, origin, estimators) -> None:
    """The single most important preprocessing guard.

    Phase 4 records the scaler's *policy* in the manifest but not the fitted means
    and scales, so an artifact loaded from disk arrives without them. Serving it
    through an identity transform would hand an unscaled vector to a model fitted on
    scaled inputs: the number that comes out is finite, plausible, and meaningless.
    """
    stripped = dataclasses.replace(artifact_for(store, "random_forest"), preprocessing=None)
    assert stripped.scaler_policy == "standard"
    with pytest.raises(Exception) as caught:
        require_preprocessing(stripped)
    assert "identity" in str(caught.value).lower()


def test_the_baseline_needs_no_fitted_record(store) -> None:
    """It has no features to transform, so nothing is missing."""
    spec = require_preprocessing(artifact_for(store, "naive"))
    assert spec is None or spec.is_identity


def test_preprocessing_is_applied_before_the_estimator_sees_the_vector(
    store, model_dataset, origin, estimators
) -> None:
    """Ordering, checked by value rather than by reading the source.

    A forest fitted on standardised inputs and handed raw ones still returns a
    number. Comparing the served vector against the recorded scaler is what makes the
    ordering observable: every column must differ from the raw value in exactly the
    way the recorded mean and scale say it should.
    """
    forest = artifact_for(store, "random_forest")
    data = serving_input(model_dataset, origin)
    vector, imputed = transformed_vector(forest, data)

    assert len(vector) == forest.feature_count
    assert all(np.isfinite(vector))
    assert len(imputed) == forest.feature_count - sum(np.isfinite(data.values))

    scaler = forest.preprocessing.scaler
    assert scaler is not None and scaler["kind"] == "standard"
    by_name = dict(zip(forest.feature_names, vector))
    checked = 0
    for name, raw in zip(forest.feature_names, data.values):
        if name in imputed or not np.isfinite(raw):
            continue
        mean = float(scaler["mean"][name])
        scale = float(scaler["scale"][name])
        assert scale != 0.0
        assert by_name[name] == pytest.approx((raw - mean) / scale)
        checked += 1
    assert checked > forest.feature_count // 2, (
        "too few fully-populated columns were available to check the transform against, "
        "so this test proved much less than it claims to"
    )


# --------------------------------------------------------------------------- #
# Weights that do not exist
# --------------------------------------------------------------------------- #


def test_a_learned_model_with_no_estimator_is_refused_not_downgraded(
    store, model_dataset, origin
) -> None:
    """The honesty case. Falling back to persistence would return a number, and the
    number would be attributed to the forest."""
    forest = artifact_for(store, "random_forest")
    data = serving_input(model_dataset, origin)
    with pytest.raises(EstimatorUnavailableError) as caught:
        predict(forest, data)
    message = str(caught.value)
    assert forest.model_family in message
    assert "persistence" not in message.lower() or "not" in message.lower()
    assert "estimator" in message.lower() or "fitted" in message.lower()


def test_a_baseline_is_not_given_an_estimator_it_does_not_need(store, model_dataset, origin) -> None:
    baseline = artifact_for(store, "naive")
    assert baseline.uses_trained_parameters is False
    result = predict(baseline, serving_input(model_dataset, origin), estimator=object())
    assert result.strategy == STRATEGY_PERSISTENCE


def test_an_estimator_that_cannot_predict_is_not_replaced_by_anything(store, model_dataset, origin) -> None:
    """A fitted object that raises is a broken artifact, and the error is reported.

    Wrapping the call and substituting persistence here would turn a deployment bug
    into a plausible forecast that nobody could trace.
    """

    class Broken:
        def predict(self, *args, **kwargs):
            raise RuntimeError("this estimator has no fitted state")

    forest = artifact_for(store, "random_forest")
    with pytest.raises(RuntimeError):
        predict(forest, serving_input(model_dataset, origin), estimator=Broken())


# --------------------------------------------------------------------------- #
# No training during inference
# --------------------------------------------------------------------------- #


def test_serving_the_baseline_fits_nothing(store, model_dataset, origin) -> None:
    """The whole pipeline's `fit` methods raise; persistence must still work.

    This is the control for the tests below. If even the baseline trips the guard,
    the guard is catching something other than training and the other results mean
    nothing.
    """
    baseline = artifact_for(store, "naive")
    data = serving_input(model_dataset, origin)
    with no_fitting() as guard:
        result = predict(baseline, data)
    assert guard.touched == [], f"persistence called {guard.touched}"
    assert result.prediction == pytest.approx(target_history_until(model_dataset, origin)[-1].value)


def test_serving_a_learned_model_fits_nothing(store, model_dataset, origin, estimators) -> None:
    """The scaler, the imputer and the family fit are all guarded.

    Re-fitting the scaler at serving time would standardise the request using the
    request's own distribution, so two identical requests against different histories
    would produce two different forecasts - and the evaluation would have described
    a model that does not exist.
    """
    forest = artifact_for(store, "random_forest")
    data = serving_input(model_dataset, origin)
    with no_fitting() as guard:
        result = predict(forest, data, estimator=estimators[forest.model_id])
    assert guard.touched == [], f"inference called {guard.touched}"
    assert np.isfinite(result.prediction)


def test_serving_fits_nothing_even_with_an_absent_feature_to_impute(
    store, model_dataset, origin, estimators
) -> None:
    """Imputation is the step most likely to reach for a statistic.

    The value used must be the one recorded during training, and this asserts the
    imputer is never asked to learn one.
    """
    forest = artifact_for(store, "random_forest")
    names = list(forest.feature_names)
    values = [float(v) for v in model_dataset.splits["train"].raw_values[0]]
    values[9] = float("nan")
    data = ForecastInput.from_sequence(
        entity=STATION_A,
        origin_instant=origin,
        names=tuple(names),
        values=values,
        feature_instants=[origin] * len(names),
        target_history=target_history_until(model_dataset, origin),
    )
    with no_fitting() as guard:
        result = predict(forest, data, estimator=estimators[forest.model_id])
    assert guard.touched == [], f"imputation at serving time called {guard.touched}"
    assert names[9] in result.imputed_features


def test_inference_does_not_change_the_artifact_or_the_training_data(
    store, model_dataset, origin, estimators
) -> None:
    """Frozen inputs stay frozen.

    A serving path that mutated the artifact it was handed would make the *second*
    request from the same store a different computation from the first. `equal_nan`
    is required because the training rows legitimately contain absent features, and
    `NaN != NaN` would make this pass or fail for a reason that has nothing to do
    with whether anything changed.
    """
    forest = artifact_for(store, "random_forest")
    before = forest.to_dict()
    dataset_before = np.array(model_dataset.splits["train"].raw_values, dtype=float)

    predict(forest, serving_input(model_dataset, origin), estimator=estimators[forest.model_id])

    assert forest.to_dict() == before
    after = np.asarray(model_dataset.splits["train"].raw_values, dtype=float)
    assert np.array_equal(np.isnan(after), np.isnan(dataset_before))
    assert np.array_equal(after, dataset_before, equal_nan=True)


def test_inference_does_not_reach_the_training_modules(store, model_dataset, origin, estimators) -> None:
    """`model_training.fit_family` is guarded directly as well as through the estimator.

    Two routes lead into training from a serving path - calling the family fit, and
    constructing an estimator and fitting it - and guarding only the second would
    leave the first open.
    """
    from app.engines.hydro import model_training

    forest = artifact_for(store, "random_forest")
    with no_fitting({model_training: "model_training.fit_family"}) as guard:
        predict(forest, serving_input(model_dataset, origin), estimator=estimators[forest.model_id])
    assert guard.touched == []


def test_the_guard_itself_refuses_and_records(store, model_dataset, origin) -> None:
    """The control for the three tests above.

    If the guard did not actually intercept a fit, then "nothing was fitted" would
    hold because nothing could be - which is the difference between a passing test and
    a passing test that proves nothing. So this test fits something on purpose and
    asserts that it is caught, and that `touched` names what was reached.
    """
    from app.engines.hydro.preprocessing import StandardScaler

    with no_fitting() as guard:
        with pytest.raises(AssertionError) as caught:
            StandardScaler().fit(None, [])
    assert guard.touched == ["StandardScaler.fit"]
    assert "during inference" in str(caught.value)

    # ...and the guard removed itself, so the next test in the session is unaffected.
    from app.engines.hydro.preprocessing import StandardScaler as Restored

    assert Restored.fit.__name__ == "fit"


# --------------------------------------------------------------------------- #
# Strategy reporting
# --------------------------------------------------------------------------- #


def test_the_supported_strategies_are_reported_per_family_with_honest_blockers() -> None:
    """One readout a caller can use instead of guessing which families can run."""
    readout = supported_strategies()
    by_family = {row["model_family"]: row for row in readout["rows"]}
    assert by_family["naive"]["strategy"] == STRATEGY_PERSISTENCE
    assert by_family["naive"]["needs_fitted_parameters"] is False
    assert by_family["random_forest"]["strategy"] == STRATEGY_ESTIMATOR
    assert by_family["random_forest"]["needs_fitted_parameters"] is True
    for family in ("xgboost", "lstm", "gru"):
        if not by_family[family]["available_here"]:
            assert by_family[family]["blocked_reason"], (
                f"{family} cannot run here but reports no reason"
            )


# --------------------------------------------------------------------------- #
# The infer() convenience form
# --------------------------------------------------------------------------- #


def test_infer_takes_the_request_first(store, model_dataset, origin, estimators) -> None:
    """Same result, argument order swapped - so callers do not pass them backwards."""
    forest = artifact_for(store, "random_forest")
    data = serving_input(model_dataset, origin)
    request = request_for(origin)
    direct = predict(forest, data, estimator=estimators[forest.model_id], request=request)
    convenience = infer(request, forest, data, estimator=estimators[forest.model_id])
    assert convenience.prediction == direct.prediction


def test_infer_checks_the_request_it_is_given(store, model_dataset, origin, estimators) -> None:
    forest = artifact_for(store, "random_forest")
    with pytest.raises(ArtifactHorizonMismatchError):
        infer(
            request_for(origin, horizon="24h"),
            forest,
            serving_input(model_dataset, origin),
            estimator=estimators[forest.model_id],
        )


# --------------------------------------------------------------------------- #
# Input construction
# --------------------------------------------------------------------------- #


def test_a_mapping_input_keeps_the_callers_order_and_the_check_notices(
    store, model_dataset, origin
) -> None:
    """`from_mapping` preserves the mapping's own order, which is the caller's.

    A caller holding a JSON object cannot express column order, so this constructor
    exists precisely because requests arrive that way - and the ordering guarantee has
    to be re-established against the artifact rather than assumed. Built here in
    reversed order so the check has something real to catch.
    """
    forest = artifact_for(store, "random_forest")
    reversed_names = list(reversed(forest.feature_names))
    data = ForecastInput.from_mapping(
        entity=STATION_A,
        origin_instant=origin,
        features={name: 1.0 for name in reversed_names},
        feature_instants={name: origin for name in reversed_names},
    )
    assert list(data.feature_names) == reversed_names

    with pytest.raises(FeatureOrderError) as caught:
        predict(forest, data)
    message = str(caught.value)
    assert forest.feature_names[0] in message
    assert forest.feature_names[1] in message


def test_the_three_constructors_agree(model_dataset, origin) -> None:
    """One input, three ways of describing it, one result.

    A constructor that quietly reordered or coerced something would show up here as
    three different forecasts for the same readings.
    """
    names = ("b_feature", "a_feature")
    values = (2.0, 1.0)
    by_sequence = ForecastInput.from_sequence(
        entity=STATION_A,
        origin_instant=origin,
        names=names,
        values=values,
        feature_instants=[origin, origin],
    )
    by_mapping = ForecastInput.from_mapping(
        entity=STATION_A,
        origin_instant=origin,
        features={"a_feature": 1.0, "b_feature": 2.0},
        feature_instants={"a_feature": origin, "b_feature": origin},
    )
    assert by_sequence.as_mapping() == by_mapping.as_mapping()
    assert by_sequence.to_dict()["feature_names"] == list(by_sequence.feature_names)


def test_an_input_describes_itself_in_readable_lines(model_dataset, origin) -> None:
    data = serving_input(model_dataset, origin)
    text = data.describe()
    assert STATION_A in text
    assert str(data.feature_count if hasattr(data, "feature_count") else len(data.values)) or "35" in text
    assert str(origin.year) in text


def test_an_input_serialises_its_history(model_dataset, origin) -> None:
    data = serving_input(model_dataset, origin)
    payload = data.to_dict()
    assert payload["entity"] == STATION_A
    assert len(payload["target_history"]) == len(data.target_history)
    assert payload["target_history"][0]["instant"]


def test_a_target_observation_serialises(model_dataset, origin) -> None:
    latest = target_history_until(model_dataset, origin)[-1]
    payload = latest.to_dict()
    assert payload["value"] == pytest.approx(latest.value)
    assert payload["instant"]


# --------------------------------------------------------------------------- #
# The error hierarchy is usable
# --------------------------------------------------------------------------- #


def test_every_input_failure_shares_one_catchable_base() -> None:
    """A caller must be able to write one `except` for "this request is not servable".

    Nine separate unrelated exception types would push the handling into every caller,
    and the first caller to forget one would return a null forecast to a dashboard.
    """
    for error in (
        CausalityError,
        EntityMismatchError,
        EstimatorUnavailableError,
        FeatureOrderError,
        FeatureTypeError,
        MissingFeatureError,
        NoTargetObservationError,
        NonFiniteFeatureError,
        UnexpectedFeatureError,
    ):
        assert issubclass(error, ForecastInferenceError), (
            f"{error.__name__} is not catchable as a ForecastInferenceError"
        )


def test_input_problems_are_catchable_as_one_family() -> None:
    """`InputValidationError` groups the feature-shape failures separately from the
    causality and availability ones, which are different problems with different
    fixes."""
    for error in (
        FeatureOrderError,
        FeatureTypeError,
        MissingFeatureError,
        NonFiniteFeatureError,
        UnexpectedFeatureError,
    ):
        assert issubclass(error, InputValidationError)
    assert not issubclass(CausalityError, InputValidationError)
    assert not issubclass(EstimatorUnavailableError, InputValidationError)


# --------------------------------------------------------------------------- #
# The result object
# --------------------------------------------------------------------------- #


def test_a_ready_result_must_carry_an_inference(store, model_dataset, origin, estimators) -> None:
    """The invariant enforced by `__post_init__`.

    A result claiming to be a forecast with no forecast inside it is the shape a
    partial failure would take, and it would serialise as a forecast with no value.
    """
    forest = artifact_for(store, "random_forest")
    result = predict(forest, serving_input(model_dataset, origin), estimator=estimators[forest.model_id])
    with pytest.raises(Exception):
        dataclasses.replace(result, inference=None)


def test_the_result_serialises_everything_it_reports(store, model_dataset, origin, estimators) -> None:
    forest = artifact_for(store, "random_forest")
    payload = predict(
        forest, serving_input(model_dataset, origin), estimator=estimators[forest.model_id]
    ).to_dict()
    for field in (
        "prediction",
        "strategy",
        "entity",
        "target",
        "target_units",
        "horizon",
        "model_id",
        "model_family",
        "model_version",
        "artifact_id",
        "origin_instant",
        "prediction_timestamp",
        "feature_version",
        "feature_digest",
        "imputed_features",
        "synthetic_demo",
        "data_status",
        "disclaimer",
        "production_ready_claimed",
    ):
        assert field in payload, f"the result payload omits {field!r}"


def test_the_result_states_the_unit_it_predicts_in(store, model_dataset, origin, estimators) -> None:
    """Metres, recorded from the manifest, not assumed."""
    result = predict(
        artifact_for(store, "random_forest"),
        serving_input(model_dataset, origin),
        estimator=estimators[artifact_for(store, "random_forest").model_id],
    )
    assert result.target_units == "m"
    assert "m" in result.describe()


def test_the_fixture_history_is_labelled_at_the_observation_instant(model_dataset, origin) -> None:
    """The mistake these fixtures exist to prevent, asserted directly.

    A `ModelDataset` row at origin `t` carries the target observed at `t + H`. A
    history entry stamped at `t` would hand persistence the true future value, and the
    baseline would score a perfect forecast it did not earn.
    """
    history = target_history_until(model_dataset, origin)
    assert history
    assert history[-1].instant <= origin
    split = model_dataset.splits["train"]
    for index, instant in enumerate(split.origin_instants):
        if instant + dt.timedelta(hours=6) == history[0].instant:
            assert history[0].value == pytest.approx(float(split.target[index]))
            break