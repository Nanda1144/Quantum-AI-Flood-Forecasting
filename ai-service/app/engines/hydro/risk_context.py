# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 6 risk-context contract: the evidence a risk assessment is allowed to see.

The boundary this module draws
------------------------------
Phase 5 answers "what does the model predict?". This module answers "what else is
known, by whom, in which units, for which station, and as of when?" — and refuses
to answer when the answer is not available.

Everything here is a **contract, not a data source**. No signal value is created in
this module; `RiskSignal` only validates and carries what a caller supplies. That
separation is the whole point: a reader can tell "the repository has no elevation
data" apart from "a caller forgot to pass elevation data", because the first is
stated in `unavailable_gis_context()` with a reason and the second is a
`RiskSignal` the caller simply did not construct.

What already existed, and is reused rather than duplicated
----------------------------------------------------------
* `domains.Measurement` / `CANONICAL_QUANTITY` — the canonical quantity vocabulary.
* `domains.NOT_AVAILABLE` / `DomainSpec.availability_note` — the repository's own
  statement of which domains have no data at all.
* `domains.FloodEvent` — the historical flood-event schema.
* `preprocess_units` — unit recognition and dimensional compatibility. Phase 6
  never invents a unit table; it asks Phase 2's.
* `config.RiskPolicy` and `risk.RiskAssessment` — the threshold policy and the
  probability model, applied in `forecast_risk.py`.

Availability is explicit, and a missing signal is never zero
------------------------------------------------------------
`SIGNAL_AVAILABILITY` is the closed set every signal must declare: `valid`,
`missing`, `unavailable`, `not_applicable`, `stale`. The distinction matters and is
not pedantry:

* ``missing`` — the quantity is expected here, and no value was supplied.
* ``unavailable`` — the repository has no such data at all (see
  `unavailable_gis_context`).
* ``not_applicable`` — the quantity is meaningless for this entity or horizon.
* ``stale`` — a value exists but is older than the caller's stated tolerance.

None of them carries a number. `SignalEvaluation.value` is `None` for every one of
them, and the risk layer reads `usable`, not `value`. This is the rule that stops
"we have no rainfall record" from quietly becoming "rainfall = 0 mm", which would
make an un-instrumented catchment look like a dry one.

Temporal safety
---------------
`evaluate_context` enforces one rule: a signal's `observed_at` may not be after the
**forecast origin**. The origin, not the prediction instant, is the causality
boundary. A prediction for `t + 6h` is made at `t`; anything observed after `t`
could not have informed it, and letting it through would let the future decide the
risk. Signals are therefore refused, not clamped.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .domains import (
    CANONICAL_QUANTITY,
    NOT_AVAILABLE,
    FloodEvent,
)
from .preprocess_units import (
    DIM_LENGTH,
    DIM_LENGTH_PER_TIME,
    DIM_VOLUME_FLOW,
    dimension_of,
)

#: Version tag written into every risk-context payload this module produces.
CONTEXT_CONTRACT_VERSION = "navya-phase6-context/v1"

# --------------------------------------------------------------------------- #
# Availability vocabulary
# --------------------------------------------------------------------------- #

#: The signal carries a validated value, in a unit whose dimension suits its
#: quantity, read at or before the forecast origin.
SIGNAL_VALID = "valid"

#: The quantity is expected for this entity and no value was supplied. This is a
#: gap in the caller's evidence, and it is reported as a gap.
SIGNAL_MISSING = "missing"

#: The repository holds no such data at all. Distinct from `missing`: nothing was
#: expected to be passed and nothing should have been.
SIGNAL_UNAVAILABLE = "unavailable"

#: The quantity does not apply to this entity or horizon — a discharge reading for
#: a gauge that measures level only, say.
SIGNAL_NOT_APPLICABLE = "not_applicable"

#: A value exists but is older than the caller said this quantity may be used for.
SIGNAL_STALE = "stale"

#: The closed availability vocabulary. Order is not significant; membership is.
SIGNAL_AVAILABILITY: tuple[str, ...] = (
    SIGNAL_VALID,
    SIGNAL_MISSING,
    SIGNAL_UNAVAILABLE,
    SIGNAL_NOT_APPLICABLE,
    SIGNAL_STALE,
)

#: Availability states that mean "no usable number is present here".
SIGNAL_UNUSABLE: tuple[str, ...] = (
    SIGNAL_MISSING,
    SIGNAL_UNAVAILABLE,
    SIGNAL_NOT_APPLICABLE,
    SIGNAL_STALE,
)

# --------------------------------------------------------------------------- #
# Context evaluation states
# --------------------------------------------------------------------------- #

#: Every declared signal was evaluated and carried a valid value.
CONTEXT_FULLY_EVALUATED = "fully_evaluated"

#: The risk was assessed, but some declared signals could not be evaluated. The
#: result says exactly which, so a partial assessment is never read as a complete
#: one.
CONTEXT_PARTIALLY_EVALUATED = "partially_evaluated"

#: No signal could be evaluated at all. Note that a risk level can still be
#: assigned here: the exceedance probability comes from the forecast, not from the
#: context. What is missing is corroboration, and the result says so.
CONTEXT_UNAVAILABLE = "context_unavailable"

#: The risk could not be computed at all — no threshold policy, no forecast, or a
#: contract violation. Nothing about the level is implied.
CONTEXT_NOT_EVALUABLE = "not_evaluable"

#: The closed evaluation-state vocabulary.
CONTEXT_EVALUATION_STATES: tuple[str, ...] = (
    CONTEXT_FULLY_EVALUATED,
    CONTEXT_PARTIALLY_EVALUATED,
    CONTEXT_UNAVAILABLE,
    CONTEXT_NOT_EVALUABLE,
)

# --------------------------------------------------------------------------- #
# Quantity vocabulary
# --------------------------------------------------------------------------- #

RISK_QUANTITY_WATER_LEVEL = "water_level"
RISK_QUANTITY_RAINFALL = "rainfall"
RISK_QUANTITY_INFLOW = "inflow"
RISK_QUANTITY_DISCHARGE = "discharge"

#: A change in level over a stated window. The trend signal. Separate from
#: `water_level` because the two are compared against different thresholds and
#: conflating them would let a level rule fire on a delta.
RISK_QUANTITY_WATER_LEVEL_CHANGE = "water_level_change"

RISK_QUANTITY_ELEVATION = "elevation"
RISK_QUANTITY_RIVER_DISTANCE = "river_distance"

#: Quantities Phase 6 accepts, split by where they come from. The first group is
#: `domains.CANONICAL_QUANTITY` — the repository's own observation vocabulary, not
#: a list invented here. The rest are either a derived trend or a spatial attribute
#: that only a GIS provider can supply.
CANONICAL_SIGNAL_QUANTITIES: tuple[str, ...] = tuple(CANONICAL_QUANTITY)
DERIVED_SIGNAL_QUANTITIES: tuple[str, ...] = (RISK_QUANTITY_WATER_LEVEL_CHANGE,)
SPATIAL_SIGNAL_QUANTITIES: tuple[str, ...] = (
    RISK_QUANTITY_ELEVATION,
    RISK_QUANTITY_RIVER_DISTANCE,
)
RISK_QUANTITIES: tuple[str, ...] = (
    CANONICAL_SIGNAL_QUANTITIES + DERIVED_SIGNAL_QUANTITIES + SPATIAL_SIGNAL_QUANTITIES
)

#: Which physical dimension each quantity may legitimately be measured in.
#:
#: An empty tuple means "no restriction, and therefore no conversion": the unit is
#: recorded and left alone. `inflow` is the live example — `domains` records its unit
#: as UNDETERMINED, so constraining it here would invent a unit nobody supplied.
QUANTITY_DIMENSIONS: Mapping[str, tuple[str, ...]] = {
    RISK_QUANTITY_WATER_LEVEL: (DIM_LENGTH,),
    RISK_QUANTITY_WATER_LEVEL_CHANGE: (DIM_LENGTH,),
    RISK_QUANTITY_ELEVATION: (DIM_LENGTH,),
    RISK_QUANTITY_RIVER_DISTANCE: (DIM_LENGTH,),
    # An accumulation is a depth; an intensity is a depth per time. Both are real
    # rainfall signals and they are not interchangeable, so both are allowed and the
    # dimension is recorded so a rule can insist on the one it meant.
    RISK_QUANTITY_RAINFALL: (DIM_LENGTH, DIM_LENGTH_PER_TIME),
    RISK_QUANTITY_DISCHARGE: (DIM_VOLUME_FLOW,),
    RISK_QUANTITY_INFLOW: (),
}

#: Where the spatial quantities live. A signal with one of these quantities is
#: spatial evidence, and a GIS provider is the only honest source for it.
SPATIAL_QUANTITIES: frozenset[str] = frozenset(SPATIAL_SIGNAL_QUANTITIES)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class RiskBoundaryError(ValueError):
    """Base for every Phase 6 refusal.

    A `ValueError` so that a caller who does not know about Phase 6 still catches
    it with the handler they would use for any other bad input.
    """

    #: Stable, machine-readable tag. Set on each subclass; the risk layer quotes it
    #: in its explanation so a withheld result still names *why* in a way a log
    #: consumer can match on.
    reason = "risk_boundary_violation"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def describe(self) -> str:
        return f"{type(self).__name__}: {self.message}"


class MissingForecastError(RiskBoundaryError):
    """No Phase 5 forecast result was supplied."""

    reason = "missing_forecast"


class InvalidForecastError(RiskBoundaryError):
    """The supplied object is not a Phase 5 result, or carries no forecast.

    Raised for a `ServedForecast` whose `status` is not `ready`, for a missing or
    absent `inference`, and for an object of the wrong type. One error covers all
    three because a caller has one thing to fix: give me a forecast that carries a
    value.
    """

    reason = "invalid_forecast"


class MissingRiskContextError(RiskBoundaryError):
    """A risk context is required and none was supplied."""

    reason = "missing_risk_context"


class InvalidUnitsError(RiskBoundaryError):
    """A unit is unusable, or is dimensionally incompatible with its quantity."""

    reason = "invalid_units"


class InvalidThresholdError(RiskBoundaryError):
    """The threshold in force cannot be used to assess anything."""

    reason = "invalid_threshold"


class EntityMismatchError(RiskBoundaryError):
    """Context, a signal, or a historical event belongs to a different station."""

    reason = "entity_mismatch"


class FutureContextError(RiskBoundaryError):
    """Evidence is timestamped after the forecast origin."""

    reason = "future_context"


class StaleContextError(RiskBoundaryError):
    """A signal a configuration declared *required* is too old to use."""

    reason = "stale_context"


class UnsupportedContextError(RiskBoundaryError):
    """A quantity, unit or context shape this module cannot interpret."""

    reason = "unsupported_context"


class InvalidRiskConfigurationError(RiskBoundaryError):
    """The risk configuration is internally inconsistent."""

    reason = "invalid_risk_configuration"


class GisContextUnavailableError(RiskBoundaryError):
    """Spatial context was required by the configuration and is not available."""

    reason = "gis_context_unavailable"


class InvalidRiskCalculationError(RiskBoundaryError):
    """The probability or band arithmetic refused to produce a value."""

    reason = "invalid_risk_calculation"


# --------------------------------------------------------------------------- #
# Small validators
# --------------------------------------------------------------------------- #


def _check_text(value: Any, field_name: str, error: type[RiskBoundaryError]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error(f"{field_name} is required and must be a non-empty string, got {value!r}")
    return value


def _check_instant(value: Any, field_name: str, error: type[RiskBoundaryError]) -> dt.datetime:
    """Require a timezone-aware instant.

    A naive datetime is refused rather than assumed UTC. Assuming is how a
    +05:30 gauge reading silently becomes nine hours in the future or past, and the
    resulting error looks like a data problem rather than a configuration one.
    """
    if not isinstance(value, dt.datetime):
        raise error(f"{field_name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise error(
            f"{field_name} must be timezone-aware; a naive datetime cannot be compared "
            f"with another instant without guessing an offset, got {value!r}"
        )
    return value


def _check_aware(value: Any) -> bool:
    return isinstance(value, dt.datetime) and value.tzinfo is not None and value.utcoffset() is not None


# --------------------------------------------------------------------------- #
# RiskSignal
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RiskSignal:
    """One piece of risk evidence, with everything needed to judge it.

    A signal is a *claim about evidence*, not evidence. Constructing one asserts
    nothing: `available_signal` below is the only convenience constructor, and it
    validates; a caller who wants an unavailable signal says so explicitly.

    `entity=None` means "the entity of the enclosing `RiskContext`". It does not
    mean "any entity" — a signal whose entity is genuinely different is refused by
    `RiskContext.__post_init__` rather than silently re-attributed.
    """

    name: str
    quantity: str
    value: float | None
    unit: str | None
    source: str
    availability: str = SIGNAL_VALID
    entity: str | None = None
    observed_at: dt.datetime | None = None
    note: str = ""

    def __post_init__(self) -> None:
        _check_text(self.name, "RiskSignal.name", UnsupportedContextError)
        _check_text(self.source, "RiskSignal.source", UnsupportedContextError)

        if self.availability not in SIGNAL_AVAILABILITY:
            raise UnsupportedContextError(
                f"signal {self.name!r} declares availability {self.availability!r}; "
                f"declared states are {SIGNAL_AVAILABILITY}"
            )

        if self.quantity not in RISK_QUANTITIES:
            raise UnsupportedContextError(
                f"signal {self.name!r} declares quantity {self.quantity!r}; Phase 6 "
                f"accepts {RISK_QUANTITIES}"
            )

        if self.availability == SIGNAL_VALID:
            if self.value is None:
                raise UnsupportedContextError(
                    f"signal {self.name!r} is declared {SIGNAL_VALID} but carries no value; "
                    f"a valid signal with no number is a missing signal wearing the wrong label"
                )
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise UnsupportedContextError(
                    f"signal {self.name!r} value must be a real number, got "
                    f"{type(self.value).__name__}"
                )
            if not math.isfinite(float(self.value)):
                raise UnsupportedContextError(
                    f"signal {self.name!r} value must be finite, got {self.value!r}"
                )
            _check_text(self.unit, f"signal {self.name!r} unit", InvalidUnitsError)
            if self.observed_at is None:
                raise UnsupportedContextError(
                    f"signal {self.name!r} is declared {SIGNAL_VALID} but carries no "
                    f"observed_at; evidence without an instant cannot be checked for leakage"
                )
            _check_instant(self.observed_at, f"signal {self.name!r} observed_at", FutureContextError)
        else:
            # An unusable signal may still carry a number — a stale reading is a
            # number nobody may use — but it must not present as authoritative.
            # Keeping the value is deliberate: the explanation can then say "held
            # 8.0 m but too old to use", which is more useful than hiding it.
            if self.unit is not None and not isinstance(self.unit, str):
                raise InvalidUnitsError(
                    f"signal {self.name!r} unit must be a string or None, got "
                    f"{type(self.unit).__name__}"
                )

    @property
    def has_value(self) -> bool:
        """True when a number is present, whatever its availability says."""
        return self.value is not None

    @property
    def is_valid(self) -> bool:
        return self.availability == SIGNAL_VALID

    @property
    def is_spatial(self) -> bool:
        """True when only a GIS provider can honestly supply this quantity."""
        return self.quantity in SPATIAL_QUANTITIES

    @property
    def allowed_dimensions(self) -> tuple[str, ...]:
        return QUANTITY_DIMENSIONS.get(self.quantity, ())

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "quantity": self.quantity,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "availability": self.availability,
            "entity": self.entity,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "dimension": self.dimension,
            "spatial": self.is_spatial,
            "note": self.note,
        }

    @property
    def dimension(self) -> str | None:
        """The physical dimension of this signal's unit, or `None` if undetermined."""
        if not self.unit:
            return None
        return dimension_of(self.unit)


def available_signal(
    name: str,
    quantity: str,
    value: float,
    unit: str,
    *,
    source: str,
    observed_at: dt.datetime,
    entity: str | None = None,
    note: str = "",
) -> RiskSignal:
    """A validated signal carrying a real value read at a real instant.

    Every parameter is required. In particular `source` and `observed_at` have no
    defaults, because a risk explanation that cannot say where a number came from
    or when it was read is not an explanation.
    """
    return RiskSignal(
        name=name,
        quantity=quantity,
        value=float(value),
        unit=unit,
        source=source,
        availability=SIGNAL_VALID,
        entity=entity,
        observed_at=observed_at,
        note=note,
    )


def unavailable_signal(
    name: str,
    quantity: str,
    *,
    source: str,
    availability: str,
    reason: str,
    entity: str | None = None,
    note: str = "",
) -> RiskSignal:
    """A signal that is declared absent, with the reason it is absent.

    `reason` is mandatory. A gap in the evidence that cannot say what kind of gap it
    is forces the reader to guess, and a guessed gap is the mechanism by which "no
    elevation data" becomes "elevation is fine".
    """
    if availability not in SIGNAL_UNUSABLE:
        raise UnsupportedContextError(
            f"unavailable_signal cannot declare availability {availability!r}; it builds "
            f"one of {SIGNAL_UNUSABLE}"
        )
    _check_text(reason, "unavailable_signal reason", UnsupportedContextError)
    return RiskSignal(
        name=name,
        quantity=quantity,
        value=None,
        unit=None,
        source=source,
        availability=availability,
        entity=entity,
        observed_at=None,
        note=note or reason,
    )


# --------------------------------------------------------------------------- #
# GIS boundary
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GisContext:
    """Spatial evidence for one station, as a GIS provider would supply it.

    **This is an interface, not an implementation.** No GIS engine is written here,
    and none is imported. The team's GIS work is untouched; this class is where its
    output will arrive.

    `available=False` is the honest state of spatial context in this repository, and
    it is what `unavailable_gis_context()` builds. Every measurement field is
    `None` in that state — not `0.0`, not `-1`, not a plausible-looking elevation for
    a river that is nearly flat everywhere. A fabricated elevation is worse than a
    missing one, because it survives every subsequent check.

    Population and infrastructure counts are carried but are deliberately **not**
    exposed as `RiskSignal`s. They are not comparable against a threshold, so
    treating them as signals would invite a rule that fires on them, and any such
    rule would be asserting a hazard relationship nobody in this repository has
    evidence for.
    """

    available: bool
    provider: str
    elevation_m: float | None = None
    river_distance_m: float | None = None
    population_exposed: int | None = None
    infrastructure_exposed: int | None = None
    provenance: Mapping[str, Any] | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        _check_text(self.provider, "GisContext.provider", UnsupportedContextError)
        if not self.available and not self.reason.strip():
            raise UnsupportedContextError(
                "an unavailable GisContext must carry a reason; 'no data' and 'we did "
                "not look' are different facts and the result has to be able to say which"
            )
        if self.available and not any(
            value is not None
            for value in (
                self.elevation_m,
                self.river_distance_m,
                self.population_exposed,
                self.infrastructure_exposed,
            )
        ):
            raise UnsupportedContextError(
                "a GisContext declared available must carry at least one measurement, or "
                "it is an unavailable context with the wrong label"
            )
        for name in ("elevation_m", "river_distance_m"):
            value = getattr(self, name)
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise InvalidUnitsError(
                        f"GisContext.{name} must be a real number or None, got "
                        f"{type(value).__name__}"
                    )
                if not math.isfinite(float(value)):
                    raise InvalidUnitsError(
                        f"GisContext.{name} must be finite, got {value!r}"
                    )
        for name in ("population_exposed", "infrastructure_exposed"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise UnsupportedContextError(
                    f"GisContext.{name} must be an integer count or None; a fractional "
                    f"or estimated population is not a count, got {value!r}"
                )

    @property
    def provenance_reference(self) -> str | None:
        """The provider's own reference for this context, if it recorded one."""
        if not self.provenance:
            return None
        for key in ("reference", "context_reference", "source_reference", "provider_reference"):
            value = self.provenance.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return self.provider

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "provider": self.provider,
            "elevation_m": self.elevation_m,
            "river_distance_m": self.river_distance_m,
            "population_exposed": self.population_exposed,
            "infrastructure_exposed": self.infrastructure_exposed,
            "provenance": dict(self.provenance) if self.provenance else None,
            "provenance_reference": self.provenance_reference,
            "reason": self.reason,
        }


def unavailable_gis_context(
    provider: str = "none",
    *,
    reason: str = NOT_AVAILABLE,
    provenance: Mapping[str, Any] | None = None,
) -> GisContext:
    """Spatial context that does not exist here, stated as such.

    The default reason is `domains.NOT_AVAILABLE`, which is the repository's own
    sentence for this — the one the `DomainSpec`s already use. Reusing it means a
    reader who greps for that string finds the feature catalogue, the domain specs
    and the risk boundary agreeing with each other.
    """
    return GisContext(
        available=False,
        provider=provider,
        provenance=provenance,
        reason=reason,
    )


# --------------------------------------------------------------------------- #
# Historical context boundary
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HistoricalContext:
    """Recorded flood events for one station, as `domains.FloodEvent` records.

    **Interface only.** `domains` states that no flood event register exists in this
    repository and that none may be invented, so `unavailable_historical_context()`
    is the only value this repository can honestly construct.

    Events are reused rather than redefined: `FloodEvent` is Phase 1's schema, with
    its own `dataset_type`, `disclaimer` and `provenance_reference`. A historical
    context built from synthetic events therefore carries the synthetic disclaimer
    automatically, with nothing for Phase 6 to remember to do.
    """

    available: bool
    provider: str
    events: tuple[FloodEvent, ...] = ()
    provenance: Mapping[str, Any] | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        _check_text(self.provider, "HistoricalContext.provider", UnsupportedContextError)
        if not isinstance(self.events, tuple):
            object.__setattr__(self, "events", tuple(self.events))
        for event in self.events:
            if not isinstance(event, FloodEvent):
                raise UnsupportedContextError(
                    f"HistoricalContext.events holds a {type(event).__name__}; Phase 6 "
                    f"reuses domains.FloodEvent rather than a parallel event schema"
                )
        if not self.available and not self.reason.strip():
            raise UnsupportedContextError(
                "an unavailable HistoricalContext must carry a reason"
            )
        if self.available and not self.events:
            raise UnsupportedContextError(
                "a HistoricalContext declared available must carry at least one event, or "
                "it is an unavailable context with the wrong label"
            )

    @property
    def provenance_reference(self) -> str | None:
        if not self.provenance:
            return None
        for key in ("reference", "context_reference", "source_reference", "register_reference"):
            value = self.provenance.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return self.provider

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "provider": self.provider,
            "event_count": len(self.events),
            "events": [event.to_dict() for event in self.events],
            "provenance": dict(self.provenance) if self.provenance else None,
            "provenance_reference": self.provenance_reference,
            "reason": self.reason,
        }


def unavailable_historical_context(
    provider: str = "none",
    *,
    reason: str = "no flood event register exists in this repository, and none may be invented",
    provenance: Mapping[str, Any] | None = None,
) -> HistoricalContext:
    """Historical flood context that does not exist here, stated as such.

    The default reason is `domains`' own wording for `DOMAIN_FLOOD_EVENT`, so the
    schema module and the risk boundary cannot drift apart on what is missing.
    """
    return HistoricalContext(
        available=False,
        provider=provider,
        provenance=provenance,
        reason=reason,
    )


# --------------------------------------------------------------------------- #
# RiskContext
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RiskContext:
    """Every piece of evidence one risk assessment is allowed to consider.

    `signals` is flat and ordered by name after validation, because the risk layer
    reads it repeatedly and a stable order is what makes two assessments of the
    same evidence comparable. `gis` and `historical` are kept as named providers so
    a result can report *that spatial evidence was wanted and absent*, which is
    different information from "no signal by that name was passed".

    A `RiskContext` is not validated against a forecast. Entity agreement and
    temporal validity are cross-contract properties — they involve the forecast's
    origin and entity — so they are checked in `evaluate_context`, where both sides
    are in hand. Checking them here would mean either guessing the forecast or
    duplicating the check.
    """

    entity: str
    signals: tuple[RiskSignal, ...] = ()
    gis: GisContext | None = None
    historical: HistoricalContext | None = None
    dataset_type: str = "unknown"
    dataset_reference: str | None = None
    disclaimer: str | None = None
    context_version: str = CONTEXT_CONTRACT_VERSION
    notes: str = ""

    def __post_init__(self) -> None:
        _check_text(self.entity, "RiskContext.entity", EntityMismatchError)

        if not isinstance(self.signals, tuple):
            object.__setattr__(self, "signals", tuple(self.signals))
        for signal in self.signals:
            if not isinstance(signal, RiskSignal):
                raise UnsupportedContextError(
                    f"RiskContext.signals holds a {type(signal).__name__}; construct "
                    f"signals with available_signal() or unavailable_signal()"
                )

        names = [signal.name for signal in self.signals]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise UnsupportedContextError(
                f"RiskContext carries duplicate signal names {duplicates}; two readings "
                f"of one quantity with no stated precedence is not a context, it is a "
                f"coin toss"
            )

        for signal in self.signals:
            if signal.entity is not None and signal.entity != self.entity:
                raise EntityMismatchError(
                    f"signal {signal.name!r} belongs to {signal.entity!r} but the context "
                    f"describes {self.entity!r}; combining them would attribute one "
                    f"station's reading to another"
                )

        # Sorted by name so the evaluation order — and therefore the explanation
        # order — does not depend on how the caller happened to build the tuple.
        object.__setattr__(self, "signals", tuple(sorted(self.signals, key=lambda s: s.name)))

    # --- lookup ------------------------------------------------------------

    def signal(self, name: str) -> RiskSignal | None:
        for signal in self.signals:
            if signal.name == name:
                return signal
        return None

    def names(self) -> tuple[str, ...]:
        return tuple(signal.name for signal in self.signals)

    def valid_signals(self) -> tuple[RiskSignal, ...]:
        return tuple(signal for signal in self.signals if signal.is_valid)

    def usable_by_quantity(self, quantity: str) -> tuple[RiskSignal, ...]:
        return tuple(
            signal for signal in self.signals if signal.quantity == quantity and signal.is_valid
        )

    def synthetic(self) -> bool:
        """True when this context declares itself synthetic.

        The context's own `dataset_type` decides, and the forecast's decides
        separately. They are not reconciled here because a context assembled from a
        real rainfall record alongside a synthetic forecast is a combination the
        caller must see rather than one this module should quietly resolve.
        """
        return self.dataset_type == "synthetic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_version": self.context_version,
            "entity": self.entity,
            "dataset_type": self.dataset_type,
            "dataset_reference": self.dataset_reference,
            "disclaimer": self.disclaimer,
            "signal_count": len(self.signals),
            "signals": [signal.to_dict() for signal in self.signals],
            "gis": self.gis.to_dict() if self.gis else None,
            "historical": self.historical.to_dict() if self.historical else None,
            "notes": self.notes,
        }


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SignalEvaluation:
    """One signal after validation against the forecast.

    `value` is `None` for every unusable availability, and `usable` is the field to
    branch on. The reason is kept verbatim because the risk explanation quotes it
    rather than paraphrasing it — a paraphrase is where "missing" quietly becomes
    "looked at, nothing found".
    """

    name: str
    quantity: str
    availability: str
    usable: bool
    value: float | None
    unit: str | None
    dimension: str | None
    source: str
    entity: str
    observed_at: dt.datetime | None
    reason: str
    note: str = ""

    @property
    def spatial(self) -> bool:
        return self.quantity in SPATIAL_QUANTITIES

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "quantity": self.quantity,
            "availability": self.availability,
            "usable": self.usable,
            "value": self.value,
            "unit": self.unit,
            "dimension": self.dimension,
            "source": self.source,
            "entity": self.entity,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "reason": self.reason,
            "note": self.note,
            "spatial": self.spatial,
        }


def _check_dimension(signal: RiskSignal) -> str | None:
    """Confirm the signal's unit is one this quantity may legitimately use.

    Returns the dimension. Raises when the unit is unrecognised, or when it is
    recognised but means the wrong kind of quantity — a `mm/h` rainfall intensity
    checked against a millimetre threshold is the case that matters, and Phase 2's
    own unit module already refuses to convert between them.
    """
    unit = signal.unit
    if not isinstance(unit, str) or not unit.strip():
        raise InvalidUnitsError(f"signal {signal.name!r} declares {SIGNAL_VALID} without a unit")
    found = dimension_of(unit)
    if found is None:
        raise InvalidUnitsError(
            f"signal {signal.name!r} declares unit {unit!r}, which is not a unit this "
            f"repository recognises; an unrecognised unit is left undetermined rather "
            f"than guessed at"
        )
    allowed = signal.allowed_dimensions
    if allowed and found not in allowed:
        raise InvalidUnitsError(
            f"signal {signal.name!r} is a {signal.quantity} measured in {unit!r}, whose "
            f"dimension is {found!r}; {signal.quantity} may be measured in "
            f"{list(allowed)}. A depth and a depth-per-time are not the same quantity and "
            f"will not be silently reconciled."
        )
    return found


def evaluate_context(
    context: RiskContext,
    *,
    forecast_entity: str,
    forecast_origin: dt.datetime,
    assessed_at: dt.datetime | None = None,
    max_age_seconds: Mapping[str, float] | None = None,
    default_max_age_seconds: float | None = None,
) -> tuple[SignalEvaluation, ...]:
    """Validate every signal against one forecast, returning the evaluated set.

    The four checks, in the order they run — order matters, because the first
    failure is the most fundamental one and a reader wants that one:

    1. **Entity.** The context and every signal must describe `forecast_entity`.
    2. **Temporal.** A signal read after `forecast_origin` is refused outright. This
       is a refusal rather than a downgrade because the evidence could not have
       existed when the forecast was made, and a risk layer that quietly ignored it
       would be indistinguishable from one that used it.
    3. **Units.** The unit must be recognised and dimensionally right for the
       quantity.
    4. **Freshness.** Older than the caller's stated tolerance becomes `stale`, and
       `usable` is `False`. Staleness is a *state*, not a refusal: the reading is
       real, it is just too old to act on, and the result says so.

    `assessed_at` defaults to `forecast_origin`. That is deliberate: the risk
    assessment is made at the instant the forecast was made, so the default is the
    only honest choice, and it keeps the result free of a clock reading.
    `max_age_seconds` is keyed by signal name with `default_max_age_seconds` as the
    fallback; when neither is supplied no signal goes stale, because this module
    will not invent an age limit nobody configured.

    Raises `EntityMismatchError`, `FutureContextError`, `InvalidUnitsError` or
    `MissingRiskContextError`. Returns evaluations ordered by signal name.
    """
    if not isinstance(context, RiskContext):
        raise MissingRiskContextError(
            f"a RiskContext is required, got {type(context).__name__}"
        )
    _check_text(forecast_entity, "forecast_entity", EntityMismatchError)
    _check_instant(forecast_origin, "forecast_origin", FutureContextError)

    if assessed_at is None:
        assessed_at = forecast_origin
    else:
        _check_instant(assessed_at, "assessed_at", FutureContextError)
        if assessed_at < forecast_origin:
            raise FutureContextError(
                f"assessed_at {assessed_at.isoformat()} precedes the forecast origin "
                f"{forecast_origin.isoformat()}; a risk assessment cannot be dated before "
                f"the forecast it assesses"
            )

    if context.entity != forecast_entity:
        raise EntityMismatchError(
            f"risk context describes {context.entity!r} but the forecast is for "
            f"{forecast_entity!r}; combining them would transfer one station's evidence "
            f"to another"
        )

    ages = dict(max_age_seconds or {})
    if default_max_age_seconds is not None:
        _check_age(default_max_age_seconds, "default_max_age_seconds")
    for name, limit in ages.items():
        _check_age(limit, f"max_age_seconds[{name!r}]")

    evaluations: list[SignalEvaluation] = []
    for signal in context.signals:
        entity = signal.entity or context.entity

        if signal.availability != SIGNAL_VALID:
            evaluations.append(
                SignalEvaluation(
                    name=signal.name,
                    quantity=signal.quantity,
                    availability=signal.availability,
                    usable=False,
                    value=None,
                    unit=signal.unit,
                    dimension=signal.dimension,
                    source=signal.source,
                    entity=entity,
                    observed_at=signal.observed_at,
                    reason=signal.note or f"signal declared {signal.availability}",
                    note=signal.note,
                )
            )
            continue

        if entity != forecast_entity:
            raise EntityMismatchError(
                f"signal {signal.name!r} resolves to {entity!r} but the forecast is for "
                f"{forecast_entity!r}"
            )

        observed_at = signal.observed_at
        assert observed_at is not None  # guaranteed by RiskSignal.__post_init__
        if observed_at > forecast_origin:
            raise FutureContextError(
                f"signal {signal.name!r} was observed at {observed_at.isoformat()}, after "
                f"the forecast origin {forecast_origin.isoformat()}; evidence that did not "
                f"exist when the forecast was made cannot inform its risk"
            )
        if observed_at > assessed_at:
            raise FutureContextError(
                f"signal {signal.name!r} was observed at {observed_at.isoformat()}, after "
                f"the assessment instant {assessed_at.isoformat()}"
            )

        dimension = _check_dimension(signal)

        limit = ages.get(signal.name, default_max_age_seconds)
        age_seconds = (assessed_at - observed_at).total_seconds()
        if limit is not None and age_seconds > limit:
            evaluations.append(
                SignalEvaluation(
                    name=signal.name,
                    quantity=signal.quantity,
                    availability=SIGNAL_STALE,
                    usable=False,
                    value=None,
                    unit=signal.unit,
                    dimension=dimension,
                    source=signal.source,
                    entity=entity,
                    observed_at=observed_at,
                    reason=(
                        f"read {age_seconds:.0f}s before the assessment instant, beyond the "
                        f"configured {limit:.0f}s limit for {signal.name!r}"
                    ),
                    note=signal.note,
                )
            )
            continue

        evaluations.append(
            SignalEvaluation(
                name=signal.name,
                quantity=signal.quantity,
                availability=SIGNAL_VALID,
                usable=True,
                value=float(signal.value),
                unit=signal.unit,
                dimension=dimension,
                source=signal.source,
                entity=entity,
                observed_at=observed_at,
                reason=f"valid {signal.quantity} in {signal.unit} read at {observed_at.isoformat()}",
                note=signal.note,
            )
        )

    _check_historical(context, forecast_entity=forecast_entity, forecast_origin=forecast_origin)
    return tuple(evaluations)


def _check_age(limit: float, label: str) -> float:
    if isinstance(limit, bool) or not isinstance(limit, (int, float)):
        raise InvalidRiskConfigurationError(
            f"{label} must be a number of seconds or None, got {type(limit).__name__}"
        )
    value = float(limit)
    if not math.isfinite(value) or value <= 0:
        raise InvalidRiskConfigurationError(
            f"{label} must be a positive finite number of seconds or None, got {limit!r}"
        )
    return value


def _check_historical(
    context: RiskContext,
    *,
    forecast_entity: str,
    forecast_origin: dt.datetime,
) -> None:
    """Apply the same entity and temporal rules to historical events.

    An event that has not finished by the origin is still possible to know about,
    so `ended_at` in the future is refused only when it *starts* in the future. An
    event that began before the origin and ends after it is legitimate knowledge
    only if it has actually been recorded, which `FloodEvent.status` is for; Phase 6
    does not second-guess the record, it only refuses to accept events from the
    future or another station.
    """
    historical = context.historical
    if historical is None or not historical.events:
        return
    for event in historical.events:
        if event.area_reference != forecast_entity:
            raise EntityMismatchError(
                f"historical event {event.event_reference!r} belongs to "
                f"{event.area_reference!r} but the forecast is for {forecast_entity!r}"
            )
        started = _parse_event_instant(event.started_at, event.event_reference, "started_at")
        if started > forecast_origin:
            raise FutureContextError(
                f"historical event {event.event_reference!r} begins at "
                f"{started.isoformat()}, after the forecast origin "
                f"{forecast_origin.isoformat()}"
            )
        if event.ended_at:
            ended = _parse_event_instant(event.ended_at, event.event_reference, "ended_at")
            if ended < started:
                raise UnsupportedContextError(
                    f"historical event {event.event_reference!r} ends before it starts "
                    f"({ended.isoformat()} < {started.isoformat()})"
                )


def _parse_event_instant(value: Any, reference: str, label: str) -> dt.datetime:
    """Read a `FloodEvent` timestamp, refusing anything unparseable or naive.

    `FloodEvent` stores instants as strings, so this is where a naive or malformed
    timestamp becomes an error. Assuming UTC here would be the same mistake as
    assuming it in `RiskSignal`, and in this domain the consequence is a flood event
    placed on the wrong side of the forecast origin.
    """
    if isinstance(value, dt.datetime):
        return _check_instant(value, f"event {reference!r} {label}", FutureContextError)
    if not isinstance(value, str) or not value.strip():
        raise UnsupportedContextError(
            f"historical event {reference!r} has no usable {label}, got {value!r}"
        )
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise UnsupportedContextError(
            f"historical event {reference!r} has an unreadable {label} {value!r}: {exc}"
        ) from exc
    return _check_instant(parsed, f"event {reference!r} {label}", FutureContextError)


# --------------------------------------------------------------------------- #
# Reporting helpers
# --------------------------------------------------------------------------- #


def availability_counts(evaluations: Sequence[SignalEvaluation]) -> dict[str, int]:
    """How many signals landed in each availability state, including the zeros.

    Every state in `SIGNAL_AVAILABILITY` is present in the result even when its
    count is zero. A count map that omits `stale` cannot distinguish "no signal went
    stale" from "staleness was never considered", and those are different states of
    the world.
    """
    counts = {state: 0 for state in SIGNAL_AVAILABILITY}
    for evaluation in evaluations:
        counts[evaluation.availability] = counts.get(evaluation.availability, 0) + 1
    return counts


def evaluation_state(evaluations: Sequence[SignalEvaluation]) -> str:
    """Classify how completely the context was evaluated.

    * no signals at all, or none usable → `context_unavailable`
    * every signal usable → `fully_evaluated`
    * otherwise → `partially_evaluated`

    `not_evaluable` is not produced here. It is a verdict on the *risk*, not on the
    context, and it belongs to the assessment in `forecast_risk.py`: a context can
    be fully evaluated while no risk level can be assigned because no threshold is
    configured. Folding that into the context state would say the evidence was
    ignored when it was read perfectly.
    """
    if not evaluations:
        return CONTEXT_UNAVAILABLE
    usable = sum(1 for evaluation in evaluations if evaluation.usable)
    if usable == 0:
        return CONTEXT_UNAVAILABLE
    if usable == len(evaluations):
        return CONTEXT_FULLY_EVALUATED
    return CONTEXT_PARTIALLY_EVALUATED


def unusable_signals(evaluations: Sequence[SignalEvaluation]) -> tuple[SignalEvaluation, ...]:
    """The signals that carried no usable value, in name order."""
    return tuple(evaluation for evaluation in evaluations if not evaluation.usable)


def context_contract_description() -> dict[str, Any]:
    """The contract, as data. Useful in a report and cheap to assert on in a test."""
    return {
        "context_version": CONTEXT_CONTRACT_VERSION,
        "signal_availability": SIGNAL_AVAILABILITY,
        "unusable_availability": SIGNAL_UNUSABLE,
        "evaluation_states": CONTEXT_EVALUATION_STATES,
        "quantities": RISK_QUANTITIES,
        "canonical_quantities": CANONICAL_SIGNAL_QUANTITIES,
        "derived_quantities": DERIVED_SIGNAL_QUANTITIES,
        "spatial_quantities": SPATIAL_SIGNAL_QUANTITIES,
        "quantity_dimensions": {
            quantity: list(dimensions)
            for quantity, dimensions in sorted(QUANTITY_DIMENSIONS.items())
        },
        "validation_order": [
            "entity agreement between context, signals and forecast",
            "temporal: no signal observed after the forecast origin",
            "units: recognised and dimensionally correct for the quantity",
            "freshness: older than the configured limit becomes stale",
            "historical events: same station, not from the future",
        ],
        "historical_context": "interface only; domains.FloodEvent schema, no register exists",
        "gis_context": "interface only; no spatial data exists in this repository",
        "missing_is_not_zero": (
            "an unusable signal carries no value; the risk layer reads `usable`, never "
            "`value`, so an absent reading can never be read as a zero reading"
        ),
        "errors": [
            "MissingForecastError",
            "InvalidForecastError",
            "MissingRiskContextError",
            "InvalidUnitsError",
            "InvalidThresholdError",
            "EntityMismatchError",
            "FutureContextError",
            "StaleContextError",
            "UnsupportedContextError",
            "InvalidRiskConfigurationError",
            "GisContextUnavailableError",
            "InvalidRiskCalculationError",
        ],
    }


__all__ = [
    "CANONICAL_SIGNAL_QUANTITIES",
    "CONTEXT_CONTRACT_VERSION",
    "CONTEXT_EVALUATION_STATES",
    "CONTEXT_FULLY_EVALUATED",
    "CONTEXT_NOT_EVALUABLE",
    "CONTEXT_PARTIALLY_EVALUATED",
    "CONTEXT_UNAVAILABLE",
    "DERIVED_SIGNAL_QUANTITIES",
    "EntityMismatchError",
    "FutureContextError",
    "GisContext",
    "GisContextUnavailableError",
    "HistoricalContext",
    "InvalidRiskCalculationError",
    "InvalidRiskConfigurationError",
    "InvalidThresholdError",
    "InvalidUnitsError",
    "MissingForecastError",
    "MissingRiskContextError",
    "InvalidForecastError",
    "QUANTITY_DIMENSIONS",
    "RISK_QUANTITIES",
    "RISK_QUANTITY_DISCHARGE",
    "RISK_QUANTITY_ELEVATION",
    "RISK_QUANTITY_INFLOW",
    "RISK_QUANTITY_RAINFALL",
    "RISK_QUANTITY_RIVER_DISTANCE",
    "RISK_QUANTITY_WATER_LEVEL",
    "RISK_QUANTITY_WATER_LEVEL_CHANGE",
    "RiskBoundaryError",
    "RiskContext",
    "RiskSignal",
    "SIGNAL_AVAILABILITY",
    "SIGNAL_MISSING",
    "SIGNAL_NOT_APPLICABLE",
    "SIGNAL_STALE",
    "SIGNAL_UNAVAILABLE",
    "SIGNAL_UNUSABLE",
    "SIGNAL_VALID",
    "SPATIAL_QUANTITIES",
    "SPATIAL_SIGNAL_QUANTITIES",
    "SignalEvaluation",
    "StaleContextError",
    "UnsupportedContextError",
    "availability_counts",
    "available_signal",
    "context_contract_description",
    "evaluate_context",
    "evaluation_state",
    "unavailable_gis_context",
    "unavailable_historical_context",
    "unavailable_signal",
    "unusable_signals",
]