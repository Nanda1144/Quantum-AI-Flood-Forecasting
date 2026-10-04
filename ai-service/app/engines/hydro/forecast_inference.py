# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Turning one validated feature vector into one forecast value, or naming why not.

This is the Phase 5 inference boundary. It is where Phase 2-4's guarantees either
hold or quietly stop holding, and the checks here are the ones that can be made at
this layer at all:

- **No fitting.** `PreprocessingSpec` in `forecast_artifact` can only `transform`.
  There is no `fit` reachable from this module, so "inference does not train" is a
  property of the types rather than a promise in a docstring. The estimator is
  supplied already fitted, and the only things this module does with it are
  `predict`.
- **Causality.** Every feature carries the instant it was derived from, and every
  one of them must be at or before the origin. A feature built from a reading after
  the origin is not a bad feature, it is a leak, and it produces a confident wrong
  answer rather than an error.
- **Entity isolation.** The input names the entity it was built for and it must be
  the entity the request asks about. A vector assembled from station A's readings
  and labelled station B is the cross-station contamination Phase 3's windows are
  built to prevent, caught one layer later.
- **Contract compatibility.** Features are checked against the artifact's names,
  order and digest *before* anything numeric happens. A reordered feature set is the
  quietest failure in a forecasting pipeline: it returns a number, it just means
  nothing.

**Nothing here invents a number.** No fitted estimator means `artifact_unavailable`,
not a fallback; no target observation means no persistence forecast, not zero; a
feature that is still absent after training-fitted imputation means an error naming
the feature, not a substituted mean.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import numpy as np

from .forecast_artifact import (
    ArtifactPreprocessingMismatchError,
    ForecastArtifact,
    PreprocessingSpec,
)
from .model_handoff import (
    ForecastRequest,
    HandoffError,
    Uncertainty,
    unavailable_uncertainty,
)
from .model_registry import MODEL_FAMILIES, spec_for

#: Values a feature cell may hold. `bool` is excluded explicitly: it is an `int`
#: subclass, so `True` would otherwise sail through as `1.0` and be consumed as a
#: measurement.
NUMERIC_TYPES = (int, float, np.integer, np.floating)


class ForecastInferenceError(ValueError):
    """Inference could not be carried out. Never raised in place of a number."""


class InputValidationError(ForecastInferenceError):
    """The supplied feature vector is not usable."""


class MissingFeatureError(InputValidationError):
    """A feature the artifact needs was not supplied."""


class UnexpectedFeatureError(InputValidationError):
    """A feature the artifact never asked for was supplied."""


class FeatureOrderError(InputValidationError):
    """The right features arrived in the wrong order."""


class FeatureTypeError(InputValidationError):
    """A feature value is not a real number."""


class CausalityError(ForecastInferenceError):
    """A feature was derived from an instant after the prediction origin."""


class EntityMismatchError(ForecastInferenceError):
    """The feature vector was built for a different entity than the request names."""


class NonFiniteFeatureError(InputValidationError):
    """A feature is still absent after training-fitted imputation."""


class EstimatorUnavailableError(ForecastInferenceError):
    """Serving this model needs fitted weights that were not supplied."""


class NoTargetObservationError(ForecastInferenceError):
    """The persistence baseline has no observation at or before the origin."""


STRATEGY_PERSISTENCE = "persistence"
STRATEGY_ESTIMATOR = "estimator"
STRATEGIES: tuple[str, ...] = (STRATEGY_PERSISTENCE, STRATEGY_ESTIMATOR)


# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TargetObservation:
    """One observed target value, at one instant, for one entity."""

    instant: datetime
    value: float

    def __post_init__(self) -> None:
        if not isinstance(self.value, NUMERIC_TYPES) or isinstance(self.value, bool):
            raise FeatureTypeError(
                f"a target observation must be a real number, got {type(self.value).__name__}"
            )
        if not np.isfinite(float(self.value)):
            raise NonFiniteFeatureError(
                f"a target observation at {self.instant.isoformat()} is not finite "
                f"({self.value!r}); an absent observation is not an observation"
            )

    def to_dict(self) -> dict[str, Any]:
        return {"instant": self.instant.isoformat(), "value": float(self.value)}


def _instant(value: Any, field_name: str) -> datetime:
    """Accept an aware datetime or an ISO-8601 string; reject naive ones.

    Same rule Phase 4's handoff applies, for the same reason: a silently assumed
    timezone becomes a silent horizon error, and this is the layer where the origin
    instant is fixed for a value that will carry a timestamp derived from it.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ForecastInferenceError(f"{field_name} must not be blank")
        candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ForecastInferenceError(
                f"{field_name} {value!r} is not an ISO-8601 timestamp ({exc})"
            ) from exc
    else:
        raise ForecastInferenceError(
            f"{field_name} must be an ISO-8601 string or a datetime, got {type(value).__name__}"
        )
    if parsed.tzinfo is None:
        raise ForecastInferenceError(
            f"{field_name} {parsed.isoformat()!r} carries no timezone; Phase 5 will not assume "
            "UTC, because an assumed offset becomes an error in the prediction timestamp"
        )
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ForecastInput:
    """One entity's feature vector at one origin instant, plus what it was read from.

    `feature_names` and `values` are parallel and positional. That is not an
    implementation detail: it is what makes a mis-ordered vector detectable. A
    mapping would carry insertion order too, but naming the order explicitly means
    the check is a comparison of two declared sequences rather than a trust that the
    caller's dictionary happened to be built in the right sequence.
    """

    entity: str
    origin_instant: datetime
    feature_names: tuple[str, ...]
    values: tuple[float, ...]
    feature_instants: tuple[datetime, ...] = ()
    target_history: tuple[TargetObservation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.entity, str) or not self.entity.strip():
            raise ForecastInferenceError(
                f"entity must be a non-blank string; got {self.entity!r}. A forecast for an "
                "unnamed station cannot be checked against a request that names one."
            )
        if len(self.feature_names) != len(self.values):
            raise FeatureOrderError(
                f"this input names {len(self.feature_names)} feature(s) but supplies "
                f"{len(self.values)} value(s); a positional vector with the wrong length cannot "
                "be aligned to a contract"
            )
        if len(set(self.feature_names)) != len(self.feature_names):
            duplicates = sorted(
                {name for name in self.feature_names if self.feature_names.count(name) > 1}
            )
            raise FeatureOrderError(
                f"feature name(s) {duplicates} appear more than once in this input; a duplicated "
                "column has no single position to be read from"
            )
        if self.feature_instants and len(self.feature_instants) != len(self.feature_names):
            raise CausalityError(
                f"this input supplies {len(self.feature_instants)} feature instant(s) for "
                f"{len(self.feature_names)} feature(s); the causality check cannot be partial, "
                "because an unchecked feature is exactly the one that leaks"
            )

    # -- constructors ------------------------------------------------------- #

    @classmethod
    def from_mapping(
        cls,
        *,
        entity: str,
        origin_instant: Any,
        features: Mapping[str, Any],
        feature_instants: Mapping[str, Any] | None = None,
        target_history: Sequence[TargetObservation | Mapping[str, Any]] = (),
    ) -> "ForecastInput":
        """Build from a name→value mapping, keeping the mapping's own order.

        The order is the mapping's, on purpose: if the caller assembled the
        dictionary in the wrong order, that mistake is preserved here and caught by
        `check_against` rather than being silently corrected into a plausible answer.
        """
        names = tuple(features.keys())
        values = tuple(_coerce(features[name], name) for name in names)
        instants: tuple[datetime, ...] = ()
        if feature_instants:
            missing = [name for name in names if name not in feature_instants]
            if missing:
                raise CausalityError(
                    f"feature instant(s) were given for some features but not {missing}; a feature "
                    "with no recorded instant cannot be shown to be causal, so it is not assumed"
                )
            instants = tuple(_instant(feature_instants[name], f"feature_instants[{name}]") for name in names)
        return cls(
            entity=entity.strip(),
            origin_instant=_instant(origin_instant, "origin_instant"),
            feature_names=names,
            values=values,
            feature_instants=instants,
            target_history=_history(target_history),
        )

    @classmethod
    def from_sequence(
        cls,
        *,
        entity: str,
        origin_instant: Any,
        names: Sequence[str],
        values: Sequence[Any],
        feature_instants: Sequence[Any] | None = None,
        target_history: Sequence[TargetObservation | Mapping[str, Any]] = (),
    ) -> "ForecastInput":
        """Build from parallel name/value sequences, validating types as they land."""
        return cls(
            entity=entity.strip(),
            origin_instant=_instant(origin_instant, "origin_instant"),
            feature_names=tuple(names),
            values=tuple(_coerce(value, name) for value, name in zip(values, names)),
            feature_instants=tuple(
                _instant(instant, "feature_instants") for instant in (feature_instants or ())
            ),
            target_history=_history(target_history),
        )

    @classmethod
    def from_feature_row(
        cls,
        row: Any,
        *,
        entity: str | None = None,
        feature_names: Sequence[str] | None = None,
        target_history: Sequence[TargetObservation | Mapping[str, Any]] = (),
    ) -> "ForecastInput":
        """Build from a Phase 3 `FeatureRow`.

        `feature_names` must be supplied because Phase 3 rows carry every declared
        feature including the ones it could not build. Silently dropping the absent
        ones here would shorten the vector and shift every column after the gap by
        one position, which is a plausible-looking wrong answer rather than an
        error.
        """
        if feature_names is None:
            raise ForecastInferenceError(
                "feature_names must be given when building input from a Phase 3 row: the row "
                "carries features that were declared but not built, and dropping them here would "
                "shift every later column"
            )
        names = tuple(feature_names)
        values = row.values
        missing = [name for name in names if name not in values]
        if missing:
            raise MissingFeatureError(
                f"Phase 3 row {row.entity} at {row.instant.isoformat()} has no value for "
                f"feature(s) {missing}. Declare them as absent (NaN) rather than dropping them, so "
                "the imputation policy decides what happens instead of a shortened vector."
            )
        source_instants = tuple(getattr(row, "source_instants", ()) or ())
        return cls(
            entity=(entity or row.entity).strip(),
            origin_instant=row.instant,
            feature_names=names,
            values=tuple(_coerce(values[name], name) for name in names),
            # Phase 3 records the set of instants a row was built from rather than a
            # per-feature mapping, so every feature inherits the same verified set.
            # That is weaker than a per-feature record and is honest about being so.
            feature_instants=source_instants * len(names),
            target_history=_history(target_history),
        )

    # -- checks ------------------------------------------------------------- #

    def check_against(self, artifact: ForecastArtifact) -> None:
        """Feature names, order and types must match the artifact exactly."""
        if len(self.feature_names) != artifact.feature_count:
            missing = [name for name in artifact.feature_names if name not in self.feature_names]
            extra = [name for name in self.feature_names if name not in artifact.feature_names]
            detail = []
            if missing:
                detail.append(f"missing {missing}")
            if extra:
                detail.append(f"unexpected {extra}")
            body = (
                f"this input supplies {len(self.feature_names)} feature(s) but artifact "
                f"{artifact.artifact_id or artifact.model_id!r} was trained on "
                f"{artifact.feature_count}"
                + (f" ({'; '.join(detail)})" if detail else "")
            )
            # The error type names the fault, so it is chosen from what is actually
            # wrong rather than from the fact that the counts disagreed. A vector with
            # one column too many is missing nothing, and reporting it as a missing
            # feature sends the reader to add a column - which is the wrong repair and
            # would be accepted by a caller who only reads the count.
            if missing or not extra:
                raise MissingFeatureError(body)
            raise UnexpectedFeatureError(body)
        if tuple(self.feature_names) != tuple(artifact.feature_names):
            if sorted(self.feature_names) == sorted(artifact.feature_names):
                raise FeatureOrderError(
                    f"this input has the right {artifact.feature_count} feature(s) in the wrong "
                    f"order; first disagreement is at position "
                    f"{_first_difference(self.feature_names, artifact.feature_names)}. Reordering "
                    "silently would return a number that means nothing."
                    + _naming_disagreement(self.feature_names, artifact.feature_names)
                )
            raise MissingFeatureError(
                "this input's features are not the artifact's features; first disagreement is at "
                f"position {_first_difference(self.feature_names, artifact.feature_names)}"
                + _naming_disagreement(self.feature_names, artifact.feature_names)
            )

    def check_causal(self) -> None:
        """Every feature must have been derived at or before the origin.

        No instants recorded means nothing can be shown, and Phase 5 does not treat
        absence of evidence as evidence of causality - so this raises rather than
        passing. A caller who genuinely knows the vector is causal passes
        `feature_instants` and gets a real check.
        """
        if not self.feature_instants:
            raise CausalityError(
                f"this input records no feature instants for {self.entity} at "
                f"{self.origin_instant.isoformat()}; Phase 5 will not assume a feature vector is "
                "causal, because the whole point of the check is that it cannot be inferred from "
                "the values"
            )
        late = [
            (name, instant)
            for name, instant in zip(self.feature_names, self.feature_instants)
            if instant > self.origin_instant
        ]
        if late:
            offenders = ", ".join(
                f"{name} at {instant.isoformat()}" for name, instant in late[:5]
            )
            more = f" (+{len(late) - 5} more)" if len(late) > 5 else ""
            raise CausalityError(
                f"{len(late)} feature(s) for {self.entity} were derived from instants after the "
                f"prediction origin {self.origin_instant.isoformat()}: {offenders}{more}. A feature "
                "built from the future is a leak, and it produces a confident wrong answer rather "
                "than an error."
            )

    def check_entity(self, request_entity: str) -> None:
        if self.entity != request_entity:
            raise EntityMismatchError(
                f"this feature vector was built for entity {self.entity!r} but the request asks for "
                f"{request_entity!r}; serving one station's readings under another's name is "
                "cross-station contamination, so it is refused rather than served"
            )

    # -- reading ------------------------------------------------------------ #

    def as_mapping(self) -> dict[str, float]:
        return {name: value for name, value in zip(self.feature_names, self.values)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "origin_instant": self.origin_instant.isoformat().replace("+00:00", "Z"),
            "feature_names": list(self.feature_names),
            "values": [None if not np.isfinite(v) else float(v) for v in self.values],
            "feature_instants": [
                instant.isoformat().replace("+00:00", "Z") for instant in self.feature_instants
            ],
            "target_history": [observation.to_dict() for observation in self.target_history],
        }

    def describe(self) -> str:
        absent = [name for name, value in zip(self.feature_names, self.values) if not np.isfinite(value)]
        return (
            f"ForecastInput {self.entity} @ {self.origin_instant.isoformat()}\n"
            f"  features        : {len(self.feature_names)}\n"
            f"  absent features : {absent or 'none'}\n"
            f"  feature instants : {len(self.feature_instants)} recorded"
            + (" (none - causality cannot be shown)" if not self.feature_instants else "")
            + f"\n  target history  : {len(self.target_history)} observation(s)"
        )


def _coerce(value: Any, name: str) -> float:
    """Accept a real number or `None`/NaN as "absent"; refuse everything else.

    `None` becomes NaN rather than an error, because Phase 3 leaves absences intact
    by design and the imputation policy is what decides what happens to them. A
    string is an error: `"3.5"` would otherwise be coerced into a number, and a
    feature that arrived as text has usually been through a serialization boundary
    that may have mangled it.
    """
    if value is None:
        return float("nan")
    if isinstance(value, bool):
        raise FeatureTypeError(
            f"feature {name!r} is a bool ({value!r}); a boolean flag is not a measurement and "
            "Phase 5 will not read it as 0 or 1"
        )
    if isinstance(value, NUMERIC_TYPES):
        return float(value)
    raise FeatureTypeError(
        f"feature {name!r} is a {type(value).__name__} ({value!r}); features must be real numbers "
        "or explicitly absent (None), because a value that arrived as text may have been mangled "
        "on the way here"
    )


def _history(
    entries: Sequence[TargetObservation | Mapping[str, Any] | tuple[Any, Any]],
) -> tuple[TargetObservation, ...]:
    """Normalise target history into sorted `TargetObservation`s.

    Three input forms are accepted - the dataclass, a mapping with `instant` and
    `value`, and a bare `(instant, value)` pair - because the same history arrives
    from three places: a caller's own construction, a JSON payload, and a Phase 4
    split matrix. All three are unambiguous, so accepting them is convenience rather
    than guesswork; anything else is refused rather than coerced.
    """
    history: list[TargetObservation] = []
    for entry in entries:
        if isinstance(entry, TargetObservation):
            history.append(entry)
            continue
        if isinstance(entry, Mapping):
            missing = [key for key in ("instant", "value") if key not in entry]
            if missing:
                raise ForecastInferenceError(
                    f"a target history entry is missing {missing}"
                )
            history.append(
                TargetObservation(
                    instant=_instant(entry["instant"], "target_history.instant"),
                    value=entry["value"],
                )
            )
            continue
        if isinstance(entry, (tuple, list)) and len(entry) == 2:
            history.append(
                TargetObservation(instant=_instant(entry[0], "target_history.instant"), value=entry[1])
            )
            continue
        raise ForecastInferenceError(
            f"a target history entry must be a TargetObservation, a mapping with 'instant' and "
            f"'value', or an (instant, value) pair; got {type(entry).__name__}"
        )
    return tuple(sorted(history, key=lambda observation: observation.instant))


def _first_difference(left: Sequence[str], right: Sequence[str]) -> int:
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    return min(len(left), len(right))


def _naming_disagreement(
    supplied: Sequence[str], expected: Sequence[str], *, limit: int = 4
) -> str:
    """Name the positions that disagree, up to `limit`, for a refusal message.

    A position number tells a reader where to look; it does not tell them what to
    fix. "Position 0" in a 35-column vector is one of several thousand candidates,
    and a caller who has to re-derive the expected order by hand will get it wrong
    eventually - at which point the forecast is confident and wrong. The positions
    and both names are short, so the whole disagreement is spelled out rather than
    summarised, with a count of any remainder.
    """
    disagreements = [
        (index, supplied[index], expected[index])
        for index in range(min(len(supplied), len(expected)))
        if supplied[index] != expected[index]
    ]
    if not disagreements:
        return ""
    named = "; ".join(
        f"position {index} is {found!r} but the artifact was trained on {want!r}"
        for index, found, want in disagreements[:limit]
    )
    if len(disagreements) > limit:
        named += f"; and {len(disagreements) - limit} more"
    return f" Disagreements: {named}."


# --------------------------------------------------------------------------- #
# The result
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ForecastInference:
    """One forecast value, and everything needed to check where it came from.

    `strategy` is the honest summary of *how* the number was produced, and it is on
    the result because the two strategies are not comparable in kind: a persistence
    value is a re-statement of an observation, while an estimator's value is a
    model's output. `feature_vector` is the transformed vector actually handed to the
    model, so a reviewer can confirm the scaler was applied without re-running
    anything.
    """

    prediction: float
    strategy: str
    entity: str
    target: str
    target_units: str | None
    horizon: str
    model_id: str
    model_family: str
    model_version: str
    artifact_id: str
    origin_instant: datetime
    prediction_timestamp: str | None = None
    carried_from_instant: datetime | None = None
    feature_version: str = ""
    feature_count: int = 0
    feature_digest: str = ""
    imputed_features: tuple[str, ...] = ()
    feature_vector: tuple[float, ...] = ()
    preprocessing_applied: bool = False
    uncertainty: Uncertainty = field(
        default_factory=lambda: unavailable_uncertainty(
            "Phase 5 cannot measure error from a single prediction"
        )
    )
    provenance: Mapping[str, Any] | None = None
    synthetic_demo: bool = True
    data_status: str = "unknown"
    disclaimer: str | None = None
    production_ready_claimed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "prediction": self.prediction,
            "strategy": self.strategy,
            "entity": self.entity,
            "target": self.target,
            "target_units": self.target_units,
            "horizon": self.horizon,
            "model_id": self.model_id,
            "model_family": self.model_family,
            "model_version": self.model_version,
            "artifact_id": self.artifact_id,
            "origin_instant": self.origin_instant.isoformat().replace("+00:00", "Z"),
            "prediction_timestamp": self.prediction_timestamp,
            "carried_from_instant": (
                self.carried_from_instant.isoformat().replace("+00:00", "Z")
                if self.carried_from_instant is not None
                else None
            ),
            "feature_version": self.feature_version,
            "feature_count": self.feature_count,
            "feature_digest": self.feature_digest,
            "imputed_features": list(self.imputed_features),
            "preprocessing_applied": self.preprocessing_applied,
            "uncertainty": self.uncertainty.to_dict(),
            "synthetic_demo": self.synthetic_demo,
            "data_status": self.data_status,
            "disclaimer": self.disclaimer,
            "production_ready_claimed": self.production_ready_claimed,
        }

    def describe(self) -> str:
        return (
            f"{self.target} @ {self.horizon} for {self.entity} = {self.prediction!r} "
            f"{self.target_units or ''}\n"
            f"  strategy        : {self.strategy}"
            + (
                f" (carried forward from "
                f"{self.carried_from_instant.isoformat()})"
                if self.carried_from_instant is not None
                else ""
            )
            + f"\n  model           : {self.model_id} ({self.model_family}) {self.model_version}"
            f"\n  artifact        : {self.artifact_id}"
            f"\n  origin          : {self.origin_instant.isoformat()}"
            f"\n  prediction at   : {self.prediction_timestamp or '(withheld - unreadable horizon)'}"
            f"\n  features        : {self.feature_count} "
            f"(digest {(self.feature_digest or '')[:12] or 'n/a'}), "
            f"{len(self.imputed_features)} imputed by training-fitted values"
            f"\n  data status     : {self.data_status} (synthetic={self.synthetic_demo})"
            # The exact platform sentence, not a paraphrase. `describe()` is what a
            # person reads in a log line or a ticket, so a paraphrase here is a
            # paraphrase that can drift away from the sentence the pipeline is
            # required to carry - and a status token like `synthetic_demo` is not a
            # warning, it is a label.
            + (
                f"\n  disclaimer      : {self.disclaimer}"
                if self.synthetic_demo and self.disclaimer
                else ""
            )
        )


# --------------------------------------------------------------------------- #
# Preprocessing
# --------------------------------------------------------------------------- #


def require_preprocessing(artifact: ForecastArtifact) -> PreprocessingSpec:
    """The artifact's preprocessing, or a refusal explaining that it is missing.

    The refusal is driven by the *recorded training policies*, not by convenience.
    If the run recorded a scaler or imputer policy other than "none" and no fitted
    record reached the artifact, then serving through an identity transform would
    hand a scaled model an unscaled vector: the prediction would come back without
    error and mean nothing. That is the failure this check exists for.

    The one artifact exempt from it is a family whose prediction rule reads nothing
    but the target history - the persistence baseline. Its manifest records the same
    scaler and impute policies as every other model because they were fitted once for
    the shared feature matrix, but persistence never sees that matrix, so there is
    nothing in it that a missing scaler could mis-scale. Refusing the baseline for a
    missing fitted record would leave no servable model at all in an environment where
    no weights exist, and the failure it was protecting against cannot occur.
    """
    if artifact.preprocessing is not None:
        return artifact.preprocessing
    if not artifact.uses_trained_parameters:
        return PreprocessingSpec(feature_names=tuple(artifact.feature_names))
    trained_with = [
        f"{label}={policy!r}"
        for label, policy in (
            ("scaler", artifact.scaler_policy),
            ("impute", artifact.impute_policy),
        )
        if policy not in (None, "none")
    ]
    if trained_with:
        raise ArtifactPreprocessingMismatchError(
            f"artifact {artifact.artifact_id or artifact.model_id!r} was trained with "
            f"{' and '.join(trained_with)} but carries no fitted preprocessing record. Serving it "
            "through an identity transform would pass an unscaled vector to a scaled model and "
            "return a number with no meaning, so it is refused."
        )
    return PreprocessingSpec(feature_names=tuple(artifact.feature_names))


def transformed_vector(
    artifact: ForecastArtifact, data: ForecastInput
) -> tuple[np.ndarray, tuple[str, ...]]:
    """`(vector, imputed_feature_names)` after training-fitted preprocessing."""
    spec = require_preprocessing(artifact)
    raw = np.asarray(data.values, dtype="float64")
    # NaN and infinity are separated before the imputer sees them, because they mean
    # opposite things. NaN is a measurement that was never taken, and the artifact
    # records what to substitute for it. An infinity is a *broken* measurement - a
    # sensor fault, a divide by an upstream zero, a value mangled by a serialization
    # boundary - and no recorded statistic is a truthful stand-in for it: filling it
    # turns a fault into a finite number that looks like a forecast and carries no
    # indication that anything went wrong upstream. So an infinity is refused here,
    # by name, while a NaN in the same vector is still imputed.
    broken = tuple(
        name for name, value in zip(data.feature_names, raw) if np.isinf(value)
    )
    if broken:
        offenders = ", ".join(
            f"{name}={raw[index]!r}"
            for index, name in enumerate(data.feature_names)
            if np.isinf(raw[index])
        )
        raise NonFiniteFeatureError(
            f"feature(s) {list(broken)} are infinite ({offenders}). An absent reading is NaN and "
            "the artifact records a value to substitute for it; an infinite reading is a broken "
            "one, and no recorded statistic is a truthful stand-in for it, so Phase 5 refuses it "
            "rather than imputing over it. An absent reading is left absent - set it to None."
        )
    imputed = tuple(
        name
        for name, value in zip(data.feature_names, raw)
        if np.isnan(value)
    )
    vector = spec.transform(raw)
    unresolved = [
        name
        for name, value in zip(data.feature_names, vector)
        if not np.isfinite(value)
    ]
    if unresolved:
        raise NonFiniteFeatureError(
            f"feature(s) {unresolved} are still absent after applying the artifact's "
            "training-fitted imputation; the model would be handed NaN, and Phase 5 does not "
            "substitute a value the training run never recorded"
        )
    return vector, imputed


# --------------------------------------------------------------------------- #
# Prediction
# --------------------------------------------------------------------------- #


def persistence_prediction(data: ForecastInput, *, origin_instant: datetime | None = None) -> tuple[float, datetime]:
    """The baseline: the latest target observation at or before the origin.

    Returns `(value, source_instant)` so the result can name the reading it carried
    forward. An observation *after* the origin is not eligible, even though it is in
    the history: using it would be a leak of exactly the kind this module exists to
    catch, and the baseline is the one predictor where that mistake is easiest to
    make by accident.
    """
    origin = origin_instant or data.origin_instant
    eligible = [item for item in data.target_history if item.instant <= origin]
    if not eligible:
        raise NoTargetObservationError(
            f"no target observation for {data.entity} exists at or before the origin "
            f"{origin.isoformat()} (the history holds "
            f"{len(data.target_history)} observation(s), "
            f"{sum(1 for item in data.target_history if item.instant > origin)} of them after it). "
            "The persistence baseline is 'the last known value', and there is no last known value "
            "to report."
        )
    latest = max(eligible, key=lambda item: item.instant)
    return float(latest.value), latest.instant


def predict(
    artifact: ForecastArtifact,
    data: ForecastInput,
    *,
    estimator: Any = None,
    request: ForecastRequest | None = None,
) -> ForecastInference:
    """Produce one forecast, validating everything before producing anything.

    `estimator` must already be fitted. It is used only through `predict`; nothing
    in this call fits, refits or mutates it.
    """
    if request is not None:
        artifact.check_family(request.model_family)
        artifact.check_target(request.target)
        artifact.check_horizon(request.horizon)
    artifact.require_servable()

    data.check_against(artifact)
    data.check_causal()
    if request is not None:
        data.check_entity(request.entity)

    if artifact.uses_trained_parameters:
        if estimator is None:
            raise EstimatorUnavailableError(
                f"artifact {artifact.artifact_id or artifact.model_id!r} is family "
                f"{artifact.model_family!r}, whose prediction rule is a set of fitted parameters, "
                "and no fitted estimator was supplied. Phase 4's weight-storage policy keeps "
                "those bytes out of this repository, so they must be resolved from "
                f"{artifact.weight_reference or 'object storage or a model registry'}. Phase 5 does "
                "not substitute a fallback model and report the number as though it came from this "
                "one."
            )
        if not hasattr(estimator, "predict"):
            raise EstimatorUnavailableError(
                f"the supplied object for {artifact.model_id!r} has no predict(); it is "
                f"{type(estimator).__name__}, which is not a fitted estimator"
            )
        vector, imputed = transformed_vector(artifact, data)
        prediction = estimator.predict(vector.reshape(1, -1))
        value = _scalar(prediction, artifact, estimator)
        strategy = STRATEGY_ESTIMATOR
        carried_from = None
        applied = not artifact.preprocessing.is_identity if artifact.preprocessing else False
    else:
        value, carried_from = persistence_prediction(data)
        imputed = ()
        vector = np.asarray(data.values, dtype="float64")
        strategy = STRATEGY_PERSISTENCE
        applied = False

    uncertainty = unavailable_uncertainty(
        "Phase 5 produces one value and has no observed counterpart for it. A residual spread "
        "would describe past errors on a split, not a bound on this value."
    )

    return ForecastInference(
        prediction=value,
        strategy=strategy,
        entity=data.entity,
        target=artifact.target,
        target_units=artifact.target_units,
        horizon=artifact.horizon,
        model_id=artifact.model_id,
        model_family=artifact.model_family,
        model_version=artifact.model_version,
        artifact_id=artifact.artifact_id or artifact.model_id,
        origin_instant=data.origin_instant,
        carried_from_instant=carried_from,
        feature_version=artifact.feature_contract_version,
        feature_count=artifact.feature_count,
        feature_digest=artifact.feature_digest,
        imputed_features=imputed,
        feature_vector=tuple(float(entry) for entry in vector),
        preprocessing_applied=applied,
        uncertainty=uncertainty,
        provenance=dict(artifact.provenance) if artifact.provenance else None,
        synthetic_demo=artifact.synthetic_demo,
        data_status=artifact.data_status,
        disclaimer=artifact.disclaimer,
    )


def _scalar(prediction: Any, artifact: ForecastArtifact, estimator: Any) -> float:
    """One finite float out of whatever `predict` returned, or a refusal."""
    array = np.asarray(prediction, dtype="float64").reshape(-1)
    if array.size == 0:
        raise ForecastInferenceError(
            f"the estimator supplied for {artifact.model_id!r} returned no value for a single "
            "feature vector; Phase 5 will not read that as zero"
        )
    if array.size > 1:
        raise ForecastInferenceError(
            f"the estimator supplied for {artifact.model_id!r} returned {array.size} values for one "
            "feature vector. That is the shape of a regressor asked about several samples, so the "
            "request or the estimator does not match what Phase 5 asked."
        )
    value = float(array[0])
    if not np.isfinite(value):
        raise ForecastInferenceError(
            f"the estimator supplied for {artifact.model_id!r} returned {value!r} for a single "
            "feature vector; a non-finite prediction is not a forecast and Phase 5 does not report "
            "it as one"
        )
    return value


def infer(
    request: ForecastRequest,
    artifact: ForecastArtifact,
    data: ForecastInput,
    *,
    estimator: Any = None,
) -> ForecastInference:
    """`predict` with the request's target, horizon, family and entity as the contract."""
    try:
        return predict(artifact, data, estimator=estimator, request=request)
    except ForecastInferenceError:
        raise
    except HandoffError as exc:
        # A `ForecastRequest` that Phase 4 already rejected is not a Phase 5 failure;
        # it is a request that should never have been built. Surfacing the original
        # error keeps the caller's own words for what was wrong with it.
        raise ForecastInferenceError(str(exc)) from exc


def supported_strategies() -> dict[str, Any]:
    """Which strategy each family uses, and whether that family can be served here.

    Readable without training anything, so a reviewer can see that the baseline
    needs no weights and the learned families do.
    """
    rows = []
    for family in MODEL_FAMILIES:
        spec = spec_for(family)
        rows.append(
            {
                "model_family": family,
                "strategy": STRATEGY_PERSISTENCE if family == "naive" else STRATEGY_ESTIMATOR,
                "needs_fitted_parameters": family != "naive",
                "available_here": spec.is_available(),
                "blocked_reason": spec.blocker_text(),
            }
        )
    return {"strategies": list(STRATEGIES), "rows": rows}


__all__ = [
    "CausalityError",
    "EntityMismatchError",
    "EstimatorUnavailableError",
    "FeatureOrderError",
    "FeatureTypeError",
    "ForecastInference",
    "ForecastInferenceError",
    "ForecastInput",
    "InputValidationError",
    "MissingFeatureError",
    "NoTargetObservationError",
    "NonFiniteFeatureError",
    "STRATEGIES",
    "STRATEGY_ESTIMATOR",
    "STRATEGY_PERSISTENCE",
    "TargetObservation",
    "UnexpectedFeatureError",
    "infer",
    "persistence_prediction",
    "predict",
    "require_preprocessing",
    "supported_strategies",
    "transformed_vector",
]