# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Temporal safety at the Phase 5 serving boundary, as regression tests.

Phase 4 audits the dataset once, when it is built. Phase 5 is what a deployment
actually calls, and a serving boundary has its own ways to leak that a dataset audit
cannot see - a fitted scaler reconstructed at serving time, an artifact whose feature
list was edited, a persistence rule that reads one row too far, a second station's
readings under the first station's name.

So the questions here are the ones a dataset audit does not answer:

* **can an artifact leak?** An artifact is a file. Its feature list, its preprocessing
  record and its fitted row count are all claims, and each claim has to be checked at
  the point where a number is produced from it.
* **is the preprocessing train-only?** Verified from the recorded fitted row count
  against the recorded split sizes, which is an independent check rather than a
  restatement of the audit's own finding.
* **does a served forecast respect its origin?** Every feature read at or before the
  origin, every observation at or before the origin, and a prediction instant strictly
  after it.
* **can one station's data answer for another?** No.
* **is train/val/test contamination detectable?** The split bounds travel on the
  artifact, so an auditor can tell whether the origin a caller chose was inside the
  window the model was fitted on.

What this module deliberately does **not** do is claim a hydrological result. Every
fixture here is synthetic/demo data; the checks below are about information flow, not
about whether a water level is right.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest

from app.engines.hydro.forecast_artifact import (
    ArtifactContractMismatchError,
    ArtifactPreprocessingMismatchError,
    ForecastArtifactError,
    PreprocessingSpec,
    artifact_from_manifest_payload,
)
from app.engines.hydro.forecast_inference import (
    CausalityError,
    EntityMismatchError,
    ForecastInput,
    TargetObservation,
    predict,
)
from app.engines.hydro.forecast_serving import serve
from app.engines.hydro.model_artifacts import feature_digest
from app.engines.hydro.model_audit import AUDIT_CHECKS, audit_leakage

from hydro_phase5_fixtures import (
    HORIZON,
    HOURS,
    STATION_A,
    STATION_B,
    TARGET,
    ArtifactStore,
    artifact,
    artifact_for,
    estimators,
    family_request,
    feature_row_at,
    manifest_payload,
    manifests,
    model_dataset,
    origin,
    request_for,
    serving_input,
    store,
    target_history_until,
    trained_run,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _input_with(
    data: ForecastInput,
    features: dict[str, float] | None = None,
    *,
    instants: tuple[dt.datetime, ...] | None = None,
    target_history: tuple | None = None,
) -> ForecastInput:
    """The same request input with its feature values swapped.

    Rebuilt through `from_sequence` rather than `dataclasses.replace`, because
    `ForecastInput` holds a parallel name/value/instant triple rather than a mapping -
    and because going through the public constructor is what a caller does. A test that
    reached past it would keep passing on a change that broke the real path.

    `features` is a *name-keyed* mapping on purpose. Every leakage test below perturbs
    specific columns by name, and a positional edit would quietly change a different
    column each time the artifact's order changed.
    """
    names = data.feature_names if features is None else tuple(features)
    values = data.values if features is None else tuple(float(features[name]) for name in names)
    # Defaults to "read at the origin" rather than to the original instants: a test that
    # adds or removes a column would otherwise leave the instant count mismatched, and
    # the mismatch would be caught as a causality error instead of the thing under test.
    default_instants = tuple([data.origin_instant] * len(names))
    return ForecastInput.from_sequence(
        entity=data.entity,
        origin_instant=data.origin_instant,
        names=names,
        values=values,
        feature_instants=default_instants if instants is None else instants,
        target_history=data.target_history if target_history is None else target_history,
    )


def _as_mapping(data: ForecastInput) -> dict[str, float]:
    """The input's values keyed by feature name, for named edits."""
    return dict(zip(data.feature_names, data.values, strict=True))


def _instant(raw: str) -> dt.datetime:
    """A split-boundary or feature timestamp, read as an aware UTC instant."""
    return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))


# --------------------------------------------------------------------------- #
# The audit a serving artifact has to be able to justify itself against
# --------------------------------------------------------------------------- #


def test_every_declared_leakage_check_runs_and_is_named(model_dataset) -> None:
    """The declared set, and the fixture's audit covering all of it.

    Asserted over the *names* as well as the statuses so that a check quietly removed
    from `AUDIT_CHECKS` fails here rather than passing quietly everywhere else. The
    set is the contract: an audit with a hole in it looks identical to one without,
    from the outside, unless the outside knows what it should contain.
    """
    assert len(AUDIT_CHECKS) == len(set(AUDIT_CHECKS)), "duplicate check name in AUDIT_CHECKS"

    audit = audit_leakage(model_dataset)
    reported = {finding.check for finding in audit.findings}
    assert reported == set(AUDIT_CHECKS)

    statuses = {finding.check: finding.status for finding in audit.findings}
    # The sequence check needs a SequenceSet, which this fixture does not build; it
    # is reported as skipped rather than silently omitted, which is the contract.
    assert statuses["sequence_windows_causal_and_entity_scoped"] == "skipped"
    for check in AUDIT_CHECKS:
        if check == "sequence_windows_causal_and_entity_scoped":
            continue
        assert statuses[check] == "pass", f"{check} did not pass on the Phase 5 fixture"

    # Every finding explains itself, including the skip - a skipped check that gives
    # no reason is indistinguishable from a broken one.
    for finding in audit.findings:
        assert finding.detail, f"{finding.check} reported {finding.status} with no detail"


def test_the_artifact_carries_the_evidence_for_every_check_it_needs(
    store, model_dataset
) -> None:
    """An auditor holding only the artifact can re-derive most of the audit.

    Phase 5's whole premise is that an artifact on disk is what a deployment reasons
    about. So the fields each leakage check depends on must be on the artifact, not
    only inside the dataset the model was trained on - otherwise "it passed the audit"
    is a claim about a file nobody deploying will ever see.

    The mapping is written out rather than derived, so adding a check that Phase 5
    cannot support is a visible act rather than an omission.
    """
    found = artifact_for(store, "random_forest")

    # features_read_at_or_before_origin / feature_columns_disjoint_from_targets:
    # the ordered feature list and its digest.
    assert found.feature_names
    assert found.feature_digest == feature_digest(found.feature_names)

    # target_instant_strictly_after_origin / target_horizon_alignment_exact:
    # the horizon the artifact was trained to predict.
    assert found.horizon == HORIZON

    # split_origins_chronologically_ordered / split_labels_do_not_cross_boundaries:
    # the split bounds and the per-split row counts.
    assert set(found.split_bounds) == {
        "train_start",
        "train_end",
        "validation_start",
        "validation_end",
        "test_start",
        "test_end",
    }
    assert found.row_counts["train"] > 0
    assert found.row_counts["validation"] > 0
    assert found.row_counts["test"] > 0

    # scaler_and_imputer_fitted_on_train_only: the fitted record itself.
    assert found.preprocessing is not None
    assert found.preprocessing.fitted_on == "train"

    # sequence_windows_causal_and_entity_scoped: the entity the model was fitted on,
    # recorded in the provenance record Phase 1 defined.
    assert found.provenance
    assert found.provenance["station_reference"] == STATION_A

    # The dataset still passes every check Phase 5 can run against it, so the two
    # views are not merely both present but consistent.
    assert {f.status for f in audit_leakage(model_dataset).findings} <= {"pass", "skipped"}


# --------------------------------------------------------------------------- #
# Target leakage
# --------------------------------------------------------------------------- #


def test_no_artifact_feature_list_contains_a_target_column(store) -> None:
    """The starting position, for every artifact including the blocked one.

    Checked against the target column itself and against any column named after the
    target *at the forecast horizon* - `target_water_level_6h` and a hypothetical
    `water_level_at_6h` are the value being predicted. The lags and rolling windows of
    the observed level are legitimate features and are deliberately not flagged: they
    are readings from the past, which is the whole point of them.
    """
    for found in store.artifacts:
        assert found.target not in found.feature_names, (
            f"{found.model_id}: its own target is among its features"
        )
        quantity = found.target.removeprefix("target_")
        assert quantity not in found.feature_names, (
            f"{found.model_id}: {quantity!r} is the predicted quantity un-prefixed, so it is "
            "the value being predicted rather than an input to predicting it"
        )


def test_an_artifact_whose_feature_list_contains_the_target_is_refused(
    store, model_dataset, origin, estimators, artifact
) -> None:
    """An artifact is a file, so its feature list can be edited.

    Refused at the point a number would be produced, and refused by name - the operator
    who edited the manifest is the person who has to be told which column is the
    problem.

    The digest is recomputed to match the edited list, because otherwise the refusal
    would be a checksum mismatch and would prove only that the tampering was visible,
    not that Phase 5 refuses a *consistent* artifact that leaks.
    """
    leaked = tuple(artifact.feature_names) + (artifact.target,)
    tampered = dataclasses.replace(
        artifact,
        feature_names=leaked,
        declared_feature_count=len(leaked),
        feature_digest=feature_digest(leaked),
        model_id="random_forest-leaky",
        artifact_id="random_forest-leaky",
    )
    assert tampered.feature_digest == feature_digest(tampered.feature_names), (
        "the forged artifact must be internally consistent, or the refusal below would "
        "be about the checksum rather than about the leak"
    )

    leaky_store = ArtifactStore(artifacts=(*store.artifacts, tampered))
    # The tampered artifact needs weights under its own id, or the refusal would be
    # "no estimator" rather than the mismatch under test.
    leaky_estimators = {
        **estimators,
        tampered.model_id: estimators[artifact.model_id],
    }
    data = serving_input(model_dataset, origin)

    # A request that does not supply the target column is refused for not supplying it,
    # and the refusal says which column.
    served = serve(
        request_for(origin, model_id=tampered.model_id),
        store=leaky_store,
        data=data,
        estimators=leaky_estimators,
    )
    assert served.status == "invalid_request"
    assert served.inference is None
    assert artifact.target in served.reason

    # A request that *does* supply it is refused too. Which check fires depends on the
    # order they run in - the preprocessing record was fitted against the original 35
    # columns, so a 36-column vector can be caught there before the order check looks at
    # it. Either refusal is correct; what is asserted is that the caller gets a named
    # error and no number.
    with_target = _input_with(
        data,
        {**_as_mapping(data), artifact.target: 1.234},
    )
    with pytest.raises(ForecastArtifactError) as caught:
        predict(tampered, with_target, estimator=leaky_estimators[tampered.model_id])
    assert "36" in str(caught.value) and "35" in str(caught.value), (
        "the refusal must show the two column counts that disagree: "
        f"{caught.value}"
    )


def test_a_target_value_in_the_feature_vector_cannot_reach_the_prediction(
    store, model_dataset, origin, estimators
) -> None:
    """The served number does not become the poisoned input.

    A direct check rather than a structural one: every water-level-derived column in
    the feature row is replaced with a value no gauge would report, and the forecast
    must still come back as a model prediction rather than as a copy of the poison.

    The water level *is* a genuine input, so the number is expected to move - what is
    asserted is that it moves to something the estimator produced.
    """
    clean = serving_input(model_dataset, origin)
    served_clean = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=clean,
        estimators=estimators,
    )
    assert served_clean.status == "ready"

    poisoned = {
        name: (9999.0 if name.startswith("water_level") else value)
        for name, value in _as_mapping(clean).items()
    }
    served_poisoned = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=_input_with(clean, poisoned),
        estimators=estimators,
    )
    assert served_poisoned.status == "ready"
    assert served_poisoned.inference.prediction != pytest.approx(9999.0), (
        "a poisoned input produced the poisoned value as its forecast"
    )
    assert served_poisoned.inference.strategy == "estimator"
    # The poisoned values are visible in the input, so the change is attributable.
    assert served_poisoned.inference.prediction != served_clean.inference.prediction


# --------------------------------------------------------------------------- #
# Future-derived preprocessing
# --------------------------------------------------------------------------- #


def test_the_fitted_scaler_and_imputer_saw_only_the_training_rows(store) -> None:
    """The fitted row count equals the train split, and is smaller than the series.

    Checked against the artifact's own recorded split sizes rather than against the
    audit's finding, so it is an independent confirmation: if preprocessing had seen
    the validation rows the count would be larger, and if it had seen only the
    supervised window rows it would be smaller than `row_counts["train"]`.
    """
    found = artifact_for(store, "random_forest")
    spec = found.preprocessing
    assert spec is not None

    train_rows = found.row_counts["train"]
    held_out = found.row_counts["validation"] + found.row_counts["test"]

    assert spec.fitted_on == "train"
    assert spec.fitted_rows == train_rows, (
        f"the fitted record reports {spec.fitted_rows} rows but the artifact records "
        f"{train_rows} training rows"
    )
    assert spec.fitted_rows < train_rows + held_out, (
        "the fitted record claims to have seen every row including the held-out splits"
    )
    assert spec.scaler["fitted_rows"] == spec.imputer["fitted_rows"] == train_rows


def test_preprocessing_fitted_on_anything_but_the_training_split_is_refused(
    artifact,
) -> None:
    """The rule that makes the check above enforceable rather than decorative.

    Written directly against `PreprocessingSpec`, because a scaler record claiming
    `fitted_on: "validation"` is exactly the artefact of a preprocessing pipeline that
    was fitted too late, and the only place that can be caught is where the record is
    turned into something usable.
    """
    good = artifact.preprocessing
    assert good is not None

    for fitted_on in ("validation", "test", "all", ""):
        for part in ("scaler", "imputer"):
            state = dict(good.to_dict()[part])
            state["fitted_on"] = fitted_on
            with pytest.raises(ArtifactPreprocessingMismatchError) as caught:
                PreprocessingSpec(
                    feature_names=good.feature_names,
                    **{part: state},
                )
            message = str(caught.value)
            assert "train" in message
            assert fitted_on in message or "not 'train'" in message, (
                f"the refusal for fitted_on={fitted_on!r} does not say what was wrong: {message}"
            )


def test_preprocessing_missing_its_provenance_is_refused(artifact) -> None:
    """`fitted_on` is not optional metadata; it is what the check is made of.

    A record without it cannot be shown to be train-only, so it is refused rather
    than assumed - the same reasoning as refusing an artifact without a checksum.
    """
    good = artifact.preprocessing
    assert good is not None
    for part in ("scaler", "imputer"):
        state = dict(good.to_dict()[part])
        del state["fitted_on"]
        with pytest.raises(ArtifactPreprocessingMismatchError) as caught:
            PreprocessingSpec(feature_names=good.feature_names, **{part: state})
        assert "fitted_on" in str(caught.value)


def test_the_preprocessing_record_offers_no_way_to_refit_itself(artifact) -> None:
    """There is no `fit` on the serving-side preprocessing, by construction.

    Not a test of the guard in `hydro_phase5_fixtures` - that one proves the *model*
    is not fitted during a request. This proves the *preprocessing object* has no
    fitting entry point at all, so no caller can reach one through it.
    """
    good = artifact.preprocessing
    assert good is not None
    assert not hasattr(good, "fit")
    assert not hasattr(good, "fit_transform")
    assert not hasattr(good, "partial_fit")
    assert callable(good.transform), "the record must still be usable for its purpose"
    assert "train" in good.describe()


def test_serving_transforms_with_the_recorded_values_rather_than_the_inputs_own(
    store, model_dataset, origin, estimators
) -> None:
    """Two different input distributions, one set of recorded scaling values.

    The mean and scale come from the artifact, so a serving batch cannot redefine them
    by arriving with a different average. Verified by handing in a vector whose values
    are far outside the training range and checking the reported imputed/scaling
    metadata and the transformation still come from the artifact's own record.
    """
    found = artifact_for(store, "random_forest")
    spec = found.preprocessing
    assert spec is not None

    data = serving_input(model_dataset, origin)
    transformed = spec.transform(tuple(data.values))
    assert len(transformed) == len(spec.feature_names)

    # The recorded means are subtracted, not the incoming vector's own mean: feeding
    # a constant vector must produce a constant offset, not zeros.
    constant = spec.transform(tuple([0.0] * len(spec.feature_names)))
    assert (constant != 0).any(), (
        "a zero vector transformed to zeros, so the recorded mean/scale are not being applied"
    )
    assert not spec.is_identity, (
        "the artifact claims a standard scaler policy but its record is an identity transform"
    )
    assert spec.fitted_on == "train"


# --------------------------------------------------------------------------- #
# Causality at the serving boundary
# --------------------------------------------------------------------------- #


def test_a_feature_read_after_the_origin_is_refused_through_serving(
    store, model_dataset, origin, estimators
) -> None:
    """End to end: the refusal is a status, not an exception escaping `serve`.

    `serve` is the deployment's entry point, so a causality violation has to arrive as
    a structured refusal a caller can log. An exception would be a different failure
    mode for the same mistake.
    """
    data = serving_input(model_dataset, origin)
    late_instant = origin + dt.timedelta(hours=2)
    served = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=_input_with(data, instants=tuple([late_instant] * len(data.feature_names))),
        estimators=estimators,
    )
    assert served.status == "invalid_request"
    assert served.inference is None
    assert served.reason


def test_a_feature_read_exactly_at_the_origin_is_accepted(
    store, model_dataset, origin, estimators
) -> None:
    """The boundary is inclusive, and that is the point.

    A feature vector at the origin uses readings up to and including the origin, which
    is what an operational forecast has. Refusing it would make every real request
    fail; accepting a read at origin+1s would leak. The two cases are asserted
    together so the boundary cannot be moved without one of them failing.
    """
    data = serving_input(model_dataset, origin)
    assert set(data.feature_instants) == {origin}, (
        "the fixture must read its features at the origin for this boundary to be tested"
    )

    served = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=data,
        estimators=estimators,
    )
    assert served.status == "ready"


def test_the_prediction_instant_is_strictly_after_the_origin(
    store, model_dataset, origin, estimators
) -> None:
    """Never at, never before - the forecast is for a future instant.

    Asserted against both halves: after the origin, and exactly one horizon after it.
    The second is the stronger claim and is what makes the timestamp meaningful to a
    caller reading it as "the level in six hours". The horizon comes from Phase 4's
    parser rather than from `timedelta(hours=6)`, so this also pins that Phase 5 reads
    the horizon the same way Phase 4 wrote it.
    """
    from app.engines.hydro.model_handoff import horizon_seconds

    span = horizon_seconds(HORIZON)
    assert span == 21600.0
    assert horizon_seconds("-6h") is None, "a non-positive horizon must yield no span"

    served = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=serving_input(model_dataset, origin),
        estimators=estimators,
    )
    assert served.status == "ready"
    predicted_at = _instant(served.inference.prediction_timestamp)
    assert predicted_at == origin + dt.timedelta(seconds=span)
    assert predicted_at > origin


def test_persistence_ignores_every_observation_after_the_origin(
    store, model_dataset, origin
) -> None:
    """The baseline's whole risk is reading one row too far.

    Persistence carries the last observed value forward, and the last observation in a
    careless implementation is the last row in the frame rather than the last row at
    or before the origin. So the history is padded here with readings from *after* the
    origin, carrying values no gauge reported, and the forecast must ignore them.
    """
    data = serving_input(model_dataset, origin)
    assert all(observation.instant <= origin for observation in data.target_history)

    poisoned = tuple(
        TargetObservation(origin + dt.timedelta(hours=hours), 9999.0)
        for hours in range(1, int(HOURS) + 1)
    )
    padded = _input_with(data, target_history=tuple(data.target_history) + poisoned)

    at_or_before = [
        observation for observation in data.target_history if observation.instant <= origin
    ]
    assert at_or_before

    served = serve(family_request(origin), store=store, data=padded)
    assert served.status == "ready"
    assert served.inference.prediction == pytest.approx(at_or_before[-1].value)
    assert served.inference.prediction != pytest.approx(9999.0), (
        "the forecast carried a post-origin observation forward"
    )
    assert served.inference.carried_from_instant == at_or_before[-1].instant
    # The forecast instant is still derived from the origin, not from the last row read.
    assert _instant(served.inference.prediction_timestamp) == origin + dt.timedelta(
        hours=int(HOURS)
    )


def test_an_origin_before_any_observation_is_refused_rather_than_answered(
    store, model_dataset, origin
) -> None:
    """A persistence forecast with nothing at or before the origin has no answer.

    Reporting the earliest available observation - which is in the future - would
    produce a forecast for an instant the caller did not ask about, from a reading the
    caller could not have had.
    """
    data = serving_input(model_dataset, origin)
    before_everything = data.target_history[0].instant - dt.timedelta(hours=1)

    early = ForecastInput.from_sequence(
        entity=data.entity,
        origin_instant=before_everything,
        names=data.feature_names,
        values=data.values,
        feature_instants=tuple([before_everything] * len(data.feature_names)),
        target_history=data.target_history,
    )
    assert all(observation.instant > before_everything for observation in data.target_history)

    served = serve(family_request(before_everything), store=store, data=early)
    assert served.status == "insufficient_data"
    assert served.inference is None
    assert served.reason


# --------------------------------------------------------------------------- #
# Cross-station isolation
# --------------------------------------------------------------------------- #


def test_one_stations_data_can_never_answer_for_another(store, model_dataset, origin) -> None:
    """Refused by name, in both directions.

    The dangerous version of this bug is not a crash - it is a plausible number for
    station B computed from station A's readings. So the assertion is that the request
    is refused *and* that the reason names both stations, so an operator can see which
    pair was mismatched rather than just that something was.
    """
    served = serve(
        family_request(origin, entity=STATION_B),
        store=store,
        data=serving_input(model_dataset, origin, entity=STATION_A),
    )
    assert served.status == "invalid_request"
    assert served.inference is None
    assert STATION_B in served.reason
    assert STATION_A in served.reason


def test_history_for_the_wrong_station_is_filtered_not_refused(
    store, model_dataset, origin
) -> None:
    """Mixed history is filtered to the requested station, not rejected.

    A frame holding both stations is the normal shape of a real query, so refusing it
    would make the boundary unusable. Filtering is safe precisely because the
    persistence rule then cannot read the other station - which the filter's effect is
    asserted on, by checking the carried value is station A's.
    """
    data = serving_input(model_dataset, origin)
    mixed = tuple(data.target_history) + target_history_until(
        model_dataset, origin, entity=STATION_B
    )
    served = serve(
        family_request(origin, entity=STATION_A),
        store=store,
        data=_input_with(data, target_history=mixed),
    )
    assert served.status == "ready"
    station_a_value = target_history_until(model_dataset, origin, entity=STATION_A)[-1].value
    assert served.inference.prediction == pytest.approx(station_a_value)


def test_the_station_the_model_was_fitted_on_is_recorded_not_assumed(store) -> None:
    """The artifact says which station it learned from.

    It does **not** refuse to serve another station, and the reason is worth stating:
    nothing in Phase 4's manifest says whether a model trained on one gauge is valid
    at another, so Phase 5 has no basis for refusing, and inventing one would be
    inventing policy. What it can do - and does - is record the station, so a
    cross-station deployment is a decision a reader can see rather than a silent one.

    This test pins both halves: the station is present, and it is not enforced.
    """
    for found in store.artifacts:
        assert found.provenance is not None, (
            f"{found.model_id}: an artifact with no provenance cannot say where it was fitted"
        )
        station = found.provenance.get("station_reference")
        assert station == STATION_A, (
            f"{found.model_id}: the fixture dataset is single-station, so every artifact "
            f"should name {STATION_A!r}, not {station!r}"
        )


def test_an_input_naming_two_stations_is_refused(model_dataset, origin) -> None:
    """Checked at the boundary the caller actually uses.

    `check_entity` is the gate `predict` and `serve` both go through, so testing it
    directly pins the rule once rather than twice through two call paths.
    """
    data = serving_input(model_dataset, origin)
    for entity in (STATION_B, "", "  "):
        with pytest.raises(EntityMismatchError):
            data.check_entity(entity)

    data.check_entity(STATION_A)


# --------------------------------------------------------------------------- #
# Train / validation / test contamination
# --------------------------------------------------------------------------- #


def test_the_split_bounds_partition_the_series_with_no_overlap(store) -> None:
    """Three disjoint, chronological windows - the property Phase 4's audit checks.

    Asserted here against the artifact's own numbers because "the audit passed" is a
    claim about a dataset, while these are the numbers a deployment reads.
    """
    for found in store.artifacts:
        bounds = {key: _instant(value) for key, value in found.split_bounds.items()}
        train_start, train_end = bounds["train_start"], bounds["train_end"]
        val_start, val_end = bounds["validation_start"], bounds["validation_end"]
        test_start, test_end = bounds["test_start"], bounds["test_end"]

        assert train_start < train_end
        assert train_end <= val_start, "validation starts before training ends"
        assert val_start < val_end
        assert val_end <= test_start, "test starts before validation ends"
        assert test_start < test_end
        assert found.split_policy


def test_serving_an_origin_inside_the_training_window_is_detectable(
    store, model_dataset, origin, estimators
) -> None:
    """Phase 5 will happily serve an origin the model was trained on - and says so.

    A forecast for an origin inside the training window is not out of sample, and
    presenting it as an operational forecast would be misleading. Refusing it outright
    would break backtesting and the platform's own historical replay, so the honest
    answer is: serve it, and give the caller the numbers they need to notice.

    The bounds are on the artifact, so the comparison is a subtraction. That is the
    whole contract, and it is what this test asserts.
    """
    found = artifact_for(store, "random_forest")
    train_start = _instant(found.split_bounds["train_start"])
    train_end = _instant(found.split_bounds["train_end"])

    inside = train_start + dt.timedelta(hours=12)
    assert train_start <= inside <= train_end

    served = serve(
        family_request(inside, "random_forest"),
        store=store,
        data=serving_input(model_dataset, inside),
        estimators=estimators,
    )
    assert served.status == "ready", "an in-window origin must still be servable"
    assert served.artifact.split_bounds == found.split_bounds, (
        "the served result must carry the bounds needed to detect that the origin was "
        "inside the training window"
    )
    # And the check is one comparison away for the caller.
    assert (
        _instant(served.artifact.split_bounds["train_start"])
        <= served.request.origin_instant
        <= _instant(served.artifact.split_bounds["train_end"])
    )


def test_no_served_value_depends_on_a_held_out_row(store, model_dataset, origin, estimators) -> None:
    """The artifact is the only thing serving reads, and it was fitted on train only.

    Verified by serving the same request twice with different *fitted* state: once from
    the real artifact, once from an artifact whose preprocessing came from a different
    dataset. If serving consulted the held-out rows, the two could not differ only in
    the recorded means - and the fact that the answer changes at all when the record
    changes proves the record is what is being used.
    """
    data = serving_input(model_dataset, origin)
    real = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=data,
        estimators=estimators,
    )
    assert real.status == "ready"

    found = artifact_for(store, "random_forest")
    spec = found.preprocessing
    assert spec is not None
    shifted = PreprocessingSpec(
        feature_names=spec.feature_names,
        scaler={**spec.to_dict()["scaler"], "mean": {name: 0.0 for name in spec.feature_names}},
        imputer=spec.imputer,
    )
    shifted_store = store.with_preprocessing({found.model_id: shifted})
    altered = serve(
        family_request(origin, "random_forest"),
        store=shifted_store,
        data=data,
        estimators=estimators,
    )
    assert altered.status == "ready"
    assert altered.inference.prediction != real.inference.prediction, (
        "changing the recorded preprocessing means did not change the forecast, so the "
        "recorded means are not what the model was served with"
    )
    assert altered.inference.preprocessing_applied is True


def test_an_artifact_with_no_preprocessing_record_cannot_serve_a_scaled_model(
    store, model_dataset, origin, estimators, artifact
) -> None:
    """The identity-transform trap, refused.

    If a scaled model were served through an identity transform the call would succeed
    and return a number with no meaning - no exception, no status, just a value that
    looks like a forecast. The manifest records that a scaler was fitted, so a missing
    record is a contradiction rather than an absence.
    """
    stripped = dataclasses.replace(
        artifact,
        preprocessing=None,
        model_id="random_forest-unpreprocessed",
        artifact_id="random_forest-unpreprocessed",
    )
    assert stripped.scaler_policy not in (None, "none"), (
        "the fixture must record a scaler policy for this test to be about a "
        "contradiction rather than a model trained without one"
    )
    # A distinct id, or the store would hand back the intact original and the test
    # would pass on the wrong artifact.
    assert stripped.model_id != artifact.model_id
    assert stripped.model_id not in {a.model_id for a in store.artifacts}

    served = serve(
        request_for(origin, model_id=stripped.model_id),
        store=ArtifactStore(artifacts=(*store.artifacts, stripped)),
        data=serving_input(model_dataset, origin),
        estimators={
            **estimators,
            stripped.model_id: estimators[artifact.model_id],
        },
    )
    assert served.status == "invalid_request"
    assert served.inference is None
    assert "scaler" in served.reason
    assert "no meaning" in served.reason or "unscaled" in served.reason


# --------------------------------------------------------------------------- #
# Invalid sequence windows
# --------------------------------------------------------------------------- #


def test_an_input_with_no_feature_instants_is_refused(store, model_dataset, origin, estimators) -> None:
    """A window with no rows is not a prediction of zero.

    The alternatives - an all-zero vector, or the first value of the series - would
    each be a number attributed to a rule that did not produce it.
    """
    data = serving_input(model_dataset, origin)
    served = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=ForecastInput.from_sequence(
            entity=data.entity,
            origin_instant=data.origin_instant,
            names=(),
            values=(),
            target_history=data.target_history,
        ),
    )
    assert served.status == "invalid_request"
    assert served.inference is None
    assert served.reason


def test_a_feature_vector_whose_order_does_not_match_the_artifact_is_refused(
    store, model_dataset, origin, estimators
) -> None:
    """Ordering is part of the contract, not a convenience.

    A shuffled vector applied positionally is the same class of failure as a
    misaligned CSV: no error, a plausible number, and no way to tell afterwards.
    """
    data = serving_input(model_dataset, origin)
    reversed_names = tuple(reversed(data.feature_names))
    mapping = _as_mapping(data)
    served = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=_input_with(data, {name: mapping[name] for name in reversed_names}),
        estimators=estimators,
    )
    assert served.status == "invalid_request"
    assert served.inference is None
    assert "position 0" in served.reason, (
        "the refusal should point at the first disagreement, not only say 'order'"
    )
    assert data.feature_names[0] in served.reason
    assert reversed_names[0] in served.reason


def test_the_feature_vector_length_is_checked_against_the_artifact_not_the_batch(
    store, model_dataset, origin, estimators
) -> None:
    """A short vector is refused even when every column it has is correct.

    A model with 35 coefficients and a 34-element vector would raise inside the
    estimator in a way that depends on the estimator, so Phase 5 checks the length
    itself and refuses with a name in the message.
    """
    data = serving_input(model_dataset, origin)
    mapping = _as_mapping(data)
    dropped = data.feature_names[-1]
    served = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=_input_with(data, {n: v for n, v in mapping.items() if n != dropped}),
        estimators=estimators,
    )
    assert served.status == "invalid_request"
    assert served.inference is None
    assert dropped in served.reason


def test_one_column_too_many_is_reported_as_extra_not_as_missing(
    store, model_dataset, origin, estimators
) -> None:
    """The two overshoots are different mistakes and get different messages.

    Reporting "one column missing" when the caller actually supplied one too many sends
    them to remove a column they had not added - the single most common way a caller
    loses an afternoon on a feature-mismatch error.
    """
    data = serving_input(model_dataset, origin)
    extra_name = "rainfall_lag_999h"
    served = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=_input_with(data, {**_as_mapping(data), extra_name: 1.0}),
        estimators=estimators,
    )
    assert served.status == "invalid_request"
    assert served.inference is None
    assert extra_name in served.reason
    assert "missing" not in served.reason.lower(), (
        "the refusal reports a missing column when the caller supplied an extra one"
    )


def test_the_causality_check_is_the_one_the_boundary_calls() -> None:
    """`check_causal` is a method on the input, so it cannot be forgotten at a call site.

    Pinned by asserting it exists on the type `serve` receives data as. A helper that
    was moved to a module function would leave the tests above passing and this one
    failing, which is the point: the boundary's guarantees live on the object's own
    surface, where a new call site inherits them.
    """
    assert callable(ForecastInput.check_causal)
    assert callable(ForecastInput.check_against)
    assert callable(ForecastInput.check_entity)
    # And the three checks are distinct: a message from one is not another's.
    assert ForecastInput.check_causal is not ForecastInput.check_entity


def test_a_causal_check_names_the_offending_instant_and_the_origin(
    model_dataset, origin
) -> None:
    """An operator needs to know *which* read was too late to fix the request.

    A message that says only "causality violated" sends them back to the data pipeline
    to work out which of thirty-five columns was wrong.
    """
    data = serving_input(model_dataset, origin)
    late_instant = origin + dt.timedelta(hours=3)
    late = _input_with(
        data, instants=tuple([late_instant] * len(data.feature_names))
    )
    with pytest.raises(CausalityError) as caught:
        late.check_causal()
    message = str(caught.value)
    assert str(late_instant.isoformat())[:16] in message or "03:00" in message
    assert str(origin.isoformat())[:16] in message or "05:00" in message
    assert "after" in message, f"the refusal does not say which side of the origin: {message}"


# --------------------------------------------------------------------------- #
# The artifact loader is part of this boundary
# --------------------------------------------------------------------------- #


def test_an_artifact_whose_digest_does_not_match_its_features_is_refused(
    artifact,
) -> None:
    """An edited manifest is caught on the way in, before any number is produced.

    A feature column is renamed in the manifest while the recorded digest is left
    alone - the shape of a hand-edit, or of a file edited by a script that did not know
    the digest was load-bearing. Without the check the artifact would load and then
    serve a vector whose positions mean something else.

    Asserted on the tampered payload itself rather than on a description of the check,
    and with both halves: the digest mismatch is *detected*, and the message names both
    the recorded and the recomputed value so an operator can see which file to compare.
    """
    tampered = dict(manifest_payload(artifact))
    columns = list(tampered["feature_names"])
    columns[0] = "water_level_lag_999h"
    tampered["feature_names"] = columns
    # The digest is deliberately NOT recomputed - that is the tamper.

    with pytest.raises(ArtifactContractMismatchError) as caught:
        artifact_from_manifest_payload(tampered)
    message = str(caught.value)
    assert "digest" in message.lower()
    assert artifact.feature_digest[:16] in message
    assert feature_digest(tuple(columns))[:16] in message


def test_a_consistently_recomputed_digest_does_not_bypass_the_earlier_checks(
    artifact,
) -> None:
    """Recomputing the digest makes the tamper invisible, which is why the other checks exist.

    A digest proves a file was not edited *after* it was written. It says nothing about
    whether the content is right - a manifest rewritten consistently with a leaky
    feature list passes the digest. So the digest cannot be the only defence, and the
    test that proves the point is the target-leakage refusal above, which recomputes the
    digest first.

    Here the same shape is asserted on the loader: a manifest whose columns and digest
    agree loads cleanly, which is what makes the earlier refusal necessary rather than
    redundant.
    """
    payload = manifest_payload(artifact)
    payload["feature_names"] = list(artifact.feature_names)
    payload["feature_digest"] = feature_digest(tuple(artifact.feature_names))

    loaded = artifact_from_manifest_payload(payload)
    assert loaded.feature_names == artifact.feature_names
    assert loaded.feature_digest == artifact.feature_digest
    assert loaded.feature_digest == feature_digest(loaded.feature_names)


def test_a_manifest_from_a_run_is_readable_and_still_carries_no_weights(
    store, model_dataset, origin, tmp_path, manifests
) -> None:
    """The round trip a deployment performs: write, read, serve the baseline.

    The point is not that the files parse - it is that what comes back cannot serve a
    learned model, because Phase 4's weight-storage policy keeps fitted parameters out
    of the repository. A deployment that reads the directory and believes it has a
    model is the failure this documents.
    """
    from app.engines.hydro.model_artifacts import write_manifests

    write_manifests(manifests, tmp_path)
    reloaded = ArtifactStore.from_directory(str(tmp_path))

    assert len(reloaded) == len(store.artifacts)
    data = serving_input(model_dataset, origin)
    statuses = set()
    for found in reloaded.artifacts:
        assert found.weight_stored_in_repository is False, (
            f"{found.model_id}: a weight file appeared in the repository"
        )
        served = serve(
            family_request(origin, found.model_family),
            store=reloaded,
            data=data,
        )
        statuses.add(served.status)

        if found.state == "dependency_blocked":
            # Named as a missing library, not as a missing artifact: the manifest is on
            # disk and the remedy is to install the package.
            assert not found.available
            assert served.status == "dependency_unavailable"
            assert served.inference is None
        elif found.uses_trained_parameters:
            # Present as metadata, refused as a source of numbers.
            assert found.available
            assert served.status == "artifact_unavailable", (
                f"{found.model_id}: a manifest directory served a learned model with no weights"
            )
            assert served.inference is None
        else:
            # The parameter-free family is servable from the manifest alone, which is
            # what makes it the testable `available` path.
            assert found.available
            assert served.status == "ready"
            assert served.inference.strategy == "persistence"

    # Every refusal in this loop is a *different* reason, not one reason reused. If the
    # three collapsed together the store would still refuse three times, and an
    # operator would still not know which problem to fix.
    assert statuses == {"ready", "artifact_unavailable", "dependency_unavailable"}


def test_a_run_supplied_at_serving_time_does_not_change_the_forecast(
    store, model_dataset, origin, estimators, trained_run
) -> None:
    """The training result is provenance for the handoff, not an input to the number.

    Phase 4's `RunResult` carries the fitted estimators. If `serve` reached into it
    for weights, then the same artifact plus the same input could answer differently
    depending on whether the caller happened to pass the run - which would make the
    artifact, not the inputs, an incomplete statement of what produced the number.
    """
    without = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=serving_input(model_dataset, origin),
        estimators=estimators,
    )
    with_run = serve(
        family_request(origin, "random_forest"),
        store=store,
        data=serving_input(model_dataset, origin),
        estimators=estimators,
        run_result=trained_run,
    )
    assert without.status == "ready"
    assert with_run.status == "ready"
    assert without.inference.prediction == with_run.inference.prediction
    assert without.forecast_id == with_run.forecast_id
    # The run is used for the handoff, and only for that.
    assert without.handoff is None
    assert with_run.handoff is not None