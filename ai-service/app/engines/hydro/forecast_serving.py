# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""The serving boundary: one request in, one forecast or one named refusal out.

This module sequences the five steps Phase 5 performs per request and stops at the
first one that fails:

    resolve artifact -> check contract -> validate input -> infer -> hand off

It exists as its own module because the ordering *is* the design. Every one of those
steps can refuse, and the ordering decides which refusal a caller sees. Resolving
the artifact first means a dependency-blocked family reports
`dependency_unavailable` rather than complaining that a feature vector was missing
for a model that will never run. Validating the input before inferring means a
mis-ordered vector never reaches a model.

**Nothing here is an HTTP layer.** There is no route, no handler, no
serialization, no persistence. The boundary this module defines is a function
signature; who calls it and how is a deployment decision that belongs to whoever
owns the service layer. Naming that here is what stops a "serving" module from
growing a framework around it.

**Two structured results, and why.** `ServedForecast` is Phase 5's own answer: it
works from a loaded artifact alone, which is what a deployment has. When a
`RunResult` from training happens to be in scope, the same prediction is *also*
expressed as Phase 4's `HandoffResult` and then as the platform's existing
`contract.ForecastOutput`, so the existing consumers read it without a second
format. Neither of those is required, and neither is faked when absent.

**A refusal carries the reason.** Every non-ready status names the cause, and
`prediction` is null on all of them. There is no code path that returns a value
alongside a failure, because a caller that checks the status is not the only reader
and the one who reads only the number is exactly the one this pipeline would
mislead.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from .contract import FORECAST_CONTRACT_VERSION, ForecastOutput
from .forecast_artifact import (
    ARTIFACT_STATES,
    FORECAST_ARTIFACT_VERSION,
    ArtifactContractMismatchError,
    ArtifactFamilyMismatchError,
    ArtifactHorizonMismatchError,
    ArtifactMissingError,
    ArtifactPreprocessingMismatchError,
    ArtifactStore,
    ArtifactTargetMismatchError,
    DependencyBlockedError,
    ForecastArtifact,
    ForecastArtifactError,
    handoff_status_for_state,
)
from .forecast_inference import (
    CausalityError,
    EntityMismatchError,
    EstimatorUnavailableError,
    FeatureOrderError,
    FeatureTypeError,
    ForecastInference,
    ForecastInferenceError,
    ForecastInput,
    MissingFeatureError,
    NoTargetObservationError,
    NonFiniteFeatureError,
    UnexpectedFeatureError,
    predict,
)
from .forecast_selection import (
    SelectionDecision,
    candidates_from_artifacts,
    select_model,
)
from .model_handoff import (
    HANDOFF_CONTRACT_VERSION,
    HANDOFF_STATUSES,
    STATUS_ARTIFACT_UNAVAILABLE,
    STATUS_DEPENDENCY_UNAVAILABLE,
    STATUS_INSUFFICIENT_DATA,
    STATUS_INVALID_REQUEST,
    STATUS_MODEL_UNAVAILABLE,
    STATUS_READY,
    ForecastRequest,
    HandoffResult,
    build_handoff,
    horizon_seconds,
    to_forecast_output,
)
from .provenance import SYNTHETIC_DATA_DISCLAIMER

#: Bumped when the serving layout changes incompatibly.
SERVING_CONTRACT_VERSION = "navya-phase5-serving/v1"

#: Statuses a served forecast may carry. Phase 4's handoff vocabulary, unchanged -
#: this module has no second set of words for "why there is no value".
SERVING_STATUSES: tuple[str, ...] = HANDOFF_STATUSES

#: Statuses that mean "no forecast value was produced", as opposed to `ready`.
UNAVAILABLE_STATUSES: frozenset[str] = frozenset(
    status for status in SERVING_STATUSES if status != STATUS_READY
)


class ForecastServiceError(ValueError):
    """The serving boundary could not be configured at all."""


# --------------------------------------------------------------------------- #
# Error to status
# --------------------------------------------------------------------------- #

#: Which handoff status each inference failure maps onto. Total by construction:
#: the tests walk every `ForecastInferenceError` subclass and assert it appears
#: here, so a new error cannot be added without deciding what a caller sees.
_STATUS_FOR_ERROR: tuple[tuple[type[Exception], str], ...] = (
    # The model is installed-but-unusable, as opposed to absent. Checked first because
    # the remedy is completely different: install the library, do not go looking for a
    # manifest that is already on disk.
    (DependencyBlockedError, STATUS_DEPENDENCY_UNAVAILABLE),
    # No artifact, or no weights to run it with. Both mean the same thing to a
    # caller: there is no servable model here.
    (ArtifactMissingError, STATUS_ARTIFACT_UNAVAILABLE),
    (EstimatorUnavailableError, STATUS_ARTIFACT_UNAVAILABLE),
    # The baseline had nothing to carry forward. That is a data-availability fact,
    # not a malformed request.
    (NoTargetObservationError, STATUS_INSUFFICIENT_DATA),
    # Everything else is the caller's input disagreeing with the contract, and the
    # reason string carries exactly which part.
    (ArtifactTargetMismatchError, STATUS_INVALID_REQUEST),
    (ArtifactHorizonMismatchError, STATUS_INVALID_REQUEST),
    (ArtifactFamilyMismatchError, STATUS_INVALID_REQUEST),
    (ArtifactContractMismatchError, STATUS_INVALID_REQUEST),
    (ArtifactPreprocessingMismatchError, STATUS_INVALID_REQUEST),
    (FeatureOrderError, STATUS_INVALID_REQUEST),
    (MissingFeatureError, STATUS_INVALID_REQUEST),
    (UnexpectedFeatureError, STATUS_INVALID_REQUEST),
    (FeatureTypeError, STATUS_INVALID_REQUEST),
    (NonFiniteFeatureError, STATUS_INVALID_REQUEST),
    (CausalityError, STATUS_INVALID_REQUEST),
    (EntityMismatchError, STATUS_INVALID_REQUEST),
    (ForecastInferenceError, STATUS_INVALID_REQUEST),
    (ForecastArtifactError, STATUS_INVALID_REQUEST),
)


def status_for_error(error: Exception) -> str:
    """The handoff status a failure maps onto, by walking a fixed table.

    Order matters and follows specificity. `MissingFeatureError` is a subclass of
    `InputValidationError` which is a subclass of `ForecastInferenceError`, so the
    general entry has to come last or every specific one would be unreachable. The
    table is a tuple for that reason rather than a dict keyed by class.
    """
    for error_type, status in _STATUS_FOR_ERROR:
        if isinstance(error, error_type):
            return status
    raise ForecastServiceError(
        f"no serving status is defined for {type(error).__name__}: {error}. Add it to the mapping "
        "table deliberately rather than letting an unmapped failure fall through to a default."
    )


# --------------------------------------------------------------------------- #
# The result
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ServedForecast:
    """What Phase 5 answered, whether or not there was a value.

    `prediction` is null on every status other than `ready`, and that is enforced in
    `__post_init__` rather than left to discipline. A caller who reads the number
    without reading the status gets `None`, which is at least visibly wrong, rather
    than a stale or borrowed value that looks plausible.
    """

    request: ForecastRequest
    status: str
    reason: str | None = None
    inference: ForecastInference | None = None
    handoff: HandoffResult | None = None
    output: ForecastOutput | None = None
    selection: SelectionDecision | None = None
    artifact: ForecastArtifact | None = None
    artifact_id: str | None = None
    state: str | None = None
    forecast_id: str | None = None

    def __post_init__(self) -> None:
        if self.status not in SERVING_STATUSES:
            raise ForecastServiceError(
                f"unknown serving status {self.status!r}; known statuses are "
                f"{list(SERVING_STATUSES)}"
            )
        if self.status == STATUS_READY and self.inference is None:
            raise ForecastServiceError(
                "a ready forecast must carry the inference that produced it; a ready status with no "
                "value is a claim with nothing behind it"
            )
        if self.status != STATUS_READY and self.inference is not None:
            raise ForecastServiceError(
                f"status {self.status!r} must carry prediction=None; a refusal that also returns a "
                "value is how a caller ends up serving the wrong number with the right error code"
            )

    @property
    def ready(self) -> bool:
        return self.status == STATUS_READY

    @property
    def prediction(self) -> float | None:
        return self.inference.prediction if self.inference is not None else None

    @property
    def prediction_timestamp(self) -> str | None:
        """The instant the value is about, or `None` on every non-ready status.

        Withheld rather than filled in, for the same reason Phase 4 withholds it: a
        well-formed timestamp beside no value reads as a forecast that does not
        exist.
        """
        return self.inference.prediction_timestamp if self.inference is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "serving_contract_version": SERVING_CONTRACT_VERSION,
            "forecast_id": self.forecast_id,
            "request": self.request.to_dict(),
            "status": self.status,
            "reason": self.reason,
            "state": self.state,
            "artifact_id": self.artifact_id,
            "selection": self.selection.to_dict() if self.selection else None,
            "prediction": self.prediction,
            "prediction_timestamp": self.prediction_timestamp,
            "forecast": self.inference.to_dict() if self.inference else None,
            "handoff": self.handoff.to_dict() if self.handoff else None,
            "forecast_output": self.output.to_dict() if self.output else None,
        }

    def describe(self) -> str:
        lines = [f"Served forecast [{self.status}]"]
        lines.append(f"  request         : {self.request.describe()}")
        if self.state:
            lines.append(f"  artifact state  : {self.state}")
        if self.artifact_id:
            lines.append(f"  artifact        : {self.artifact_id}")
        if self.selection is not None:
            lines.append(
                f"  selection       : {self.selection.selected_model_id or 'none'} on "
                f"{self.selection.metric}/{self.selection.split}"
                f" ({self.selection.direction} is better)"
            )
        if self.inference is not None:
            for line in self.inference.describe().splitlines():
                lines.append("  " + line.strip())
        elif self.artifact is not None:
            # A refusal still names a model, and a model still has a data status. The
            # reader who opens a refusal is usually trying to work out what the
            # deployment is running - which is the wrong moment to discover that the
            # synthetic-data warning only appears once a forecast exists.
            lines.append(
                f"  data status     : {self.artifact.data_status} "
                f"(synthetic={self.artifact.synthetic_demo})"
            )
            if self.artifact.synthetic_demo and self.artifact.disclaimer:
                lines.append(f"  disclaimer      : {self.artifact.disclaimer}")
        if self.handoff is not None:
            lines.append(f"  phase 4 handoff : {self.handoff.status}")
        if self.output is not None:
            lines.append(
                f"  platform output : {self.output.status} "
                f"(contract {self.output.contract_version})"
            )
        if self.reason:
            lines.append(f"  reason          : {self.reason}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Serving
# --------------------------------------------------------------------------- #


def _resolver_for(
    store: ArtifactStore,
    estimators: Mapping[str, Any] | None,
    model_id: str,
) -> Any:
    """The fitted estimator for `model_id`, or `None` so `predict` refuses properly.

    Returning `None` rather than raising keeps the refusal in one place - the
    inference layer's `EstimatorUnavailableError`, whose message explains the
    weight-storage policy. Raising here would mean two different explanations for
    the same fact.
    """
    if estimators is None:
        return None
    return estimators.get(model_id)


def _build_selection(
    store: ArtifactStore,
    request: ForecastRequest,
    *,
    selection_metric: str,
    selection_split: str,
    baseline_family: str | None,
) -> SelectionDecision:
    candidates = candidates_from_artifacts(
        store.artifacts, target=request.target, horizon=request.horizon
    )
    return select_model(
        candidates,
        metric=selection_metric,
        split=selection_split,
        baseline_family=baseline_family,
    )


def _no_selection_reason(
    store: ArtifactStore, request: ForecastRequest, decision: SelectionDecision
) -> str:
    """Explain an empty candidate set in terms of what the store *does* hold.

    "no eligible candidates" is true and useless on its own. A store holding three
    artifacts, all trained at `6h`, being asked for `24h` is a different problem
    from an empty store, and the two need different actions - train a longer-horizon
    model, versus point the deployment at the right artifact directory. So the
    inventory is reported alongside the refusal.
    """
    if not store.artifacts:
        return (
            f"no model could be selected for this request. {decision.reason} This store is empty: "
            "it holds no artifacts at all, so the deployment is pointing at a directory with no "
            "manifests in it, rather than at a set of models for the wrong target."
        )
    others = sorted(
        {
            (artifact.target, artifact.horizon, artifact.state)
            for artifact in store.artifacts
            if artifact.target != request.target or artifact.horizon != request.horizon
        }
    )
    inventory = (
        f" This store holds {len(store.artifacts)} artifact(s); none was trained on "
        f"{request.target!r} at {request.horizon!r}. What it does hold: "
        + ", ".join(f"{target} @ {horizon} ({state})" for target, horizon, state in others)
        if others
        else f" All {len(store.artifacts)} of them are for {request.target!r} at "
        f"{request.horizon!r}, and every one was rejected above."
    )
    return f"no model could be selected for this request. {decision.reason}{inventory}"


def _resolve_by_family(
    store: ArtifactStore, request: ForecastRequest
) -> tuple[ForecastArtifact | None, str | None]:
    """`(artifact, refusal)` for a request that named a family instead of a model.

    Phase 4's request contract offers `model_family` as a selector and its handoff
    honours it, so honouring it here is not a new feature - it is the same contract
    behaving consistently across the two layers that implement it.

    Zero matches and several matches are both refusals rather than a choice. Picking
    one of several would make the answer depend on artifact ordering, and the caller
    would have no way to tell which model answered; picking one of zero would mean
    inventing a model. Both messages list what is there, so the repair is obvious.
    """
    family = request.model_family
    matching = [
        artifact
        for artifact in store.for_target_horizon(request.target, request.horizon)
        if artifact.model_family == family
    ]
    if len(matching) == 1:
        return matching[0], None
    if not matching:
        held = sorted(
            {
                (artifact.target, artifact.horizon, artifact.model_family)
                for artifact in store.artifacts
            }
        )
        return None, (
            f"this store holds no artifact of family {family!r} for {request.target!r} at "
            f"{request.horizon!r}. Phase 5 does not serve a different family than the one "
            "requested. What it holds: "
            + (
                ", ".join(f"{t} @ {h} ({f})" for t, h, f in held)
                if held
                else "(nothing)"
            )
        )
    return None, (
        f"{len(matching)} artifacts of family {family!r} match {request.target!r} at "
        f"{request.horizon!r} ({', '.join(sorted(a.model_id for a in matching))}), so naming the "
        "family does not identify one. Phase 5 will not choose between them on ordering - name "
        "the model_id instead"
    )


def _resolved_request(request: ForecastRequest, artifact: ForecastArtifact) -> ForecastRequest:
    """The request as Phase 4's handoff should see it, naming the resolved model.

    Phase 4's `build_handoff` resolves a run by `model_id`, or by a family that
    matches exactly one run. A Phase 5 request usually names neither, because Phase
    5 is the layer that decides which model answers - and by then it knows. Handing
    Phase 4 the original anonymous request would produce `model_unavailable` beside
    a perfectly good number, which is worse than either being right or wrong.

    So the resolved request names the model that actually ran. That is not a
    re-interpretation of what was asked for: it is the same request with the
    decision Phase 5 already made written down.

    Only `model_id` is passed, never the family as well, because Phase 4's
    `ForecastRequest.build` treats naming two selectors as ambiguous - a reasonable
    rule, and one this module respects rather than works around.
    """
    if request.model_id == artifact.model_id:
        return request
    return ForecastRequest.build(
        target=request.target,
        horizon=request.horizon,
        entity=request.entity,
        origin_instant=request.origin_instant,
        model_id=artifact.model_id,
        notes=request.notes,
    )


def prediction_timestamp_for(horizon: str, origin_instant: datetime) -> str | None:
    """The instant a forecast of `horizon` from `origin_instant` is about, or `None`.

    `None` for an unreadable horizon label, for Phase 4's reason restated here
    because the consequence is now Phase 5's: a timestamp guessed from a label this
    code cannot parse would be wrong in a way that looks traceable. The origin must
    be aware; the shift is applied in UTC.
    """
    seconds = horizon_seconds(horizon)
    if seconds is None:
        return None
    instant = origin_instant.astimezone(timezone.utc) + timedelta(seconds=seconds)
    return instant.isoformat().replace("+00:00", "Z")


def _refusal(
    request: ForecastRequest,
    status: str,
    reason: str,
    *,
    artifact: ForecastArtifact | None = None,
    selection: SelectionDecision | None = None,
    forecast_id: str | None = None,
) -> ServedForecast:
    """A refusal, with the same identity a success would have had.

    The forecast id is derived even when there is no forecast. A log line that only
    records failures without a way to tell them apart leaves an operator comparing
    "no model could be selected" messages from three different requests, and the
    request that caused each is not in the line because the caller did not know the
    id in advance.
    """
    return ServedForecast(
        request=request,
        status=status,
        reason=reason,
        artifact=artifact,
        artifact_id=(artifact.artifact_id or artifact.model_id) if artifact else None,
        state=artifact.state if artifact else None,
        selection=selection,
        forecast_id=forecast_id or default_forecast_id(request),
    )


def serve(
    request: ForecastRequest,
    *,
    store: ArtifactStore,
    data: ForecastInput | None = None,
    estimators: Mapping[str, Any] | None = None,
    run_result: Any = None,
    manifests: Any = None,
    selection_metric: str = "rmse",
    selection_split: str = "validation",
    baseline_family: str | None = "naive",
    forecast_id: str | None = None,
) -> ServedForecast:
    """Answer one request, or refuse it by name.

    `data` is the feature vector, and it is required for any family whose prediction
    rule needs features. The persistence baseline does not read features at all -
    its prediction is the last observed target value - so `data=None` is accepted
    for it and refused for everything else. That is not a special case bolted on:
    it falls out of the artifact's `uses_trained_parameters` flag.

    `estimators` maps `model_id` to an already-fitted estimator. Phase 4's weight
    policy keeps those bytes out of the repository, so they are the caller's to
    resolve; an absent entry produces `artifact_unavailable` with an explanation
    rather than a fallback model.
    """
    # 1. Resolve the artifact. Three selectors, in the order of how precisely they
    #    name a model: an explicit `model_id`, an explicit `model_family`, or neither -
    #    in which case Phase 5 chooses, from validated metrics alone. An explicit
    #    selector is never overridden by selection: a caller who asked for a family is
    #    entitled to that family, and quietly substituting a better-scoring one would
    #    make the served model unnameable in the caller's own logs.
    if request.model_id:
        try:
            artifact = store.require(request.model_id)
        except ArtifactMissingError as exc:
            return _refusal(
                request,
                STATUS_ARTIFACT_UNAVAILABLE,
                f"{exc}",
                forecast_id=forecast_id,
            )
        decision = None
    elif request.model_family:
        artifact, refusal = _resolve_by_family(store, request)
        if refusal is not None:
            return _refusal(
                request, STATUS_ARTIFACT_UNAVAILABLE, refusal, forecast_id=forecast_id
            )
        decision = None
    else:
        decision = _build_selection(
            store,
            request,
            selection_metric=selection_metric,
            selection_split=selection_split,
            baseline_family=baseline_family,
        )
        if decision.selected is None:
            return _refusal(
                request,
                STATUS_MODEL_UNAVAILABLE,
                _no_selection_reason(store, request, decision),
                selection=decision,
                forecast_id=forecast_id,
            )
        artifact = decision.selected.artifact

    # 2. Check the contract. A model that cannot serve this target/horizon is a
    #    refused request, not a substitute.
    try:
        artifact.check_family(request.model_family)
        artifact.check_target(request.target)
        artifact.check_horizon(request.horizon)
        artifact.require_servable()
    except ForecastArtifactError as exc:
        return _refusal(
            request,
            status_for_error(exc),
            str(exc),
            artifact=artifact,
            forecast_id=forecast_id,
        )

    # 3. Validate the input, or discover that none is needed.
    if data is None:
        if artifact.uses_trained_parameters:
            return _refusal(
                request,
                STATUS_INVALID_REQUEST,
                (
                    f"model {artifact.model_id!r} is family {artifact.model_family!r}, whose "
                    f"prediction needs its {artifact.feature_count} feature(s), and no feature "
                    "vector was supplied. Phase 5 does not fetch or rebuild one implicitly: the "
                    "features for an instant are Phase 3's contract, and this request named no "
                    "instant to build them for."
                ),
                artifact=artifact,
                selection=decision,
                forecast_id=forecast_id,
            )
        return _refusal(
            request,
            STATUS_INVALID_REQUEST,
            (
                f"model {artifact.model_id!r} is the persistence baseline, which reads target "
                "history rather than features, but no target history was supplied; the baseline "
                "needs at least one observation at or before the origin"
            ),
            artifact=artifact,
            selection=decision,
            forecast_id=forecast_id,
        )

    # 4. Infer. Every failure below is a named refusal, not an exception to the caller.
    try:
        inference = predict(
            artifact,
            data,
            estimator=_resolver_for(store, estimators, artifact.model_id),
            request=request,
        )
    except (ForecastInferenceError, ForecastArtifactError) as exc:
        return _refusal(
            request,
            status_for_error(exc),
            str(exc),
            artifact=artifact,
            selection=decision,
            forecast_id=forecast_id,
        )

    # 5. Express the same answer in the two contracts that already exist.
    handoff, prediction_timestamp, output = _enrich(
        request, inference, artifact, run_result=run_result, manifests=manifests
    )

    return ServedForecast(
        request=request,
        status=STATUS_READY,
        reason=None,
        inference=replace(inference, prediction_timestamp=prediction_timestamp),
        handoff=handoff,
        output=output,
        selection=decision,
        artifact=artifact,
        artifact_id=artifact.artifact_id or artifact.model_id,
        state=artifact.state,
        forecast_id=forecast_id or default_forecast_id(request),
    )


def _enrich(
    request: ForecastRequest,
    inference: ForecastInference,
    artifact: ForecastArtifact,
    *,
    run_result: Any,
    manifests: Any,
) -> tuple[HandoffResult | None, str | None, ForecastOutput | None]:
    """Phase 4's handoff and the platform's forecast output, when a `RunResult` exists.

    Returns `(handoff, prediction_timestamp, output)`. The timestamp comes back
    from the handoff rather than being recomputed here: Phase 4 already owns the
    horizon-label parsing, and a second parser in this module is a second thing that
    can disagree about what `6h` means. For the same reason the handoff is handed
    the *resolved* request - see `_resolved_request`.

    `manifests` is optional and, when given, is what Phase 4 uses to report the
    artifact status. Phase 5 does not synthesise one: the manifest bundle is
    Phase 4's artifact of record, and inventing a substitute would put a second,
    unreviewed description of the same model into the result.

    With no `RunResult` there is still a timestamp, computed through Phase 4's own
    exported `horizon_seconds`. Withholding it because no training run happened to
    be in scope would make the timestamp a function of the caller's context rather
    than of the request, which is worse than either always or never.
    """
    if run_result is None:
        return None, prediction_timestamp_for(request.horizon, inference.origin_instant), None
    resolved = _resolved_request(request, artifact)
    handoff = build_handoff(
        resolved,
        run_result,
        manifests=manifests,
        prediction=inference.prediction,
        uncertainty=inference.uncertainty,
    )
    if handoff.status != STATUS_READY:
        # The value exists but Phase 4's contract refuses to stamp it - most likely
        # an unreadable horizon label. The refusal is reported rather than papered
        # over, and the caller sees `ready` here with no timestamp, which is the
        # honest combination: there is a value, and there is no instant to say it
        # is about.
        return handoff, handoff.prediction_timestamp, None
    output = to_forecast_output(handoff, forecast_id=default_forecast_id(resolved))
    return handoff, handoff.prediction_timestamp, output


def serve_many(
    requests: Iterable[ForecastRequest],
    **kwargs: Any,
) -> tuple[ServedForecast, ...]:
    """Serve a batch, in the order given.

    Order is preserved rather than sorted, because a caller asking for three
    forecasts expects them back in the order they asked. Every request is served
    independently: one refusal does not stop the batch, because a batch that aborted
    on the first bad request would report fewer forecasts than were asked for
    without saying why.
    """
    return tuple(serve(request, **kwargs) for request in requests)


def default_forecast_id(request: ForecastRequest) -> str:
    """A deterministic identifier for a forecast request.

    Derived from the request's own fields rather than from a clock, so the same
    request always yields the same id and a caller can compare two runs. A UUID per
    request would make every artifact non-reproducible for no benefit.
    """
    stamp = request.origin_instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    selector = request.model_id or request.model_family or "selected"
    return f"{request.entity}-{request.target}-{request.horizon}-{stamp}-{selector}"


def serving_contract_description() -> dict[str, Any]:
    """A machine-readable description of what this boundary promises.

    Documentation that lives in code drifts from documentation that lives in a
    Markdown file; this is the version the docs and the tests both read.
    """
    return {
        "serving_contract_version": SERVING_CONTRACT_VERSION,
        "artifact_schema_version": FORECAST_ARTIFACT_VERSION,
        "handoff_contract_version": HANDOFF_CONTRACT_VERSION,
        "downstream_forecast_contract_version": FORECAST_CONTRACT_VERSION,
        "artifact_states": list(ARTIFACT_STATES),
        "statuses": list(SERVING_STATUSES),
        # Derived from `handoff_status_for_state` rather than re-typed, so the two
        # cannot drift. It is read here for the same reason the function exists: the
        # mapping is the contract, and a reader should see it in one place.
        "status_for_state": {
            state: handoff_status_for_state(state) for state in ARTIFACT_STATES
        },
        "error_to_status": {
            error_type.__name__: status for error_type, status in _STATUS_FOR_ERROR
        },
        "request_fields": ["target", "horizon", "entity", "origin_instant", "model_id", "model_family"],
        "result_fields": [
            "serving_contract_version",
            "forecast_id",
            "request",
            "status",
            "reason",
            "prediction",
            "prediction_timestamp",
            "state",
            "artifact_id",
            "selection",
            "forecast",
            "handoff",
            "forecast_output",
        ],
        "validation_order": [
            "resolve artifact",
            "check family / target / horizon",
            "require servable state",
            "validate feature names, order and types",
            "check causality and entity",
            "predict",
            "express in the Phase 4 handoff and the platform forecast output",
        ],
        "integration_statement": (
            "Phase 5 defines a function boundary, not an HTTP surface: no route, no handler, no "
            "serialization middleware and no persistence. Whoever owns the service layer calls "
            "serve() and renders ServedForecast.to_dict()."
        ),
        "scope": (
            "forecast generation from a validated artifact. Phase 5 does not train, does not "
            "refit preprocessing, does not resolve model weights from object storage, and does "
            "not define a route."
        ),
        # The data-status caveat belongs in the machine-readable contract, not only in
        # the Markdown. Anyone integrating reads `serving_contract_description()` -
        # or the payload it describes - and a contract that omits this would let a
        # forecaster believe every artifact it describes describes a usable model.
        "data_status_statement": (
            "every artifact, forecast and metric in this phase was produced from synthetic/demo "
            "data. Nothing here validates a hydrological method, and no artifact claims to be "
            "production-ready. The disclaimer travels with each result and cannot be switched "
            "off: "
            + SYNTHETIC_DATA_DISCLAIMER
        ),
    }


def state_counts(store: ArtifactStore) -> dict[str, int]:
    """How many artifacts sit in each state. A one-line health read of a store."""
    return {state: len(store.by_state(state)) for state in ARTIFACT_STATES}


__all__ = [
    "SERVING_CONTRACT_VERSION",
    "SERVING_STATUSES",
    "UNAVAILABLE_STATUSES",
    "ForecastServiceError",
    "ServedForecast",
    "default_forecast_id",
    "prediction_timestamp_for",
    "serve",
    "serve_many",
    "serving_contract_description",
    "state_counts",
    "status_for_error",
]