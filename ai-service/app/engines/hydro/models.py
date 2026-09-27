# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Model registry / strategy pattern for the hydro forecasting pipeline.

Only estimators that are **actually implemented and executable** are registered
here. There is deliberately no stub, placeholder or name-only entry:

Implemented and always available (pure NumPy, no third-party ML dependency):

* `linear` — ordinary least squares baseline.
* `ridge`  — L2-regularised least squares, the default.

Implemented and available when the optional dependency is importable:

* `random_forest`     — `sklearn.ensemble.RandomForestRegressor`
* `gradient_boosting` — `sklearn.ensemble.GradientBoostingRegressor`
* `xgboost`           — `xgboost.XGBRegressor`, only if that package exists

`registry_keys()` reports what this environment can actually run, and
`unavailable_models()` explains, per model, exactly which dependency is missing.
That distinction is what keeps the model-comparison report honest: a model that
was not executed is never listed among the compared candidates.

**Not implemented — documented as future work only:** LSTM, GRU and any
quantum / QML regressor. Their names are rejected by the registry with a clear
message rather than silently mapped onto a classical model. See
`01_Flood_Forecasting/Forecast_Implementation.md` §"Model roadmap".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np


class ModelError(ValueError):
    """Raised when a model cannot be resolved, built or fitted."""


class ModelUnavailableError(ModelError):
    """Raised when a registered model's optional dependency is not installed."""


@runtime_checkable
class HydroEstimator(Protocol):
    """Minimal estimator contract used by the pipeline and the artifact store."""

    key: str
    display_name: str
    algorithm: str

    def fit(self, x: np.ndarray, y: np.ndarray) -> "HydroEstimator": ...

    def predict(self, x: np.ndarray) -> np.ndarray: ...

    def state(self) -> dict[str, Any]:
        """JSON-serialisable description of the fitted parameters."""

    def to_parameter_dict(self) -> dict[str, Any]:
        """Serialisable parameters suitable for an artifact file."""

    @classmethod
    def from_parameter_dict(cls, payload: Mapping[str, Any]) -> "HydroEstimator": ...


# --------------------------------------------------------------------------- #
# Always-available NumPy estimators
# --------------------------------------------------------------------------- #


@dataclass
class LinearRegressionModel:
    """Ordinary least squares with an intercept, solved with `numpy.linalg.lstsq`.

    This is the honest baseline for the candidate comparison: if nothing beats
    it, the pipeline says so. A rank-deficient design is reported through
    `rank` so a caller can see that the feature set was collinear.
    """

    key: str = "linear"
    display_name: str = "Linear Regression (OLS baseline)"
    algorithm: str = "ordinary_least_squares"

    coefficients: np.ndarray | None = field(default=None, repr=False)
    intercept: float = 0.0
    rank: int | None = None
    n_features: int = 0

    def __post_init__(self) -> None:
        if self.coefficients is None:
            self.coefficients = np.zeros(0, dtype="float64")

    def _design(self, x: np.ndarray) -> np.ndarray:
        matrix = np.asarray(x, dtype="float64")
        if matrix.ndim == 1:
            matrix = matrix.reshape(-1, 1)
        if not np.isfinite(matrix).all():
            # A NaN feature would flow silently through the solve and come out
            # as a NaN "forecast", which is far worse than a refused fit: it
            # looks like a number on the wire. The pipeline fits a train-only
            # imputer before here, so reaching this means the caller bypassed it.
            raise ModelError(
                f"model {self.key!r} received non-finite feature values; fit the train-only "
                "imputer before fitting or predicting"
            )
        # `n_features` is 0 until the first `fit`, so the width check only applies
        # once the model has recorded a fitted width.
        if self.n_features and matrix.shape[1] != self.n_features:
            raise ModelError(
                f"model {self.key!r} was fitted on {self.n_features} feature(s) but received "
                f"{matrix.shape[1]}"
            )
        return matrix

    def fit(self, x: np.ndarray, y: np.ndarray) -> "LinearRegressionModel":
        matrix = self._design(x)
        target = np.asarray(y, dtype="float64").reshape(-1)
        if matrix.shape[0] != target.shape[0]:
            raise ModelError(
                f"X has {matrix.shape[0]} row(s) but y has {target.shape[0]}"
            )
        if matrix.shape[0] < 2:
            raise ModelError("at least 2 samples are required to fit a linear model")
        design = np.column_stack([np.ones(matrix.shape[0]), matrix])
        try:
            solution, _residuals, rank, _singular = np.linalg.lstsq(design, target, rcond=None)
        except np.linalg.LinAlgError as exc:
            raise ModelError(f"model {self.key!r} could not be solved: {exc}") from exc
        if rank < design.shape[1]:
            # A rank-deficient design has infinitely many exact solutions and
            # `lstsq` silently returns the minimum-norm one. Reporting that as
            # "the coefficients" would present an arbitrary pick as the fit, so
            # the model refuses and the caller chooses a regularised model such
            # as `ridge`, which is well defined for a singular matrix.
            raise ModelError(
                f"model {self.key!r} cannot be fitted: the design matrix has rank {rank} "
                f"but {design.shape[1]} column(s), so the coefficients are not uniquely "
                "determined. Remove a collinear feature or use a regularised model "
                "such as 'ridge'."
            )
        self.intercept = float(solution[0])
        self.coefficients = np.asarray(solution[1:], dtype="float64")
        self.rank = int(rank)
        self.n_features = matrix.shape[1]
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        if self.coefficients.size == 0:
            raise ModelError(f"model {self.key!r} is not fitted")
        matrix = self._design(x)
        return matrix @ self.coefficients + self.intercept

    def state(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "algorithm": self.algorithm,
            "intercept": self.intercept,
            "coefficients": [float(value) for value in self.coefficients],
            "rank": self.rank,
            "n_features": self.n_features,
        }

    def to_parameter_dict(self) -> dict[str, Any]:
        return self.state()

    @classmethod
    def from_parameter_dict(cls, payload: Mapping[str, Any]) -> "LinearRegressionModel":
        coefficients = np.asarray(payload.get("coefficients", []), dtype="float64")
        if coefficients.size == 0:
            # An artifact with no coefficients is corrupt, not a model. Refusing
            # here means the failure names the artifact, instead of surfacing
            # later as a confusing "not fitted" on the first prediction.
            raise ModelError(
                "linear model artifact carries no coefficients; it was never fitted or has "
                "been corrupted"
            )
        return cls(
            coefficients=coefficients,
            intercept=float(payload.get("intercept", 0.0)),
            rank=payload.get("rank"),
            n_features=int(payload.get("n_features", 0)),
        )


@dataclass
class RidgeRegressionModel:
    """L2-regularised least squares.

    The penalty is applied to the coefficients only; the intercept is left
    unpenalised, which is the standard formulation and keeps the model centred
    on the training mean.
    """

    alpha: float = 1.0
    key: str = "ridge"
    display_name: str = "Ridge Regression (L2 regularised)"
    algorithm: str = "ridge_regression_l2"

    coefficients: np.ndarray | None = field(default=None, repr=False)
    intercept: float = 0.0
    n_features: int = 0

    def __post_init__(self) -> None:
        if self.alpha < 0:
            raise ModelError(f"ridge alpha must be >= 0, got {self.alpha}")
        if self.coefficients is None:
            self.coefficients = np.zeros(0, dtype="float64")

    def _design(self, x: np.ndarray) -> np.ndarray:
        matrix = np.asarray(x, dtype="float64")
        if matrix.ndim == 1:
            matrix = matrix.reshape(-1, 1)
        if not np.isfinite(matrix).all():
            raise ModelError(
                f"model {self.key!r} received non-finite feature values; fit the train-only "
                "imputer before fitting or predicting"
            )
        # `n_features` is 0 until the first `fit`, so the width check only applies
        # once the model has recorded a fitted width.
        if self.n_features and matrix.shape[1] != self.n_features:
            raise ModelError(
                f"model {self.key!r} was fitted on {self.n_features} feature(s) but received "
                f"{matrix.shape[1]}"
            )
        return matrix

    def fit(self, x: np.ndarray, y: np.ndarray) -> "RidgeRegressionModel":
        matrix = self._design(x)
        target = np.asarray(y, dtype="float64").reshape(-1)
        if matrix.shape[0] != target.shape[0]:
            raise ModelError(f"X has {matrix.shape[0]} row(s) but y has {target.shape[0]}")
        if matrix.shape[0] < 2:
            raise ModelError("at least 2 samples are required to fit a ridge model")
        n_features = matrix.shape[1]
        self.n_features = n_features
        self.intercept = float(target.mean())
        centred = target - self.intercept
        gram = matrix.T @ matrix + self.alpha * np.eye(n_features, dtype="float64")
        try:
            self.coefficients = np.linalg.solve(gram, matrix.T @ centred)
        except np.linalg.LinAlgError as exc:
            # Reachable only with alpha == 0 on a singular Gram matrix. Ridge is
            # documented as the answer for collinear features, so a failure here
            # means the caller asked for the unregularised limit by mistake.
            raise ModelError(
                f"model {self.key!r} could not be solved (alpha={self.alpha!r}): {exc}. "
                "A positive alpha makes the normal equations invertible for a "
                "collinear design; alpha=0 does not."
            ) from exc
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        if self.coefficients.size == 0 and self.n_features == 0:
            raise ModelError(f"model {self.key!r} is not fitted")
        matrix = self._design(x)
        return matrix @ self.coefficients + self.intercept

    def state(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "algorithm": self.algorithm,
            "alpha": self.alpha,
            "intercept": self.intercept,
            "coefficients": [float(value) for value in self.coefficients],
            "n_features": self.n_features,
        }

    def to_parameter_dict(self) -> dict[str, Any]:
        return self.state()

    @classmethod
    def from_parameter_dict(cls, payload: Mapping[str, Any]) -> "RidgeRegressionModel":
        coefficients = np.asarray(payload.get("coefficients", []), dtype="float64")
        if coefficients.size == 0:
            raise ModelError(
                "ridge model artifact carries no coefficients; it was never fitted or has "
                "been corrupted"
            )
        return cls(
            alpha=float(payload.get("alpha", 1.0)),
            coefficients=coefficients,
            intercept=float(payload.get("intercept", 0.0)),
            n_features=int(payload.get("n_features", 0)),
        )


# --------------------------------------------------------------------------- #
# Optional scikit-learn estimators
# --------------------------------------------------------------------------- #


@dataclass
class SklearnEnsembleModel:
    """Adapter around a scikit-learn regressor.

    The dependency is imported inside `build()`, never at module import time, so
    the pipeline runs unchanged on an environment without scikit-learn.
    """

    key: str
    display_name: str
    algorithm: str
    import_path: str
    factory_kwargs: Mapping[str, Any] = field(default_factory=dict)
    estimator: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.estimator is not None and not hasattr(self.estimator, "predict"):
            raise ModelError(
                f"model {self.key!r} resolved to {type(self.estimator).__name__}, which is not a regressor"
            )

    def fit(self, x: np.ndarray, y: np.ndarray) -> "SklearnEnsembleModel":
        if self.estimator is None:
            raise ModelError(f"model {self.key!r} was not built; call build() first")
        matrix = np.asarray(x, dtype="float64")
        target = np.asarray(y, dtype="float64").reshape(-1)
        if matrix.shape[0] != target.shape[0]:
            raise ModelError(f"X has {matrix.shape[0]} row(s) but y has {target.shape[0]}")
        # scikit-learn regressors reject NaN; the pipeline guarantees the imputer
        # ran, but the check is kept so a caller bypassing it gets a clear error.
        if not np.isfinite(matrix).all():
            raise ModelError(
                f"model {self.key!r} received non-finite feature values; fit the train-only imputer first"
            )
        self.estimator.fit(matrix, target)
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        if self.estimator is None:
            raise ModelError(f"model {self.key!r} is not fitted")
        matrix = np.asarray(x, dtype="float64")
        if not np.isfinite(matrix).all():
            raise ModelError(
                f"model {self.key!r} received non-finite feature values; apply the fitted imputer first"
            )
        return np.asarray(self.estimator.predict(matrix), dtype="float64").reshape(-1)

    def state(self) -> dict[str, Any]:
        if self.estimator is None:
            return {"key": self.key, "display_name": self.display_name, "fitted": False}
        state: dict[str, Any] = {
            "key": self.key,
            "display_name": self.display_name,
            "algorithm": self.algorithm,
            "fitted": True,
            "estimator_class": type(self.estimator).__name__,
            "params": {k: _jsonable(v) for k, v in self.estimator.get_params().items()},
        }
        feature_importances = getattr(self.estimator, "feature_importances_", None)
        if feature_importances is not None:
            state["feature_importances"] = [float(v) for v in np.asarray(feature_importances).reshape(-1)]
        return state

    def to_parameter_dict(self) -> dict[str, Any]:
        if self.estimator is None:
            raise ModelError(f"model {self.key!r} is not fitted; nothing to serialise")
        import pickle  # local import: only needed when an artifact is written

        return {
            "key": self.key,
            "display_name": self.display_name,
            "algorithm": self.algorithm,
            "import_path": self.import_path,
            "factory_kwargs": {k: _jsonable(v) for k, v in self.factory_kwargs.items()},
            "pickled_estimator": pickle.dumps(self.estimator, protocol=5).hex(),
        }

    @classmethod
    def from_parameter_dict(cls, payload: Mapping[str, Any]) -> "SklearnEnsembleModel":
        import pickle  # local import: only needed when an artifact is read

        raw = payload.get("pickled_estimator")
        if not raw:
            raise ModelError(f"artifact for model {payload.get('key')!r} has no serialised estimator")
        estimator = pickle.loads(bytes.fromhex(raw))
        return cls(
            key=str(payload["key"]),
            display_name=str(payload.get("display_name", payload["key"])),
            algorithm=str(payload.get("algorithm", payload["key"])),
            import_path=str(payload.get("import_path", "")),
            factory_kwargs=dict(payload.get("factory_kwargs", {})),
            estimator=estimator,
        )


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def _import_symbol(import_path: str) -> Any:
    module_name, _, symbol = import_path.rpartition(".")
    if not module_name:
        raise ModelUnavailableError(f"invalid import path {import_path!r}")
    try:
        module = __import__(module_name, fromlist=[symbol])
    except ImportError as exc:
        raise ModelUnavailableError(str(exc)) from exc
    try:
        return getattr(module, symbol)
    except AttributeError as exc:
        raise ModelUnavailableError(
            f"{import_path!r} does not exist in {module_name!r}"
        ) from exc


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ModelCandidate:
    """A registry entry describing one candidate model."""

    key: str
    display_name: str
    builder: Callable[[Mapping[str, Any]], HydroEstimator]
    requires: tuple[str, ...] = ()
    notes: str = ""

    def available(self) -> bool:
        """True when every required third-party package is importable."""
        for import_path in self.requires:
            try:
                _import_symbol(import_path)
            except ModelUnavailableError:
                return False
        return True

    def missing_dependency(self) -> str | None:
        """Name of the first missing dependency, or `None` when available."""
        for import_path in self.requires:
            try:
                _import_symbol(import_path)
            except ModelUnavailableError:
                return import_path
        return None


def _build_linear(options: Mapping[str, Any]) -> HydroEstimator:
    return LinearRegressionModel()


def _build_ridge(options: Mapping[str, Any]) -> HydroEstimator:
    return RidgeRegressionModel(alpha=float(options.get("alpha", 1.0)))


def _build_sklearn(import_path: str, display_name: str, algorithm: str, key: str) -> Callable[[Mapping[str, Any]], HydroEstimator]:
    def builder(options: Mapping[str, Any]) -> HydroEstimator:
        factory = _import_symbol(import_path)
        kwargs = {k: v for k, v in dict(options).items()}
        kwargs.setdefault("random_state", 0)
        estimator = factory(**kwargs)
        return SklearnEnsembleModel(
            key=key,
            display_name=display_name,
            algorithm=algorithm,
            import_path=import_path,
            factory_kwargs=kwargs,
            estimator=estimator,
        )

    return builder


#: Every model this pipeline can actually execute. Keys are the values accepted
#: by `HYDRO_MODEL` and by `build_model`.
MODEL_CANDIDATES: tuple[ModelCandidate, ...] = (
    ModelCandidate(
        key="linear",
        display_name="Linear Regression (OLS baseline)",
        builder=_build_linear,
        notes="pure NumPy; the mandatory baseline every other candidate must beat",
    ),
    ModelCandidate(
        key="ridge",
        display_name="Ridge Regression (L2 regularised)",
        builder=_build_ridge,
        notes="pure NumPy; default model, regularised for correlated hydrological features",
    ),
    ModelCandidate(
        key="random_forest",
        display_name="Random Forest Regressor",
        builder=_build_sklearn(
            "sklearn.ensemble.RandomForestRegressor",
            "Random Forest Regressor",
            "random_forest_regression",
            "random_forest",
        ),
        requires=("sklearn.ensemble.RandomForestRegressor",),
        notes="optional; requires scikit-learn",
    ),
    ModelCandidate(
        key="gradient_boosting",
        display_name="Gradient Boosting Regressor",
        builder=_build_sklearn(
            "sklearn.ensemble.GradientBoostingRegressor",
            "Gradient Boosting Regressor",
            "gradient_boosted_trees",
            "gradient_boosting",
        ),
        requires=("sklearn.ensemble.GradientBoostingRegressor",),
        notes="optional; requires scikit-learn",
    ),
    ModelCandidate(
        key="xgboost",
        display_name="XGBoost Regressor",
        builder=_build_sklearn(
            "xgboost.XGBRegressor",
            "XGBoost Regressor",
            "xgboost_gradient_boosting",
            "xgboost",
        ),
        requires=("xgboost.XGBRegressor",),
        notes="optional; only usable where the xgboost package is installed",
    ),
)

#: Documented future work. Deliberately NOT in the registry — the registry only
#: contains executable models.
FUTURE_MODEL_ROADMAP: Mapping[str, str] = {
    "lstm": "Long Short-Term Memory recurrent network — not implemented; requires a deep-learning runtime",
    "gru": "Gated Recurrent Unit network — not implemented; requires a deep-learning runtime",
    "qml_regressor": "Quantum kernel / variational regressor — not implemented; no quantum regressor exists in this repository",
    "lstm_gru_hybrid": "Hybrid recurrent + static-feature architecture — not implemented",
}


def registry_keys(available_only: bool = True) -> tuple[str, ...]:
    """Keys the registry can resolve, optionally restricted to this environment."""
    if not available_only:
        return tuple(candidate.key for candidate in MODEL_CANDIDATES)
    return tuple(candidate.key for candidate in MODEL_CANDIDATES if candidate.available())


def candidate(key: str) -> ModelCandidate:
    """Look up a candidate by key, with a helpful error for unknown names."""
    for entry in MODEL_CANDIDATES:
        if entry.key == key:
            return entry
    known = ", ".join(registry_keys(available_only=False))
    raise ModelError(f"unknown model key {key!r}; registered keys are: {known}")


def build_model(key: str, options: Mapping[str, Any] | None = None) -> HydroEstimator:
    """Instantiate a model by registry key.

    Raises `ModelUnavailableError` naming the missing dependency when a
    candidate's optional package is not installed, and a distinct error for the
    documented-but-unimplemented deep-learning/quantum names.
    """
    if key in FUTURE_MODEL_ROADMAP:
        raise ModelUnavailableError(
            f"model {key!r} is documented as future work and is NOT implemented: "
            f"{FUTURE_MODEL_ROADMAP[key]}"
        )
    entry = candidate(key)
    missing = entry.missing_dependency()
    if missing is not None:
        raise ModelUnavailableError(
            f"model {entry.key!r} requires {missing!r}, which is not importable in this environment"
        )
    return entry.builder(dict(options or {}))


def unavailable_models() -> dict[str, str]:
    """Map of unavailable candidate key -> the dependency that is missing."""
    return {
        entry.key: entry.missing_dependency() or "unknown"
        for entry in MODEL_CANDIDATES
        if not entry.available()
    }


def describe_registry() -> str:
    """Human-readable registry listing with real availability for this env."""
    lines = ["Candidate models actually executable in this environment:"]
    for entry in MODEL_CANDIDATES:
        status = "available" if entry.available() else f"unavailable (missing {entry.missing_dependency()})"
        lines.append(f"  - {entry.key}: {entry.display_name} [{status}] {entry.notes}")
    lines.append("Documented future work, NOT implemented:")
    for key, description in FUTURE_MODEL_ROADMAP.items():
        lines.append(f"  - {key}: {description}")
    return "\n".join(lines)
