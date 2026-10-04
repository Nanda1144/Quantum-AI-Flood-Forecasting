# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 4 training: fit what can be fitted, and report what could not be.

This is the module where a model could most easily be made to lie. Fitting a
regressor is easy; deciding what to do when the dependency is missing, when there
are not enough rows, when the target does not exist, or when two models end up with
the same MAE is where honesty has to be built in rather than reviewed in.

The design answer is that every model ends in exactly one `TrainingStatus`, and
only one of those statuses can carry a metric.

* ``trained`` — fitted, and possibly scored.
* ``dependency_unavailable`` — the family needs a package this environment lacks;
  the blocker names the module.
* ``target_unavailable`` — Phase 3 never built the configured target. No
  substitution, ever.
* ``insufficient_data`` — not enough rows for the lookback, the horizon or the
  split, carrying `required` and `available` counts.
* ``failed_training`` — the estimator raised; the message is preserved verbatim.

**Training touches training rows only.** Every fit reads `ModelDataset.train`.
Validation is used for exactly two things — early stopping for families that
declare support for it, and scoring. Test is used only for scoring. The held-out
split is never passed to a fit or to an early-stopping callback, and the claim is
recorded in the run record itself rather than left to be inferred from the absence
of a call.

**The persistence baseline goes through the identical path.** It has no
parameters, so it is not "fitted", but it is split, target-bound, horizon-bound
and scored exactly like every other family — which is the only way "did this beat
doing nothing?" gets a real answer.

**Sequences are built after the splits exist.** `build_sequences` runs on a single
`SplitMatrix`, so a window cannot span two periods even in principle. This module
never stacks windows itself.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

import numpy as np

from .feature_pipeline import SPLIT_TEST, SPLIT_TRAIN, SPLIT_VALIDATION
from .model_audit import LeakageAudit, audit_leakage
from .model_config import (
    ARTIFACT_INCLUDE_PARAMETERS,
    FAMILY_GRU,
    FAMILY_LSTM,
    FAMILY_NAIVE,
    FAMILY_RANDOM_FOREST,
    FAMILY_XGBOOST,
    IMPUTE_MEDIAN,
    MODEL_CONTRACT_VERSION,
    SCALER_STANDARD,
    ModelConfig,
    ModelConfigError,
)
from .model_dataset import (
    CODE_IMPUTED,
    ModelDataError,
    ModelDataset,
    SequenceSet,
    assemble_dataset,
    build_sequences,
    resolve_step_seconds,
)
from .model_evaluation import (
    ComparisonTable,
    EvaluationOutcome,
    build_comparison,
    data_status,
    evaluate_predictions,
    unevaluated_outcome,
)
from .model_registry import (
    ARTIFACT_STATUS_METADATA,
    ARTIFACT_STATUS_NOT_WRITTEN,
    ARTIFACT_STATUS_WITH_PARAMETERS,
    EVALUATION_DONE,
    EVALUATION_INSUFFICIENT_ROWS,
    EVALUATION_NOT_RUN,
    MODEL_REGISTRY,
    STATUS_DEPENDENCY_UNAVAILABLE,
    STATUS_FAILED_TRAINING,
    STATUS_INSUFFICIENT_DATA,
    STATUS_TARGET_UNAVAILABLE,
    STATUS_TRAINED,
    ModelSpec,
    probe,
    spec_for,
)
from .models import ModelUnavailableError, SklearnEnsembleModel, build_model
from .provenance import ProvenanceRecord, software_environment, utc_now_iso

# --------------------------------------------------------------------------- #
# Codes
# --------------------------------------------------------------------------- #

TRAIN_PREFIX = "MODEL_TRAIN_"

CODE_TRAINED = TRAIN_PREFIX + "TRAINED"
CODE_TARGET_UNAVAILABLE = TRAIN_PREFIX + "TARGET_UNAVAILABLE"
CODE_INSUFFICIENT = TRAIN_PREFIX + "INSUFFICIENT_DATA"
CODE_TRAINING_FAILED = TRAIN_PREFIX + "FAILED"
CODE_SEQUENCE_READY = TRAIN_PREFIX + "SEQUENCE_WINDOWS_BUILT"
CODE_SEQUENCE_UNAVAILABLE = TRAIN_PREFIX + "SEQUENCE_WINDOWS_UNAVAILABLE"
CODE_VALIDATION_FOR_EARLY_STOPPING = TRAIN_PREFIX + "VALIDATION_USED_FOR_EARLY_STOPPING"
CODE_PRODUCTION_DECLINED = TRAIN_PREFIX + "PRODUCTION_READY_DECLINED"
CODE_SYNTHETIC_LABEL = TRAIN_PREFIX + "SYNTHETIC_EVALUATION_ONLY"
CODE_TEST_NOT_FITTED = TRAIN_PREFIX + "HELD_OUT_SPLIT_NEVER_FITTED_ON"

#: Splits in chronological order.
SPLIT_ORDER: tuple[str, ...] = (SPLIT_TRAIN, SPLIT_VALIDATION, SPLIT_TEST)

#: Splits that are scored. Training is deliberately absent: a score on the rows a
#: model was fitted on measures memorisation, and printing it beside a held-out
#: figure invites a reader to quote the wrong one.
SCORED_SPLITS: tuple[str, ...] = (SPLIT_VALIDATION, SPLIT_TEST)


class TrainingError(RuntimeError):
    """Raised when a training run cannot be completed at all."""


# --------------------------------------------------------------------------- #
# Insufficiency
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Insufficiency:
    """A structured refusal to fit, with the numbers behind it.

    `required` and `available` are the whole point. "Not enough data" without them
    is a shrug; a reader told the lookback needs 24 windows and 6 were available
    can decide whether to shorten the lookback, extend the record, or accept that
    this family does not apply to this dataset.
    """

    reason: str
    required: int
    available: int
    target: str | None = None
    horizon: str | None = None
    entity: str | None = None
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "required": self.required,
            "available": self.available,
            "target": self.target,
            "horizon": self.horizon,
            "entity": self.entity,
            "model": self.model,
        }

    def describe(self) -> str:
        scope = self.target or "(no target)"
        horizon = f" at horizon {self.horizon}" if self.horizon else ""
        return (
            f"{self.model or 'model'}: {self.reason} for {scope}{horizon}; "
            f"required {self.required}, available {self.available}"
        )


class InsufficientData(TrainingError):
    """Raised by `fit_family`; carries the `Insufficiency` that explains it."""

    def __init__(self, insufficiency: Insufficiency) -> None:
        super().__init__(insufficiency.describe())
        self.insufficiency = insufficiency


# --------------------------------------------------------------------------- #
# Estimators
# --------------------------------------------------------------------------- #


class Phase4Estimator:
    """The minimal estimator surface Phase 4 relies on.

    `models.HydroEstimator` already declares fit/predict/state, and the tree
    families use that protocol directly by returning `models.SklearnEnsembleModel`.
    This class exists for the two families it does not fit: the naive baseline,
    which has no parameters to learn, and the sequence networks, whose fitted state
    is a compiled Keras model plus a configuration rather than a JSON block.
    """

    def fit(self, x: np.ndarray, y: np.ndarray) -> "Phase4Estimator":  # pragma: no cover
        raise NotImplementedError

    def predict(self, x: np.ndarray) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError

    def state(self) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError


@dataclass
class NaivePersistenceEstimator(Phase4Estimator):
    """`prediction(t + h) = latest known target value`, carried forward.

    Described as unfitted rather than fitted, because there is nothing to learn and
    calling it "trained" would be a claim about something that did not happen.

    It is held **per split** rather than as one flat vector. The persistence pool is
    split-scoped by policy — `model_dataset.persistence_predictions` refuses to read
    a baseline value from another split — so a single vector would have to be either
    the wrong split's values or a mixture of all of them, and both would quietly
    change what the number in the comparison table means. `bind_split` is called
    before each prediction so the estimator answers for the split being scored.

    What it does carry is a provenance: the origin each value was valid from, so a
    reader can confirm the value a prediction was made from really was in the past.
    """

    key: str = FAMILY_NAIVE
    display_name: str = "Naive persistence"
    algorithm: str = "last_value_persistence"
    #: Split -> one prediction per evaluable row of that split, in split row order.
    values: Mapping[str, np.ndarray] = field(default_factory=dict)
    #: Split -> the instant each prediction was carried forward from.
    source_instants: Mapping[str, tuple[datetime, ...]] = field(default_factory=dict)
    bound_split: str | None = None

    def fit(self, x: np.ndarray, y: np.ndarray) -> "NaivePersistenceEstimator":
        return self

    def bind_split(self, split: str) -> "NaivePersistenceEstimator":
        if split not in self.values:
            raise TrainingError(
                f"the persistence baseline has no prediction block for {split!r}; blocks exist "
                f"for {sorted(self.values)}"
            )
        self.bound_split = split
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        matrix = np.asarray(x, dtype="float64")
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        if self.bound_split is None:
            raise TrainingError(
                "the persistence baseline must be bound to a split before predicting; without "
                "one there is no way to know which prediction block the rows came from"
            )
        values = self.values[self.bound_split]
        if matrix.shape[0] != values.size:
            raise TrainingError(
                f"the persistence baseline holds {values.size} prediction(s) for "
                f"{self.bound_split!r} but received {matrix.shape[0]} row(s); they must "
                "describe the same rows in the same order"
            )
        return values.copy()

    def state(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "algorithm": self.algorithm,
            "parameters": None,
            "parameters_note": (
                "the persistence baseline has no fitted parameters; its prediction for a row is "
                "the most recent target value read at or before that row's origin"
            ),
            "splits": {
                split: int(block.size) for split, block in sorted(self.values.items())
            },
        }


@dataclass
class XGBoostEstimator(SklearnEnsembleModel):
    """`models.SklearnEnsembleModel` plus the `eval_set` early-stopping path.

    The pre-Phase-1 adapter's `fit(x, y)` cannot pass an evaluation set, and
    xgboost's early stopping is driven by `eval_set`. Fitting without one would
    train to a fixed `n_estimators` and silently give up the one piece of the
    brief that says "early stopping where appropriate".

    The validation split is passed **explicitly**, as an `(X_valid, y_valid)`
    tuple. Letting xgboost carve its own random validation fraction out of the
    training rows would break chronological ordering inside the period that is
    supposed to be the most trustworthy one.
    """

    early_stopping_rounds: int | None = None
    best_iteration: int | None = None
    #: Recorded for the artifact: the step early stopping settled on, so a reader
    #: knows how many trees were actually used rather than how many were allowed.
    fitted_n_estimators: int | None = None

    def fit(  # type: ignore[override]
        self,
        x: np.ndarray,
        y: np.ndarray,
        *,
        validation_data: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> "XGBoostEstimator":
        if self.estimator is None:
            raise TrainingError(f"model {self.key!r} was not built; call build_model() first")
        matrix = np.asarray(x, dtype="float64")
        target = np.asarray(y, dtype="float64").reshape(-1)
        if matrix.shape[0] != target.shape[0]:
            raise TrainingError(
                f"X has {matrix.shape[0]} row(s) but y has {target.shape[0]}"
            )
        if not np.isfinite(matrix).all():
            raise TrainingError(
                f"model {self.key!r} received non-finite feature values; set impute_policy to "
                f"{IMPUTE_MEDIAN!r} so absences are replaced by training statistics"
            )
        kwargs: dict[str, Any] = {"verbose": False}
        if validation_data is not None and self.early_stopping_rounds:
            x_valid, y_valid = validation_data
            kwargs["eval_set"] = [(np.asarray(x_valid, dtype="float64"), np.asarray(y_valid, dtype="float64"))]
        self.estimator.fit(matrix, target, **kwargs)
        best = getattr(self.estimator, "best_iteration", None)
        self.best_iteration = int(best) if best is not None else None
        self.fitted_n_estimators = getattr(self.estimator, "n_estimators", None)
        return self

    def state(self) -> dict[str, Any]:
        base = super().state()
        base["early_stopping_rounds"] = self.early_stopping_rounds
        base["best_iteration"] = self.best_iteration
        base["early_stopping_note"] = (
            "the validation split was supplied explicitly as eval_set; no random validation "
            "fraction was carved out of the training rows"
        )
        return base


class SequenceEstimator(Phase4Estimator):
    """LSTM / GRU adapter. The network is built lazily, so this module imports
    without a deep-learning runtime.

    Nothing here fabricates a result when the runtime is absent: `train_models`
    checks `ModelSpec.missing_dependency()` first and reports
    `dependency_unavailable` without reaching this class. The class exists so the
    contract, the configuration validation and the window construction can be
    tested on a machine that cannot run the network at all.
    """

    def __init__(self, model_family: str, options: Mapping[str, Any], seed: int) -> None:
        self.model_family = model_family
        self.options = dict(options)
        self.seed = seed
        self.model: Any = None
        self.history: dict[str, Any] = {}
        self._fitted = False

    def _architecture(self, keras: Any, n_features: int) -> Any:
        units = int(self.options.get("units", 32))
        dropout = float(self.options.get("dropout", 0.0))
        recurrent = keras.layers.LSTM if self.model_family == FAMILY_LSTM else keras.layers.GRU
        model = keras.Sequential(
            [
                keras.layers.Input(shape=(None, n_features)),
                recurrent(units, dropout=dropout, return_sequences=False),
                keras.layers.Dense(1),
            ]
        )
        model.compile(
            optimizer=self.options.get("optimizer", "adam"),
            loss="mse",
            # Metric-free on purpose. The validation split is passed as
            # `validation_data` for early stopping; every reported metric is
            # computed by Phase 4 from predictions on a split the network never saw.
            metrics=[],
        )
        return model

    def build(self, n_features: int) -> "SequenceEstimator":
        try:
            import keras  # noqa: PLC0415 - optional dependency, imported on demand
        except Exception as exc:  # noqa: BLE001
            raise TrainingError(
                f"{self.model_family} needs a Keras runtime, which is not importable here "
                f"({type(exc).__name__}: {exc}); the dependency is team-owned and Phase 4 does "
                "not install it"
            ) from exc
        self.model = self._architecture(keras, n_features)
        return self

    def fit(
        self,
        x: np.ndarray,
        y: np.ndarray,
        *,
        validation_data: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> "SequenceEstimator":
        if self.model is None:
            raise TrainingError(
                "the sequence estimator was not built; call build(n_features) with a Keras "
                "runtime first"
            )
        self.model.fit(
            np.asarray(x, dtype="float32"),
            np.asarray(y, dtype="float32").reshape(-1),
            epochs=int(self.options.get("epochs", 50)),
            batch_size=int(self.options.get("batch_size", 32)),
            validation_data=validation_data,
            # `shuffle=False` keeps each epoch's batches in chronological order.
            # Shuffling inside the training split would not leak anything, but it
            # would make the loss curve unreadable and two seeded runs harder to
            # compare, for no benefit.
            shuffle=False,
            verbose=0,
        )
        self._fitted = True
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        if self.model is None or not self._fitted:
            raise TrainingError("the sequence estimator is not fitted")
        return np.asarray(
            self.model.predict(np.asarray(x, dtype="float32"), verbose=0), dtype="float64"
        ).reshape(-1)

    def state(self) -> dict[str, Any]:
        return {
            "key": self.model_family,
            "display_name": f"{self.model_family.upper()} sequence regressor",
            "algorithm": f"{self.model_family}_sequence_regression",
            "parameters": dict(sorted(self.options.items())),
            "dependencies": {"keras": "required; see model_registry.MODEL_REGISTRY"},
            "fitted": self._fitted,
            "weights_note": (
                "network weights are not serialised into the Phase 4 artifact manifest; "
                "see model_artifacts.WEIGHT_STORAGE_POLICY"
            ),
        }


def build_sequence_estimator(
    model_family: str, options: Mapping[str, Any], seed: int
) -> SequenceEstimator:
    return SequenceEstimator(model_family, options, seed)


# --------------------------------------------------------------------------- #
# One fitted model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FittedModel:
    """An estimator plus everything needed to reproduce the fit."""

    estimator: Any = field(repr=False)
    record: Mapping[str, Any] = field(default_factory=dict)
    feature_names: tuple[str, ...] = ()
    sequences: Mapping[str, SequenceSet] = field(default_factory=dict)

    def state(self) -> dict[str, Any]:
        state = self.estimator.state()
        state["feature_names"] = list(self.feature_names)
        state["feature_importances"] = _importances(self.estimator, self.feature_names)
        return state


def _importances(estimator: Any, feature_names: Sequence[str]) -> dict[str, float] | None:
    """Feature importances aligned to column names, when the estimator has them.

    The estimator is fitted on a NumPy matrix, so it never learns column names and
    its importance array is positional. Rather than report an anonymous list, the
    names are attached here — and an array whose length disagrees with the feature
    set returns `None` instead of being zipped onto the wrong labels.
    """
    values = getattr(estimator, "estimator", None)
    raw = getattr(values, "feature_importances_", None) if values is not None else None
    if raw is None:
        return None
    flat = np.asarray(raw, dtype="float64").reshape(-1)
    if flat.size != len(feature_names):
        return None
    return {name: float(value) for name, value in zip(feature_names, flat)}


# --------------------------------------------------------------------------- #
# Fitting
# --------------------------------------------------------------------------- #


def _hyperparameters(spec: ModelSpec, config: ModelConfig) -> dict[str, Any]:
    """Registry defaults, overridden by the configuration.

    The defaults are written out in `ModelSpec.default_training` rather than
    delegated to the library, so the value actually used can be stated on the run
    record. A default that lives only in scikit-learn's source is not a default
    this project can declare or reproduce.
    """
    merged = spec.default_training()
    merged.update(dict(config.training))
    return merged


def _legacy_key(model_family: str) -> str | None:
    """The `models.py` registry key for a Phase 4 family, when one exists."""
    return {
        FAMILY_NAIVE: None,
        FAMILY_RANDOM_FOREST: "random_forest",
        FAMILY_XGBOOST: "xgboost",
        FAMILY_LSTM: None,
        FAMILY_GRU: None,
    }.get(model_family)


def _supervised_rows(dataset: ModelDataset):
    """Training rows that actually carry a target.

    Phase 3 keeps warm-up and tail rows rather than deleting them, so the training
    split can hold rows with no label. Those rows cannot supervise anything, and
    handing them to an estimator as a label of `NaN` would produce `NaN`
    coefficients rather than an honest count.
    """
    train = dataset.train
    mask = np.isfinite(train.target)
    return mask


def _persistence_estimator(dataset: ModelDataset) -> NaivePersistenceEstimator:
    """The baseline, assembled once for every split at once.

    One block per split, each holding exactly the predictions for that split's
    `evaluable_mask` rows in split order — the same rows, and the same order, that
    every other model is scored on. That alignment is what turns the table into a
    comparison rather than five unrelated numbers printed next to each other.
    """
    blocks: dict[str, np.ndarray] = {}
    instants: dict[str, tuple[datetime, ...]] = {}
    for split in sorted(dataset.splits):
        part = dataset.splits[split]
        mask = part.evaluable_mask
        blocks[split] = np.asarray(part.persistence[mask], dtype="float64")
        instants[split] = tuple(
            instant for instant, keep in zip(part.origin_instants, mask) if keep
        )
    return NaivePersistenceEstimator(values=blocks, source_instants=instants)


def _seed_estimator(estimator: Any, legacy_key: str, options: Mapping[str, Any], seed: int) -> Any:
    """Rebuild `estimator` with `random_state=seed` when the factory accepts one.

    `models._build_sklearn` inserts `kwargs.setdefault("random_state", 0)`, so a
    forest built without an explicit seed was fitted with seed **0** while the run
    recorded, the model id and the provenance all said `seed20240917`. Nothing on the
    record was false about itself; the record and the model simply disagreed, which
    is worse, because a run that cannot be reproduced from its own record is not
    reproducible at all. Worse still, changing `random_seed` in the configuration
    changed every number describing the run and nothing about the run.

    A family whose estimator has no `random_state` - a linear model, a ridge - is
    left exactly as built. Rebuilding is attempted only when the parameter exists, so
    no family receives a keyword its factory does not accept.
    """
    inner = getattr(estimator, "estimator", None)
    params = getattr(inner, "get_params", None)
    if params is None:
        return estimator
    try:
        current = params()
    except Exception:  # noqa: BLE001 - a third-party get_params may raise
        return estimator
    if "random_state" not in current or current["random_state"] == seed:
        return estimator
    from .models import build_model as _build_model

    return _build_model(legacy_key, {**options, "random_state": seed})


def _effective_parameters(
    estimator: Any, options: Mapping[str, Any], seed: int
) -> dict[str, Any]:
    """The parameters the fitted estimator actually holds, for the run record.

    `_hyperparameters` states what was *requested*; a reader reproducing the run needs
    to know what was *used*, which includes the values scikit-learn fills in itself.
    Where the estimator exposes its parameters they are reported verbatim; where it
    does not - the persistence baseline has none - the requested options stand, with
    the seed added so the record still names the seed the run used.
    """
    inner = getattr(estimator, "estimator", None)
    params = getattr(inner, "get_params", None)
    if params is not None:
        try:
            effective = dict(params())
        except Exception:  # noqa: BLE001 - a third-party get_params may raise
            effective = {}
        if effective:
            effective.setdefault("random_state", seed)
            return dict(sorted(effective.items()))
    stated = dict(options)
    stated["random_state"] = seed
    return dict(sorted(stated.items()))


def fit_family(
    dataset: ModelDataset,
    config: ModelConfig,
    *,
    estimator: Any = None,
) -> FittedModel:
    """Fit one family on training rows only."""
    spec = spec_for(config.model_family)
    options = _hyperparameters(spec, config)
    if not dataset.feature_names:
        raise ModelDataError(
            "no declared feature has a finite value in the training split; there is nothing to "
            "fit on and Phase 4 will not synthesise a feature to make a fit possible"
        )
    train = dataset.train
    mask = _supervised_rows(dataset)
    supervised = int(np.count_nonzero(mask))
    required = max(config.min_train_rows, spec.minimum_train_rows)
    if supervised < required:
        raise InsufficientData(
            Insufficiency(
                reason="fewer supervised training rows than this family requires",
                required=required,
                available=supervised,
                target=dataset.binding.column,
                horizon=dataset.binding.horizon_label,
                model=config.model_family,
            )
        )

    seed_everything(config.random_seed)

    sequences: dict[str, SequenceSet] = {}
    step: float | None = None
    record: dict[str, Any] = {
        "model_family": config.model_family,
        "seed": config.random_seed,
        "seeded_components": ["random_state", "python.random", "numpy.random"],
        "hyperparameters": dict(sorted(options.items())),
        "train_rows": train.rows,
        "train_supervised_rows": supervised,
        "validation_rows": dataset.splits[SPLIT_VALIDATION].rows if SPLIT_VALIDATION in dataset.splits else None,
        "test_rows": dataset.splits[SPLIT_TEST].rows if SPLIT_TEST in dataset.splits else None,
        "environment": dict(sorted(spec.runtime_versions().items())),
        "feature_columns": len(dataset.feature_names),
        "sequence": None,
        "validation_data_for_early_stopping": False,
    }

    if config.is_sequence:
        step = resolve_step_seconds(dataset.cadences, dataset.entities, dataset.binding.quantity)
        for split in (SPLIT_TRAIN, SPLIT_VALIDATION):
            if split not in dataset.splits:
                continue
            sequences[split] = build_sequences(dataset.splits[split], config.lookback, step)
        record["sequence"] = {split: block.to_dict() for split, block in sorted(sequences.items())}
        windows = sequences.get(SPLIT_TRAIN)
        available = windows.samples if windows is not None else 0
        if available < required:
            raise InsufficientData(
                Insufficiency(
                    reason=(
                        "not enough complete causal lookback windows for this family"
                        + (
                            "; the sampling step was never established, so the window's length "
                            "in time is unknown"
                            if step is None
                            else ""
                        )
                    ),
                    required=required,
                    available=available,
                    target=dataset.binding.column,
                    horizon=dataset.binding.horizon_label,
                    model=config.model_family,
                )
            )
        validation = sequences.get(SPLIT_VALIDATION)
        if validation is not None and validation.samples:
            record["validation_data_for_early_stopping"] = True

    if config.model_family == FAMILY_NAIVE:
        estimator = estimator or _persistence_estimator(dataset)
        estimator.fit(train.values[mask], train.target[mask])
        record["fitted"] = False
        record["fitted_note"] = (
            "the persistence baseline has no parameters to learn; it is scored, not fitted"
        )
        record["training_rows"] = int(np.count_nonzero(mask))
        record["predictions_per_split"] = {
            split: int(block.size) for split, block in sorted(estimator.values.items())
        }
        return FittedModel(
            estimator=estimator,
            record=record,
            feature_names=dataset.feature_names,
            sequences=sequences,
        )

    if config.is_sequence:
        windows = sequences[SPLIT_TRAIN]
        estimator = estimator or build_sequence_estimator(
            config.model_family, options, config.random_seed
        )
        estimator.build(len(dataset.feature_names))
        validation = sequences.get(SPLIT_VALIDATION)
        validation_data = (
            (validation.windows, validation.targets)
            if validation is not None and validation.samples
            else None
        )
        estimator.fit(windows.windows, windows.targets, validation_data=validation_data)
        record["fitted"] = True
        record["training_rows"] = windows.samples
        return FittedModel(
            estimator=estimator,
            record=record,
            feature_names=dataset.feature_names,
            sequences=sequences,
        )

    legacy_key = _legacy_key(config.model_family)
    if legacy_key is None:
        raise TrainingError(f"there is no adapter for model family {config.model_family!r}")
    legacy = build_model(legacy_key, options)
    legacy = _seed_estimator(legacy, legacy_key, options, config.random_seed)
    record["hyperparameters"] = _effective_parameters(legacy, options, config.random_seed)
    if config.model_family == FAMILY_XGBOOST:
        estimator = XGBoostEstimator(
            key=legacy.key,
            display_name=legacy.display_name,
            algorithm=legacy.algorithm,
            import_path=legacy.import_path,
            factory_kwargs=legacy.factory_kwargs,
            estimator=legacy.estimator,
            early_stopping_rounds=int(options.get("early_stopping_rounds", 0) or 0) or None,
        )
        validation = None
        if config.scaler_policy and SPLIT_VALIDATION in dataset.splits:
            part = dataset.splits[SPLIT_VALIDATION]
            usable = np.isfinite(part.target)
            if int(np.count_nonzero(usable)) >= 2:
                validation = (part.values[usable], part.target[usable])
        estimator.fit(
            train.values[mask],
            train.target[mask],
            validation_data=validation,
        )
        record["fitted"] = True
        record["training_rows"] = supervised
        record["early_stopping_rounds"] = estimator.early_stopping_rounds
        record["best_iteration"] = estimator.best_iteration
        record["validation_data_for_early_stopping"] = validation is not None
        return FittedModel(
            estimator=estimator,
            record=record,
            feature_names=dataset.feature_names,
            sequences=sequences,
        )

    if not np.isfinite(train.values[mask]).all():
        raise TrainingError(
            f"model {config.model_family!r} cannot be fitted: the training matrix holds "
            "non-finite values. Set impute_policy='median' so absences are replaced by "
            "training statistics, or 'none' and accept that this family cannot be fitted."
        )
    estimator = legacy
    estimator.fit(train.values[mask], train.target[mask])
    record["fitted"] = True
    record["training_rows"] = supervised
    return FittedModel(
        estimator=estimator,
        record=record,
        feature_names=dataset.feature_names,
        sequences=sequences,
    )


# --------------------------------------------------------------------------- #
# Run records
# --------------------------------------------------------------------------- #


def model_id_for(config: ModelConfig, binding: Any) -> str:
    """A deterministic identifier: family, target, horizon, seed.

    Deterministic on purpose. An identifier containing a timestamp, a row count or
    a random component would make two identical runs produce two different names,
    which defeats the point of naming an artifact at all.
    """
    horizon = binding.horizon_label or config.horizon_labels[0]
    return f"{config.model_family}-{binding.column}-{horizon}-seed{config.random_seed}"


def _model_version(config: ModelConfig, dataset: ModelDataset) -> str:
    """A version string that changes when the model or its inputs change."""
    return (
        f"{config.model_family}/{MODEL_CONTRACT_VERSION}/{dataset.feature_contract_version}"
        f"/seed{config.random_seed}"
    )


@dataclass(frozen=True)
class ModelRun:
    """One model's outcome, whether or not it produced anything.

    Every field a reader needs to decide whether to trust the run, and no field
    that would be a claim rather than a fact. `production_ready_claimed` is
    permanently `False`, and it is present so the declined claim travels with the
    record instead of being left to be inferred from an absent field.
    """

    model_id: str
    model_family: str
    role: str
    target: str
    target_units: str | None
    horizon: str | None
    status: str
    artifact_status: str
    evaluation_status: str
    reason: str | None
    data_status: str
    synthetic_demo: bool
    record: Mapping[str, Any] = field(default_factory=dict)
    insufficiency: Insufficiency | None = None
    provenance: ProvenanceRecord | None = None
    feature_names: tuple[str, ...] = ()
    production_ready_claimed: bool = False
    #: The fitted estimator. Excluded from equality and from `to_dict`; an
    #: estimator is not a fact about the run, it is the run's output.
    estimator: Any = field(default=None, repr=False, compare=False)

    @property
    def trained(self) -> bool:
        return self.status == STATUS_TRAINED

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model_id": self.model_id,
            "model_family": self.model_family,
            "role": self.role,
            "target": self.target,
            "target_units": self.target_units,
            "horizon": self.horizon,
            "status": self.status,
            "artifact_status": self.artifact_status,
            "evaluation_status": self.evaluation_status,
            "reason": self.reason,
            "data_status": self.data_status,
            "synthetic_demo": self.synthetic_demo,
            "record": _jsonable(self.record),
            "insufficiency": self.insufficiency.to_dict() if self.insufficiency else None,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "feature_columns": len(self.feature_names),
            "production_ready_claimed": self.production_ready_claimed,
        }
        return payload


@dataclass(frozen=True)
class RunResult:
    """Everything one `train_models` call produced."""

    runs: tuple[ModelRun, ...] = ()
    outcomes: tuple[EvaluationOutcome, ...] = ()
    comparison: ComparisonTable | None = None
    datasets: Mapping[str, ModelDataset] = field(default_factory=dict)
    audit: LeakageAudit | None = None
    sequences: Mapping[str, SequenceSet] = field(default_factory=dict)
    data_status: str = "unknown"
    is_synthetic: bool = True
    disclaimer: str | None = None
    scored_splits: tuple[str, ...] = ()
    selection_metric: str = "rmse"
    selection_split: str = SPLIT_VALIDATION
    baseline_family: str = FAMILY_NAIVE
    #: The dataset the audit ran over, kept so artifacts and reports can quote the
    #: exact rows and columns behind a number.
    primary_dataset: ModelDataset | None = None
    generated_at: str = field(default_factory=utc_now_iso)

    @property
    def trained(self) -> tuple[ModelRun, ...]:
        return tuple(run for run in self.runs if run.trained)

    def run_for(self, model_id: str) -> ModelRun:
        for run in self.runs:
            if run.model_id == model_id:
                return run
        raise KeyError(f"no model run {model_id!r}; runs: {[r.model_id for r in self.runs]}")

    def metrics_for(self, model_id: str, split: str) -> Mapping[str, float] | None:
        for outcome in self.outcomes:
            if outcome.model_id == model_id and outcome.split == split:
                return outcome.metrics
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs": [run.to_dict() for run in self.runs],
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
            "comparison": self.comparison.to_dict() if self.comparison else None,
            "audit": self.audit.to_dict() if self.audit else None,
            "data_status": self.data_status,
            "is_synthetic": self.is_synthetic,
            "disclaimer": self.disclaimer,
            "scored_splits": list(self.scored_splits),
            "selection_metric": self.selection_metric,
            "selection_split": self.selection_split,
            "baseline_family": self.baseline_family,
            "generated_at": self.generated_at,
        }

    def describe(self) -> str:
        lines = [
            "Phase 4 training run",
            f"  data status : {self.data_status}",
            f"  synthetic   : {self.is_synthetic}",
        ]
        if self.disclaimer:
            lines.append(f"  disclaimer  : {self.disclaimer}")
        lines.append("")
        for run in self.runs:
            lines.append(
                f"  {run.model_id:<52} {run.status:<22}"
                + (f"evaluation={run.evaluation_status}" if run.trained else (run.reason or ""))
            )
            if run.insufficiency is not None:
                lines.append(f"      {run.insufficiency.describe()}")
        if self.comparison is not None:
            lines.append("")
            lines.append(self.comparison.describe())
        for split, block in sorted(self.sequences.items()):
            if not block.samples:
                continue
            lines.append(
                f"  sequences[{split}]: {block.samples} window(s) of lookback "
                f"{block.lookback} x {len(block.feature_names)} feature(s), "
                f"step={block.step_seconds}s"
            )
        if self.audit is not None:
            lines.append("")
            lines.append(self.audit.describe())
        return "\n".join(lines)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return str(value)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def _dataset_cache_key(config: ModelConfig) -> tuple[Any, ...]:
    """Configurations that differ only in family share one assembled dataset.

    Two models compared against each other must see the same columns and the same
    fitted statistics, otherwise the comparison is between two different problems.
    Keying the cache on the data-shaping fields and not on the family is what
    enforces that.
    """
    return (
        config.target_quantity,
        config.horizon_hours,
        config.feature_selection,
        config.scaler_policy,
        config.impute_policy,
        config.persistence_source,
    )


def _runtime_environment(config: ModelConfig) -> dict[str, str]:
    """The dependency picture behind this run, in Phase 1's own shape.

    `provenance.software_environment` already records Python, NumPy, pandas and
    scikit-learn, and already writes `not installed` rather than guessing a
    version for a package it cannot import. Phase 4's optional families are added
    on top of that rather than beside it, so there is one environment record
    rather than two that could disagree.

    Packages that were asked for and are missing are named explicitly. An
    environment block that simply omits `xgboost` reads as "not relevant", and the
    honest reading is "requested, absent".
    """
    env = dict(software_environment())
    env["phase4_model_contract"] = MODEL_CONTRACT_VERSION
    env["random_seed"] = str(config.random_seed)
    for requirement in spec_for(config.model_family).requires:
        report = probe(requirement)
        key = f"dependency:{requirement.module}"
        if report.installed:
            env[key] = f"installed ({report.version})"
        else:
            env[key] = f"not installed - {report.blocked_reason}"
    return env


def _provenance_for(
    config: ModelConfig,
    dataset: ModelDataset,
    *,
    metrics: Mapping[str, float] | None,
) -> ProvenanceRecord:
    """Build the Phase 1 provenance record for one run.

    Reuses `provenance.ProvenanceRecord` rather than defining a fourth record type,
    so a reviewer reads one provenance shape whether a record came from Phase 1
    ingestion or Phase 4 training. Phase 4-specific facts — the seed, the contract
    versions, the policies — go in the run record next to it rather than being
    smuggled into fields that mean something else.

    `model_version` is derived from the configuration and the feature contract,
    never from a timestamp, so two identical runs produce identical records apart
    from `created_at`.
    """
    return ProvenanceRecord(
        dataset_reference=dataset.dataset_reference,
        dataset_type=dataset.dataset_type,
        dataset_license=dataset.dataset_license,
        dataset_checksum=dataset.dataset_checksum,
        sampling_interval=_sampling_interval_text(dataset),
        target=dataset.binding.column,
        target_units=dataset.binding.units,
        forecast_horizon=dataset.binding.horizon_label,
        station_reference=dataset.station_reference,
        feature_list=tuple(dataset.feature_names),
        split=dataset.bounds,
        model_name=config.model_family,
        model_version=_model_version(config, dataset),
        artifact_reference=None,
        software_environment=_runtime_environment(config),
        disclaimer=dataset.disclaimer,
        evaluation_metrics=dict(metrics) if metrics else None,
    )


def _sampling_interval_text(dataset: ModelDataset) -> str | None:
    """Phase 3's sampling interval, quoted rather than re-derived.

    Read from the cadence Phase 3 published. When several series disagree the
    joined text says so instead of picking one and calling it *the* interval.
    """
    cadences = dataset.cadences or {}
    seconds = {
        float(getattr(item, "seconds"))
        for item in cadences.values()
        if getattr(item, "seconds", None)
    }
    if not seconds:
        return None
    ordered = sorted(seconds)
    if len(ordered) == 1:
        return f"{int(ordered[0])}s"
    return ",".join(f"{int(value)}s" for value in ordered)


def _order_configs(configs: Sequence[ModelConfig]) -> tuple[ModelConfig, ...]:
    """Registry order, one configuration per family.

    The baseline leads so a truncated report still shows the yardstick. Two
    configurations for one family would make the comparison ambiguous, so the
    second is refused rather than silently dropped.
    """
    by_family: dict[str, ModelConfig] = {}
    for config in configs:
        if config.model_family in by_family:
            raise ModelConfigError(
                f"two configurations were given for model family {config.model_family!r}; a "
                "comparison needs one model per family, and a second one would make the "
                "table ambiguous about which is which"
            )
        by_family[config.model_family] = config
    ordered: list[ModelConfig] = []
    for spec in MODEL_REGISTRY:
        if spec.model_family in by_family:
            ordered.append(by_family.pop(spec.model_family))
    if by_family:
        raise ModelConfigError(
            f"unknown model families {sorted(by_family)}; known families are "
            f"{[spec.model_family for spec in MODEL_REGISTRY]}"
        )
    if not ordered:
        raise ModelConfigError("no model configurations were supplied")
    return tuple(ordered)


def _dataset_for_audit(
    cache: Mapping[tuple[Any, ...], ModelDataset]
) -> ModelDataset | None:
    """The assembled dataset with the most rows, or `None` if none assembled.

    When every configuration failed to assemble there is nothing to audit, and the
    audit stays `None` rather than reporting an all-clear over nothing.
    """
    usable = [item for item in cache.values() if item.splits and item.feature_names]
    if not usable:
        return None
    return max(usable, key=lambda item: item.total_rows)


def _sequence_blocks(
    dataset: ModelDataset, config: ModelConfig, splits: Sequence[str]
) -> dict[str, SequenceSet]:
    """Causal windows for `splits`, restricted to each split's evaluable rows.

    The restriction matters. Without it a sequence family would be scored on every
    row that has a target while the persistence baseline is scored only on rows
    that also have a baseline prediction, and the two metrics would differ partly
    because they were measured on different rows. Restricting each window set to
    `evaluable_mask` makes the populations identical.
    """
    step = resolve_step_seconds(dataset.cadences, dataset.entities, dataset.binding.quantity)
    blocks: dict[str, SequenceSet] = {}
    for split in splits:
        if split not in dataset.splits:
            continue
        part = dataset.splits[split]
        mask = np.isfinite(part.target) if split == SPLIT_TRAIN else part.evaluable_mask
        blocks[split] = build_sequences(part, config.lookback, step, restrict=mask)
    return blocks


def _score_family(
    config: ModelConfig,
    dataset: ModelDataset,
    estimator: Any,
    model_id: str,
    split: str,
    sequences: Mapping[str, SequenceSet] | None,
) -> EvaluationOutcome:
    """Score one model on one split, or state why it could not be scored.

    Both prediction paths produce predictions for *exactly* the rows
    `SplitMatrix.evaluable_mask` selects, in split row order, so every model in a
    run is measured on the same observations.
    """
    part = dataset.splits[split]
    mask = part.evaluable_mask
    n_evaluable = int(np.count_nonzero(mask))

    def unavailable(status: str, reason: str) -> EvaluationOutcome:
        return unevaluated_outcome(
            model_id=model_id,
            model_family=config.model_family,
            target=dataset.binding.column,
            target_units=dataset.binding.units,
            horizon=dataset.binding.horizon_label,
            split=split,
            status=status,
            reason=reason,
            is_synthetic=dataset.is_synthetic,
            dataset_type=dataset.dataset_type,
        )

    if config.is_sequence:
        windows = (sequences or {}).get(split)
        if windows is None or windows.samples == 0:
            return unavailable(
                EVALUATION_NOT_RUN,
                f"no causal lookback window exists for {split} at lookback="
                f"{config.lookback}; a sequence model cannot be scored without one",
            )
        if windows.samples != n_evaluable:
            return unavailable(
                EVALUATION_NOT_RUN,
                f"{split} yields {windows.samples} window(s) against {n_evaluable} evaluable "
                "row(s); scoring those against each other would compare different populations, "
                "so the split was not scored",
            )
        predictions = estimator.predict(windows.windows)
        actual = windows.targets
    else:
        # The baseline holds one block per split and has to be told which one it is
        # answering for; everything else is stateless here.
        bind = getattr(estimator, "bind_split", None)
        if bind is not None:
            bind(split)
        predictions = estimator.predict(part.values[mask])
        actual = part.target[mask]

    return evaluate_predictions(
        model_id=model_id,
        model_family=config.model_family,
        target=dataset.binding.column,
        target_units=dataset.binding.units,
        horizon=dataset.binding.horizon_label,
        split=split,
        y_true=actual,
        y_pred=predictions,
        is_synthetic=dataset.is_synthetic,
        dataset_type=dataset.dataset_type,
        report=config.metrics,
    )


def _run_one(
    config: ModelConfig,
    dataset: ModelDataset,
    *,
    artifact_status: str | None,
    selection_split: str,
    scored_splits: Sequence[str],
) -> tuple[ModelRun, list[EvaluationOutcome], FittedModel | None]:
    """Train, score and record one family.

    The order of the gates is deliberate and identical for every family: the
    target has to exist, then the dependency has to be importable, then the rows
    have to be enough, and only then is anything fitted. Checking the cheap and
    unconditional gates first is what stops a missing package from being reported
    as a data problem, or an absent target as a missing dependency.
    """
    spec = spec_for(config.model_family)
    identifier = model_id_for(config, dataset.binding)
    status_label = data_status(dataset.is_synthetic, dataset.dataset_type)

    def finish(
        status: str,
        reason: str,
        *,
        record: Mapping[str, Any] | None = None,
        insufficiency: Insufficiency | None = None,
        estimator: Any = None,
        outcomes: Sequence[EvaluationOutcome] = (),
        evaluation_status: str = EVALUATION_NOT_RUN,
        fitted: FittedModel | None = None,
    ) -> tuple[ModelRun, list[EvaluationOutcome], FittedModel | None]:
        artifact = artifact_status
        if artifact is None:
            artifact = (
                ARTIFACT_STATUS_WITH_PARAMETERS
                if config.artifact_policy == ARTIFACT_INCLUDE_PARAMETERS
                else ARTIFACT_STATUS_METADATA
            )
        if status != STATUS_TRAINED:
            # A model that did not fit has no weights to store, and writing a
            # placeholder under the same name would invite someone to load it.
            artifact = ARTIFACT_STATUS_NOT_WRITTEN
        selection_metrics: Mapping[str, float] | None = None
        for outcome in outcomes:
            if outcome.split == selection_split and outcome.metrics:
                selection_metrics = outcome.metrics
                break
        run = ModelRun(
            model_id=identifier,
            model_family=config.model_family,
            role=spec.role,
            target=dataset.binding.column,
            target_units=dataset.binding.units,
            horizon=dataset.binding.horizon_label,
            status=status,
            artifact_status=artifact,
            evaluation_status=evaluation_status,
            reason=reason,
            data_status=status_label,
            synthetic_demo=dataset.is_synthetic,
            record=dict(record or {}),
            insufficiency=insufficiency,
            provenance=_provenance_for(config, dataset, metrics=selection_metrics),
            feature_names=dataset.feature_names,
            estimator=estimator,
        )
        return run, list(outcomes), fitted

    def gated(status: str, reason: str) -> list[EvaluationOutcome]:
        """One unevaluated outcome per scored split, for a model that never fit.

        A blocked model must still appear in the comparison table. *Absent* is not
        the same statement as *attempted and could not run*: a reader counting rows
        would otherwise conclude those families were never considered, and the table
        exists precisely to record what was tried. The training status travels on the
        run and the evaluation status here, so the row reads `dependency_unavailable`
        beside `not_evaluated` rather than being missing.
        """
        evaluation = (
            EVALUATION_INSUFFICIENT_ROWS
            if status == STATUS_INSUFFICIENT_DATA
            else EVALUATION_NOT_RUN
        )
        return [
            unevaluated_outcome(
                model_id=identifier,
                model_family=config.model_family,
                target=dataset.binding.column,
                target_units=dataset.binding.units,
                horizon=dataset.binding.horizon_label,
                split=split,
                status=evaluation,
                reason=reason,
                is_synthetic=dataset.is_synthetic,
                dataset_type=dataset.dataset_type,
            )
            for split in scored_splits
            if split in dataset.splits
        ]

    # --- gate 1: the target has to exist -----------------------------------
    if not dataset.binding.usable:
        reason = (
            dataset.binding.reason
            or "Phase 3 did not build a usable target for this configuration"
        )
        return finish(
            STATUS_TARGET_UNAVAILABLE,
            reason,
            outcomes=gated(STATUS_TARGET_UNAVAILABLE, reason),
        )

    # --- gate 2: then the dependency, before any data-shaped work ----------
    blocker = spec.blocker_text()
    if blocker is not None:
        return finish(
            STATUS_DEPENDENCY_UNAVAILABLE,
            blocker,
            outcomes=gated(STATUS_DEPENDENCY_UNAVAILABLE, blocker),
        )

    # --- gate 3: then the fit ----------------------------------------------
    try:
        fitted = fit_family(dataset, config)
    except InsufficientData as exc:
        return finish(
            STATUS_INSUFFICIENT_DATA,
            str(exc),
            insufficiency=exc.insufficiency,
            outcomes=gated(STATUS_INSUFFICIENT_DATA, str(exc)),
        )
    except ModelUnavailableError as exc:
        return finish(
            STATUS_DEPENDENCY_UNAVAILABLE,
            str(exc),
            outcomes=gated(STATUS_DEPENDENCY_UNAVAILABLE, str(exc)),
        )
    except ModelDataError as exc:
        return finish(
            STATUS_INSUFFICIENT_DATA,
            str(exc),
            outcomes=gated(STATUS_INSUFFICIENT_DATA, str(exc)),
        )
    except Exception as exc:  # noqa: BLE001 - an estimator may raise anything
        reason = f"{type(exc).__name__}: {exc}"
        return finish(
            STATUS_FAILED_TRAINING,
            reason,
            record={"exception_type": type(exc).__name__, "stage": "fit"},
            outcomes=gated(STATUS_FAILED_TRAINING, reason),
        )

    # --- scoring, split by split -------------------------------------------
    outcomes: list[EvaluationOutcome] = []
    any_scored = False
    # Declared before the loop, not inside it. Every split can take the
    # "not enough evaluable rows" branch below and `continue`, and a configuration
    # whose `min_eval_rows` exceeds every split's evaluable count is ordinary, not
    # exotic — a short series, or a series whose first hours lack a baseline. Binding
    # this name inside the loop left it unbound when that happened for *all* splits,
    # so the run raised `UnboundLocalError` instead of reporting the two statuses it
    # exists to report: `trained` with `evaluation_unavailable`.
    blocks: dict[str, SequenceSet] = {}
    for split in scored_splits:
        if split not in dataset.splits:
            continue
        part = dataset.splits[split]
        n_evaluable = int(np.count_nonzero(part.evaluable_mask))
        if n_evaluable < config.min_eval_rows:
            outcomes.append(
                unevaluated_outcome(
                    model_id=identifier,
                    model_family=config.model_family,
                    target=dataset.binding.column,
                    target_units=dataset.binding.units,
                    horizon=dataset.binding.horizon_label,
                    split=split,
                    status=EVALUATION_INSUFFICIENT_ROWS,
                    reason=(
                        f"{split} offers {n_evaluable} evaluable row(s) after excluding rows "
                        f"with no persistence baseline; {config.min_eval_rows} are required "
                        "to score anything, and no metric was invented for the remainder"
                    ),
                    is_synthetic=dataset.is_synthetic,
                    dataset_type=dataset.dataset_type,
                )
            )
            continue
        if config.is_sequence:
            blocks.update(_sequence_blocks(dataset, config, (split,)))
        try:
            outcome = _score_family(
                config, dataset, fitted.estimator, identifier, split, blocks
            )
        except Exception as exc:  # noqa: BLE001 - a prediction may raise anything
            outcome = unevaluated_outcome(
                model_id=identifier,
                model_family=config.model_family,
                target=dataset.binding.column,
                target_units=dataset.binding.units,
                horizon=dataset.binding.horizon_label,
                split=split,
                status=EVALUATION_NOT_RUN,
                reason=f"prediction failed on {split}: {type(exc).__name__}: {exc}",
                is_synthetic=dataset.is_synthetic,
                dataset_type=dataset.dataset_type,
            )
        if outcome.evaluated:
            any_scored = True
        outcomes.append(outcome)

    merged: dict[str, SequenceSet] = dict(fitted.sequences)
    for split in blocks:
        merged[split] = blocks[split]
    full = FittedModel(
        estimator=fitted.estimator,
        record=dict(fitted.record),
        feature_names=fitted.feature_names,
        sequences=merged,
    )
    return finish(
        STATUS_TRAINED,
        "",
        record=full.record,
        estimator=full.estimator,
        outcomes=outcomes,
        evaluation_status=EVALUATION_DONE if any_scored else EVALUATION_NOT_RUN,
        fitted=full,
    )


def _comparison_context_notes(dataset: ModelDataset) -> tuple[str, ...]:
    """The dataset notes that qualify every figure in the comparison table.

    Compactly. A reader looking at one row needs to know that (a) the scored
    population is smaller than the split, (b) some cells were imputed from training
    medians, and (c) some declared features contributed nothing — not to read
    twenty-four near-identical sentences saying (c) once per column. The per-feature
    detail stays in `ModelDataset.notes` and in the artifact manifest, where a
    reviewer can get it without it burying the table it qualifies.

    Nothing here contradicts `ModelDataset.notes`: the counts are computed from the
    same split matrices those notes were derived from.
    """
    notes: list[str] = []
    dropped = sorted(dataset.dropped_features)
    if dropped:
        notes.append(
            f"FEATURE SET: {len(dropped)} of {len(dataset.declared_feature_names)} declared "
            f"feature column(s) were dropped because no finite value exists for them in the "
            f"training split ({', '.join(dropped[:6])}"
            + (f", +{len(dropped) - 6} more" if len(dropped) > 6 else "")
            + "). Every model above saw the same "
            f"{len(dataset.feature_names)} column(s)."
        )
    imputed = sum(note.code == CODE_IMPUTED for note in dataset.notes)
    if imputed:
        message = next(note.message for note in dataset.notes if note.code == CODE_IMPUTED)
        notes.append(f"IMPUTATION: {message}")

    evaluable = {name: part.evaluable for name, part in sorted(dataset.splits.items())}
    total = {name: part.rows for name, part in sorted(dataset.splits.items())}
    if any(total[name] - evaluable[name] for name in total):
        detail = ", ".join(
            f"{name}: {evaluable[name]} of {total[name]}" for name in sorted(total)
        )
        notes.append(
            "SCORED POPULATION: every model above is scored on exactly the rows listed "
            f"here, so the figures are like-for-like ({detail}). Rows are removed only "
            "because no persistence baseline existed for them under policy "
            f"{dataset.config.persistence_source!r}."
        )
    return tuple(notes)


def train_models(
    source: Any,
    configs: Sequence[ModelConfig],
    *,
    cadences: Mapping[str, Any] | None = None,
    baseline_family: str = FAMILY_NAIVE,
    selection_metric: str = "rmse",
    selection_split: str = SPLIT_VALIDATION,
    artifact_status: str | None = None,
    scored_splits: Sequence[str] = SCORED_SPLITS,
) -> RunResult:
    """Train and score every configured family against one Phase 3 dataset.

    `configs` is a list rather than a single configuration because the comparison
    is the point: one target, one horizon, one split policy, several models. Each
    is executed independently and reports its own status, so one family's blocker
    cannot end the run or contaminate another's numbers.

    Nothing raises for a model that cannot run. `ModelConfigError` still
    propagates, because it means the caller built something inconsistent and
    swallowing it would hide a bug.
    """
    ordered = _order_configs(configs)
    cache: dict[tuple[Any, ...], ModelDataset] = {}
    datasets: dict[str, ModelDataset] = {}
    runs: list[ModelRun] = []
    outcomes: list[EvaluationOutcome] = []
    sequences: dict[str, SequenceSet] = {}

    for config in ordered:
        key = _dataset_cache_key(config)
        dataset = cache.get(key)
        if dataset is None:
            dataset = assemble_dataset(source, config, cadences=cadences)
            cache[key] = dataset
            # Keyed by target column rather than by configuration: one target is
            # one problem, and five families sharing it is the point.
            datasets.setdefault(dataset.binding.column, dataset)
        run, run_outcomes, fitted = _run_one(
            config,
            dataset,
            artifact_status=artifact_status,
            selection_split=selection_split,
            scored_splits=tuple(scored_splits),
        )
        if config.is_sequence:
            # Built here as well as inside `fit_family`, and deliberately so. Window
            # construction needs NumPy and the Phase 3 cadence, not a deep-learning
            # runtime, so the causality audit can inspect the windows of a family
            # whose *runtime* is missing. Auditing the sequence path only when
            # TensorFlow happens to be installed would mean the most safety-critical
            # check is the one that runs least often.
            #
            # Every split is built, not just the scored ones. The audit's claim is
            # "no window anywhere reaches forward or crosses an entity"; checking
            # only validation and test would leave the training windows — the
            # largest and the ones a fit actually consumes — unaudited.
            sequences.update(_sequence_blocks(dataset, config, tuple(dataset.splits)))
        runs.append(run)
        outcomes.extend(run_outcomes)
        if fitted is not None:
            sequences.update(fitted.sequences)

    primary = _dataset_for_audit(cache)
    if primary is None:
        raise TrainingError(
            "no dataset could be assembled from the Phase 3 output, so there is nothing to "
            "train or evaluate; inspect the Phase 3 result before running Phase 4"
        )

    statuses = {run.model_id: run.status for run in runs}
    reasons = {run.model_id: (run.reason or "") for run in runs}
    # The baseline is configured by *family* ("naive"), but the table joins on
    # model_id. Resolving it here is what makes `baseline_delta` a real number
    # rather than a column of `None` that reads like a missing measurement.
    baseline_id = baseline_family
    baseline_present = False
    for run in runs:
        if run.model_family == baseline_family:
            baseline_id = run.model_id
            baseline_present = True
            break
    if not baseline_present:
        reasons = dict(reasons)
        reasons[baseline_family] = (
            f"no configuration for baseline family {baseline_family!r} was supplied, so no "
            "delta against a persistence baseline can be stated for any model in this run"
        )
    comparison = build_comparison(
        outcomes,
        statuses,
        reasons,
        baseline_model_id=baseline_id,
        selection_metric=selection_metric,
        selection_split=selection_split,
        disclaimer=primary.disclaimer,
        context_notes=_comparison_context_notes(primary),
    )
    audit = audit_leakage(primary, sequences=sequences)

    return RunResult(
        runs=tuple(runs),
        outcomes=tuple(outcomes),
        comparison=comparison,
        datasets=datasets,
        audit=audit,
        sequences=dict(sequences),
        data_status=data_status(primary.is_synthetic, primary.dataset_type),
        is_synthetic=primary.is_synthetic,
        disclaimer=primary.disclaimer,
        scored_splits=tuple(scored_splits),
        selection_metric=selection_metric,
        selection_split=selection_split,
        baseline_family=baseline_family,
        primary_dataset=primary,
    )


def seed_everything(seed: int) -> None:
    """Seed Python's and NumPy's global generators, not just the estimator.

    A seed on `random_state` alone makes *this project's* code reproducible and
    nothing else; a library drawing from a global generator mid-fit would still
    vary between runs. Seeding both costs nothing and turns a repeated run into a
    test rather than an assumption.
    """
    random.seed(seed)
    np.random.seed(seed % (2**32))


def default_configurations(
    *,
    target_quantity: str = "water_level",
    horizon_hours: tuple[float, ...] = (6.0,),
    seed: int = 20240917,
    scaler_policy: str = SCALER_STANDARD,
) -> tuple[ModelConfig, ...]:
    """One configuration per registered family, in registry order.

    Convenience, not policy. Every value is the registry default, so a caller who
    wants a different lookback, seed or horizon changes it explicitly here or on
    the individual `ModelConfig`.
    """
    return tuple(
        ModelConfig(
            model_family=spec.model_family,
            target_quantity=target_quantity,
            horizon_hours=horizon_hours,
            random_seed=seed,
            scaler_policy=scaler_policy,
        )
        for spec in MODEL_REGISTRY
    )


__all__ = [
    "FittedModel",
    "Insufficiency",
    "InsufficientData",
    "ModelRun",
    "NaivePersistenceEstimator",
    "Phase4Estimator",
    "RunResult",
    "SequenceEstimator",
    "TrainingError",
    "XGBoostEstimator",
    "build_sequence_estimator",
    "default_configurations",
    "fit_family",
    "model_id_for",
    "seed_everything",
    "train_models",
]
