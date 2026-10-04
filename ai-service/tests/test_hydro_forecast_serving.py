# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 5 serving: one entry point, and no silent failure anywhere on it.

`serve()` is what a deployment actually calls, so it is what these tests exercise.
The properties pinned down here are the ones that survive contact with a real
caller:

* **a failure is a value, not an exception.** Every refusal comes back as a
  `ServedForecast` whose `status` says which of seven things went wrong. A serving
  boundary that raised would push the taxonomy into every caller, and the first
  caller to forget a branch returns a null forecast to a dashboard.
* **no status is a stand-in for a forecast.** Every status except `ready` carries a
  reason, and only `ready` carries an inference. A caller that reads `prediction`
  without reading `status` gets `None` rather than a number.
* **the training run is never touched.** `serve` with no `run_result` must produce a
  complete result from the artifact alone - the deployment path - and must not reach
  into Phase 4 to train or evaluate anything on the way.
* **the same request twice is the same answer twice.**
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest

from app.engines.hydro.contract import FORECAST_CONTRACT_VERSION, ForecastOutput
from app.engines.hydro.forecast_artifact import (
    STATE_ARTIFACT_MISSING,
    STATE_AVAILABLE,
    STATE_DEPENDENCY_BLOCKED,
    STATE_INVALID,
    STATE_NOT_EVALUABLE,
    ArtifactMissingError,
    ArtifactStore,
    ARTIFACT_STATES,
)
from app.engines.hydro.forecast_selection import SelectionDecision
from app.engines.hydro.forecast_serving import (
    SERVING_CONTRACT_VERSION,
    SERVING_STATUSES,
    UNAVAILABLE_STATUSES,
    ForecastServiceError,
    ServedForecast,
    default_forecast_id,
    prediction_timestamp_for,
    serve,
    serve_many,
    serving_contract_description,
    state_counts,
    status_for_error,
)
from app.engines.hydro.model_handoff import HANDOFF_STATUSES, HandoffResult

from hydro_phase5_fixtures import (
    HORIZON,
    STATION_A,
    STATION_B,
    SYNTHETIC_DISCLAIMER,
    TARGET,
    artifact,
    artifact_for,
    baseline_artifact,
    estimators,
    family_request,
    forecast_request,
    manifests,
    model_dataset,
    no_fitting,
    origin,
    preprocessing_for,
    request_for,
    serving_input,
    store,
    target_history_until,
    trained_run,
)

READY = "ready"


# --------------------------------------------------------------------------- #
# The two paths that can work
# --------------------------------------------------------------------------- #


def test_the_baseline_is_served_from_an_artifact_with_nothing_loaded(
    store, model_dataset, origin
) -> None:
    """The deployment path, end to end, with no weights anywhere.

    This is the case a deployment meets on day one: manifests on disk, no fitted
    parameters, and a request that can still be answered. The baseline answers it
    because its prediction rule reads only the target history the request carries -
    so nothing needs loading, and the answer is reproducible from what the request
    itself contained.
    """
    served = serve(
        family_request(origin),
        store=store,
        data=serving_input(model_dataset, origin),
    )

    assert served.status == READY
    assert served.reason is None
    assert served.inference is not None
    assert served.inference.prediction == pytest.approx(
        target_history_until(model_dataset, origin)[-1].value
    )
    assert served.forecast_id
    assert served.artifact is not None
    assert served.artifact.model_family == "naive"
    assert served.inference.strategy == "persistence"


def test_the_served_number_says_it_came_from_the_baseline(
    store, model_dataset, origin
) -> None:
    """A persistence forecast is not a model forecast, and must not read as one.

    Both facts are on the result: `strategy` names the rule that produced the value,
    and the artifact id names the artifact. A caller who forwards only the number has
    the second; a reviewer reading the payload has both.
    """
    served = serve(
        family_request(origin),
        store=store,
        data=serving_input(model_dataset, origin),
    )
    payload = served.to_dict()["forecast"]
    assert payload["model_family"] == "naive"
    assert payload["strategy"] == "persistence"
    assert "naive" in served.to_dict()["artifact_id"]
    assert payload["synthetic_demo"] is True
    assert payload["disclaimer"] == SYNTHETIC_DISCLAIMER


def test_a_family_named_in_the_request_is_honoured_over_the_selection(
    store, model_dataset, origin, estimators
) -> None:
    """A caller who asks for the baseline gets the baseline.

    Selection would have chosen the random forest, because its validation RMSE is
    lower. Substituting it would make the served model different from the requested
    one with nothing in the result saying so - and the caller's own logs would name a
    family it never got.
    """
    served = serve(
        family_request(origin, "naive"),
        store=store,
        data=serving_input(model_dataset, origin),
        estimators=estimators,
    )
    assert served.status == READY
    assert served.inference.model_family == "naive"
    assert served.selection is None, (
        "naming a family is not a selection decision, so no decision should be recorded as if "
        "Phase 5 had chosen"
    )


def test_a_family_with_no_artifact_is_refused_and_the_inventory_is_quoted(
    store, model_dataset, origin
) -> None:
    """The caller asked for a specific family and is told what exists instead.

    Not a fallback to a similar family: `lstm` and `xgboost` are not substitutes for
    one another, and neither is for a random forest.
    """
    served = serve(
        family_request(origin, "xgboost"),
        store=store,
        data=serving_input(model_dataset, origin),
    )
    # xgboost *is* in the store but is dependency-blocked, so the refusal is about
    # state rather than absence.
    assert served.status != READY
    assert served.inference is None
    assert "xgboost" in served.reason

    absent = serve(
        family_request(origin, "lstm"),
        store=store,
        data=serving_input(model_dataset, origin),
    )
    assert absent.status == "artifact_unavailable"
    assert absent.inference is None
    assert "lstm" in absent.reason
    assert "random_forest" in absent.reason, "the refusal should list what is available"


def test_a_family_matching_several_models_is_refused_as_ambiguous(
    store, model_dataset, origin
) -> None:
    """Two artifacts of one family, and the request named only the family.

    Choosing between them would make the answer depend on artifact ordering. So the
    caller is told to name one, and both ids are given so that is a copy-paste away.
    """
    twin = dataclasses.replace(
        artifact_for(store, "naive"),
        model_id="naive-target_water_level_6h-6h-seed20240918",
    )
    two = ArtifactStore(artifacts=(*store.artifacts, twin))

    served = serve(
        family_request(origin, "naive"),
        store=two,
        data=serving_input(model_dataset, origin),
    )
    assert served.status == "artifact_unavailable"
    assert served.inference is None
    assert "does not identify one" in served.reason
    assert twin.model_id in served.reason
    assert "model_id" in served.reason


def test_a_learned_model_is_served_when_its_weights_are_supplied(
    store, model_dataset, origin, estimators
) -> None:
    """The same request, with the fitted estimator resolved by the caller.

    Phase 4's weight-storage policy keeps fitted parameters out of the repository, so
    Phase 5 takes them as an argument rather than finding them. That boundary is
    deliberate and is what this test pins down: supply them and the learned model is
    used, and nothing else changes about the answer's shape.
    """
    served = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=serving_input(model_dataset, origin),
        estimators=estimators,
    )

    assert served.status == READY
    assert served.inference.strategy == "estimator"
    assert served.inference.model_family == "random_forest"


def test_an_anonymous_request_is_answered_by_selection_when_weights_are_supplied(
    store, model_dataset, origin, estimators
) -> None:
    """No model named: Phase 5 chooses, from validated metrics, and says so.

    The baseline is deliberately not a candidate - a persistence model would win any
    comparison it was allowed into, which would make the selection metric meaningless.
    """
    served = serve(
        request_for(origin),
        store=store,
        data=serving_input(model_dataset, origin),
        estimators=estimators,
    )
    assert served.status == READY
    assert served.inference.model_family == "random_forest"
    assert served.selection is not None
    assert served.selection.selected.artifact.model_id == served.inference.model_id
    assert served.selection.reason


def test_an_anonymous_request_is_refused_when_the_selected_model_has_no_weights(
    store, model_dataset, origin
) -> None:
    """The refusal that keeps Phase 5 honest, stated where it actually happens.

    Selection picks the random forest - it is the only eligible candidate - and its
    weights were never stored. So the answer is a refusal naming the forest, not a
    persistence number reported as the forest's forecast. The alternative would give
    a deployment with manifests but no weights a number from a model it never loaded.
    """
    served = serve(
        request_for(origin),
        store=store,
        data=serving_input(model_dataset, origin),
    )
    assert served.status == "artifact_unavailable"
    assert served.inference is None
    assert "random_forest" in served.reason
    assert "naive" not in served.reason.split(".")[0], (
        "the refusal names a fallback, which would be an invitation to take one"
    )
    # Selection did happen, and it is reported, so a caller can see what was chosen
    # and why nothing came of it.
    assert served.selection is not None
    assert served.selection.selected.artifact.model_family == "random_forest"


def test_the_result_names_itself_by_id_and_reports_what_it_used(
    store, model_dataset, origin
) -> None:
    """Every field the phase promises on the way out, present in the payload.

    The entity, target, horizon and units live in the nested `forecast` block and the
    decision-relevant metadata at the top level, so the assertion walks both - a
    caller reading only one of the two would miss half of what was promised.
    """
    served = serve(
        family_request(origin), store=store, data=serving_input(model_dataset, origin)
    )
    payload = served.to_dict()

    for field in (
        "serving_contract_version",
        "request",
        "status",
        "reason",
        "state",
        "artifact_id",
        "selection",
        "prediction",
        "prediction_timestamp",
        "forecast",
        "handoff",
        "forecast_output",
    ):
        assert field in payload, f"the served payload omits {field!r}"

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
        "feature_count",
        "feature_digest",
        "imputed_features",
        "preprocessing_applied",
        "uncertainty",
        "synthetic_demo",
        "data_status",
        "disclaimer",
        "production_ready_claimed",
    ):
        assert field in payload["forecast"], f"the forecast block omits {field!r}"

    for field in ("target", "horizon", "entity", "origin_instant", "model_id", "model_family"):
        assert field in payload["request"], f"the echoed request omits {field!r}"

    # The number appears in both places it is expected, and nowhere else.
    assert payload["prediction"] == payload["forecast"]["prediction"]
    assert payload["prediction_timestamp"] == payload["forecast"]["prediction_timestamp"]
    assert payload["artifact_id"] == payload["forecast"]["artifact_id"]


def test_a_served_forecast_describes_itself_in_readable_lines(
    store, model_dataset, origin
) -> None:
    served = serve(
        family_request(origin), store=store, data=serving_input(model_dataset, origin)
    )
    text = served.describe()
    assert STATION_A in text
    assert TARGET in text
    assert HORIZON in text
    assert SYNTHETIC_DISCLAIMER in text


# --------------------------------------------------------------------------- #
# What is *not* faked when something is missing
# --------------------------------------------------------------------------- #


def test_a_learned_model_whose_weights_are_absent_is_not_served_as_the_baseline(
    store, model_dataset, origin
) -> None:
    """The single most important refusal in the phase.

    Falling back to persistence would return a number, a timestamp and a status of
    `ready`. Everything would look right, and the number would be attributed to a
    model that was never loaded - so the log would show a random forest serving
    forecasts while a persistence baseline did the work.
    """
    request = request_for(origin, model_id=artifact_for(store, "random_forest").model_id)
    served = serve(request, store=store, data=serving_input(model_dataset, origin))

    assert served.status == "artifact_unavailable"
    assert served.inference is None
    assert "random_forest" in served.reason
    assert "fitted" in served.reason.lower() or "estimator" in served.reason.lower()


def test_a_request_for_a_model_the_store_has_never_heard_of_is_refused(
    store, model_dataset, origin
) -> None:
    """Phase 5 does not resolve a model by guessing at the nearest artifact."""
    request = request_for(origin, model_id="lstm-target_water_level_6h-6h-seed20240917")
    served = serve(request, store=store, data=serving_input(model_dataset, origin))

    assert served.status == "artifact_unavailable"
    assert served.inference is None
    assert "lstm" in served.reason
    # The inventory is quoted, so "you asked for something I do not have" is
    # distinguishable from "I have nothing at all".
    assert "random_forest" in served.reason


def test_an_empty_store_says_it_is_empty_rather_than_that_the_model_is_unknown(
    store, model_dataset, origin
) -> None:
    """Two very different deployment faults, and the message must not conflate them.

    An empty store means the deployment is pointed at the wrong directory. A store
    full of artifacts for other targets means the model was trained for something
    else. Both need a different fix, so the refusal distinguishes them.
    """
    empty = ArtifactStore(artifacts=())
    served = serve(
        request_for(origin), store=empty, data=serving_input(model_dataset, origin)
    )
    assert served.status == "model_unavailable"
    assert served.inference is None
    assert "store is empty" in served.reason
    assert "no artifacts at all" in served.reason

    # ...and a store with artifacts, all for the wrong horizon, says so.
    wrong_horizon = serve(
        request_for(origin, horizon="24h"),
        store=store,
        data=serving_input(model_dataset, origin),
    )
    assert wrong_horizon.status == "model_unavailable"
    assert "What it does hold" in wrong_horizon.reason
    assert "6h" in wrong_horizon.reason
    assert "dependency_blocked" in wrong_horizon.reason, (
        "the inventory should report blocked models too, or 'why is there no forecast for 24h?' "
        "cannot be answered from the refusal"
    )


def test_a_wrong_horizon_is_refused_and_the_available_horizons_are_named(
    store, model_dataset, origin
) -> None:
    """The most common configuration error, and the easiest to fix once stated."""
    served = serve(
        request_for(origin, horizon="24h"),
        store=store,
        data=serving_input(model_dataset, origin),
    )
    assert served.status != READY
    assert served.inference is None
    assert "24h" in served.reason
    assert "6h" in served.reason


def test_a_wrong_target_is_refused_by_name(store, model_dataset, origin) -> None:
    served = serve(
        request_for(origin, target="target_inflow_6h"),
        store=store,
        data=serving_input(model_dataset, origin),
    )
    assert served.status != READY
    assert served.inference is None
    assert "target_inflow_6h" in served.reason


def test_a_named_model_for_the_wrong_horizon_is_refused_by_name(
    store, model_dataset, origin
) -> None:
    """Naming a model bypasses selection, so the target/horizon check is the only gate.

    That gate has to work on its own. An artifact found by id but trained for `24h`
    cannot answer a `6h` request, and it is the artifact's own recorded horizon that
    says so.
    """
    served = serve(
        request_for(origin, model_id=artifact_for(store, "naive").model_id, horizon="24h"),
        store=store,
        data=serving_input(model_dataset, origin),
    )
    assert served.status == "invalid_request"
    assert served.inference is None
    assert "24h" in served.reason


def test_a_station_with_no_artifact_at_all_is_refused(store, model_dataset, origin) -> None:
    """`model_dataset` holds one entity, so a second station cannot be served.

    Reported rather than answered with the other station's data - see the
    cross-station test in the inference module for why that matters.
    """
    served = serve(
        request_for(origin, entity=STATION_B, model_family="naive"),
        store=store,
        data=serving_input(model_dataset, origin, entity=STATION_A),
    )
    assert served.status != READY
    assert served.inference is None


def test_a_baseline_with_no_target_history_is_refused_not_predicted(
    store, model_dataset, origin
) -> None:
    """Persistence with nothing to carry forward has no answer.

    The alternatives - the last value in the training split, zero, or the mean of an
    empty list - would each be a number attributed to a rule that did not produce it.
    """
    empty_history = serving_input(model_dataset, origin)
    served = serve(
        family_request(origin),
        store=store,
        data=dataclasses.replace(empty_history, target_history=()),
    )
    assert served.status == "insufficient_data"
    assert served.inference is None
    assert served.reason


def test_a_request_with_no_feature_data_is_refused_rather_than_predicted(
    store, model_dataset, origin, estimators
) -> None:
    """`data=None` means nobody supplied the readings.

    Reusing the training rows would produce a forecast from data the request never
    carried, and it would look like a real forecast.
    """
    request = request_for(origin, model_id=artifact_for(store, "random_forest").model_id)
    served = serve(request, store=store, data=None, estimators=estimators)
    assert served.status != READY
    assert served.inference is None


# --------------------------------------------------------------------------- #
# The status taxonomy
# --------------------------------------------------------------------------- #


def test_every_refusal_status_is_distinct_from_ready_and_carries_a_reason(
    store, model_dataset, origin
) -> None:
    """A caller that only reads `status` must be able to act on it.

    So: `ready` is the only status that carries a forecast, and every other status
    carries a reason. A status with neither would leave the caller to guess, which is
    the failure mode the whole structured-result design exists to remove.
    """
    cases = {
        "artifact_unavailable": serve(
            request_for(origin, model_id=artifact_for(store, "random_forest").model_id),
            store=store,
            data=serving_input(model_dataset, origin),
        ),
        "insufficient_data": serve(
            family_request(origin),
            store=store,
            data=dataclasses.replace(
                serving_input(model_dataset, origin), target_history=()
            ),
        ),
        "invalid_request": serve(
            request_for(origin, model_id=artifact_for(store, "naive").model_id, horizon="24h"),
            store=store,
            data=serving_input(model_dataset, origin),
        ),
        "model_unavailable": serve(
            request_for(origin), store=ArtifactStore(artifacts=()), data=None
        ),
    }
    for expected, served in cases.items():
        assert served.status == expected, f"expected {expected}, got {served.status}"
        assert served.status in UNAVAILABLE_STATUSES
        assert served.reason, f"{expected} came back with no reason"
        assert served.inference is None
        assert served.forecast_id, (
            f"{expected} has no forecast id, so two failures cannot be told apart in a log"
        )
        assert served.to_dict()["prediction"] is None


def test_ready_is_the_only_status_that_carries_a_forecast(
    store, model_dataset, origin
) -> None:
    """The invariant, asserted over the whole taxonomy rather than one case at a time.

    `UNAVAILABLE_STATUSES` is the contract: everything outside it must carry a
    forecast, and everything inside it must not. Checking the *sets* rather than
    individual requests is what makes a newly added status impossible to leave
    unclassified.
    """
    assert "ready" not in UNAVAILABLE_STATUSES
    assert UNAVAILABLE_STATUSES < set(SERVING_STATUSES)
    assert set(SERVING_STATUSES) - UNAVAILABLE_STATUSES == {"ready"}

    ready = serve(
        family_request(origin), store=store, data=serving_input(model_dataset, origin)
    )
    assert ready.status == "ready"
    assert ready.status not in UNAVAILABLE_STATUSES
    assert ready.inference is not None
    assert ready.reason is None


def test_an_error_maps_to_a_status_through_a_declared_table() -> None:
    """The mapping is data, so it can be read and reviewed rather than inferred.

    Each artifact-layer error maps to the status a caller would want, and an error
    that is not in the table is refused rather than defaulted - defaulting would give
    a new failure mode the status of an old one.
    """
    from app.engines.hydro.forecast_artifact import (
        ArtifactPreprocessingMismatchError,
    )
    from app.engines.hydro.forecast_inference import (
        CausalityError,
        EntityMismatchError,
        EstimatorUnavailableError,
        FeatureOrderError,
        MissingFeatureError,
        NoTargetObservationError,
        UnexpectedFeatureError,
    )

    assert status_for_error(ArtifactMissingError("x")) == "artifact_unavailable"
    assert status_for_error(EstimatorUnavailableError("x")) == "artifact_unavailable"
    assert status_for_error(NoTargetObservationError("x")) == "insufficient_data"
    assert status_for_error(CausalityError("x")) == "invalid_request"
    assert status_for_error(EntityMismatchError("x")) == "invalid_request"
    assert status_for_error(FeatureOrderError("x")) == "invalid_request"
    assert status_for_error(MissingFeatureError("x")) == "invalid_request"
    assert status_for_error(UnexpectedFeatureError("x")) == "invalid_request"
    assert status_for_error(ArtifactPreprocessingMismatchError("x")) == "invalid_request"


def test_a_blocked_dependency_is_named_as_such_rather_than_as_a_missing_artifact(
    store, model_dataset, origin, estimators
) -> None:
    """The two absences need opposite remedies, so they get different statuses.

    `dependency_unavailable` means the manifest is on disk and the library is not, so
    the fix is to install a package. `artifact_unavailable` means there is nothing to
    run at all. Reporting the second for the first sends whoever is on call to look for
    a manifest that already exists - and the refusal still *looks* correct, so nothing
    upstream flags it.

    Asserted end to end through `serve`, on the artifact whose recorded reason names
    the exact missing import, so the status and the reason agree with each other.
    """
    from app.engines.hydro.forecast_artifact import DependencyBlockedError

    blocked = store.by_state("dependency_blocked")
    assert blocked, "the fixture must contain a dependency-blocked artifact"
    blocked_artifact = blocked[0]
    assert blocked_artifact.dependency_versions, (
        "a blocked artifact that does not record its dependency versions cannot say what "
        "is missing"
    )
    assert not blocked_artifact.available
    assert DependencyBlockedError is not ArtifactMissingError

    served = serve(
        request_for(origin, model_id=blocked_artifact.model_id),
        store=store,
        data=serving_input(model_dataset, origin),
        estimators=estimators,
    )
    assert served.status == "dependency_unavailable"
    assert served.status != "artifact_unavailable"
    assert served.inference is None
    assert served.artifact.state == "dependency_blocked"
    # The reason names the missing library, so the status tells an operator where to go.
    assert blocked_artifact.reason in served.reason
    assert "not importable" in served.reason or "not installed" in served.reason

    # And the same is true through the family selector, which is how a caller who does
    # not know the model id reaches the same artifact.
    by_family = serve(
        family_request(origin, blocked_artifact.model_family),
        store=store,
        data=serving_input(model_dataset, origin),
        estimators=estimators,
    )
    assert by_family.status == "dependency_unavailable"


def test_every_declared_artifact_error_has_a_status_and_no_two_states_share_one_reason() -> None:
    """The mapping table is closed over the error hierarchy, and states stay distinct.

    Two properties, both of which have been violated by accident before:

    * *Closure* - every `ForecastArtifactError` and `ForecastInferenceError` subclass
      has an entry, so a new error cannot be added without someone deciding what a
      caller sees. `status_for_error` raises on an unmapped error rather than guessing,
      so an unmapped class would break requests at runtime instead of failing a test.
    * *Distinctness* - the five artifact states map onto statuses that a caller can
      tell apart, so `state_counts` and a refusal log mean the same thing.
    """
    from app.engines.hydro import forecast_inference as inference_module
    from app.engines.hydro.forecast_artifact import (
        ForecastArtifactError,
        handoff_status_for_state,
    )

    def all_subclasses(root: type) -> set[type]:
        found = set()
        pending = [root]
        while pending:
            current = pending.pop()
            for child in current.__subclasses__():
                if child not in found:
                    found.add(child)
                    pending.append(child)
        return found

    unmapped = sorted(
        error.__name__
        for error in all_subclasses(ForecastArtifactError) | all_subclasses(
            inference_module.ForecastInferenceError
        )
        if isinstance(error(), Exception)
    )
    assert unmapped, "no artifact error classes were found; the walk is broken"
    # Every one resolves through the same walk `status_for_error` performs.
    for name in unmapped:
        error_type = next(
            cls
            for cls in (
                all_subclasses(ForecastArtifactError)
                | all_subclasses(inference_module.ForecastInferenceError)
            )
            if cls.__name__ == name
        )
        assert status_for_error(error_type("probe")) in SERVING_STATUSES, name

    # And the two absences that call for opposite remedies stay apart. `invalid` and
    # `not_evaluable` do share `invalid_request` - Phase 4's handoff vocabulary has no
    # separate word for "this artifact was never evaluable" - and that is acceptable
    # only because the exact state travels on the refusal, which the end-to-end check
    # below pins.
    by_state = {state: handoff_status_for_state(state) for state in ARTIFACT_STATES}
    assert by_state["available"] == "ready"
    assert by_state["dependency_blocked"] == "dependency_unavailable"
    assert by_state["artifact_missing"] == "artifact_unavailable"
    assert by_state["dependency_blocked"] != by_state["artifact_missing"], (
        "a missing library and a missing artifact report the same refusal"
    )


def test_a_refusal_carries_the_exact_artifact_state_not_only_a_status(
    store, model_dataset, origin, estimators, artifact
) -> None:
    """Where two states share a status, the state itself has to survive the refusal.

    `invalid` and `not_evaluable` both report `invalid_request`, because the handoff
    vocabulary has one word for "this artifact will not serve" and inventing a second
    would mean a reader translating between two vocabularies. The distinction is not
    lost - it is on `ServedForecast.artifact.state` - so a caller can still tell "this
    model was never evaluable" from "this artifact is corrupt", which are very
    different facts about a training run.

    Asserted by serving two artifacts whose states differ but whose status is the same.
    """
    not_evaluable = dataclasses.replace(
        artifact,
        model_id="random_forest-unevaluated",
        artifact_id="random_forest-unevaluated",
        state="not_evaluable",
        reason="this artifact carries no validated evaluation result for any split",
    )
    corrupt = dataclasses.replace(
        artifact,
        model_id="random_forest-invalid",
        artifact_id="random_forest-invalid",
        state="invalid",
        reason="this artifact failed its own manifest consistency checks",
    )
    assert not_evaluable.state != corrupt.state

    combined = ArtifactStore(
        artifacts=(*store.artifacts, not_evaluable, corrupt),
    )
    data = serving_input(model_dataset, origin)

    statuses = set()
    states = set()
    for candidate in (not_evaluable, corrupt):
        served = serve(
            request_for(origin, model_id=candidate.model_id),
            store=combined,
            data=data,
            estimators=estimators,
        )
        statuses.add(served.status)
        states.add(served.artifact.state)
        assert served.inference is None
        assert candidate.reason in served.reason, (
            "the artifact's own recorded reason must reach the caller unchanged: "
            f"{served.reason}"
        )

    assert statuses == {"invalid_request"}
    assert states == {"not_evaluable", "invalid"}, (
        "two artifacts with the same refusal status reported the same state, so one of "
        "them lost its identity on the way out"
    )


def test_an_unmapped_error_is_refused_rather_than_assigned_a_status() -> None:
    """`KeyError` from anywhere in the stack has no honest status.

    Giving it `invalid_request` would file a server bug as the caller's fault, and
    the caller would go looking for a malformed request that does not exist.
    """
    with pytest.raises(ForecastServiceError) as caught:
        status_for_error(KeyError("something unrelated"))
    assert "KeyError" in str(caught.value)
    assert "invalid_request" not in str(caught.value), (
        "the refusal named a status, which is what this test is checking it does not do"
    )


def test_the_error_to_status_table_is_published_with_the_contract() -> None:
    """A table only used by the code that owns it is a table nobody can review."""
    described = serving_contract_description()
    mapping = described["error_to_status"]
    assert mapping, "the contract publishes no error-to-status mapping"
    for name, status in mapping.items():
        assert status in SERVING_STATUSES, f"{name} maps to an undeclared status {status!r}"


# --------------------------------------------------------------------------- #
# The enriched result, and what is honestly absent from it
# --------------------------------------------------------------------------- #


def test_a_result_without_a_training_run_has_no_handoff_and_no_output(
    store, model_dataset, origin
) -> None:
    """The deployment path: the optional enrichments are absent, not fabricated.

    A `HandoffResult` cannot be produced without the `RunResult` it summarises, and a
    `ForecastOutput` cannot be produced without the handoff. Inventing either would
    mean inventing the metrics and provenance that sit inside them.
    """
    served = serve(
        family_request(origin), store=store, data=serving_input(model_dataset, origin)
    )
    assert served.status == READY
    assert served.inference is not None
    assert served.handoff is None
    assert served.output is None
    assert served.to_dict()["handoff"] is None
    assert served.to_dict()["forecast_output"] is None


def test_a_result_with_a_training_run_carries_the_handoff_and_the_output(
    store, model_dataset, origin, estimators, trained_run, manifests
) -> None:
    """...and with one, the enrichments are real.

    Same code path, same result shape, one more input - which is what makes the
    absences above meaningful rather than merely unimplemented.
    """
    served = serve(
        request_for(origin, model_id=artifact_for(store, "random_forest").model_id),
        store=store,
        data=serving_input(model_dataset, origin),
        estimators=estimators,
        run_result=trained_run,
        manifests=manifests,
    )
    assert served.status == READY
    assert isinstance(served.handoff, HandoffResult)
    assert served.handoff.status in HANDOFF_STATUSES
    assert isinstance(served.output, ForecastOutput)
    assert served.output.predicted_value == pytest.approx(served.inference.prediction)
    assert served.output.target_units == served.inference.target_units


def test_the_handoff_and_the_output_agree_with_the_inference(
    store, model_dataset, origin, estimators, trained_run, manifests
) -> None:
    """Three objects reporting one number must report the *same* number.

    Nothing here recomputes anything: the handoff is enriched with the Phase 5
    inference and the output is derived from the handoff. Asserted rather than
    assumed, because a divergence would mean the value the platform stores differs
    from the value the model produced.
    """
    served = serve(
        request_for(origin, model_id=artifact_for(store, "random_forest").model_id),
        store=store,
        data=serving_input(model_dataset, origin),
        estimators=estimators,
        run_result=trained_run,
        manifests=manifests,
    )
    prediction = served.inference.prediction
    assert served.output.predicted_value == pytest.approx(prediction)
    assert served.handoff.prediction == pytest.approx(prediction)
    # The platform output uses its own vocabulary - `forecast_horizon`,
    # `station_reference` - so the correspondence is asserted field by field rather
    # than assumed. A silent rename on either side would show up here.
    assert served.output.forecast_horizon == served.inference.horizon
    assert served.output.station_reference == served.inference.entity
    assert served.output.target == served.inference.target
    assert served.output.target_units == served.inference.target_units
    assert served.output.model_id == served.inference.model_id
    assert served.output.model_version == served.inference.model_version
    assert served.output.forecast_timestamp == served.inference.prediction_timestamp
    # Not `served.status`: the platform contract has its own vocabulary, where a
    # produced forecast is `completed`. Asserting the two strings agree would be
    # asserting a coincidence, not a contract.
    assert served.output.status == "completed"
    assert served.handoff.status == "ready"
    assert served.handoff.entity == served.inference.entity
    assert served.handoff.model_id == served.inference.model_id
    assert served.handoff.model_family == served.inference.model_family
    assert served.handoff.target_units == served.inference.target_units
    assert served.handoff.prediction_timestamp == served.inference.prediction_timestamp
    assert served.output.contract_version == FORECAST_CONTRACT_VERSION


def test_the_prediction_timestamp_is_present_even_with_no_training_run(
    store, model_dataset, origin
) -> None:
    """It comes from the origin and the horizon, which a request always has.

    Withholding it because the deployment happens to have no `RunResult` would make a
    perfectly well-defined timestamp depend on the serving path taken.
    """
    served = serve(
        family_request(origin), store=store, data=serving_input(model_dataset, origin)
    )
    expected = (origin + dt.timedelta(hours=6)).isoformat().replace("+00:00", "Z")
    assert served.inference.prediction_timestamp == expected
    assert served.to_dict()["prediction_timestamp"] == expected


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_the_same_request_is_answered_the_same_way_every_time(
    store, model_dataset, origin
) -> None:
    request = family_request(origin)
    data = serving_input(model_dataset, origin)
    answers = [serve(request, store=store, data=data) for _ in range(5)]

    assert len({a.inference.prediction for a in answers}) == 1
    assert len({a.forecast_id for a in answers}) == 1
    assert len({a.status for a in answers}) == 1
    assert len({a.reason for a in answers}) == 1


def test_the_served_payload_is_byte_identical_across_repeated_calls(
    store, model_dataset, origin, estimators
) -> None:
    """The whole payload, not just the number.

    `created_at` is the one field a naive implementation would let a clock into, and
    it is the field that would make two identical requests look different in a diff.
    """
    request = request_for(origin, model_id=artifact_for(store, "random_forest").model_id)
    payloads = [
        serve(
            request,
            store=store,
            data=serving_input(model_dataset, origin),
            estimators=estimators,
        ).to_dict()
        for _ in range(3)
    ]
    assert payloads[0] == payloads[1] == payloads[2]


def test_the_forecast_id_is_derived_from_the_request_not_from_a_clock(
    store, model_dataset, origin
) -> None:
    """Two identical requests produce one id; a different request produces another.

    A UUID per call would make the same forecast unreferenceable, and a timestamp
    alone would collide for two gauges forecasting the same horizon.
    """
    first = default_forecast_id(request_for(origin))
    second = default_forecast_id(request_for(origin))
    assert first == second
    assert first != default_forecast_id(request_for(origin, entity=STATION_B))
    assert first != default_forecast_id(request_for(origin, horizon="24h"))
    assert first != default_forecast_id(request_for(origin, target="target_inflow_6h"))


def test_a_caller_supplied_forecast_id_is_used_verbatim(
    store, model_dataset, origin
) -> None:
    """So a caller can correlate a forecast with its own work order.

    ...and it reaches the payload, because an id the caller cannot read back is not
    usable for correlation.
    """
    served = serve(
        family_request(origin),
        store=store,
        data=serving_input(model_dataset, origin),
        forecast_id="WORK-1234",
    )
    assert served.forecast_id == "WORK-1234"
    assert served.to_dict()["forecast_id"] == "WORK-1234"


def test_serving_never_mutates_the_store_it_answers_from(
    store, model_dataset, origin, estimators
) -> None:
    """The store is frozen, and this is the check that keeps it that way.

    A serving path that appended its artifacts to its own registry would make the
    second request a different computation from the first.
    """
    before = tuple(store.artifacts)
    served = serve(
        request_for(origin, model_id=artifact_for(store, "random_forest").model_id),
        store=store,
        data=serving_input(model_dataset, origin),
        estimators=estimators,
    )
    assert served.status == READY
    assert tuple(store.artifacts) == before
    assert len(store.artifacts) == len(before)


# --------------------------------------------------------------------------- #
# No training during serving
# --------------------------------------------------------------------------- #


def test_serving_fits_nothing(store, model_dataset, origin, estimators) -> None:
    """The end-to-end version of the inference guard.

    `serve` reaches artifact selection, preprocessing and prediction, so it is the
    function that would break if any of those three started fitting.
    """
    request = request_for(origin, model_id=artifact_for(store, "random_forest").model_id)
    with no_fitting() as guard:
        served = serve(
            request,
            store=store,
            data=serving_input(model_dataset, origin),
            estimators=estimators,
        )
    assert guard.touched == [], f"serving called {guard.touched}"
    assert served.status == READY


def test_serving_the_baseline_fits_nothing_either(store, model_dataset, origin) -> None:
    request = family_request(origin)
    with no_fitting() as guard:
        served = serve(request, store=store, data=serving_input(model_dataset, origin))
    assert guard.touched == []
    assert served.status == READY


def test_a_refused_request_fits_nothing_on_the_way_to_being_refused(
    store, model_dataset, origin
) -> None:
    """The refusal path is the one nobody reviews.

    A handler that built a fallback model, or refitted a scaler "just in case",
    would do it here - where there is no forecast to inspect for a suspicious number.
    """
    request = request_for(origin, model_id=artifact_for(store, "random_forest").model_id)
    with no_fitting() as guard:
        served = serve(request, store=store, data=serving_input(model_dataset, origin))
    assert guard.touched == []
    assert served.status == "artifact_unavailable"


# --------------------------------------------------------------------------- #
# serve_many
# --------------------------------------------------------------------------- #


def test_a_batch_of_requests_is_answered_in_order(store, model_dataset, origin, estimators) -> None:
    """Order is the caller's only correlation handle, so it is preserved exactly."""
    requests = [
        family_request(origin),
        family_request(origin, "random_forest"),
        request_for(origin, model_id="lstm-target_water_level_6h-6h-seed20240917"),
    ]
    served = serve_many(
        requests,
        store=store,
        data=serving_input(model_dataset, origin),
        estimators=estimators,
    )
    assert len(served) == len(requests)
    assert [s.status for s in served] == [
        READY,
        READY,
        "artifact_unavailable",
    ]


def test_one_failure_in_a_batch_does_not_stop_the_rest(store, model_dataset, origin) -> None:
    """A batch of ten where three fail must answer ten.

    Aborting on the first refusal would make the batch caller's only alternative to
    give up on batching - and the failures are exactly the part they need reported.
    """
    requests = [family_request(origin) for _ in range(3)]
    requests.insert(1, request_for(origin, horizon="24h"))
    served = serve_many(
        requests, store=store, data=serving_input(model_dataset, origin)
    )
    assert [s.status for s in served] == [
        READY,
        "model_unavailable",
        READY,
        READY,
    ]


def test_an_empty_batch_is_an_empty_answer(store) -> None:
    assert serve_many([], store=store) == ()


# --------------------------------------------------------------------------- #
# The published contract
# --------------------------------------------------------------------------- #


def test_the_serving_contract_declares_everything_a_caller_needs() -> None:
    """A versioned, self-describing contract, so integration is reading rather than
    reading source.

    Every status is declared, every artifact state maps to one, and the validation
    order is published - because the order is what makes a refusal reproducible, and a
    caller debugging a refusal needs to know which check fired first.
    """
    described = serving_contract_description()

    assert described["serving_contract_version"] == SERVING_CONTRACT_VERSION
    assert set(described["statuses"]) == set(SERVING_STATUSES)
    assert set(described["artifact_states"]) == set(ARTIFACT_STATES)
    assert set(described["status_for_state"]) == set(ARTIFACT_STATES)
    for state, status in described["status_for_state"].items():
        assert status in SERVING_STATUSES, f"{state} maps to an undeclared status"

    assert described["validation_order"], "the contract publishes no validation order"
    assert described["request_fields"], "the contract lists no request fields"
    assert described["result_fields"], "the contract lists no result fields"
    assert described["integration_statement"], "the contract states no integration scope"
    # The synthetic-data caveat is part of the machine-readable contract, not only of
    # the Markdown, because this is what an integrator reads.
    assert SYNTHETIC_DISCLAIMER in described["data_status_statement"]
    assert "production-ready" in described["data_status_statement"]

    # Every published result field is actually on the payload, so the contract cannot
    # advertise a field that does not exist.
    payload = serve(
        family_request(dt.datetime(2024, 1, 4, tzinfo=dt.timezone.utc)),
        store=ArtifactStore(artifacts=()),
        data=None,
    ).to_dict()
    for field in described["result_fields"]:
        assert field in payload, f"the contract advertises {field!r}, which is not on the payload"


def test_state_counts_summarises_the_store_without_hiding_a_blocked_model(
    store,
) -> None:
    """The one-line summary a health endpoint wants.

    Asserted against every declared state so a new state cannot be added without also
    being counted - which is how a blocked model goes missing from a dashboard.
    """
    counts = state_counts(store)
    assert set(counts) == set(ARTIFACT_STATES)
    assert counts[STATE_AVAILABLE] == 2
    assert counts[STATE_DEPENDENCY_BLOCKED] == 1
    assert sum(counts.values()) == len(store.artifacts)
    assert counts[STATE_INVALID] == 0
    assert counts[STATE_ARTIFACT_MISSING] == 0
    assert counts[STATE_NOT_EVALUABLE] == 0


# --------------------------------------------------------------------------- #
# The result object
# --------------------------------------------------------------------------- #


def test_a_served_forecast_cannot_claim_to_be_ready_without_a_forecast() -> None:
    """The invariant `ServedForecast.__post_init__` enforces.

    A result whose `status` is `ready` and whose `inference` is `None` is the exact
    shape a partial failure takes, and it serialises as a forecast with no value in
    it - which a caller checking `status` alone would forward as a real forecast.
    """
    request = request_for(dt.datetime(2024, 1, 4, tzinfo=dt.timezone.utc))
    with pytest.raises(ForecastServiceError) as caught:
        ServedForecast(
            request=request,
            status=READY,
            reason=None,
            inference=None,
            handoff=None,
            output=None,
            selection=None,
            artifact=None,
            artifact_id=None,
            state=None,
            forecast_id="x",
        )
    assert "nothing behind it" in str(caught.value)


def test_a_refusal_cannot_carry_a_value(store, model_dataset, origin) -> None:
    """The mirror image, and the more dangerous of the two.

    A refusal carrying a number is how a caller ends up serving the wrong value with
    the right error code - the error is logged, the number is displayed, and nothing
    flags the combination. So it is refused at construction.
    """
    ready = serve(
        family_request(origin), store=store, data=serving_input(model_dataset, origin)
    )
    with pytest.raises(ForecastServiceError) as caught:
        dataclasses.replace(ready, status="artifact_unavailable", reason="no")
    assert "wrong number" in str(caught.value)

    # ...and the object as served is consistent.
    assert ready.status == READY
    assert ready.inference is not None
    assert ready.reason is None


def test_an_unknown_status_is_refused_rather_than_passed_through() -> None:
    """A typo in a status would otherwise serialise as a status nothing understands."""
    request = request_for(dt.datetime(2024, 1, 4, tzinfo=dt.timezone.utc))
    with pytest.raises(ForecastServiceError) as caught:
        ServedForecast(
            request=request,
            status="READY",  # the case is what a caller writes by mistake
            reason=None,
            inference=None,
            handoff=None,
            output=None,
            selection=None,
            artifact=None,
            artifact_id=None,
            state=None,
            forecast_id="x",
        )
    assert "unknown serving status" in str(caught.value)
    assert "ready" in str(caught.value), "the refusal should list the statuses it knows"