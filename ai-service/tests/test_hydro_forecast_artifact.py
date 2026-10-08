# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 5: the artifact is checked before anything is served from it.

The tests here assert *rejections*. A forecasting pipeline's real risk at this layer
is not that it refuses too often, it is that it accepts something subtly wrong and
returns a number that looks fine: a feature list reordered, a scaler that saw a
validation row, a six-hour model handed a twenty-four-hour request. Each of those
has a test below that constructs the mistake and asserts a named error comes back
with a message saying what was wrong.

The positive cases matter too, and they assert the field values rather than just
"no exception": an artifact that loads without saying what target it predicts, at
what horizon, from which features and with which weights is not much of a contract.
"""

from __future__ import annotations

import json
import os

import pytest

from app.engines.hydro.forecast_artifact import (
    ARTIFACT_STATES,
    FORECAST_ARTIFACT_VERSION,
    REQUIRED_ARTIFACT_FIELDS,
    STATE_ARTIFACT_MISSING,
    STATE_AVAILABLE,
    STATE_DEPENDENCY_BLOCKED,
    ArtifactContractMismatchError,
    ArtifactFamilyMismatchError,
    ArtifactHorizonMismatchError,
    ArtifactMalformedError,
    ArtifactMissingError,
    ArtifactPreprocessingMismatchError,
    ArtifactSchemaMismatchError,
    ArtifactStore,
    ArtifactTargetMismatchError,
    ForecastArtifactError,
    PreprocessingSpec,
    handoff_status_for_state,
    load_artifact,
    load_artifact_directory,
    parse_artifact,
    registry_availability,
    state_for_manifest,
)
from app.engines.hydro.model_artifacts import (
    ARTIFACT_MANIFEST_VERSION,
    LEGACY_MANIFEST_VERSION,
    build_manifests,
    write_manifests,
)
from app.engines.hydro.model_handoff import (
    STATUS_ARTIFACT_UNAVAILABLE,
    STATUS_DEPENDENCY_UNAVAILABLE,
    STATUS_INVALID_REQUEST,
    STATUS_READY,
)
from app.engines.hydro.model_registry import MODEL_FAMILIES

from hydro_phase5_fixtures import (
    FAMILIES,
    STATION_A,
    SYNTHETIC_DISCLAIMER,
    TARGET,
    artifact,
    artifact_for,
    build_run,
    manifest_payload,
    manifests,
    model_dataset,
    store,
    trained_run,
)


# --------------------------------------------------------------------------- #
# The five states
# --------------------------------------------------------------------------- #


def test_every_declared_state_is_reachable_and_maps_to_a_handoff_status(store) -> None:
    """The five names are a contract, not a suggestion: each maps to a Phase 4 status."""
    assert ARTIFACT_STATES == (
        "available",
        "dependency_blocked",
        "artifact_missing",
        "invalid",
        "not_evaluable",
    )
    mapping = {state: handoff_status_for_state(state) for state in ARTIFACT_STATES}
    assert mapping == {
        "available": STATUS_READY,
        "dependency_blocked": STATUS_DEPENDENCY_UNAVAILABLE,
        "artifact_missing": STATUS_ARTIFACT_UNAVAILABLE,
        "invalid": STATUS_INVALID_REQUEST,
        "not_evaluable": STATUS_INVALID_REQUEST,
    }


def test_an_unknown_state_is_refused_rather_than_treated_as_something(store) -> None:
    """Guessing that a state means something is how a blocked model gets served."""
    good = artifact_for(store, "random_forest")
    with pytest.raises(ForecastArtifactError) as caught:
        parse_artifact(manifest_payload(good, state="probably_fine"))
    assert "probably_fine" in str(caught.value)
    assert str(list(ARTIFACT_STATES)) in str(caught.value)


def test_a_trained_and_scored_model_is_available(store) -> None:
    artifact = artifact_for(store, "random_forest")
    assert artifact.state == STATE_AVAILABLE
    assert artifact.available is True
    assert artifact.selectable is True
    assert artifact.reason is None


def test_a_dependency_blocked_family_is_reported_as_blocked_not_as_missing(store) -> None:
    """`artifact_missing` would send a reader looking for a file.

    The fix for a blocked family is to install a package, and the reason string has
    to say so — that is the actionable difference between the two states.
    """
    blocked = artifact_for(store, "xgboost")
    assert blocked.state == STATE_DEPENDENCY_BLOCKED
    assert blocked.available is False
    assert blocked.selectable is False
    assert "xgboost" in blocked.reason
    assert "ModuleNotFoundError" in blocked.reason or "not importable" in blocked.reason


def test_a_blocked_model_carries_no_metrics_and_no_fabricated_weights(store) -> None:
    """A model that never ran cannot have scored. `None`, never `0.0`."""
    blocked = artifact_for(store, "xgboost")
    assert blocked.metrics_by_split == {}
    assert blocked.weight_reference is None
    assert blocked.weight_stored_in_repository is False


def test_a_blocked_model_is_not_evaluable_rather_than_evaluated(store) -> None:
    blocked = artifact_for(store, "xgboost")
    assert not blocked.selectable, (
        "a dependency-blocked model was treated as a selection candidate; ranking it would "
        "require metrics that do not exist"
    )


def test_a_family_with_no_written_artifact_is_artifact_missing(manifests) -> None:
    """The state that means: training completed but nothing was written.

    Reached through `state_for_manifest` rather than by hand-setting a state,
    because the rule that maps statuses onto states is the thing worth testing - it
    is what decides what a caller is told when nothing was written. The blocked
    model is used as the base because it is the one manifest in this fixture that
    reports `not_written`; the training status is then corrected to `trained`, which
    is what separates "the package is missing" from "we produced nothing".
    """
    import dataclasses

    blocked = next(m for m in manifests.manifests if m.model_family == "xgboost")
    assert blocked.artifact_status == "not_written", (
        "the fixture's xgboost model is expected to write no manifest; if it does, the "
        "environment can import xgboost and this test no longer reaches the state"
    )
    never_written = dataclasses.replace(blocked, training_status="trained")
    assert state_for_manifest(never_written) == STATE_ARTIFACT_MISSING
    # ...and the same manifest with its real training status is blocked instead.
    assert state_for_manifest(blocked) == STATE_DEPENDENCY_BLOCKED


def test_a_fitted_but_unscored_model_is_not_evaluable_not_invalid(manifests) -> None:
    """Servable but not rankable is a real distinction and is reported as one.

    Collapsing it into `invalid` would refuse to serve a model that works; collapsing
    it into `available` would let an unscored model be ranked against scored ones.
    """
    import dataclasses

    manifest = next(m for m in manifests.manifests if m.model_family == "random_forest")
    unscored = dataclasses.replace(manifest, evaluation_status="not_evaluated")
    assert state_for_manifest(unscored) == "not_evaluable"


# --------------------------------------------------------------------------- #
# The artifact's own fields
# --------------------------------------------------------------------------- #


def test_the_artifact_states_its_target_horizon_and_features(store) -> None:
    artifact = artifact_for(store, "random_forest")
    assert artifact.target == TARGET
    assert artifact.horizon == "6h"
    assert artifact.target_units == "m"
    assert artifact.feature_count == len(artifact.feature_names) > 0
    assert artifact.feature_digest
    assert artifact.feature_contract_version


def test_the_feature_order_is_preserved_not_sorted(artifact) -> None:
    """Order is the contract. An artifact that sorted its names would be a lie.

    Phase 3's dataset ends on `calendar_doy_cos`, not on the alphabetically first
    column, so the fixture's own order is distinguishable from a sorted one - which
    is what makes this test able to fail.
    """
    assert list(artifact.feature_names) != sorted(artifact.feature_names)
    assert artifact.feature_names[-1] == "calendar_doy_cos"


def test_the_artifact_carries_the_training_provenance_and_the_seed(artifact) -> None:
    assert artifact.random_seed == 20240917
    assert artifact.provenance
    assert artifact.scaler_policy == "standard"
    assert artifact.impute_policy == "median"


def test_the_artifact_records_the_split_bounds_and_row_counts(artifact) -> None:
    """Bounds are recorded as `*_start`/`*_end` instants, not as bare split names.

    A bound without an instant says nothing, and the whole point of recording the
    split windows is that a reader can check them against the request instants - so
    the test asserts the instants are present, not just the words.
    """
    assert artifact.split_policy
    for split in ("train", "validation", "test"):
        assert f"{split}_start" in artifact.split_bounds
        assert f"{split}_end" in artifact.split_bounds
        assert artifact.split_bounds[f"{split}_start"] < artifact.split_bounds[f"{split}_end"]
    assert (
        artifact.split_bounds["train_end"]
        <= artifact.split_bounds["validation_start"]
        <= artifact.split_bounds["validation_end"]
        <= artifact.split_bounds["test_start"]
    )
    assert artifact.row_counts
    assert all(count > 0 for count in artifact.row_counts.values())


def test_the_artifact_records_the_evaluation_metrics_per_split(artifact) -> None:
    assert set(artifact.metrics_by_split) == {"validation", "test"}
    for values in artifact.metrics_by_split.values():
        assert "rmse" in values and "mae" in values and "r2" in values


def test_the_synthetic_disclaimer_travels_onto_the_artifact(store) -> None:
    """The exact sentence, so a reader of the artifact sees what the data is."""
    for artifact in store.artifacts:
        assert artifact.disclaimer == SYNTHETIC_DISCLAIMER
        assert artifact.synthetic_demo is True
        assert artifact.data_status == "synthetic_demo"


def test_no_artifact_claims_production_readiness(store) -> None:
    for artifact in store.artifacts:
        assert artifact.production_ready_claimed is False


def test_an_artifact_that_claimed_production_readiness_is_rejected(store) -> None:
    """Not merely flagged: refused at construction, so it cannot reach a result."""
    import dataclasses

    good = artifact_for(store, "random_forest")
    with pytest.raises(ForecastArtifactError) as caught:
        dataclasses.replace(good, production_ready_claimed=True)
    assert "synthetic" in str(caught.value).lower()


def test_the_artifact_says_whether_it_needs_weights_it_cannot_load(store) -> None:
    """The baseline's prediction rule is not a set of parameters; the forest's is.

    This is the fact that lets the serving path know in advance which models can be
    run from a manifest alone, instead of discovering it by failing.
    """
    assert artifact_for(store, "naive").uses_trained_parameters is False
    assert artifact_for(store, "random_forest").uses_trained_parameters is True
    assert artifact_for(store, "random_forest").weight_stored_in_repository is False


def test_the_schema_version_is_declared_and_recorded(store) -> None:
    artifact = artifact_for(store, "random_forest")
    assert artifact.artifact_schema_version == FORECAST_ARTIFACT_VERSION
    assert artifact.manifest_version == ARTIFACT_MANIFEST_VERSION
    assert artifact.to_dict()["artifact_schema_version"] == FORECAST_ARTIFACT_VERSION


def test_the_artifact_serialises_every_contract_field(store) -> None:
    """A reader of the payload can reconstruct what the model is, without the code."""
    payload = artifact_for(store, "random_forest").to_dict()
    for field in (
        "artifact_id",
        "model_id",
        "model_family",
        "model_version",
        "target",
        "target_units",
        "horizon",
        "feature_names",
        "feature_count",
        "feature_digest",
        "feature_contract_version",
        "preprocessing",
        "split_bounds",
        "row_counts",
        "metrics_by_split",
        "hyperparameters",
        "random_seed",
        "scaler_policy",
        "impute_policy",
        "synthetic_demo",
        "data_status",
        "disclaimer",
        "state",
        "created_at",
        "artifact_schema_version",
        "handoff_status",
        "production_ready_claimed",
    ):
        assert field in payload, f"the artifact payload omits {field!r}"


def test_the_artifact_describes_itself_in_readable_lines(store) -> None:
    """Documentation that can only be produced by the object is documentation that
    stays true."""
    text = artifact_for(store, "xgboost").describe()
    assert "xgboost" in text
    assert STATE_DEPENDENCY_BLOCKED in text
    assert SYNTHETIC_DISCLAIMER in text


# --------------------------------------------------------------------------- #
# Contract checks
# --------------------------------------------------------------------------- #


def test_a_target_mismatch_is_refused_by_name(artifact) -> None:
    with pytest.raises(ArtifactTargetMismatchError) as caught:
        artifact.check_target("target_inflow_6h")
    assert "target_inflow_6h" in str(caught.value)
    assert TARGET in str(caught.value)


def test_the_matching_target_passes(artifact) -> None:
    assert artifact.check_target(TARGET) is None


def test_a_horizon_mismatch_is_refused_by_name(artifact) -> None:
    """A six-hour model answering a twenty-four-hour request is Phase 4's exact defect.

    Phase 4 fixed it on the handoff side; Phase 5 must not reintroduce it on the
    serving side, where a wrong `prediction_timestamp` would be the visible symptom.
    """
    with pytest.raises(ArtifactHorizonMismatchError) as caught:
        artifact.check_horizon("24h")
    assert "6h" in str(caught.value)
    assert "24h" in str(caught.value)


def test_the_matching_horizon_passes(artifact) -> None:
    assert artifact.check_horizon("6h") is None


def test_a_family_mismatch_is_refused_by_name(artifact) -> None:
    with pytest.raises(ArtifactFamilyMismatchError) as caught:
        artifact.check_family("xgboost")
    assert "random_forest" in str(caught.value)


def test_omitting_the_family_is_allowed(artifact) -> None:
    assert artifact.check_family(None) is None


def test_an_unknown_family_cannot_be_constructed(artifact) -> None:
    import dataclasses

    with pytest.raises(ArtifactFamilyMismatchError) as caught:
        dataclasses.replace(artifact, model_family="crystal_ball")
    assert "crystal_ball" in str(caught.value)
    assert str(list(MODEL_FAMILIES)) in str(caught.value)


def test_a_reordered_feature_contract_is_refused(artifact) -> None:
    names = list(artifact.feature_names)
    names[0], names[1] = names[1], names[0]
    with pytest.raises(ArtifactContractMismatchError) as caught:
        artifact.check_feature_contract(names)
    assert "order" in str(caught.value).lower()


def test_a_feature_contract_from_a_different_version_is_refused(artifact) -> None:
    with pytest.raises(ArtifactContractMismatchError) as caught:
        artifact.check_feature_contract(artifact.feature_names, version="navya-features/v0")
    assert "navya-features/v0" in str(caught.value)


def test_the_matching_feature_contract_passes(artifact) -> None:
    assert (
        artifact.check_feature_contract(
            artifact.feature_names, version=artifact.feature_contract_version
        )
        is None
    )


def test_a_feature_digest_that_does_not_match_its_names_is_refused(store) -> None:
    """The digest exists so a reader need not compare thirty-five names by eye.

    If the digest can disagree with the list, it is not a check - it is a second
    thing to be wrong.
    """
    good = artifact_for(store, "random_forest")
    with pytest.raises(ArtifactContractMismatchError) as caught:
        parse_artifact(manifest_payload(good, feature_digest="0" * 64))
    assert "digest" in str(caught.value)


def test_a_feature_count_that_contradicts_the_names_is_refused(store) -> None:
    good = artifact_for(store, "random_forest")
    with pytest.raises(ArtifactContractMismatchError) as caught:
        parse_artifact(manifest_payload(good, feature_count=good.feature_count + 1))
    assert str(good.feature_count) in str(caught.value)


def test_a_non_servable_artifact_refuses_to_serve_and_says_why(store) -> None:
    blocked = artifact_for(store, "xgboost")
    with pytest.raises(ForecastArtifactError) as caught:
        blocked.require_servable()
    assert STATE_DEPENDENCY_BLOCKED in str(caught.value)


def test_a_servable_artifact_returns_itself(artifact) -> None:
    assert artifact.require_servable() is artifact


# --------------------------------------------------------------------------- #
# Preprocessing
# --------------------------------------------------------------------------- #


def test_preprocessing_fitted_on_other_than_train_is_refused(model_dataset) -> None:
    """The check that matters most: a scaler that saw a validation row.

    Nothing downstream can undo it. The arithmetic would be right and the number
    would still be contaminated, which is why this is refused rather than noted.
    """
    state = dict(model_dataset.scaler_state)
    state["fitted_on"] = "validation"
    with pytest.raises(ArtifactPreprocessingMismatchError) as caught:
        PreprocessingSpec(
            feature_names=tuple(model_dataset.feature_names), scaler=state
        )
    assert "validation" in str(caught.value)
    assert "train" in str(caught.value)


def test_preprocessing_fitted_on_the_wrong_columns_is_refused(model_dataset) -> None:
    state = dict(model_dataset.scaler_state)
    state["columns"] = list(state["columns"])[:-1]
    with pytest.raises(ArtifactPreprocessingMismatchError) as caught:
        PreprocessingSpec(
            feature_names=tuple(model_dataset.feature_names), scaler=state
        )
    assert "position" in str(caught.value) or "column" in str(caught.value)


def test_preprocessing_missing_a_required_field_is_refused_not_defaulted() -> None:
    """A partial record cannot be completed with a guess.

    Filling in `fitted_on='train'` for a record that does not say so would assert
    the one property this module exists to establish.
    """
    with pytest.raises(ArtifactPreprocessingMismatchError) as caught:
        PreprocessingSpec(
            feature_names=("a", "b"),
            scaler={"kind": "standard", "columns": ["a", "b"], "fitted_rows": 3},
        )
    assert "fitted_on" in str(caught.value)


def test_preprocessing_with_no_feature_names_is_refused() -> None:
    with pytest.raises(ArtifactPreprocessingMismatchError) as caught:
        PreprocessingSpec(feature_names=())
    assert "feature" in str(caught.value)


def test_transform_reports_the_length_it_was_fitted_on(model_dataset) -> None:
    spec = PreprocessingSpec(
        feature_names=tuple(model_dataset.feature_names),
        scaler=model_dataset.scaler_state,
    )
    with pytest.raises(ArtifactPreprocessingMismatchError) as caught:
        spec.transform([1.0, 2.0])
    assert str(len(model_dataset.feature_names)) in str(caught.value)


def test_transform_fills_an_absent_feature_from_the_training_record(model_dataset) -> None:
    """The recorded value, not the column mean, not zero, not this batch."""
    spec = PreprocessingSpec(
        feature_names=tuple(model_dataset.feature_names),
        imputer=model_dataset.imputer_state,
    )
    assert spec.imputer is not None
    name = spec.feature_names[3]
    recorded = float(spec.imputer["values"][name])
    values = [float("nan")] * len(spec.feature_names)
    transformed = spec.transform(values)
    assert transformed[3] == pytest.approx(recorded)


def test_transform_refuses_when_the_record_has_nothing_to_fill_with() -> None:
    """A column the imputer never recorded a value for cannot be filled from nothing.

    The record lists both columns - so the contract check passes - but holds a value
    for only one. Filling the other with the batch mean, with zero, or by dropping
    the row would each produce a number that looks like a forecast.
    """
    spec = PreprocessingSpec(
        feature_names=("a", "b"),
        imputer={
            "kind": "median",
            "columns": ["a", "b"],
            "fitted_on": "train",
            "fitted_rows": 3,
            "values": {"a": 1.0},
        },
    )
    with pytest.raises(ArtifactPreprocessingMismatchError) as caught:
        spec.transform([float("nan"), float("nan")])
    assert "'b'" in str(caught.value)


def test_a_zero_scale_is_reported_as_corruption_not_as_a_constant_column() -> None:
    """A zero divisor would be an infinity, and infinity would look like a forecast."""
    spec = PreprocessingSpec(
        feature_names=("a",),
        scaler={
            "kind": "standard",
            "columns": ["a"],
            "fitted_on": "train",
            "fitted_rows": 3,
            "mean": {"a": 1.0},
            "scale": {"a": 0.0},
        },
    )
    with pytest.raises(ArtifactPreprocessingMismatchError) as caught:
        spec.transform([1.0])
    assert "corrupt" in str(caught.value)


def test_no_recorded_preprocessing_passes_the_vector_through_unchanged() -> None:
    spec = PreprocessingSpec(feature_names=("a", "b"))
    assert spec.is_identity is True
    assert list(spec.transform([3.0, 4.0])) == [3.0, 4.0]


def test_an_empty_preprocessing_record_describes_itself() -> None:
    assert "unchanged" in PreprocessingSpec(feature_names=("a",)).describe()


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def test_a_manifest_written_by_phase4_loads_back_unchanged(manifests, tmp_path) -> None:
    """The disk round-trip is the deployment path, so it is tested on real output."""
    write_manifests(manifests, str(tmp_path))
    loaded = load_artifact_directory(str(tmp_path))
    live = ArtifactStore.from_manifests(manifests)

    assert len(loaded) == len(live)
    for artifact in loaded:
        original = live.require(artifact.model_id)
        assert artifact.feature_names == original.feature_names
        assert artifact.feature_digest == original.feature_digest
        assert artifact.target == original.target
        assert artifact.horizon == original.horizon
        assert dict(artifact.metrics_by_split) == dict(original.metrics_by_split)
        assert artifact.state == original.state
        assert artifact.random_seed == original.random_seed
        assert artifact.scaler_policy == original.scaler_policy


def test_a_blocked_model_survives_the_disk_round_trip_through_the_index(
    manifests, tmp_path
) -> None:
    """A dependency-blocked model must not vanish from a deployment's view.

    It has no manifest file - Phase 4 writes nothing for a model it could not train
    - so it exists in the directory only as an index entry. Reading the manifests
    alone would leave a deployment concluding xgboost was never attempted, with no
    way to learn from the artifacts that the blocker is a missing package rather
    than a missing experiment.
    """
    write_manifests(manifests, str(tmp_path))
    files = [name for name in os.listdir(str(tmp_path)) if name.endswith(".manifest.json")]
    assert not any("xgboost" in name for name in files), (
        "the fixture's blocked model unexpectedly has a manifest file, so the index-only "
        "path is no longer being exercised"
    )

    reloaded = ArtifactStore.from_directory(str(tmp_path))
    blocked = artifact_for(reloaded, "xgboost")
    assert blocked.state == STATE_DEPENDENCY_BLOCKED
    assert blocked.reason and "xgboost" in blocked.reason
    assert blocked.metrics_by_split == {}
    assert STATE_DEPENDENCY_BLOCKED not in {
        a.state for a in reloaded.servable_for(TARGET, "6h")
    }


def test_a_directory_without_an_index_still_loads_its_manifests(manifests, tmp_path) -> None:
    """The index is a convenience; the manifests beside it are the authority.

    A deployment that copied the `*.manifest.json` files without the index must
    still be able to serve, so an absent index is not an error.
    """
    write_manifests(manifests, str(tmp_path))
    os.remove(os.path.join(str(tmp_path), "phase4-artifacts.index.json"))
    loaded = ArtifactStore.from_directory(str(tmp_path))
    assert {a.model_family for a in loaded} == {"naive", "random_forest"}


def test_an_unreadable_index_does_not_hide_the_manifests_beside_it(
    manifests, tmp_path
) -> None:
    write_manifests(manifests, str(tmp_path))
    with open(os.path.join(str(tmp_path), "phase4-artifacts.index.json"), "w") as handle:
        handle.write("{ not json")
    loaded = ArtifactStore.from_directory(str(tmp_path))
    assert {a.model_family for a in loaded} == {"naive", "random_forest"}


def test_a_reloaded_feature_list_can_be_verified_against_its_own_digest(
    manifests, tmp_path
) -> None:
    """The reason `ARTIFACT_MANIFEST_VERSION` went to v2.

    Under v1 the written file held a digest over an ordered list and only a *sorted*
    list of names, so nobody reading the file back could confirm the two agreed. If
    this test ever needs the fingerprint's column order to be sorted, the fix has
    been undone.
    """
    write_manifests(manifests, str(tmp_path))
    path = os.path.join(str(tmp_path), sorted(os.listdir(str(tmp_path)))[0])
    payload = json.loads(open(path, encoding="utf-8").read())

    from app.engines.hydro.model_artifacts import feature_digest

    assert payload["feature_count"] == len(payload["feature_columns"])
    assert feature_digest(payload["feature_columns"]) == payload["feature_digest"]
    assert payload["feature_columns"] != sorted(payload["feature_columns"]), (
        "the written feature list is sorted, so the order-sensitive digest cannot be "
        "verified from the file"
    )


def test_a_missing_manifest_says_it_is_missing(tmp_path) -> None:
    with pytest.raises(ArtifactMissingError) as caught:
        load_artifact(str(tmp_path / "nope.manifest.json"))
    assert "never written" in str(caught.value)


def test_a_missing_directory_says_it_is_missing(tmp_path) -> None:
    with pytest.raises(ArtifactMissingError) as caught:
        load_artifact_directory(str(tmp_path / "nope"))
    assert "HYDRO_ARTIFACT_DIR" in str(caught.value)


def test_a_truncated_manifest_is_refused_not_parsed_leniently(tmp_path) -> None:
    path = tmp_path / "half.manifest.json"
    path.write_text('{"model_id": "x", "horizon":', encoding="utf-8")
    with pytest.raises(ArtifactMalformedError) as caught:
        load_artifact(str(path))
    assert "not valid JSON" in str(caught.value)
    assert "line" in str(caught.value)


def test_a_manifest_missing_a_required_field_names_the_field(store) -> None:
    """Every field of `REQUIRED_ARTIFACT_FIELDS` is named when one is absent."""
    payload = manifest_payload(artifact_for(store, "random_forest"))
    for field in REQUIRED_ARTIFACT_FIELDS:
        reduced = {k: v for k, v in payload.items() if k != field}
        with pytest.raises(ArtifactMalformedError) as caught:
            parse_artifact(reduced)
        assert field in str(caught.value), f"dropping {field!r} did not name it"


def test_a_payload_that_is_not_an_object_is_refused(store) -> None:
    with pytest.raises(ArtifactMalformedError) as caught:
        parse_artifact(["not", "a", "manifest"])
    assert "not a JSON object" in str(caught.value)


def test_a_future_schema_version_is_refused_by_name(store) -> None:
    good = artifact_for(store, "random_forest")
    with pytest.raises(ArtifactSchemaMismatchError) as caught:
        parse_artifact(manifest_payload(good, artifact_schema_version="navya-phase5-artifact/v2"))
    assert "navya-phase5-artifact/v1" in str(caught.value)
    assert "Refusing" in str(caught.value)


def test_an_old_manifest_version_is_refused_with_the_reason_it_cannot_be_loaded(
    store,
) -> None:
    """Not merely "wrong version" - the reason is that its digest is unverifiable."""
    good = artifact_for(store, "random_forest")
    with pytest.raises(ArtifactSchemaMismatchError) as caught:
        parse_artifact(manifest_payload(good, manifest_version=LEGACY_MANIFEST_VERSION))
    message = str(caught.value)
    assert LEGACY_MANIFEST_VERSION in message
    assert "feature_digest" in message
    assert "cannot be confirmed" in message


def test_unusable_preprocessing_in_a_manifest_is_reported_against_the_file(store) -> None:
    good = artifact_for(store, "random_forest")
    payload = manifest_payload(
        good,
        preprocessing={
            "feature_names": list(good.feature_names),
            "scaler": {"kind": "standard", "columns": list(good.feature_names),
                       "fitted_on": "test", "fitted_rows": 10},
            "imputer": None,
        },
    )
    with pytest.raises(ArtifactPreprocessingMismatchError) as caught:
        parse_artifact(payload, source="some/where.manifest.json")
    assert "some/where.manifest.json" in str(caught.value)
    assert "test" in str(caught.value)


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #


def test_the_store_indexes_by_model_id_and_reports_what_is_missing(store) -> None:
    assert len(store) == len(FAMILIES)
    assert store.require("random_forest-target_water_level_6h-6h-seed20240917")
    with pytest.raises(ArtifactMissingError) as caught:
        store.require("no_such_model")
    assert "no_such_model" in str(caught.value)
    assert store.get("no_such_model") is None


def test_the_store_separates_what_exists_from_what_may_be_served(store) -> None:
    """Both accessors, because "is there a 6h model?" and "can I serve one?" differ.

    The dependency-blocked artifact exists — Phase 4 tried and recorded why it could
    not train — but it is not an option. Collapsing the two would either hide the
    blocker or offer it.
    """
    everything = store.for_target_horizon(TARGET, "6h")
    servable = store.servable_for(TARGET, "6h")
    assert len(everything) == len(FAMILIES)
    assert len(servable) == len(everything) - 1
    assert {a.model_family for a in everything} == {"naive", "random_forest", "xgboost"}
    assert "xgboost" not in {a.model_family for a in servable}
    assert store.for_target_horizon(TARGET, "24h") == ()
    assert store.servable_for("target_inflow_6h", "6h") == ()


def test_the_store_groups_by_state(store) -> None:
    assert len(store.by_state(STATE_AVAILABLE)) == 2
    assert len(store.by_state(STATE_DEPENDENCY_BLOCKED)) == 1
    assert store.by_state(STATE_ARTIFACT_MISSING) == ()


def test_the_store_is_iterable_and_describable(store) -> None:
    assert [a.model_id for a in store] == list(store.model_ids)
    text = store.describe()
    assert STATE_AVAILABLE in text
    assert STATE_DEPENDENCY_BLOCKED in text


def test_the_store_is_frozen_so_serving_cannot_change_it(store) -> None:
    """A store that mutated under a request would make answers order-dependent."""
    with pytest.raises(Exception):
        store.artifacts = store.artifacts + ()


def test_attaching_preprocessing_returns_a_new_store_and_leaves_the_first(
    store, model_dataset
) -> None:
    """The store a request was answered from must not change under a later one.

    Exercised against a store loaded from disk, which is the case that needs it: a
    Phase 4 manifest records the scaler *policy* but not the fitted means, so the
    learned models come back without their preprocessing until a caller supplies it.
    """
    import tempfile

    from app.engines.hydro.model_artifacts import write_manifests

    _, manifests = build_run()
    directory = tempfile.mkdtemp()
    write_manifests(manifests, directory)
    reloaded = ArtifactStore.from_directory(directory)
    forest = artifact_for(reloaded, "random_forest")
    assert forest.preprocessing is None, (
        "a Phase 4 manifest is not expected to carry the fitted scaler; if it does, this test "
        "is no longer exercising the path it was written for"
    )
    assert forest.scaler_policy == "standard"

    spec = PreprocessingSpec(
        feature_names=tuple(model_dataset.feature_names),
        scaler=model_dataset.scaler_state,
    )
    fixed = reloaded.with_preprocessing({forest.model_id: spec})

    assert artifact_for(fixed, "random_forest").preprocessing is spec
    assert reloaded.require(forest.model_id).preprocessing is None, (
        "attaching preprocessing mutated the store the previous artifact came from"
    )


def test_attaching_the_wrong_columns_is_refused_against_the_artifact_that_caused_it(
    store, model_dataset
) -> None:
    forest = artifact_for(store, "random_forest")
    # Internally consistent - two names, two columns of mean and scale - so the spec
    # itself is well formed and the only thing wrong with it is that it does not
    # belong to this artifact.
    wrong = PreprocessingSpec(
        feature_names=("wrong", "columns"),
        scaler={
            "kind": "standard",
            "columns": ["wrong", "columns"],
            "fitted_on": "train",
            "fitted_rows": 10,
            "mean": {"wrong": 0.0, "columns": 0.0},
            "scale": {"wrong": 1.0, "columns": 1.0},
        },
    )
    with pytest.raises(ArtifactPreprocessingMismatchError) as caught:
        store.with_preprocessing({forest.model_id: wrong})
    message = str(caught.value)
    assert forest.model_id in message
    assert "'wrong'" in message


def test_a_baseline_artifact_needs_no_preprocessing_record(store) -> None:
    """The baseline's prediction rule reads the target history, not a feature vector.

    So its servability does not depend on a fitted record Phase 4 does not write,
    which is what makes it the one model Phase 5 can serve from a manifest alone.
    """
    naive = artifact_for(store, "naive")
    assert naive.uses_trained_parameters is False
    assert naive.state == STATE_AVAILABLE


# --------------------------------------------------------------------------- #
# Registry availability
# --------------------------------------------------------------------------- #


def test_the_registry_readout_names_every_family_and_honest_blockers() -> None:
    readout = registry_availability()
    assert readout["families"] == list(MODEL_FAMILIES)
    by_family = {row["model_family"]: row for row in readout["rows"]}
    assert by_family["naive"]["uses_trained_parameters"] is False
    assert by_family["random_forest"]["uses_trained_parameters"] is True
    for family in ("xgboost", "lstm", "gru"):
        if not by_family[family]["available_here"]:
            assert by_family[family]["blocked_reason"], (
                f"{family} is unavailable here but reports no reason; a blocked model must "
                "name what is missing"
            )


def test_a_blocked_family_reports_the_status_a_caller_would_see() -> None:
    readout = registry_availability()
    for row in readout["rows"]:
        expected = STATUS_READY if row["available_here"] else STATUS_DEPENDENCY_UNAVAILABLE
        assert row["handoff_status_when_unavailable"] == expected


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def test_the_fixture_synthetic_disclaimer_is_the_exact_pipeline_sentence() -> None:
    """Guards against a test asserting a *different* disclaimer than the code emits."""
    from app.engines.hydro.datasets import SYNTHETIC_DATA_DISCLAIMER

    assert SYNTHETIC_DISCLAIMER == SYNTHETIC_DATA_DISCLAIMER
    assert "MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION DATA" in (
        SYNTHETIC_DATA_DISCLAIMER
    )


def test_the_fixture_station_is_synthetic() -> None:
    assert STATION_A.startswith("SYNTHETIC-")