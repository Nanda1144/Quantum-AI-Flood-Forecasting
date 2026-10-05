# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/app/engines/hydro | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 7's response context: what the risk layer actually established.

Phase 6 ended with a `RiskResult`. This module is the read-only boundary between
that result and the response decision that Phase 7 goes on to make. It copies
facts across, validates the ones with a safety dimension, and **adds nothing**.

The single hardest rule in this file
-----------------------------------

`ExposureAvailability` has **no value field**. Not a default, not an optional
one - the field does not exist.

Phase 6's `GisContext` already carries `population_exposed` and
`infrastructure_exposed` as counts, and already refuses to expose them as
`RiskSignal`s, for a reason recorded in `risk_context.py`: a population count is
not comparable against a threshold, so any rule that fired on one would be
asserting a hazard relationship nobody in this repository has evidence for.

Phase 7 is the layer where that temptation is strongest, because a response
category is exactly the sort of thing someone would want to weight by how many
people are downstream. So the option is not offered. There is no field to put a
count in, which means `risk x population_weight` cannot be written - not as a
policy that we declined to configure, but as code that does not compile. That is
a stronger guarantee than a documented intention.

Missing is not zero
-------------------

Every availability state Phase 6 defined is reused verbatim - `valid`, `missing`,
`unavailable`, `not_applicable`, `stale` - because a response decision that
spoke a different dialect from the risk decision above it would be two
vocabularies pretending to be one.

None of the unusable states carries a number. A decision that reads
`population = unavailable` and reasons "so probably nobody is there" has made a
safety claim out of an absence of evidence. `response_unavailable_context`
returns records for exactly those absences, so a caller can be told what was
missing instead of being handed a zero.

What is deliberately absent
--------------------------

No clock. `decided_at` defaults to the forecast origin, so two decisions over the
same inputs cannot differ for a reason that has nothing to do with the evidence.

No composite score. This module carries `risk_score` because Phase 6 computed it,
and never combines it with anything. There is no `response_score` to compute.

No forecast, no threshold, no probability. Phase 6 owns those, and re-deriving any
of them here would make Phase 7 a second risk engine with the same arithmetic and
none of the review.

The name `ResponseContext` is Phase 7's own. Nothing equivalent existed - the
repository has no response vocabulary at all - and this is that vocabulary's first
typed expression.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from app.engines.hydro.contract import SUPPORTED_RISK_LEVELS
from app.engines.hydro.domains import NOT_AVAILABLE
from app.engines.hydro.forecast_risk import RISK_STATUS_RECORDED
from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER
from app.engines.hydro.risk_context import (
    CONTEXT_EVALUATION_STATES,
    CONTEXT_NOT_EVALUABLE,
    CONTEXT_UNAVAILABLE,
    SIGNAL_AVAILABILITY,
    SIGNAL_MISSING,
    SIGNAL_NOT_APPLICABLE,
    SIGNAL_STALE,
    SIGNAL_UNUSABLE,
    SIGNAL_UNAVAILABLE,
    SIGNAL_VALID,
    EntityMismatchError,
    FutureContextError,
)

RESPONSE_CONTEXT_VERSION = "navya-phase7-response-context/v1"

#: The availability states a contextual input may be in. Phase 6's vocabulary,
#: unchanged and not extended: a response decision has no business introducing an
#: availability state the risk layer above it cannot express.
RESPONSE_AVAILABILITY: tuple[str, ...] = SIGNAL_AVAILABILITY

#: States in which a contextual input contributed nothing. Reused from Phase 6 so
#: that "usable" means the same thing on both sides of this boundary.
RESPONSE_UNUSABLE: tuple[str, ...] = SIGNAL_UNUSABLE

#: Contextual inputs Phase 7 records the availability of, and nothing more.
#:
#: `population` and `infrastructure` are here because a reader of a response
#: decision will ask whether exposure was considered. The answer this module can
#: give is "yes, and here is whether it was available" - never "and here is what it
#: weighed".
EXPOSURE_KINDS: tuple[str, ...] = ("population", "infrastructure")

#: The state a contextual input starts in when a risk result says nothing about
#: it. `unavailable` rather than `missing`: the repository has no such provider at
#: all, which is a stronger and more honest statement than "a caller forgot".
EXPOSURE_DEFAULT_AVAILABILITY = SIGNAL_UNAVAILABLE


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class ResponseBoundaryError(ValueError):
    """Base for Phase 7 contract violations.

    Deliberately **not** a `RiskBoundaryError`. A caller that catches the risk
    taxonomy to handle "the risk layer refused" would otherwise silently swallow
    "the response layer refused", and the two failures need different responses.

    Two Phase 6 errors *are* reused, because they encode rules identical to Phase
    7's own and there is no reason to have two of them: `EntityMismatchError` and
    `FutureContextError`. Same class, same `reason` tag, one taxonomy.
    """

    reason = "response_boundary_error"


class MissingRiskResultError(ResponseBoundaryError):
    """No risk result was supplied. There is nothing to respond to."""

    reason = "missing_risk_result"


class InvalidRiskResultError(ResponseBoundaryError):
    """The supplied object is not a `RiskResult`, or is internally inconsistent."""

    reason = "invalid_risk_result"


class InvalidResponseContextError(ResponseBoundaryError):
    """A response context contradicts itself or the risk result it came from."""

    reason = "invalid_response_context"


# --------------------------------------------------------------------------- #
# Contextual availability
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExposureAvailability:
    """Whether one kind of exposure context was available. Never how much of it.

    The absence of a `value` field is the point of this class. See the module
    docstring: a population or infrastructure count cannot be compared against a
    threshold, and nothing in this repository establishes how either one relates
    to a response category.
    """

    kind: str
    availability: str
    reason: str = ""
    source: str = "no provider"

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise InvalidResponseContextError(
                "an exposure record must name the kind of exposure it describes, got "
                f"{self.kind!r}"
            )
        if self.kind not in EXPOSURE_KINDS:
            raise InvalidResponseContextError(
                f"exposure kind {self.kind!r} is not one of {list(EXPOSURE_KINDS)}; a "
                "response decision records the availability of the exposure kinds it "
                "knows about and invents no others"
            )
        if self.availability not in RESPONSE_AVAILABILITY:
            raise InvalidResponseContextError(
                f"exposure {self.kind!r} availability {self.availability!r} is not one of "
                f"{list(RESPONSE_AVAILABILITY)}; an unknown state cannot be reported as a "
                "known one"
            )
        if self.availability != SIGNAL_VALID and not self.reason.strip():
            raise InvalidResponseContextError(
                f"exposure {self.kind!r} is {self.availability!r} and must say why; 'no "
                "data' and 'we did not look' are different facts and a decision has to "
                "be able to tell them apart"
            )

    @property
    def usable(self) -> bool:
        return self.availability == SIGNAL_VALID

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "availability": self.availability,
            "reason": self.reason,
            "source": self.source,
            "usable": self.usable,
        }


def available_exposure(
    kind: str,
    *,
    source: str,
    reason: str = "",
) -> ExposureAvailability:
    """An exposure context that was available.

    There is no count argument, on purpose. The nearest thing to a population count
    anywhere in this repository is Phase 6's `GisContext.population_exposed`, and a
    factory that took the number and dropped it would invite the next reader to
    add it back.
    """
    return ExposureAvailability(kind=kind, availability=SIGNAL_VALID, source=source, reason=reason)


def unavailable_exposure(
    kind: str,
    availability: str,
    *,
    reason: str,
    source: str = "none",
) -> ExposureAvailability:
    """An exposure context that is not usable, and why.

    `availability` may be any state in `RESPONSE_UNUSABLE` - `missing`,
    `unavailable`, `not_applicable` or `stale` - and they mean different things, so
    the caller has to name which one applies rather than defaulting to a single
    "no data" answer.
    """
    if availability not in RESPONSE_UNUSABLE:
        raise InvalidResponseContextError(
            f"{availability!r} is a usable exposure state, not an unavailable one; "
            "use available_exposure() for it"
        )
    return ExposureAvailability(
        kind=kind, availability=availability, reason=reason, source=source
    )


def _exposure_records(
    gis: Mapping[str, Any] | None,
    overrides: Sequence[ExposureAvailability] | None,
) -> tuple[ExposureAvailability, ...]:
    """One record per exposure kind, in a fixed order, from whatever is known.

    Phase 6 serialises `GisContext` into a plain mapping on `RiskResult`, and it is
    the only place a population or infrastructure count appears anywhere in the
    repository. Whether the *count* is present is read here; the count itself is
    not copied, because a decision that holds the number can weight by it.
    """
    overrides = tuple(overrides or ())
    kinds = [record.kind for record in overrides]
    duplicates = sorted({kind for kind in kinds if kinds.count(kind) > 1})
    if duplicates:
        raise InvalidResponseContextError(
            f"exposure kinds {duplicates} were supplied more than once; a kind that "
            "appears twice has two availability states and no way to choose between "
            "them, and silently keeping one would misreport the other"
        )

    declared = {record.kind: record for record in overrides}
    for record in declared.values():
        if record.kind not in EXPOSURE_KINDS:
            raise InvalidResponseContextError(
                f"exposure kind {record.kind!r} is not one of {list(EXPOSURE_KINDS)}"
            )

    records: list[ExposureAvailability] = []
    for kind in EXPOSURE_KINDS:
        if kind in declared:
            records.append(declared[kind])
            continue
        value = None if gis is None else gis.get(f"{kind}_exposed")
        if value is None:
            records.append(
                ExposureAvailability(
                    kind=kind,
                    availability=EXPOSURE_DEFAULT_AVAILABILITY,
                    reason=NOT_AVAILABLE,
                    source="none",
                )
            )
        else:
            records.append(
                ExposureAvailability(
                    kind=kind,
                    availability=SIGNAL_VALID,
                    reason="",
                    source=str(gis.get("provider") or "a Phase 6 GIS provider"),
                )
            )
    return tuple(records)


def response_unavailable_context(
    context: "ResponseContext",
) -> tuple[ExposureAvailability, ...]:
    """Every contextual input that contributed nothing, and why."""
    return tuple(record for record in context.exposure if not record.usable)


# --------------------------------------------------------------------------- #
# The response context
# --------------------------------------------------------------------------- #


def _require_aware(value: dt.datetime, name: str) -> None:
    if not isinstance(value, dt.datetime):
        raise InvalidResponseContextError(
            f"{name} must be a datetime, got {type(value).__name__}"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise FutureContextError(
            f"{name} must be timezone-aware, got {value!r}; an instant with no offset "
            "cannot be compared against a forecast origin"
        )


@dataclass(frozen=True)
class ResponseContext:
    """Everything a response decision is allowed to know, copied from Phase 6.

    Every field is a fact Phase 6 already established. Nothing here is fetched,
    inferred, or estimated: `from_risk_result` is the only way this is meant to be
    built, and a context assembled field by field is a context nobody has checked
    against the result it claims to describe.

    `decided_at` defaults to the forecast origin and exists so a caller *may* state
    a later instant explicitly. Nothing in this module or in
    `response_decision` calls a clock.
    """

    entity: str
    risk_result_id: str
    risk_status: str
    risk_evaluation_state: str
    risk_level: str | None
    risk_score: float | None
    risk_score_type: str | None
    risk_threshold_policy: str
    risk_threshold_configuration: str
    risk_configuration_version: str
    residual_sigma_source: str | None
    forecast_id: str | None
    forecast_origin: dt.datetime
    forecast_horizon: str | None
    prediction: float | None
    prediction_units: str | None
    risk_availability_counts: Mapping[str, int] = field(default_factory=dict)
    usable_signal_names: tuple[str, ...] = ()
    gis_available: bool = False
    gis_reason: str = NOT_AVAILABLE
    historical_available: bool = False
    historical_reason: str = NOT_AVAILABLE
    historical_event_count: int = 0
    exposure: tuple[ExposureAvailability, ...] = ()
    decided_at: dt.datetime | None = None
    provenance: Any | None = None
    synthetic_demo: bool = True
    data_status: str = "unknown"
    disclaimer: str = SYNTHETIC_DATA_DISCLAIMER
    notes: str = ""
    context_version: str = RESPONSE_CONTEXT_VERSION

    # --- construction ------------------------------------------------------

    @classmethod
    def from_risk_result(
        cls,
        risk_result: Any,
        *,
        entity: str | None = None,
        decided_at: dt.datetime | None = None,
        exposure: Sequence[ExposureAvailability] | None = None,
    ) -> "ResponseContext":
        """Project a Phase 6 `RiskResult` onto a response context.

        `entity` is the caller's independent statement of which station this
        decision is about, and it is **checked against the risk result rather than
        overwriting it**. If the two disagree, `EntityMismatchError` fires here.

        That check is the whole point of the argument. Without it, a caller who
        assembled Station A's forecast with Station B's exposure would get a
        context labelled Station B containing Station A's evidence, and every later
        field would look consistent while describing the wrong place. There is no
        nearest-station logic and no geographic inference: if the two names are not
        the same string, the answer is a refusal.
        """
        if risk_result is None:
            raise MissingRiskResultError(
                "no Phase 6 risk result was supplied; a response decision needs a risk "
                "result to respond to, and Phase 7 does not assess risk itself"
            )

        inference = getattr(risk_result, "forecast", None)
        origin = getattr(inference, "origin_instant", None)
        if origin is None:
            raise InvalidRiskResultError(
                "the supplied risk result carries no forecast, so it has no origin "
                "instant; a decision with no origin cannot be checked against "
                "temporal leakage"
            )
        _require_aware(origin, "the risk result's forecast origin")

        gis = getattr(risk_result, "gis_context", None)
        historical = getattr(risk_result, "historical_context", None)
        signals = tuple(getattr(risk_result, "signals", ()) or ())
        counts = {
            state: sum(
                1 for signal in signals if signal.availability == state
            )
            for state in RESPONSE_AVAILABILITY
        }
        counts = {state: n for state, n in counts.items() if n}

        risk_entity = getattr(inference, "entity", None)
        if not isinstance(risk_entity, str) or not risk_entity.strip():
            raise InvalidRiskResultError(
                "the supplied risk result names no entity; a response decision is "
                "about a place, and one without a place is not a decision"
            )
        if entity is not None and entity != risk_entity:
            raise EntityMismatchError(
                f"the requested entity {entity!r} is not the entity this risk result "
                f"describes, {risk_entity!r}; a response decision about one station "
                "must not carry another station's evidence, and Phase 7 has no station "
                "registry, mapping or nearest-station rule with which to reconcile "
                "two different names"
            )

        return cls(
            entity=risk_entity,
            risk_result_id=str(getattr(risk_result, "risk_result_id", "")),
            risk_status=str(getattr(risk_result, "status", "")),
            risk_evaluation_state=str(getattr(risk_result, "evaluation_state", "")),
            risk_level=getattr(risk_result, "risk_level", None),
            risk_score=getattr(risk_result, "risk_score", None),
            risk_score_type=getattr(risk_result, "risk_score_type", None),
            risk_threshold_policy=str(getattr(risk_result, "threshold_policy", "")),
            risk_threshold_configuration=str(
                getattr(risk_result, "threshold_configuration", "")
            ),
            risk_configuration_version=str(
                getattr(risk_result, "risk_configuration_version", "")
            ),
            residual_sigma_source=getattr(risk_result, "residual_sigma_source", None),
            forecast_id=getattr(risk_result, "forecast_id", None),
            forecast_origin=origin,
            forecast_horizon=getattr(inference, "horizon", None),
            prediction=getattr(inference, "prediction", None),
            prediction_units=getattr(inference, "target_units", None),
            risk_availability_counts=MappingProxyType(counts),
            usable_signal_names=tuple(
                sorted(signal.name for signal in signals if signal.usable)
            ),
            gis_available=bool(gis.get("available")) if isinstance(gis, Mapping) else False,
            gis_reason=(
                str(gis.get("reason") or NOT_AVAILABLE)
                if isinstance(gis, Mapping)
                else NOT_AVAILABLE
            ),
            historical_available=(
                bool(historical.get("available")) if isinstance(historical, Mapping) else False
            ),
            historical_reason=(
                str(historical.get("reason") or NOT_AVAILABLE)
                if isinstance(historical, Mapping)
                else NOT_AVAILABLE
            ),
            historical_event_count=(
                int(historical.get("event_count") or 0)
                if isinstance(historical, Mapping)
                else 0
            ),
            exposure=_exposure_records(gis, exposure),
            decided_at=decided_at,
            provenance=getattr(risk_result, "provenance", None),
            synthetic_demo=bool(getattr(risk_result, "synthetic_demo", True)),
            data_status=str(getattr(risk_result, "data_status", "unknown")),
            disclaimer=str(
                getattr(risk_result, "disclaimer", None) or SYNTHETIC_DATA_DISCLAIMER
            ),
        )

    def __post_init__(self) -> None:
        if not isinstance(self.entity, str) or not self.entity.strip():
            raise EntityMismatchError(
                f"a response context must name the entity it describes, got {self.entity!r}"
            )
        if not isinstance(self.risk_result_id, str) or not self.risk_result_id.strip():
            raise InvalidRiskResultError(
                "a response context must name the risk result it came from; an "
                "unidentified result cannot be audited"
            )
        if self.risk_level is not None and self.risk_level not in SUPPORTED_RISK_LEVELS:
            raise InvalidRiskResultError(
                f"risk level {self.risk_level!r} is not among Phase 6's "
                f"{list(SUPPORTED_RISK_LEVELS)}; Phase 7 will not act on a risk level "
                "the risk layer cannot emit"
            )
        if self.risk_evaluation_state not in CONTEXT_EVALUATION_STATES:
            raise InvalidRiskResultError(
                f"risk evaluation state {self.risk_evaluation_state!r} is not one of "
                f"{list(CONTEXT_EVALUATION_STATES)}"
            )
        if self.risk_score is not None:
            if isinstance(self.risk_score, bool) or not isinstance(self.risk_score, (int, float)):
                raise InvalidRiskResultError(
                    f"risk score must be a real number or None, got {self.risk_score!r}"
                )
            if not 0.0 <= float(self.risk_score) <= 1.0:
                raise InvalidRiskResultError(
                    f"a Phase 6 exceedance probability lies in [0, 1], got "
                    f"{self.risk_score!r}"
                )

        _require_aware(self.forecast_origin, "ResponseContext.forecast_origin")
        if self.decided_at is not None:
            _require_aware(self.decided_at, "ResponseContext.decided_at")
            if self.decided_at < self.forecast_origin:
                raise FutureContextError(
                    f"decided_at {self.decided_at.isoformat()} precedes the forecast "
                    f"origin {self.forecast_origin.isoformat()}; a decision cannot be "
                    "made before the forecast it responds to exists"
                )

        if not isinstance(self.exposure, tuple):
            object.__setattr__(self, "exposure", tuple(self.exposure))
        kinds = [record.kind for record in self.exposure]
        duplicates = sorted({kind for kind in kinds if kinds.count(kind) > 1})
        if duplicates:
            raise InvalidResponseContextError(
                f"exposure kinds {duplicates} appear more than once; a record that "
                "cannot be named unambiguously cannot be reported honestly"
            )
        for record in self.exposure:
            if not isinstance(record, ExposureAvailability):
                raise InvalidResponseContextError(
                    f"ResponseContext.exposure holds a {type(record).__name__}"
                )

        if isinstance(self.risk_availability_counts, dict):
            object.__setattr__(
                self, "risk_availability_counts", MappingProxyType(dict(self.risk_availability_counts))
            )
        for state in self.risk_availability_counts:
            if state not in RESPONSE_AVAILABILITY:
                raise InvalidResponseContextError(
                    f"availability count for {state!r} is not one of "
                    f"{list(RESPONSE_AVAILABILITY)}"
                )

        if not isinstance(self.usable_signal_names, tuple):
            object.__setattr__(
                self, "usable_signal_names", tuple(sorted(self.usable_signal_names))
            )
        else:
            object.__setattr__(self, "usable_signal_names", tuple(sorted(self.usable_signal_names)))

    # --- derived -----------------------------------------------------------

    @property
    def resolved_decided_at(self) -> dt.datetime:
        """The instant the decision is attributed to. Defaults to the origin.

        Not a clock reading. Phase 6 made the same choice for `assessed_at`, for the
        same reason: an audit that changes when nobody changed the evidence is not
        an audit trail, it is a timestamp.
        """
        return self.decided_at if self.decided_at is not None else self.forecast_origin

    @property
    def risk_is_available(self) -> bool:
        """True when Phase 6 recorded a level this decision could act on."""
        return self.risk_status == RISK_STATUS_RECORDED and self.risk_level is not None

    @property
    def risk_context_is_available(self) -> bool:
        """False when Phase 6 read no context at all."""
        return self.risk_evaluation_state != CONTEXT_UNAVAILABLE

    @property
    def risk_is_evaluable(self) -> bool:
        """False when Phase 6 could not assign a band."""
        return self.risk_evaluation_state != CONTEXT_NOT_EVALUABLE

    @property
    def digest(self) -> str:
        """A short sha256 over the decision-relevant fields.

        Deterministic and derived: the same evidence produces the same digest, and
        the digest changes if any field that could change a decision changes. It is
        an integrity handle for the decision id, not a security primitive.
        """
        payload = {
            "entity": self.entity,
            "risk_result_id": self.risk_result_id,
            "risk_status": self.risk_status,
            "risk_evaluation_state": self.risk_evaluation_state,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "risk_score_type": self.risk_score_type,
            "forecast_id": self.forecast_id,
            "forecast_origin": self.forecast_origin.isoformat(),
            "forecast_horizon": self.forecast_horizon,
            "prediction": self.prediction,
            "prediction_units": self.prediction_units,
            "availability": dict(sorted(self.risk_availability_counts.items())),
            "usable_signals": list(self.usable_signal_names),
            "gis_available": self.gis_available,
            "historical_available": self.historical_available,
            "exposure": [
                record.to_dict() for record in self.exposure
            ],
            "decided_at": self.resolved_decided_at.isoformat(),
            "data_status": self.data_status,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]

    def describe(self) -> str:
        """One paragraph, for a log line."""
        return (
            f"response context for {self.entity}: risk {self.risk_status}/"
            f"{self.risk_evaluation_state} level={self.risk_level!r} "
            f"score={self.risk_score!r} from {self.risk_result_id!r}, origin "
            f"{self.forecast_origin.isoformat()}, decided at "
            f"{self.resolved_decided_at.isoformat()}, digest {self.digest}"
        )

    def to_dict(self) -> dict[str, Any]:
        provenance = self.provenance
        if dataclasses.is_dataclass(provenance) and hasattr(provenance, "to_dict"):
            provenance = provenance.to_dict()
        return {
            "entity": self.entity,
            "risk_result_id": self.risk_result_id,
            "risk_status": self.risk_status,
            "risk_evaluation_state": self.risk_evaluation_state,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "risk_score_type": self.risk_score_type,
            "risk_threshold_policy": self.risk_threshold_policy,
            "risk_threshold_configuration": self.risk_threshold_configuration,
            "risk_configuration_version": self.risk_configuration_version,
            "residual_sigma_source": self.residual_sigma_source,
            "forecast_id": self.forecast_id,
            "forecast_origin": self.forecast_origin.isoformat(),
            "forecast_horizon": self.forecast_horizon,
            "prediction": self.prediction,
            "prediction_units": self.prediction_units,
            "risk_availability_counts": dict(sorted(self.risk_availability_counts.items())),
            "usable_signal_names": list(self.usable_signal_names),
            "gis_available": self.gis_available,
            "gis_reason": self.gis_reason,
            "historical_available": self.historical_available,
            "historical_reason": self.historical_reason,
            "historical_event_count": self.historical_event_count,
            "exposure": [record.to_dict() for record in self.exposure],
            "decided_at": self.resolved_decided_at.isoformat(),
            "provenance": provenance,
            "synthetic_demo": self.synthetic_demo,
            "data_status": self.data_status,
            "disclaimer": self.disclaimer,
            "notes": self.notes,
            "context_version": self.context_version,
            "context_digest": self.digest,
        }


# --------------------------------------------------------------------------- #
# The contract, described
# --------------------------------------------------------------------------- #


def context_contract_description() -> dict[str, Any]:
    """The response-context contract as data, for a report or a review."""
    return {
        "response_context_version": RESPONSE_CONTEXT_VERSION,
        "consumes": "Phase 6 RiskResult, read-only",
        "risk_levels": list(SUPPORTED_RISK_LEVELS),
        "availability": list(RESPONSE_AVAILABILITY),
        "unusable_availability": list(RESPONSE_UNUSABLE),
        "exposure_kinds": list(EXPOSURE_KINDS),
        "exposure_carries_values": False,
        "exposure_values_note": (
            "population and infrastructure are recorded as availability only. Phase 6's "
            "GisContext carries the counts and already refuses to expose them as "
            "RiskSignals; Phase 7 has no field to put a count in, so no weight can be "
            "applied to one"
        ),
        "gis_absent_marker": NOT_AVAILABLE,
        "risk_evaluation_states": list(CONTEXT_EVALUATION_STATES),
        "errors": [
            cls.reason
            for cls in (
                MissingRiskResultError,
                InvalidRiskResultError,
                InvalidResponseContextError,
            )
        ],
        "reused_phase6_errors": [
            EntityMismatchError.reason,
            FutureContextError.reason,
        ],
        "no_clock": (
            "decided_at defaults to the forecast origin; nothing in this module calls "
            "a clock"
        ),
        "no_composite_score": (
            "risk_score is carried because Phase 6 computed it and is never combined "
            "with anything; there is no response_score"
        ),
    }


__all__ = [
    "CONTEXT_NOT_EVALUABLE",
    "CONTEXT_UNAVAILABLE",
    "EXPOSURE_DEFAULT_AVAILABILITY",
    "EXPOSURE_KINDS",
    "EntityMismatchError",
    "FutureContextError",
    "InvalidResponseContextError",
    "InvalidRiskResultError",
    "MissingRiskResultError",
    "NOT_AVAILABLE",
    "RESPONSE_AVAILABILITY",
    "RESPONSE_CONTEXT_VERSION",
    "RESPONSE_UNUSABLE",
    "SIGNAL_MISSING",
    "SIGNAL_NOT_APPLICABLE",
    "SIGNAL_STALE",
    "SIGNAL_UNUSABLE",
    "SIGNAL_UNAVAILABLE",
    "SIGNAL_VALID",
    "SYNTHETIC_DATA_DISCLAIMER",
    "ExposureAvailability",
    "ResponseBoundaryError",
    "ResponseContext",
    "available_exposure",
    "context_contract_description",
    "response_unavailable_context",
    "unavailable_exposure",
]