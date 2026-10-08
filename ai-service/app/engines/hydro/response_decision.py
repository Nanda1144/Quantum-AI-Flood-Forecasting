# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/app/engines/hydro | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 7: the risk-to-response decision boundary.

What this layer is
------------------

Phase 6 produced a `RiskResult`. This module answers exactly one question about
it: *which response category does the configured policy assign, and on what
evidence?* It answers that question and nothing else.

What this layer is not
----------------------

It is **not** a second risk engine. It calls no risk mathematics. There is no
probability here, no threshold, no sigma, no band edge. `exceedance_probability`,
`classify_risk_level` and the threshold policy remain Phase 6's alone, and the
risk level this module reads is the one Phase 6 already assigned. If Phase 7
recomputed it, the two layers could disagree and there would be no way to tell
which was right.

It is **not** an authority. `WITHHELD`, `MONITOR`, `HEIGHTENED_MONITORING` and
`REVIEW_WARNING` are recommendations about attention. None of them is an
evacuation, an emergency, or an instruction to anyone. `EVACUATE`,
`MANDATORY_EVACUATION` and `EMERGENCY_DECLARED` are deliberately absent from
`RESPONSE_STATES`, so a policy that tried to configure one would be refused -
which is a stronger outcome than documenting that we would not honour it.

It is **not** an optimiser. Nothing here calls quantum-service, a QUBO builder,
a sensor-placement optimiser, or any combinatorial search. Choosing *what to do
about* a catchment is the optimisation layer's job, on the far side of this one.

Why WITHHELD is the default
---------------------------

Because no authoritative response policy exists in this repository.

`ResponsePolicy()` with no mapping is unusable, and an unusable policy yields
`WITHHELD` - the same shape as Phase 6, where a `RiskPolicy` with no threshold
yields a withheld risk level. This is not a stub waiting to be filled in with
something plausible; it is the honest state of a repository that has no approved
flood-warning criteria and no signed-off response matrix.

The three states that *can* be produced are reached only when somebody explicitly
configures a mapping and says where it came from. A DEMO mapping is honoured as a
DEMO mapping: the decision is computed, and it is labelled `synthetic/demo`,
`policy_status='pending'` and `operational_authority=False` on every surface.

The design decision worth arguing for
-------------------------------------

An earlier draft of this phase proposed a weighted composite - severity weighted
by population, adjusted by infrastructure, nudged by historical frequency. It was
dropped, and the reason is the same one that dropped it in Phase 6: the weights
would have to be invented, and an invented composite is worse than no composite,
because it looks like a measurement.

So `ResponseDecision` has no score at all. Not a low-weight score, not a score
that defaults to zero - no field named `response_score`, `severity_score` or
`danger_score`. There is nothing to combine, so there is nothing to combine
*with*. What a decision carries instead is `evidence`: the risk level, the risk
score, the configured mapping, and a `contributed` flag on each item saying
whether it actually moved the decision.

That flag is what makes "missing is not zero" checkable rather than merely
intended. An unavailable input appears in `unavailable_context` and in the
explanation as *"population context was unavailable and did not contribute to this
decision"* - never as a contributor with a value of zero, which is what a
weighted sum would have produced.

Raise-only, and never above the configured ceiling
--------------------------------------------------

Rules may only move a decision **up** in severity, for the same reason Phase 6's
escalation rules are raise-only: a rule that could lower a category would be a
second, silent risk classifier, and one that could raise it past the policy's own
declared maximum would be a rule overriding the policy that authorised it.

Errors versus states
--------------------

The same split Phase 6 uses, for the same reason. A contract violation is
something the caller did wrong and should be told about; an availability
condition is a fact about the world that belongs in the result.

``decide_response`` raises ``ResponseBoundaryError`` subclasses and returns a
``WITHHELD`` decision for availability conditions. ``decide_response_safe``
converts the former into the latter, so a caller that must answer rather than
fail has one call to make. No error path returns `MONITOR`, and none returns
`WITHHELD` with a risk level attached.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from app.engines.hydro.contract import SUPPORTED_RISK_LEVELS, priority_for_risk_level
from app.engines.hydro.domains import NOT_AVAILABLE
from app.engines.hydro.forecast_risk import RISK_CONTRACT_VERSION
from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER
from app.engines.hydro.risk_context import (
    CONTEXT_NOT_EVALUABLE,
    CONTEXT_UNAVAILABLE,
    EntityMismatchError,
    FutureContextError,
)
from app.engines.hydro.response_context import (
    RESPONSE_AVAILABILITY,
    RESPONSE_CONTEXT_VERSION,
    ExposureAvailability,
    InvalidResponseContextError,
    InvalidRiskResultError,
    MissingRiskResultError,
    ResponseBoundaryError,
    ResponseContext,
)

RESPONSE_CONTRACT_VERSION = "navya-phase7-response/v1"
RESPONSE_POLICY_VERSION = "navya-phase7-response-policy/v1"

# --------------------------------------------------------------------------- #
# The response vocabulary
# --------------------------------------------------------------------------- #

#: The four states Phase 7 can produce. Nothing else is representable.
#:
#: `WITHHELD` is the absence of a recommendation, not a severity - it is the state
#: a caller reaches when the evidence or the policy could not support one. The
#: other three are ordered by how much attention they ask for.
#:
#: There is deliberately no `EVACUATE`, no `MANDATORY_EVACUATION` and no
#: `EMERGENCY_DECLARED`. This repository has no approved warning criteria, no
#: authority to issue a warning, and no population or infrastructure data with
#: which to justify one. Naming such a state here would imply the capability
#: exists; leaving it out means the vocabulary itself refuses it.
RESPONSE_STATES: tuple[str, ...] = (
    "WITHHELD",
    "MONITOR",
    "HEIGHTENED_MONITORING",
    "REVIEW_WARNING",
)

DECISION_WITHHELD = "WITHHELD"
DECISION_MONITOR = "MONITOR"
DECISION_HEIGHTENED_MONITORING = "HEIGHTENED_MONITORING"
DECISION_REVIEW_WARNING = "REVIEW_WARNING"

#: Severity order, for the raise-only rule check. `WITHHELD` sits below everything
#: because a rule must never be able to *create* a recommendation out of the
#: absence of one - `required=False` on an unmet rule leaves the decision alone.
RESPONSE_SEVERITY: Mapping[str, int] = MappingProxyType(
    {
        DECISION_WITHHELD: 0,
        DECISION_MONITOR: 1,
        DECISION_HEIGHTENED_MONITORING: 2,
        DECISION_REVIEW_WARNING: 3,
    }
)

#: States a configured policy may map a risk level onto. Excludes `WITHHELD`,
#: because "map LOW to WITHHELD" would be a policy asserting that a low risk
#: deserves no attention - a claim, not an absence, and not one this repository
#: can make.
POLICY_TARGET_STATES: tuple[str, ...] = RESPONSE_STATES[1:]

#: Permanently false. No configuration, environment variable, or code path in this
#: module sets it true, because this repository has no authority to grant it and no
#: evidence to support it. It exists so a consumer can assert on it rather than
#: have to trust the absence of a claim.
OPERATIONAL_AUTHORITY = False

#: Permanently false, for the same reason and by the same mechanism Phase 6
#: carries `production_ready_claimed = False`.
PRODUCTION_READY_CLAIMED = False


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class InvalidResponsePolicyError(ResponseBoundaryError):
    """The configured policy cannot be interpreted as a response policy."""

    reason = "invalid_response_policy"


class UnsupportedResponseStateError(ResponseBoundaryError):
    """Something asserted a response state outside `RESPONSE_STATES`.

    Raised rather than coerced. `EVACUATE` is the case that matters: if a caller
    asks for one, the honest answer is that this layer cannot provide it, and
    quietly mapping it to the nearest state it *can* provide would be the most
    dangerous single behaviour available here.
    """

    reason = "unsupported_response_state"


# --------------------------------------------------------------------------- #
# Policy
# --------------------------------------------------------------------------- #


def _require_text(value: Any, name: str, error: type[ResponseBoundaryError]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error(f"{name} must be a non-empty string, got {value!r}")
    return value


def _require_policy(policy: Any) -> ResponsePolicy:
    """One check, one message, on every path that accepts a policy.

    A bare mapping is refused on purpose. It would carry no source, no status and no
    version, and a decision made under one could not be audited afterwards - there
    would be nothing in the result saying which mapping produced it.
    """
    if not isinstance(policy, ResponsePolicy):
        raise InvalidResponsePolicyError(
            f"policy must be a ResponsePolicy, got {type(policy).__name__}; phase 7 "
            "reuses that policy rather than accepting an arbitrary mapping"
        )
    return policy


def _reportable_policy(policy: Any) -> ResponsePolicy:
    """`policy` if it is one, otherwise an empty one.

    Used only where a policy is being *reported* rather than applied - the error
    paths, where the caller is already being told the decision was refused and the
    policy they passed is not going to be applied anyway. Reporting the unusable
    object would raise inside the error handler, which is the one place that must
    not fail.
    """
    return policy if isinstance(policy, ResponsePolicy) else ResponsePolicy()


@dataclass(frozen=True)
class ResponsePolicy:
    """Which response category each risk level maps onto, with its provenance.

    A **mapping is required** and must be supplied by whoever has the authority to
    decide what a risk level means operationally. There is no default mapping,
    because a default would be this module inventing a warning matrix.

    `is_usable` is therefore false for a bare `ResponsePolicy()`, and
    `decide_response` on one yields `WITHHELD` with the reason stated in the
    explanation.
    """

    risk_level_response: Mapping[str, str] = field(default_factory=dict)
    policy_status: str = "pending"
    policy_source: str = ""
    policy_version: str = RESPONSE_POLICY_VERSION
    policy_reference: str | None = None
    reviewed_by: str | None = None
    reviewed_at: dt.datetime | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.risk_level_response, Mapping):
            raise InvalidResponsePolicyError(
                "ResponsePolicy.risk_level_response must be a mapping from risk level to "
                f"response category, got {type(self.risk_level_response).__name__}"
            )
        for level, response in self.risk_level_response.items():
            if level not in SUPPORTED_RISK_LEVELS:
                raise InvalidResponsePolicyError(
                    f"policy key {level!r} is not among Phase 6's risk levels "
                    f"{list(SUPPORTED_RISK_LEVELS)}; a policy cannot map a risk level "
                    "the risk layer cannot emit"
                )
            if response not in RESPONSE_STATES:
                raise UnsupportedResponseStateError(
                    f"policy maps {level!r} to {response!r}, which is not one of "
                    f"{list(RESPONSE_STATES)}. Phase 7 does not provide evacuation, "
                    "mandatory evacuation, or emergency declaration, and will not "
                    "approximate one with the nearest state it does provide"
                )
            if response not in POLICY_TARGET_STATES:
                raise InvalidResponsePolicyError(
                    f"policy maps {level!r} to {DECISION_WITHHELD!r}; a mapping states "
                    "what a risk level warrants, and WITHHELD is the absence of a "
                    "recommendation rather than a recommendation of its own"
                )

        _require_text(self.policy_status, "ResponsePolicy.policy_status", InvalidResponsePolicyError)
        if self.reviewed_at is not None:
            if not isinstance(self.reviewed_at, dt.datetime):
                raise InvalidResponsePolicyError(
                    f"ResponsePolicy.reviewed_at must be a datetime or None, got "
                    f"{type(self.reviewed_at).__name__}"
                )
            if self.reviewed_at.tzinfo is None or self.reviewed_at.tzinfo.utcoffset(
                self.reviewed_at
            ) is None:
                raise FutureContextError(
                    f"ResponsePolicy.reviewed_at must be timezone-aware, got "
                    f"{self.reviewed_at!r}; a review with no instant cannot be audited"
                )
        if self.policy_source:
            _require_text(
                self.policy_source, "ResponsePolicy.policy_source", InvalidResponsePolicyError
            )
        _require_text(self.policy_version, "ResponsePolicy.policy_version", InvalidResponsePolicyError)

        object.__setattr__(
            self,
            "risk_level_response",
            MappingProxyType(dict(sorted(self.risk_level_response.items()))),
        )

    # --- derived -----------------------------------------------------------

    @property
    def is_usable(self) -> bool:
        """True when at least one risk level has been mapped.

        A policy that maps only some levels is usable but incomplete: a decision
        on an unmapped level is `WITHHELD` with that fact named, rather than
        defaulted to the nearest mapped level.
        """
        return bool(self.risk_level_response)

    @property
    def mapped_levels(self) -> tuple[str, ...]:
        return tuple(sorted(self.risk_level_response))

    @property
    def highest_mapped_state(self) -> str | None:
        """The most severe state this policy can produce, or `None` if it maps none."""
        if not self.risk_level_response:
            return None
        return max(
            self.risk_level_response.values(),
            key=lambda state: RESPONSE_SEVERITY[state],
        )

    def describe(self) -> str:
        if not self.is_usable:
            return (
                "no response mapping is configured, so no response category can be "
                "recommended; this repository has no approved warning criteria"
            )
        pairs = ", ".join(
            f"{level}->{self.risk_level_response[level]}"
            for level in self.mapped_levels
        )
        source = self.policy_source or "an unrecorded source"
        return (
            f"response mapping ({pairs}) from {source}; policy status "
            f"{self.policy_status!r}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_level_response": dict(self.risk_level_response),
            "mapped_levels": list(self.mapped_levels),
            "usable": self.is_usable,
            "policy_status": self.policy_status,
            "policy_source": self.policy_source,
            "policy_version": self.policy_version,
            "policy_reference": self.policy_reference,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "operational_authority": OPERATIONAL_AUTHORITY,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ResponseRule:
    """Raise the response category when the risk level is at or above a level.

    The condition is a **risk level**, not a signal value, and that is deliberate.
    Phase 6 already owns signal-threshold comparison (`RiskEscalationRule`),
    including unit conversion and the raise-only guarantee. A signal-based rule
    here would be a second implementation of the same machinery with a different
    set of bugs, and the risk level is the one thing Phase 6 has definitively
    evaluated and Phase 7 is entitled to read.

    A rule may only raise. `escalate_to` below the current category is recorded as
    `fired` with `applied=False` and a reason, so a misconfigured rule is visible
    rather than silently inert.

    There is deliberately **no `required` flag**. Phase 6 needed one, because a
    rule there can depend on a signal that might be missing or stale. This rule
    depends on the risk level, and by the time rules are evaluated Phase 7 has
    already confirmed a level exists - the withholding checks above it return
    otherwise. A `required` flag here would be a knob that cannot change any
    outcome, which is worse than no knob: it would look like a safety control
    while doing nothing.
    """

    rule_id: str
    risk_level_at_least: str
    escalate_to: str
    source: str
    note: str = ""

    def __post_init__(self) -> None:
        _require_text(self.rule_id, "ResponseRule.rule_id", InvalidResponsePolicyError)
        _require_text(self.source, "ResponseRule.source", InvalidResponsePolicyError)
        if self.risk_level_at_least not in SUPPORTED_RISK_LEVELS:
            raise InvalidResponsePolicyError(
                f"rule {self.rule_id!r} triggers at risk level "
                f"{self.risk_level_at_least!r}, which is not among "
                f"{list(SUPPORTED_RISK_LEVELS)}"
            )
        if self.escalate_to not in RESPONSE_STATES:
            raise UnsupportedResponseStateError(
                f"rule {self.rule_id!r} escalates to {self.escalate_to!r}, which is not "
                f"one of {list(RESPONSE_STATES)}. Phase 7 does not provide evacuation, "
                "mandatory evacuation, or emergency declaration"
            )
        if self.escalate_to not in POLICY_TARGET_STATES:
            raise InvalidResponsePolicyError(
                f"rule {self.rule_id!r} escalates to {DECISION_WITHHELD!r}, which is the "
                "absence of a recommendation and cannot be a rule's target"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "risk_level_at_least": self.risk_level_at_least,
            "escalate_to": self.escalate_to,
            "source": self.source,
            "note": self.note,
        }


@dataclass(frozen=True)
class RuleEvaluation:
    """What one configured rule did, whether or not it fired.

    Non-fired rules are recorded, for the reason Phase 6 records non-fired
    escalations: "no rule fired" and "no rule was configured" support completely
    different conclusions about the same decision.
    """

    rule_id: str
    risk_level_at_least: str
    escalate_to: str
    source: str
    fired: bool
    applied: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "risk_level_at_least": self.risk_level_at_least,
            "escalate_to": self.escalate_to,
            "source": self.source,
            "fired": self.fired,
            "applied": self.applied,
            "reason": self.reason,
        }


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DecisionEvidence:
    """One input the decision actually read.

    `contributed` is the field that matters. Evidence that was read but did not
    move the decision carries `contributed=False` with a reason, so a reader can
    tell "we looked at this and it was not decisive" from "we did not look". An
    input the decision never read does not appear here at all - it appears in
    `unavailable_context`.
    """

    name: str
    value: Any
    units: str | None
    source: str
    availability: str
    contributed: bool
    reason: str = ""

    def __post_init__(self) -> None:
        _require_text(self.name, "DecisionEvidence.name", InvalidResponseContextError)
        _require_text(self.source, "DecisionEvidence.source", InvalidResponseContextError)
        _require_text(self.reason, "DecisionEvidence.reason", InvalidResponseContextError)
        if self.availability not in RESPONSE_AVAILABILITY:
            raise InvalidResponseContextError(
                f"evidence {self.name!r} availability {self.availability!r} is not one "
                f"of {list(RESPONSE_AVAILABILITY)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "units": self.units,
            "source": self.source,
            "availability": self.availability,
            "contributed": self.contributed,
            "reason": self.reason,
        }


# --------------------------------------------------------------------------- #
# The decision
# --------------------------------------------------------------------------- #


def default_decision_id(context: ResponseContext, policy: ResponsePolicy) -> str:
    """A readable prefix plus a sha256 of everything that could change the outcome.

    Deterministic by construction: the same context and the same policy produce the
    same id, and the id changes when either changes. No uuid, no counter, no clock.
    A random id would make two identical decisions look like two different events.
    """
    payload = {
        "response_contract_version": RESPONSE_CONTRACT_VERSION,
        "entity": context.entity,
        "risk_result_id": context.risk_result_id,
        "context_digest": context.digest,
        "policy_version": policy.policy_version,
        "policy_status": policy.policy_status,
        "mapping": dict(policy.risk_level_response),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
    level = context.risk_level or "no-risk-level"
    return f"response-{context.entity}-{level}-{policy.policy_version}@{digest}"


@dataclass(frozen=True)
class ResponseDecision:
    """One response recommendation, with every field either true or honestly absent.

    Two fields are structural safety properties rather than data:

    * ``operational_authority`` is permanently `False`. It is a dataclass field so
      that a consumer can assert on it, not so that a caller can set it.
    * ``production_ready_claimed`` is permanently `False`, matching Phase 6.

    There is no score field, and that is the load-bearing omission: with nothing to
    weight, no composite can be assembled downstream either.
    """

    decision_id: str
    decision: str
    status: str
    entity: str
    risk_result_id: str
    risk_level: str | None
    risk_score: float | None
    risk_score_type: str | None
    priority: str | None
    rationale: str
    explanation: tuple[str, ...]
    evidence: tuple[DecisionEvidence, ...]
    unavailable_context: tuple[ExposureAvailability, ...]
    rules: tuple[RuleEvaluation, ...]
    response_policy: Mapping[str, Any]
    decided_at: dt.datetime
    forecast_origin: dt.datetime
    forecast_id: str | None
    forecast_horizon: str | None
    provenance: Mapping[str, Any]
    synthetic_demo: bool
    data_status: str
    disclaimer: str
    operational_authority: bool = OPERATIONAL_AUTHORITY
    production_ready_claimed: bool = PRODUCTION_READY_CLAIMED
    response_contract_version: str = RESPONSE_CONTRACT_VERSION
    response_context_version: str = RESPONSE_CONTEXT_VERSION
    risk_contract_version: str = RISK_CONTRACT_VERSION

    # --- derived -----------------------------------------------------------

    @property
    def is_withheld(self) -> bool:
        return self.decision == DECISION_WITHHELD

    @property
    def is_recommendation(self) -> bool:
        """True when a response category was recommended rather than withheld."""
        return not self.is_withheld

    @property
    def evidence_read(self) -> tuple[DecisionEvidence, ...]:
        return tuple(item for item in self.evidence if item.contributed)

    @property
    def fired_rules(self) -> tuple[RuleEvaluation, ...]:
        return tuple(rule for rule in self.rules if rule.fired)

    @property
    def applied_rules(self) -> tuple[RuleEvaluation, ...]:
        return tuple(rule for rule in self.rules if rule.applied)

    def explain(self) -> str:
        """The explanation as one paragraph, for a log line."""
        return " ".join(self.explanation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "decision": self.decision,
            "status": self.status,
            "entity": self.entity,
            "risk_result_id": self.risk_result_id,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "risk_score_type": self.risk_score_type,
            "priority": self.priority,
            "rationale": self.rationale,
            "explanation": list(self.explanation),
            "evidence": [item.to_dict() for item in self.evidence],
            "unavailable_context": [item.to_dict() for item in self.unavailable_context],
            "rules": [rule.to_dict() for rule in self.rules],
            "response_policy": dict(self.response_policy),
            "decided_at": self.decided_at.isoformat(),
            "forecast_origin": self.forecast_origin.isoformat(),
            "forecast_id": self.forecast_id,
            "forecast_horizon": self.forecast_horizon,
            "provenance": dict(self.provenance),
            "synthetic_demo": self.synthetic_demo,
            "data_status": self.data_status,
            "disclaimer": self.disclaimer,
            "operational_authority": self.operational_authority,
            "production_ready_claimed": self.production_ready_claimed,
            "response_contract_version": self.response_contract_version,
            "response_context_version": self.response_context_version,
            "risk_contract_version": self.risk_contract_version,
        }


# --------------------------------------------------------------------------- #
# Explanation
# --------------------------------------------------------------------------- #

#: The line that appears whenever a decision recommends something. It names the
#: category and states plainly that it is a recommendation, so the string cannot be
#: lifted out of the explanation and quoted as a warning.
RECOMMENDATION_DISCLAIMER = (
    "this is a recommendation about attention on synthetic/demo evidence; it is not a "
    "flood warning, not an evacuation instruction, and carries no operational or "
    "government authority"
)


def _render_evidence(item: DecisionEvidence) -> str:
    """One evidence item as a reader sees it.

    `value=None` is rendered as "no value carried" rather than as a bare `None`.
    A bare `None` next to a signal name reads as a *missing measurement*, when the
    truth is that Phase 7 deliberately did not carry the value at all - and those
    two must never look alike, because one is a data gap and the other is a scope
    boundary.
    """
    if item.value is None:
        rendered = "no value carried"
    else:
        rendered = repr(item.value)
        if item.units:
            rendered = f"{rendered} {item.units}"
    if not item.contributed:
        rendered += " (read, did not decide)"
    return f"{item.name}: {rendered}"


def _explanation(
    context: ResponseContext,
    policy: ResponsePolicy,
    decision: str,
    rationale: str,
    evidence: Sequence[DecisionEvidence],
    unavailable: Sequence[ExposureAvailability],
    rules: Sequence[RuleEvaluation],
) -> tuple[str, ...]:
    """Every line, derived. No template can describe a contributor not read."""
    lines: list[str] = []

    lines.append(
        f"phase 7 response decision for {context.entity} from risk result "
        f"{context.risk_result_id!r}: risk {context.risk_status}/"
        f"{context.risk_evaluation_state}, level {context.risk_level!r}, score "
        f"{context.risk_score!r}"
        + (
            f" ({context.risk_score_type})"
            if context.risk_score_type
            else ""
        )
        + f"; phase 6 owns the risk classification and phase 7 did not recompute it"
    )

    if decision == DECISION_WITHHELD:
        lines.append(
            f"no response category is recommended: {rationale}; withholding is the "
            "honest answer when the evidence or the policy cannot support one, and it "
            "is not the same as recommending that nothing be done"
        )
    else:
        lines.append(
            f"response category {decision} is recommended because {rationale}"
        )

    # --- what was actually read --------------------------------------------
    if evidence:
        lines.append(
            f"{len(evidence)} input(s) were read: "
            + "; ".join(_render_evidence(item) for item in evidence)
        )
    else:
        lines.append("no input was read; a decision made from nothing is recorded as such")

    # --- what was not ------------------------------------------------------
    if unavailable:
        lines.append(
            "context that was unavailable and did not contribute to this decision: "
            + "; ".join(
                f"{item.kind} {item.availability} ({item.reason})" for item in unavailable
            )
            + "; an unavailable input is absent from the decision, not counted as zero "
            "and not read as reassuring"
        )
    else:
        lines.append("no contextual input was declared unavailable for this decision")

    if not context.historical_available:
        lines.append(
            f"historical flood context was unavailable ({context.historical_reason}); "
            "this absence is not evidence that this location has never flooded"
        )

    if not context.gis_available:
        lines.append(
            f"spatial context was unavailable ({context.gis_reason}); no elevation, "
            "river-distance, floodplain or accessibility conclusion was drawn"
        )

    if context.risk_availability_counts:
        parts = ", ".join(
            f"{state}={context.risk_availability_counts[state]}"
            for state in sorted(context.risk_availability_counts)
        )
        lines.append(
            f"phase 6 evaluated the context at state {context.risk_evaluation_state} "
            f"with {parts}; phase 7 read that state and did not re-evaluate any signal"
        )

    # --- the policy --------------------------------------------------------
    lines.append(policy.describe())

    applied = [rule for rule in rules if rule.applied]
    if applied:
        lines.append(
            "raised by "
            + "; ".join(
                f"rule {rule.rule_id!r} (risk level at least "
                f"{rule.risk_level_at_least}, from {rule.source})"
                for rule in applied
            )
            + "; rules may only raise a response category, never lower one"
        )
    inert = [rule for rule in rules if rule.fired and not rule.applied]
    if inert:
        lines.append(
            "configured but not applied: "
            + "; ".join(f"rule {rule.rule_id!r}: {rule.reason}" for rule in inert)
        )
    if not rules:
        lines.append(
            "no response rules are configured, so no rule contributed to this decision"
        )

    # --- safety ------------------------------------------------------------
    if context.residual_sigma_source in (None, "unavailable"):
        lines.append(
            "the underlying risk score rests on no measured residual spread "
            "(Phase 6 recorded it as unavailable), so this decision inherits an "
            "unquantified spread and is not a confidence statement"
        )
    if context.risk_threshold_policy != "approved":
        lines.append(
            f"the underlying threshold policy is {context.risk_threshold_policy!r} "
            f"({context.risk_threshold_configuration}); the risk level this decision "
            "responds to is a demo value with no official meaning"
        )
    if decision != DECISION_WITHHELD:
        lines.append(RECOMMENDATION_DISCLAIMER)
    lines.append(
        "no evacuation, mandatory evacuation, or emergency declaration is provided by "
        "this layer, and none was requested; those are not response categories this "
        "repository is able to justify"
    )
    if context.synthetic_demo:
        lines.append(SYNTHETIC_DATA_DISCLAIMER)

    return tuple(lines)


# --------------------------------------------------------------------------- #
# Decision
# --------------------------------------------------------------------------- #


def _withheld(
    context: ResponseContext,
    policy: ResponsePolicy,
    reason: str,
    *,
    decision_id: str | None = None,
    rules: Sequence[RuleEvaluation] = (),
    evidence: Sequence[DecisionEvidence] = (),
    unavailable: Sequence[ExposureAvailability] = (),
) -> ResponseDecision:
    """Build the withheld decision. The single place `WITHHELD` is produced."""
    return ResponseDecision(
        decision_id=decision_id or default_decision_id(context, policy),
        decision=DECISION_WITHHELD,
        status="withheld",
        entity=context.entity,
        risk_result_id=context.risk_result_id,
        risk_level=context.risk_level,
        risk_score=context.risk_score,
        risk_score_type=context.risk_score_type,
        priority=priority_for_risk_level(context.risk_level) if context.risk_level else None,
        rationale=reason,
        explanation=_explanation(context, policy, DECISION_WITHHELD, reason, evidence, unavailable, rules),
        evidence=tuple(evidence),
        unavailable_context=tuple(unavailable),
        rules=tuple(rules),
        response_policy=policy.to_dict(),
        decided_at=context.resolved_decided_at,
        forecast_origin=context.forecast_origin,
        forecast_id=context.forecast_id,
        forecast_horizon=context.forecast_horizon,
        provenance={
            "response_contract_version": RESPONSE_CONTRACT_VERSION,
            "risk_contract_version": RISK_CONTRACT_VERSION,
            "risk_result_id": context.risk_result_id,
            "forecast_id": context.forecast_id,
            "entity": context.entity,
            "risk_evaluation_state": context.risk_evaluation_state,
            "risk_threshold_policy": context.risk_threshold_policy,
            "risk_configuration_version": context.risk_configuration_version,
            "response_policy_version": policy.policy_version,
            "response_policy_status": policy.policy_status,
            "operational_authority": OPERATIONAL_AUTHORITY,
            "production_ready_claimed": PRODUCTION_READY_CLAIMED,
            "response_context_disclaimer": context.disclaimer,
        },
        synthetic_demo=context.synthetic_demo,
        data_status=context.data_status,
        disclaimer=context.disclaimer,
    )


def _evaluate_rules(
    rules: Sequence[ResponseRule],
    risk_level: str,
    policy: ResponsePolicy,
) -> list[RuleEvaluation]:
    """Evaluate each rule.

    Raise-only, and never past the policy's own ceiling: a rule may not produce a
    category the configured mapping cannot produce, because that would be a rule
    overriding the policy that authorised it.
    """
    order = {level: index for index, level in enumerate(SUPPORTED_RISK_LEVELS)}
    current_index = order[risk_level]
    ceiling = policy.highest_mapped_state

    evaluations: list[RuleEvaluation] = []
    for rule in rules:
        if order[rule.risk_level_at_least] > current_index:
            evaluations.append(
                RuleEvaluation(
                    rule_id=rule.rule_id,
                    risk_level_at_least=rule.risk_level_at_least,
                    escalate_to=rule.escalate_to,
                    source=rule.source,
                    fired=False,
                    applied=False,
                    reason=(
                        f"risk level {risk_level} is below the trigger "
                        f"{rule.risk_level_at_least}"
                    ),
                )
            )
            continue

        ceiling_index = RESPONSE_SEVERITY[ceiling] if ceiling else -1
        if RESPONSE_SEVERITY[rule.escalate_to] > ceiling_index:
            evaluations.append(
                RuleEvaluation(
                    rule_id=rule.rule_id,
                    risk_level_at_least=rule.risk_level_at_least,
                    escalate_to=rule.escalate_to,
                    source=rule.source,
                    fired=True,
                    applied=False,
                    reason=(
                        f"target {rule.escalate_to} is beyond the configured ceiling "
                        f"{ceiling}; a rule may not exceed the policy that authorised it"
                    ),
                )
            )
            continue

        evaluations.append(
            RuleEvaluation(
                rule_id=rule.rule_id,
                risk_level_at_least=rule.risk_level_at_least,
                escalate_to=rule.escalate_to,
                source=rule.source,
                fired=True,
                applied=True,
                reason=f"risk level {risk_level} is at or above {rule.risk_level_at_least}",
            )
        )
    return evaluations


def decide_response(
    context: ResponseContext | Any,
    *,
    policy: ResponsePolicy,
    rules: Sequence[ResponseRule] = (),
    decision_id: str | None = None,
) -> ResponseDecision:
    """The response category the configured policy assigns to a Phase 6 risk result.

    `context` may be a `ResponseContext` or a Phase 6 `RiskResult`, which is
    projected with `ResponseContext.from_risk_result`. Passing the risk result
    directly is the common case and the one the docs show.

    Raises a `ResponseBoundaryError` subclass for a contract violation; returns a
    `WITHHELD` decision for an availability condition. `decide_response_safe`
    converts the former into the latter.
    """
    if context is None:
        raise MissingRiskResultError(
            "no risk result was supplied; phase 7 consumes a phase 6 risk result and "
            "does not assess risk itself"
        )
    _require_policy(policy)
    if not isinstance(context, ResponseContext):
        context = ResponseContext.from_risk_result(context)

    if not isinstance(rules, tuple):
        rules = tuple(rules)
    for rule in rules:
        if not isinstance(rule, ResponseRule):
            raise InvalidResponsePolicyError(
                f"rules holds a {type(rule).__name__}, not a ResponseRule; a rule that "
                "cannot be validated cannot be evaluated or explained"
            )
    identifiers = [rule.rule_id for rule in rules]
    duplicates = sorted({name for name in identifiers if identifiers.count(name) > 1})
    if duplicates:
        raise InvalidResponsePolicyError(
            f"response rule ids {duplicates} appear more than once; a rule that cannot "
            "be named in an explanation cannot be audited"
        )
    rules = tuple(sorted(rules, key=lambda rule: rule.rule_id))

    unavailable = tuple(record for record in context.exposure if not record.usable)

    # --- the withholding conditions, in a fixed order ----------------------
    # The order matters and is tested: a decision must name *one* reason, and the
    # first unmet precondition is the one a caller has to fix.

    if not context.risk_is_available:
        if context.risk_evaluation_state == CONTEXT_NOT_EVALUABLE:
            reason = (
                "phase 6 could not assign a risk band, so no response category can be "
                "derived from it; an exceedance probability without a band is not a "
                "level, and phase 7 will not choose one"
            )
        else:
            reason = (
                f"phase 6 recorded no usable risk level (status {context.risk_status!r}, "
                f"evaluation state {context.risk_evaluation_state!r}); there is nothing "
                "for a response to respond to"
            )
        return _withheld(
            context, policy, reason, decision_id=decision_id, unavailable=unavailable
        )

    if context.risk_evaluation_state == CONTEXT_UNAVAILABLE:
        return _withheld(
            context,
            policy,
            "phase 6 could read no context at all, so the risk level rests on the "
            "forecast alone with nothing to corroborate it",
            decision_id=decision_id,
            unavailable=unavailable,
        )

    if not policy.is_usable:
        return _withheld(
            context,
            policy,
            "no response mapping is configured, and this repository has no approved "
            "warning criteria to fall back on",
            decision_id=decision_id,
            unavailable=unavailable,
        )

    if context.risk_level not in policy.risk_level_response:
        return _withheld(
            context,
            policy,
            f"the configured policy maps {list(policy.mapped_levels)} and does not "
            f"cover risk level {context.risk_level!r}; an unmapped level is not "
            "defaulted to the nearest mapped one",
            decision_id=decision_id,
            unavailable=unavailable,
        )

    # --- the recommendation ------------------------------------------------
    base = policy.risk_level_response[context.risk_level]
    evaluations = _evaluate_rules(rules, context.risk_level, policy)

    final = base
    for evaluation in evaluations:
        if not evaluation.applied:
            continue
        if RESPONSE_SEVERITY[evaluation.escalate_to] > RESPONSE_SEVERITY[final]:
            final = evaluation.escalate_to

    contributing = [
        evaluation for evaluation in evaluations if evaluation.applied
    ]
    if contributing:
        rationale = (
            f"the configured policy maps risk level {context.risk_level} to {base}, and "
            + "; ".join(
                f"rule {evaluation.rule_id!r} raised it to {evaluation.escalate_to}"
                for evaluation in contributing
            )
        )
    else:
        rationale = (
            f"the configured policy maps risk level {context.risk_level} to {base}"
        )

    evidence = _build_evidence(context, final)

    return ResponseDecision(
        decision_id=decision_id or default_decision_id(context, policy),
        decision=final,
        status="recommended",
        entity=context.entity,
        risk_result_id=context.risk_result_id,
        risk_level=context.risk_level,
        risk_score=context.risk_score,
        risk_score_type=context.risk_score_type,
        priority=priority_for_risk_level(context.risk_level) if context.risk_level else None,
        rationale=rationale,
        explanation=_explanation(
            context, policy, final, rationale, evidence, unavailable, evaluations
        ),
        evidence=tuple(evidence),
        unavailable_context=unavailable,
        rules=tuple(evaluations),
        response_policy=policy.to_dict(),
        decided_at=context.resolved_decided_at,
        forecast_origin=context.forecast_origin,
        forecast_id=context.forecast_id,
        forecast_horizon=context.forecast_horizon,
        provenance={
            "response_contract_version": RESPONSE_CONTRACT_VERSION,
            "risk_contract_version": RISK_CONTRACT_VERSION,
            "risk_result_id": context.risk_result_id,
            "forecast_id": context.forecast_id,
            "entity": context.entity,
            "risk_level": context.risk_level,
            "risk_score": context.risk_score,
            "risk_score_type": context.risk_score_type,
            "risk_evaluation_state": context.risk_evaluation_state,
            "risk_threshold_policy": context.risk_threshold_policy,
            "risk_configuration_version": context.risk_configuration_version,
            "response_policy_version": policy.policy_version,
            "response_policy_status": policy.policy_status,
            "response_policy_source": policy.policy_source,
            "operational_authority": OPERATIONAL_AUTHORITY,
            "production_ready_claimed": PRODUCTION_READY_CLAIMED,
            "response_context_disclaimer": context.disclaimer,
        },
        synthetic_demo=context.synthetic_demo,
        data_status=context.data_status,
        disclaimer=context.disclaimer,
    )


def _build_evidence(context: ResponseContext, decision: str) -> list[DecisionEvidence]:
    """The inputs actually read, each marked with whether it decided anything.

    A `WITHHELD` decision contributes nothing, because nothing decided it - the
    withheld path builds its own evidence-free decision.
    """
    evidence = [
        DecisionEvidence(
            name="risk_level",
            value=context.risk_level,
            units=None,
            source="phase 6 risk classification (not recomputed by phase 7)",
            availability="valid",
            contributed=True,
            reason="the configured policy maps this level to a response category",
        ),
        DecisionEvidence(
            name="risk_score",
            value=context.risk_score,
            units=None,
            source=(
                context.risk_score_type
                or "phase 6 exceedance probability, unlabelled by the risk result"
            ),
            availability="valid" if context.risk_score is not None else "missing",
            contributed=False,
            reason=(
                "carried for traceability; phase 7 applies no numeric threshold of its "
                "own, so the score informs the explanation and not the category"
            ),
        ),
        DecisionEvidence(
            name="risk_evaluation_state",
            value=context.risk_evaluation_state,
            units=None,
            source="phase 6 context evaluation",
            availability="valid",
            contributed=True,
            reason="partially_evaluated still supports a category; context_unavailable and not_evaluable do not",
        ),
        DecisionEvidence(
            name="threshold_policy_status",
            value=context.risk_threshold_policy,
            units=None,
            source="phase 6 threshold policy",
            availability="valid",
            contributed=False,
            reason="recorded so the demo nature of the underlying level is visible; it does not change the category",
        ),
    ]
    for name in context.usable_signal_names:
        evidence.append(
            DecisionEvidence(
                name=f"phase6_signal:{name}",
                value=None,
                units=None,
                source="phase 6 evaluated this signal",
                availability="valid",
                contributed=False,
                reason=(
                    "read by phase 6 and already reflected in the risk level; phase 7 "
                    "does not re-read it and applies no rule of its own to it"
                ),
            )
        )
    return evidence


def response_from_error(
    error: Exception,
    *,
    policy: ResponsePolicy | None = None,
    context: ResponseContext | Any | None = None,
    decision_id: str = "response-withheld",
) -> ResponseDecision:
    """Build the withheld decision from a caught error.

    Names `error.reason` in the explanation so a refusal is countable rather than
    something to be parsed out of prose. Tolerates any `ValueError`, not only a
    `ResponseBoundaryError`, because a caller reaching for this has usually already
    decided not to fail.

    A `policy` that is not a `ResponsePolicy` is reported as an empty one rather
    than raised on: this function is the error path, and raising from inside it would
    turn a refusal into a traceback.
    """
    policy = _reportable_policy(policy)
    resolved = context
    if resolved is not None and not isinstance(resolved, ResponseContext):
        try:
            resolved = ResponseContext.from_risk_result(resolved)
        except Exception:  # noqa: BLE001 - the point is to withhold, not to fail
            resolved = None
    if resolved is None:
        reason = f"{getattr(error, 'reason', 'error')}: {error}"
        explanation = (
            f"phase 7 produced no response decision and no risk result was available to "
            f"read: {reason}. Withholding is the honest answer; it is not a "
            "recommendation that nothing be done"
        )
        return ResponseDecision(
            decision_id=decision_id,
            decision=DECISION_WITHHELD,
            status="withheld",
            entity="unknown",
            risk_result_id="unknown",
            risk_level=None,
            risk_score=None,
            risk_score_type=None,
            priority=None,
            rationale=reason,
            explanation=(
                explanation,
                RECOMMENDATION_DISCLAIMER,
                SYNTHETIC_DATA_DISCLAIMER,
            ),
            evidence=(),
            unavailable_context=(),
            rules=(),
            response_policy=policy.to_dict(),
            decided_at=dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc),
            forecast_origin=dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc),
            forecast_id=None,
            forecast_horizon=None,
            provenance={
                "response_contract_version": RESPONSE_CONTRACT_VERSION,
                "risk_contract_version": RISK_CONTRACT_VERSION,
                "error_reason": getattr(error, "reason", "error"),
                "response_policy_version": policy.policy_version,
                "operational_authority": OPERATIONAL_AUTHORITY,
                "production_ready_claimed": PRODUCTION_READY_CLAIMED,
                "response_context_disclaimer": SYNTHETIC_DATA_DISCLAIMER,
            },
            synthetic_demo=True,
            data_status="unknown",
            disclaimer=SYNTHETIC_DATA_DISCLAIMER,
        )
    return _withheld(
        resolved,
        policy,
        f"{getattr(error, 'reason', 'error')}: {error}",
        decision_id=decision_id,
    )


def decide_response_safe(
    context: ResponseContext | Any,
    *,
    policy: ResponsePolicy,
    rules: Sequence[ResponseRule] = (),
    decision_id: str | None = None,
) -> ResponseDecision:
    """`decide_response`, with contract violations converted into `WITHHELD`.

    For a caller that must answer rather than fail. The withheld decision names the
    error's `reason`, so nothing is lost by not raising.
    """
    try:
        return decide_response(context, policy=policy, rules=rules, decision_id=decision_id)
    except Exception as error:  # noqa: BLE001 - the contract is to answer, not fail
        resolved = context if isinstance(context, ResponseContext) else None
        return response_from_error(
            error,
            policy=policy,
            context=resolved,
            decision_id=decision_id or "response-withheld",
        )


# --------------------------------------------------------------------------- #
# The contract, described
# --------------------------------------------------------------------------- #


def response_contract_description() -> dict[str, Any]:
    """The response-decision contract as data, for a report or a review."""
    return {
        "response_contract_version": RESPONSE_CONTRACT_VERSION,
        "response_policy_version": RESPONSE_POLICY_VERSION,
        "response_context_version": RESPONSE_CONTEXT_VERSION,
        "consumes": "Phase 6 RiskResult, read-only",
        "response_states": list(RESPONSE_STATES),
        "policy_target_states": list(POLICY_TARGET_STATES),
        "severity_order": list(RESPONSE_STATES),
        "default_decision": DECISION_WITHHELD,
        "default_reason": (
            "no authoritative response policy exists in this repository, so the "
            "default is to recommend nothing rather than to invent a warning matrix"
        ),
        "deliberately_absent_states": [
            "EVACUATE",
            "MANDATORY_EVACUATION",
            "EMERGENCY_DECLARED",
        ],
        "deliberately_absent_states_reason": (
            "phase 7 is a recommendation boundary, not an emergency authority. EVACUATE, "
            "MANDATORY_EVACUATION and EMERGENCY_DECLARED are absent because there are "
            "no approved warning criteria, no population or infrastructure data, and no "
            "signed-off response matrix in this repository. Naming such a state would "
            "imply a capability that does not exist, so the vocabulary refuses it rather "
            "than the documentation disclaiming it"
        ),
        "risk_authority": (
            "phase 6 owns exceedance probability, threshold handling, sigma and band "
            "classification. Phase 7 reads the resulting RiskResult and recomputes "
            "none of it; a phase 7 rule conditions on the risk level, not on a "
            "signal value, because signal-threshold comparison is phase 6's"
        ),
        "composite_score": None,
        "composite_score_note": (
            "there is no response_score, severity_score or danger_score field. Phase 6 "
            "declined to invent a weighted composite and phase 7 does not add one; "
            "there is nothing to weight, so no composite can be assembled downstream"
        ),
        "operational_authority": OPERATIONAL_AUTHORITY,
        "production_ready_claimed": PRODUCTION_READY_CLAIMED,
        "errors_are_raised_not_swallowed": (
            "contract violations raise a ResponseBoundaryError; availability "
            "conditions return a WITHHELD decision. decide_response_safe converts the "
            "former into the latter for callers that must answer rather than fail"
        ),
        "errors": [
            cls.reason
            for cls in (
                MissingRiskResultError,
                InvalidRiskResultError,
                InvalidResponseContextError,
                InvalidResponsePolicyError,
                UnsupportedResponseStateError,
            )
        ],
        "reused_phase6_errors": [
            EntityMismatchError.reason,
            FutureContextError.reason,
        ],
        "determinism": (
            "decision_id is a readable prefix plus sha256 over the context digest and "
            "the policy mapping; decided_at defaults to the forecast origin; no clock, "
            "no uuid, and no randomness is used anywhere in the decision path"
        ),
        "no_composite": True,
        "gis_absent_marker": NOT_AVAILABLE,
        "no_emergency_states": True,
    }


__all__ = [
    "DECISION_HEIGHTENED_MONITORING",
    "DECISION_MONITOR",
    "DECISION_REVIEW_WARNING",
    "DECISION_WITHHELD",
    "OPERATIONAL_AUTHORITY",
    "POLICY_TARGET_STATES",
    "PRODUCTION_READY_CLAIMED",
    "RECOMMENDATION_DISCLAIMER",
    "RESPONSE_CONTRACT_VERSION",
    "RESPONSE_POLICY_VERSION",
    "RESPONSE_SEVERITY",
    "RESPONSE_STATES",
    "DecisionEvidence",
    "InvalidResponseContextError",
    "InvalidResponsePolicyError",
    "InvalidRiskResultError",
    "MissingRiskResultError",
    "ResponseBoundaryError",
    "ResponseDecision",
    "ResponsePolicy",
    "ResponseRule",
    "RuleEvaluation",
    "UnsupportedResponseStateError",
    "decide_response",
    "decide_response_safe",
    "default_decision_id",
    "response_contract_description",
    "response_from_error",
]