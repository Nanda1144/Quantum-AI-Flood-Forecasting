# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""The Phase 4 → Phase 5 contract: what a trained model offers, and what it does not.

Phase 5 generates forecasts. This module defines what it is allowed to ask for and
what it gets back. It is a **contract, not an API** — there is no route, no
request handler, no serialization middleware, and nothing here that knows about
HTTP. Adding those belongs to Phase 5 and to whoever owns the service layer.

**It defines no second forecast domain model.** `contract.ForecastOutput` already
exists and is what the downstream platform reads; `to_forecast_output` converts a
handoff result into that type rather than letting two forecast shapes drift apart.

**Uncertainty is either measured or declared absent.** This is the field where a
forecasting pipeline is most tempted to lie. A ± value that appeared from nowhere
looks like rigour and is read as a guarantee. So there is exactly one way for a
number to get into `uncertainty.value`: it is computed here, by
`residual_sigma_from`, from actual observed-versus-predicted pairs the caller
hands over. No inputs, no number:

    uncertainty.status = "unavailable"
    uncertainty.reason = "no observed/predicted pairs were supplied for this split"

And even when the number exists it is labelled `residual_sigma_measured` with
`is_prediction_interval = False`, because the spread of past residuals is not a
confidence bound on a future one. Nothing here produces a 95% interval, and there
is no code path that could.

**Every failure is a status, not an exception.** A model blocked by a missing
dependency, a model with no artifact, a target Phase 3 never built — each produces
a `HandoffResult` with a distinct status and a reason naming the cause. Phase 5 can
render "unavailable" from it; it cannot accidentally render a zero.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

import numpy as np

from .artifacts import ARTIFACT_FORMAT_VERSION
from .contract import (
    FORECAST_CONTRACT_VERSION,
    INTEGRATION_STATEMENT,
    ForecastOutput,
)
from .feature_pipeline import FEATURE_CONTRACT_VERSION
from .model_artifacts import (
    ARTIFACT_MANIFEST_VERSION,
    WEIGHT_STORAGE_POLICY,
    ArtifactManifest,
    ArtifactManifests,
)
from .model_config import MODEL_CONTRACT_VERSION
from .model_registry import (
    ARTIFACT_STATUS_NOT_WRITTEN,
    STATUS_DEPENDENCY_UNAVAILABLE,
    STATUS_INSUFFICIENT_DATA,
    STATUS_TARGET_UNAVAILABLE,
    STATUS_TRAINED,
)
from .model_training import RunResult

#: Bumped when the handoff layout changes incompatibly. Distinct from
#: `contract.FORECAST_CONTRACT_VERSION`, which versions the payload the downstream
#: platform already reads and which this module must not redefine.
HANDOFF_CONTRACT_VERSION = "navya-handoff/v1"

# --------------------------------------------------------------------------- #
# Statuses
# --------------------------------------------------------------------------- #

STATUS_READY = "ready"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_DEPENDENCY_UNAVAILABLE = STATUS_DEPENDENCY_UNAVAILABLE
STATUS_INSUFFICIENT_DATA = STATUS_INSUFFICIENT_DATA
STATUS_TARGET_UNAVAILABLE = STATUS_TARGET_UNAVAILABLE
STATUS_ARTIFACT_UNAVAILABLE = "artifact_unavailable"
STATUS_MODEL_UNAVAILABLE = "model_unavailable"
STATUS_NO_PREDICTION = "no_prediction"

#: Every status a handoff result may carry. Phase 5 switches on this tuple.
HANDOFF_STATUSES: tuple[str, ...] = (
    STATUS_READY,
    STATUS_INVALID_REQUEST,
    STATUS_DEPENDENCY_UNAVAILABLE,
    STATUS_INSUFFICIENT_DATA,
    STATUS_TARGET_UNAVAILABLE,
    STATUS_ARTIFACT_UNAVAILABLE,
    STATUS_MODEL_UNAVAILABLE,
    STATUS_NO_PREDICTION,
)

#: Statuses that mean "no forecast value is available", as opposed to `ready`.
UNAVAILABLE_STATUSES: frozenset[str] = frozenset(
    status for status in HANDOFF_STATUSES if status != STATUS_READY
)

# --------------------------------------------------------------------------- #
# Uncertainty
# --------------------------------------------------------------------------- #

UNCERTAINTY_UNAVAILABLE = "unavailable"
UNCERTAINTY_RESIDUAL_SIGMA = "residual_sigma_measured"

UNCERTAINTY_STATUSES: tuple[str, ...] = (
    UNCERTAINTY_UNAVAILABLE,
    UNCERTAINTY_RESIDUAL_SIGMA,
)

#: Stated on every measured uncertainty so nobody reads it as a bound.
RESIDUAL_SIGMA_CAVEAT = (
    "residual_sigma is the standard deviation of observed-minus-predicted on a split "
    "that model was scored on. It is a description of past errors, NOT a prediction "
    "interval and NOT a guarantee about any future value."
)


class HandoffError(ValueError):
    """Raised when a handoff request or result is structurally invalid."""


@dataclass(frozen=True)
class Uncertainty:
    """An uncertainty figure, or an explicit statement that there is none.

    The invariant: `status != UNCERTAINTY_RESIDUAL_SIGMA` implies `value is None`,
    and `status == UNCERTAINTY_RESIDUAL_SIGMA` implies `value` is a real measured
    number. There is no third state in which a value exists without a measurement
    behind it, and `__post_init__` raises rather than accept one.
    """

    status: str = UNCERTAINTY_UNAVAILABLE
    value: float | None = None
    unit: str | None = None
    source: str | None = None
    reason: str | None = None
    is_prediction_interval: bool = False
    caveat: str | None = None

    def __post_init__(self) -> None:
        if self.status not in UNCERTAINTY_STATUSES:
            raise HandoffError(
                f"unknown uncertainty status {self.status!r}; known statuses are "
                f"{list(UNCERTAINTY_STATUSES)}"
            )
        if self.status == UNCERTAINTY_RESIDUAL_SIGMA:
            if self.value is None:
                raise HandoffError(
                    "uncertainty status is 'residual_sigma_measured' but no value was supplied; "
                    "a measured status with no measurement is exactly the claim this module "
                    "refuses to make"
                )
            if not np.isfinite(self.value):
                raise HandoffError(
                    f"uncertainty value must be finite; got {self.value!r}"
                )
            if self.is_prediction_interval:
                raise HandoffError(
                    "this module does not produce prediction intervals; "
                    f"{RESIDUAL_SIGMA_CAVEAT}"
                )
        elif self.value is not None:
            raise HandoffError(
                f"uncertainty status {self.status!r} must carry value=None; a value with no "
                "measurement behind it is exactly the claim this module refuses to make"
            )

    @property
    def available(self) -> bool:
        return self.status == UNCERTAINTY_RESIDUAL_SIGMA and self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "reason": self.reason,
            "is_prediction_interval": self.is_prediction_interval,
            "caveat": self.caveat,
        }

    def describe(self) -> str:
        if not self.available:
            return f"uncertainty: {self.status} - {self.reason or 'no reason recorded'}"
        return (
            f"uncertainty: {self.value:.6g} {self.unit or ''} "
            f"({self.status}, measured on {self.source})"
        )


def unavailable_uncertainty(reason: str) -> Uncertainty:
    """The explicit "there is no number" answer. Always reachable, always honest."""
    return Uncertainty(
        status=UNCERTAINTY_UNAVAILABLE,
        value=None,
        reason=reason,
        caveat=RESIDUAL_SIGMA_CAVEAT,
    )


def residual_sigma_from(
    y_true: Sequence[float],
    y_pred: Sequence[float],
    *,
    unit: str | None = None,
    source: str | None = None,
    minimum_pairs: int = 2,
) -> Uncertainty:
    """The spread of observed-minus-predicted, or an explicit refusal.

    This is the only function in the module that can put a number into an
    `Uncertainty`, and it computes that number from pairs the caller supplies. With
    fewer than `minimum_pairs` pairs it returns `unavailable` rather than a
    standard deviation of one residual, which is zero and would read as perfect
    certainty.
    """
    actual = np.asarray(y_true, dtype="float64").reshape(-1)
    predicted = np.asarray(y_pred, dtype="float64").reshape(-1)
    if actual.size != predicted.size:
        raise HandoffError(
            f"y_true has {actual.size} value(s) and y_pred has {predicted.size}; they must "
            "describe the same observations"
        )
    finite = np.isfinite(actual) & np.isfinite(predicted)
    if int(np.count_nonzero(finite)) < minimum_pairs:
        return unavailable_uncertainty(
            f"{int(np.count_nonzero(finite))} finite observed/predicted pair(s) were supplied; "
            f"at least {minimum_pairs} are needed to describe error spread, and a standard "
            "deviation over fewer would be zero rather than precise"
        )
    residuals = actual[finite] - predicted[finite]
    return Uncertainty(
        status=UNCERTAINTY_RESIDUAL_SIGMA,
        value=float(residuals.std(ddof=1)),
        unit=unit,
        source=source,
        reason=None,
        is_prediction_interval=False,
        caveat=RESIDUAL_SIGMA_CAVEAT,
    )


# --------------------------------------------------------------------------- #
# The request
# --------------------------------------------------------------------------- #


def _parse_instant(value: Any, field_name: str) -> datetime:
    """Accept an ISO-8601 string or a datetime; return an aware UTC datetime.

    Naive datetimes are rejected rather than assumed to be UTC. Assuming is how a
    timezone offset silently becomes a six-hour error in a horizon calculation, and
    this is the layer where the origin instant is fixed.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise HandoffError(f"{field_name} must not be blank")
        candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise HandoffError(
                f"{field_name} {value!r} is not an ISO-8601 timestamp ({exc})"
            ) from exc
    else:
        raise HandoffError(
            f"{field_name} must be an ISO-8601 string or a datetime, got "
            f"{type(value).__name__}"
        )
    if parsed.tzinfo is None:
        raise HandoffError(
            f"{field_name} {parsed.isoformat()!r} carries no timezone; Phase 4 will not "
            "assume UTC, because a silently assumed offset becomes a horizon error"
        )
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ForecastRequest:
    """What Phase 5 asks Phase 4 for.

    Deliberately small. A request names a target, a horizon, an entity and an
    origin instant; everything else about how to build the feature vector belongs
    to the feature contract that Phase 3 already froze, not to a caller-supplied
    dictionary that could disagree with it.
    """

    target: str
    horizon: str
    entity: str
    origin_instant: datetime
    model_id: str | None = None
    model_family: str | None = None
    notes: str = ""

    @classmethod
    def build(
        cls,
        *,
        target: str,
        horizon: str,
        entity: str,
        origin_instant: Any,
        model_id: str | None = None,
        model_family: str | None = None,
        notes: str = "",
    ) -> "ForecastRequest":
        """Validate while constructing, so an invalid request never exists."""
        for name, value in (("target", target), ("horizon", horizon), ("entity", entity)):
            if not isinstance(value, str) or not value.strip():
                raise HandoffError(
                    f"{name} must be a non-blank string; got {value!r}. A blank target or "
                    "horizon would be resolved against nothing."
                )
        if model_id and model_family:
            raise HandoffError(
                "give either model_id or model_family, not both; naming two selectors makes "
                "it ambiguous which one the caller meant"
            )
        return cls(
            target=target.strip(),
            horizon=horizon.strip(),
            entity=entity.strip(),
            origin_instant=_parse_instant(origin_instant, "origin_instant"),
            model_id=model_id.strip() if isinstance(model_id, str) and model_id.strip() else None,
            model_family=(
                model_family.strip()
                if isinstance(model_family, str) and model_family.strip()
                else None
            ),
            notes=notes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "horizon": self.horizon,
            "entity": self.entity,
            "origin_instant": _iso(self.origin_instant),
            "model_id": self.model_id,
            "model_family": self.model_family,
            "notes": self.notes,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)

    def describe(self) -> str:
        return (
            f"{self.target} @ {self.horizon} for {self.entity} at "
            f"{_iso(self.origin_instant)}"
            + (f" [model {self.model_id or self.model_family}]" if (self.model_id or self.model_family) else "")
        )


# --------------------------------------------------------------------------- #
# The result
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HandoffResult:
    """Phase 5's answer: a forecast value, or a named reason there is not one."""

    status: str
    reason: str | None = None
    model_id: str | None = None
    model_family: str | None = None
    target: str | None = None
    target_units: str | None = None
    horizon: str | None = None
    entity: str | None = None
    prediction: float | None = None
    source_timestamp: str | None = None
    prediction_timestamp: str | None = None
    model_version: str | None = None
    feature_version: str = FEATURE_CONTRACT_VERSION
    feature_count: int | None = None
    uncertainty: Uncertainty = field(default_factory=lambda: unavailable_uncertainty(
        "no forecast was produced, so there is no error to describe"
    ))
    provenance: Mapping[str, Any] | None = None
    artifact_status: str | None = None
    artifact_manifest_version: str = ARTIFACT_MANIFEST_VERSION
    data_status: str = "unknown"
    synthetic_demo: bool = True
    disclaimer: str | None = None
    weight_storage_policy: str = WEIGHT_STORAGE_POLICY
    production_ready_claimed: bool = False
    request: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.status not in HANDOFF_STATUSES:
            raise HandoffError(
                f"unknown handoff status {self.status!r}; known statuses are "
                f"{list(HANDOFF_STATUSES)}"
            )
        if self.status == STATUS_READY:
            if self.prediction is None:
                raise HandoffError(
                    "status 'ready' requires a prediction value; a ready result with no "
                    "prediction is a null forecast wearing a success label"
                )
            if not np.isfinite(self.prediction):
                raise HandoffError(
                    f"prediction must be finite; got {self.prediction!r}"
                )
            for name in ("target", "horizon", "entity", "prediction_timestamp", "source_timestamp"):
                if getattr(self, name) in (None, ""):
                    raise HandoffError(
                        f"status 'ready' requires {name!r}; a forecast without it cannot be "
                        "traced back to the observation it came from"
                    )
        else:
            if self.prediction is not None:
                raise HandoffError(
                    f"status {self.status!r} must not carry a prediction value; returning a "
                    "number alongside 'unavailable' is how a caller ends up using it"
                )
            if not self.reason:
                raise HandoffError(
                    f"status {self.status!r} requires a reason naming the cause; 'unavailable' "
                    "with no explanation is indistinguishable from a bug"
                )

    @property
    def ready(self) -> bool:
        return self.status == STATUS_READY

    @property
    def prediction_datetime(self) -> datetime | None:
        return _parse_instant(self.prediction_timestamp, "prediction_timestamp")

    def to_dict(self) -> dict[str, Any]:
        return {
            "handoff_contract_version": HANDOFF_CONTRACT_VERSION,
            "status": self.status,
            "reason": self.reason,
            "model_id": self.model_id,
            "model_family": self.model_family,
            "target": self.target,
            "target_units": self.target_units,
            "horizon": self.horizon,
            "entity": self.entity,
            "prediction": self.prediction,
            "source_timestamp": self.source_timestamp,
            "prediction_timestamp": self.prediction_timestamp,
            "model_version": self.model_version,
            "feature_version": self.feature_version,
            "feature_count": self.feature_count,
            "uncertainty": self.uncertainty.to_dict(),
            "provenance": dict(self.provenance) if self.provenance else None,
            "artifact_status": self.artifact_status,
            "artifact_manifest_version": self.artifact_manifest_version,
            "data_status": self.data_status,
            "synthetic_demo": self.synthetic_demo,
            "disclaimer": self.disclaimer,
            "weight_storage_policy": self.weight_storage_policy,
            "production_ready_claimed": self.production_ready_claimed,
            "request": dict(self.request) if self.request else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)

    def describe(self) -> str:
        head = f"{self.status.upper()}"
        if self.model_id:
            head += f" {self.model_id}"
        if self.ready:
            head += (
                f" -> {self.target} [{self.target_units or 'unit unknown'}] = "
                f"{self.prediction:.6g} at {self.prediction_timestamp}"
            )
        lines = [head, f"  {self.uncertainty.describe()}"]
        if self.reason:
            lines.insert(1, f"  reason: {self.reason}")
        if self.disclaimer:
            lines.append(f"  disclaimer: {self.disclaimer}")
        return "\n".join(lines)


def invalid_request(request: Any, reason: str) -> HandoffResult:
    """A well-formed refusal for a malformed request."""
    return HandoffResult(
        status=STATUS_INVALID_REQUEST,
        reason=reason,
        target=getattr(request, "target", None),
        horizon=getattr(request, "horizon", None),
        entity=getattr(request, "entity", None),
        request=request.to_dict() if isinstance(request, ForecastRequest) else None,
    )


# --------------------------------------------------------------------------- #
# Building a handoff from a training run
# --------------------------------------------------------------------------- #


def horizon_seconds(horizon: str) -> float | None:
    """Parse Phase 3's horizon label into seconds, or `None` if it is not one.

    Phase 3 emits labels like `6h`. Anything else is left as `None` rather than
    guessed at: a horizon this function cannot read must not silently become zero,
    which would put the prediction timestamp on top of the source timestamp.

    **Public because Phase 5 needs it without a training run.** Serving a forecast
    from a loaded artifact has no `RunResult` to hand to `_prediction_instant`, so
    without this the prediction timestamp could only be produced as a side effect
    of the Phase 4 handoff — meaning a deployment that loads artifacts from disk
    would withhold the timestamp for a reason that has nothing to do with the
    forecast. One parser, exported, rather than one parser plus a copy.

    A non-positive span is `None`, not a negative number of seconds. `-6h` parses
    arithmetically, and accepting it puts the prediction timestamp *before* the
    origin — a forecast for the past, stamped as though it were a forecast. That
    reads as a correct answer to anyone who checks only that a timestamp exists, and
    it is worse than the unparseable-label case the `None` above is there for.
    """
    text = str(horizon).strip().lower()
    if not text:
        return None
    try:
        if text.endswith("h"):
            seconds = float(text[:-1]) * 3600.0
        elif text.endswith("m"):
            seconds = float(text[:-1]) * 60.0
        elif text.endswith("s"):
            seconds = float(text[:-1])
        elif text.endswith("d"):
            seconds = float(text[:-1]) * 86400.0
        else:
            return None
    except ValueError:
        return None
    return seconds if seconds > 0.0 else None


def _prediction_instant(request: ForecastRequest) -> tuple[str | None, str | None]:
    """`(source_timestamp, prediction_timestamp)` for a request.

    Returns `(None, None)` when the horizon label is unreadable, because a
    prediction timestamp computed from a guess would be worse than no timestamp at
    all — it would look traceable.
    """
    seconds = horizon_seconds(request.horizon)
    if seconds is None:
        return _iso(request.origin_instant), None
    return _iso(request.origin_instant), _iso(
        request.origin_instant + timedelta(seconds=seconds)
    )


def _select_run(result: RunResult, request: ForecastRequest) -> Any:
    """The run serving this request, or `None`.

    Selection is exact: `model_id` wins when given, otherwise the single run of the
    requested family. A run for a different target or horizon is not a fallback —
    it is a different forecast, and quietly serving it would make the result's
    `target` field a lie.
    """
    if request.model_id:
        try:
            candidate = result.run_for(request.model_id)
        except KeyError:
            return None
        return candidate
    matches = [
        run
        for run in result.runs
        if run.model_family == request.model_family and run.target == request.target
    ]
    return matches[0] if len(matches) == 1 else None


def build_handoff(
    request: ForecastRequest,
    result: RunResult,
    *,
    manifests: ArtifactManifests | None = None,
    prediction: float | None = None,
    uncertainty: Uncertainty | None = None,
    y_true: Sequence[float] | None = None,
    y_pred: Sequence[float] | None = None,
    evaluation_split: str = "validation",
) -> HandoffResult:
    """Answer one request from one training run.

    `prediction` is the caller-supplied forecast value. Phase 4 trained and scored
    models; producing a forecast for an arbitrary future instant is Phase 5's job
    and needs the Phase 3 feature vector for that instant, which is not something
    this module can conjure. So when no prediction is supplied the result says
    `no_prediction` with that reason rather than inventing one.

    `uncertainty` may be passed directly, or `y_true`/`y_pred` may be supplied and
    the residual spread computed from them. With neither, uncertainty is explicitly
    unavailable.
    """
    source_timestamp, prediction_timestamp = _prediction_instant(request)
    common: dict[str, Any] = {
        "target": request.target,
        "horizon": request.horizon,
        "entity": request.entity,
        "source_timestamp": source_timestamp,
        "feature_version": FEATURE_CONTRACT_VERSION,
        "data_status": result.data_status,
        "synthetic_demo": result.is_synthetic,
        "disclaimer": result.disclaimer,
        "request": request.to_dict(),
    }
    # `prediction_timestamp` is deliberately NOT in `common`. It describes an instant a
    # prediction is *about*, and it is derivable from the request alone - so putting it
    # on a refusal would attach a well-formed instant to a result that has no value,
    # and a reader scanning timestamps rather than statuses would see a forecast that
    # does not exist. Only the `ready` branch fills it in; every other status leaves it
    # null. `source_timestamp` stays on all of them, because the origin instant was
    # read and it describes the request rather than an answer.

    run = _select_run(result, request)
    if run is None:
        available = sorted({f"{r.model_family}:{r.target}" for r in result.runs})
        return HandoffResult(
            status=STATUS_MODEL_UNAVAILABLE,
            reason=(
                f"no trained model in this run serves target {request.target!r} at horizon "
                f"{request.horizon!r} for the requested selector "
                f"(model_id={request.model_id!r}, model_family={request.model_family!r}); "
                f"models available: {available or '(none)'}"
            ),
            **common,
        )

    # The run's own target and horizon are authoritative. If either disagrees with the
    # request, the disagreement is reported rather than resolved in either direction.
    # `common` already carries the *requested* target and horizon, which is what the
    # caller asked for and what belongs on the response; the model's own are named in
    # the reason, because naming them in the fields would silently answer a different
    # question than the one that was asked.
    #
    # The horizon matters as much as the target here. A six-hour model asked for a
    # 24-hour forecast would otherwise return `ready` with the value stamped 24 hours
    # out - a plausible number about the wrong instant, which is harder to catch than
    # an outright refusal and is the failure this guard exists to prevent.
    if run.target != request.target or run.horizon != request.horizon:
        return HandoffResult(
            status=STATUS_INVALID_REQUEST,
            reason=(
                f"requested {request.target!r} at horizon {request.horizon!r} but model "
                f"{run.model_id!r} was trained on {run.target!r} at horizon {run.horizon!r}; "
                "Phase 4 does not substitute a target or extend a horizon"
            ),
            model_id=run.model_id,
            model_family=run.model_family,
            target_units=run.target_units,
            **common,
        )

    common["model_id"] = run.model_id
    common["model_family"] = run.model_family
    common["target_units"] = run.target_units
    common["feature_count"] = len(run.feature_names)
    if run.provenance is not None:
        # `ProvenanceRecord` has no feature-contract field, so the version is added
        # alongside it under an explicit key rather than squeezed into an existing
        # one. A reader can tell which came from the provenance record and which
        # Phase 4 supplied.
        common["provenance"] = {
            **run.provenance.to_dict(),
            "model_contract_version": MODEL_CONTRACT_VERSION,
            "feature_contract_version": FEATURE_CONTRACT_VERSION,
        }
        common["model_version"] = run.provenance.model_version

    if run.status != STATUS_TRAINED:
        return HandoffResult(
            status=_handoff_status_for(run.status),
            reason=run.reason or f"model {run.model_id!r} is in state {run.status!r}",
            artifact_status=run.artifact_status,
            **common,
        )

    manifest = _manifest_for(manifests, run.model_id)
    if manifest is None or manifest.artifact_status == ARTIFACT_STATUS_NOT_WRITTEN:
        return HandoffResult(
            status=STATUS_ARTIFACT_UNAVAILABLE,
            reason=(
                f"model {run.model_id!r} trained but has no stored artifact "
                f"(artifact_status="
                f"{manifest.artifact_status if manifest is not None else 'absent'}); Phase 5 "
                "cannot serve a forecast from a model whose weights were never written"
            ),
            artifact_status=(
                manifest.artifact_status if manifest is not None else ARTIFACT_STATUS_NOT_WRITTEN
            ),
            **common,
        )

    if prediction is None:
        return HandoffResult(
            status=STATUS_NO_PREDICTION,
            reason=(
                "no forecast value was supplied for this request. Phase 4 trains and scores; "
                "generating a value for an arbitrary future instant is Phase 5's job and "
                "requires the Phase 3 feature vector at that instant"
            ),
            artifact_status=manifest.artifact_status,
            **common,
        )

    if uncertainty is None:
        if y_true is not None and y_pred is not None:
            uncertainty = residual_sigma_from(
                y_true,
                y_pred,
                unit=run.target_units,
                source=f"{run.model_id} residuals on {evaluation_split}",
            )
        else:
            uncertainty = unavailable_uncertainty(
                "no observed/predicted pairs were supplied for this request, and Phase 4 does "
                "not estimate an error bound from a model it cannot evaluate here"
            )

    if prediction_timestamp is None:
        return HandoffResult(
            status=STATUS_INVALID_REQUEST,
            reason=(
                f"horizon {request.horizon!r} is not a readable Phase 3 horizon label (expected "
                "something like '6h'), so the prediction instant cannot be stated; the value "
                "was withheld rather than stamped with a guessed timestamp"
            ),
            artifact_status=manifest.artifact_status,
            **common,
        )

    return HandoffResult(
        status=STATUS_READY,
        reason=None,
        prediction=float(prediction),
        # The one place a prediction timestamp is stated, because it is the only
        # status that has a prediction for the instant to be about.
        prediction_timestamp=prediction_timestamp,
        uncertainty=uncertainty,
        artifact_status=manifest.artifact_status,
        **common,
    )


def _handoff_status_for(training_status: str) -> str:
    """Map a training status onto the handoff vocabulary Phase 5 switches on."""
    mapping = {
        STATUS_DEPENDENCY_UNAVAILABLE: STATUS_DEPENDENCY_UNAVAILABLE,
        STATUS_INSUFFICIENT_DATA: STATUS_INSUFFICIENT_DATA,
        STATUS_TARGET_UNAVAILABLE: STATUS_TARGET_UNAVAILABLE,
    }
    return mapping.get(training_status, STATUS_MODEL_UNAVAILABLE)


def _manifest_for(
    manifests: ArtifactManifests | None, model_id: str
) -> ArtifactManifest | None:
    if manifests is None:
        return None
    for manifest in manifests.manifests:
        if manifest.model_id == model_id:
            return manifest
    return None


# --------------------------------------------------------------------------- #
# Conversion to the existing forecast contract
# --------------------------------------------------------------------------- #


def to_forecast_output(
    result: HandoffResult,
    *,
    forecast_id: str,
    forecast_timestamp: str | None = None,
) -> ForecastOutput:
    """Convert a handoff result into the existing `contract.ForecastOutput`.

    Reuse, not replacement: `ForecastOutput` is what the downstream platform
    already reads and what `ForecastSyncService` already stores, so defining a
    parallel shape here would be the duplication this module is written to avoid.

    Only `ready` results become a forecast. Anything else becomes
    `status="failed"` with `predicted_value=None` and the reason carried in
    `provenance_reference`, because the running contract has no vocabulary for
    "unavailable" and inventing one is not this module's call to make.
    """
    if not result.ready:
        return ForecastOutput(
            forecast_id=forecast_id,
            forecast_timestamp=forecast_timestamp or result.prediction_timestamp or "",
            forecast_horizon=result.horizon or "",
            model_id=result.model_id or "unknown",
            model_version=result.model_version or "unknown",
            status="failed",
            station_reference=result.entity,
            target=result.target,
            target_units=result.target_units,
            predicted_value=None,
            provenance_reference=result.reason,
            evaluation_metrics=None,
            disclaimer=result.disclaimer,
        )
    return ForecastOutput(
        forecast_id=forecast_id,
        forecast_timestamp=forecast_timestamp or result.prediction_timestamp or "",
        forecast_horizon=result.horizon or "",
        model_id=result.model_id or "unknown",
        model_version=result.model_version or "unknown",
        status="completed",
        station_reference=result.entity,
        target=result.target,
        target_units=result.target_units,
        predicted_value=result.prediction,
        residual_sigma=result.uncertainty.value,
        provenance_reference=None,
        evaluation_metrics=None,
        disclaimer=result.disclaimer,
    )


def handoff_contract_description() -> dict[str, Any]:
    """A machine-readable description of what this contract promises.

    Documentation that lives in code drifts from documentation that lives in a
    Markdown file; this is the version Phase 5, the docs and the tests all read.
    """
    return {
        "handoff_contract_version": HANDOFF_CONTRACT_VERSION,
        "downstream_forecast_contract_version": FORECAST_CONTRACT_VERSION,
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "request_fields": (
            "target",
            "horizon",
            "entity",
            "origin_instant",
            "model_id",
            "model_family",
        ),
        "result_fields": (
            "status",
            "reason",
            "model_id",
            "model_family",
            "target",
            "target_units",
            "horizon",
            "entity",
            "prediction",
            "source_timestamp",
            "prediction_timestamp",
            "model_version",
            "feature_version",
            "feature_count",
            "uncertainty",
            "provenance",
            "artifact_status",
            "data_status",
            "synthetic_demo",
            "disclaimer",
        ),
        "statuses": list(HANDOFF_STATUSES),
        "uncertainty_statuses": list(UNCERTAINTY_STATUSES),
        "uncertainty_policy": (
            "uncertainty.value is populated only by residual_sigma_from(), which computes the "
            "standard deviation of observed-minus-predicted pairs the caller supplies. No "
            "prediction interval is produced by this module, and uncertainty that cannot be "
            "measured is reported with value=None and a reason."
        ),
        "weight_storage_policy": WEIGHT_STORAGE_POLICY,
        "integration_statement": INTEGRATION_STATEMENT,
        "scope": (
            "contract only: this module defines no HTTP route, no handler and no persistence. "
            "Forecast generation and the API surface are Phase 5"
        ),
    }


__all__ = [
    "HANDOFF_CONTRACT_VERSION",
    "HANDOFF_STATUSES",
    "RESIDUAL_SIGMA_CAVEAT",
    "STATUS_ARTIFACT_UNAVAILABLE",
    "STATUS_DEPENDENCY_UNAVAILABLE",
    "STATUS_INSUFFICIENT_DATA",
    "STATUS_INVALID_REQUEST",
    "STATUS_MODEL_UNAVAILABLE",
    "STATUS_NO_PREDICTION",
    "STATUS_READY",
    "STATUS_TARGET_UNAVAILABLE",
    "UNAVAILABLE_STATUSES",
    "UNCERTAINTY_RESIDUAL_SIGMA",
    "UNCERTAINTY_STATUSES",
    "UNCERTAINTY_UNAVAILABLE",
    "ForecastRequest",
    "HandoffError",
    "HandoffResult",
    "Uncertainty",
    "build_handoff",
    "handoff_contract_description",
    "horizon_seconds",
    "invalid_request",
    "residual_sigma_from",
    "to_forecast_output",
    "unavailable_uncertainty",
]