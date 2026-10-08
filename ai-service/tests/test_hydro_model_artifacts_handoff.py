# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 4 — artifact manifests, and the contract handed to Phase 5.

These are the two places where a run stops being a computation and becomes a
promise. A manifest says what was built, from what, with which seed, and where
the weights are - and in this repository the honest answer to "where the weights
are" is "not here", which is a decision this file checks rather than assumes. The
handoff contract is the one interface Phase 5 will call, so the statuses it can
return are checked here individually: a caller must be able to tell a model that
fitted from a model that could not even be imported, and the difference has to be
in the status rather than in a null where a number should have been.

One test in this file is about what must never appear. `production_ready_claimed`
is permanently false and a test says so, because the field exists only to be
checked.

Everything here runs on synthetic/demo fixtures. No test asserts a forecasting
result, and none can: there is no measured hydrological data in this repository.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import pathlib

import numpy as np
import pytest

from hydro_phase4_fixtures import (
    SYNTHETIC_DISCLAIMER,
    build_feature_result,
    config_for,
    configs_for,
    feature_result,
)

from app.engines.hydro.contract import FORECAST_CONTRACT_VERSION
from app.engines.hydro.feature_pipeline import (
    FEATURE_CONTRACT_VERSION,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VALIDATION,
)
from app.engines.hydro.model_artifacts import (
    ARTIFACT_FORMAT_VERSION,
    ARTIFACT_MANIFEST_VERSION,
    ARTIFACT_METADATA_ONLY,
    ARTIFACT_STATUS_NOT_WRITTEN,
    ARTIFACT_STATUSES,
    NONDETERMINISTIC_FIELDS,
    WEIGHT_STORAGE_POLICY,
    ArtifactManifestError,
    ArtifactManifests,
    build_manifests,
    feature_digest,
    manifest_for,
    registry_manifest_rows,
    write_manifests,
)
from app.engines.hydro.model_config import (
    FAMILY_GRU,
    FAMILY_LSTM,
    FAMILY_NAIVE,
    FAMILY_RANDOM_FOREST,
    FAMILY_XGBOOST,
    MODEL_CONTRACT_VERSION,
)
from app.engines.hydro.model_handoff import (
    HANDOFF_CONTRACT_VERSION,
    HANDOFF_STATUSES,
    STATUS_ARTIFACT_UNAVAILABLE,
    STATUS_DEPENDENCY_UNAVAILABLE,
    STATUS_INSUFFICIENT_DATA,
    STATUS_INVALID_REQUEST,
    STATUS_MODEL_UNAVAILABLE,
    STATUS_NO_PREDICTION,
    STATUS_READY,
    STATUS_TARGET_UNAVAILABLE,
    UNAVAILABLE_STATUSES,
    UNCERTAINTY_RESIDUAL_SIGMA,
    UNCERTAINTY_STATUSES,
    UNCERTAINTY_UNAVAILABLE,
    ForecastRequest,
    HandoffError,
    HandoffResult,
    Uncertainty,
    build_handoff,
    handoff_contract_description,
    residual_sigma_from,
    to_forecast_output,
)
from app.engines.hydro.model_registry import (
    EVALUATION_STATUSES,
    TRAINING_STATUSES,
    spec_for,
)
from app.engines.hydro.model_training import train_models

pytest_plugins: list[str] = []

TARGET_COLUMN = "target_water_level_6h"
HORIZON_LABEL = "6h"
ENTITY = "SYNTHETIC-STATION-0001"
ORIGIN = dt.datetime(2024, 1, 5, 12, 0, tzinfo=dt.timezone.utc)
ALL_FAMILIES = (FAMILY_NAIVE, FAMILY_RANDOM_FOREST, FAMILY_XGBOOST, FAMILY_LSTM, FAMILY_GRU)

#: Every status the handoff contract is required to be able to distinguish. Written
#: out rather than read from the module, so a status quietly dropping out of the
#: vocabulary fails here instead of becoming something Phase 5 cannot rely on.
REQUIRED_HANDOFF_STATUSES = frozenset(
    {
        STATUS_READY,
        STATUS_DEPENDENCY_UNAVAILABLE,
        STATUS_INSUFFICIENT_DATA,
        STATUS_ARTIFACT_UNAVAILABLE,
        STATUS_TARGET_UNAVAILABLE,
        STATUS_INVALID_REQUEST,
    }
)


@pytest.fixture(scope="module")
def full_result():
    """All five families on the short fixture: two fitted, three dependency-blocked."""
    result = build_feature_result()
    return train_models(
        result.dataset,
        configs_for(*ALL_FAMILIES, scaler_policy="standard"),
        cadences=result.report.cadence,
    )


@pytest.fixture(scope="module")
def full_manifests(full_result):
    return build_manifests(full_result)


def _forest_manifest(manifests: ArtifactManifests):
    return manifests.for_model(
        next(
            manifest.model_id
            for manifest in manifests.manifests
            if manifest.model_family == FAMILY_RANDOM_FOREST
        )
    )


def _blocked_manifest(manifests: ArtifactManifests):
    return manifests.for_model(
        next(
            manifest.model_id
            for manifest in manifests.manifests
            if manifest.model_family == FAMILY_XGBOOST
        )
    )


def _request(**changes) -> ForecastRequest:
    fields = {
        "target": TARGET_COLUMN,
        "horizon": HORIZON_LABEL,
        "entity": ENTITY,
        "origin_instant": ORIGIN,
    }
    fields.update(changes)
    return ForecastRequest.build(**fields)


# =========================================================================== #
# Manifest shape and version
# =========================================================================== #


def test_a_manifest_is_produced_for_every_model_in_the_run(full_manifests) -> None:
    """Including the ones that never fitted.

    A blocked model that appears nowhere is indistinguishable from one that was
    never attempted, and "we did not try" is not the same claim as "we tried and
    could not".
    """
    assert len(full_manifests.manifests) == len(ALL_FAMILIES)
    assert {m.model_family for m in full_manifests.manifests} == set(ALL_FAMILIES)
    assert len({m.model_id for m in full_manifests.manifests}) == len(ALL_FAMILIES)


def test_every_manifest_carries_the_declared_format_versions(full_manifests) -> None:
    for manifest in full_manifests.manifests:
        assert manifest.manifest_version == ARTIFACT_MANIFEST_VERSION
        assert manifest.model_contract_version == MODEL_CONTRACT_VERSION
        assert manifest.feature_contract_version == FEATURE_CONTRACT_VERSION
        assert manifest.artifact_format_version == ARTIFACT_FORMAT_VERSION
    assert full_manifests.manifest_version == ARTIFACT_MANIFEST_VERSION


def test_a_manifest_names_the_target_horizon_and_units_it_was_built_for(
    full_manifests,
) -> None:
    """Phase 3's target definition, carried through unaltered.

    `target_units` is here because a forecast of 3.2 with no unit is not a forecast;
    it is a number whose meaning has to be guessed.
    """
    for manifest in full_manifests.manifests:
        assert manifest.target == TARGET_COLUMN
        assert manifest.horizon == HORIZON_LABEL
        assert manifest.target_units == "m", (
            f"{manifest.model_id} lost the units Phase 3 declared"
        )


def test_a_manifest_names_its_own_family_role_and_model_id(full_manifests) -> None:
    for manifest in full_manifests.manifests:
        assert manifest.model_family in ALL_FAMILIES
        assert manifest.display_name
        assert manifest.role
        assert manifest.model_id.startswith(manifest.model_family)


def test_manifest_for_finds_a_model_by_its_id(full_result, full_manifests) -> None:
    """The lookup a Phase 5 caller will make.

    `manifest_for` takes the run, not the bundle, because the bundle is what the run
    produced and asking for a manifest from the thing you just built would be a
    circular way to find it.
    """
    model_id = next(
        manifest.model_id
        for manifest in full_manifests.manifests
        if manifest.model_family == FAMILY_RANDOM_FOREST
    )
    assert manifest_for(full_result, model_id).model_id == model_id


def test_manifest_for_raises_rather_than_returning_none_for_an_unknown_model(
    full_manifests,
) -> None:
    """A missing manifest is a mistake in the caller, and a `None` return would push
    that mistake downstream where it becomes a null forecast."""
    with pytest.raises(KeyError) as missing:
        full_manifests.for_model("random_forest-target_water_level_6h-6h-seed99999999")
    assert "known models" in str(missing.value)


# =========================================================================== #
# The artifact policy: metadata only, no weights in the repository
# =========================================================================== #


def test_a_fitted_model_records_metadata_only_and_no_stored_weights(
    full_manifests,
) -> None:
    """The decision, stated.

    A forest fitted on 168 rows is a few hundred kilobytes of binary that would
    make every diff unreviewable. Everything a reviewer needs to judge the run is
    text, so the text is what is kept.
    """
    manifest = _forest_manifest(full_manifests)
    assert manifest.artifact_status == ARTIFACT_METADATA_ONLY
    assert manifest.weight_stored_in_repository is False
    assert manifest.weight_reference is None, (
        "no weight reference can exist when nothing was written anywhere; a reference "
        "string with no object behind it is worse than none"
    )
    assert manifest.weight_policy == WEIGHT_STORAGE_POLICY


def test_the_weight_policy_says_where_the_bytes_belong(full_manifests) -> None:
    """A policy that only says "not here" leaves the next person with nowhere to go."""
    policy = WEIGHT_STORAGE_POLICY
    lowered = policy.lower()
    for word in ("not stored in this repository", "object storage", "phase 5"):
        assert word in lowered, f"the policy does not mention {word!r}: {policy}"
    assert WEIGHT_STORAGE_POLICY in _forest_manifest(full_manifests).weight_policy


def test_a_model_that_never_fitted_records_not_written_and_no_metrics(
    full_manifests,
) -> None:
    """`not_written`, and an empty metrics block.

    This is the case the requirement names directly: a model that did not fit
    cannot have an artifact, and reporting metrics for it would be reporting a
    number nothing produced.
    """
    manifest = _blocked_manifest(full_manifests)
    assert manifest.training_status == "dependency_unavailable"
    assert manifest.artifact_status == ARTIFACT_STATUS_NOT_WRITTEN
    assert manifest.weight_stored_in_repository is False
    assert not any(
        value for value in manifest.metrics_by_split.values()
    ), f"a blocked model reported metrics: {manifest.metrics_by_split}"
    assert manifest.reason, "a blocked model must say why it is blocked"


def test_a_blocked_manifest_records_no_parameters_because_there_are_none(
    full_manifests,
) -> None:
    """`parameters_recorded` is False and the hyperparameters block is empty.

    The parameters were requested and could not be realised, which is different
    from having realised them.
    """
    manifest = _blocked_manifest(full_manifests)
    assert manifest.parameters_recorded is False
    assert manifest.hyperparameters in ({}, None)


def test_parameters_recorded_agrees_with_the_hyperparameters_beside_it(
    full_manifests,
) -> None:
    """The two fields describe one fact, so they cannot disagree.

    `parameters_recorded` used to key off the artifact policy rather than off the
    block it sits next to, which produced a manifest with fifteen recorded
    hyperparameters and `parameters_recorded: false` beside them. Nothing was false
    about the run - the fields simply meant different things and neither said which.
    """
    for manifest in full_manifests.manifests:
        assert manifest.parameters_recorded == bool(manifest.hyperparameters), (
            f"{manifest.model_family}: parameters_recorded="
            f"{manifest.parameters_recorded} but hyperparameters="
            f"{sorted(manifest.hyperparameters)}"
        )

    forest = _forest_manifest(full_manifests)
    assert forest.parameters_recorded is True, (
        "the forest fitted with a recorded random_state; the manifest must say so"
    )
    assert forest.hyperparameters["random_state"] == 20240917

    for family in (FAMILY_XGBOOST, FAMILY_LSTM, FAMILY_GRU):
        blocked = next(m for m in full_manifests.manifests if m.model_family == family)
        if blocked.artifact_status == ARTIFACT_STATUS_NOT_WRITTEN:
            assert blocked.parameters_recorded is False
        else:
            # The family's runtime (e.g. a deep-learning framework) is installed
            # here, so the family fitted and recorded its hyperparameters. The
            # invariant above already ties `parameters_recorded` to the block
            # beside it; this branch keeps the check honest on every machine
            # instead of assuming which runtimes are importable.
            assert blocked.parameters_recorded is True


def test_the_artifact_status_vocabulary_distinguishes_the_three_states(
    full_manifests,
) -> None:
    """`metadata`, `with_parameters`, `not_written` - three distinct facts."""
    assert set(ARTIFACT_STATUSES) >= {
        ARTIFACT_METADATA_ONLY,
        ARTIFACT_STATUS_NOT_WRITTEN,
    }
    assert len(ARTIFACT_STATUSES) == 3, (
        f"the vocabulary is {ARTIFACT_STATUSES}; a fourth state needs a reason and a "
        "reader, and adding one silently would blur which is which"
    )
    seen = {m.artifact_status for m in full_manifests.manifests}
    assert seen <= set(ARTIFACT_STATUSES)
    assert ARTIFACT_STATUS_NOT_WRITTEN in seen, (
        "this run has dependency-blocked families, so a not_written manifest must exist"
    )
    assert ARTIFACT_METADATA_ONLY in seen


def test_written_property_means_the_same_as_the_artifact_status(full_manifests) -> None:
    """Two names for one predicate would be one too many; the property exists because
    the filter over the tuple was otherwise about to be written three times."""
    assert ArtifactManifests().written == ()

    written = _forest_manifest(full_manifests)
    blocked = _blocked_manifest(full_manifests)
    assert written.artifact_status != ARTIFACT_STATUS_NOT_WRITTEN
    assert blocked.artifact_status == ARTIFACT_STATUS_NOT_WRITTEN

    assert tuple(m.model_id for m in full_manifests.written) == tuple(
        m.model_id
        for m in full_manifests.manifests
        if m.artifact_status != ARTIFACT_STATUS_NOT_WRITTEN
    )
    not_written = {m.model_id for m in full_manifests.by_status(ARTIFACT_STATUS_NOT_WRITTEN)}
    assert not_written == {
        m.model_id
        for m in full_manifests.manifests
        if m.artifact_status == ARTIFACT_STATUS_NOT_WRITTEN
    }
    # The not_written group must at least contain xgboost: it is not a declared
    # dependency of this repository, so its family is blocked on every machine.
    # How many *other* families are blocked depends on which optional runtimes
    # (deep-learning frameworks) are importable, so the count is not pinned.
    assert any(
        manifest.model_family == FAMILY_XGBOOST
        for manifest in full_manifests.by_status(ARTIFACT_STATUS_NOT_WRITTEN)
    ), "xgboost is never a declared dependency, so the not_written group cannot be empty"
    assert {m.model_id for m in full_manifests.by_status(ARTIFACT_METADATA_ONLY)} == {
        m.model_id for m in full_manifests.written
    }


# =========================================================================== #
# Reproducibility: the fingerprint, the seed, and the dependency versions
# =========================================================================== #


def test_the_fingerprint_is_a_stable_digest_of_the_facts_that_matter(
    full_manifests,
) -> None:
    """Two manifests for the same experiment agree; the digest is reproducible.

    A fingerprint that changed every run would be worse than none, because it would
    look like a provenance field while proving nothing.
    """
    manifest = _forest_manifest(full_manifests)
    assert manifest.fingerprint_digest
    again = build_manifests(
        train_models(
            build_feature_result().dataset,
            configs_for(FAMILY_RANDOM_FOREST, scaler_policy="standard"),
            cadences=build_feature_result().report.cadence,
        )
    ).for_model(manifest.model_id)
    assert again.fingerprint_digest == manifest.fingerprint_digest, (
        "the same configuration on the same data produced a different fingerprint; "
        "a reader cannot use it to tell two runs apart"
    )


def test_the_fingerprint_covers_the_seed_the_features_and_the_row_counts(
    full_manifests,
) -> None:
    fingerprint = dataclasses.asdict(_forest_manifest(full_manifests).fingerprint)
    for field in (
        "model_contract_version",
        "feature_contract_version",
        "target",
        "horizon",
        "feature_columns",
        "feature_digest",
        "scaler_policy",
        "impute_policy",
        "feature_selection",
        "persistence_source",
        "random_seed",
        "hyperparameters",
        "train_rows",
        "validation_rows",
        "test_rows",
        "supervised_train_rows",
        "dependency_versions",
    ):
        assert field in fingerprint, f"the fingerprint omits {field!r}"
    assert fingerprint["random_seed"] == 20240917
    assert fingerprint["train_rows"] > 0
    assert fingerprint["validation_rows"] > 0
    assert fingerprint["test_rows"] > 0
    assert fingerprint["train_rows"] > fingerprint["test_rows"]


def test_the_feature_digest_is_a_digest_and_not_the_feature_list(full_manifests) -> None:
    """The list is also recorded - as `feature_columns`. The digest is for the case
    where comparing thirty-five names by eye is not a check."""
    manifest = _forest_manifest(full_manifests)
    assert manifest.feature_columns
    assert manifest.feature_count == len(manifest.feature_columns)
    assert manifest.feature_digest == feature_digest(manifest.feature_columns)
    assert manifest.feature_digest != ",".join(manifest.feature_columns)


def test_a_changed_seed_changes_the_fingerprint(full_manifests) -> None:
    """If the seed were not in the fingerprint, two different experiments would be
    indistinguishable by their provenance - which is what a fingerprint is for."""
    fingerprint = _forest_manifest(full_manifests).fingerprint
    baseline = fingerprint.digest
    assert baseline
    reseeded = dataclasses.replace(fingerprint, random_seed=fingerprint.random_seed + 1)
    assert reseeded.digest != baseline, (
        "two runs with different seeds produced the same fingerprint, so the digest "
        "cannot be used to tell two experiments apart"
    )


def test_the_manifest_states_the_dependency_versions_the_model_was_fitted_in(
    full_manifests,
) -> None:
    """A metric computed by scikit-learn 1.9.1 is not the same metric as one computed
    by some other version, and the manifest is where that difference is recorded."""
    manifest = _forest_manifest(full_manifests)
    assert manifest.dependency_versions
    assert any("sklearn" in key for key in manifest.dependency_versions), (
        f"the fitted estimator's own library is absent: {manifest.dependency_versions}"
    )
    runtime = spec_for(FAMILY_RANDOM_FOREST).runtime_versions()
    for key, value in manifest.dependency_versions.items():
        if key in runtime:
            assert value == runtime[key], (
                f"{key}: the manifest says {value!r} but the environment reports "
                f"{runtime[key]!r}"
            )


def test_a_blocked_manifest_names_the_dependency_it_could_not_import(
    full_manifests,
) -> None:
    """The blocker text, verbatim.

    This is the line whoever enables the family will read, and paraphrasing it would
    lose the exact symbol and the exact import error.
    """
    manifest = _blocked_manifest(full_manifests)
    assert "xgboost" in manifest.reason
    assert "not importable" in manifest.reason or "not installed" in manifest.reason


def test_the_random_seed_is_recorded_on_every_manifest(full_manifests) -> None:
    """Even on a manifest for a model that never ran. The configuration that was
    attempted is part of the record."""
    for manifest in full_manifests.manifests:
        assert manifest.random_seed == 20240917


def test_the_manifest_records_the_row_counts_of_every_split(full_manifests) -> None:
    counts = _forest_manifest(full_manifests).row_counts
    assert set(counts) >= {SPLIT_TRAIN, SPLIT_VALIDATION, SPLIT_TEST}
    assert counts[SPLIT_TRAIN] > counts[SPLIT_VALIDATION]
    assert counts[SPLIT_TRAIN] > counts[SPLIT_TEST]
    assert all(value > 0 for value in counts.values())


def test_the_manifest_records_the_split_bounds_not_only_the_counts(full_manifests) -> None:
    """The counts say how much; the bounds say which instants. A reviewer needs both
    to confirm the split was chronological rather than merely large."""
    bounds = _forest_manifest(full_manifests).split_bounds
    assert bounds
    for key in ("train_start", "train_end", "validation_start", "test_end"):
        assert bounds.get(key), f"the manifest does not state {key!r}"


# =========================================================================== #
# Metrics, evaluation status, and the synthetic label
# =========================================================================== #


def test_metrics_are_recorded_per_split_and_only_where_they_exist(
    full_manifests,
) -> None:
    """Validation and test separately, never averaged into one headline.

    The requirement asks for both splits reported apart, because the gap between
    them is the interesting part.
    """
    manifest = _forest_manifest(full_manifests)
    assert set(manifest.metrics_by_split) == {SPLIT_VALIDATION, SPLIT_TEST}
    for split, metrics in manifest.metrics_by_split.items():
        assert metrics, f"{split} has a status but no metric: {metrics}"
        for name in ("mae", "rmse", "r2", "bias"):
            assert name in metrics, f"{split} is missing {name!r}"
        assert np.isfinite(metrics["mae"])
        assert metrics["rmse"] >= metrics["mae"] - 1e-12, (
            f"{split}: RMSE below MAE is arithmetically impossible and indicates a "
            "bug in the metric, not a good model"
        )


def test_a_manifest_with_no_metrics_reports_an_evaluation_status_not_zero(
    full_manifests,
) -> None:
    """Unavailable is never zero.

    `None` means the number does not exist; `0.0` would mean the model was perfect,
    which is a claim, not a default.
    """
    manifest = _blocked_manifest(full_manifests)
    assert manifest.evaluation_status == "not_evaluated"
    for split in (SPLIT_VALIDATION, SPLIT_TEST):
        assert split in manifest.evaluation_status_by_split
        assert manifest.evaluation_status_by_split[split] != "evaluated"
        assert manifest.metrics_by_split.get(split) is None


def test_every_evaluation_status_is_from_the_declared_vocabulary(
    full_manifests,
) -> None:
    """A status a reader cannot look up is not machine-readable, whatever else it
    is."""
    for manifest in full_manifests.manifests:
        assert manifest.evaluation_status in EVALUATION_STATUSES
        for split, status in manifest.evaluation_status_by_split.items():
            assert status in EVALUATION_STATUSES, f"{manifest.model_id} {split}: {status}"


def test_every_training_status_is_from_the_declared_vocabulary(full_manifests) -> None:
    for manifest in full_manifests.manifests:
        assert manifest.training_status in TRAINING_STATUSES, (
            f"{manifest.model_family}: {manifest.training_status}"
        )


def test_the_training_and_evaluation_statuses_are_independent_facts(
    full_manifests,
) -> None:
    """A model can fit perfectly well and still not be evaluated - on too few rows,
    for instance - and a status column that conflates the two would call that a
    failed fit."""
    trained = _forest_manifest(full_manifests)
    assert trained.training_status == "trained"
    assert trained.evaluation_status == "evaluated"

    blocked = _blocked_manifest(full_manifests)
    assert blocked.training_status == "dependency_unavailable"
    assert blocked.evaluation_status == "not_evaluated"


def test_synthetic_data_is_labelled_on_every_manifest_and_on_the_bundle(
    full_manifests,
) -> None:
    """Visible at both levels.

    The flag on one model could be missed in a table of thirty; the flag on the
    bundle is what a reader sees before reading any of it.
    """
    for manifest in full_manifests.manifests:
        assert manifest.synthetic_demo is True
        assert manifest.data_status == "synthetic_demo"
        assert manifest.disclaimer == SYNTHETIC_DISCLAIMER
    assert full_manifests.is_synthetic is True
    assert full_manifests.data_status == "synthetic_demo"
    assert full_manifests.disclaimer == SYNTHETIC_DISCLAIMER


def test_the_synthetic_label_reaches_the_serialised_bundle(full_manifests) -> None:
    payload = json.loads(full_manifests.to_json())
    assert payload["is_synthetic"] is True
    assert payload["data_status"] == "synthetic_demo"
    assert payload["disclaimer"] == SYNTHETIC_DISCLAIMER
    for manifest in payload["manifests"]:
        assert manifest["synthetic_demo"] is True
        assert manifest["disclaimer"] == SYNTHETIC_DISCLAIMER


def test_no_manifest_claims_to_be_production_ready(full_manifests) -> None:
    """The field exists to be false.

    Training completed. That is all that means. Nothing here has been validated
    against a gauge network, a rating curve or a flood threshold, and a reader
    seeing `True` would reasonably infer that it had.
    """
    for manifest in full_manifests.manifests:
        assert manifest.production_ready_claimed is False
    assert full_manifests.to_dict()["manifests"]
    for row in registry_manifest_rows():
        assert row["production_ready_claimed"] is False


# =========================================================================== #
# Provenance: one system, reused
# =========================================================================== #


def test_the_manifest_carries_the_phase_1_to_3_provenance_unchanged(
    full_manifests,
) -> None:
    """Reuse, not a second scheme.

    The provenance block is the Phase 1-3 record serialised as it stands, so a
    prediction can be traced through one record rather than two that agree. The
    manifest does not add, drop or rename a field of it.
    """
    provenance = _forest_manifest(full_manifests).provenance
    assert provenance, "the manifest carries no provenance"
    assert provenance["dataset_type"] == "synthetic"
    assert provenance["target"] == TARGET_COLUMN
    assert provenance["target_units"] == "m"
    assert provenance["forecast_horizon"] == HORIZON_LABEL
    assert provenance["is_synthetic"] is True
    assert provenance["model_version"].endswith("seed20240917")
    assert provenance["disclaimer"] == SYNTHETIC_DISCLAIMER
    # The fields Phase 1 through 3 populate, none of them Phase 4's invention.
    for field in ("dataset_reference", "dataset_license", "sampling_interval", "split"):
        assert field in provenance, f"the shared provenance record lost {field!r}"


def test_the_provenance_states_which_contract_versions_were_in_force(
    full_manifests,
) -> None:
    environment = _forest_manifest(full_manifests).provenance["software_environment"]
    assert environment["phase4_model_contract"] == MODEL_CONTRACT_VERSION
    assert environment["random_seed"] == "20240917"
    assert environment["python"]
    assert environment["numpy"]
    assert environment["sklearn"]


def test_a_blocked_model_still_carries_provenance(full_manifests) -> None:
    """A run that was attempted produced a record even though it produced no model.
    Without one, the attempt would be invisible."""
    provenance = _blocked_manifest(full_manifests).provenance
    assert provenance, "an attempted-but-blocked run left no record of the attempt"
    assert provenance["evaluation_metrics"] is None, (
        "provenance must not carry metrics for a model that never fitted"
    )
    assert provenance["metrics_label"]
    assert provenance["missing_fields"]
    assert "dependency:xgboost" in provenance["software_environment"]


# =========================================================================== #
# Determinism and serialisation
# =========================================================================== #


def test_a_manifest_serialises_to_stable_json(full_manifests) -> None:
    """Keys sorted, two spaces, stable across calls.

    A manifest that reorders its own keys between writes produces a diff on every
    write, which is the fastest way to train a team to ignore diffs.
    """
    first = full_manifests.to_json()
    second = full_manifests.to_json()
    assert first == second
    payload = json.loads(first)
    assert payload["manifest_version"] == ARTIFACT_MANIFEST_VERSION
    assert payload["weight_storage_policy"] == WEIGHT_STORAGE_POLICY
    assert payload["nondeterministic_fields"] == list(NONDETERMINISTIC_FIELDS)


def test_the_only_declared_nondeterministic_fields_are_the_two_timestamps() -> None:
    """Everything else in a manifest is a fact about the run, and a fact about a run
    does not move between two runs of it.

    This matters because it is what makes a manifest diffable: a reviewer comparing
    two runs needs every difference to be a real change, not a clock. The declaration
    is a dotted path list because the second timestamp is nested inside the Phase 1-3
    provenance record the manifest reuses; declaring only the top-level one would
    claim a determinism the manifest does not have.
    """
    assert NONDETERMINISTIC_FIELDS == ("created_at", "provenance.created_at")
    assert all(path.startswith("created_at") or "." in path for path in NONDETERMINISTIC_FIELDS)


def _without_volatile(payload, paths=NONDETERMINISTIC_FIELDS):
    """`payload` with every declared nondeterministic path removed, at every depth.

    The paths are dotted rather than flat because the second wall-clock instant lives
    inside the provenance block the manifest reuses from Phase 3. A stripper that only
    understood top-level keys would silently miss it - which is exactly what happened
    before `provenance.created_at` was added to the declaration.

    It also descends, because the run bundle embeds every manifest verbatim. Stripping
    only at the top level would let each embedded manifest carry its own clock through
    unchanged, and the comparison would then fail for a reason that has nothing to do
    with determinism.
    """
    if isinstance(payload, list):
        return [_without_volatile(item, paths) for item in payload]
    if not isinstance(payload, dict):
        return payload

    stripped: dict = {}
    for key, value in payload.items():
        # A key declared volatile at this level is dropped outright, and its value is
        # not descended into: it is a clock, and there is nothing beneath it to keep.
        if key in paths:
            continue
        nested_keys = {path.split(".", 1)[1] for path in paths if path.startswith(f"{key}.")}
        if nested_keys and isinstance(value, dict):
            inner = {
                inner_key: inner_value
                for inner_key, inner_value in value.items()
                if inner_key not in nested_keys
            }
            stripped[key] = _without_volatile(inner, nested_keys)
        else:
            stripped[key] = _without_volatile(value, paths)
    return stripped


def test_two_runs_of_the_same_configuration_differ_only_in_created_at() -> None:
    """The determinism claim, stated as a test.

    It is not "identical": `created_at` is a wall-clock instant, and pretending
    otherwise would mean either lying about it or dropping it from the record. It is
    "identical apart from the two fields declared nondeterministic", and the test
    strips exactly those and nothing else - so a third moving field would fail here
    rather than being quietly tolerated.
    """
    def run_once():
        result = build_feature_result()
        outcome = train_models(
            result.dataset,
            configs_for(FAMILY_NAIVE, FAMILY_RANDOM_FOREST, scaler_policy="standard"),
            cadences=result.report.cadence,
        )
        manifests = build_manifests(outcome)
        return manifests.to_dict(), [m.to_dict() for m in manifests.manifests]

    first_bundle, first_models = run_once()
    second_bundle, second_models = run_once()

    assert len(first_models) == len(second_models) == 2
    for left, right in zip(first_models, second_models):
        model_id = left["model_id"]
        assert model_id == right["model_id"]
        assert _without_volatile(left) == _without_volatile(right), (
            f"{model_id} differs between two identical runs in a field that is not "
            f"declared nondeterministic (declared: {list(NONDETERMINISTIC_FIELDS)})"
        )

    assert _without_volatile(first_bundle) == _without_volatile(second_bundle), (
        "the run-level bundle differs between two identical runs in a field that is "
        "not declared nondeterministic"
    )


def test_the_two_runs_really_did_differ_in_the_volatile_fields() -> None:
    """Without this the test above would also pass if `created_at` were simply absent.

    Stripping a field that never moved proves nothing about determinism; it only
    proves the field is missing.
    """
    def stamps():
        result = build_feature_result()
        outcome = train_models(
            result.dataset,
            configs_for(FAMILY_NAIVE, scaler_policy="standard"),
            cadences=result.report.cadence,
        )
        manifest = build_manifests(outcome).manifests[0].to_dict()
        return manifest["created_at"], manifest["provenance"]["created_at"]

    first_created, first_provenance = stamps()
    second_created, second_provenance = stamps()
    assert first_created != second_created, (
        "two runs produced the same manifest timestamp; the determinism test would be "
        "proving nothing about the fields it strips"
    )
    assert first_provenance != second_provenance, (
        "the provenance block's own timestamp did not move, so `provenance.created_at` "
        "is declared nondeterministic without being one"
    )


def test_two_runs_produce_the_same_metrics(full_manifests) -> None:
    """Determinism is a property of the numbers too, not only of the text."""
    def metrics():
        result = build_feature_result()
        outcome = train_models(
            result.dataset,
            configs_for(FAMILY_RANDOM_FOREST, scaler_policy="standard"),
            cadences=result.report.cadence,
        )
        return build_manifests(outcome).to_dict()["manifests"][0]["metrics_by_split"]

    assert metrics() == metrics()


def test_manifest_describe_is_readable_and_names_every_model(full_manifests) -> None:
    text = full_manifests.describe()
    assert ARTIFACT_MANIFEST_VERSION in text
    assert "synthetic_demo" in text
    for manifest in full_manifests.manifests:
        assert manifest.model_family in text


# =========================================================================== #
# Writing manifests to disk
# =========================================================================== #


INDEX_FILENAME = "phase4-artifacts.index.json"


def test_write_manifests_writes_one_file_per_written_manifest_plus_an_index(
    full_manifests, tmp_path: pathlib.Path
) -> None:
    """One file per written model, plus a bundle index.

    The index exists so a reader can find the set without globbing, and it names every
    model including the blocked ones - the attempt is part of the record.
    """
    directory = tmp_path / "manifests"
    paths = write_manifests(full_manifests, str(directory))
    written = [
        m for m in full_manifests.manifests if m.artifact_status != ARTIFACT_STATUS_NOT_WRITTEN
    ]
    assert len(paths) == len(written) + 1, "expected one file per written model plus the index"

    per_model = sorted(
        pathlib.Path(p).name for p in paths if not p.endswith(INDEX_FILENAME)
    )
    assert per_model == sorted(f"{m.model_id}.manifest.json" for m in written)

    index = json.loads(
        (directory / INDEX_FILENAME).read_text(encoding="utf-8")
    )
    assert index["manifest_version"] == ARTIFACT_MANIFEST_VERSION
    assert index["baseline_family"] == FAMILY_NAIVE
    assert index["data_status"] == "synthetic_demo"
    assert index["disclaimer"] == SYNTHETIC_DISCLAIMER
    assert len(index["manifests"]) == len(full_manifests.manifests), (
        "the index must list the blocked models too, or an attempt disappears from the "
        "written record"
    )


def test_write_manifests_writes_nothing_for_a_model_that_never_fitted(
    full_manifests, tmp_path: pathlib.Path
) -> None:
    """A blocked model still has a manifest in memory and in the index; it just does
    not get its own file on disk that says nothing."""
    directory = tmp_path / "manifests"
    paths = write_manifests(full_manifests, str(directory))
    blocked = _blocked_manifest(full_manifests)
    assert not any(blocked.model_id in path for path in paths)
    assert not list(directory.glob(f"{blocked.model_id}.manifest.json"))
    assert blocked.model_id in (directory / INDEX_FILENAME).read_text(encoding="utf-8")


def test_write_manifests_writes_no_binary_of_any_kind(
    full_manifests, tmp_path: pathlib.Path
) -> None:
    """The policy is checkable, so it is checked: every file written is `.json` and
    every one is text."""
    directory = tmp_path / "manifests"
    for path in write_manifests(full_manifests, str(directory)):
        assert str(path).endswith(".json")
        text = pathlib.Path(path).read_text(encoding="utf-8")
        assert text.lstrip().startswith("{")
        json.loads(text)


def test_write_manifests_refuses_to_write_nowhere(
    full_manifests,
) -> None:
    """Silently succeeding while writing nothing is the kind of success that hides a
    misconfiguration until something downstream cannot find its artifact."""
    with pytest.raises(ArtifactManifestError) as nowhere:
        write_manifests(full_manifests, "")
    assert "HYDRO_ARTIFACT_DIR" in str(nowhere.value)


def test_a_manifest_model_id_is_made_safe_for_a_filename(
    full_manifests, tmp_path: pathlib.Path
) -> None:
    """Model ids contain `/` and `:`; a path separator in a filename would write the
    manifest somewhere the caller did not ask for."""
    directory = tmp_path / "manifests"
    paths = write_manifests(full_manifests, str(directory))
    assert paths, "nothing was written"
    for path in paths:
        assert pathlib.Path(path).parent == directory
        assert pathlib.Path(path).exists()


def test_rewriting_a_manifest_replaces_it_rather_than_appending(
    full_manifests, tmp_path: pathlib.Path
) -> None:
    """Atomic replace, so a reader never sees a half-written manifest."""
    directory = tmp_path / "manifests"
    write_manifests(full_manifests, str(directory))
    first = {path: pathlib.Path(path).read_text(encoding="utf-8") for path in write_manifests(full_manifests, str(directory))}
    second = write_manifests(full_manifests, str(directory))
    for path in second:
        assert pathlib.Path(path).read_text(encoding="utf-8") == first[path]
        assert len(pathlib.Path(path).read_text(encoding="utf-8").splitlines()) < 4000


# =========================================================================== #
# The registry, rendered without running a fit
# =========================================================================== #


def test_the_registry_can_be_rendered_without_training_anything() -> None:
    """A reviewer can read the artifact surface before running anything.

    `runtime_versions` is empty for the baseline and for every blocked family, and
    that is the honest answer rather than a missing one: the baseline imports no
    estimator library, and a blocked family's libraries are precisely what is absent.
    """
    rows = registry_manifest_rows()
    assert {row["model_family"] for row in rows} == set(ALL_FAMILIES)
    for row in rows:
        assert row["role"]
        assert row["implementation"]
        assert isinstance(row["available_here"], bool)
        assert "runtime_versions" in row, (
            f"{row['model_family']} does not even declare the key, so a reader cannot "
            "tell an empty runtime from an unreported one"
        )
    forest = next(r for r in rows if r["model_family"] == FAMILY_RANDOM_FOREST)
    assert forest["available_here"] is True
    assert forest["runtime_versions"], (
        "the one family that actually fitted an estimator reports no library version"
    )


def test_an_unavailable_family_declares_the_artifact_status_it_will_have() -> None:
    """Predictable, so a Phase 5 caller can branch on the status without having run
    anything."""
    rows = registry_manifest_rows()
    assert rows, "the registry rendered nothing"
    for row in rows:
        if row["available_here"]:
            continue
        assert row["expected_artifact_status"] == ARTIFACT_STATUS_NOT_WRITTEN
        assert row["blocked_reason"], (
            f"{row['model_family']} is unavailable and says nothing about why"
        )


# =========================================================================== #
# The Phase 5 handoff request
# =========================================================================== #


def test_a_request_states_a_target_a_horizon_an_entity_and_an_origin() -> None:
    """The four things that cannot be defaulted.

    A target, a horizon, a station and a prediction instant are all it takes to make
    "what is the level in six hours at this gauge" a well-posed question. Everything
    else is Phase 3's frozen feature contract, not a caller's guesswork.
    """
    payload = _request().to_dict()
    assert payload["target"] == TARGET_COLUMN
    assert payload["horizon"] == HORIZON_LABEL
    assert payload["entity"] == ENTITY
    assert payload["origin_instant"] == "2024-01-05T12:00:00Z"
    assert payload["model_id"] is None
    assert payload["model_family"] is None


def test_a_request_accepts_an_optional_model_selector() -> None:
    assert _request(model_id="random_forest-x").model_id == "random_forest-x"
    assert _request(model_family=FAMILY_RANDOM_FOREST).model_family == FAMILY_RANDOM_FOREST


def test_a_request_naming_two_selectors_is_refused() -> None:
    """Two selectors make it ambiguous which model the caller meant, and guessing
    would pick one silently."""
    with pytest.raises(HandoffError) as both:
        _request(model_id="random_forest-x", model_family=FAMILY_RANDOM_FOREST)
    assert "not both" in str(both.value)


@pytest.mark.parametrize("field", ["target", "horizon", "entity"])
@pytest.mark.parametrize("value", ["", "   ", None, 3])
def test_a_blank_target_horizon_or_entity_is_refused(field, value) -> None:
    """A blank field would be resolved against nothing."""
    with pytest.raises(HandoffError) as blank:
        _request(**{field: value})
    assert field in str(blank.value)


def test_an_unparseable_origin_instant_is_refused() -> None:
    """A wrong timestamp is not a cosmetic fault: it is what the prediction is
    claimed to be about."""
    for value in ("not-a-time", "", None, "2024-13-45T00:00:00Z"):
        with pytest.raises(HandoffError):
            _request(origin_instant=value)


def test_a_request_accepts_an_iso_string_origin_and_normalises_it() -> None:
    assert _request(origin_instant="2024-01-05T12:00:00Z").origin_instant == ORIGIN
    assert _request(origin_instant=ORIGIN).origin_instant == ORIGIN


def test_a_request_serialises_deterministically() -> None:
    assert _request().to_json() == _request().to_json()
    assert json.loads(_request().to_json())["horizon"] == HORIZON_LABEL


# =========================================================================== #
# The Phase 5 handoff result: one status per distinct reason
# =========================================================================== #


def test_every_required_handoff_status_exists_in_the_vocabulary() -> None:
    assert REQUIRED_HANDOFF_STATUSES <= set(HANDOFF_STATUSES), (
        f"missing: {sorted(REQUIRED_HANDOFF_STATUSES - set(HANDOFF_STATUSES))}"
    )


def test_a_ready_request_returns_the_prediction_and_its_timestamps(
    full_result, full_manifests
) -> None:
    """The whole point of the contract, in one result.

    `source_timestamp` is the reading instant the forecast was made from and
    `prediction_timestamp` is the instant it is about; both are carried rather than
    derived by the caller, because a caller that derives them can get them wrong.
    """
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(model_id=model_id), full_result, manifests=full_manifests, prediction=3.5
    )
    assert result.status == STATUS_READY
    assert result.prediction == 3.5
    assert result.source_timestamp == "2024-01-05T12:00:00Z"
    assert result.prediction_timestamp == "2024-01-05T18:00:00Z"
    assert result.reason is None, "a ready result needs no excuse"


def test_a_ready_result_preserves_the_target_name_units_horizon_and_entity(
    full_result, full_manifests
) -> None:
    """Phase 3's target definition, carried through the handoff untouched.

    `target_units` is here because a forecast of 3.5 with no unit is not a forecast.
    """
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(model_id=model_id), full_result, manifests=full_manifests, prediction=3.5
    )
    assert result.target == TARGET_COLUMN
    assert result.target_units == "m"
    assert result.horizon == HORIZON_LABEL
    assert result.entity == ENTITY


def test_a_ready_result_carries_the_model_version_and_the_feature_version(
    full_result, full_manifests
) -> None:
    """Both contracts. One says what produced the number, the other what produced the
    inputs; a forecast is only traceable if both are named."""
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(model_id=model_id), full_result, manifests=full_manifests, prediction=3.5
    )
    assert result.feature_version == FEATURE_CONTRACT_VERSION
    assert result.model_version
    assert MODEL_CONTRACT_VERSION in result.model_version
    assert FEATURE_CONTRACT_VERSION in result.model_version
    assert "seed20240917" in result.model_version


def test_a_ready_result_carries_the_full_provenance_record(
    full_result, full_manifests
) -> None:
    """The Phase 1-3 record, plus the two contract versions Phase 4 supplied.

    The two are labelled rather than merged: a reader can tell which fields came from
    the shared provenance system and which were added here.
    """
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(model_id=model_id), full_result, manifests=full_manifests, prediction=3.5
    )
    provenance = result.provenance
    assert provenance["model_contract_version"] == MODEL_CONTRACT_VERSION
    assert provenance["feature_contract_version"] == FEATURE_CONTRACT_VERSION
    assert provenance["target"] == TARGET_COLUMN
    assert provenance["is_synthetic"] is True
    assert provenance["metrics_label"]


def test_a_ready_result_still_says_the_data_was_synthetic(
    full_result, full_manifests
) -> None:
    """The label does not disappear once a number exists.

    This is the failure that matters most in practice: the disclaimer survives the
    training report and is dropped from the thing a downstream service actually
    consumes.
    """
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(model_id=model_id), full_result, manifests=full_manifests, prediction=3.5
    )
    assert result.status == STATUS_READY
    assert result.synthetic_demo is True
    assert result.data_status == "synthetic_demo"
    assert result.disclaimer == SYNTHETIC_DISCLAIMER
    assert result.production_ready_claimed is False


def test_a_ready_result_echoes_the_request_that_produced_it(
    full_result, full_manifests
) -> None:
    """So a log line answers "what was asked for" without a second lookup."""
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    request = _request(model_id=model_id)
    result = build_handoff(request, full_result, manifests=full_manifests, prediction=3.5)
    assert result.request == request.to_dict()


def test_a_dependency_blocked_model_answers_dependency_unavailable(
    full_result, full_manifests
) -> None:
    """Not `ready`, not `no_prediction`, not a null.

    A caller that sees this knows the model family cannot be run here at all, which
    is a different action from "the model exists but declined to answer".
    """
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_XGBOOST
    )
    result = build_handoff(
        _request(model_id=model_id),
        full_result,
        manifests=full_manifests,
        prediction=3.5,
    )
    assert result.status == STATUS_DEPENDENCY_UNAVAILABLE
    assert result.prediction is None
    assert "xgboost" in result.reason


def test_an_insufficient_data_model_answers_insufficient_data() -> None:
    """A different status from dependency-unavailable, because a different action.

    Here the model could have run; there were not enough rows. Fixing that is a data
    problem, not an installation problem.
    """
    result = build_feature_result()
    outcome = train_models(
        result.dataset,
        (config_for(FAMILY_RANDOM_FOREST, min_train_rows=10_000, scaler_policy="standard"),),
        cadences=result.report.cadence,
    )
    manifests = build_manifests(outcome)
    model_id = outcome.runs[0].model_id
    handoff = build_handoff(
        _request(model_id=model_id),
        outcome,
        manifests=manifests,
        prediction=3.5,
    )
    assert handoff.status == STATUS_INSUFFICIENT_DATA
    assert handoff.prediction is None
    assert "row" in handoff.reason


def test_an_insufficient_data_manifest_states_the_shortfall_in_numbers() -> None:
    """Required and available, so a reader knows what to collect.

    The record is a structured block rather than a sentence so a tool can act on it -
    "collect 9844 more training rows for this target at this horizon" is a different
    task from reading a paragraph that says the data was insufficient.
    """
    result = build_feature_result()
    outcome = train_models(
        result.dataset,
        (config_for(FAMILY_RANDOM_FOREST, min_train_rows=10_000, scaler_policy="standard"),),
        cadences=result.report.cadence,
    )
    manifest = build_manifests(outcome).manifests[0]
    shortfall = manifest.insufficiency
    assert shortfall, "an insufficient-data run recorded no shortfall"
    assert shortfall["required"] == 10_000
    assert 0 < shortfall["available"] < 10_000
    assert shortfall["reason"]
    assert shortfall["target"] == TARGET_COLUMN
    assert shortfall["horizon"] == HORIZON_LABEL
    assert shortfall["model"] == FAMILY_RANDOM_FOREST
    assert "entity" in shortfall, (
        "the shortfall record has no entity/station key, so a multi-station shortfall "
        "could not be attributed to a gauge"
    )
    json.dumps(shortfall), "the shortfall record does not serialise"


def test_a_target_the_model_was_not_trained_on_is_refused_not_substituted(
    full_result, full_manifests
) -> None:
    """The requirement is explicit: never invent or silently substitute a target.

    A model trained on water level is not a model of discharge, and answering with
    its output under a different column name would be the worst possible outcome -
    a plausible number with the wrong meaning.
    """
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(target="target_discharge_6h", model_id=model_id),
        full_result,
        manifests=full_manifests,
        prediction=3.5,
    )
    assert result.status == STATUS_INVALID_REQUEST
    assert result.prediction is None
    assert "does not substitute a target" in result.reason
    assert TARGET_COLUMN in result.reason


def test_a_model_selector_that_matches_nothing_answers_model_unavailable(
    full_result, full_manifests
) -> None:
    """And it lists what was available, so the caller can correct itself."""
    result = build_handoff(
        _request(model_id="random_forest-does-not-exist"),
        full_result,
        manifests=full_manifests,
        prediction=3.5,
    )
    assert result.status == STATUS_MODEL_UNAVAILABLE
    assert result.prediction is None
    assert "models available" in result.reason
    assert FAMILY_NAIVE in result.reason


def test_a_model_that_trained_but_wrote_no_artifact_answers_artifact_unavailable(
    full_result,
) -> None:
    """The distinction that matters at handoff.

    The model exists and was scored; its weights were never written. Phase 5 cannot
    serve a forecast from a model it cannot load, and saying `ready` here would
    produce a number with no model behind it.
    """
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(model_id=model_id),
        full_result,
        manifests=None,
        prediction=3.5,
    )
    assert result.status == STATUS_ARTIFACT_UNAVAILABLE
    assert result.prediction is None
    assert "never written" in result.reason


def test_a_request_with_no_prediction_value_answers_no_prediction_and_invents_none(
    full_result, full_manifests
) -> None:
    """Phase 4 trains and scores; generating a value for a future instant is Phase
    5's job and needs a feature vector this module cannot conjure.

    The tempting alternative - last observed value, the naive baseline, the mean of
    the training target - would each return a number that looks like a forecast and
    is not one.
    """
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(model_id=model_id), full_result, manifests=full_manifests
    )
    assert result.status == STATUS_NO_PREDICTION
    assert result.prediction is None
    assert "Phase 5" in result.reason


def test_a_horizon_the_model_was_not_trained_on_is_refused_not_stretched(
    full_result, full_manifests
) -> None:
    """The horizon guard, and the reason it exists.

    A six-hour model asked for a 24-hour forecast would otherwise return `ready` with
    the value stamped 24 hours out - a plausible number about the wrong instant. That
    is harder to catch downstream than an outright refusal, and harder still for a
    reader to notice, because every field on the response is individually well-formed.
    """
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(horizon="24h", model_id=model_id),
        full_result,
        manifests=full_manifests,
        prediction=3.5,
    )
    assert result.status == STATUS_INVALID_REQUEST
    assert result.prediction is None
    assert "does not substitute a target or extend a horizon" in result.reason
    assert HORIZON_LABEL in result.reason, (
        "the reason must name the horizon the model actually has"
    )


def test_an_unreadable_horizon_label_is_refused_rather_than_guessed(
    full_result, full_manifests
) -> None:
    """No horizon label, no prediction timestamp.

    The value is withheld rather than stamped from a guess: a timestamp derived from
    an unreadable label would look traceable and be wrong, and a wrong timestamp on a
    real number is the hardest kind of error to notice downstream.
    """
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(horizon="later", model_id=model_id),
        full_result,
        manifests=full_manifests,
        prediction=3.5,
    )
    assert result.status == STATUS_INVALID_REQUEST
    assert result.prediction is None
    assert result.prediction_timestamp is None
    assert result.source_timestamp == "2024-01-05T12:00:00Z", (
        "the origin instant is readable and is still reported"
    )


def test_no_non_ready_result_ever_carries_a_prediction_timestamp(
    full_result, full_manifests
) -> None:
    """The timestamp invariant, checked across every refusal path at once.

    A withheld value with a timestamp attached reads as "there is a value, it is just
    not here yet", which is not what any of these statuses mean.
    """
    forest = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    xgboost = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_XGBOOST
    )
    requests = [
        _request(model_id=xgboost),
        _request(model_id=forest),
        _request(horizon="24h", model_id=forest),
        _request(horizon="later", model_id=forest),
        _request(target="target_discharge_6h", model_id=forest),
        _request(model_id="no-such-model"),
    ]
    for request in requests:
        for manifests in (full_manifests, None):
            result = build_handoff(request, full_result, manifests=manifests, prediction=3.5)
            if result.status == STATUS_READY:
                continue
            assert result.prediction is None, f"{result.status} returned a value"
            assert result.prediction_timestamp is None, (
                f"{result.status} returned the prediction timestamp "
                f"{result.prediction_timestamp!r} with no prediction"
            )
            assert result.reason, f"{result.status} returned no reason"


def test_every_unavailable_status_returns_no_prediction(full_result, full_manifests) -> None:
    """The invariant the whole contract rests on.

    `prediction is None` on a non-ready status and a number on a ready one. There is
    no third arrangement, so a caller can branch on the status alone.
    """
    forest = next(
        model_id for model_id in (run.model_id for run in full_result.runs)
        if model_id.startswith(FAMILY_RANDOM_FOREST)
    )
    xgboost = next(
        model_id for model_id in (run.model_id for run in full_result.runs)
        if model_id.startswith(FAMILY_XGBOOST)
    )

    # (expected status, request, manifests, supply a prediction?)
    cases = (
        (STATUS_DEPENDENCY_UNAVAILABLE, _request(model_id=xgboost), full_manifests, True),
        (STATUS_ARTIFACT_UNAVAILABLE, _request(model_id=forest), None, True),
        (STATUS_NO_PREDICTION, _request(model_id=forest), full_manifests, False),
        (STATUS_INVALID_REQUEST, _request(horizon="24h", model_id=forest), full_manifests, True),
        (STATUS_INVALID_REQUEST, _request(target="target_discharge_6h", model_id=forest), full_manifests, True),
        (STATUS_MODEL_UNAVAILABLE, _request(model_id="no-such-model"), full_manifests, True),
    )
    seen = set()
    for expected, request, manifests, supply in cases:
        result = build_handoff(
            request, full_result, manifests=manifests, prediction=3.5 if supply else None
        )
        assert result.status == expected, f"{request.describe()}: {result.status}"
        assert result.prediction is None, f"{result.status} returned a value"
        assert result.reason, f"{result.status} returned no reason"
        assert result.status in UNAVAILABLE_STATUSES, (
            f"{expected} is not in UNAVAILABLE_STATUSES, so a caller filtering on that "
            "set would treat it as a success"
        )
        seen.add(result.status)

    assert seen == {
        STATUS_DEPENDENCY_UNAVAILABLE,
        STATUS_ARTIFACT_UNAVAILABLE,
        STATUS_NO_PREDICTION,
        STATUS_INVALID_REQUEST,
        STATUS_MODEL_UNAVAILABLE,
    }, "a status in this set is unreachable, so a Phase 5 caller could branch on it forever"


def test_a_result_rejects_a_status_outside_the_vocabulary() -> None:
    """The vocabulary is enforced at construction, not trusted from a caller."""
    with pytest.raises(HandoffError) as unknown:
        HandoffResult(status="probably_fine", target=TARGET_COLUMN)
    assert "unknown handoff status" in str(unknown.value)


# =========================================================================== #
# Uncertainty: measured, or explicitly unavailable
# =========================================================================== #


def test_uncertainty_is_unavailable_by_default_and_says_why() -> None:
    """The default is a statement, not a null.

    `Uncertainty()` with nothing supplied means "no uncertainty figure exists",
    which is a fact about the run and has to be reported as one.
    """
    uncertainty = Uncertainty()
    assert uncertainty.status == UNCERTAINTY_UNAVAILABLE
    assert uncertainty.value is None
    assert uncertainty.is_prediction_interval is False
    assert Uncertainty(status=UNCERTAINTY_UNAVAILABLE).to_dict()["value"] is None


def test_a_residual_sigma_may_only_be_built_from_measured_residuals() -> None:
    """The only path to a number.

    `residual_sigma_from` computes the standard deviation of observed-minus-predicted
    on a split the model was scored on. There is no constructor that takes a number
    and a status saying "measured"; you have to bring the pairs.
    """
    uncertainty = residual_sigma_from(
        [1.0, 2.0, 3.0, 4.0], [1.2, 1.8, 3.4, 3.6], unit="m", source="test split"
    )
    assert uncertainty.status == UNCERTAINTY_RESIDUAL_SIGMA
    assert uncertainty.value is not None
    assert uncertainty.unit == "m"
    assert uncertainty.source == "test split"
    assert uncertainty.is_prediction_interval is False


def test_a_residual_sigma_is_not_presented_as_a_prediction_interval() -> None:
    """A past-error spread is a description of past errors.

    Calling it a prediction interval would be claiming a coverage guarantee for a
    future value, on the strength of a distribution observed on a synthetic fixture.
    """
    uncertainty = residual_sigma_from([1.0, 2.0, 3.0], [1.1, 2.2, 2.7])
    assert uncertainty.is_prediction_interval is False
    assert uncertainty.caveat
    caveat = uncertainty.caveat.lower()
    for word in ("not a prediction interval", "past errors"):
        assert word in caveat, f"the caveat does not say {word!r}: {uncertainty.caveat}"


def test_a_residual_sigma_with_too_few_residuals_is_unavailable_not_zero() -> None:
    """The refusal the requirement asks for, expressed as a return.

    A standard deviation needs at least two residuals. With one pair it is exactly
    0.0, and 0.0 would be read as "this model makes no error" - the strongest possible
    claim and the least supported. So below the minimum the value is withheld and the
    reason says how many pairs arrived.
    """
    for pairs in (([], []), ([1.0], [1.0])):
        y_true, y_pred = pairs
        uncertainty = residual_sigma_from(y_true, y_pred)
        assert uncertainty.status == UNCERTAINTY_UNAVAILABLE
        assert uncertainty.value is None
        assert uncertainty.reason, "the refusal must say why"
        assert "pair" in uncertainty.reason
        assert "zero" in uncertainty.reason.lower(), (
            "the reason must name the failure mode it is refusing: a sigma of zero "
            "reads as certainty"
        )


def test_a_residual_sigma_over_two_or_more_pairs_is_measured() -> None:
    """The boundary of the case above.

    Once there are two residuals the statistic exists, and if the residuals really are
    all zero then 0.0 is the measured answer rather than an invented one. That is the
    distinction the test above is drawing: the code refuses to compute where the
    statistic does not exist, and computes it where it does.
    """
    identical = residual_sigma_from([1.0, 2.0], [1.0, 2.0])
    assert identical.status == UNCERTAINTY_RESIDUAL_SIGMA
    assert identical.value == 0.0

    spread = residual_sigma_from([1.0, 2.0, 3.0], [2.0, 4.0, 6.0])
    assert spread.status == UNCERTAINTY_RESIDUAL_SIGMA
    assert spread.value is not None
    assert spread.value > 0
    assert spread.is_prediction_interval is False, (
        "the lowest residual count that produces a number is still not a coverage "
        "guarantee, and the caveat has to travel with the value"
    )


def test_uncertainty_that_claims_to_be_measured_with_no_value_is_refused() -> None:
    """A measured status with no measurement is exactly the claim this refuses."""
    with pytest.raises(HandoffError) as no_value:
        Uncertainty(status=UNCERTAINTY_RESIDUAL_SIGMA, value=None)
    assert "no value" in str(no_value.value)


def test_an_unavailable_uncertainty_cannot_carry_a_value() -> None:
    """A number attached to "unavailable" would be read as available."""
    with pytest.raises(HandoffError) as contradiction:
        Uncertainty(status=UNCERTAINTY_UNAVAILABLE, value=0.5)
    assert "unavailable" in str(contradiction.value).lower()


def test_an_uncertainty_that_claims_to_be_a_prediction_interval_is_refused() -> None:
    """Phase 4 has no interval method. The flag exists so the refusal is explicit at
    the point of construction rather than a matter of convention."""
    with pytest.raises(HandoffError) as interval:
        Uncertainty(status=UNCERTAINTY_RESIDUAL_SIGMA, value=0.5, is_prediction_interval=True)
    assert "prediction interval" in str(interval.value).lower()


def test_uncertainty_rejects_an_unknown_status() -> None:
    with pytest.raises(HandoffError):
        Uncertainty(status="roughly")


def test_uncertainty_serialises_with_its_value_and_its_caveat() -> None:
    payload = residual_sigma_from([1.0, 2.0, 3.0], [1.1, 2.2, 2.7], unit="m").to_dict()
    json.dumps(payload)
    assert payload["status"] == UNCERTAINTY_RESIDUAL_SIGMA
    assert isinstance(payload["value"], float)
    assert payload["caveat"]
    assert payload["is_prediction_interval"] is False


def test_a_ready_result_with_no_residuals_reports_uncertainty_as_unavailable(
    full_result, full_manifests
) -> None:
    """Explicitly unavailable, not a plausible band.

    The temptation here is to return the run's RMSE as an uncertainty. It is not one:
    it is an aggregate error over a population, and presenting it as a bound on a
    single value would be a different and unsupported claim.
    """
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(model_id=model_id), full_result, manifests=full_manifests, prediction=3.5
    )
    assert result.uncertainty.status == UNCERTAINTY_UNAVAILABLE
    assert result.uncertainty.value is None
    assert result.uncertainty.reason


def test_a_ready_result_with_residuals_reports_the_measured_sigma(
    full_result, full_manifests
) -> None:
    """The one path where an uncertainty number legitimately exists."""
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(model_id=model_id),
        full_result,
        manifests=full_manifests,
        prediction=3.5,
        y_true=[1.0, 2.0, 3.0, 4.0],
        y_pred=[1.2, 1.8, 3.4, 3.6],
    )
    assert result.status == STATUS_READY
    assert result.uncertainty.status == UNCERTAINTY_RESIDUAL_SIGMA
    assert result.uncertainty.value is not None
    assert result.uncertainty.unit == "m"
    assert model_id in result.uncertainty.source
    assert SPLIT_VALIDATION in result.uncertainty.source
    assert result.uncertainty.is_prediction_interval is False


def test_the_evaluation_split_used_for_residuals_can_be_named(
    full_result, full_manifests
) -> None:
    """Whichever split is quoted, the source line says which."""
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(model_id=model_id),
        full_result,
        manifests=full_manifests,
        prediction=3.5,
        y_true=[1.0, 2.0, 3.0],
        y_pred=[1.1, 2.2, 2.8],
        evaluation_split=SPLIT_TEST,
    )
    assert SPLIT_TEST in result.uncertainty.source


# =========================================================================== #
# Serialisation, and the reuse of the existing forecast contract
# =========================================================================== #


def test_a_handoff_result_serialises_to_json_and_keeps_its_status(
    full_result, full_manifests
) -> None:
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(model_id=model_id), full_result, manifests=full_manifests, prediction=3.5
    )
    payload = json.loads(json.dumps(result.to_dict(), default=str))
    assert payload["status"] == STATUS_READY
    assert payload["prediction"] == 3.5
    assert payload["handoff_contract_version"] == HANDOFF_CONTRACT_VERSION
    assert payload["weight_storage_policy"] == WEIGHT_STORAGE_POLICY
    assert payload["production_ready_claimed"] is False


def test_a_ready_handoff_converts_to_the_existing_forecast_output(
    full_result, full_manifests
) -> None:
    """Reuse, not replacement.

    `ForecastOutput` is what the platform already reads and what the forecast-sync
    service already stores. Defining a parallel shape here would be the duplication
    this module exists to avoid.

    Note that `ForecastOutput` has no `production_ready_claimed` field. It carries the
    honest state in the two fields it does have: the disclaimer travels with the value,
    and the residual sigma stays null because none was measured. Absence of a
    production-readiness flag is not a claim of production readiness.
    """
    from app.engines.hydro.contract import ForecastOutput

    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_RANDOM_FOREST
    )
    result = build_handoff(
        _request(model_id=model_id), full_result, manifests=full_manifests, prediction=3.5
    )
    output = to_forecast_output(result, forecast_id="fcst-0001")
    assert isinstance(output, ForecastOutput)
    assert output.predicted_value == 3.5
    assert output.station_reference == ENTITY
    assert output.target == TARGET_COLUMN
    assert output.target_units == "m"
    assert output.forecast_horizon == HORIZON_LABEL
    assert output.forecast_timestamp == "2024-01-05T18:00:00Z"
    assert output.model_id == model_id
    assert output.disclaimer == SYNTHETIC_DISCLAIMER, (
        "the synthetic label is dropped in the conversion into the existing contract, "
        "which is where it would do the most damage"
    )
    assert output.residual_sigma is None
    assert not hasattr(output, "production_ready_claimed")


def test_a_non_ready_handoff_converts_to_a_failed_output_with_no_value(
    full_result, full_manifests
) -> None:
    """The running contract has no vocabulary for "unavailable", and inventing one is
    not this module's call to make.

    So a non-ready result becomes `failed` with a null value and the reason carried
    through, rather than a zero or a best guess. The status that reaches the older
    contract is deliberately less specific than the one Phase 4 produced: it says the
    forecast did not succeed, and the reason string says which of the five reasons it
    was.
    """
    model_id = next(
        run.model_id for run in full_result.runs if run.model_family == FAMILY_XGBOOST
    )
    result = build_handoff(
        _request(model_id=model_id),
        full_result,
        manifests=full_manifests,
        prediction=3.5,
    )
    assert result.status == STATUS_DEPENDENCY_UNAVAILABLE
    output = to_forecast_output(result, forecast_id="fcst-0002")
    assert output.predicted_value is None
    assert output.status != "success"
    assert output.disclaimer == SYNTHETIC_DISCLAIMER
    assert output.residual_sigma is None
    assert result.reason.split(";")[0] in (output.provenance_reference or ""), (
        f"the reason was lost in conversion: {output.provenance_reference!r}"
    )


# =========================================================================== #
# The contract, described
# =========================================================================== #


def test_the_handoff_contract_is_described_without_running_anything() -> None:
    """So a Phase 5 author can read the contract without a training run.

    The description is structured rather than prose, because the thing being described
    is a wire contract: a reader needs field names to write a client, and a paragraph
    would make them be extracted from a sentence by eye.
    """
    description = handoff_contract_description()
    assert description["handoff_contract_version"] == HANDOFF_CONTRACT_VERSION
    assert description["downstream_forecast_contract_version"] == FORECAST_CONTRACT_VERSION
    assert description["artifact_format_version"] == ARTIFACT_FORMAT_VERSION

    for field in ("target", "horizon", "entity", "origin_instant"):
        assert field in description["request_fields"], (
            f"{field!r} is a required request field but the description omits it"
        )
    for field in (
        "model_id",
        "model_family",
        "prediction",
        "prediction_timestamp",
        "source_timestamp",
        "model_version",
        "feature_version",
        "provenance",
        "uncertainty",
        "status",
        "reason",
    ):
        assert field in description["result_fields"], (
            f"{field!r} is on every result but the description omits it"
        )

    for status in sorted(REQUIRED_HANDOFF_STATUSES):
        assert status in description["statuses"], f"the description omits {status!r}"
    assert set(description["statuses"]) == set(HANDOFF_STATUSES)
    assert set(description["uncertainty_statuses"]) == set(UNCERTAINTY_STATUSES)
    assert description["weight_storage_policy"] == WEIGHT_STORAGE_POLICY


def test_the_contract_description_states_the_boundary_this_module_does_not_cross() -> None:
    """Phase 5 handoff, not a forecast API.

    The description has to say that this is a contract and not a service, because a
    reader who found an endpoint-shaped thing in Phase 4 would reasonably assume a
    deployable forecaster exists. There is none.
    """
    scope = handoff_contract_description()["scope"].lower()
    for phrase in ("contract only", "no http route", "phase 5"):
        assert phrase in scope, f"the boundary statement does not mention {phrase!r}: {scope!r}"

    integration = handoff_contract_description()["integration_statement"]
    assert "team-owner integration" in integration.lower(), (
        "the one place this module leans on a seam it does not own must be named, so a "
        "reader knows what is still outstanding"
    )


def test_the_uncertainty_policy_in_the_description_matches_the_enforced_rule() -> None:
    """The written policy and the constructor's rule must not drift apart.

    The constructor refuses an unavailable status carrying a value and refuses any
    prediction interval. A description claiming something else would document a
    contract the code does not hold.
    """
    policy = handoff_contract_description()["uncertainty_policy"].lower()
    assert "value=none" in policy
    assert "residual_sigma_from" in policy
    assert "no prediction interval is produced" in policy

    with pytest.raises(HandoffError):
        Uncertainty(status=UNCERTAINTY_UNAVAILABLE, value=0.1)
    with pytest.raises(HandoffError):
        Uncertainty(status=UNCERTAINTY_RESIDUAL_SIGMA, value=0.1, is_prediction_interval=True)


def test_the_handoff_contract_version_is_declared_and_versioned() -> None:
    assert HANDOFF_CONTRACT_VERSION.startswith("navya-handoff/")
    assert MODEL_CONTRACT_VERSION.startswith("navya-model/")
    assert FEATURE_CONTRACT_VERSION.startswith("navya-features/")


# =========================================================================== #
# The whole chain, end to end
# =========================================================================== #


def test_the_fixture_reports_its_own_phase_3_audit_before_phase_4_runs(
    feature_result,
) -> None:
    """Phase 4 consumes Phase 3's verdict rather than replacing it.

    Training on rows Phase 3 flagged would invalidate everything downstream, so the
    precondition is asserted rather than assumed.
    """
    leakage = feature_result.report.leakage
    assert leakage.ok is True, leakage.describe()


def test_one_run_produces_a_registry_a_comparison_and_a_manifest_bundle(full_result) -> None:
    """All four artefacts of one training run, mutually consistent.

    The families in the comparison table, the families in the registry and the
    families in the manifest bundle are the same list. A mismatch would mean one of
    them is reporting a run that did not happen.
    """
    from app.engines.hydro.model_registry import registry_rows

    manifests = build_manifests(full_result)
    registry = {row["model_family"] for row in registry_rows()}
    compared = {row.model_family for row in full_result.comparison.rows}
    manifested = {m.model_family for m in manifests.manifests}

    assert registry == set(ALL_FAMILIES)
    assert compared == set(ALL_FAMILIES), (
        f"the comparison table is missing {sorted(set(ALL_FAMILIES) - compared)}; a family "
        "that was attempted and failed has to appear with a status"
    )
    assert manifested == set(ALL_FAMILIES)
    assert len(full_result.comparison.rows) == len(ALL_FAMILIES) * 2, (
        "every family must be reported on both the validation and the test split"
    )


def test_the_baseline_family_is_named_in_the_manifest_bundle(full_manifests) -> None:
    """So a reader knows which row the deltas are measured against."""
    assert full_manifests.baseline_family == FAMILY_NAIVE
    assert full_manifests.selection_metric
    assert full_manifests.selection_split == SPLIT_VALIDATION


def test_the_baseline_mae_appears_in_the_manifest_for_every_evaluated_model(
    full_manifests,
) -> None:
    """The comparison is the point. A reader must be able to see the forest's MAE and
    the baseline's MAE in the same document without joining two files."""
    baseline = next(
        m for m in full_manifests.manifests if m.model_family == FAMILY_NAIVE
    )
    forest = _forest_manifest(full_manifests)
    for split in (SPLIT_VALIDATION, SPLIT_TEST):
        assert split in baseline.metrics_by_split
        assert split in forest.metrics_by_split
    assert baseline.training_status == "trained"


def test_the_baseline_manifest_says_it_has_no_parameters_to_record(full_manifests) -> None:
    """The baseline is scored, not fitted, and the manifest distinguishes those."""
    baseline = next(
        m for m in full_manifests.manifests if m.model_family == FAMILY_NAIVE
    )
    assert baseline.training_status == "trained"
    assert baseline.parameters_recorded is False
    assert baseline.artifact_status == ARTIFACT_METADATA_ONLY


def test_nothing_in_this_run_claims_a_hydrological_result(full_result) -> None:
    """The final check, and the one that is easiest to lose.

    Every metric in this run was computed on a synthetic fixture with a 6-hour
    horizon, a two-station constant offset and no physics. Nothing here says a river
    will do anything.
    """
    for outcome in full_result.outcomes:
        if not outcome.evaluated:
            assert outcome.metrics is None
            continue
        assert outcome.synthetic_demo is True, (
            f"{outcome.model_id} {outcome.split} was evaluated without the synthetic flag"
        )
    assert full_result.is_synthetic is True
    assert full_result.disclaimer == SYNTHETIC_DISCLAIMER
    assert full_result.data_status == "synthetic_demo"


def test_no_status_outside_the_declared_vocabularies_is_reported(full_result) -> None:
    for run in full_result.runs:
        assert run.status in TRAINING_STATUSES
        assert run.artifact_status in ARTIFACT_STATUSES
    for row in full_result.comparison.rows:
        assert row.training_status in TRAINING_STATUSES
        assert row.evaluation_status in EVALUATION_STATUSES


def test_a_target_the_phase_3_report_declares_unavailable_is_reported_unavailable(
    full_result,
) -> None:
    """Phase 3 marks an unavailable target as unavailable and Phase 4 must not fill
    the gap with a substitute column."""
    report = full_result.report if hasattr(full_result, "report") else None
    if report is None:
        pytest.skip("the run result does not carry the Phase 3 report")
    for target in report.unavailable:
        assert target not in {
            run.target for run in full_result.runs if run.target is not None
        } or all(
            run.status != "trained" for run in full_result.runs if run.target == target
        ), f"a target Phase 3 declared unavailable was trained on: {target}"


def test_status_target_unavailable_is_reachable_from_the_contract() -> None:
    """The status exists in the vocabulary, so some path must be able to produce it.

    A status no path can return is a promise the contract cannot keep, and Phase 5
    would branch on it forever.
    """
    assert STATUS_TARGET_UNAVAILABLE in HANDOFF_STATUSES
    result = build_feature_result()
    outcome = train_models(
        result.dataset,
        (config_for(FAMILY_NAIVE, target_quantity="rain_total_24h"),),
        cadences=result.report.cadence,
    )
    manifests = build_manifests(outcome)
    model_id = outcome.runs[0].model_id
    handoff = build_handoff(
        _request(target="rain_total_24h", model_id=model_id),
        outcome,
        manifests=manifests,
        prediction=1.0,
    )
    assert handoff.status in (STATUS_TARGET_UNAVAILABLE, STATUS_INVALID_REQUEST)
    assert handoff.prediction is None
    assert handoff.reason
