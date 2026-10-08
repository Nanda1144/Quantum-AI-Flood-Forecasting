# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""What Phase 5 loads before it is willing to forecast anything.

A Phase 4 artifact manifest is a description of a model. This module turns that
description into something a serving path can *check itself against*, and refuses
the ones that do not line up.

**It loads no weights and writes no weights.** Phase 4's
`WEIGHT_STORAGE_POLICY` is explicit that fitted parameters are not in this
repository; what a manifest carries is a pointer plus the metadata needed to use
the bytes safely. So `ForecastArtifact` is metadata, and the byte-loading side is
the caller's business - either an in-process estimator from the training run, or
a resolver reading object storage in a deployment. What this module guarantees is
that whatever gets loaded is *checked against a manifest that has been validated
first*.

**Every rejection is a named error, and none of them is a zero.** A manifest with
the wrong feature digest, the wrong target, the wrong horizon or a scaler that was
fitted on something other than the training split is refused loudly. The failure
modes this guards against are all silent ones: a feature column reordered, a
scaler that saw a validation row, a six-hour model asked for a twenty-four-hour
forecast. Each of those produces a number that looks fine and is about the wrong
thing.

**It defines no new state vocabulary for the platform.** Phase 4's
`HANDOFF_STATUSES` already name every way a forecast can fail to exist, so
`ARTIFACT_STATES` here is an *artifact-level* view with an explicit mapping back
onto them (`handoff_status_for_state`), rather than a parallel set of words for
the same six ideas.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .feature_pipeline import FEATURE_CONTRACT_VERSION
from .model_artifacts import (
    ARTIFACT_MANIFEST_VERSION,
    ARTIFACT_STATUS_NOT_WRITTEN,
    INDEX_FILENAME,
    LEGACY_MANIFEST_VERSION,
    ArtifactManifest,
    feature_digest,
)
from .model_config import MODEL_CONTRACT_VERSION
from .model_registry import (
    ARTIFACT_STATUSES,
    DATA_STATUS_MEASURED,
    DATA_STATUS_SYNTHETIC_DEMO,
    DATA_STATUS_UNKNOWN,
    MODEL_FAMILIES,
    STATUS_DEPENDENCY_UNAVAILABLE,
    STATUS_FAILED_TRAINING,
    STATUS_TARGET_UNAVAILABLE,
    STATUS_TRAINED,
    TRAINING_STATUSES,
    spec_for,
)
from .model_handoff import (
    STATUS_ARTIFACT_UNAVAILABLE,
    STATUS_DEPENDENCY_UNAVAILABLE as HANDOFF_DEPENDENCY_UNAVAILABLE,
    STATUS_INVALID_REQUEST,
    STATUS_TARGET_UNAVAILABLE as HANDOFF_TARGET_UNAVAILABLE,
)
from .provenance import (
    DATASET_TYPE_REAL,
    DATASET_TYPE_SYNTHETIC,
    DATASET_TYPE_UNKNOWN,
    SYNTHETIC_DATA_DISCLAIMER,
)

#: Bumped when the artifact payload changes incompatibly. Distinct from Phase 4's
#: `ARTIFACT_MANIFEST_VERSION`, which versions the manifest Phase 4 writes; this
#: versions the *serving-side* view of it, which is allowed to carry fields the
#: manifest does not (the preprocessing block, the model version).
FORECAST_ARTIFACT_VERSION = "navya-phase5-artifact/v1"

#: The manifest file name Phase 4 writes, kept here so the loader and the writer
#: are not two independent guesses about the same string.
MANIFEST_SUFFIX = ".manifest.json"
ARTIFACT_INDEX_NAME = "phase4-artifacts.index.json"

#: Only a scaler or imputer fitted on this split may be used at serving time.
#: Stated as a constant because the check reads better as a comparison against a
#: named thing than against a literal buried in a conditional.
TRAINING_SPLIT = "train"

#: Phase 4's data-status vocabulary, restated as a tuple so an artifact can
#: validate the field without reaching into a module that exports the three
#: constants but not the collection. Reused, not reinvented: the values are
#: Phase 4's.
DATA_STATUSES: tuple[str, ...] = (
    DATA_STATUS_SYNTHETIC_DEMO,
    DATA_STATUS_MEASURED,
    DATA_STATUS_UNKNOWN,
)


# --------------------------------------------------------------------------- #
# Artifact-level states
# --------------------------------------------------------------------------- #

STATE_AVAILABLE = "available"
STATE_DEPENDENCY_BLOCKED = "dependency_blocked"
STATE_ARTIFACT_MISSING = "artifact_missing"
STATE_INVALID = "invalid"
STATE_NOT_EVALUABLE = "not_evaluable"

#: Every state a `ForecastArtifact` may carry, in the order a reader should read
#: them: what is servable first, then the refusals, then the two that describe an
#: artifact which exists but is not a candidate.
ARTIFACT_STATES: tuple[str, ...] = (
    STATE_AVAILABLE,
    STATE_DEPENDENCY_BLOCKED,
    STATE_ARTIFACT_MISSING,
    STATE_INVALID,
    STATE_NOT_EVALUABLE,
)

#: The one state from which a forecast may actually be produced.
SERVABLE_STATES: frozenset[str] = frozenset({STATE_AVAILABLE})


def handoff_status_for_state(state: str) -> str:
    """Map an artifact state onto the Phase 4 handoff status it corresponds to.

    Phase 4 already names every way a forecast can fail to exist. Introducing a
    second vocabulary here would mean a reader translating between two sets of
    words for the same six ideas, and getting it wrong silently. So the mapping is
    explicit, total, and tested rather than left to the reader to infer.
    """
    mapping = {
        STATE_AVAILABLE: "ready",
        STATE_DEPENDENCY_BLOCKED: HANDOFF_DEPENDENCY_UNAVAILABLE,
        STATE_ARTIFACT_MISSING: STATUS_ARTIFACT_UNAVAILABLE,
        STATE_INVALID: STATUS_INVALID_REQUEST,
        STATE_NOT_EVALUABLE: STATUS_INVALID_REQUEST,
    }
    if state not in mapping:
        raise ForecastArtifactError(
            f"unknown artifact state {state!r}; known states are {list(ARTIFACT_STATES)}"
        )
    return mapping[state]


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class ForecastArtifactError(ValueError):
    """Base class: an artifact could not be loaded, or would not be served from."""


class ArtifactMissingError(ForecastArtifactError):
    """There is no artifact for this model at all."""


class DependencyBlockedError(ForecastArtifactError):
    """The artifact exists, but the library its family needs is not installed.

    Deliberately *not* a subclass of `ArtifactMissingError`. The two look alike to an
    operator - "I asked for xgboost and got nothing" - and they call for opposite
    responses: a missing artifact means the training run did not produce a manifest,
    while a blocked one means the manifest is sitting there and cannot be executed.
    Collapsing them into one status sends whoever is on call to the wrong place, and
    it does so quietly, because the refusal still reads as a refusal either way.
    """


class ArtifactMalformedError(ForecastArtifactError):
    """The artifact exists but is not a shape this loader understands."""


class ArtifactSchemaMismatchError(ForecastArtifactError):
    """The artifact declares a schema version this loader does not implement."""


class ArtifactChecksumError(ForecastArtifactError):
    """The artifact's own recorded checksum does not match its contents."""


class ArtifactContractMismatchError(ForecastArtifactError):
    """The feature contract does not match what the caller supplied."""


class ArtifactTargetMismatchError(ForecastArtifactError):
    """The artifact was not trained on the requested target."""


class ArtifactHorizonMismatchError(ForecastArtifactError):
    """The artifact was not trained at the requested horizon."""


class ArtifactFamilyMismatchError(ForecastArtifactError):
    """The artifact's family is not one the registry knows, or was not requested."""


class ArtifactPreprocessingMismatchError(ForecastArtifactError):
    """The recorded preprocessing cannot be trusted to transform serving input."""


# --------------------------------------------------------------------------- #
# Preprocessing
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PreprocessingSpec:
    """Training-fitted preprocessing, in a form that can only transform.

    This is deliberately **not** a `preprocessing.StandardScaler` or
    `TrainFittedImputer`. Those objects can be `fit`, and a serving path that
    holds a fittable object is a serving path one accidental call away from
    recomputing its own statistics on whatever it was handed. Here the parameters
    are plain recorded values and the only operation is `transform`, so
    "does not fit during inference" is a property of the type rather than a
    property of a test.

    The order is impute then scale, which is the order Phase 4 fitted in, and
    reordering it would produce a subtly different vector from the same numbers.
    """

    feature_names: tuple[str, ...]
    scaler: Mapping[str, Any] | None = None
    imputer: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.feature_names:
            raise ArtifactPreprocessingMismatchError(
                "a preprocessing spec needs the ordered feature names it was fitted on; "
                "without them there is nothing to align a column to"
            )
        for label, state in (("scaler", self.scaler), ("imputer", self.imputer)):
            if state is None:
                continue
            missing = [key for key in ("kind", "columns", "fitted_on", "fitted_rows") if key not in state]
            if missing:
                raise ArtifactPreprocessingMismatchError(
                    f"the recorded {label} state is missing {missing}; a partial record cannot be "
                    "used to transform anything and must not be filled in with a default"
                )
            # `fitted_on` is the whole point. A scaler that saw a validation row is
            # a scaler carrying validation information into inference, and no amount
            # of correct arithmetic downstream undoes that.
            if state["fitted_on"] != TRAINING_SPLIT:
                raise ArtifactPreprocessingMismatchError(
                    f"the recorded {label} reports fitted_on={state['fitted_on']!r}; serving "
                    f"preprocessing must have been fitted on {TRAINING_SPLIT!r} only, and this "
                    "one cannot be used"
                )
            recorded = tuple(state["columns"])
            if recorded != tuple(self.feature_names):
                raise ArtifactPreprocessingMismatchError(
                    f"the recorded {label} was fitted on {len(recorded)} column(s) that are not "
                    f"the artifact's {len(self.feature_names)} feature column(s) in order; the "
                    "first disagreement is "
                    + _first_disagreement(recorded, tuple(self.feature_names))
                )

    @property
    def fitted_on(self) -> str | None:
        """The split the recorded statistics were fitted on, if any were."""
        for state in (self.scaler, self.imputer):
            if state is not None:
                return str(state["fitted_on"])
        return None

    @property
    def fitted_rows(self) -> int | None:
        for state in (self.scaler, self.imputer):
            if state is not None:
                return int(state["fitted_rows"])
        return None

    @property
    def is_identity(self) -> bool:
        """True when nothing was fitted, so the vector passes through unchanged."""
        return self.scaler is None and self.imputer is None

    def transform(self, values: Sequence[float]) -> np.ndarray:
        """Apply the recorded imputer then the recorded scaler. Never fits."""
        vector = np.asarray(values, dtype="float64").reshape(-1)
        if vector.size != len(self.feature_names):
            raise ArtifactPreprocessingMismatchError(
                f"the vector has {vector.size} value(s) but this artifact's preprocessing was "
                f"recorded against {len(self.feature_names)} feature(s)"
            )
        if self.imputer is not None:
            vector = self._impute(vector)
        if self.scaler is not None:
            vector = self._scale(vector)
        return vector

    def _impute(self, vector: np.ndarray) -> np.ndarray:
        """Replace non-finite cells with the recorded training value for that column.

        Only *recorded* values are used. There is no fallback to the column mean,
        to zero, or to the serving batch: a value this code had to invent would be
        a statistic computed outside the training boundary, which is the exact
        thing this module exists to prevent.
        """
        kind = self.imputer.get("kind")
        values = self.imputer.get("values") or {}
        out = vector.copy()
        for index, name in enumerate(self.feature_names):
            if np.isfinite(out[index]):
                continue
            if name not in values:
                raise ArtifactPreprocessingMismatchError(
                    f"feature {name!r} is absent at serving time and the recorded imputer has no "
                    f"value for it (kind={kind!r}); refusing to invent one"
                )
            out[index] = float(values[name])
        return out

    def _scale(self, vector: np.ndarray) -> np.ndarray:
        mean = self.scaler.get("mean") or {}
        scale = self.scaler.get("scale") or {}
        centred = vector.copy()
        for index, name in enumerate(self.feature_names):
            if name not in mean or name not in scale:
                raise ArtifactPreprocessingMismatchError(
                    f"the recorded scaler has no mean/scale for feature {name!r}; a partially "
                    "recorded scaler cannot be applied"
                )
            divisor = float(scale[name])
            if divisor == 0.0:
                raise ArtifactPreprocessingMismatchError(
                    f"the recorded scale for feature {name!r} is zero, which would divide by zero; "
                    "Phase 2's scaler substitutes 1.0 for a constant column, so a zero here means "
                    "the record is corrupt rather than that the column was constant"
                )
            centred[index] = (centred[index] - float(mean[name])) / divisor
        return centred

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_names": list(self.feature_names),
            "scaler": dict(self.scaler) if self.scaler else None,
            "imputer": dict(self.imputer) if self.imputer else None,
        }

    def describe(self) -> str:
        if self.is_identity:
            return "preprocessing: none recorded; the feature vector passes through unchanged"
        parts = []
        for label, state in (("imputer", self.imputer), ("scaler", self.scaler)):
            if state is None:
                continue
            parts.append(
                f"{label}={state['kind']} on {len(state['columns'])} column(s) fitted on "
                f"{state['fitted_on']} with {state['fitted_rows']} row(s)"
            )
        return "preprocessing: " + "; ".join(parts)


def _first_disagreement(left: Sequence[str], right: Sequence[str]) -> str:
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return f"position {index}: {a!r} vs {b!r}"
    if len(left) != len(right):
        return f"length {len(left)} vs {len(right)}"
    return "(none - the sequences match)"


# --------------------------------------------------------------------------- #
# The artifact
# --------------------------------------------------------------------------- #

#: Keys a manifest must carry for this loader to build an artifact from it. Listed
#: explicitly so "malformed" means "one of these is absent" rather than "the code
#: got as far as it could before failing", which is a much harder thing to debug
#: from a traceback.
REQUIRED_ARTIFACT_FIELDS: tuple[str, ...] = (
    "model_id",
    "model_family",
    "target",
    "horizon",
    "training_status",
    "artifact_status",
    "feature_count",
    "feature_digest",
)


@dataclass(frozen=True)
class ForecastArtifact:
    """One model, checked and ready to be served from - or a named reason it is not.

    Construction is not validation. A `ForecastArtifact` can exist in any of the
    five `ARTIFACT_STATES`, including the four that refuse a forecast, because
    "this artifact exists and it is dependency-blocked" is a fact worth holding.
    What construction *does* guarantee is the shape: the feature digest matches the
    feature names, the family is one the registry knows, the statuses are in their
    vocabularies, and the preprocessing was fitted on training rows only.
    """

    model_id: str
    model_family: str
    target: str
    horizon: str
    training_status: str
    artifact_status: str
    artifact_id: str = ""
    artifact_schema_version: str = FORECAST_ARTIFACT_VERSION
    manifest_version: str = ARTIFACT_MANIFEST_VERSION
    model_version: str = "unknown"
    role: str | None = None
    target_units: str | None = None
    feature_names: tuple[str, ...] = ()
    declared_feature_count: int | None = None
    feature_digest: str = ""
    feature_contract_version: str = FEATURE_CONTRACT_VERSION
    model_contract_version: str = MODEL_CONTRACT_VERSION
    artifact_format_version: str | None = None
    preprocessing: PreprocessingSpec | None = None
    split_policy: str | None = None
    split_bounds: Mapping[str, Any] = field(default_factory=dict)
    row_counts: Mapping[str, Any] = field(default_factory=dict)
    metrics_by_split: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    evaluation_status_by_split: Mapping[str, str] = field(default_factory=dict)
    hyperparameters: Mapping[str, Any] = field(default_factory=dict)
    dependency_versions: Mapping[str, str] = field(default_factory=dict)
    random_seed: int | None = None
    scaler_policy: str | None = None
    impute_policy: str | None = None
    fingerprint_digest: str | None = None
    provenance: Mapping[str, Any] | None = None
    synthetic_demo: bool = True
    data_status: str = "unknown"
    disclaimer: str | None = None
    weight_reference: str | None = None
    weight_stored_in_repository: bool = False
    state: str = STATE_INVALID
    reason: str | None = None
    insufficiency: Mapping[str, Any] | None = None
    production_ready_claimed: bool = False
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.state not in ARTIFACT_STATES:
            raise ForecastArtifactError(
                f"unknown artifact state {self.state!r}; known states are {list(ARTIFACT_STATES)}"
            )
        if self.model_family not in MODEL_FAMILIES:
            raise ArtifactFamilyMismatchError(
                f"model_family {self.model_family!r} is not in the Phase 4 registry "
                f"({list(MODEL_FAMILIES)}); an artifact whose family nothing declares cannot be "
                "checked against a contract"
            )
        if not self.reason:
            # Phase 4 records an empty string where there is nothing to report.
            # Normalised to `None` here so that `artifact.reason` means "there is a
            # reason" rather than "there is a reason, possibly a blank one" - a
            # caller checking `if artifact.reason` and finding `""` should be told
            # there is nothing, and a caller reading a reason should never be handed
            # one that explains nothing.
            object.__setattr__(self, "reason", None)
        if self.training_status not in TRAINING_STATUSES:
            raise ArtifactMalformedError(
                f"training_status {self.training_status!r} is not a Phase 4 training status "
                f"({list(TRAINING_STATUSES)})"
            )
        if self.artifact_status not in ARTIFACT_STATUSES:
            raise ArtifactMalformedError(
                f"artifact_status {self.artifact_status!r} is not a Phase 4 artifact status "
                f"({list(ARTIFACT_STATUSES)})"
            )
        if self.data_status not in DATA_STATUSES:
            raise ArtifactMalformedError(
                f"data_status {self.data_status!r} is not one of {list(DATA_STATUSES)}"
            )
        if self.declared_feature_count is not None and len(self.feature_names) != self.declared_feature_count:
            raise ArtifactContractMismatchError(
                f"the artifact names {len(self.feature_names)} feature(s) but reports "
                f"feature_count={self.declared_feature_count}; the count and the names must agree "
                "or neither can be trusted"
            )
        if self.feature_names:
            recomputed = feature_digest(self.feature_names)
            if self.feature_digest and recomputed != self.feature_digest:
                raise ArtifactContractMismatchError(
                    f"the recorded feature digest does not match the recorded feature names "
                    f"(recorded {self.feature_digest[:16]}..., recomputed {recomputed[:16]}...); "
                    "the feature contract this artifact was built against cannot be verified"
                )
        if self.production_ready_claimed:
            raise ForecastArtifactError(
                "an artifact on synthetic/demo data may not claim production readiness; "
                "production_ready_claimed is permanently False in Phase 5"
            )

    # -- derived facts ------------------------------------------------------- #

    @property
    def feature_count(self) -> int:
        return len(self.feature_names)

    @property
    def available(self) -> bool:
        """True only when this artifact may actually produce a forecast."""
        return self.state in SERVABLE_STATES

    @property
    def selectable(self) -> bool:
        """True when this artifact is a candidate for model *selection*.

        Selection needs a scored evaluation, not just a fit, so a trained-but-
        unevaluated artifact is servable and not selectable. Collapsing the two
        would mean either ranking an unscored model or refusing to serve a model
        that works.
        """
        return self.state == STATE_AVAILABLE and bool(self.metrics_by_split)

    @property
    def handoff_status(self) -> str:
        return handoff_status_for_state(self.state)

    @property
    def uses_trained_parameters(self) -> bool:
        """Whether serving this artifact needs fitted weights resolved from outside.

        The persistence baseline is the interesting case: it has no fitted
        parameters at all, because its prediction *is* the last observed value. So
        it can be served from a manifest alone, with nothing loaded, and this
        property is what lets the serving path know that in advance rather than
        discovering it by failing to find an estimator.
        """
        return self.model_family not in _PARAMETER_FREE_FAMILIES

    def feature_index(self, name: str) -> int:
        try:
            return self.feature_names.index(name)
        except ValueError:
            raise ArtifactContractMismatchError(
                f"feature {name!r} is not one of this artifact's "
                f"{self.feature_count} feature(s)"
            ) from None

    # -- contract checks ---------------------------------------------------- #

    def require_servable(self) -> "ForecastArtifact":
        """Return self, or raise the error that explains why this cannot serve."""
        if self.state == STATE_AVAILABLE:
            return self
        raise _error_for_state(self.state)(
            f"artifact {self.artifact_id or self.model_id!r} is in state {self.state!r}"
            + (f": {self.reason}" if self.reason else "")
        )

    def check_target(self, target: str) -> None:
        if target != self.target:
            raise ArtifactTargetMismatchError(
                f"artifact {self.artifact_id or self.model_id!r} was trained on target "
                f"{self.target!r}; a forecast for {target!r} would be a different model, and "
                "Phase 5 does not substitute a target"
            )

    def check_horizon(self, horizon: str) -> None:
        if horizon != self.horizon:
            raise ArtifactHorizonMismatchError(
                f"artifact {self.artifact_id or self.model_id!r} was trained at horizon "
                f"{self.horizon!r}; answering a request for {horizon!r} would stamp a value "
                "with an instant it was never predicted for"
            )

    def check_family(self, model_family: str | None) -> None:
        if model_family is not None and model_family != self.model_family:
            raise ArtifactFamilyMismatchError(
                f"artifact {self.artifact_id or self.model_id!r} is family "
                f"{self.model_family!r}, not {model_family!r}"
            )

    def check_feature_contract(
        self, names: Sequence[str], *, version: str | None = None
    ) -> None:
        """The caller's features must be this artifact's features, in this order."""
        if version is not None and version != self.feature_contract_version:
            raise ArtifactContractMismatchError(
                f"the caller built features under contract {version!r} but this artifact was "
                f"trained against {self.feature_contract_version!r}; the two feature sets are not "
                "the same contract and their columns cannot be lined up"
            )
        if tuple(names) != tuple(self.feature_names):
            raise ArtifactContractMismatchError(
                f"the caller supplied {len(names)} feature(s) in an order this artifact does not "
                f"recognise; first disagreement is "
                + _first_disagreement(tuple(names), tuple(self.feature_names))
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_schema_version": self.artifact_schema_version,
            "artifact_id": self.artifact_id,
            "manifest_version": self.manifest_version,
            "model_id": self.model_id,
            "model_family": self.model_family,
            "model_version": self.model_version,
            "role": self.role,
            "target": self.target,
            "target_units": self.target_units,
            "horizon": self.horizon,
            "training_status": self.training_status,
            "artifact_status": self.artifact_status,
            "state": self.state,
            "reason": self.reason,
            "feature_names": list(self.feature_names),
            "feature_count": self.feature_count,
            "feature_digest": self.feature_digest,
            "feature_contract_version": self.feature_contract_version,
            "model_contract_version": self.model_contract_version,
            "artifact_format_version": self.artifact_format_version,
            "preprocessing": self.preprocessing.to_dict() if self.preprocessing else None,
            "split_policy": self.split_policy,
            "split_bounds": dict(sorted(self.split_bounds.items())),
            "row_counts": dict(sorted(self.row_counts.items())),
            "metrics_by_split": {
                split: {k: float(v) for k, v in sorted(values.items())}
                for split, values in sorted(self.metrics_by_split.items())
            },
            "evaluation_status_by_split": dict(sorted(self.evaluation_status_by_split.items())),
            "hyperparameters": dict(sorted(self.hyperparameters.items())),
            "dependency_versions": dict(sorted(self.dependency_versions.items())),
            "random_seed": self.random_seed,
            "scaler_policy": self.scaler_policy,
            "impute_policy": self.impute_policy,
            "fingerprint_digest": self.fingerprint_digest,
            "provenance": dict(self.provenance) if self.provenance else None,
            "synthetic_demo": self.synthetic_demo,
            "data_status": self.data_status,
            "disclaimer": self.disclaimer,
            "weight_reference": self.weight_reference,
            "weight_stored_in_repository": self.weight_stored_in_repository,
            "uses_trained_parameters": self.uses_trained_parameters,
            "insufficiency": dict(self.insufficiency) if self.insufficiency else None,
            "production_ready_claimed": self.production_ready_claimed,
            "handoff_status": self.handoff_status,
            "created_at": self.created_at,
        }

    def describe(self) -> str:
        lines = [
            f"Forecast artifact {self.artifact_schema_version}",
            f"  artifact id    : {self.artifact_id or '(none)'}",
            f"  model          : {self.model_id} [{self.model_family}]",
            f"  model version  : {self.model_version}",
            f"  target         : {self.target} [{self.target_units or 'unit unknown'}]"
            f" @ {self.horizon}",
            f"  state          : {self.state} -> handoff {self.handoff_status}",
            f"  training       : {self.training_status}",
            f"  artifact       : {self.artifact_status}",
            f"  features       : {self.feature_count} (digest "
            f"{(self.feature_digest or '')[:12] or 'n/a'})",
            f"  weights in git : {self.weight_stored_in_repository}"
            + (f" (reference {self.weight_reference})" if self.weight_reference else ""),
            f"  needs weights  : {self.uses_trained_parameters}",
            f"  data status    : {self.data_status} (synthetic={self.synthetic_demo})",
        ]
        if self.preprocessing is not None:
            lines.append("  " + self.preprocessing.describe())
        for split in sorted(self.metrics_by_split):
            values = ", ".join(
                f"{key}={value:.6g}" for key, value in sorted(self.metrics_by_split[split].items())
            )
            lines.append(f"  {split:<15}: {values or 'no metrics recorded'}")
        if self.reason:
            lines.append(f"  reason         : {self.reason}")
        if self.disclaimer:
            lines.append(f"  disclaimer     : {self.disclaimer}")
        return "\n".join(lines)


def _error_for_state(state: str) -> type[ForecastArtifactError]:
    return {
        STATE_AVAILABLE: ForecastArtifactError,
        STATE_DEPENDENCY_BLOCKED: DependencyBlockedError,
        STATE_ARTIFACT_MISSING: ArtifactMissingError,
        STATE_INVALID: ArtifactContractMismatchError,
        STATE_NOT_EVALUABLE: ArtifactContractMismatchError,
    }[state]


#: Families whose prediction rule is not a set of fitted parameters. The
#: persistence baseline is defined *as* the last observed value, so it needs no
#: weights and can be served from a manifest plus the target history alone.
_PARAMETER_FREE_FAMILIES: frozenset[str] = frozenset({"naive"})


# --------------------------------------------------------------------------- #
# Building an artifact from a Phase 4 manifest
# --------------------------------------------------------------------------- #


def state_for_manifest(manifest: ArtifactManifest) -> str:
    """The artifact-level state implied by a Phase 4 manifest.

    Order matters and is stated rather than implied. A dependency-blocked family
    is reported as *that* rather than as `artifact_missing`, even though it also
    wrote no artifact: the missing artifact is a consequence of the missing
    package, and "artifact_missing" would send a reader looking for a file when the
    fix is to install something. Only once the dependency is present does "nothing
    was written" become the informative answer. An artifact that exists and fitted
    but was never scored is *not_evaluable*, which is a different problem again and
    is not a reason to refuse a forecast.
    """
    if manifest.training_status == STATUS_DEPENDENCY_UNAVAILABLE:
        return STATE_DEPENDENCY_BLOCKED
    if manifest.artifact_status == ARTIFACT_STATUS_NOT_WRITTEN:
        return STATE_ARTIFACT_MISSING
    if manifest.training_status in (STATUS_FAILED_TRAINING, STATUS_TARGET_UNAVAILABLE):
        return STATE_INVALID
    if manifest.training_status != STATUS_TRAINED:
        return STATE_INVALID
    if manifest.evaluation_status != "evaluated":
        return STATE_NOT_EVALUABLE
    return STATE_AVAILABLE


def build_artifact(
    manifest: ArtifactManifest,
    *,
    preprocessing: PreprocessingSpec | None = None,
    feature_names: Sequence[str] | None = None,
    model_version: str | None = None,
) -> ForecastArtifact:
    """Wrap a validated Phase 4 manifest as a serving-side artifact.

    `preprocessing` is the training-fitted scaler/imputer record from Phase 4's
    `ModelDataset`. It is passed in rather than looked up because a manifest does
    not carry it: Phase 4 keeps it on the dataset, and inventing a default here
    would mean serving with parameters nobody fitted. An artifact with no
    preprocessing is only usable by a family that needs none.
    """
    names = tuple(feature_names if feature_names is not None else manifest.feature_columns or ())
    state = state_for_manifest(manifest)
    reason = manifest.reason
    if state == STATE_NOT_EVALUABLE and not reason:
        reason = (
            f"model {manifest.model_id!r} fitted but was never scored "
            f"(evaluation_status={manifest.evaluation_status!r}), so this artifact can serve a "
            "forecast but cannot be ranked against another model"
        )
    version = model_version or _model_version_from_provenance(manifest) or manifest.model_id
    artifact = ForecastArtifact(
        artifact_id=f"{manifest.model_id}@{manifest.fingerprint_digest[:12]}"
        if manifest.fingerprint_digest
        else manifest.model_id,
        model_id=manifest.model_id,
        model_family=manifest.model_family,
        model_version=version,
        role=manifest.role,
        target=manifest.target,
        target_units=manifest.target_units,
        horizon=manifest.horizon,
        training_status=manifest.training_status,
        artifact_status=manifest.artifact_status,
        manifest_version=manifest.manifest_version,
        artifact_format_version=manifest.artifact_format_version,
        feature_names=names,
        declared_feature_count=(
            manifest.feature_count if manifest.feature_count is not None else len(names)
        ),
        feature_digest=manifest.feature_digest or (feature_digest(names) if names else ""),
        feature_contract_version=manifest.feature_contract_version,
        model_contract_version=manifest.model_contract_version,
        preprocessing=preprocessing,
        split_policy=manifest.split_policy,
        split_bounds=dict(manifest.split_bounds),
        row_counts=dict(manifest.row_counts),
        metrics_by_split={
            split: dict(values) for split, values in manifest.metrics_by_split.items()
        },
        evaluation_status_by_split=dict(manifest.evaluation_status_by_split),
        hyperparameters=dict(manifest.hyperparameters),
        dependency_versions=dict(manifest.dependency_versions),
        random_seed=manifest.random_seed,
        # The policies come from the training fingerprint rather than being
        # re-inferred. They are what lets the serving path detect the one
        # preprocessing failure that produces a plausible wrong number: a model
        # trained through a scaler whose fitted record never reached the artifact.
        scaler_policy=getattr(manifest.fingerprint, "scaler_policy", None),
        impute_policy=getattr(manifest.fingerprint, "impute_policy", None),
        fingerprint_digest=manifest.fingerprint_digest,
        provenance=dict(manifest.provenance) if manifest.provenance else None,
        synthetic_demo=manifest.synthetic_demo,
        data_status=manifest.data_status,
        disclaimer=manifest.disclaimer,
        weight_reference=manifest.weight_reference,
        weight_stored_in_repository=manifest.weight_stored_in_repository,
        state=state,
        reason=reason,
        insufficiency=dict(manifest.insufficiency) if manifest.insufficiency else None,
        production_ready_claimed=False,
        created_at=manifest.created_at,
    )
    return artifact


def _model_version_from_provenance(manifest: ArtifactManifest) -> str | None:
    provenance = manifest.provenance or {}
    value = provenance.get("model_version")
    return str(value) if value else None


def build_artifacts(
    manifests: Any,
    *,
    preprocessing_for: Mapping[str, PreprocessingSpec | None] | None = None,
) -> tuple[ForecastArtifact, ...]:
    """Build every artifact from an `ArtifactManifests` bundle (or a list of manifests).

    `preprocessing_for` is keyed by model id so a caller with one dataset can hand
    each family's fitted record to the right artifact. A family with no entry gets
    no preprocessing, which is honest: it means "nothing fitted was recorded for
    it", and the serving path will refuse it if it needed one.
    """
    # Accepting either a bundle or a bare iterable keeps this usable from a
    # rehydrated JSON index as well as from a live `train_models` result, which is
    # the whole point of having a loader.
    source = getattr(manifests, "manifests", manifests)
    lookup = preprocessing_for or {}
    return tuple(
        build_artifact(manifest, preprocessing=lookup.get(manifest.model_id))
        for manifest in source
    )


# --------------------------------------------------------------------------- #
# Loading from disk
# --------------------------------------------------------------------------- #


def parse_artifact(payload: Mapping[str, Any], *, source: str | None = None) -> ForecastArtifact:
    """Build an artifact from a manifest payload, validating the shape first.

    `source` is only used in error messages. Every failure here names what was
    missing or wrong, because a loader that raises `KeyError('target')` has told
    the reader nothing about which of the eight required fields was absent or
    whether the file was truncated.
    """
    where = f" in {source}" if source else ""
    if not isinstance(payload, Mapping):
        raise ArtifactMalformedError(
            f"the artifact{where} is a {type(payload).__name__}, not a JSON object"
        )
    missing = [key for key in REQUIRED_ARTIFACT_FIELDS if key not in payload]
    if missing:
        raise ArtifactMalformedError(
            f"the artifact{where} is missing required field(s) {missing}; it cannot be validated, "
            "and filling them in with defaults would produce an artifact that says nothing about "
            "the model it claims to describe"
        )
    declared_schema = payload.get("artifact_schema_version")
    if declared_schema is not None and declared_schema != FORECAST_ARTIFACT_VERSION:
        raise ArtifactSchemaMismatchError(
            f"the artifact{where} declares schema version {declared_schema!r}; this loader "
            f"implements {FORECAST_ARTIFACT_VERSION!r}. Refusing rather than guessing which fields "
            "moved."
        )
    manifest_version = payload.get("manifest_version")
    if manifest_version is not None and manifest_version != ARTIFACT_MANIFEST_VERSION:
        detail = (
            f"it predates the self-verifying feature contract, so its order-sensitive "
            f"`feature_digest` cannot be recomputed from anything the file records; re-run "
            f"Phase 4 with this version to produce an artifact whose feature list can be checked"
            if manifest_version == LEGACY_MANIFEST_VERSION
            else f"this loader understands {ARTIFACT_MANIFEST_VERSION!r} only"
        )
        raise ArtifactSchemaMismatchError(
            f"the artifact{where} declares manifest version {manifest_version!r} and cannot be "
            f"loaded: {detail}. Refusing rather than serving from a checksum that cannot be "
            "confirmed."
        )

    # A Phase 4 manifest on disk keeps the feature list, the fitted policies and the
    # feature digest inside `fingerprint` - that is the structure Phase 4 hashes -
    # while Phase 5's own `to_dict` carries them at the top level. Both are read
    # here, so a Phase 4 artifact directory loads without a migration step and a
    # Phase 5 artifact round-trips through `to_dict`/`parse_artifact` unchanged.
    fingerprint = payload.get("fingerprint") or {}
    if not isinstance(fingerprint, Mapping):
        raise ArtifactMalformedError(
            f"the artifact{where} has a 'fingerprint' of type {type(fingerprint).__name__}; it "
            "must be a JSON object or absent"
        )
    feature_names = tuple(
        payload.get("feature_names") or fingerprint.get("feature_columns") or ()
    )
    declared_count = payload.get("feature_count")
    if declared_count is None:
        declared_count = fingerprint.get("feature_count")
    digest = str(payload.get("feature_digest") or fingerprint.get("feature_digest") or "")
    scaler_policy = payload.get("scaler_policy") or fingerprint.get("scaler_policy")
    impute_policy = payload.get("impute_policy") or fingerprint.get("impute_policy")

    preprocessing_payload = payload.get("preprocessing")
    preprocessing = None

    # Data status, the synthetic flag and the disclaimer are three views of one fact,
    # and the manifest carries two independent statements about it: its own
    # `synthetic_demo`/`data_status`/`disclaimer` triple, and Phase 1's
    # `ProvenanceRecord.dataset_type` inside `provenance`. When both are present the
    # record wins, because it is the object the platform audits and the one a reviewer
    # opens - and because trusting the manifest's copy means a manifest that says
    # `synthetic_demo: false` about a model trained on synthetic data produces an
    # artifact that reports the data as real, with the contradicting record attached.
    #
    # With no record present there is nothing to derive from, so the manifest's own
    # fields are used: an older manifest is not corrupt for lacking a record.
    provenance_payload = payload.get("provenance")
    synthetic_demo = bool(payload.get("synthetic_demo", True))
    data_status = str(payload.get("data_status") or "unknown")
    disclaimer = payload.get("disclaimer")
    if provenance_payload:
        dataset_type = str(provenance_payload.get("dataset_type") or DATASET_TYPE_UNKNOWN)
        synthetic_demo = dataset_type == DATASET_TYPE_SYNTHETIC
        data_status = (
            DATA_STATUS_SYNTHETIC_DEMO
            if synthetic_demo
            else (DATA_STATUS_MEASURED if dataset_type == DATASET_TYPE_REAL else DATA_STATUS_UNKNOWN)
        )
        # The record's own disclaimer is authoritative, and it is the exact platform
        # sentence. A manifest cannot substitute a shorter one - or omit it - because
        # the one in the record is what the platform README requires.
        if synthetic_demo:
            disclaimer = provenance_payload.get("disclaimer") or SYNTHETIC_DATA_DISCLAIMER
        else:
            disclaimer = provenance_payload.get("disclaimer")

    if preprocessing_payload:
        names = tuple(preprocessing_payload.get("feature_names") or ())
        try:
            preprocessing = PreprocessingSpec(
                feature_names=names,
                scaler=preprocessing_payload.get("scaler"),
                imputer=preprocessing_payload.get("imputer"),
            )
        except ForecastArtifactError as exc:
            raise ArtifactPreprocessingMismatchError(
                f"the artifact{where} carries unusable preprocessing: {exc}"
            ) from exc

    return ForecastArtifact(
        artifact_id=str(payload.get("artifact_id") or payload["model_id"]),
        artifact_schema_version=FORECAST_ARTIFACT_VERSION,
        manifest_version=str(manifest_version or ARTIFACT_MANIFEST_VERSION),
        model_id=str(payload["model_id"]),
        model_family=str(payload["model_family"]),
        model_version=str(payload.get("model_version") or payload["model_id"]),
        role=payload.get("role"),
        target=str(payload["target"]),
        target_units=payload.get("target_units"),
        horizon=str(payload["horizon"]),
        training_status=str(payload["training_status"]),
        artifact_status=str(payload["artifact_status"]),
        feature_names=feature_names,
        declared_feature_count=declared_count,
        feature_digest=digest,
        feature_contract_version=str(
            payload.get("feature_contract_version")
            or fingerprint.get("feature_contract_version")
            or FEATURE_CONTRACT_VERSION
        ),
        model_contract_version=str(
            payload.get("model_contract_version")
            or fingerprint.get("model_contract_version")
            or MODEL_CONTRACT_VERSION
        ),
        artifact_format_version=payload.get("artifact_format_version"),
        preprocessing=preprocessing,
        split_policy=payload.get("split_policy"),
        split_bounds=dict(payload.get("split_bounds") or {}),
        row_counts=dict(payload.get("row_counts") or {}),
        metrics_by_split={
            split: {k: float(v) for k, v in values.items()}
            for split, values in (payload.get("metrics_by_split") or {}).items()
        },
        evaluation_status_by_split=dict(payload.get("evaluation_status_by_split") or {}),
        hyperparameters=dict(payload.get("hyperparameters") or {}),
        dependency_versions=dict(payload.get("dependency_versions") or {}),
        random_seed=payload.get("random_seed") or fingerprint.get("random_seed"),
        scaler_policy=scaler_policy,
        impute_policy=impute_policy,
        fingerprint_digest=payload.get("fingerprint_digest")
        or (fingerprint.get("feature_digest") if fingerprint else None),
        provenance=dict(payload["provenance"]) if payload.get("provenance") else None,
        synthetic_demo=synthetic_demo,
        data_status=data_status,
        disclaimer=disclaimer,
        weight_reference=payload.get("weight_reference"),
        weight_stored_in_repository=bool(payload.get("weight_stored_in_repository", False)),
        state=str(payload.get("state") or state_from_payload(payload)),
        reason=payload.get("reason"),
        insufficiency=dict(payload["insufficiency"]) if payload.get("insufficiency") else None,
        production_ready_claimed=False,
        created_at=str(payload.get("created_at") or ""),
    )


def state_from_payload(payload: Mapping[str, Any]) -> str:
    """Derive the state from a raw Phase 4 manifest payload.

    A Phase 4 manifest written before Phase 5 existed carries no `state` field, so
    the state is derived from the same fields `state_for_manifest` reads. That
    keeps one rule for "what state is this artifact in" rather than two that could
    disagree.
    """
    training = str(payload.get("training_status") or "")
    artifact_status = str(payload.get("artifact_status") or "")
    if training == STATUS_DEPENDENCY_UNAVAILABLE:
        return STATE_DEPENDENCY_BLOCKED
    if artifact_status == ARTIFACT_STATUS_NOT_WRITTEN:
        return STATE_ARTIFACT_MISSING
    if training in (STATUS_FAILED_TRAINING, STATUS_TARGET_UNAVAILABLE, ""):
        return STATE_INVALID
    if training != STATUS_TRAINED:
        return STATE_INVALID
    if str(payload.get("evaluation_status") or payload.get("evaluation_status_by_split", {}).get("validation") or "") not in ("evaluated",):
        return STATE_NOT_EVALUABLE
    return STATE_AVAILABLE


def load_artifact(path: str) -> ForecastArtifact:
    """Read and validate one artifact manifest from disk.

    A missing file and an unreadable file are different failures and get different
    errors: the first says "there is no artifact for this model", the second says
    "there is one and I cannot read it". Collapsing them would hide a permissions
    or encoding problem behind a message that reads like the model does not exist.
    """
    if not path or not os.path.isfile(path):
        raise ArtifactMissingError(
            f"no artifact manifest at {path!r}; Phase 5 will not serve a forecast from a model "
            "whose artifact was never written, and will not invent one"
        )
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeDecodeError) as exc:
        raise ArtifactMalformedError(
            f"the artifact manifest at {path!r} could not be read ({type(exc).__name__}: {exc}); it "
            "exists but is not usable as written"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ArtifactMalformedError(
            f"the artifact manifest at {path!r} is not valid JSON (line {exc.lineno}, column "
            f"{exc.colno}: {exc.msg}); a truncated or hand-edited manifest is refused rather than "
            "parsed leniently"
        ) from exc
    return parse_artifact(payload, source=path)


def load_artifact_directory(directory: str) -> tuple[ForecastArtifact, ...]:
    """Load every model a directory Phase 4 wrote describes, in deterministic order.

    Two sources, and the second is not optional:

    * the `*.manifest.json` files, which carry the full contract for models whose
      artifact was actually written;
    * the bundle index, which additionally lists models Phase 4 *tried and could
      not train* - a dependency-blocked family has `artifact_status='not_written'`
      and so has no manifest file.

    Reading only the files would make a blocked model vanish rather than report
    itself. That is the specific dishonesty this phase is meant to avoid: a
    deployment pointed at this directory would conclude xgboost was never
    attempted, and would have no way to learn from the artifacts alone that the
    blocker is a missing package rather than a missing experiment. Entries in the
    index that also have a file are skipped, so a model is never described twice
    from two sources that could disagree.

    Sorted by model id, so the returned order does not depend on the filesystem.
    """
    if not directory or not os.path.isdir(directory):
        raise ArtifactMissingError(
            f"no artifact directory at {directory!r}; Phase 4 writes manifests to HYDRO_ARTIFACT_DIR "
            "and Phase 5 reads them from there"
        )
    names = sorted(
        name for name in os.listdir(directory) if name.endswith(MANIFEST_SUFFIX)
    )
    artifacts = [load_artifact(os.path.join(directory, name)) for name in names]
    seen = {artifact.model_id for artifact in artifacts}
    artifacts.extend(
        artifact
        for artifact in _index_only_artifacts(directory, seen)
        if artifact.model_id not in seen
    )
    return tuple(sorted(artifacts, key=lambda artifact: artifact.model_id))


def _index_only_artifacts(directory: str, already_loaded: set[str]) -> tuple[ForecastArtifact, ...]:
    """Artifacts the index describes that no manifest file backs.

    Returns `()` for a directory with no index, an unreadable index, or an index
    that describes nothing further. A bundle index is a convenience file, not the
    artifact of record, so failing to read it must not make a whole artifact
    directory unusable - the manifests beside it are the authority, and this is
    only the extra honesty about models that produced no manifest.
    """
    index = os.path.join(directory, INDEX_FILENAME)
    if not os.path.isfile(index):
        return ()
    try:
        with open(index, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, Mapping):
        return ()
    entries = payload.get("manifests")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        return ()

    found: list[ForecastArtifact] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        model_id = str(entry.get("model_id") or "")
        if not model_id or model_id in already_loaded:
            continue
        try:
            found.append(parse_artifact(dict(entry), source=index))
        except ForecastArtifactError:
            # A single unreadable index entry must not hide the manifests that were
            # readable. The entry is skipped and the models that *can* be served are
            # still served; the skipped one simply is not offered as an option.
            continue
    return tuple(found)


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ArtifactStore:
    """Loaded artifacts, indexed by model id and by what they can serve.

    Frozen, so serving cannot mutate what the next request sees. That is the point:
    a serving path that appends to its own registry is a serving path whose answers
    depend on request order.
    """

    artifacts: tuple[ForecastArtifact, ...] = ()

    @classmethod
    def from_manifests(
        cls,
        manifests: Any,
        *,
        preprocessing_for: Mapping[str, PreprocessingSpec | None] | None = None,
    ) -> "ArtifactStore":
        return cls(artifacts=build_artifacts(manifests, preprocessing_for=preprocessing_for))

    @classmethod
    def from_directory(cls, directory: str) -> "ArtifactStore":
        return cls(artifacts=load_artifact_directory(directory))

    def with_preprocessing(
        self, preprocessing_for: Mapping[str, PreprocessingSpec | None]
    ) -> "ArtifactStore":
        """A new store with fitted preprocessing attached. This one is unchanged.

        A Phase 4 manifest records the scaler and imputer *policies* but not the
        fitted means, scales and medians, so a scaled model loaded from disk cannot
        be served until the caller supplies the record that training produced. That
        is not a gap Phase 5 can close by inventing numbers - it is the record of
        what the training split looked like, and only training saw it.

        Returning a new store rather than mutating is what keeps serving
        reproducible: the store a request was answered from cannot change under a
        later one.

        A spec whose feature names do not match its artifact is refused here rather
        than at predict time, so the mismatch is reported against the artifact that
        caused it.
        """
        rebuilt: list[ForecastArtifact] = []
        for artifact in self.artifacts:
            spec = preprocessing_for.get(artifact.model_id)
            if spec is None:
                rebuilt.append(artifact)
                continue
            if tuple(spec.feature_names) != tuple(artifact.feature_names):
                raise ArtifactPreprocessingMismatchError(
                    f"the preprocessing supplied for {artifact.model_id!r} was fitted on "
                    f"{len(spec.feature_names)} feature(s) that are not that artifact's "
                    f"{artifact.feature_count}; first disagreement is "
                    + _first_disagreement(
                        tuple(spec.feature_names), tuple(artifact.feature_names)
                    )
                )
            rebuilt.append(replace(artifact, preprocessing=spec))
        return ArtifactStore(artifacts=tuple(rebuilt))

    @property
    def model_ids(self) -> tuple[str, ...]:
        return tuple(artifact.model_id for artifact in self.artifacts)

    def __len__(self) -> int:
        return len(self.artifacts)

    def __iter__(self):
        return iter(self.artifacts)

    def get(self, model_id: str) -> ForecastArtifact | None:
        for artifact in self.artifacts:
            if artifact.model_id == model_id:
                return artifact
        return None

    def require(self, model_id: str) -> ForecastArtifact:
        artifact = self.get(model_id)
        if artifact is None:
            raise ArtifactMissingError(
                f"no artifact for model {model_id!r}; this store holds "
                f"{list(self.model_ids) or '(nothing)'} and Phase 5 does not resolve a model it "
                "has no artifact for"
            )
        return artifact

    def for_target_horizon(self, target: str, horizon: str) -> tuple[ForecastArtifact, ...]:
        """Every artifact trained on this target at this horizon, in any state.

        Not filtered by state on purpose: "why is there no forecast for `24h`?" has
        to be answerable from the same call that finds the `6h` artifacts, and an
        answer that silently omits the dependency-blocked ones cannot say that
        xgboost was tried and could not run. Use `servable_for` to get only the
        artifacts a forecast may actually be produced from.
        """
        return tuple(
            artifact
            for artifact in self.artifacts
            if artifact.target == target and artifact.horizon == horizon
        )

    def servable_for(self, target: str, horizon: str) -> tuple[ForecastArtifact, ...]:
        """The artifacts at this target and horizon a forecast may be produced from.

        The narrower of the two accessors, and the one a serving path wants: a
        dependency-blocked artifact is present in the store but is not an option.
        """
        return tuple(
            artifact
            for artifact in self.for_target_horizon(target, horizon)
            if artifact.available
        )

    def available(self) -> tuple[ForecastArtifact, ...]:
        return tuple(artifact for artifact in self.artifacts if artifact.available)

    def by_state(self, state: str) -> tuple[ForecastArtifact, ...]:
        return tuple(artifact for artifact in self.artifacts if artifact.state == state)

    def describe(self) -> str:
        lines = [
            f"Forecast artifact store ({FORECAST_ARTIFACT_VERSION})",
            f"  artifacts     : {len(self.artifacts)}",
            f"  servable      : {len(self.available())}",
        ]
        for state in ARTIFACT_STATES:
            found = self.by_state(state)
            if found:
                lines.append(f"  {state:<20}: {[a.model_id for a in found]}")
        return "\n".join(lines)


def artifact_from_manifest_payload(
    manifest_payload: Mapping[str, Any],
    *,
    preprocessing: PreprocessingSpec | None = None,
    source: str | None = None,
) -> ForecastArtifact:
    """Wrap an already-parsed Phase 4 manifest dictionary.

    `preprocessing` is attached here because a Phase 4 manifest on disk does not
    contain it. The alternative - defaulting to "no preprocessing" - would let a
    scaled model be served through an unscaled vector, which returns a number with
    no error and no meaning.
    """
    artifact = parse_artifact(manifest_payload, source=source)
    if preprocessing is None or artifact.preprocessing is not None:
        return artifact
    if tuple(preprocessing.feature_names) != tuple(artifact.feature_names):
        raise ArtifactPreprocessingMismatchError(
            "the supplied preprocessing was fitted on features that are not this artifact's "
            f"features; first disagreement is "
            + _first_disagreement(tuple(preprocessing.feature_names), tuple(artifact.feature_names))
        )
    object.__setattr__(artifact, "preprocessing", preprocessing)
    return artifact


def utc_now() -> str:
    """The one wall-clock reader in this module, so a test can name it."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def registry_availability() -> dict[str, Any]:
    """The Phase 4 registry, rendered as artifact-availability rows.

    Lets a reader see which families could ever produce an artifact without running
    a fit or loading anything.
    """
    rows = []
    for family in MODEL_FAMILIES:
        spec = spec_for(family)
        rows.append(
            {
                "model_family": family,
                "role": spec.role,
                "implementation": spec.implementation,
                "uses_trained_parameters": family not in _PARAMETER_FREE_FAMILIES,
                "available_here": spec.is_available(),
                "blocked_reason": spec.blocker_text(),
                "handoff_status_when_unavailable": handoff_status_for_state(
                    STATE_AVAILABLE if spec.is_available() else STATE_DEPENDENCY_BLOCKED
                ),
            }
        )
    return {"families": list(MODEL_FAMILIES), "rows": rows}


__all__ = [
    "ARTIFACT_INDEX_NAME",
    "ARTIFACT_STATES",
    "FORECAST_ARTIFACT_VERSION",
    "MANIFEST_SUFFIX",
    "REQUIRED_ARTIFACT_FIELDS",
    "SERVABLE_STATES",
    "STATE_ARTIFACT_MISSING",
    "STATE_AVAILABLE",
    "STATE_DEPENDENCY_BLOCKED",
    "STATE_INVALID",
    "STATE_NOT_EVALUABLE",
    "TRAINING_SPLIT",
    "ArtifactChecksumError",
    "ArtifactContractMismatchError",
    "ArtifactFamilyMismatchError",
    "ArtifactHorizonMismatchError",
    "ArtifactMalformedError",
    "ArtifactMissingError",
    "DependencyBlockedError",
    "ArtifactPreprocessingMismatchError",
    "ArtifactSchemaMismatchError",
    "ArtifactStore",
    "ArtifactTargetMismatchError",
    "ForecastArtifact",
    "ForecastArtifactError",
    "PreprocessingSpec",
    "artifact_from_manifest_payload",
    "build_artifact",
    "build_artifacts",
    "handoff_status_for_state",
    "load_artifact",
    "load_artifact_directory",
    "parse_artifact",
    "registry_availability",
    "state_for_manifest",
    "state_from_payload",
    "utc_now",
]