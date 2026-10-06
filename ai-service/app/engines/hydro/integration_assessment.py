# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/app/engines/hydro | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 8: the forecast -> risk -> response integration boundary.

    Phase 5  ServedForecast
        v
    Phase 6  RiskResult
        v
    Phase 7  ResponseDecision
        v
    Phase 8  IntegratedForecastAssessment
        v
    Deterministic serialized analytical result

What this layer is
------------------

One typed, immutable record that answers, from a single object: what forecast was
produced, which model and artifact produced it, what risk assessment followed,
what response decision followed that, what evidence was available, what evidence
was not, why the response was produced or withheld, and how the three layers are
chained together.

What this layer is not
----------------------

It is **not** a second forecast engine, a second risk engine, or a second response
engine. It contains no threshold arithmetic, no normal CDF, no sigma estimation,
no band classification, no policy mapping, and no rule evaluation. Every one of
those belongs to the layer that already owns it, and this module reads their
output the way a reader reads a report: it does not recompute the numbers in it.

That is enforced structurally rather than by intention. There is no function here
that takes a prediction and returns a probability, because `integrate` accepts
only already-built layer results and has nothing to compute with. If a future
editor needs a new field, they must go and ask the owning layer for it.

It is **not** a downgrade path. A `ResponseDecision` of `WITHHELD` enters this
module as `WITHHELD` and leaves as `WITHHELD`; a `REVIEW_WARNING` leaves as
`REVIEW_WARNING`. The integration status is a separate axis and never rewrites the
decision it reports. The one place Phase 8 is deliberately *more* conservative than
the layers below it is the status, never the recommendation.

It is **not** a service. This branch has no HTTP boundary - `app/api/`,
`app/core/` and `app/schemas/` are empty directories - so this is a pure domain
contract with deterministic serialization. Manufacturing a web framework here
because another branch has one would be inventing infrastructure, not integrating.

Why COMPLETE is hard to reach, on purpose
-----------------------------------------

`COMPLETE` requires that every declared contextual input be usable. In this
repository, population and infrastructure exposure have **no provider at all**, so
an integration built from repository data alone tops out at `PARTIAL`.

That is not a limitation of this module; it is the state of the platform. Reaching
`COMPLETE` requires a caller to supply both exposure providers explicitly, which is
a claim the caller then owns. The alternative - treating absent exposure as
"nothing to report" - would let a result with no exposure data claim to be the most
complete one available, which is exactly backwards.

Nothing here invents an exposure value. `ExposureAvailability` has no value field
and Phase 8 does not add one; Phase 8 reads the availability records Phase 7
already produced and never a count.

Status is derived, never supplied
---------------------------------

`integrate` accepts no `integration_status` argument. A caller cannot assert that
its chain is `COMPLETE`, so no bug in an upstream layer can be papered over by
declaring the integration fine. The status is computed from the layers in a fixed,
tested order, and `integration_reason` names the condition that decided it.

No clock, no randomness
-----------------------

`integrated_at` is the forecast origin, or `None` when there is no forecast. It is
never a reading of the current time. `integration_id` is a readable prefix plus a
sha256 over the chain's own content. Two calls with the same inputs produce
byte-identical output, which is what makes the serialized form citable.

The disclaimer rule that is easy to get wrong
---------------------------------------------

`risk_from_error` builds a `RiskResult` with `disclaimer=""`, because an error
path has no data to describe and an empty string is the honest answer there. Left
alone, an integration wrapping that result would carry an empty disclaimer and read
as though no synthetic-data warning were needed. So the disclaimer is resolved by
taking the first non-empty one from response, then risk, then the forecast, and
falling back to the canonical synthetic/demo sentence when all of them are empty.
The warning survives every path, including every error path.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from app.engines.hydro.domains import NOT_AVAILABLE
from app.engines.hydro.forecast_risk import RISK_CONTRACT_VERSION, RISK_STATUS_RECORDED
from app.engines.hydro.forecast_serving import SERVING_CONTRACT_VERSION, ServedForecast
from app.engines.hydro.model_handoff import STATUS_READY
from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER
from app.engines.hydro.response_context import (
    RESPONSE_CONTEXT_VERSION,
    ExposureAvailability,
    InvalidRiskResultError,
)
from app.engines.hydro.response_decision import (
    RECOMMENDATION_DISCLAIMER,
    RESPONSE_CONTRACT_VERSION,
    RESPONSE_STATES,
    ResponseDecision,
)
from app.engines.hydro.risk_context import (
    CONTEXT_NOT_EVALUABLE,
    CONTEXT_PARTIALLY_EVALUATED,
    CONTEXT_UNAVAILABLE,
    EntityMismatchError,
    FutureContextError,
)

INTEGRATION_CONTRACT_VERSION = "navya-phase8-integration/v1"

# --------------------------------------------------------------------------- #
# The integration vocabulary
# --------------------------------------------------------------------------- #

#: The four states an integration may carry, from most complete to least.
#:
#: `COMPLETE`     every layer produced a valid result and every declared contextual
#:                input was usable.
#: `PARTIAL`      the analytical chain is valid, but at least one declared contextual
#:                input was not usable. The upstream results are preserved as they
#:                are, with the gaps named.
#: `WITHHELD`     a valid chain exists, but no response interpretation may be made
#:                from it - because Phase 7 withheld, because Phase 6 read no context
#:                at all, or because Phase 7 produced no decision.
#: `NOT_EVALUABLE` the forecast or risk contract itself cannot be evaluated from what
#:                was supplied: no forecast, a refused forecast, no risk result, or a
#:                risk result carrying no level.
#:
#: There is deliberately no `FAILED` and no `ERROR`. A failure is a raised exception
#: or a recorded `error_reason`, never a status a caller could mistake for an
#: analytical outcome. There is also no `COMPLETE_WITH_ERRORS`: an integration that
#: hit a problem and calls itself complete is how a broken chain gets shipped.
INTEGRATION_COMPLETE = "COMPLETE"
INTEGRATION_PARTIAL = "PARTIAL"
INTEGRATION_WITHHELD = "WITHHELD"
INTEGRATION_NOT_EVALUABLE = "NOT_EVALUABLE"

INTEGRATION_STATES: tuple[str, ...] = (
    INTEGRATION_COMPLETE,
    INTEGRATION_PARTIAL,
    INTEGRATION_WITHHELD,
    INTEGRATION_NOT_EVALUABLE,
)

#: Permanently false. Phase 8 is not an authority and inherits no authority from the
#: layers it integrates; it exists so a consumer can assert on this rather than have
#: to trust the absence of a claim.
OPERATIONAL_AUTHORITY = False

#: Permanently false, matching Phase 6's and Phase 7's identical field.
PRODUCTION_READY_CLAIMED = False

#: The three layers, in the only order an integration may list them.
LAYER_ORDER: tuple[str, ...] = ("forecast", "risk", "response")

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class IntegrationBoundaryError(ValueError):
    """Base for Phase 8 contract violations.

    Deliberately **not** a `RiskBoundaryError` or a `ResponseBoundaryError`. A
    caller that catches the risk taxonomy to handle "the risk layer refused" must
    not silently swallow "the integration refused", because the three failures need
    different responses and the same `except` clause would hide two of them.

    Two Phase 6 errors *are* reused verbatim, because they encode rules identical to
    Phase 8's own and there is no reason to have two of them:
    `EntityMismatchError` and `FutureContextError`. Phase 7's `InvalidRiskResultError`
    is reused for the same reason - "this is not a valid Phase 6 risk result" is one
    rule with one reason tag, not two. One taxonomy, one set of strings.
    """

    reason = "integration_boundary_error"


class InvalidForecastResultError(IntegrationBoundaryError):
    """The supplied object is not a Phase 5 `ServedForecast`.

    Phase 8 accepts `ServedForecast | None` and nothing else. A bare
    `ForecastInference` is refused on purpose: it carries no forecast id and no
    serving status, so accepting it would force this module to invent the two facts
    the chain is built on. A caller holding only an inference has a forecast and
    should ask Phase 5 to serve it.
    """

    reason = "invalid_forecast_result"


class InvalidResponseDecisionError(IntegrationBoundaryError):
    """The supplied object is not a Phase 7 `ResponseDecision`, or names no known state."""

    reason = "invalid_response_decision"


class LayerSequenceError(IntegrationBoundaryError):
    """A downstream layer was supplied while an upstream one was absent.

    A risk result with no forecast, or a response decision with no risk result, is
    not a partially-populated chain - it is an unauditable one. Phase 8 reports the
    chain it was given rather than filling the gap, so a caller cannot pass a Phase 7
    decision from some other forecast and have it presented as this one's.
    """

    reason = "layer_sequence_error"


class ChainMismatchError(IntegrationBoundaryError):
    """Two layers disagree about the forecast they share.

    A different `forecast_id`, origin instant or horizon between layers means they
    do not describe the same event, and stitching them together would produce a
    result that looks internally consistent while mixing two forecasts.
    """

    reason = "chain_mismatch"


# --------------------------------------------------------------------------- #
# The chain
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LayerLink:
    """One slot of the provenance chain: which layer, which result, which status.

    The chain is always three slots long, in `LAYER_ORDER`, whether or not the layer
    produced anything. An absent layer is a slot with `layer_id is None`, not a
    missing slot.

    That is the point. A chain that simply omits the response because none was
    produced looks identical to a chain that never had one, and the second is the
    kind of bug this module exists to make visible. Three fixed slots mean
    "Phase 7 produced nothing" is assertable in one comparison.
    """

    layer: str
    layer_id: str | None
    status: str | None
    contract_version: str | None = None

    def __post_init__(self) -> None:
        if self.layer not in LAYER_ORDER:
            raise IntegrationBoundaryError(
                f"chain slot {self.layer!r} is not one of {list(LAYER_ORDER)}; the chain "
                "has exactly three layers and adding a fourth would mean a layer this "
                "module does not integrate"
            )

    @property
    def present(self) -> bool:
        """True when the layer actually produced a result.

        Keyed on `status`, not on `layer_id`, because a refused Phase 5 serving *is*
        a result: it produced `status='artifact_unavailable'` and no forecast id. A
        chain that treated that slot as absent would report "no forecast layer ran"
        when in fact the layer ran and refused - two different operational situations
        that a reader has to be able to tell apart.
        """
        return self.status is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "layer_id": self.layer_id,
            "status": self.status,
            "contract_version": self.contract_version,
            "present": self.present,
        }


# --------------------------------------------------------------------------- #
# Type validation
# --------------------------------------------------------------------------- #

#: The attributes Phase 8 reads from a Phase 6 risk result, and therefore the
#: attributes that must be present for an object to be treated as one.
#:
#: Listed once so `_require_risk` (which validates) and `_reportable_risk` (which
#: accepts on the error path) can never disagree about what a risk layer is. Two
#: lists would eventually drift, and the drift would show up only as a crash inside
#: the error handler.
_RISK_LAYER_FIELDS: tuple[str, ...] = (
    "risk_result_id",
    "status",
    "evaluation_state",
    "risk_level",
    "risk_score",
    "risk_score_type",
    "threshold_policy",
)


def _require_forecast(forecast: Any) -> ServedForecast | None:
    """`None`, or a Phase 5 `ServedForecast`. Nothing else.

    `None` is accepted because "the forecast layer produced nothing" is a state the
    integration must be able to report, not an error. A bare `ForecastInference` is
    refused: it has no forecast id and no serving status, and this module will not
    fabricate either.
    """
    if forecast is None or isinstance(forecast, ServedForecast):
        return forecast
    raise InvalidForecastResultError(
        f"expected a Phase 5 ServedForecast or None, got {type(forecast).__name__}. "
        "Phase 8 integrates the serving result because the chain needs its forecast "
        "id and status; a bare ForecastInference carries neither and Phase 8 will "
        "not invent them"
    )


def _require_risk(risk: Any) -> Any | None:
    """`None`, or a Phase 6 `RiskResult`.

    The failure reuses Phase 7's `InvalidRiskResultError` rather than declaring a
    Phase 8 twin: "this is not a valid Phase 6 risk result" is one rule, and two
    classes with the same reason tag would make `except` clauses ambiguous.

    Checked by duck typing rather than `isinstance`, matching Phases 6 and 7, so a
    `RiskResult` rebuilt from a serialized one still integrates. The attribute list is
    exactly what the projections below read, and `_reportable_risk` uses the same
    list - so "looks like a risk result" and "can be reported as one" cannot diverge.
    """
    if risk is None:
        return None
    required = _RISK_LAYER_FIELDS
    if all(hasattr(risk, name) for name in required):
        return risk
    raise InvalidRiskResultError(
        f"expected a Phase 6 RiskResult or None, got {type(risk).__name__}; a Phase 8 "
        "integration consumes a risk result Phase 6 already produced and never "
        "assesses risk itself"
    )


def _require_response(response: Any) -> ResponseDecision | None:
    """`None`, or a Phase 7 `ResponseDecision` naming a state Phase 7 can produce."""
    if response is None or isinstance(response, ResponseDecision):
        candidate = response
    else:
        raise InvalidResponseDecisionError(
            f"expected a Phase 7 ResponseDecision or None, got {type(response).__name__}; "
            "Phase 7 is the sole authority for response classification and Phase 8 "
            "does not produce a response"
        )
    if candidate is None:
        return None
    if candidate.decision not in RESPONSE_STATES:
        raise InvalidResponseDecisionError(
            f"the supplied response decision is {candidate.decision!r}, which is not "
            f"one of {list(RESPONSE_STATES)}; Phase 8 will not recognise a response "
            "state the response layer cannot emit"
        )
    return candidate


def _require_sequence(
    forecast: ServedForecast | None,
    risk: Any | None,
    response: ResponseDecision | None,
) -> None:
    """A layer may only be present if every layer above it is.

    This is the rule that stops a caller from handing over a Phase 7 decision
    computed against some other forecast. Phase 8 reports the chain it was given; it
    does not fill holes, and a response decision with no risk result in the chain has
    nothing to be audited against.
    """
    if risk is not None and forecast is None:
        raise LayerSequenceError(
            "a Phase 6 risk result was supplied with no Phase 5 forecast; a risk result "
            "cannot be placed in a chain whose first layer is missing, and Phase 8 will "
            "not reconstruct the forecast it came from"
        )
    if response is not None and risk is None:
        raise LayerSequenceError(
            "a Phase 7 response decision was supplied with no Phase 6 risk result; a "
            "response decision must be auditable against the risk result that produced "
            "it, and Phase 8 will not infer which risk result was meant"
        )


def _require_aware(value: dt.datetime, name: str) -> None:
    if not isinstance(value, dt.datetime):
        raise InvalidForecastResultError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise FutureContextError(
            f"{name} must be timezone-aware, got {value!r}; an instant with no offset "
            "cannot be compared against the forecast origin it must match"
        )


# --------------------------------------------------------------------------- #
# Entity and chain consistency
# --------------------------------------------------------------------------- #


def _forecast_entity(forecast: ServedForecast | None) -> str | None:
    """The entity the forecast layer names, ready or not.

    Read from the inference when there is one and from the request otherwise, so a
    refused serving result still reports which station it was asked about. That is
    the entity a caller needs in order to see *which* request failed.
    """
    if forecast is None:
        return None
    inference = getattr(forecast, "inference", None)
    entity = getattr(inference, "entity", None)
    if isinstance(entity, str) and entity.strip():
        return entity
    request = getattr(forecast, "request", None)
    entity = getattr(request, "entity", None)
    return entity if isinstance(entity, str) and entity.strip() else None


def _check_entity(
    forecast: ServedForecast | None,
    risk: Any | None,
    response: ResponseDecision | None,
) -> None:
    """Every layer must describe the same place, or the integration is refused.

    Phase 6 checks the request against the forecast, and Phase 7 checks the request
    against the risk result. This check is different in kind: it verifies that the
    three results assembled into one object agree *with each other*, which neither of
    them can do because neither of them can see the whole chain.

    There is no nearest-station rule and no geographic inference here. If the names
    are not the same string, the answer is a refusal, because the alternative -
    deciding that Station A and Station B are probably the same catchment - is a
    guess about the physical world made by an integration layer.
    """
    names: list[tuple[str, str]] = []
    forecast_entity = _forecast_entity(forecast)
    if forecast_entity is not None:
        names.append(("forecast", forecast_entity))
    risk_inference = getattr(risk, "forecast", None) if risk is not None else None
    risk_entity = getattr(risk_inference, "entity", None)
    if isinstance(risk_entity, str) and risk_entity.strip():
        names.append(("risk", risk_entity))
    response_entity = getattr(response, "entity", None)
    if isinstance(response_entity, str) and response_entity.strip():
        names.append(("response", response_entity))

    distinct = sorted({entity for _, entity in names})
    if len(distinct) > 1:
        detail = ", ".join(f"{layer}={entity!r}" for layer, entity in names)
        raise EntityMismatchError(
            f"the supplied layers describe different entities ({detail}); an integration "
            "must be about one place, and this repository has no station registry, "
            "mapping or nearest-station rule with which to reconcile two different names"
        )


def _check_chain(
    forecast: ServedForecast | None,
    risk: Any | None,
    response: ResponseDecision | None,
) -> None:
    """The layers must agree on which forecast this is.

    Three facts have to match across layers: the forecast id, the origin instant and
    the horizon. Any disagreement means the chain stitches together results from two
    different forecasts, and an object that reported them together would look
    self-consistent while describing a mixture.

    An origin that is *later* than the forecast's is reported as `FutureContextError`
    rather than `ChainMismatchError`, because that is the temporal-violation case and
    it deserves the same reason tag Phase 6 and Phase 7 use for it.
    """
    inference = getattr(forecast, "inference", None)
    if inference is None:
        return
    _require_aware(inference.origin_instant, "the forecast origin instant")

    forecast_id = getattr(forecast, "forecast_id", None)
    risk_inference = getattr(risk, "forecast", None) if risk is not None else None

    if risk_inference is not None:
        risk_id = getattr(risk, "forecast_id", None)
        if forecast_id is not None and risk_id is not None and risk_id != forecast_id:
            raise ChainMismatchError(
                f"the Phase 6 risk result names forecast {risk_id!r} while the supplied "
                f"Phase 5 result is {forecast_id!r}; these are two different forecasts "
                "and Phase 8 will not pair one forecast's identity with another's risk"
            )
        _check_origin(
            risk_inference.origin_instant,
            inference.origin_instant,
            "Phase 6",
        )
        _check_horizon(
            getattr(risk_inference, "horizon", None),
            getattr(inference, "horizon", None),
            "Phase 6",
        )

    if response is not None:
        response_id = getattr(response, "forecast_id", None)
        if forecast_id is not None and response_id is not None and response_id != forecast_id:
            raise ChainMismatchError(
                f"the Phase 7 response decision names forecast {response_id!r} while the "
                f"supplied Phase 5 result is {forecast_id!r}; Phase 8 will not report a "
                "decision against a forecast other than the one it was given"
            )
        _check_origin(
            response.forecast_origin,
            inference.origin_instant,
            "Phase 7",
        )
        _check_horizon(
            getattr(response, "forecast_horizon", None),
            getattr(inference, "horizon", None),
            "Phase 7",
        )


def _check_origin(
    claimed: dt.datetime,
    origin: dt.datetime,
    layer: str,
) -> None:
    _require_aware(claimed, f"the {layer} origin instant")
    if claimed == origin:
        return
    if claimed > origin:
        raise FutureContextError(
            f"the {layer} result describes forecast origin "
            f"{claimed.isoformat()}, which is later than the supplied forecast origin "
            f"{origin.isoformat()}; integrating them would place information from a "
            "later forecast into this result"
        )
    raise ChainMismatchError(
        f"the {layer} result describes forecast origin {claimed.isoformat()} but the "
        f"supplied forecast origin is {origin.isoformat()}; the layers are not about "
        "the same forecast and Phase 8 will not reconcile two origins"
    )


def _check_horizon(
    claimed: str | None,
    horizon: str | None,
    layer: str,
) -> None:
    if claimed is None or horizon is None or claimed == horizon:
        return
    raise ChainMismatchError(
        f"the {layer} result describes forecast horizon {claimed!r} but the supplied "
        f"forecast horizon is {horizon!r}; a risk or response for one lead time "
        "cannot be integrated with a forecast for another"
    )


# --------------------------------------------------------------------------- #
# Carried-forward facts
# --------------------------------------------------------------------------- #


def _disclaimer(
    forecast: ServedForecast | None,
    risk: Any | None,
    response: ResponseDecision | None,
) -> str:
    """The first non-empty disclaimer carried by any layer, or the canonical one.

    The fallback is the load-bearing part. `risk_from_error` builds a `RiskResult`
    whose `disclaimer` is the empty string, because an error path has no data to
    describe and an empty string is the honest answer *there*. Forwarded unchanged it
    would make an integration wrapping a failed risk assessment read as though no
    synthetic-data warning were required, which is the one conclusion this repository
    must never produce by accident.

    So an empty disclaimer never survives to the integrated result: the canonical
    synthetic/demo sentence is returned instead. Nothing here weakens a warning or
    invents one - the layers below already decided this data is synthetic.
    """
    candidates = (
        getattr(response, "disclaimer", None),
        getattr(risk, "disclaimer", None),
        getattr(getattr(forecast, "inference", None), "disclaimer", None),
    )
    for text in candidates:
        if isinstance(text, str) and text.strip():
            return text
    return SYNTHETIC_DATA_DISCLAIMER


def _synthetic_demo(
    forecast: ServedForecast | None,
    risk: Any | None,
    response: ResponseDecision | None,
) -> bool:
    """True when any layer says its data is synthetic, and when nothing says otherwise.

    The default is `True`, not `False`. An integration whose layers carry no data
    status has not established that its data is real, and reporting `False` would be
    a claim about the world that no layer made.
    """
    for source in (response, risk, getattr(forecast, "inference", None)):
        flag = getattr(source, "synthetic_demo", None)
        if flag is True:
            return True
    return not any(
        getattr(source, "synthetic_demo", None) is not None
        for source in (response, risk, getattr(forecast, "inference", None))
    )


def _data_status(
    forecast: ServedForecast | None,
    risk: Any | None,
    response: ResponseDecision | None,
) -> str:
    """The first non-empty data status carried by any layer, or `unknown`."""
    for source in (response, risk, getattr(forecast, "inference", None)):
        status = getattr(source, "data_status", None)
        if isinstance(status, str) and status.strip():
            return status
    return "unknown"


def _integrated_at(
    forecast: ServedForecast | None,
) -> dt.datetime | None:
    """The forecast origin, or `None` when there is no forecast.

    Never a clock reading. An integration is attributed to the instant its forecast
    was made, so re-running the integration over unchanged evidence produces an
    unchanged timestamp. With no forecast there is no instant to attribute it to, and
    `None` says that rather than substituting an arbitrary one.
    """
    inference = getattr(forecast, "inference", None)
    origin = getattr(inference, "origin_instant", None)
    return origin if isinstance(origin, dt.datetime) else None


def _artifact_identity(
    forecast: ServedForecast | None,
) -> tuple[str | None, str | None, str | None]:
    """`(model_id, model_version, artifact_id)` for the forecast layer.

    Read from the inference when there is one, falling back to the `ServedForecast`'s
    own `artifact_id`. A refused serving result has no inference, so it can report
    which artifact was asked for and not found - which is exactly the fact an operator
    needs from a `NOT_EVALUABLE` integration.
    """
    inference = getattr(forecast, "inference", None)
    if inference is None:
        fallback = getattr(forecast, "artifact_id", None)
        return None, None, fallback if isinstance(fallback, str) else None
    return (
        getattr(inference, "model_id", None),
        getattr(inference, "model_version", None),
        getattr(inference, "artifact_id", None),
    )


def _gis_and_history(
    risk: Any | None,
) -> tuple[bool, str, bool, str]:
    """GIS and historical availability, carried forward from Phase 6 verbatim.

    These are projected, not recomputed, and never interpreted. This repository has no
    GIS implementation and no flood-event data source, so both will read as the
    `NOT_AVAILABLE` marker; carrying them forward is what lets a reader see that the
    absence was noticed rather than forgotten.

    No spatial conclusion is drawn anywhere in this module.
    """
    if risk is None:
        return False, NOT_AVAILABLE, False, NOT_AVAILABLE
    gis = getattr(risk, "gis_context", None)
    historical = getattr(risk, "historical_context", None)
    return (
        bool(gis.get("available")) if isinstance(gis, Mapping) else False,
        str(gis.get("reason") or NOT_AVAILABLE) if isinstance(gis, Mapping) else NOT_AVAILABLE,
        bool(historical.get("available")) if isinstance(historical, Mapping) else False,
        str(historical.get("reason") or NOT_AVAILABLE)
        if isinstance(historical, Mapping)
        else NOT_AVAILABLE,
    )


def _risk_projection(
    risk: Any | None,
) -> tuple[str | None, str | None, str | None, float | None, str | None]:
    """`(status, evaluation_state, level, score, score_type)` read off Phase 6."""
    if risk is None:
        return None, None, None, None, None
    return (
        risk.status,
        risk.evaluation_state,
        risk.risk_level,
        risk.risk_score,
        risk.risk_score_type,
    )


def _response_projection(
    response: ResponseDecision | None,
) -> tuple[str | None, str | None, str | None]:
    """`(decision, status, decision_id)` read off Phase 7."""
    if response is None:
        return None, None, None
    return response.decision, response.status, response.decision_id


# --------------------------------------------------------------------------- #
# The integrated result
# --------------------------------------------------------------------------- #


class InvalidIntegrationStatusError(IntegrationBoundaryError):
    """The integration status is not one of `INTEGRATION_STATES`.

    A constructor invariant rather than a caller obligation. The status is derived
    from the layers, so the only way to reach this is a hand-built object or a future
    edit that adds a state without updating the derivation - and both are worth
    failing on rather than silently reporting an unrecognised status to a consumer.
    """

    reason = "invalid_integration_status"


@dataclass(frozen=True)
class IntegratedForecastAssessment:
    """One forecast, its risk assessment and its response decision, as a single record.

    The three layer results are held **by reference**, as the objects their own layers
    produced. Nothing is copied out of them, so no projection here can drift from its
    source and no upstream object has to be duplicated to be recorded.

    The flat fields that repeat a value already on a layer - `forecast_id`,
    `risk_level`, `response_decision` and the rest - exist so a reader can answer
    "which forecast, which risk, which response" without walking three nested
    structures, including on a `NOT_EVALUABLE` chain where there is no nested
    structure to walk. They are **projections, and `__post_init__` proves it**: each
    one is checked against the object it came from at construction time, so a
    projection cannot disagree with its source. A test asserts the same property from
    outside.

    Three structural safety properties:

    * ``operational_authority`` is permanently `False` and ``production_ready_claimed``
      is permanently `False`. They are fields so a consumer can assert on them, not so
      a caller can set them.
    * ``chain`` always has three slots in `LAYER_ORDER`, so "Phase 7 produced nothing"
      is a slot with a `None` id rather than a silently shorter chain.
    * ``disclaimer`` is never empty. See `_disclaimer`.

    There is no score field of Phase 8's own. Phases 6 and 7 already declined to
    invent a composite, and a third layer that added one would have to invent it again.
    """

    integration_id: str
    integration_status: str
    integration_reason: str
    entity: str | None
    forecast: ServedForecast | None
    risk: Any | None
    response: ResponseDecision | None
    chain: tuple[LayerLink, ...]
    provenance: Mapping[str, Any]
    evidence_availability: Mapping[str, int]
    available_inputs: tuple[str, ...]
    unusable_context: tuple[ExposureAvailability, ...]
    explanation: tuple[str, ...]
    forecast_id: str | None
    forecast_status: str | None
    forecast_origin: dt.datetime | None
    forecast_horizon: str | None
    prediction: float | None
    prediction_units: str | None
    model_id: str | None
    model_version: str | None
    artifact_id: str | None
    risk_result_id: str | None
    risk_status: str | None
    risk_evaluation_state: str | None
    risk_level: str | None
    risk_score: float | None
    risk_score_type: str | None
    response_decision: str | None
    response_status: str | None
    response_decision_id: str | None
    gis_available: bool
    gis_reason: str
    historical_available: bool
    historical_reason: str
    integrated_at: dt.datetime | None
    error_reason: str | None = None
    operational_authority: bool = OPERATIONAL_AUTHORITY
    production_ready_claimed: bool = PRODUCTION_READY_CLAIMED
    synthetic_demo: bool = True
    data_status: str = "unknown"
    disclaimer: str = SYNTHETIC_DATA_DISCLAIMER
    integration_contract_version: str = INTEGRATION_CONTRACT_VERSION
    serving_contract_version: str = SERVING_CONTRACT_VERSION
    risk_contract_version: str = RISK_CONTRACT_VERSION
    response_contract_version: str = RESPONSE_CONTRACT_VERSION
    response_context_version: str = RESPONSE_CONTEXT_VERSION

    def __post_init__(self) -> None:
        if self.integration_status not in INTEGRATION_STATES:
            raise InvalidIntegrationStatusError(
                f"integration status {self.integration_status!r} is not one of "
                f"{list(INTEGRATION_STATES)}"
            )

        # --- the chain is exactly three slots, in order --------------------
        if not isinstance(self.chain, tuple):
            object.__setattr__(self, "chain", tuple(self.chain))
        if len(self.chain) != len(LAYER_ORDER):
            raise IntegrationBoundaryError(
                f"the provenance chain has {len(self.chain)} slot(s); it must have "
                f"{len(LAYER_ORDER)} - {list(LAYER_ORDER)} - whether or not a layer "
                "produced anything, because a short chain cannot express a layer that "
                "produced nothing"
            )
        for expected, link in zip(LAYER_ORDER, self.chain):
            if link.layer != expected:
                raise IntegrationBoundaryError(
                    f"chain slot is {link.layer!r} where {expected!r} was expected; the "
                    f"chain order is fixed at {list(LAYER_ORDER)}"
                )

        for name in ("available_inputs", "unusable_context", "explanation"):
            if not isinstance(getattr(self, name), tuple):
                object.__setattr__(self, name, tuple(getattr(self, name)))

        if isinstance(self.provenance, dict):
            object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))
        if isinstance(self.evidence_availability, dict):
            object.__setattr__(
                self,
                "evidence_availability",
                MappingProxyType(dict(sorted(self.evidence_availability.items()))),
            )

        # --- the projections must equal their sources ----------------------
        # Not a defensive check for its own sake. It is what makes "projections, not
        # copies" a property rather than a claim: if a projection could disagree with
        # the object it was taken from, this record would be able to report one thing
        # while holding another.
        expected_entity = _forecast_entity(self.forecast)
        if self.entity != expected_entity:
            raise IntegrationBoundaryError(
                f"entity {self.entity!r} does not match the forecast layer's entity "
                f"{expected_entity!r}; the projection must equal its source"
            )
        for name, projected, actual in (
            ("forecast_status", self.forecast_status, getattr(self.forecast, "status", None)),
            ("forecast_id", self.forecast_id, getattr(self.forecast, "forecast_id", None)),
        ):
            if projected != actual:
                raise IntegrationBoundaryError(
                    f"{name} {projected!r} does not match the forecast layer's "
                    f"{actual!r}; the projection must equal its source"
                )
        for name, projected, actual in zip(
            ("risk_status", "risk_evaluation_state", "risk_level", "risk_score", "risk_score_type"),
            _risk_projection(self.risk),
            (self.risk_status, self.risk_evaluation_state, self.risk_level, self.risk_score, self.risk_score_type),
        ):
            if projected != actual:
                raise InvalidRiskResultError(
                    f"{name} {projected!r} does not match the risk layer's {actual!r}; "
                    "the projection must equal its source"
                )
        if self.risk_result_id != getattr(self.risk, "risk_result_id", None):
            raise InvalidRiskResultError(
                f"risk_result_id {self.risk_result_id!r} does not match the risk layer's "
                f"{getattr(self.risk, 'risk_result_id', None)!r}"
            )
        for name, projected, actual in zip(
            ("response_decision", "response_status", "response_decision_id"),
            _response_projection(self.response),
            (self.response_decision, self.response_status, self.response_decision_id),
        ):
            if projected != actual:
                raise InvalidResponseDecisionError(
                    f"{name} {projected!r} does not match the response layer's "
                    f"{actual!r}; the projection must equal its source"
                )
        for name, projected, actual in zip(
            ("model_id", "model_version", "artifact_id"),
            _artifact_identity(self.forecast),
            (self.model_id, self.model_version, self.artifact_id),
        ):
            if projected != actual:
                raise InvalidForecastResultError(
                    f"{name} {projected!r} does not match the forecast layer's {actual!r}"
                )
        expected_flags = (
            _disclaimer(self.forecast, self.risk, self.response),
            _synthetic_demo(self.forecast, self.risk, self.response),
            _data_status(self.forecast, self.risk, self.response),
            _integrated_at(self.forecast),
        )
        actual_flags = (self.disclaimer, self.synthetic_demo, self.data_status, self.integrated_at)
        if expected_flags != actual_flags:
            raise IntegrationBoundaryError(
                "the disclaimer, synthetic flag, data status and integrated_at must be "
                f"derived from the layers; expected {expected_flags!r}, got {actual_flags!r}"
            )
        if not (isinstance(self.disclaimer, str) and self.disclaimer.strip()):
            raise IntegrationBoundaryError(
                "an integrated result must carry a disclaimer; an empty one would let a "
                "synthetic-data warning be dropped by omission"
            )

    # --- derived -----------------------------------------------------------

    @property
    def is_complete(self) -> bool:
        return self.integration_status == INTEGRATION_COMPLETE

    @property
    def is_partial(self) -> bool:
        return self.integration_status == INTEGRATION_PARTIAL

    @property
    def is_withheld(self) -> bool:
        return self.integration_status == INTEGRATION_WITHHELD

    @property
    def is_not_evaluable(self) -> bool:
        return self.integration_status == INTEGRATION_NOT_EVALUABLE

    @property
    def layer_ids(self) -> tuple[str | None, ...]:
        return tuple(link.layer_id for link in self.chain)

    @property
    def chain_intact(self) -> bool:
        """True when the chain has no holes: the first absent slot ends it.

        A response with no risk, or a risk with no forecast, would make this `False`.
        `integrate` refuses to build such a chain, so this is a property a consumer
        can assert on without trusting that.
        """
        seen_gap = False
        for link in self.chain:
            if not link.present:
                seen_gap = True
            elif seen_gap:
                return False
        return True

    @property
    def response_is_recommendation(self) -> bool:
        """True when Phase 7 recommended a response category rather than withholding.

        Reads the decision, never the integration status. A `WITHHELD` integration
        that carries a recommended response still reports that recommendation; the two
        axes are independent and Phase 8 does not collapse them.
        """
        return self.response is not None and not self.response.is_withheld

    def explain(self) -> str:
        """The explanation as one paragraph, for a log line."""
        return " ".join(self.explanation)

    # --- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """The deterministic analytical record.

        What is serialized is chosen deliberately. The full `ServedForecast`,
        `RiskResult` and `ResponseDecision` stay reachable on the object; what goes
        into the serialized form is each layer's *summary* plus every fact the
        contract is expected to answer. Dumping the nested objects whole would triple
        the size of every record and reproduce Phase 6's signal list and Phase 7's
        evidence list inside a third contract that owns none of them - so those are
        referenced, not inlined, and this module stays a reader rather than a second
        copy of the chain.

        Deterministic by construction: no clock, no ordering that depends on a dict's
        insertion order, and every value is either a JSON primitive or a list of
        them. `to_json` relies on that, so it needs no fallback serializer that could
        quietly stringify something unserialisable.
        """
        return {
            "integration_id": self.integration_id,
            "integration_status": self.integration_status,
            "integration_reason": self.integration_reason,
            "error_reason": self.error_reason,
            "entity": self.entity,
            "chain": [link.to_dict() for link in self.chain],
            "chain_intact": self.chain_intact,
            "provenance": dict(self.provenance),
            "evidence_availability": dict(sorted(self.evidence_availability.items())),
            "available_inputs": list(self.available_inputs),
            "unavailable_context": [record.to_dict() for record in self.unusable_context],
            "explanation": list(self.explanation),
            "forecast": _forecast_summary(self.forecast),
            "risk": _risk_summary(self.risk),
            "response": _response_summary(self.response),
            "forecast_id": self.forecast_id,
            "forecast_status": self.forecast_status,
            "forecast_origin": self.forecast_origin.isoformat() if self.forecast_origin else None,
            "forecast_horizon": self.forecast_horizon,
            "prediction": self.prediction,
            "prediction_units": self.prediction_units,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "artifact_id": self.artifact_id,
            "risk_result_id": self.risk_result_id,
            "risk_status": self.risk_status,
            "risk_evaluation_state": self.risk_evaluation_state,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "risk_score_type": self.risk_score_type,
            "response_decision": self.response_decision,
            "response_status": self.response_status,
            "response_decision_id": self.response_decision_id,
            "gis_available": self.gis_available,
            "gis_reason": self.gis_reason,
            "historical_available": self.historical_available,
            "historical_reason": self.historical_reason,
            "integrated_at": self.integrated_at.isoformat() if self.integrated_at else None,
            "operational_authority": self.operational_authority,
            "production_ready_claimed": self.production_ready_claimed,
            "synthetic_demo": self.synthetic_demo,
            "data_status": self.data_status,
            "disclaimer": self.disclaimer,
            "integration_contract_version": self.integration_contract_version,
            "serving_contract_version": self.serving_contract_version,
            "risk_contract_version": self.risk_contract_version,
            "response_contract_version": self.response_contract_version,
            "response_context_version": self.response_context_version,
        }

    def to_json(self, *, indent: int | None = None) -> str:
        """The serialized record as JSON text.

        `sort_keys=True` because two records with the same content must serialize to
        the same string regardless of how their mappings were built, and `default` is
        deliberately absent so an unserialisable value fails loudly instead of being
        quietly stringified into something that looks like data.
        """
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            ensure_ascii=False,
            indent=indent,
        )


def _forecast_summary(forecast: ServedForecast | None) -> dict[str, Any] | None:
    """The Phase 5 facts a reader of the integrated record needs."""
    if forecast is None:
        return None
    inference = getattr(forecast, "inference", None)
    return {
        "forecast_id": getattr(forecast, "forecast_id", None),
        "status": getattr(forecast, "status", None),
        "reason": getattr(forecast, "reason", None),
        "state": getattr(forecast, "state", None),
        "artifact_id": getattr(forecast, "artifact_id", None),
        "entity": _forecast_entity(forecast),
        "model_id": getattr(inference, "model_id", None),
        "model_family": getattr(inference, "model_family", None),
        "model_version": getattr(inference, "model_version", None),
        "target": getattr(inference, "target", None),
        "target_units": getattr(inference, "target_units", None),
        "horizon": getattr(inference, "horizon", None),
        "prediction": getattr(inference, "prediction", None),
        "prediction_timestamp": getattr(inference, "prediction_timestamp", None),
        "origin_instant": getattr(inference, "origin_instant", None).isoformat()
        if isinstance(getattr(inference, "origin_instant", None), dt.datetime)
        else None,
        "carried_from_instant": getattr(inference, "carried_from_instant", None).isoformat()
        if isinstance(getattr(inference, "carried_from_instant", None), dt.datetime)
        else None,
    }


def _risk_summary(risk: Any | None) -> dict[str, Any] | None:
    """The Phase 6 facts a reader of the integrated record needs.

    No signal list and no band arithmetic: Phase 6 already serialized both, and
    reproducing them here would be a second place to keep in step with a second
    authority.
    """
    if risk is None:
        return None
    return {
        "risk_result_id": risk.risk_result_id,
        "status": risk.status,
        "evaluation_state": risk.evaluation_state,
        "risk_level": risk.risk_level,
        "risk_score": risk.risk_score,
        "risk_score_type": risk.risk_score_type,
        "forecast_id": getattr(risk, "forecast_id", None),
        "threshold": getattr(risk, "threshold", None),
        "threshold_units": getattr(risk, "threshold_units", None),
        "threshold_source": getattr(risk, "threshold_source", None),
        "threshold_policy": getattr(risk, "threshold_policy", None),
        "threshold_configuration": getattr(risk, "threshold_configuration", None),
        "residual_sigma": getattr(risk, "residual_sigma", None),
        "residual_sigma_source": getattr(risk, "residual_sigma_source", None),
        "context_digest": getattr(risk, "context_digest", None),
        "band_edges": list(getattr(risk, "band_edges", ()) or ()),
        "band_labels": list(getattr(risk, "band_labels", ()) or ()),
        "risk_configuration_version": getattr(risk, "risk_configuration_version", None),
        "production_ready_claimed": getattr(risk, "production_ready_claimed", None),
    }


def _response_summary(response: ResponseDecision | None) -> dict[str, Any] | None:
    """The Phase 7 facts a reader of the integrated record needs.

    No evidence list and no rule evaluations: Phase 7 serialized both. The policy
    *is* included, because "which response policy produced this decision" is one of
    the questions the integrated record exists to answer.
    """
    if response is None:
        return None
    return {
        "decision_id": response.decision_id,
        "decision": response.decision,
        "status": response.status,
        "entity": response.entity,
        "risk_result_id": response.risk_result_id,
        "risk_level": response.risk_level,
        "priority": response.priority,
        "rationale": response.rationale,
        "decided_at": response.decided_at.isoformat(),
        "forecast_origin": response.forecast_origin.isoformat(),
        "forecast_id": response.forecast_id,
        "forecast_horizon": response.forecast_horizon,
        "response_policy": dict(response.response_policy),
        "operational_authority": response.operational_authority,
        "production_ready_claimed": response.production_ready_claimed,
    }


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #


def default_integration_id(
    *,
    integration_status: str,
    chain: Sequence[LayerLink],
    entity: str | None,
    risk: Any | None = None,
    unusable_context: Sequence[ExposureAvailability] = (),
) -> str:
    """A readable prefix plus a sha256 over the chain's own content.

    Deterministic by construction: the same chain produces the same id, and the id
    changes when any layer's identity, the entity, the derived status, the risk
    outcome or the set of unusable contextual inputs changes. No uuid, no counter,
    no clock.

    The risk *outcome* is hashed explicitly, and that is not redundant. Phase 6's
    `risk_result_id` is a digest over the assessment's **configuration** — forecast,
    threshold policy, context digest — so two assessments of the same forecast under
    the same policy produce the **same** `risk_result_id` while recording different
    risk levels. That is correct on Phase 6's part: the id identifies the question
    asked, not the answer. But it means the layer ids alone cannot distinguish a
    MEDIUM record from a HIGH one.

    Without this field, two integrated records describing genuinely different risk
    outcomes would share an identity unless some downstream layer happened to encode
    the level into its own id — which Phase 7 currently does, incidentally. An
    identity that is correct by luck is not an identity. So the level, score and
    evaluation state are hashed directly, and the record is distinguishable because
    Phase 8 checked, not because it assumed.
    """
    payload = {
        "integration_contract_version": INTEGRATION_CONTRACT_VERSION,
        "integration_status": integration_status,
        "entity": entity,
        "chain": [link.to_dict() for link in chain],
        "risk_context_digest": getattr(risk, "context_digest", None),
        "risk_outcome": (
            None
            if risk is None
            else {
                "level": getattr(risk, "risk_level", None),
                "score": getattr(risk, "risk_score", None),
                "evaluation_state": getattr(risk, "evaluation_state", None),
                "status": getattr(risk, "status", None),
            }
        ),
        "unusable_context": sorted(
            f"{record.kind}:{record.availability}" for record in unusable_context
        ),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
    return f"integration-{entity or 'no-entity'}-{integration_status}@{digest}"


# --------------------------------------------------------------------------- #
# Chain assembly
# --------------------------------------------------------------------------- #


def _build_chain(
    forecast: ServedForecast | None,
    risk: Any | None,
    response: ResponseDecision | None,
) -> tuple[LayerLink, ...]:
    """Three slots, always, in `LAYER_ORDER`.

    An absent layer yields a slot with `status is None` rather than no slot at all.
    The ids are copied from the layers' own identifiers - never regenerated - so the
    chain answers "which forecast, which risk result, which decision" with the exact
    strings those layers published.
    """
    return (
        LayerLink(
            layer="forecast",
            layer_id=getattr(forecast, "forecast_id", None),
            status=getattr(forecast, "status", None),
            contract_version=SERVING_CONTRACT_VERSION if forecast is not None else None,
        ),
        LayerLink(
            layer="risk",
            layer_id=getattr(risk, "risk_result_id", None),
            status=getattr(risk, "status", None),
            contract_version=RISK_CONTRACT_VERSION if risk is not None else None,
        ),
        LayerLink(
            layer="response",
            layer_id=getattr(response, "decision_id", None),
            status=getattr(response, "status", None),
            contract_version=RESPONSE_CONTRACT_VERSION if response is not None else None,
        ),
    )


def _build_provenance(
    forecast: ServedForecast | None,
    risk: Any | None,
    response: ResponseDecision | None,
    *,
    integration_status: str,
    entity: str | None,
) -> dict[str, Any]:
    """The provenance chain as one mapping.

    Every key is copied from a layer that already published it. Nothing is invented
    and no key is populated with a value the owning layer did not set - the
    `None`s here mean "the layer that would have supplied this did not", which is a
    different statement from "this is empty".

    The four contract versions make it possible to tell which generation of each
    layer produced the record, so an old chain stays interpretable after a contract
    bump.
    """
    risk_provenance = getattr(risk, "provenance", None) if risk is not None else None
    response_provenance = dict(getattr(response, "provenance", {}) or {})
    return {
        "integration_contract_version": INTEGRATION_CONTRACT_VERSION,
        "serving_contract_version": SERVING_CONTRACT_VERSION,
        "risk_contract_version": RISK_CONTRACT_VERSION,
        "response_contract_version": RESPONSE_CONTRACT_VERSION,
        "response_context_version": RESPONSE_CONTEXT_VERSION,
        "integration_status": integration_status,
        "entity": entity,
        "forecast_id": getattr(forecast, "forecast_id", None),
        "model_id": getattr(getattr(forecast, "inference", None), "model_id", None),
        "model_version": getattr(getattr(forecast, "inference", None), "model_version", None),
        "artifact_id": getattr(forecast, "artifact_id", None),
        "risk_result_id": getattr(risk, "risk_result_id", None),
        "risk_configuration_version": getattr(risk, "risk_configuration_version", None),
        "risk_context_digest": getattr(risk, "context_digest", None),
        "risk_dataset_type": getattr(risk_provenance, "dataset_type", None),
        "decision_id": getattr(response, "decision_id", None),
        "response_policy_version": response_provenance.get("response_policy_version"),
        "response_policy_status": response_provenance.get("response_policy_status"),
        "operational_authority": OPERATIONAL_AUTHORITY,
        "production_ready_claimed": PRODUCTION_READY_CLAIMED,
    }


# --------------------------------------------------------------------------- #
# Explanation
# --------------------------------------------------------------------------- #


def _render_unusable(record: ExposureAvailability) -> str:
    return f"{record.kind} {record.availability} ({record.reason})"


def _explanation(
    forecast: ServedForecast | None,
    risk: Any | None,
    response: ResponseDecision | None,
    *,
    integration_status: str,
    integration_reason: str,
    chain: Sequence[LayerLink],
    evidence_availability: Mapping[str, int],
    available_inputs: Sequence[str],
    unusable: Sequence[ExposureAvailability],
    entity: str | None,
    disclaimer: str,
    synthetic_demo: bool,
) -> tuple[str, ...]:
    """Every line, derived from what the layers actually produced.

    No template can describe a layer that was not supplied, so the lines that mention
    a layer are emitted only when that layer is present.
    """
    lines: list[str] = []

    lines.append(
        f"phase 8 integration for {entity!r}: status {integration_status}. Phase 8 is an "
        "orchestration boundary: it assembles the Phase 5, Phase 6 and Phase 7 results "
        "already produced and recomputes none of the forecast, the risk or the response"
    )

    # --- the chain ---------------------------------------------------------
    lines.append(
        "chain: "
        + "; ".join(
            f"{link.layer}={link.layer_id!r} status={link.status!r}"
            for link in chain
        )
        + ". An absent layer is recorded as absent rather than omitted"
    )

    # --- what the status means here -----------------------------------------
    lines.append(
        f"integration status {integration_status}: {integration_reason}. This status "
        "describes how completely the chain was assembled; it is not a risk level, not "
        "a response category, and not a statement that any result is correct"
    )

    # --- the forecast -------------------------------------------------------
    if forecast is None:
        lines.append(
            "no Phase 5 result was supplied, so this record describes no forecast. An "
            "absent forecast is not a zero forecast and not a low risk"
        )
    elif forecast.status != STATUS_READY:
        detail = f"status {forecast.status!r}"
        if forecast.reason:
            detail += f": {forecast.reason}"
        lines.append(
            f"Phase 5 refused to serve a forecast ({detail}); Phase 6 does not assess a "
            "forecast that was never served, so no risk or response exists and none was "
            "produced here"
        )
    else:
        inference = forecast.inference
        lines.append(
            f"forecast {forecast.forecast_id!r} predicts {inference.prediction!r} "
            f"{inference.target_units or ''} for {inference.target!r} at horizon "
            f"{inference.horizon!r} from origin {inference.origin_instant.isoformat()}, "
            f"produced by {inference.model_id!r} "
            f"({inference.model_family!r}, artifact {inference.artifact_id!r}); Phase 5 "
            "remains the sole authority for whether this forecast is valid, and Phase 8 "
            "did not re-run, re-fit or fall back to another model"
        )

    # --- the risk -----------------------------------------------------------
    if risk is None:
        lines.append(
            "no Phase 6 risk result was supplied; no risk level, score, threshold or "
            "sigma is reported, because nothing about the risk was established here"
        )
    else:
        lines.append(
            f"risk {risk.risk_result_id!r} is {risk.status!r}/{risk.evaluation_state!r} "
            f"with level {risk.risk_level!r} and score {risk.risk_score!r}"
            + (f" ({risk.risk_score_type})" if risk.risk_score_type else "")
            + "; Phase 6 remains the sole authority for the exceedance probability, the "
            "threshold interpretation, the measured spread and the band classification, "
            "and Phase 8 recomputed none of them"
        )
        if risk.threshold_policy != "approved":
            lines.append(
                f"the threshold policy the risk level rests on is {risk.threshold_policy!r} "
                f"({risk.threshold_configuration}), so that level is a demo value with no "
                "official meaning"
            )

    # --- the response -------------------------------------------------------
    if response is None:
        lines.append(
            "no Phase 7 response decision was supplied, so no response category is "
            "reported; Phase 7 remains the sole authority for response classification "
            "and Phase 8 did not produce, substitute or approximate a decision"
        )
    elif response.is_withheld:
        lines.append(
            f"Phase 7 returned {response.decision} with the reason {response.rationale!r}. "
            "That decision is preserved exactly: an integration object has to exist for "
            "this record, and WITHHELD does not become MONITOR to make it convenient. "
            "Withheld is also not a claim that nothing needs attention"
        )
    else:
        lines.append(
            f"Phase 7 returned {response.decision} with the reason {response.rationale!r}; "
            "Phase 8 reports it unchanged and neither upgrades nor downgrades a response "
            "category"
        )

    # --- evidence -----------------------------------------------------------
    if evidence_availability:
        parts = ", ".join(
            f"{state}={evidence_availability[state]}" for state in sorted(evidence_availability)
        )
        lines.append(
            f"Phase 6 evaluated its declared context with {parts}; Phase 8 read that "
            "distribution and re-evaluated no signal"
        )
    if available_inputs:
        lines.append(
            "contextual inputs that were usable: " + ", ".join(available_inputs)
        )
    if unusable:
        lines.append(
            "contextual inputs that were not usable and contributed nothing: "
            + "; ".join(_render_unusable(record) for record in unusable)
            + ". An unavailable input is absent from the assessment, not counted as zero "
            "and not read as reassuring"
        )
    else:
        lines.append(
            "no declared contextual input was recorded as unusable by Phase 7; that is a "
            "statement about what was available, not a claim that the underlying data "
            "is accurate"
        )

    # --- GIS and history, carried forward -----------------------------------
    gis_available, gis_reason, historical_available, historical_reason = _gis_and_history(risk)
    if not gis_available:
        lines.append(
            f"spatial context was carried forward as unavailable ({gis_reason}); Phase 8 "
            "computes no river distance, elevation, floodplain, road access or "
            "infrastructure exposure, and draws no spatial conclusion of any kind"
        )
    if not historical_available:
        lines.append(
            f"historical flood context was carried forward as unavailable "
            f"({historical_reason}); no flood event was invented to enrich this record, "
            "and the absence is not evidence that this location has never flooded"
        )

    # --- authority ----------------------------------------------------------
    lines.append(
        "this record carries no operational or government authority: it is not a flood "
        "warning, not an evacuation instruction and not an emergency declaration, and "
        "this repository provides none of those"
    )
    if response is not None and not response.is_withheld:
        lines.append(RECOMMENDATION_DISCLAIMER)
    lines.append(
        f"production_ready_claimed is {PRODUCTION_READY_CLAIMED} and operational_authority "
        f"is {OPERATIONAL_AUTHORITY}; no configuration or code path in this module sets "
        "either true"
    )
    lines.append(
        "this is a domain contract with deterministic serialization; exposing it through "
        "an HTTP API is a later integration step and no service boundary exists on this "
        "branch"
    )
    if synthetic_demo:
        lines.append(disclaimer)

    return tuple(lines)


# --------------------------------------------------------------------------- #
# The boundary
# --------------------------------------------------------------------------- #


def integrate(
    forecast: ServedForecast | None,
    risk: Any | None = None,
    response: ResponseDecision | None = None,
    *,
    integration_id: str | None = None,
) -> IntegratedForecastAssessment:
    """Assemble the three already-produced layer results into one record.

    This is orchestration and nothing else. No forecast is produced, no probability is
    computed, no threshold is interpreted, no band is classified and no response is
    mapped - every one of those belongs to the layer that owns it, and this function
    reads their results the way a reader reads a report.

    **Raises** an `IntegrationBoundaryError` subclass for a contract violation: a
    supplied object of the wrong type, a downstream layer present while an upstream
    one is absent, two layers describing different entities, or two layers disagreeing
    about which forecast this is. Those are mistakes in what the caller passed, and a
    caller that is told is better than one handed a plausible-looking mixture.

    **Returns** a record with a derived `integration_status` for every *availability*
    condition: no forecast, a refused forecast, no risk result, a risk result with no
    level, a missing response, a withheld response, an unreadable context, or missing
    contextual inputs. Those are honest states of the world, and the record names the
    one that decided the status.

    There is deliberately no `integration_status` parameter. A caller that could
    assert its chain is `COMPLETE` could paper over an upstream bug, and the status
    would stop meaning anything.
    """
    forecast = _require_forecast(forecast)
    risk = _require_risk(risk)
    response = _require_response(response)

    _require_sequence(forecast, risk, response)
    _check_entity(forecast, risk, response)
    _check_chain(forecast, risk, response)

    status, reason = _derive_status(forecast, risk, response)

    chain = _build_chain(forecast, risk, response)
    unusable = tuple(
        record
        for record in (getattr(response, "unavailable_context", ()) or ())
        if not record.usable
    )
    evidence_availability = dict(getattr(risk, "availability_counts", {}) or {})
    available_inputs = tuple(
        signal.name for signal in (getattr(risk, "usable_signals", ()) or ())
    )

    entity = _forecast_entity(forecast)
    disclaimer = _disclaimer(forecast, risk, response)
    synthetic_demo = _synthetic_demo(forecast, risk, response)
    data_status = _data_status(forecast, risk, response)
    integrated_at = _integrated_at(forecast)

    inference = getattr(forecast, "inference", None)
    gis_available, gis_reason, historical_available, historical_reason = _gis_and_history(risk)

    return IntegratedForecastAssessment(
        integration_id=integration_id
        or default_integration_id(
            integration_status=status,
            chain=chain,
            entity=entity,
            risk=risk,
            unusable_context=unusable,
        ),
        integration_status=status,
        integration_reason=reason,
        entity=entity,
        forecast=forecast,
        risk=risk,
        response=response,
        chain=chain,
        provenance=_build_provenance(
            forecast, risk, response, integration_status=status, entity=entity
        ),
        evidence_availability=evidence_availability,
        available_inputs=available_inputs,
        unusable_context=unusable,
        explanation=_explanation(
            forecast,
            risk,
            response,
            integration_status=status,
            integration_reason=reason,
            chain=chain,
            evidence_availability=evidence_availability,
            available_inputs=available_inputs,
            unusable=unusable,
            entity=entity,
            disclaimer=disclaimer,
            synthetic_demo=synthetic_demo,
        ),
        forecast_id=getattr(forecast, "forecast_id", None),
        forecast_status=getattr(forecast, "status", None),
        forecast_origin=integrated_at,
        forecast_horizon=getattr(inference, "horizon", None),
        prediction=getattr(inference, "prediction", None),
        prediction_units=getattr(inference, "target_units", None),
        model_id=getattr(inference, "model_id", None),
        model_version=getattr(inference, "model_version", None),
        artifact_id=getattr(forecast, "artifact_id", None),
        risk_result_id=getattr(risk, "risk_result_id", None),
        risk_status=getattr(risk, "status", None),
        risk_evaluation_state=getattr(risk, "evaluation_state", None),
        risk_level=getattr(risk, "risk_level", None),
        risk_score=getattr(risk, "risk_score", None),
        risk_score_type=getattr(risk, "risk_score_type", None),
        response_decision=getattr(response, "decision", None),
        response_status=getattr(response, "status", None),
        response_decision_id=getattr(response, "decision_id", None),
        gis_available=gis_available,
        gis_reason=gis_reason,
        historical_available=historical_available,
        historical_reason=historical_reason,
        integrated_at=integrated_at,
        synthetic_demo=synthetic_demo,
        data_status=data_status,
        disclaimer=disclaimer,
    )


def integrate_safe(
    forecast: ServedForecast | None,
    risk: Any | None = None,
    response: ResponseDecision | None = None,
    *,
    integration_id: str | None = None,
) -> IntegratedForecastAssessment:
    """`integrate`, with contract violations converted into a recorded result.

    For a caller that must answer rather than fail. The returned record is
    `NOT_EVALUABLE` with the violation's `reason` in both `error_reason` and
    `integration_reason`, so nothing is lost by not raising - which is the same split
    Phase 6 and Phase 7 made, for the same reason.

    It is deliberately not the default: a caller who swallows a boundary error without
    reading the reason has turned a refusal into an unnoticed one.
    """
    try:
        return integrate(forecast, risk, response, integration_id=integration_id)
    except Exception as error:  # noqa: BLE001 - the contract is to answer, not fail
        return integration_from_error(
            error,
            forecast=forecast,
            risk=risk,
            response=response,
            integration_id=integration_id or "integration-not-evaluable",
        )


def _reportable_forecast(value: Any) -> ServedForecast | None:
    """`value` when it is a `ServedForecast`, otherwise `None`.

    Used only where a layer is being *reported* rather than used, which is the error
    path. Reporting a malformed object as though it were a layer result would be a
    lie, and raising from inside the error handler would turn a refusal into a
    traceback.
    """
    return value if isinstance(value, ServedForecast) else None


def _reportable_risk(value: Any) -> Any | None:
    if value is not None and all(hasattr(value, name) for name in _RISK_LAYER_FIELDS):
        return value
    return None


def _reportable_response(value: Any) -> ResponseDecision | None:
    if isinstance(value, ResponseDecision) and value.decision in RESPONSE_STATES:
        return value
    return None


def integration_from_error(
    error: Exception,
    *,
    forecast: Any = None,
    risk: Any = None,
    response: Any = None,
    integration_id: str = "integration-not-evaluable",
) -> IntegratedForecastAssessment:
    """The record for an integration that could not be assembled.

    Names `error.reason` in `error_reason` so a refusal is countable rather than
    something to be parsed out of prose, and tolerates any exception - not only an
    `IntegrationBoundaryError` - because a caller reaching for this has usually
    already decided not to fail.

    Whatever layers *were* recognisable are still carried, so the reader can see how
    far the chain got. Anything unrecognisable is dropped rather than reported, because
    the alternative is a record asserting a layer that cannot be identified.

    The status is `NOT_EVALUABLE`, never `COMPLETE`: a chain that hit a violation has
    not been assembled, and reporting it as complete is precisely the silent
    downgrade this module exists to prevent.
    """
    reported_forecast = _reportable_forecast(forecast)
    reported_risk = _reportable_risk(risk)
    reported_response = _reportable_response(response)

    reason = str(getattr(error, "reason", "error"))
    detail = f"{reason}: {error}"

    status = INTEGRATION_NOT_EVALUABLE
    chain = _build_chain(reported_forecast, reported_risk, reported_response)
    entity = _forecast_entity(reported_forecast)
    unusable = tuple(
        record
        for record in (getattr(reported_response, "unavailable_context", ()) or ())
        if not record.usable
    )
    evidence_availability = dict(getattr(reported_risk, "availability_counts", {}) or {})
    available_inputs = tuple(
        signal.name for signal in (getattr(reported_risk, "usable_signals", ()) or ())
    )
    disclaimer = _disclaimer(reported_forecast, reported_risk, reported_response)
    synthetic_demo = _synthetic_demo(reported_forecast, reported_risk, reported_response)
    data_status = _data_status(reported_forecast, reported_risk, reported_response)
    integrated_at = _integrated_at(reported_forecast)
    inference = getattr(reported_forecast, "inference", None)
    gis_available, gis_reason, historical_available, historical_reason = _gis_and_history(
        reported_risk
    )

    return IntegratedForecastAssessment(
        integration_id=integration_id,
        integration_status=status,
        integration_reason=(
            f"the chain could not be assembled: {detail}. No layer was recomputed and no "
            "result was substituted; whatever layers were recognisable are reported below "
            "and the refusal is recorded rather than resolved"
        ),
        entity=entity,
        forecast=reported_forecast,
        risk=reported_risk,
        response=reported_response,
        chain=chain,
        provenance=_build_provenance(
            reported_forecast,
            reported_risk,
            reported_response,
            integration_status=status,
            entity=entity,
        ),
        evidence_availability=evidence_availability,
        available_inputs=available_inputs,
        unusable_context=unusable,
        explanation=_explanation(
            reported_forecast,
            reported_risk,
            reported_response,
            integration_status=status,
            integration_reason=f"the chain could not be assembled: {detail}",
            chain=chain,
            evidence_availability=evidence_availability,
            available_inputs=available_inputs,
            unusable=unusable,
            entity=entity,
            disclaimer=disclaimer,
            synthetic_demo=synthetic_demo,
        )
        + (
            f"integration refused: {detail}. An unassembled chain is recorded as "
            "NOT_EVALUABLE; it is never reported as complete, and it is never "
            "downgraded into a lower risk or a monitoring instruction",
        ),
        forecast_id=getattr(reported_forecast, "forecast_id", None),
        forecast_status=getattr(reported_forecast, "status", None),
        forecast_origin=integrated_at,
        forecast_horizon=getattr(inference, "horizon", None),
        prediction=getattr(inference, "prediction", None),
        prediction_units=getattr(inference, "target_units", None),
        model_id=getattr(inference, "model_id", None),
        model_version=getattr(inference, "model_version", None),
        artifact_id=getattr(reported_forecast, "artifact_id", None),
        risk_result_id=getattr(reported_risk, "risk_result_id", None),
        risk_status=getattr(reported_risk, "status", None),
        risk_evaluation_state=getattr(reported_risk, "evaluation_state", None),
        risk_level=getattr(reported_risk, "risk_level", None),
        risk_score=getattr(reported_risk, "risk_score", None),
        risk_score_type=getattr(reported_risk, "risk_score_type", None),
        response_decision=getattr(reported_response, "decision", None),
        response_status=getattr(reported_response, "status", None),
        response_decision_id=getattr(reported_response, "decision_id", None),
        gis_available=gis_available,
        gis_reason=gis_reason,
        historical_available=historical_available,
        historical_reason=historical_reason,
        integrated_at=integrated_at,
        error_reason=reason,
        synthetic_demo=synthetic_demo,
        data_status=data_status,
        disclaimer=disclaimer,
    )


# --------------------------------------------------------------------------- #
# The contract, described
# --------------------------------------------------------------------------- #


def integration_contract_description() -> dict[str, Any]:
    """The integration contract as data, for a report or a review."""
    return {
        "integration_contract_version": INTEGRATION_CONTRACT_VERSION,
        "architecture": (
            "Phase 5 ServedForecast -> Phase 6 RiskResult -> Phase 7 ResponseDecision -> "
            "Phase 8 IntegratedForecastAssessment -> deterministic serialized analytical "
            "result"
        ),
        "consumes": "Phase 5, Phase 6 and Phase 7 results, all read-only",
        "integration_states": list(INTEGRATION_STATES),
        "state_meanings": {
            INTEGRATION_COMPLETE: (
                "every layer produced a valid result and every declared contextual input "
                "was usable"
            ),
            INTEGRATION_PARTIAL: (
                "the analytical chain is valid and preserved, but at least one declared "
                "contextual input was not usable and is named"
            ),
            INTEGRATION_WITHHELD: (
                "a valid chain exists but no response interpretation may be made from "
                "it: Phase 7 withheld, Phase 7 produced nothing, or Phase 6 read no "
                "context at all"
            ),
            INTEGRATION_NOT_EVALUABLE: (
                "the forecast or risk contract itself cannot be evaluated from what was "
                "supplied: no forecast, a refused forecast, no risk result, or a risk "
                "result carrying no level"
            ),
        },
        "status_is_derived": (
            "integrate accepts no integration_status argument, so no caller can assert "
            "that its chain is COMPLETE. The order of the derivation is fixed and tested: "
            "first unmet condition wins"
        ),
        "status_derivation_order": [
            "no forecast",
            "forecast status is not 'ready'",
            "'ready' forecast carrying no inference",
            "no risk result",
            "risk result with no level, not recorded, or not evaluable",
            "no response decision",
            "response decision withheld",
            "risk context_unavailable",
            "risk partially_evaluated or any unusable contextual input",
            "otherwise COMPLETE",
        ],
        "accepts": "ServedForecast | None, RiskResult | None, ResponseDecision | None",
        "bare_forecast_inference_refused": (
            "a bare ForecastInference carries no forecast id and no serving status, and "
            "Phase 8 will not invent either; Phase 5 serves it instead"
        ),
        "forecast_authority": (
            "Phase 5 owns forecast validity, artifact resolution, model selection and "
            "serving. Phase 8 re-runs nothing, fits nothing and falls back to no other "
            "model; a forecast that was refused is reported as refused"
        ),
        "risk_authority": (
            "Phase 6 owns the exceedance probability, threshold interpretation, measured "
            "spread and band classification. Phase 8 contains no threshold arithmetic, no "
            "normal CDF, no sigma estimation and no band logic, and recomputes nothing"
        ),
        "response_authority": (
            "Phase 7 is the sole authority for response classification. Phase 8 never "
            "reinterprets a risk level, never downgrades REVIEW_WARNING, never upgrades "
            "MONITOR, never replaces WITHHELD and invents no emergency state"
        ),
        "no_downgrade": (
            "a WITHHELD decision enters and leaves as WITHHELD, whatever the integration "
            "status. The status and the recommendation are independent axes"
        ),
        "no_composite_score": (
            "there is no integration_score, final_risk_score, danger_score, severity_score "
            "or response_score field. Phases 6 and 7 declined to invent a weighted "
            "composite and Phase 8 adds no third one; with nothing to weight, no composite "
            "can be assembled downstream either"
        ),
        "no_exposure_values": (
            "Phase 8 reads the availability records Phase 7 produced and never a count. "
            "ExposureAvailability has no value field and Phase 8 adds none, so "
            "risk x population cannot be written here at all"
        ),
        "chain": (
            "a three-slot tuple in the fixed order (forecast, risk, response). An absent "
            "layer is a slot with no status rather than a missing slot, so 'Phase 7 "
            "produced nothing' is assertable in one comparison"
        ),
        "projections_not_copies": (
            "the flat repeating fields are projections, and __post_init__ checks each one "
            "against the object it came from, so a projection cannot disagree with its "
            "source"
        ),
        "disclaimer_rule": (
            "the first non-empty disclaimer carried by response, risk then forecast, "
            "falling back to the canonical synthetic/demo sentence. risk_from_error builds "
            "a RiskResult with an empty disclaimer, and an empty disclaimer must not "
            "survive to the integrated record"
        ),
        "no_clock": (
            "integrated_at is the forecast origin, or None when there is no forecast. "
            "Nothing in this module reads a clock"
        ),
        "no_randomness": (
            "integration_id is a readable prefix plus sha256 over the chain's own content. "
            "No uuid, no random, no secrets"
        ),
        "immutability": (
            "IntegratedForecastAssessment is a frozen dataclass and holds the three layer "
            "results by reference. Mappings are wrapped read-only; nothing upstream is "
            "mutated, copied or normalized"
        ),
        "availability_vocabulary": (
            "Phase 6's states - valid, missing, unavailable, not_applicable, stale - are "
            "reused verbatim through Phase 7's records and are never mapped to 0, False, "
            "safe, low or none"
        ),
        "gis_absent_marker": NOT_AVAILABLE,
        "gis_note": (
            "GIS and historical availability are carried forward from Phase 6 verbatim. "
            "Phase 8 computes no river distance, elevation, floodplain status, road access "
            "or infrastructure exposure, and draws no spatial or historical conclusion"
        ),
        "service_boundary": (
            "none. This branch has no HTTP boundary, so Phase 8 is a pure domain contract "
            "with deterministic serialization. No framework, router or endpoint is created "
            "here"
        ),
        "quantum_boundary": (
            "none. No QUBO, no quantum-service call, no sensor placement, no combinatorial "
            "optimisation. Choosing what to do about a catchment remains the "
            "optimisation layer's job, on the far side of this one"
        ),
        "operational_authority": OPERATIONAL_AUTHORITY,
        "production_ready_claimed": PRODUCTION_READY_CLAIMED,
        "errors_are_raised_not_swallowed": (
            "contract violations raise an IntegrationBoundaryError; availability "
            "conditions return a derived status. integrate_safe converts the former into "
            "the latter for callers that must answer rather than fail"
        ),
        "errors": [
            cls.reason
            for cls in (
                InvalidForecastResultError,
                InvalidResponseDecisionError,
                LayerSequenceError,
                ChainMismatchError,
                InvalidIntegrationStatusError,
            )
        ],
        "reused_errors": [
            InvalidRiskResultError.reason,
            EntityMismatchError.reason,
            FutureContextError.reason,
        ],
        "determinism": (
            "the same three layer results always produce the same integration_id, the same "
            "explanation and the same to_json() text. Re-running the integration over "
            "unchanged evidence changes nothing, including the timestamp"
        ),
    }


__all__ = [
    "INTEGRATION_COMPLETE",
    "INTEGRATION_CONTRACT_VERSION",
    "INTEGRATION_NOT_EVALUABLE",
    "INTEGRATION_PARTIAL",
    "INTEGRATION_STATES",
    "INTEGRATION_WITHHELD",
    "LAYER_ORDER",
    "OPERATIONAL_AUTHORITY",
    "PRODUCTION_READY_CLAIMED",
    "ChainMismatchError",
    "EntityMismatchError",
    "FutureContextError",
    "IntegrationBoundaryError",
    "IntegratedForecastAssessment",
    "InvalidForecastResultError",
    "InvalidIntegrationStatusError",
    "InvalidResponseDecisionError",
    "InvalidRiskResultError",
    "LayerLink",
    "LayerSequenceError",
    "ResponseDecision",
    "ServedForecast",
    "default_integration_id",
    "integrate",
    "integrate_safe",
    "integration_contract_description",
    "integration_from_error",
]


# --------------------------------------------------------------------------- #
# Status derivation
# --------------------------------------------------------------------------- #


def _derive_status(
    forecast: ServedForecast | None,
    risk: Any | None,
    response: ResponseDecision | None,
) -> tuple[str, str]:
    """The integration status and the condition that decided it.

    The order is fixed and tested, because a status with several applicable
    conditions needs one answer and the reader needs to know which condition gave
    it. First unmet precondition wins, exactly as Phase 7's withholding order does.

    Two properties are load-bearing:

    * Nothing is ever downgraded into `COMPLETE`. The only route to `COMPLETE` is the
      last branch, and it is reachable only after every earlier condition has passed.
    * The status never rewrites a response decision. Branch six reports `WITHHELD`
      while leaving the `ResponseDecision` exactly as Phase 7 built it.
    """
    if forecast is None:
        return INTEGRATION_NOT_EVALUABLE, (
            "no Phase 5 served forecast was supplied; there is no analytical chain to "
            "integrate, and Phase 8 does not produce a forecast"
        )

    if forecast.status != STATUS_READY:
        detail = f"status {forecast.status!r}"
        if forecast.reason:
            detail += f": {forecast.reason}"
        return INTEGRATION_NOT_EVALUABLE, (
            f"Phase 5 refused to serve a forecast ({detail}); a chain that begins with "
            "a refusal cannot be reported as complete, and an absent forecast is not "
            "a low risk"
        )

    if forecast.inference is None:
        return INTEGRATION_NOT_EVALUABLE, (
            "the Phase 5 result is 'ready' but carries no inference, so there is no "
            "prediction, origin or horizon to integrate"
        )

    if risk is None:
        return INTEGRATION_NOT_EVALUABLE, (
            "no Phase 6 risk result was supplied; Phase 8 integrates a risk "
            "assessment Phase 6 already produced and never assesses risk itself"
        )

    if (
        risk.risk_level is None
        or risk.status != RISK_STATUS_RECORDED
        or risk.evaluation_state == CONTEXT_NOT_EVALUABLE
    ):
        return INTEGRATION_NOT_EVALUABLE, (
            f"Phase 6 recorded no risk level (status {risk.status!r}, evaluation state "
            f"{risk.evaluation_state!r}); nothing downstream can be evaluated from a "
            "result with no level, and Phase 8 will not assign one"
        )

    if response is None:
        return INTEGRATION_WITHHELD, (
            "Phase 7 produced no response decision; the forecast and risk results "
            "above are preserved exactly as produced, and no response category is "
            "recommended because none was supplied and Phase 8 does not invent one"
        )

    if response.is_withheld:
        return INTEGRATION_WITHHELD, (
            f"Phase 7 withheld the response: {response.rationale}; withholding is "
            "preserved rather than resolved into a recommendation, and a decision of "
            "WITHHELD is not the same claim as recommending that nothing be done"
        )

    if risk.evaluation_state == CONTEXT_UNAVAILABLE:
        return INTEGRATION_WITHHELD, (
            "Phase 6 could read no context at all, so the risk level rests on the "
            "forecast alone with nothing corroborating it; the integration refuses to "
            "report a complete or partial result over that, and the Phase 7 decision "
            "is carried through unchanged"
        )

    gaps = tuple(record for record in response.unavailable_context if not record.usable)
    partial_context = risk.evaluation_state == CONTEXT_PARTIALLY_EVALUATED
    if partial_context or gaps:
        reasons: list[str] = []
        if partial_context:
            reasons.append(
                f"Phase 6 evaluated the context only partially (state "
                f"{risk.evaluation_state!r})"
            )
        if gaps:
            reasons.append(
                "declared contextual input(s) were not usable: "
                + "; ".join(f"{record.kind} {record.availability}" for record in gaps)
            )
        return INTEGRATION_PARTIAL, (
            "the analytical chain is valid and preserved exactly as produced, but "
            + " and ".join(reasons)
            + ". Every gap is named rather than counted as zero, and an unavailable "
            "input is not read as reassuring"
        )

    return INTEGRATION_COMPLETE, (
        "every layer produced a valid result and every declared contextual input was "
        "usable; this states that the chain was assembled completely, and says nothing "
        "about whether the response is correct, approved or operational"
    )