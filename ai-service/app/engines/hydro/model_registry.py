# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 4 model registry: what each family is, and what it needs to run.

This is a **declaration** registry, not an execution registry, and the difference
matters. `models.MODEL_CANDIDATES` already exists and already answers "what can
this interpreter import right now" for the pre-Phase-1 pandas pipeline. Phase 4
answers a different question: "what model families does this project recognise,
what does each one require, and is that requirement met here?"

So nothing here is fitted, imported at module scope, or resolved lazily behind a
flag. A `ModelSpec` is data. `dependency_status(spec)` is the one place that
touches `importlib`, it returns a *report* rather than raising, and the caller
decides what to do with the answer.

Three properties the registry is built to guarantee.

**A declared family is never reported as trained.** `availability` is computed,
recorded and carried into the comparison as `training_status`. A family whose
dependency is missing appears in the comparison with its blocker text, and never
with a metric.

**A dependency blocker is specific.** `DependencyReport.blocked_reason` names the
module, the version it would need and why the absence is not something Phase 4
worked around — in practice, because the shared dependency manifest is
team-owned and Phase 4 does not edit it. A generic "model not available" is how a
missing package becomes an unfalsifiable claim.

**Nothing here is production-ready.** The registry carries
`production_ready_claimed`, permanently `False`, on every run record. A family
becoming trainable says nothing about it being correct in a river basin, and a
field that is always `False` is visible in every artifact in a way that a missing
field is not.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Mapping

from .model_config import (
    ARTIFACT_METADATA_ONLY,
    FAMILY_GRU,
    FAMILY_LSTM,
    FAMILY_NAIVE,
    FAMILY_RANDOM_FOREST,
    FAMILY_XGBOOST,
    MODEL_FAMILIES,
    ROLE_BASELINE,
    ROLE_CLASSICAL_ML,
    ROLE_PRIMARY_CANDIDATE,
    ROLE_SEQUENCE,
)

#: How an estimator is obtained.
IMPLEMENTATION_NATIVE = "native"
IMPLEMENTATION_SCIKIT_LEARN = "scikit_learn"
IMPLEMENTATION_XGBOOST = "xgboost"
IMPLEMENTATION_KERAS = "keras"
IMPLEMENTATIONS: tuple[str, ...] = (
    IMPLEMENTATION_NATIVE,
    IMPLEMENTATION_SCIKIT_LEARN,
    IMPLEMENTATION_XGBOOST,
    IMPLEMENTATION_KERAS,
)

#: Training statuses. Every run ends in exactly one of these, and the comparison
#: table carries the status next to the metrics so a metric is never read without
#: the statement of what produced it.
STATUS_TRAINED = "trained"
STATUS_DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
#: Phase 3 never built the configured target. A distinct status from
#: `insufficient_data` because the remedy is different: there are plenty of rows,
#: they simply do not describe the quantity this configuration asked for, and no
#: substitution is permitted.
STATUS_TARGET_UNAVAILABLE = "target_unavailable"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_EVALUATION_UNAVAILABLE = "evaluation_unavailable"
STATUS_FAILED_TRAINING = "failed_training"
TRAINING_STATUSES: tuple[str, ...] = (
    STATUS_TRAINED,
    STATUS_DEPENDENCY_UNAVAILABLE,
    STATUS_TARGET_UNAVAILABLE,
    STATUS_INSUFFICIENT_DATA,
    STATUS_EVALUATION_UNAVAILABLE,
    STATUS_FAILED_TRAINING,
)

#: Evaluation statuses, one per evaluation split.
EVALUATION_DONE = "evaluated"
EVALUATION_NOT_RUN = "not_evaluated"
EVALUATION_INSUFFICIENT_ROWS = "insufficient_rows"
EVALUATION_FAILED = "failed"
EVALUATION_STATUSES: tuple[str, ...] = (
    EVALUATION_DONE,
    EVALUATION_NOT_RUN,
    EVALUATION_INSUFFICIENT_ROWS,
    EVALUATION_FAILED,
)

#: Artifact statuses.
ARTIFACT_STATUS_NOT_WRITTEN = "not_written"
ARTIFACT_STATUS_METADATA = "metadata_only"
ARTIFACT_STATUS_WITH_PARAMETERS = "metadata_and_parameters"
ARTIFACT_STATUSES: tuple[str, ...] = (
    ARTIFACT_STATUS_NOT_WRITTEN,
    ARTIFACT_STATUS_METADATA,
    ARTIFACT_STATUS_WITH_PARAMETERS,
)

#: The data-status vocabulary. `synthetic_demo` is the only value any run in this
#: repository can honestly reach today; see `datasets.NO_VERIFIED_DATASETS`.
DATA_STATUS_SYNTHETIC_DEMO = "synthetic_demo"
DATA_STATUS_MEASURED = "measured"
DATA_STATUS_UNKNOWN = "unknown"


# --------------------------------------------------------------------------- #
# Dependency probing
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DependencyRequirement:
    """One importable package a family needs.

    `module` is the package name a reader would recognise; `symbol` is the
    attribute that must exist, because a package can be installed and still be
    missing the specific API (an old xgboost has no `XGBRegressor`).
    """

    module: str
    symbol: str | None = None
    purpose: str = ""

    @property
    def import_path(self) -> str:
        return f"{self.module}.{self.symbol}" if self.symbol else self.module

    def to_dict(self) -> dict[str, Any]:
        return {"module": self.module, "symbol": self.symbol, "purpose": self.purpose}


@dataclass(frozen=True)
class DependencyReport:
    """The outcome of probing one requirement. Never raises; always explains."""

    requirement: DependencyRequirement
    installed: bool
    version: str | None = None
    #: Present only when `installed` is `False`. Names the module and the reason.
    blocked_reason: str | None = None

    @property
    def import_path(self) -> str:
        return self.requirement.import_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "import_path": self.import_path,
            "purpose": self.requirement.purpose,
            "installed": self.installed,
            "version": self.version,
            "blocked_reason": self.blocked_reason,
        }


def _resolve_dotted(path: str) -> tuple[Any, str, str | None]:
    """Resolve a dotted path to an object, importing submodules on the way.

    Plain `importlib.import_module(path)` is not enough, and the reason is worth
    recording: `import sklearn` does **not** make `sklearn.ensemble` reachable as
    an attribute. Until something has imported that submodule, `hasattr(sklearn,
    "ensemble")` is `False`, so the naive check would report scikit-learn as
    missing while the estimator sits there working.

    So the longest importable *module* prefix is imported and the remaining
    segments are then walked as attributes. That is the same thing a reader does
    when they write `from sklearn.ensemble import RandomForestRegressor`, and it
    is the reason `scikit-learn` correctly reports as available here.
    """
    parts = path.split(".")
    module: Any = None
    module_length = 0
    failures: list[str] = []
    for length in range(len(parts), 0, -1):
        candidate = ".".join(parts[:length])
        try:
            module = importlib.import_module(candidate)
        except Exception as exc:  # noqa: BLE001 - a broken install must be reportable
            failures.append(f"{candidate} -> {type(exc).__name__}")
            continue
        module_length = length
        break
    if module is None:
        return None, "", "; ".join(failures) or "no importable module prefix"
    value: Any = module
    for segment in parts[module_length:]:
        value = getattr(value, segment, None)
        if value is None:
            return None, "", f"{path!r} is not reachable from {parts[module_length - 1]!r}"
    # The top-level package is what carries a distribution version a reader would
    # recognise. `sklearn.ensemble.__version__` does not exist; `sklearn.__version__`
    # does, and reporting the latter is the only honest answer to "which version
    # of scikit-learn is this".
    return value, parts[0], None


def probe(requirement: DependencyRequirement) -> DependencyReport:
    """Try to resolve one requirement and report what happened.

    Deliberately imports nothing at module scope. A registry that failed to
    import because an optional package is absent would make the registry itself
    unavailable, which is the opposite of what a registry is for.
    """
    resolved, package, failure = _resolve_dotted(requirement.import_path)
    if failure is not None:
        return DependencyReport(
            requirement=requirement,
            installed=False,
            blocked_reason=(
                f"{requirement.import_path!r} is not importable in this environment "
                f"({failure}). Phase 4 does not install it and does not edit the "
                "team-owned dependency manifest; the required integration action is recorded "
                "in 01_Flood_Forecasting/TEAM_INTEGRATION_REQUIREMENTS.md"
            ),
        )
    try:
        version = str(getattr(importlib.import_module(package), "__version__", "unknown"))
    except Exception:  # noqa: BLE001 - resolution already succeeded, so this cannot
        version = "unknown"
    return DependencyReport(
        requirement=requirement,
        installed=True,
        version=version,
    )


def probe_all(requirements: tuple[DependencyRequirement, ...]) -> tuple[DependencyReport, ...]:
    return tuple(probe(requirement) for requirement in requirements)


# --------------------------------------------------------------------------- #
# Registry entries
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ModelSpec:
    """A machine-readable description of one model family.

    Everything a reviewer needs to judge whether the run was legitimate, and
    nothing that would require importing the dependency to read.
    """

    model_family: str
    display_name: str
    role: str
    implementation: str
    requires: tuple[DependencyRequirement, ...] = ()
    #: Hyperparameter names this family understands. An unknown name in a run's
    #: configuration is reported rather than ignored.
    tunable: tuple[str, ...] = ()
    supports_importances: bool = False
    supports_early_stopping: bool = False
    is_sequence: bool = False
    #: Rows this family needs in the training split before a fit is meaningful.
    minimum_train_rows: int = 2
    #: Smallest lookback this family will accept.
    minimum_lookback: int = 2
    #: Never `True`. Present so the declined claim is visible in every artifact.
    production_ready_claimed: bool = False
    notes: str = ""

    @property
    def requirements(self) -> tuple[str, ...]:
        return tuple(requirement.import_path for requirement in self.requires)

    def dependency_reports(self) -> tuple[DependencyReport, ...]:
        return probe_all(self.requires)

    def availability(self) -> tuple[DependencyReport, ...]:
        """Reports for every requirement; empty means the family always runs."""
        return self.dependency_reports()

    def missing_dependency(self) -> str | None:
        """The first requirement that is not met, or `None` when all are."""
        for report in self.dependency_reports():
            if not report.installed:
                return report.import_path
        return None

    def is_available(self) -> bool:
        return self.missing_dependency() is None

    def blocker_text(self) -> str | None:
        """A single sentence naming why this family cannot run here."""
        for report in self.dependency_reports():
            if not report.installed:
                return report.blocked_reason
        return None

    def runtime_versions(self) -> dict[str, str]:
        return {
            report.import_path: (report.version or "unknown")
            for report in self.dependency_reports()
            if report.installed
        }

    def default_training(self) -> dict[str, Any]:
        """Explicit hyperparameters, so nothing is implicit at the call site.

        Every value is a number a reviewer can disagree with. A default chosen
        by a library and recorded only in the library's own source is not a
        default this project can state.
        """
        defaults: dict[str, Any] = {
            FAMILY_NAIVE: {},
            FAMILY_RANDOM_FOREST: {
                "n_estimators": 200,
                "max_depth": None,
                "min_samples_leaf": 1,
                "max_features": 1.0,
                "n_jobs": 1,
                "bootstrap": True,
            },
            FAMILY_XGBOOST: {
                "objective": "reg:squarederror",
                "n_estimators": 200,
                "max_depth": 4,
                "learning_rate": 0.1,
                "subsample": 1.0,
                "colsample_bytree": 1.0,
                "min_child_weight": 1.0,
                "reg_lambda": 1.0,
                "tree_method": "hist",
                "n_jobs": 1,
                "early_stopping_rounds": 25,
            },
            FAMILY_LSTM: {
                "units": 32,
                "dropout": 0.0,
                "epochs": 50,
                "batch_size": 32,
                "learning_rate": 0.001,
                "optimizer": "adam",
            },
            FAMILY_GRU: {
                "units": 32,
                "dropout": 0.0,
                "epochs": 50,
                "batch_size": 32,
                "learning_rate": 0.001,
                "optimizer": "adam",
            },
        }
        return dict(defaults.get(self.model_family, {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_family": self.model_family,
            "display_name": self.display_name,
            "role": self.role,
            "implementation": self.implementation,
            "requires": [requirement.to_dict() for requirement in self.requires],
            "tunable": list(self.tunable),
            "supports_importances": self.supports_importances,
            "supports_early_stopping": self.supports_early_stopping,
            "is_sequence": self.is_sequence,
            "minimum_train_rows": self.minimum_train_rows,
            "minimum_lookback": self.minimum_lookback,
            "default_training": self.default_training(),
            "production_ready_claimed": self.production_ready_claimed,
            "notes": self.notes,
        }


#: The registry. Order is the comparison order, and it is fixed: the baseline
#: first, so no reader can mistake an unevaluated table for a ranking that
#: happened to exclude it.
MODEL_REGISTRY: tuple[ModelSpec, ...] = (
    ModelSpec(
        model_family=FAMILY_NAIVE,
        display_name="Naive persistence (latest known target value carried forward)",
        role=ROLE_BASELINE,
        implementation=IMPLEMENTATION_NATIVE,
        tunable=(),
        minimum_train_rows=1,
        minimum_lookback=1,
        notes=(
            "prediction(t + h) = the latest observed value of the target quantity at or "
            "before t. This is the minimum benchmark: without it, 'the model is good' has "
            "nothing to be good compared to."
        ),
    ),
    ModelSpec(
        model_family=FAMILY_RANDOM_FOREST,
        display_name="Random Forest Regressor",
        role=ROLE_CLASSICAL_ML,
        implementation=IMPLEMENTATION_SCIKIT_LEARN,
        requires=(
            DependencyRequirement(
                module="sklearn",
                symbol="ensemble.RandomForestRegressor",
                purpose="ensemble estimator",
            ),
        ),
        tunable=(
            "n_estimators",
            "max_depth",
            "min_samples_leaf",
            "max_features",
            "n_jobs",
            "bootstrap",
        ),
        supports_importances=True,
        minimum_train_rows=2,
        notes=(
            "A comparison model, not a champion claim. Bagging over decorrelated trees; "
            "reported with feature importances because the ordering is informative about "
            "the feature set, not about hydrological causality."
        ),
    ),
    ModelSpec(
        model_family=FAMILY_XGBOOST,
        display_name="XGBoost Regressor",
        role=ROLE_PRIMARY_CANDIDATE,
        implementation=IMPLEMENTATION_XGBOOST,
        requires=(
            DependencyRequirement(
                module="xgboost",
                symbol="XGBRegressor",
                purpose="gradient-boosted tree estimator",
            ),
        ),
        tunable=(
            "objective",
            "n_estimators",
            "max_depth",
            "learning_rate",
            "subsample",
            "colsample_bytree",
            "min_child_weight",
            "reg_lambda",
            "tree_method",
            "n_jobs",
            "early_stopping_rounds",
        ),
        supports_importances=True,
        supports_early_stopping=True,
        minimum_train_rows=2,
        notes=(
            "The primary classical candidate *when the dependency exists*. Early stopping "
            "is fed the validation split explicitly; a random validation fraction inside "
            "fit() would break temporal ordering."
        ),
    ),
    ModelSpec(
        model_family=FAMILY_LSTM,
        display_name="LSTM sequence regressor",
        role=ROLE_SEQUENCE,
        implementation=IMPLEMENTATION_KERAS,
        requires=(
            DependencyRequirement(
                module="keras",
                symbol="Sequential",
                purpose="deep-learning runtime hosting recurrent layers "
                "(tf.keras or standalone keras)",
            ),
        ),
        tunable=("units", "dropout", "epochs", "batch_size", "learning_rate", "optimizer"),
        is_sequence=True,
        minimum_train_rows=32,
        minimum_lookback=2,
        notes=(
            "Requires a deep-learning runtime and is therefore skipped with a named blocker "
            "rather than approximated. Input windows are built causally in "
            "`model_dataset.build_sequences`; this spec never builds one itself."
        ),
    ),
    ModelSpec(
        model_family=FAMILY_GRU,
        display_name="GRU sequence regressor",
        role=ROLE_SEQUENCE,
        implementation=IMPLEMENTATION_KERAS,
        requires=(
            DependencyRequirement(
                module="keras",
                symbol="Sequential",
                purpose="deep-learning runtime hosting recurrent layers "
                "(tf.keras or standalone keras)",
            ),
        ),
        tunable=("units", "dropout", "epochs", "batch_size", "learning_rate", "optimizer"),
        is_sequence=True,
        minimum_train_rows=32,
        minimum_lookback=2,
        notes=(
            "Same safeguards as LSTM: causal windows, entity isolation, training-only "
            "scaling, explicit chronological split. Fewer parameters than LSTM at equal "
            "width; no claim is made here about which is better on any dataset, because "
            "neither has been fitted on real hydrological data."
        ),
    ),
)


def spec_for(model_family: str) -> ModelSpec:
    """Look up one registry entry, with the known names in the error message."""
    for entry in MODEL_REGISTRY:
        if entry.model_family == model_family:
            return entry
    known = ", ".join(entry.model_family for entry in MODEL_REGISTRY)
    raise KeyError(f"no Phase 4 model family {model_family!r}; registered families are: {known}")


def registry_rows() -> tuple[dict[str, Any], ...]:
    """The machine-readable registry, one dict per family, in registry order.

    Availability is included because a registry that has to be combined with
    another document to answer "can this run here?" is not doing its job. The
    blocker text travels with it, so a report can state the reason rather than
    making the reader go and check.
    """
    rows: list[dict[str, Any]] = []
    for entry in MODEL_REGISTRY:
        reports = entry.dependency_reports()
        payload = entry.to_dict()
        payload["available_here"] = entry.is_available()
        payload["runtime_versions"] = entry.runtime_versions()
        payload["dependency_reports"] = [report.to_dict() for report in reports]
        payload["blocked_reason"] = entry.blocker_text()
        payload["default_artifact_policy"] = ARTIFACT_METADATA_ONLY
        payload["production_ready_claimed"] = False
        rows.append(payload)
    return tuple(rows)


def available_families() -> tuple[str, ...]:
    return tuple(entry.model_family for entry in MODEL_REGISTRY if entry.is_available())


def blocked_families() -> Mapping[str, str]:
    """Family -> the reason it cannot run here."""
    blocked: dict[str, str] = {}
    for entry in MODEL_REGISTRY:
        reason = entry.blocker_text()
        if reason is not None:
            blocked[entry.model_family] = reason
    return blocked


def validate_family_names(names: tuple[str, ...]) -> None:
    """Refuse an unknown family by name before any work is attempted."""
    unknown = [name for name in names if name not in MODEL_FAMILIES]
    if unknown:
        raise KeyError(
            f"unknown Phase 4 model family/families {unknown}; known families are {list(MODEL_FAMILIES)}"
        )


__all__ = [
    "ARTIFACT_STATUSES",
    "ARTIFACT_STATUS_METADATA",
    "ARTIFACT_STATUS_NOT_WRITTEN",
    "ARTIFACT_STATUS_WITH_PARAMETERS",
    "DATA_STATUS_MEASURED",
    "DATA_STATUS_SYNTHETIC_DEMO",
    "DATA_STATUS_UNKNOWN",
    "EVALUATION_DONE",
    "EVALUATION_FAILED",
    "EVALUATION_INSUFFICIENT_ROWS",
    "EVALUATION_NOT_RUN",
    "EVALUATION_STATUSES",
    "IMPLEMENTATION_KERAS",
    "IMPLEMENTATION_NATIVE",
    "IMPLEMENTATION_SCIKIT_LEARN",
    "IMPLEMENTATION_XGBOOST",
    "IMPLEMENTATIONS",
    "MODEL_REGISTRY",
    "STATUS_DEPENDENCY_UNAVAILABLE",
    "STATUS_EVALUATION_UNAVAILABLE",
    "STATUS_FAILED_TRAINING",
    "STATUS_INSUFFICIENT_DATA",
    "STATUS_TARGET_UNAVAILABLE",
    "STATUS_TRAINED",
    "TRAINING_STATUSES",
    "DependencyReport",
    "DependencyRequirement",
    "ModelSpec",
    "available_families",
    "blocked_families",
    "probe",
    "probe_all",
    "registry_rows",
    "spec_for",
    "validate_family_names",
]