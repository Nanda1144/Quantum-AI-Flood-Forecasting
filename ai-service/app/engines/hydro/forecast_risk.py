# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 6: a validated Phase 5 forecast turned into an auditable risk assessment.

What this module adds, and what it deliberately does not
--------------------------------------------------------
Phase 1 already wrote a risk engine (`risk.py`): an exceedance probability under a
normal residual assumption, and a band classification over configured edges.
Phase 6 does not rewrite it, re-weight it, or add a second one. It connects three
things that existed but had never been joined:

1. a **validated** Phase 5 `ServedForecast`, with its artifact, model version,
   feature digest and provenance;
2. a **typed** evidence context (`risk_context.RiskContext`), with per-signal
   source, units, availability and observation instant;
3. an **auditable** result that says which signals were read, which were not, why
   the band came out where it did, and which platform contract fields follow from
   it.

The score is a probability, and it is labelled as one
----------------------------------------------------
`risk_score` is the exceedance probability produced by `risk.exceedance_probability`.
Its meaning is exactly `P(target > threshold)` **under the assumption that
residuals are normal**, and its type is reported as
`RISK_SCORE_TYPE_EXCEEDANCE`. It is *not* a scientifically validated flood
probability: nobody in this repository has calibrated a flood-frequency model, and
the module says so rather than letting a [0, 1] number imply otherwise.

Why there are no magic risk weights
-----------------------------------
A weighted composite of normalised signals would need a normalisation rule and a
weight vector, and neither can be derived from anything in this repository — they
would be invented. So there are none. Two mechanisms replace them:

* **One classifier.** The band comes from `risk.classify_risk_level` applied to the
  exceedance probability, over edges the operator configured. Nothing else assigns
  a band.
* **Configured escalation.** A `RiskEscalationRule` compares one named signal
  against one configured value, in one declared unit, and may only *raise* the band
  to a named platform level. With no rules configured, signals contribute to the
  explanation and to the evaluation state and nothing else. A rule that fires is
  recorded with the value, the unit, the source and the rule's own provenance, so
  an escalated band is as traceable as a computed one.

Why residual spread must be supplied
------------------------------------
`exceedance_probability` needs a measured residual spread. A Phase 5 artifact
carries *aggregate* metrics — `mae`, `rmse`, `r2`, `bias` — and not the residuals,
so no spread can be measured from it.

`rmse` is not that spread and is not accepted as one. RMSE is
`sqrt(mean(r^2))`, about zero; the normal model needs `sqrt(mean((r - mean(r))^2))`,
about the mean. The two coincide only when the residuals are unbiased, and this
pipeline's residuals are not: the fixture models carry `bias` of `-0.13` and `-0.20`
metres. Substituting RMSE would inflate the spread, shrink every exceedance
probability, and silently change the method recorded on the result — so
`assess_risk` refuses to compute a level without a measured `residuals` or
`residual_sigma`, and says why in the explanation.

Nothing here trains
-------------------
No estimator, scaler, imputer or artifact is touched. The only inputs read are the
Phase 5 result, the caller's context, and the caller's configuration.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import math
import operator
from dataclasses import dataclass, is_dataclass
from typing import Any, Mapping, Sequence

from .config import RiskPolicy
from .contract import SUPPORTED_RISK_LEVELS, ForecastOutput, priority_for_risk_level
from .domains import (
    DATASET_TYPE_SYNTHETIC,
    DATASET_TYPE_UNKNOWN,
    RISK_STATUS_RECORDED,
    RISK_STATUS_WITHHELD,
    RiskScoreRecord,
)
from .forecast_inference import ForecastInference, Uncertainty
from .forecast_serving import SERVING_CONTRACT_VERSION, ServedForecast
from .preprocess_units import dimension_of, normalize_unit
from .provenance import (
    SYNTHETIC_DATA_DISCLAIMER,
    ProvenanceRecord,
    SplitBoundaries,
)
from .risk import RiskAssessment, RiskError
from .risk import RiskAssessor
from .risk import residual_sigma as measured_residual_sigma
from .risk_context import (
    CONTEXT_NOT_EVALUABLE,
    InvalidForecastError,
    InvalidRiskCalculationError,
    InvalidRiskConfigurationError,
    InvalidThresholdError,
    InvalidUnitsError,
    MissingForecastError,
    MissingRiskContextError,
    RISK_QUANTITIES,
    RiskBoundaryError,
    RiskContext,
    SignalEvaluation,
    availability_counts,
    evaluation_state,
    evaluate_context,
)

#: Version tag written into every risk result this module produces.
RISK_CONTRACT_VERSION = "navya-phase6-risk/v1"

#: Default identifier for a risk configuration that has not declared its own.
RISK_CONFIGURATION_VERSION = "navya-phase6-risk-config/v1"

#: What `threshold_configuration` reports when no threshold source exists at all.
THRESHOLD_UNCONFIGURED = "unconfigured"

#: The mathematical meaning of `RiskResult.risk_score`.
#:
#: It is a probability under an explicit normal-residual assumption, computed from a
#: measured residual spread. It is **not** a calibrated flood frequency, and no
#: repository evidence supports reading it as one.
RISK_SCORE_TYPE_EXCEEDANCE = "normal_approximation_exceedance_probability"

#: The closed set of score types this module can report. One entry, deliberately:
#: the alternative was an `engineering_composite` built from invented weights.
RISK_SCORE_TYPES: tuple[str, ...] = (RISK_SCORE_TYPE_EXCEEDANCE,)

#: Where a residual spread came from. Recorded so a reader can tell a measured
#: spread from a supplied one.
SIGMA_SOURCE_RESIDUALS = "measured_residuals"
SIGMA_SOURCE_SUPPLIED = "caller_supplied_measurement"
SIGMA_SOURCE_ABSENT = "unavailable"

#: Comparison operators a configured escalation rule may use.
_COMPARISONS: Mapping[str, Any] = {
    ">=": operator.ge,
    ">": operator.gt,
    "<=": operator.le,
    "<": operator.lt,
}

#: The supported comparison spellings, in a stable order for reporting.
COMPARISONS: tuple[str, ...] = (">=", ">", "<=", "<")


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RiskEscalationRule:
    """One configured rule that may raise a risk band on contextual evidence.

    A rule is a *declared policy input*, in the same sense the flood threshold is:
    someone chose the value, the value is recorded with its source, and nothing here
    is a default. The two things that make this safe to compare are that `unit` is
    mandatory — a value without a unit cannot be checked — and that `escalate_to` is
    restricted to the platform's own risk vocabulary.

    `required=True` turns a missing or unusable signal into a refusal instead of a
    silent non-escalation. It exists because the failure mode of an optional rule is
    dangerous in a specific way: the context loses its rainfall record, the rule
    quietly does not fire, and the band comes out lower than the policy intended
    with nothing in the result to say so. A rule that says it needs this signal gets
    told when the signal is not there.
    """

    rule_id: str
    signal: str
    quantity: str
    comparison: str
    value: float
    unit: str
    escalate_to: str
    source: str
    required: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        for field_name in ("rule_id", "signal", "unit", "source"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise InvalidRiskConfigurationError(
                    f"RiskEscalationRule.{field_name} is required and must be a non-empty "
                    f"string, got {value!r}"
                )
        if self.quantity not in RISK_QUANTITIES:
            raise InvalidRiskConfigurationError(
                f"rule {self.rule_id!r} references quantity {self.quantity!r}, which is not "
                f"one of {RISK_QUANTITIES}"
            )
        if self.comparison not in _COMPARISONS:
            raise InvalidRiskConfigurationError(
                f"rule {self.rule_id!r} uses comparison {self.comparison!r}; supported "
                f"comparisons are {COMPARISONS}"
            )
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise InvalidRiskConfigurationError(
                f"rule {self.rule_id!r} value must be a real number, got "
                f"{type(self.value).__name__}"
            )
        if not math.isfinite(float(self.value)):
            raise InvalidRiskConfigurationError(
                f"rule {self.rule_id!r} value must be finite, got {self.value!r}"
            )
        if self.escalate_to not in SUPPORTED_RISK_LEVELS:
            raise InvalidRiskConfigurationError(
                f"rule {self.rule_id!r} escalates to {self.escalate_to!r}, which is not one "
                f"of the platform risk levels {SUPPORTED_RISK_LEVELS}; a risk level this "
                f"platform cannot speak is not a level it may produce"
            )

    def compare(self, value: float) -> bool:
        """Does `value` satisfy this rule's comparison?"""
        return bool(_COMPARISONS[self.comparison](value, float(self.value)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "signal": self.signal,
            "quantity": self.quantity,
            "comparison": self.comparison,
            "value": self.value,
            "unit": self.unit,
            "escalate_to": self.escalate_to,
            "source": self.source,
            "required": self.required,
            "note": self.note,
        }


@dataclass(frozen=True)
class RiskConfiguration:
    """Everything the risk layer is allowed to assume, declared in one place.

    `policy` is Phase 1's `RiskPolicy`, reused unchanged — the flood threshold, its
    source, its approval status and the band edges all live there. This class adds
    only what a *contextual* assessment needs on top of a point forecast: the
    escalation rules, how old a signal may be, and identifiers for the configuration
    itself so a result can be traced back to the assumptions that produced it.

    With no rules and no age limits, a configuration still works: it produces the
    exceedance probability and the band, and reports the context as evaluated or not
    without acting on it. That is the honest default, and it is why nothing in this
    class has a non-empty default beyond the version string.
    """

    policy: RiskPolicy
    rules: tuple[RiskEscalationRule, ...] = ()
    signal_max_age_seconds: Mapping[str, float] = dataclasses.field(default_factory=dict)
    default_max_age_seconds: float | None = None
    threshold_units: str | None = None
    risk_configuration_version: str = RISK_CONFIGURATION_VERSION
    threshold_configuration_version: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.policy, RiskPolicy):
            raise InvalidRiskConfigurationError(
                f"RiskConfiguration.policy must be a config.RiskPolicy, got "
                f"{type(self.policy).__name__}; Phase 6 reuses that policy rather than "
                f"declaring a second threshold surface"
            )

        if not isinstance(self.rules, tuple):
            object.__setattr__(self, "rules", tuple(self.rules))
        for rule in self.rules:
            if not isinstance(rule, RiskEscalationRule):
                raise InvalidRiskConfigurationError(
                    f"RiskConfiguration.rules holds a {type(rule).__name__}"
                )
        identifiers = [rule.rule_id for rule in self.rules]
        duplicates = sorted({name for name in identifiers if identifiers.count(name) > 1})
        if duplicates:
            raise InvalidRiskConfigurationError(
                f"escalation rule ids {duplicates} appear more than once; a rule that "
                f"cannot be named in an explanation cannot be audited"
            )
        # Sorted so escalation order — and therefore the explanation order — does not
        # depend on how the operator happened to list the rules.
        object.__setattr__(self, "rules", tuple(sorted(self.rules, key=lambda r: r.rule_id)))

        ages = dict(self.signal_max_age_seconds or {})
        for name, limit in ages.items():
            if isinstance(limit, bool) or not isinstance(limit, (int, float)):
                raise InvalidRiskConfigurationError(
                    f"signal_max_age_seconds[{name!r}] must be a number of seconds, got "
                    f"{type(limit).__name__}"
                )
            if not math.isfinite(float(limit)) or float(limit) <= 0:
                raise InvalidRiskConfigurationError(
                    f"signal_max_age_seconds[{name!r}] must be positive and finite, got "
                    f"{limit!r}"
                )
        object.__setattr__(self, "signal_max_age_seconds", ages)

        if self.default_max_age_seconds is not None:
            if isinstance(self.default_max_age_seconds, bool) or not isinstance(
                self.default_max_age_seconds, (int, float)
            ):
                raise InvalidRiskConfigurationError(
                    f"default_max_age_seconds must be a number of seconds or None, got "
                    f"{type(self.default_max_age_seconds).__name__}"
                )
            if not math.isfinite(float(self.default_max_age_seconds)) or float(
                self.default_max_age_seconds
            ) <= 0:
                raise InvalidRiskConfigurationError(
                    f"default_max_age_seconds must be positive and finite, got "
                    f"{self.default_max_age_seconds!r}"
                )

        if self.threshold_units is not None:
            if not isinstance(self.threshold_units, str) or not self.threshold_units.strip():
                raise InvalidRiskConfigurationError(
                    f"threshold_units must be a unit string or None, got "
                    f"{self.threshold_units!r}"
                )
            from .preprocess_units import dimension_of

            if dimension_of(self.threshold_units) is None:
                raise InvalidRiskConfigurationError(
                    f"threshold_units {self.threshold_units!r} is not a unit this "
                    f"repository recognises; a threshold in an unknown unit cannot be "
                    f"checked against a forecast"
                )

        if self.policy.is_usable:
            unknown = [
                label for label in self.policy.band_labels if label not in SUPPORTED_RISK_LEVELS
            ]
            if unknown:
                raise InvalidRiskConfigurationError(
                    f"policy band labels {unknown} are outside the platform vocabulary "
                    f"{SUPPORTED_RISK_LEVELS}; Phase 6 will not emit a risk level the "
                    f"platform cannot read"
                )
            for rule in self.rules:
                if rule.escalate_to not in self.policy.band_labels:
                    raise InvalidRiskConfigurationError(
                        f"rule {rule.rule_id!r} escalates to {rule.escalate_to!r}, which is "
                        f"not among the policy's band labels {self.policy.band_labels}; a "
                        f"rule may only escalate to a band this policy can produce"
                    )

        if not isinstance(self.risk_configuration_version, str) or not (
            self.risk_configuration_version.strip()
        ):
            raise InvalidRiskConfigurationError(
                "risk_configuration_version must be a non-empty string; a configuration "
                "with no version cannot be traced back to"
            )

    # --- derived -----------------------------------------------------------

    @property
    def threshold_configuration(self) -> str:
        """An identifier for the threshold configuration actually in force.

        Prefers the operator's own version string, falls back to the policy's
        declared source, and finally says `unconfigured` rather than inventing one.
        """
        return (
            self.threshold_configuration_version
            or self.policy.threshold_source
            or THRESHOLD_UNCONFIGURED
        )

    @property
    def is_usable(self) -> bool:
        """True when the policy can produce a band at all."""
        return self.policy.is_usable

    def missing_configuration(self) -> tuple[str, ...]:
        """Exactly what an operator still has to supply for a risk level."""
        return tuple(RiskAssessor(self.policy).missing_configuration())

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_configuration_version": self.risk_configuration_version,
            "threshold_configuration": self.threshold_configuration,
            "threshold_units": self.threshold_units,
            "policy": {
                "flood_threshold": self.policy.flood_threshold,
                "threshold_source": self.policy.threshold_source,
                "policy_status": self.policy.policy_status,
                "band_edges": list(self.policy.band_edges),
                "band_labels": list(self.policy.band_labels),
                "usable": self.policy.is_usable,
            },
            "rules": [rule.to_dict() for rule in self.rules],
            "signal_max_age_seconds": dict(self.signal_max_age_seconds),
            "default_max_age_seconds": self.default_max_age_seconds,
            "notes": self.notes,
        }


# --------------------------------------------------------------------------- #
# Rule evaluation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EscalationEvaluation:
    """What one configured rule did, whether or not it fired.

    Non-fired rules are recorded too. A result that lists only the rules that fired
    leaves a reader unable to tell "no rule fired" from "no rule was configured" —
    and those support very different conclusions about the same band.
    """

    rule_id: str
    signal: str
    quantity: str
    comparison: str
    configured_value: float
    configured_units: str
    escalate_to: str
    source: str
    fired: bool
    reason: str
    observed_value: float | None = None
    observed_units: str | None = None
    converted_from: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "signal": self.signal,
            "quantity": self.quantity,
            "comparison": self.comparison,
            "configured_value": self.configured_value,
            "configured_units": self.configured_units,
            "escalate_to": self.escalate_to,
            "source": self.source,
            "fired": self.fired,
            "reason": self.reason,
            "observed_value": self.observed_value,
            "observed_units": self.observed_units,
            "converted_from": self.converted_from,
        }


def _evaluate_rule(
    rule: RiskEscalationRule,
    signals: Mapping[str, SignalEvaluation],
) -> EscalationEvaluation:
    """Compare one rule's configured value against one evaluated signal.

    Unit handling is explicit in both directions: identical units are used as they
    are, convertible units are converted with an exact documented factor, and the
    converted value and its source unit are both recorded. Incompatible dimensions
    are never reconciled — a `mm` accumulation and a `mm/h` intensity have no factor
    between them, and Phase 2's own unit module says so.
    """
    evaluation = signals.get(rule.signal)

    if evaluation is None:
        if rule.required:
            raise MissingRiskContextError(
                f"rule {rule.rule_id!r} requires signal {rule.signal!r}, which the risk "
                f"context does not declare; declaring the gap is what makes the rule "
                f"reportable"
            )
        return EscalationEvaluation(
            rule_id=rule.rule_id,
            signal=rule.signal,
            quantity=rule.quantity,
            comparison=rule.comparison,
            configured_value=float(rule.value),
            configured_units=rule.unit,
            escalate_to=rule.escalate_to,
            source=rule.source,
            fired=False,
            reason=f"signal {rule.signal!r} is not declared by the risk context",
        )

    if evaluation.quantity != rule.quantity:
        if rule.required:
            raise InvalidRiskConfigurationError(
                f"rule {rule.rule_id!r} reads quantity {rule.quantity!r} but signal "
                f"{rule.signal!r} is a {evaluation.quantity}; a rule cannot compare a "
                f"signal it has mislabelled"
            )
        return EscalationEvaluation(
            rule_id=rule.rule_id,
            signal=rule.signal,
            quantity=rule.quantity,
            comparison=rule.comparison,
            configured_value=float(rule.value),
            configured_units=rule.unit,
            escalate_to=rule.escalate_to,
            source=rule.source,
            fired=False,
            reason=(
                f"signal {rule.signal!r} is a {evaluation.quantity}, not the "
                f"{rule.quantity} this rule compares"
            ),
        )

    if not evaluation.usable or evaluation.value is None:
        if rule.required:
            if evaluation.availability == "stale":
                raise StaleContextRuleError(
                    f"rule {rule.rule_id!r} requires signal {rule.signal!r}, which is "
                    f"stale: {evaluation.reason}"
                )
            raise MissingRiskContextError(
                f"rule {rule.rule_id!r} requires signal {rule.signal!r}, which is "
                f"{evaluation.availability}: {evaluation.reason}"
            )
        return EscalationEvaluation(
            rule_id=rule.rule_id,
            signal=rule.signal,
            quantity=rule.quantity,
            comparison=rule.comparison,
            configured_value=float(rule.value),
            configured_units=rule.unit,
            escalate_to=rule.escalate_to,
            source=rule.source,
            fired=False,
            reason=(
                f"signal {rule.signal!r} was {evaluation.availability}: {evaluation.reason}"
            ),
        )

    value = float(evaluation.value)
    units = evaluation.unit
    converted_from: str | None = None

    if units != rule.unit:
        conversion = normalize_unit(value, str(units), target_unit=rule.unit)
        if not conversion.converted:
            if rule.required:
                raise InvalidUnitsError(
                    f"rule {rule.rule_id!r} compares {rule.signal!r} in {rule.unit!r}, but "
                    f"the signal is in {units!r}: {conversion.note}"
                )
            return EscalationEvaluation(
                rule_id=rule.rule_id,
                signal=rule.signal,
                quantity=rule.quantity,
                comparison=rule.comparison,
                configured_value=float(rule.value),
                configured_units=rule.unit,
                escalate_to=rule.escalate_to,
                source=rule.source,
                fired=False,
                reason=(
                    f"signal {rule.signal!r} is in {units!r}, which is not convertible to "
                    f"the rule's {rule.unit!r}: {conversion.note}"
                ),
                observed_value=value,
                observed_units=units,
            )
        value = float(conversion.value)
        converted_from = units

    fired = rule.compare(value)
    if fired:
        reason = (
            f"signal {rule.signal!r} measured {value!r} {rule.unit} "
            f"{conversion_note(converted_from)}which satisfies {rule.comparison} "
            f"{rule.value!r} {rule.unit}"
        )
    else:
        reason = (
            f"signal {rule.signal!r} measured {value!r} {rule.unit} "
            f"{conversion_note(converted_from)}which does not satisfy "
            f"{rule.comparison} {rule.value!r} {rule.unit}"
        )
    return EscalationEvaluation(
        rule_id=rule.rule_id,
        signal=rule.signal,
        quantity=rule.quantity,
        comparison=rule.comparison,
        configured_value=float(rule.value),
        configured_units=rule.unit,
        escalate_to=rule.escalate_to,
        source=rule.source,
        fired=fired,
        reason=reason,
        observed_value=value,
        observed_units=units,
        converted_from=converted_from,
    )


def conversion_note(converted_from: str | None) -> str:
    """A short clause describing an explicit unit conversion, or nothing."""
    return f"(converted from {converted_from}) " if converted_from else ""


class StaleContextRuleError(RiskBoundaryError):
    """A rule that declared a signal *required* found it stale.

    Distinct from `risk_context.StaleContextError`, which is raised by
    `evaluate_context`. This one is raised later, by the rule evaluator: the signal
    exists and is readable, it simply is not fresh enough for the rule that depends
    on it, and which of those two happened matters to whoever reads the log.
    """

    reason = "stale_rule_signal"


# --------------------------------------------------------------------------- #
# RiskResult
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RiskResult:
    """One risk assessment, with every field either true or honestly absent.

    `status` uses `domains.RISK_STATUSES` — `recorded` when a level was assigned,
    `withheld` when none could be — so this record and the repository's own
    `RiskScoreRecord` cannot drift apart on what "no risk level" is called.

    `evaluation_state` is the separate question of how much of the *context* was
    read. The two are independent on purpose: a level can be `recorded` while the
    context is `context_unavailable` (the forecast alone carried it), and a context
    can be `fully_evaluated` while the status is `withheld` (no threshold is
    configured). Collapsing them would make one of those two combinations
    unrepresentable.

    `explanation` holds sentences derived from what was actually evaluated. There is
    no template that produces a contributor the pipeline did not read.
    """

    risk_result_id: str
    status: str
    evaluation_state: str
    risk_level: str | None
    risk_score: float | None
    risk_score_type: str | None
    assessment: RiskAssessment | None
    threshold: float | None
    threshold_units: str | None
    threshold_source: str | None
    threshold_policy: str
    threshold_configuration: str
    band_edges: tuple[float, ...]
    band_labels: tuple[str, ...]
    residual_sigma: float | None
    residual_sigma_source: str | None
    forecast_id: str | None
    forecast: ForecastInference | None
    signals: tuple[SignalEvaluation, ...]
    escalations: tuple[EscalationEvaluation, ...]
    explanation: tuple[str, ...]
    uncertainty: Uncertainty
    provenance: ProvenanceRecord
    provenance_chain: Mapping[str, Any]
    gis_context: Mapping[str, Any] | None
    historical_context: Mapping[str, Any] | None
    context_digest: str
    synthetic_demo: bool
    data_status: str
    disclaimer: str
    risk_configuration_version: str
    production_ready_claimed: bool = False
    risk_contract_version: str = RISK_CONTRACT_VERSION

    # --- derived -----------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """True when a level was actually assigned."""
        return self.status == RISK_STATUS_RECORDED and self.risk_level is not None

    @property
    def priority(self) -> str | None:
        """The backend's priority vocabulary, derived by the platform's own mapping."""
        return priority_for_risk_level(self.risk_level) if self.risk_level else None

    @property
    def usable_signals(self) -> tuple[SignalEvaluation, ...]:
        return tuple(signal for signal in self.signals if signal.usable)

    @property
    def fired_rules(self) -> tuple[EscalationEvaluation, ...]:
        return tuple(rule for rule in self.escalations if rule.fired)

    @property
    def availability_counts(self) -> dict[str, int]:
        return availability_counts(self.signals)

    def explain(self) -> str:
        """The explanation as one paragraph, for a log line or a report cell."""
        return " ".join(self.explanation)

    # --- platform contracts ------------------------------------------------

    def to_forecast_output(self, base: ForecastOutput | None = None) -> ForecastOutput | None:
        """Phase 6's risk fields projected onto the platform `ForecastOutput`.

        `base` is the Phase 5 `ForecastOutput` for the same forecast when there is
        one, so the forecast fields are Phase 5's and only the risk fields are
        added. Returns `None` when there is neither a forecast nor a base: an output
        needs a forecast to be an output, and Phase 6 does not invent one.
        """
        if self.forecast is None and base is None:
            return None
        fields: dict[str, Any] = {}
        if base is not None:
            fields = {f.name: getattr(base, f.name) for f in dataclasses.fields(base)}
        else:
            inference = self.forecast
            assert inference is not None  # guarded above
            fields = {
                "forecast_id": f"risk:{self.risk_result_id}",
                "forecast_timestamp": _stamp(inference.prediction_timestamp)
                or inference.origin_instant.isoformat(),
                "forecast_horizon": inference.horizon,
                "model_id": inference.model_id,
                "model_version": inference.model_version,
                "station_reference": inference.entity,
                "target": inference.target,
                "target_units": inference.target_units,
                "predicted_value": float(inference.prediction),
            }

        fields["flood_probability"] = self.assessment.flood_probability
        fields["risk_level"] = self.risk_level
        fields["risk_score"] = self.risk_score
        fields["threshold"] = self.threshold
        fields["threshold_policy"] = self.threshold_policy
        fields["residual_sigma"] = self.residual_sigma
        fields["disclaimer"] = self.disclaimer
        return ForecastOutput(**fields)

    def to_risk_score_record(self) -> RiskScoreRecord | None:
        """This assessment as the repository's `RiskScoreRecord` schema.

        `assessed_at` is the forecast origin, not a clock reading: the assessment is
        made at the instant the forecast was made, and stamping it with `now()` would
        make two identical assessments differ for no reason. Returns `None` without
        a forecast, because the record is about a place and a moment and a risk
        level attached to neither is not a record.
        """
        if self.forecast is None:
            return None
        return RiskScoreRecord(
            area_reference=self.forecast.entity,
            risk_score=self.risk_score,
            risk_level=self.risk_level,
            forecast_reference=self.forecast_id,
            assessed_at=self.forecast.origin_instant.isoformat(),
            status=RISK_STATUS_RECORDED if self.is_available else RISK_STATUS_WITHHELD,
            threshold=self.threshold,
            threshold_policy=self.threshold_policy,
            threshold_source=self.threshold_source,
            provenance_reference=self.provenance.artifact_reference,
            dataset_reference=self.provenance.dataset_reference,
            dataset_type=self.provenance.dataset_type,
            disclaimer=self.disclaimer,
            notes=self.explain(),
        )

    # --- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_contract_version": self.risk_contract_version,
            "risk_result_id": self.risk_result_id,
            "forecast_id": self.forecast_id,
            "status": self.status,
            "evaluation_state": self.evaluation_state,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "risk_score_type": self.risk_score_type,
            "threshold": self.threshold,
            "threshold_units": self.threshold_units,
            "threshold_source": self.threshold_source,
            "threshold_policy": self.threshold_policy,
            "threshold_configuration": self.threshold_configuration,
            "band_edges": list(self.band_edges),
            "band_labels": list(self.band_labels),
            "residual_sigma": self.residual_sigma,
            "residual_sigma_source": self.residual_sigma_source,
            "risk_configuration_version": self.risk_configuration_version,
            "context_digest": self.context_digest,
            "availability_counts": self.availability_counts,
            "signals": [signal.to_dict() for signal in self.signals],
            "escalations": [rule.to_dict() for rule in self.escalations],
            "explanation": list(self.explanation),
            "uncertainty": self.uncertainty.to_dict(),
            "forecast": _forecast_summary(self.forecast),
            "provenance": self.provenance.to_dict(),
            "provenance_chain": dict(self.provenance_chain),
            "gis_context": dict(self.gis_context) if self.gis_context else None,
            "historical_context": (
                dict(self.historical_context) if self.historical_context else None
            ),
            "synthetic_demo": self.synthetic_demo,
            "data_status": self.data_status,
            "disclaimer": self.disclaimer,
            "production_ready_claimed": self.production_ready_claimed,
        }


def _forecast_summary(inference: ForecastInference | None) -> dict[str, Any] | None:
    """The forecast facts a risk result carries, in the platform's own spelling.

    Phase 5's `ForecastInference` is a 28-field inference record; a risk report wants
    the dozen fields that identify the forecast. The object itself is kept on
    `RiskResult.forecast` — this is the serialised projection, not a replacement.
    """
    if inference is None:
        return None
    return {
        "model_id": inference.model_id,
        "model_family": inference.model_family,
        "model_version": inference.model_version,
        "artifact_id": inference.artifact_id,
        "feature_digest": inference.feature_digest,
        "entity": inference.entity,
        "target": inference.target,
        "target_units": inference.target_units,
        "horizon": inference.horizon,
        "prediction": inference.prediction,
        "origin_instant": inference.origin_instant.isoformat(),
        "prediction_timestamp": inference.prediction_timestamp,
        "strategy": inference.strategy,
        "feature_count": inference.feature_count,
        "synthetic_demo": inference.synthetic_demo,
        "data_status": inference.data_status,
    }


# --------------------------------------------------------------------------- #
# Deterministic identity
# --------------------------------------------------------------------------- #


def _canonical(payload: Any) -> str:
    """JSON with sorted keys and no incidental whitespace, for hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _digest(payload: Any, length: int = 12) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:length]


def context_digest(signals: Sequence[SignalEvaluation]) -> str:
    """A short digest of the evaluated evidence.

    Covers the decision-relevant parts of every signal — which signals existed, what
    they said, in what units, and when. Two assessments with the same digest were
    made from the same evidence; that is the property determinism testing asserts,
    so the digest has to be computed from evidence rather than from object identity.
    """
    return _digest(
        [
            {
                "name": signal.name,
                "quantity": signal.quantity,
                "availability": signal.availability,
                "usable": signal.usable,
                "value": signal.value,
                "unit": signal.unit,
                "observed_at": signal.observed_at.isoformat() if signal.observed_at else None,
            }
            for signal in signals
        ]
    )


def default_risk_result_id(
    *,
    forecast_id: str | None,
    entity: str,
    target: str,
    horizon: str,
    origin_instant: dt.datetime,
    risk_configuration_version: str,
    threshold_configuration: str,
    context_digest: str,
) -> str:
    """A deterministic identifier for one risk assessment.

    Readable in the same shape as Phase 5's `default_forecast_id`, with a digest
    suffix covering everything the readable part cannot: the evidence and the
    configuration. Derived from inputs only — no clock, no UUID — so the same
    forecast, context and configuration always produce the same id.
    """
    stamp = origin_instant.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    fingerprint = _digest(
        {
            "risk_configuration_version": risk_configuration_version,
            "threshold_configuration": threshold_configuration,
            "context_digest": context_digest,
        }
    )
    return (
        f"risk-{entity}-{target}-{horizon}-{stamp}-"
        f"{forecast_id or 'no_forecast'}@{fingerprint}"
    )


# --------------------------------------------------------------------------- #
# Forecast resolution
# --------------------------------------------------------------------------- #


def _stamp(value: str | None) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _resolve_forecast(
    served: ServedForecast | ForecastInference | None,
) -> tuple[ForecastInference, str | None, ServedForecast | None]:
    """Accept either Phase 5 shape and insist it carries a forecast.

    Both `ServedForecast` and `ForecastInference` are Phase 5's own types, so
    accepting both is not a second contract — it is refusing to force a caller that
    already holds a validated inference to re-run serving in order to ask a risk
    question. A `ServedForecast` is additionally required to be `ready`: a refused
    serving result has no prediction to assess, and treating its reason as a risk
    input would report the same thing twice.
    """
    if served is None:
        raise MissingForecastError(
            "a Phase 5 forecast result is required; risk assessment consumes a "
            "validated forecast and never produces one"
        )

    if isinstance(served, ServedForecast):
        if served.status != "ready":
            raise InvalidForecastError(
                f"the Phase 5 serving status is {served.status!r}, not 'ready'"
                + (f": {served.reason}" if served.reason else "")
            )
        if served.inference is None:
            raise InvalidForecastError(
                f"the Phase 5 result is 'ready' but carries no inference "
                f"(state={served.state!r}, artifact_id={served.artifact_id!r})"
            )
        inference = served.inference
        if not isinstance(inference.prediction, float) or not math.isfinite(
            inference.prediction
        ):
            raise InvalidForecastError(
                f"the forecast carries no usable prediction value ({inference.prediction!r})"
            )
        return inference, served.forecast_id, served

    if isinstance(served, ForecastInference):
        if not isinstance(served.prediction, float) or not math.isfinite(served.prediction):
            raise InvalidForecastError(
                f"the forecast carries no usable prediction value ({served.prediction!r})"
            )
        return served, None, None

    raise InvalidForecastError(
        f"expected a Phase 5 ServedForecast or ForecastInference, got "
        f"{type(served).__name__}"
    )


def _require_units(inference: ForecastInference, config: RiskConfiguration) -> str:
    """Settle the unit the threshold is expressed in, refusing ambiguity.

    `RiskPolicy` defines its threshold as being in the target's units, so the
    forecast's own `target_units` is the default. When the operator declares a
    threshold unit, it must be dimensionally compatible with the forecast's — a
    threshold in millimetres against a forecast in metres is comparable, and the
    conversion is exact, but a threshold in `m3/s` is not comparable at all and
    saying so beats guessing.
    """
    forecast_units = inference.target_units
    if not isinstance(forecast_units, str) or not forecast_units.strip():
        raise InvalidUnitsError(
            f"the forecast for {inference.target!r} does not state its units, so no "
            f"threshold can be checked against it; a threshold and a forecast in "
            f"unrelated units would compare two different quantities"
        )

    if config.threshold_units is None:
        return forecast_units

    forecast_dimension = dimension_of(forecast_units)
    threshold_dimension = dimension_of(config.threshold_units)
    if forecast_dimension != threshold_dimension:
        raise InvalidUnitsError(
            f"the configured threshold unit {config.threshold_units!r} has dimension "
            f"{threshold_dimension!r} but the forecast is in {forecast_units!r} with "
            f"dimension {forecast_dimension!r}"
        )
    return config.threshold_units


def _validate_threshold(config: RiskConfiguration) -> None:
    """Refuse a threshold that cannot be compared with anything.

    `RiskPolicy.is_usable` only asks whether a threshold is present, so a `NaN` or a
    non-number reaches this layer intact. `risk.exceedance_probability` would then
    raise, and without this check that would surface as an arithmetic failure — which
    blames the calculation for a fault in the configuration. A threshold that is not a
    finite real number is reported as the invalid threshold it is.
    """
    if not config.policy.is_usable:
        return
    threshold = config.policy.flood_threshold
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise InvalidThresholdError(
            f"the configured flood threshold must be a real number, got "
            f"{threshold!r} of type {type(threshold).__name__}"
        )
    if not math.isfinite(float(threshold)):
        raise InvalidThresholdError(
            f"the configured flood threshold must be finite, got {threshold!r}; a "
            f"non-finite threshold compares against nothing"
        )


def _resolve_sigma(
    residuals: Sequence[float] | None,
    residual_sigma: float | None,
) -> tuple[float | None, str | None]:
    """Resolve a *measured* residual spread, or say plainly that there is none.

    Two ways in, both measurements: a sequence of real residuals, which
    `risk.residual_sigma` reduces to a ddof=1 standard deviation, or a spread the
    caller already measured. Aggregate metrics are not accepted, for the reason in
    the module docstring.
    """
    if residuals is not None and residual_sigma is not None:
        raise InvalidRiskCalculationError(
            "supply either residuals or a measured residual_sigma, not both; two "
            "sources for one spread means nobody can say which one was used"
        )

    if residuals is not None:
        try:
            value = measured_residual_sigma(list(residuals))
        except RiskError as exc:
            raise InvalidRiskCalculationError(
                f"the supplied residuals could not be reduced to a measured spread: {exc}"
            ) from exc
        return value, f"{SIGMA_SOURCE_RESIDUALS}(n={len(list(residuals))})"

    if residual_sigma is not None:
        if isinstance(residual_sigma, bool) or not isinstance(residual_sigma, (int, float)):
            raise InvalidRiskCalculationError(
                f"residual_sigma must be a real number or None, got "
                f"{type(residual_sigma).__name__}"
            )
        value = float(residual_sigma)
        if not math.isfinite(value) or value <= 0:
            raise InvalidRiskCalculationError(
                f"residual_sigma must be a positive finite measurement, got "
                f"{residual_sigma!r}; with no spread there is no distribution and a "
                f"confident 0 or 1 would be a fabrication"
            )
        return value, SIGMA_SOURCE_SUPPLIED

    return None, SIGMA_SOURCE_ABSENT


#: Why no risk level was assigned when no residual spread was supplied. The wording
#: is deliberately specific, because "insufficient data" would leave a reader
#: thinking more data of any kind would help.
SIGMA_ABSENT_REASON = (
    "no measured residual spread was supplied, so no exceedance probability could be "
    "computed and no risk level was assigned. A Phase 5 artifact carries aggregate "
    "metrics (mae, rmse, r2, bias) but not the residuals themselves, so a spread cannot "
    "be measured from it. rmse is not a substitute: it is the root-mean-square error "
    "about zero, while the normal exceedance model needs the standard deviation of "
    "residuals about their mean, and the two differ whenever the model is biased. "
    "Supply residuals, or a residual sigma you measured yourself."
)


# --------------------------------------------------------------------------- #
# Escalation
# --------------------------------------------------------------------------- #


def _apply_escalations(
    assessment: Any,
    escalations: Sequence[EscalationEvaluation],
) -> tuple[Any, tuple[str, ...]]:
    """Raise the band to the highest level any fired rule asked for.

    The base band from `risk.classify_risk_level` is authoritative and a rule can
    only *raise* it — a rule that would lower a band is recorded as not firing,
    because a contextual rule has no business overriding a computed probability. When
    no band was assigned at all, fired rules are recorded and the level stays
    unassigned; escalating an absent level would manufacture one.
    """
    fired = [rule for rule in escalations if rule.fired]
    if not fired:
        return assessment, ()

    if assessment.risk_level is None:
        notes = tuple(
            f"rule {rule.rule_id!r} fired ({rule.reason}) but no risk band was assigned, "
            f"so nothing was escalated"
            for rule in fired
        )
        return assessment, notes

    order = {level: index for index, level in enumerate(SUPPORTED_RISK_LEVELS)}
    current = order[assessment.risk_level]
    best = max(fired, key=lambda rule: order[rule.escalate_to])

    if order[best.escalate_to] <= current:
        notes = tuple(
            f"rule {rule.rule_id!r} fired ({rule.reason}) but {assessment.risk_level} is "
            f"already at or above {rule.escalate_to}"
            for rule in fired
        )
        return assessment, notes

    notes = tuple(
        f"rule {rule.rule_id!r} fired ({rule.reason})"
        + (
            f"; escalated {assessment.risk_level} -> {best.escalate_to}"
            if rule.rule_id == best.rule_id
            else f"; escalation to {rule.escalate_to} superseded by {best.escalate_to}"
        )
        for rule in fired
    )
    escalated = dataclasses.replace(
        assessment,
        risk_level=best.escalate_to,
        notes=" ".join(part for part in (assessment.notes, *notes) if part).strip(),
    )
    return escalated, notes


# --------------------------------------------------------------------------- #
# Explanation
# --------------------------------------------------------------------------- #


def _build_explanation(
    *,
    inference: ForecastInference | None,
    assessment: Any,
    sigma: float | None,
    sigma_source: str | None,
    signals: Sequence[SignalEvaluation],
    escalations: Sequence[EscalationEvaluation],
    escalation_notes: Sequence[str],
    context: RiskContext,
    config: RiskConfiguration,
    threshold_units: str | None,
    provenance_synthetic: bool,
) -> tuple[str, ...]:
    """Assemble the explanation from what was actually evaluated.

    Every sentence is generated from state that exists. There is no fixed template
    that could name a signal which was not read, and no branch that adds a
    contributor the pipeline did not have. Lines are ordered so the result reads
    top-down: what was predicted, what it was compared against, how the band came
    out, what else was read, and what was not.
    """
    lines: list[str] = []

    # --- the forecast ----------------------------------------------------
    if inference is not None:
        units = inference.target_units or "unstated units"
        lines.append(
            f"forecast {inference.prediction!r} {units} for {inference.target} at "
            f"{inference.entity}, origin {inference.origin_instant.isoformat()}, horizon "
            f"{inference.horizon}, prediction instant "
            f"{inference.prediction_timestamp or 'unstated'}, from "
            f"{inference.model_family}/{inference.model_id} "
            f"(version {inference.model_version}, artifact {inference.artifact_id})"
        )
    else:
        lines.append("no validated forecast was available, so nothing was assessed")

    # --- the threshold ----------------------------------------------------
    policy = config.policy
    if not policy.is_usable:
        lines.append(
            "no usable threshold policy: "
            + (
                f"flood threshold {policy.flood_threshold!r}, bands "
                f"{list(policy.band_edges)}"
                if policy.flood_threshold is not None or policy.band_edges
                else "neither a flood stage nor any band edge is configured"
            )
        )
        missing = config.missing_configuration()
        if missing:
            lines.append("an operator still has to supply " + "; ".join(missing))
    else:
        # `risk.classify_risk_level` is the authority on whether a set of edges
        # describes a band mapping: it accepts `len(labels)` edges or
        # `len(labels) - 1` interior edges, and nothing else. Repeating that rule
        # here to keep the explanation tidy would be a second, inevitably divergent
        # copy of it, so the two arities are named as they are and the mismatch is
        # stated rather than papered over.
        edges = list(policy.band_edges)
        labels = list(policy.band_labels)
        if len(edges) in (len(labels), len(labels) - 1):
            mapping = f"band edges {edges} map to {labels}"
        else:
            mapping = (
                f"band edges {edges} do not describe {len(labels)} bands "
                f"{labels}, so they assign no band"
            )
        lines.append(
            f"threshold {policy.flood_threshold!r} {threshold_units or 'unstated units'} "
            f"from {policy.threshold_source or 'an unrecorded source'}; {mapping}; "
            f"policy status {policy.policy_status!r}"
            + (
                " (APPROVED)"
                if policy.policy_status == "approved"
                else " (NOT an approved flood stage - bands are demo values)"
            )
        )

    # --- the probability --------------------------------------------------
    if sigma is None:
        lines.append(SIGMA_ABSENT_REASON)
    else:
        lines.append(
            f"residual spread {sigma!r} taken from {sigma_source}; exceedance probability "
            f"P(target > threshold) = {assessment.flood_probability!r} under method "
            f"{assessment.method!r}"
        )

    if assessment.risk_level is not None:
        lines.append(
            f"the probability falls in band {assessment.risk_level} "
            f"(of {list(policy.band_labels)})"
        )
    else:
        lines.append(
            "no risk band could be assigned, so no risk level is reported; the absence is "
            "a statement, not a LOW rating"
        )

    # --- the context ------------------------------------------------------
    counts = availability_counts(signals)
    if not signals:
        lines.append("the risk context declared no signals")
    else:
        parts = [f"{state}={counts.get(state, 0)}" for state in sorted(counts)]
        lines.append(
            f"context evaluated at state {evaluation_state(signals)} with "
            f"{len(signals)} declared signal(s): " + ", ".join(parts)
        )
        for signal in signals:
            if signal.usable:
                lines.append(
                    f"signal {signal.name!r} read {signal.value!r} {signal.unit} "
                    f"({signal.quantity}, {signal.source}) at "
                    f"{signal.observed_at.isoformat() if signal.observed_at else 'unstated'}"
                )
            else:
                lines.append(
                    f"signal {signal.name!r} ({signal.quantity}) not evaluated: "
                    f"{signal.availability} - {signal.reason}"
                )

    if context.gis is not None and not context.gis.available:
        lines.append(f"spatial exposure context unavailable: {context.gis.reason}")
    if context.historical is not None and not context.historical.available:
        lines.append(
            f"historical flood context unavailable: {context.historical.reason}"
        )

    # --- the rules --------------------------------------------------------
    if not escalations:
        lines.append(
            "no escalation rules are configured, so the context informed the explanation "
            "and the evaluation state but could not change the band"
        )
    else:
        for rule in escalations:
            lines.append(
                f"rule {rule.rule_id!r} ({rule.source}): {rule.reason}"
                + (
                    f" -> escalated to {rule.escalate_to}"
                    if rule.fired
                    else " -> no escalation"
                )
            )
    lines.extend(escalation_notes)

    # --- uncertainty ------------------------------------------------------
    uncertainty = inference.uncertainty if inference is not None else None
    if uncertainty is None or not uncertainty.available:
        reason = uncertainty.reason if uncertainty is not None else "no forecast carried one"
        lines.append(
            f"no uncertainty is available for this forecast, and none is invented: {reason}"
        )
    else:
        lines.append(
            f"uncertainty {uncertainty.value!r} {uncertainty.unit or ''} from "
            f"{uncertainty.source or 'an unrecorded source'}"
            + (
                "; it is NOT a prediction interval and NOT a guarantee about any value"
                if not uncertainty.is_prediction_interval
                else ""
            )
        )

    # --- production safety ------------------------------------------------
    if config.policy.policy_status != "approved":
        # Only call it a band when one was actually assigned. Saying "this level"
        # about a result that has no level would put a claim in the explanation the
        # result does not support, which is the one thing an explanation must never
        # do.
        lines.append(
            "the threshold policy is still pending approval, so "
            + (
                "this level is a demo band and carries no official meaning"
                if assessment.risk_level is not None
                else "no level it could assign would carry any official meaning"
            )
        )
    if provenance_synthetic:
        lines.append(SYNTHETIC_DATA_DISCLAIMER)

    return tuple(lines)


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


def _rebuild_split(value: Any) -> Any:
    """Re-type a serialised split as `SplitBoundaries` when it plainly is one.

    Phase 5's `ForecastInference.provenance` is a serialised record, so its `split`
    arrives as a mapping of exactly the nine `SplitBoundaries` fields. Rebuilding the
    dataclass keeps the risk record type-correct instead of relying on the
    serialiser's tolerance of both shapes.

    Anything else is left alone rather than coerced. A mapping with fields this
    module does not recognise is evidence of a different provenance shape, and
    guessing at it would invent split boundaries nobody stated.

    The test is the key set and nothing else. Sniffing the value types would look
    tidier and would fail on a perfectly ordinary `numpy` row count, and then a real
    split would be silently left as a mapping.
    """
    if is_dataclass(value) or not isinstance(value, Mapping):
        return value
    if set(value) != {f.name for f in dataclasses.fields(SplitBoundaries)}:
        return value
    return SplitBoundaries(**value)


def _build_provenance(
    inference: ForecastInference | None,
    context: RiskContext,
    config: RiskConfiguration,
) -> ProvenanceRecord:
    """Carry the forecast's provenance forward, on a real `ProvenanceRecord`.

    Phase 5's `ForecastInference.provenance` is already the serialised form of a
    `ProvenanceRecord`, so the honest thing is to reuse it field for field rather
    than build a parallel structure. Two changes, both deliberate:

    * `artifact_reference` is set to the artifact id the forecast came from, so the
      risk record points at the artifact rather than at a dataset;
    * the synthetic disclaimer is guaranteed. `ProvenanceRecord.__post_init__`
      attaches it whenever `dataset_type` is synthetic, so a synthetic forecast
      cannot produce a risk provenance record without the warning — and Phase 6
      does not have to remember to add it.

    The context's own `dataset_type` is *not* merged in. A context assembled from a
    real rainfall record next to a synthetic forecast is a combination the caller
    must be able to see, so it stays visible in `RiskContext` rather than being
    reconciled here.
    """
    if inference is None:
        return ProvenanceRecord(dataset_type=DATASET_TYPE_UNKNOWN)

    source = dict(inference.provenance or {})
    known = {field.name for field in dataclasses.fields(ProvenanceRecord)}
    carried = {key: value for key, value in source.items() if key in known}
    carried.setdefault("target", inference.target)
    carried.setdefault("target_units", inference.target_units)
    carried.setdefault("forecast_horizon", inference.horizon)
    carried.setdefault("station_reference", inference.entity)
    carried.setdefault("model_name", inference.model_family)
    carried.setdefault("model_version", inference.model_version)
    carried["artifact_reference"] = inference.artifact_id
    if "split" in carried:
        carried["split"] = _rebuild_split(carried["split"])

    if not carried.get("disclaimer") and inference.synthetic_demo:
        carried["disclaimer"] = SYNTHETIC_DATA_DISCLAIMER

    dataset_type = carried.get("dataset_type")
    if dataset_type not in (DATASET_TYPE_SYNTHETIC, DATASET_TYPE_UNKNOWN, "real"):
        carried["dataset_type"] = DATASET_TYPE_UNKNOWN
    return ProvenanceRecord(**carried)


def _build_chain(
    *,
    inference: ForecastInference | None,
    context: RiskContext,
    config: RiskConfiguration,
    assessment: Any,
) -> dict[str, Any]:
    """The traceability links from this result back to everything it rests on.

    Kept as a flat mapping on the result rather than folded into the
    `ProvenanceRecord`, because most of these identify *this layer's* assumptions —
    the risk configuration, the threshold configuration, the GIS provider — and
    stuffing them into a dataset-provenance record would misdescribe what they are.
    The dataset provenance stays in `RiskResult.provenance`.
    """
    chain: dict[str, Any] = {
        "risk_contract_version": RISK_CONTRACT_VERSION,
        "serving_contract_version": SERVING_CONTRACT_VERSION,
        "risk_configuration_version": config.risk_configuration_version,
        "threshold_configuration": config.threshold_configuration,
        "threshold_policy_status": config.policy.policy_status,
        "threshold_source": config.policy.threshold_source,
        "risk_score_type": assessment.method,
    }
    if inference is not None:
        chain.update(
            {
                "forecast_artifact_id": inference.artifact_id,
                "model_family": inference.model_family,
                "model_id": inference.model_id,
                "model_version": inference.model_version,
                "feature_digest": inference.feature_digest,
                "forecast_timestamp": inference.prediction_timestamp,
                "forecast_horizon": inference.horizon,
                "entity": inference.entity,
            }
        )
    if context.gis is not None:
        chain["gis_context_provenance"] = context.gis.provenance_reference
        chain["gis_context_available"] = context.gis.available
    if context.historical is not None:
        chain["historical_context_provenance"] = context.historical.provenance_reference
        chain["historical_context_available"] = context.historical.available
    if context.dataset_reference:
        chain["risk_context_dataset_reference"] = context.dataset_reference
    if context.disclaimer:
        chain["risk_context_disclaimer"] = context.disclaimer
    return chain


# --------------------------------------------------------------------------- #
# The boundary
# --------------------------------------------------------------------------- #


def assess_risk(
    served: ServedForecast | ForecastInference | None,
    *,
    config: RiskConfiguration,
    context: RiskContext | None = None,
    residuals: Sequence[float] | None = None,
    residual_sigma: float | None = None,
    assessed_at: dt.datetime | None = None,
    risk_result_id: str | None = None,
) -> RiskResult:
    """Assess the risk carried by one validated Phase 5 forecast.

    The whole boundary in one call: validate the forecast, validate the context
    against it, measure or refuse the residual spread, compute the probability and
    the band, apply any configured escalation, and report everything that was read
    and everything that was not.

    **Raises** a `RiskBoundaryError` for a contract violation — a missing or invalid
    forecast, no context, a station mismatch, evidence from after the origin,
    unusable units, an inconsistent configuration, or a rule whose required signal
    is absent or stale. Those are mistakes in what the caller passed, and a caller
    that is told is better than a caller that gets a plausible number.

    **Returns** a `RiskResult` for every *availability* condition — no threshold
    configured, no measurable residual spread, context that could not be read. Those
    are honest states of the world, not errors, and they come back as a result whose
    `status` is `withheld` and whose `evaluation_state` says why.

    `assessed_at` defaults to the forecast origin. Nothing here reads a clock, so two
    calls with the same arguments produce byte-identical output.
    """
    if not isinstance(config, RiskConfiguration):
        raise InvalidRiskConfigurationError(
            f"config must be a RiskConfiguration, got {type(config).__name__}"
        )

    inference, forecast_id, base = _resolve_forecast(served)

    threshold_units = _require_units(inference, config)
    _validate_threshold(config)

    if context is None:
        raise MissingRiskContextError(
            "a RiskContext is required; a forecast with no declared evidence around it "
            "cannot be reported as a fully assessed risk"
        )

    origin = inference.origin_instant
    if assessed_at is None:
        assessed_at = origin

    signals = evaluate_context(
        context,
        forecast_entity=inference.entity,
        forecast_origin=origin,
        assessed_at=assessed_at,
        max_age_seconds=config.signal_max_age_seconds,
        default_max_age_seconds=config.default_max_age_seconds,
    )
    by_name = {signal.name: signal for signal in signals}

    sigma, sigma_source = _resolve_sigma(residuals, residual_sigma)

    assessor = RiskAssessor(config.policy)
    try:
        assessment = assessor.assess(
            float(inference.prediction),
            residual_sigma=sigma,
            extra_notes=(),
        )
    except RiskError as exc:
        raise InvalidRiskCalculationError(
            f"the exceedance calculation refused to produce a value: {exc}"
        ) from exc

    escalations = tuple(_evaluate_rule(rule, by_name) for rule in config.rules)
    assessment, escalation_notes = _apply_escalations(assessment, escalations)

    # The context state answers "how much evidence was read"; `not_evaluable` answers
    # "was any risk computed at all". They are separate questions, and a level computed
    # from the forecast alone over an empty context is a real combination worth
    # reporting: `context_unavailable` alongside a recorded level says the band came
    # from the forecast with nothing corroborating it, which is not the same claim as
    # a fully evaluated risk.
    if assessment.risk_level is None:
        state = CONTEXT_NOT_EVALUABLE
    else:
        state = evaluation_state(signals)

    synthetic = bool(inference.synthetic_demo)
    if not synthetic and context.synthetic():
        synthetic = True

    digest = context_digest(signals)
    provenance = _build_provenance(inference, context, config)
    disclaimer = provenance.disclaimer or (
        SYNTHETIC_DATA_DISCLAIMER if provenance.is_synthetic else ""
    )

    explanation = _build_explanation(
        inference=inference,
        assessment=assessment,
        sigma=sigma,
        sigma_source=sigma_source,
        signals=signals,
        escalations=escalations,
        escalation_notes=escalation_notes,
        context=context,
        config=config,
        threshold_units=threshold_units,
        provenance_synthetic=provenance.is_synthetic,
    )

    return RiskResult(
        risk_result_id=risk_result_id
        or default_risk_result_id(
            forecast_id=forecast_id,
            entity=inference.entity,
            target=inference.target,
            horizon=inference.horizon,
            origin_instant=origin,
            risk_configuration_version=config.risk_configuration_version,
            threshold_configuration=config.threshold_configuration,
            context_digest=digest,
        ),
        status=RISK_STATUS_RECORDED
        if assessment.risk_level is not None
        else RISK_STATUS_WITHHELD,
        evaluation_state=state,
        risk_level=assessment.risk_level,
        risk_score=assessment.risk_score,
        risk_score_type=RISK_SCORE_TYPE_EXCEEDANCE if assessment.risk_score is not None else None,
        assessment=assessment,
        threshold=assessment.threshold,
        threshold_units=threshold_units,
        threshold_source=assessment.threshold_source,
        threshold_policy=assessment.threshold_policy,
        threshold_configuration=config.threshold_configuration,
        band_edges=tuple(config.policy.band_edges),
        band_labels=tuple(config.policy.band_labels),
        residual_sigma=sigma,
        residual_sigma_source=sigma_source,
        forecast_id=forecast_id,
        forecast=inference,
        signals=signals,
        escalations=escalations,
        explanation=explanation,
        uncertainty=inference.uncertainty,
        provenance=provenance,
        provenance_chain=_build_chain(
            inference=inference, context=context, config=config, assessment=assessment
        ),
        gis_context=context.gis.to_dict() if context.gis else None,
        historical_context=context.historical.to_dict() if context.historical else None,
        context_digest=digest,
        synthetic_demo=synthetic,
        data_status=inference.data_status,
        disclaimer=disclaimer,
        risk_configuration_version=config.risk_configuration_version,
        production_ready_claimed=False,
    )


def risk_from_error(
    error: RiskBoundaryError,
    *,
    config: RiskConfiguration | None = None,
    served: ServedForecast | ForecastInference | None = None,
    risk_result_id: str = "risk-withheld",
) -> RiskResult:
    """A withheld `RiskResult` that names the violation instead of hiding it.

    The operational counterpart to `assess_risk`'s exceptions. An assessment that
    *cannot* be made is still a fact an operator needs, and returning `None` would
    leave the caller with no record of why. The reason is the exception's own
    `reason` tag, so a log consumer can match on a stable string rather than on
    prose.

    Everything that could not be established stays absent: no level, no score, no
    threshold, no signals. There is no partial fabrication here.
    """
    return RiskResult(
        risk_result_id=risk_result_id,
        status=RISK_STATUS_WITHHELD,
        evaluation_state=CONTEXT_NOT_EVALUABLE,
        risk_level=None,
        risk_score=None,
        risk_score_type=None,
        assessment=None,
        threshold=None,
        threshold_units=None,
        threshold_source=None,
        threshold_policy=(config.policy.policy_status if config else "pending"),
        threshold_configuration=(config.threshold_configuration if config else THRESHOLD_UNCONFIGURED),
        band_edges=tuple(config.policy.band_edges) if config else (),
        band_labels=tuple(config.policy.band_labels) if config else (),
        residual_sigma=None,
        residual_sigma_source=SIGMA_SOURCE_ABSENT,
        forecast_id=served.forecast_id if isinstance(served, ServedForecast) else None,
        forecast=(
            served.inference
            if isinstance(served, ServedForecast) and served.inference is not None
            else (served if isinstance(served, ForecastInference) else None)
        ),
        signals=(),
        escalations=(),
        explanation=(
            f"no risk assessment was made: {error.reason} - {error.message}",
            "no risk level, score, threshold or signal is reported, because nothing "
            "about the risk was established",
        ),
        uncertainty=Uncertainty(
            status="unavailable",
            value=None,
            unit=None,
            source=None,
            reason=(
                "no assessment was made, so there is no value and no spread to describe"
            ),
            is_prediction_interval=False,
            caveat=None,
        ),
        provenance=ProvenanceRecord(dataset_type=DATASET_TYPE_UNKNOWN),
        provenance_chain={
            "risk_contract_version": RISK_CONTRACT_VERSION,
            "serving_contract_version": SERVING_CONTRACT_VERSION,
            "risk_error": error.reason,
            "risk_configuration_version": (
                config.risk_configuration_version if config else None
            ),
        },
        gis_context=None,
        historical_context=None,
        context_digest=_digest([], length=12),
        synthetic_demo=False,
        data_status=DATASET_TYPE_UNKNOWN,
        disclaimer="",
        risk_configuration_version=(
            config.risk_configuration_version if config else RISK_CONFIGURATION_VERSION
        ),
        production_ready_claimed=False,
    )


def assess_risk_safe(
    served: ServedForecast | ForecastInference | None,
    *,
    config: RiskConfiguration,
    context: RiskContext | None = None,
    residuals: Sequence[float] | None = None,
    residual_sigma: float | None = None,
    assessed_at: dt.datetime | None = None,
) -> RiskResult:
    """`assess_risk`, with a contract violation reported instead of raised.

    For the caller that wants a result for every input — a batch loop, or a service
    endpoint that must answer rather than 500. The returned result has
    `status == RISK_STATUS_WITHHELD`, `evaluation_state == CONTEXT_NOT_EVALUABLE`,
    no level, no score, and an explanation naming the violation.

    It is deliberately *not* the default: a caller who swallows a `RiskBoundaryError`
    without logging it has thrown away the reason, and that is how an unavailable
    risk becomes an unnoticed one.
    """
    try:
        return assess_risk(
            served,
            config=config,
            context=context,
            residuals=residuals,
            residual_sigma=residual_sigma,
            assessed_at=assessed_at,
        )
    except RiskBoundaryError as error:
        return risk_from_error(error, config=config, served=served)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def risk_contract_description() -> dict[str, Any]:
    """The Phase 6 contract, as data."""
    from .risk_context import context_contract_description

    return {
        "risk_contract_version": RISK_CONTRACT_VERSION,
        "risk_configuration_version": RISK_CONFIGURATION_VERSION,
        "score_types": RISK_SCORE_TYPES,
        "risk_levels": SUPPORTED_RISK_LEVELS,
        "status_vocabulary": [RISK_STATUS_RECORDED, RISK_STATUS_WITHHELD],
        "residual_sigma_sources": [
            SIGMA_SOURCE_RESIDUALS,
            SIGMA_SOURCE_SUPPLIED,
            SIGMA_SOURCE_ABSENT,
        ],
        "rmse_is_not_residual_sigma": (
            "aggregate artifact metrics cannot supply a residual spread; rmse is the "
            "root-mean-square error about zero, not the standard deviation of residuals "
            "about their mean, and the two differ whenever the model is biased"
        ),
        "pipeline": [
            "resolve and validate the Phase 5 forecast",
            "settle the threshold units against the forecast's units",
            "validate the risk context against the forecast: entity, temporality, units, freshness",
            "resolve a measured residual spread, or withhold the level",
            "compute the exceedance probability and classify the band",
            "apply configured escalation rules (raise only)",
            "explain from the evaluated evidence",
            "carry provenance and the synthetic/demo status",
        ],
        "errors_are_raised_not_swallowed": (
            "contract violations raise a RiskBoundaryError; availability conditions "
            "return a withheld RiskResult. assess_risk_safe converts the former into the "
            "latter for callers that must answer rather than fail"
        ),
        "context": context_contract_description(),
    }


__all__ = [
    "COMPARISONS",
    "EscalationEvaluation",
    "InvalidRiskCalculationError",
    "InvalidRiskConfigurationError",
    "InvalidThresholdError",
    "InvalidUnitsError",
    "RISK_CONTRACT_VERSION",
    "RISK_CONFIGURATION_VERSION",
    "RISK_SCORE_TYPES",
    "RISK_SCORE_TYPE_EXCEEDANCE",
    "RiskConfiguration",
    "RiskEscalationRule",
    "RiskResult",
    "SIGMA_ABSENT_REASON",
    "SIGMA_SOURCE_ABSENT",
    "SIGMA_SOURCE_RESIDUALS",
    "SIGMA_SOURCE_SUPPLIED",
    "StaleContextRuleError",
    "THRESHOLD_UNCONFIGURED",
    "assess_risk",
    "assess_risk_safe",
    "context_digest",
    "default_risk_result_id",
    "risk_contract_description",
    "risk_from_error",
]