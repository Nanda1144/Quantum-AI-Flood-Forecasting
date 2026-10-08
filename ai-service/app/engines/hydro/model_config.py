# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 4 configuration: every model-development policy in one place.

Phase 3 deliberately kept its configuration separate from its code because a
feature policy is a scientific decision. The same argument applies here, one
level up: which family to fit, which target to predict, which horizon, which
seed, which lookback and which scaler are all decisions a reviewer must be able
to read, compare and reject without reading the training loop.

Three rules govern what this module may contain.

**No invented targets or horizons.** `ModelConfig` does not accept a target
*column* name. It accepts a target **quantity** plus a set of horizon **hours**,
and derives the column names through Phase 3's own `target_name`. A horizon that
Phase 3 did not build cannot be spelled here, so Phase 4 cannot silently ask for
a target that was never produced. `model_training` then checks the derived names
against the dataset and reports `target_unavailable` when one is missing — never
substituting a different variable.

**No invented splits.** There is one split policy,
``phase3_chronological``, and it means "use the split label Phase 3 already put
on every row". No percentages live in Phase 4. A split fraction is a decision
about which instants belong to which period, and Phase 3 — which owns the
timeline, the grids and the gaps — already made it. Re-deriving it here would be
a second, silently divergent split.

**No unfalsifiable defaults.** Every field below has a value that is either a
conservative choice or an explicit opt-in away from it, and each carries the
reason in the docstring where the reason is not obvious from the name.

The module is pure standard library. Asking "what did this run assume?" must not
require importing scikit-learn, and nothing here imports it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from .feature_registry import TARGET_PREFIX, target_name, window_label

#: The Phase 4 contract identifier. Travels on every run record and artifact so a
#: consumer can tell which shape it is holding without reading this file.
MODEL_CONTRACT_VERSION = "navya-model/v1"

#: Prefix for every warning/note code Phase 4 emits. Keeps Phase 4 notes
#: distinguishable from Phase 3's ``FEATURE_`` codes in one shared report.
CONFIG_PREFIX = "MODEL_"

#: Codes for the refusals this module makes. They are constants rather than
#: inline strings so a run report and a test can name the same refusal without
#: either side retyping it.
MODEL_CONFIG_NOTE_CODES: Mapping[str, str] = {
    CONFIG_PREFIX + "SEQUENCE_REQUIRES_LOOKBACK": (
        "a sequence family was configured without a usable lookback; the flat-feature "
        "families do not read this field"
    ),
    CONFIG_PREFIX + "HORIZON_NOT_BUILT": (
        "a configured horizon has no target column in the Phase 3 dataset; the run "
        "reports target_unavailable for it and never substitutes another variable"
    ),
    CONFIG_PREFIX + "SCALER_FIT_ON_TRAIN_ONLY": (
        "the scaler is fitted on training rows only; validation and test statistics "
        "never reach it"
    ),
}


class ModelConfigError(ValueError):
    """Raised when a Phase 4 configuration cannot be honoured."""


# --------------------------------------------------------------------------- #
# Model families
# --------------------------------------------------------------------------- #

#: The trivial benchmark every other model is measured against.
FAMILY_NAIVE = "naive"
#: Classical tree ensemble, available when scikit-learn is importable.
FAMILY_RANDOM_FOREST = "random_forest"
#: Gradient-boosted trees, available when xgboost is importable.
FAMILY_XGBOOST = "xgboost"
#: Recurrent sequence model, available when a deep-learning runtime exists.
FAMILY_LSTM = "lstm"
#: Recurrent sequence model, available when a deep-learning runtime exists.
FAMILY_GRU = "gru"

#: Every family Phase 4 knows how to name. Membership here is a statement about
#: the *registry*, never about what this environment can execute: availability is
#: probed separately in `model_registry` and reported per run.
MODEL_FAMILIES: tuple[str, ...] = (
    FAMILY_NAIVE,
    FAMILY_RANDOM_FOREST,
    FAMILY_XGBOOST,
    FAMILY_LSTM,
    FAMILY_GRU,
)

#: Families that consume a lookback window instead of one flat feature row.
SEQUENCE_FAMILIES: frozenset[str] = frozenset({FAMILY_LSTM, FAMILY_GRU})

#: Families implemented as tree ensembles over a flat feature row.
TREE_FAMILIES: frozenset[str] = frozenset({FAMILY_RANDOM_FOREST, FAMILY_XGBOOST})

#: The role each family plays in the comparison. Written down so a comparison
#: table can be read without knowing which family is "the important one" — the
#: point of the comparison is that no family is privileged.
ROLE_BASELINE = "baseline"
ROLE_CLASSICAL_ML = "classical_ml"
ROLE_PRIMARY_CANDIDATE = "primary_candidate"
ROLE_SEQUENCE = "sequence"


# --------------------------------------------------------------------------- #
# Scaling / imputation
# --------------------------------------------------------------------------- #

#: Pass the feature matrix through unchanged. Correct for tree ensembles, which
#: are invariant to monotone rescaling, and the honest default for them.
SCALER_NONE = "none"
#: Per-column standardisation fitted on training rows only.
SCALER_STANDARD = "standard"
SCALER_POLICIES: tuple[str, ...] = (SCALER_NONE, SCALER_STANDARD)

#: Leave absent feature cells absent. The model will refuse the fit, which is
#: the correct outcome when a caller has not decided what an absence means.
IMPUTE_NONE = "none"
#: Replace an absent cell with the **training** median of that column.
#:
#: Training-only is the whole point. A median computed over the whole dataset
#: would carry validation and test distribution information into the model's
#: inputs, and Phase 3 established that features are deliberately left absent
#: rather than filled — so the fill happens here, on one split, and is counted.
IMPUTE_MEDIAN = "median"
IMPUTE_POLICIES: tuple[str, ...] = (IMPUTE_NONE, IMPUTE_MEDIAN)


# --------------------------------------------------------------------------- #
# Feature selection
# --------------------------------------------------------------------------- #

#: Use every declared feature column, including columns that are absent for
#: every entity. Honest but usually useless: a column with no finite training
#: value cannot be standardised, so this policy requires an explicit decision
#: about what to do with it (see `IMPUTE_*`).
FEATURE_SELECTION_ALL = "all_declared"
#: Keep the columns that have at least one finite value in the **training**
#: split and report the rest by name and reason.
#:
#: The decision is made on training rows alone, so the column set cannot be
#: influenced by what validation or test happen to contain.
FEATURE_SELECTION_TRAIN_PRESENT = "train_present_only"
FEATURE_SELECTION_POLICIES: tuple[str, ...] = (
    FEATURE_SELECTION_ALL,
    FEATURE_SELECTION_TRAIN_PRESENT,
)


# --------------------------------------------------------------------------- #
# Split policy
# --------------------------------------------------------------------------- #

#: The only split policy. Phase 4 reads the split label Phase 3 attached to each
#: row; it does not re-slice the timeline and it does not accept a percentage.
SPLIT_POLICY_PHASE3 = "phase3_chronological"
SPLIT_POLICIES: tuple[str, ...] = (SPLIT_POLICY_PHASE3,)


# --------------------------------------------------------------------------- #
# Persistence-baseline source
# --------------------------------------------------------------------------- #

#: The persistence prediction for origin ``t`` may use only a target value whose
#: split is ``t``'s own split.
#:
#: This is the conservative default and it is deliberately so. The observation at
#: ``t`` is *also* the target of the row at ``t - horizon``, and for the first
#: ``horizon`` rows of a split that earlier row belongs to the previous split.
#: Using it would be causally defensible — everything involved is in the past —
#: but it is the kind of choice that needs to be a decision rather than a
#: default. With this policy those rows are instead removed from the evaluation
#: set **for every model**, so the comparison stays like-for-like.
PERSISTENCE_SOURCE_SAME_SPLIT = "same_split_only"
#: Allow the most recent target value from any earlier split, i.e. everything
#: available in the past at prediction time. Opt-in; documented in
#: `PHASE4_MODEL_TRAINING.md` §"Persistence baseline".
PERSISTENCE_SOURCE_ANY_PAST = "any_past_split"
PERSISTENCE_SOURCE_POLICIES: tuple[str, ...] = (
    PERSISTENCE_SOURCE_SAME_SPLIT,
    PERSISTENCE_SOURCE_ANY_PAST,
)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #

#: Metrics Phase 4 reports per model, target, horizon and split.
#:
#: `nse` and `peak_absolute_error` are computed by `evaluation.compute_metrics`
#: and are always available too; they are simply not in the default reporting
#: set. `mape` is deliberately absent and is not a default because it is not
#: defined for a target that crosses its datum — see
#: `model_evaluation.PERCENT_ERROR_UNAVAILABLE_REASON`.
DEFAULT_METRICS: tuple[str, ...] = ("mae", "rmse", "r2", "bias")

#: Every metric name `evaluation.compute_metrics` can produce. A configuration is
#: refused if it asks for anything outside this set.
#:
#: Declared here rather than imported from `model_evaluation` because that module
#: imports this one, and a cycle would make the vocabulary depend on import order.
#: `model_evaluation.REPORTABLE_METRICS` is this same tuple, so there is still only
#: one list.
#:
#: The check matters because it is *early*. `evaluate_predictions` also refuses an
#: uncomputed metric — but only after the model has been fitted and predictions
#: made, by which point an hour of compute has been spent discovering a typo.
COMPUTABLE_METRICS: tuple[str, ...] = (
    "mae",
    "rmse",
    "r2",
    "nse",
    "peak_absolute_error",
    "bias",
)


# --------------------------------------------------------------------------- #
# Artifact policy
# --------------------------------------------------------------------------- #

#: Write metadata, configuration, lineage, fingerprints and the evaluation
#: report. Never the weights. The default, because a generated model binary in
#: version control is unreviewable and enormous.
ARTIFACT_METADATA_ONLY = "metadata_only"
#: Additionally persist the estimator's serialisable parameters, which for a
#: tree ensemble still means pickle and is therefore still opt-in.
ARTIFACT_INCLUDE_PARAMETERS = "metadata_and_parameters"
ARTIFACT_POLICIES: tuple[str, ...] = (ARTIFACT_METADATA_ONLY, ARTIFACT_INCLUDE_PARAMETERS)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ModelConfig:
    """One model-development configuration.

    Immutable and fully explicit: two runs with equal configurations and equal
    inputs must be comparable, and a configuration that can change after the run
    starts is not comparable to anything.
    """

    model_family: str
    #: The Phase 1 measurement quantity to predict. Phase 3 owns which
    #: quantities have targets; a name here that Phase 3 never targeted is
    #: reported unavailable rather than approximated.
    target_quantity: str = "water_level"
    #: Forecast horizons in hours, in evaluation order. Must be a subset of the
    #: horizons Phase 3 built targets for.
    horizon_hours: tuple[float, ...] = (6.0,)
    #: Seed for every stochastic component. Fixed by default so a repeated run
    #: is a test rather than an assumption.
    random_seed: int = 20240917
    feature_selection: str = FEATURE_SELECTION_TRAIN_PRESENT
    scaler_policy: str = SCALER_NONE
    impute_policy: str = IMPUTE_MEDIAN
    split_policy: str = SPLIT_POLICY_PHASE3
    persistence_source: str = PERSISTENCE_SOURCE_SAME_SPLIT
    #: Number of consecutive same-entity rows a sequence model sees, ending at
    #: the prediction origin. Ignored by non-sequence families, and validated
    #: only for them.
    lookback: int = 24
    #: Rows below this in the training split stop the run with
    #: `insufficient_data` rather than fitting on nothing.
    min_train_rows: int = 2
    #: Rows below this in an evaluation split stop that split's scoring.
    min_eval_rows: int = 2
    metrics: tuple[str, ...] = DEFAULT_METRICS
    artifact_policy: str = ARTIFACT_METADATA_ONLY
    #: Family hyperparameters. Validated for finiteness so no silent NaN can make
    #: two runs incomparable.
    training: Mapping[str, Any] = field(default_factory=dict)
    #: Free-text label recorded on the run record.
    subject: str = "phase4_models"

    def __post_init__(self) -> None:
        if self.model_family not in MODEL_FAMILIES:
            raise ModelConfigError(
                f"unknown model family {self.model_family!r}; Phase 4 knows {list(MODEL_FAMILIES)}"
            )
        if not isinstance(self.target_quantity, str) or not self.target_quantity.strip():
            raise ModelConfigError("target_quantity must be a non-empty measurement quantity name")
        if self.target_quantity.startswith(TARGET_PREFIX):
            raise ModelConfigError(
                f"target_quantity {self.target_quantity!r} looks like a target column name; "
                f"give the measurement quantity instead (the {TARGET_PREFIX!r} prefix is reserved)"
            )
        horizons = tuple(float(hour) for hour in self.horizon_hours)
        if not horizons:
            raise ModelConfigError("horizon_hours must name at least one horizon")
        for hour in horizons:
            if not math.isfinite(hour) or hour <= 0.0:
                raise ModelConfigError(
                    f"horizon_hours entries must be positive finite hours; got {hour!r}. "
                    "A zero or negative horizon is a contemporaneous value, not a forecast."
                )
        object.__setattr__(self, "horizon_hours", horizons)
        if len(set(horizons)) != len(horizons):
            raise ModelConfigError(f"horizon_hours contains duplicates: {list(horizons)}")
        if self.feature_selection not in FEATURE_SELECTION_POLICIES:
            raise ModelConfigError(
                f"unknown feature_selection {self.feature_selection!r}; "
                f"known policies are {list(FEATURE_SELECTION_POLICIES)}"
            )
        if self.scaler_policy not in SCALER_POLICIES:
            raise ModelConfigError(
                f"unknown scaler_policy {self.scaler_policy!r}; known policies are {list(SCALER_POLICIES)}"
            )
        if self.impute_policy not in IMPUTE_POLICIES:
            raise ModelConfigError(
                f"unknown impute_policy {self.impute_policy!r}; known policies are {list(IMPUTE_POLICIES)}"
            )
        if self.split_policy not in SPLIT_POLICIES:
            raise ModelConfigError(
                f"unknown split_policy {self.split_policy!r}; Phase 4 does not define its own "
                f"split fractions; known policies are {list(SPLIT_POLICIES)}"
            )
        if self.persistence_source not in PERSISTENCE_SOURCE_POLICIES:
            raise ModelConfigError(
                f"unknown persistence_source {self.persistence_source!r}; "
                f"known policies are {list(PERSISTENCE_SOURCE_POLICIES)}"
            )
        if self.artifact_policy not in ARTIFACT_POLICIES:
            raise ModelConfigError(
                f"unknown artifact_policy {self.artifact_policy!r}; "
                f"known policies are {list(ARTIFACT_POLICIES)}"
            )
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int):
            raise ModelConfigError(f"random_seed must be an int; got {self.random_seed!r}")
        if self.is_sequence:
            if isinstance(self.lookback, bool) or not isinstance(self.lookback, int):
                raise ModelConfigError(f"lookback must be an int; got {self.lookback!r}")
            if self.lookback < 2:
                raise ModelConfigError(
                    f"a sequence model needs a lookback of at least 2 rows; got {self.lookback}. "
                    "A lookback of 1 is the flat-feature case and belongs to a tree family."
                )
        for name, bound in (("min_train_rows", self.min_train_rows), ("min_eval_rows", self.min_eval_rows)):
            if isinstance(bound, bool) or not isinstance(bound, int) or bound < 2:
                raise ModelConfigError(
                    f"{name} must be an int >= 2 so a fit and a score are both possible; got {bound!r}"
                )
        metrics = tuple(str(name).lower() for name in self.metrics)
        if not metrics:
            raise ModelConfigError("metrics must name at least one metric to report")
        if len(set(metrics)) != len(metrics):
            raise ModelConfigError(f"metrics contains duplicates: {list(metrics)}")
        uncomputed = [name for name in metrics if name not in COMPUTABLE_METRICS]
        if uncomputed:
            raise ModelConfigError(
                f"metrics {uncomputed} cannot be computed; evaluation.compute_metrics "
                f"produces {list(COMPUTABLE_METRICS)}. A metric nothing computes would be "
                "recorded as absent and read as 'measured, and it happened to be nothing'."
            )
        object.__setattr__(self, "metrics", metrics)
        # A NaN hyperparameter silently produces a model that cannot be compared
        # with anything, so it is refused here rather than discovered later.
        for key, value in dict(self.training).items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ModelConfigError(
                    f"training hyperparameter {key!r} is not finite ({value!r}); a non-finite "
                    "hyperparameter makes two runs incomparable and cannot be recorded honestly"
                )
        object.__setattr__(self, "training", dict(self.training))
        object.__setattr__(self, "subject", str(self.subject))

    # --- derived ------------------------------------------------------------

    @property
    def is_sequence(self) -> bool:
        return self.model_family in SEQUENCE_FAMILIES

    @property
    def target_columns(self) -> tuple[str, ...]:
        """Target column names, built by Phase 3's own naming rule.

        Derived, never declared: this is what makes an unavailable target
        detectable. If Phase 3 produced no `target_water_level_6h` column, this
        name simply does not appear in the dataset and the run reports
        `target_unavailable`.
        """
        return tuple(target_name(self.target_quantity, hour * 3600.0) for hour in self.horizon_hours)

    @property
    def horizon_seconds(self) -> tuple[float, ...]:
        return tuple(hour * 3600.0 for hour in self.horizon_hours)

    @property
    def horizon_labels(self) -> tuple[str, ...]:
        return tuple(window_label(hour * 3600.0) for hour in self.horizon_hours)

    def with_changes(self, **changes: Any) -> "ModelConfig":
        """A copy with `changes` applied, re-validated."""
        return replace(self, **changes)

    # --- serialisation ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": MODEL_CONTRACT_VERSION,
            "model_family": self.model_family,
            "target_quantity": self.target_quantity,
            "target_columns": list(self.target_columns),
            "horizon_hours": list(self.horizon_hours),
            "horizon_labels": list(self.horizon_labels),
            "random_seed": self.random_seed,
            "feature_selection": self.feature_selection,
            "scaler_policy": self.scaler_policy,
            "impute_policy": self.impute_policy,
            "split_policy": self.split_policy,
            "persistence_source": self.persistence_source,
            "lookback": self.lookback,
            "min_train_rows": self.min_train_rows,
            "min_eval_rows": self.min_eval_rows,
            "metrics": list(self.metrics),
            "artifact_policy": self.artifact_policy,
            "training": dict(sorted(self.training.items())),
            "subject": self.subject,
        }

    def describe(self) -> str:
        return (
            f"Model configuration ({MODEL_CONTRACT_VERSION})\n"
            f"  family           : {self.model_family}\n"
            f"  target           : {self.target_quantity}\n"
            f"  horizons         : {', '.join(self.horizon_labels)}\n"
            f"  target columns   : {', '.join(self.target_columns)}\n"
            f"  seed             : {self.random_seed}\n"
            f"  features         : {self.feature_selection}\n"
            f"  scaling          : {self.scaler_policy}\n"
            f"  imputation       : {self.impute_policy} (training rows only)\n"
            f"  split            : {self.split_policy}\n"
            f"  persistence from : {self.persistence_source}\n"
            f"  lookback         : {self.lookback if self.is_sequence else '(unused)'}\n"
            f"  metrics          : {', '.join(self.metrics)}\n"
            f"  artifacts        : {self.artifact_policy}\n"
            f"  hyperparameters  : "
            + (", ".join(f"{k}={v}" for k, v in sorted(self.training.items())) or "(defaults)")
        )


def deterministic_config(model_family: str, **changes: Any) -> ModelConfig:
    """A configuration with the fixed seed left in place and `changes` applied."""
    if "random_seed" in changes:
        raise ModelConfigError(
            "random_seed is part of what makes a run reproducible; refusing to build a "
            "'deterministic' configuration that overrides it"
        )
    return ModelConfig(model_family=model_family, **changes)


__all__ = [
    "ARTIFACT_INCLUDE_PARAMETERS",
    "ARTIFACT_METADATA_ONLY",
    "ARTIFACT_POLICIES",
    "COMPUTABLE_METRICS",
    "CONFIG_PREFIX",
    "DEFAULT_METRICS",
    "FEATURE_SELECTION_ALL",
    "FEATURE_SELECTION_POLICIES",
    "FEATURE_SELECTION_TRAIN_PRESENT",
    "FAMILY_GRU",
    "FAMILY_LSTM",
    "FAMILY_NAIVE",
    "FAMILY_RANDOM_FOREST",
    "FAMILY_XGBOOST",
    "IMPUTE_MEDIAN",
    "IMPUTE_NONE",
    "IMPUTE_POLICIES",
    "MODEL_CONFIG_NOTE_CODES",
    "MODEL_CONTRACT_VERSION",
    "MODEL_FAMILIES",
    "PERSISTENCE_SOURCE_ANY_PAST",
    "PERSISTENCE_SOURCE_POLICIES",
    "PERSISTENCE_SOURCE_SAME_SPLIT",
    "ROLE_BASELINE",
    "ROLE_CLASSICAL_ML",
    "ROLE_PRIMARY_CANDIDATE",
    "ROLE_SEQUENCE",
    "SCALER_NONE",
    "SCALER_POLICIES",
    "SCALER_STANDARD",
    "SEQUENCE_FAMILIES",
    "SPLIT_POLICIES",
    "SPLIT_POLICY_PHASE3",
    "TREE_FAMILIES",
    "ModelConfig",
    "ModelConfigError",
    "deterministic_config",
]