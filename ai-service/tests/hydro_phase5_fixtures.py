# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Shared fixtures for the Phase 5 serving tests.

Not a test module — a helper. Every Phase 5 test needs the same thing: one Phase 4
run's manifests turned into a validated `ArtifactStore`, the fitted estimators that
run produced, and one origin instant whose feature vector is causally sound. Those
are built once here so the individual test files read as claims rather than as
pipeline re-implementations.

**Everything here is synthetic/demo data.** Reused from `hydro_phase4_fixtures`,
including its station identities and its disclaimer, so a Phase 5 test cannot pass
against a differently-shaped dataset than a Phase 4 one. No test asserts a
hydrological result. What the tests assert is that the pipeline reports honestly
about the numbers it computed, refuses what it cannot support, and does not change
its answer between two identical calls.

**The target history is labelled at the observation instant, not the origin.**
This is the one detail most likely to be got wrong, and getting it wrong is
dangerous in a way that produces a plausible answer: a `ModelDataset` row at origin
`t` carries the target observed at `t + H`, so a history entry must be stamped at
`t + H` too. Stamping it at `t` would make the persistence baseline read the true
future value and call it a forecast — which is exactly the leak these fixtures exist
to make detectable. `target_history_until` builds it correctly so a test that
mislabels history has to do so deliberately.
"""

from __future__ import annotations

import datetime as dt
import inspect
from typing import Any, Mapping, Sequence

import numpy as np
import pytest

from app.engines.hydro.forecast_artifact import (
    ArtifactStore,
    ForecastArtifact,
    PreprocessingSpec,
)
from app.engines.hydro.forecast_inference import ForecastInput, TargetObservation
from app.engines.hydro.model_artifacts import build_manifests
from app.engines.hydro.model_handoff import ForecastRequest
from app.engines.hydro.model_training import train_models

from hydro_phase4_fixtures import (
    STATION_A,
    STATION_B,
    SYNTHETIC_DISCLAIMER,
    build_feature_result,
    configs_for,
)

#: The target this fixture set trains. Stated rather than derived, because a test
#: that asserts on it wants the literal a reader can check against the docs.
TARGET = "target_water_level_6h"
HORIZON = "6h"
HOURS = 6.0

#: The families trained here. `xgboost` is included on purpose: it is
#: dependency-blocked in this environment, and Phase 5's contract for a blocked
#: family is a testable behaviour rather than a comment.
FAMILIES: tuple[str, ...] = ("naive", "random_forest", "xgboost")


def build_run(families: Sequence[str] = FAMILIES, *, scaler_policy: str = "standard"):
    """One real Phase 4 training run, on the real Phase 3 synthetic dataset.

    Real rather than hand-built manifests, because the thing under test is what
    Phase 4 actually produces. A fabricated manifest would let a Phase 5 test pass
    while Phase 5 was incompatible with Phase 4 - which is precisely the seam this
    phase owns.
    """
    result = build_feature_result()
    trained = train_models(
        result.dataset,
        configs_for(*families, scaler_policy=scaler_policy),
        cadences=result.report.cadence,
    )
    return trained, build_manifests(trained)


def preprocessing_for(manifests, dataset) -> dict[str, PreprocessingSpec | None]:
    """The fitted scaler/imputer record for each non-baseline family.

    Keyed by model id because the fitted record lives on the `ModelDataset` in
    Phase 4 and does not travel in the manifest. The baseline gets `None` rather
    than a spec: it has no features to preprocess, and attaching one would make a
    test pass for the wrong reason.
    """
    spec = PreprocessingSpec(
        feature_names=tuple(dataset.feature_names),
        scaler=dataset.scaler_state,
        imputer=dataset.imputer_state,
    )
    return {
        manifest.model_id: (spec if manifest.model_family != "naive" else None)
        for manifest in manifests.manifests
    }


@pytest.fixture(scope="module")
def trained_run():
    """The `train_models` result. Carries the fitted estimators and the audit."""
    return build_run()[0]


@pytest.fixture(scope="module")
def manifests(trained_run):
    return build_manifests(trained_run)


@pytest.fixture(scope="module")
def model_dataset(trained_run):
    """The `ModelDataset` the run was fitted on, for reading raw feature rows."""
    return trained_run.datasets[TARGET]


@pytest.fixture(scope="module")
def store(manifests, model_dataset):
    return ArtifactStore.from_manifests(
        manifests, preprocessing_for=preprocessing_for(manifests, model_dataset)
    )


@pytest.fixture(scope="module")
def estimators(trained_run):
    """`model_id` -> fitted estimator, for the families that have one.

    The persistence baseline is deliberately absent, matching what is really on
    disk: its prediction rule needs no fitted parameters, so giving it an estimator
    would hide the property that makes it servable from a manifest alone.
    """
    return {
        run.model_id: run.estimator
        for run in trained_run.runs
        if run.estimator is not None
    }


# --------------------------------------------------------------------------- #
# Artifacts by name
# --------------------------------------------------------------------------- #


def model_id_for(family: str, trained_run=None) -> str:
    """The `model_id` Phase 4 assigned to `family` for this fixture's target.

    Built from the run rather than formatted from a template, so a Phase 4 change to
    id composition updates these tests instead of silently pointing at nothing.
    """
    if trained_run is None:
        trained_run = build_run()[0]
    for run in trained_run.runs:
        if run.model_family == family:
            return run.model_id
    raise AssertionError(f"the fixture run trained no {family!r} model")


def artifact_for(store: ArtifactStore, family: str) -> ForecastArtifact:
    for artifact in store.artifacts:
        if artifact.model_family == family:
            return artifact
    raise AssertionError(f"the store holds no {family!r} artifact")


# --------------------------------------------------------------------------- #
# Serving instants and feature vectors
# --------------------------------------------------------------------------- #


def serving_instant(model_dataset, entity: str = STATION_A) -> dt.datetime:
    """An origin late enough that real target history exists before it.

    The last *training* row is used deliberately. Serving from a validation or test
    row would mean serving from an instant whose target Phase 4 scored, which is a
    fine test of the arithmetic and a misleading test of the serving boundary; the
    last training row is the latest instant this pipeline is entitled to have seen.
    """
    split = model_dataset.splits["train"]
    for index in range(len(split.origin_instants) - 1, -1, -1):
        if split.row_entities[index] == entity and np.isfinite(split.target[index]):
            return split.origin_instants[index]
    raise AssertionError(f"no usable training row for {entity!r}")


def target_history_until(
    model_dataset, origin: dt.datetime, entity: str = STATION_A
) -> tuple[TargetObservation, ...]:
    """Every observed target for `entity` at or before `origin`.

    Entries are stamped at the instant the value was *observed* — origin plus the
    horizon — which is the instant a persistence baseline is allowed to read from.
    Observations after `origin` are excluded here rather than filtered at read time,
    so a test that wants to prove the leak is caught can pass them in deliberately.
    """
    history: list[TargetObservation] = []
    offset = dt.timedelta(hours=HOURS)
    for split in model_dataset.splits.values():
        for index, entity_at in enumerate(split.row_entities):
            value = split.target[index]
            if entity_at != entity or not np.isfinite(value):
                continue
            observed_at = split.origin_instants[index] + offset
            if observed_at <= origin:
                history.append(TargetObservation(instant=observed_at, value=float(value)))
    return tuple(sorted(history, key=lambda item: item.instant))


def feature_row_at(model_dataset, origin: dt.datetime, entity: str = STATION_A):
    """`(values, row_index, split_name)` for the feature vector at `origin`."""
    for name, split in model_dataset.splits.items():
        for index, entity_at in enumerate(split.row_entities):
            if entity_at == entity and split.origin_instants[index] == origin:
                return split.raw_values[index], index, name
    raise AssertionError(f"no feature row for {entity!r} at {origin.isoformat()}")


def serving_input(
    model_dataset,
    origin: dt.datetime,
    entity: str = STATION_A,
    *,
    include_history: bool = True,
    source_instant: dt.datetime | None = None,
) -> ForecastInput:
    """A causally sound `ForecastInput` for `origin`.

    `source_instant` overrides the instant each feature is claimed to have come
    from, which is how the leakage tests build a vector that *claims* to know the
    future. Default is `origin` itself, which is true: Phase 3 builds each row from
    readings at or before the row's instant.
    """
    values, _, _ = feature_row_at(model_dataset, origin, entity)
    names = tuple(model_dataset.feature_names)
    read_at = source_instant or origin
    return ForecastInput.from_sequence(
        entity=entity,
        origin_instant=origin,
        names=names,
        values=[float(value) for value in values],
        feature_instants=[read_at] * len(names),
        target_history=(
            target_history_until(model_dataset, origin, entity) if include_history else ()
        ),
    )


def request_for(
    origin: dt.datetime,
    *,
    entity: str = STATION_A,
    target: str = TARGET,
    horizon: str = HORIZON,
    model_id: str | None = None,
    model_family: str | None = None,
) -> ForecastRequest:
    """A `ForecastRequest`. `model_id` and `model_family` are Phase 4's two selectors.

    Passing both is refused by `ForecastRequest.build` itself, so the helper does not
    guard against it - the contract already does, and a second guard here would be a
    second place for the rule to live.
    """
    return ForecastRequest.build(
        target=target,
        horizon=horizon,
        entity=entity,
        origin_instant=origin,
        model_id=model_id,
        model_family=model_family,
    )


def family_request(origin: dt.datetime, family: str = "naive", **kwargs: Any) -> ForecastRequest:
    """A request that names a model *family* rather than a specific model.

    The deployment shape Phase 5 has to support: "serve the baseline" is answerable
    from a manifest on disk, while naming a `model_id` requires the caller to have
    read the index first.
    """
    return request_for(origin, model_family=family, **kwargs)


@pytest.fixture(scope="module")
def origin(model_dataset):
    return serving_instant(model_dataset)


@pytest.fixture(scope="module")
def forecast_request(origin):
    """The request. Named `forecast_request` because `request` is pytest's own."""
    return request_for(origin)


@pytest.fixture(scope="module")
def serving_feature_input(model_dataset, origin):
    return serving_input(model_dataset, origin)


@pytest.fixture(scope="module")
def artifact(store):
    return artifact_for(store, "random_forest")


@pytest.fixture(scope="module")
def baseline_artifact(store):
    return artifact_for(store, "naive")


# --------------------------------------------------------------------------- #
# Hand-built artifacts, for states a real run cannot produce here
# --------------------------------------------------------------------------- #


def manifest_payload(artifact: ForecastArtifact, **overrides: Any) -> dict[str, Any]:
    """A Phase 5 artifact payload shaped like a Phase 4 manifest on disk.

    Built from a real artifact so the shape is always the real one; `overrides` then
    produce the specific malformed or blocked variant a test needs. A test that
    hand-wrote the whole payload could pass while `load_artifact` had stopped
    matching what Phase 4 writes.
    """
    payload: dict[str, Any] = {
        "model_id": artifact.model_id,
        "model_family": artifact.model_family,
        "target": artifact.target,
        "target_units": artifact.target_units,
        "horizon": artifact.horizon,
        "training_status": artifact.training_status,
        "artifact_status": artifact.artifact_status,
        "model_contract_version": artifact.model_contract_version,
        "feature_contract_version": artifact.feature_contract_version,
        "feature_count": artifact.feature_count,
        "feature_names": list(artifact.feature_names),
        "feature_digest": artifact.feature_digest,
        "metrics_by_split": {
            split: dict(values) for split, values in artifact.metrics_by_split.items()
        },
        "evaluation_status_by_split": dict(artifact.evaluation_status_by_split),
        "hyperparameters": dict(artifact.hyperparameters),
        "dependency_versions": dict(artifact.dependency_versions),
        "random_seed": artifact.random_seed,
        "scaler_policy": artifact.scaler_policy,
        "impute_policy": artifact.impute_policy,
        "split_policy": artifact.split_policy,
        "split_bounds": dict(artifact.split_bounds),
        "row_counts": dict(artifact.row_counts),
        "data_status": artifact.data_status,
        "synthetic_demo": artifact.synthetic_demo,
        "disclaimer": artifact.disclaimer,
        "provenance": dict(artifact.provenance) if artifact.provenance else None,
        "weight_stored_in_repository": artifact.weight_stored_in_repository,
        "weight_reference": artifact.weight_reference,
        "production_ready_claimed": False,
        "state": artifact.state,
        "reason": artifact.reason,
        "created_at": artifact.created_at,
    }
    payload.update(overrides)
    return payload


def _refusal(label: str, touched: list[str]):
    """The replacement installed in place of a fit entry point.

    A closure rather than a shared function so the message can name *which* fit was
    reached. "Something tried to train" is a much harder failure to diagnose than
    "the scaler was re-fitted at serving time", and the person reading the failure is
    not the person who wrote the serving path.
    """

    def refuse(*args: Any, **kwargs: Any):
        touched.append(label)
        raise AssertionError(
            f"Phase 5 called {label} during inference. Serving must not fit anything: the "
            "scaler, the imputer and the model were all fitted on the training split during "
            "Phase 4, and re-fitting at serving time would compute statistics from whatever "
            "data this request happened to carry - so the forecast would depend on which "
            "other requests arrived, and the Phase 4 evaluation would have described a "
            "model that does not exist."
        )

    return refuse


class FittingGuard:
    """Makes every `fit` the pipeline could reach from serving raise.

    This is how "inference does not train" is tested rather than asserted in a
    docstring. It covers Phase 2's scaler and imputer, scikit-learn's regressors,
    and Phase 4's `model_training.fit_family` - so a serving path that quietly
    called any of them fails loudly instead of producing a number computed from
    data it just re-read.

    Classes are patched at the class and the training function at the module, so
    the guard holds however the pipeline chooses to arrive: `scaler.fit(...)`,
    `StandardScaler().fit(...)` and a freshly imported `fit_family(...)` are all
    covered by the same entry.

    Usage is a context manager, and `touched` is empty if nothing tried to fit.
    """

    def __init__(self, targets: Mapping[Any, str] | None = None) -> None:
        #: `{owner: label}`, where `owner` is a class whose `fit` is patched or a
        #: module whose `fit_family` is. Overridable so a test can narrow the guard
        #: to one route into training without re-implementing the mechanism.
        self._targets: dict[Any, str] = (
            dict(targets)
            if targets
            else {
                self._standard_scaler(): "StandardScaler.fit",
                self._train_fitted_imputer(): "TrainFittedImputer.fit",
                self._random_forest_regressor(): "RandomForestRegressor.fit",
                self._model_training(): "model_training.fit_family",
            }
        )
        self.touched: list[str] = []
        #: `(owner, attribute, original)` triples, restored in reverse on exit.
        self._saved: list[tuple[Any, str, Any]] = []

    # Resolved lazily so importing this helper does not require sklearn, keeping
    # the fixture module importable in an environment where the dependency is absent
    # - which is the situation it exists to describe.
    @staticmethod
    def _standard_scaler() -> type:  # pragma: no cover - trivial
        from app.engines.hydro.preprocessing import StandardScaler

        return StandardScaler

    @staticmethod
    def _train_fitted_imputer() -> type:  # pragma: no cover - trivial
        from app.engines.hydro.preprocessing import TrainFittedImputer

        return TrainFittedImputer

    @staticmethod
    def _random_forest_regressor() -> type:  # pragma: no cover - trivial
        from sklearn.ensemble import RandomForestRegressor

        return RandomForestRegressor

    @staticmethod
    def _model_training() -> Any:  # pragma: no cover - trivial
        from app.engines.hydro import model_training

        return model_training

    def __enter__(self) -> "FittingGuard":
        for owner, label in self._targets.items():
            # Dispatch on what the owner actually *is*, never on its name. A name
            # check keeps working right up until a module is renamed or imported
            # under an alias, and then guards the wrong attribute on the wrong
            # object - which here means a guard that reports a clean run while
            # training happens freely, which is the one outcome a test like this
            # exists to make impossible.
            attribute = "fit_family" if inspect.ismodule(owner) else "fit"
            self._guard(owner, attribute, label)
        return self

    def __exit__(self, *exc_info: Any) -> None:
        for owner, attribute, original in reversed(self._saved):
            setattr(owner, attribute, original)
        self._saved.clear()

    def _guard(self, owner: Any, attribute: str, label: str) -> None:
        """Replace `owner.attribute` with a refusal, remembering what was there.

        `getattr` rather than `__dict__.get` for two reasons: an inherited method is
        guarded too (`RandomForestRegressor` inherits `fit` from `BaseForest`), and a
        genuinely absent attribute fails *here*, loudly, instead of being created by
        the guard - which would make a call to something that does not exist look
        like a guarded one.
        """
        original = getattr(owner, attribute)
        self._saved.append((owner, attribute, original))
        setattr(owner, attribute, _refusal(label, self.touched))


def no_fitting(monkeypatch_targets: Mapping[Any, str] | None = None) -> FittingGuard:
    """A `FittingGuard` for `with no_fitting() as guard: ...`.

    `monkeypatch_targets` replaces the default set, for a test that wants to prove one
    specific route into training is closed.
    """
    return FittingGuard(monkeypatch_targets)


__all__ = [
    "FAMILIES",
    "HORIZON",
    "HOURS",
    "STATION_A",
    "STATION_B",
    "SYNTHETIC_DISCLAIMER",
    "TARGET",
    "FittingGuard",
    "artifact",
    "artifact_for",
    "baseline_artifact",
    "build_run",
    "estimators",
    "family_request",
    "feature_row_at",
    "forecast_request",
    "manifest_payload",
    "manifests",
    "model_dataset",
    "model_id_for",
    "no_fitting",
    "origin",
    "preprocessing_for",
    "request_for",
    "serving_feature_input",
    "serving_input",
    "serving_instant",
    "store",
    "target_history_until",
    "trained_run",
]