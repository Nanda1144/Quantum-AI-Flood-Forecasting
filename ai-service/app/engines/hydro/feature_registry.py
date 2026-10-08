# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 3 — the feature registry: what a feature is, and what it must not claim.

A feature name is a promise. `water_level_change_1h` promises three specific
things at once: that the source is water level, that the number is a difference
taken over one hour, and that it was formed from readings that existed at the
prediction time. A pipeline that produces a column with that name and cannot
answer those three questions has produced a number, not a feature.

This module makes the promise checkable. Every feature that Phase 3 can build is
described by a :class:`FeatureDefinition` carrying its source domain, its source
quantity, its transformation, its window, its unit, its dtype, what it needs in
order to exist at all, whether it is causal, which entity scope it is computed
in, how it behaves when its input is missing, and why it is scientifically
defensible for flood and inflow forecasting. The registry is the ordered,
de-duplicated compilation of those definitions, and it is the *only* thing that
decides what a column is called.

Three properties are load-bearing:

1. **Names are derived, never typed.** They come from
   :func:`feature_name`, one function, so the same definition can never be
   called two things. Nothing in the pipeline builds a feature name with an
   f-string at the point of use.
2. **Order is declaration order.** The registry is an ordered tuple, not a set
   or a dict, so the feature column order of a dataset is a property of the
   configuration rather than of hash iteration.
3. **Absence is documented, not silent.** :data:`UNAVAILABLE_STATIC_CATALOGUE`
   names the static and geographic features that a flood model would like and
   that this repository has no verified data for. They appear in the registry's
   report as unavailable with a reason. They are never emitted as columns, and
   no placeholder, zero or synthetic coordinate stands in for them.

What this module deliberately does not do: it does not compute anything. Every
value in it is a declaration. Whether a declared feature turns out to be
available for a particular dataset is decided in `feature_pipeline`, against
the data, and the answer is reported rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .domains import (
    CANONICAL_QUANTITY,
    MEASUREMENT_DOMAINS,
    NOT_AVAILABLE,
    QUANTITY_HUMIDITY,
    QUANTITY_TEMPERATURE,
    WEATHER_QUANTITIES,
    Observation,
)

#: Version of the Phase 4 handoff contract described in `PHASE3_FEATURE_ENGINEERING.md`.
#:
#: Distinct from `contract.FORECAST_CONTRACT_VERSION` (`hydro-forecast/v1`),
#: which describes a *forecast*, and from `datasets.SCHEMA_VERSION`
#: (`navya-hydro-schema/v1`), which describes an *ingested record*. This one
#: describes a model-ready feature dataset handed from Phase 3 to Phase 4.
FEATURE_CONTRACT_VERSION = "navya-features/v1"

#: Prefix for every Phase 3 report code. Distinct from Phase 2's
#: `preprocess_pipeline.CODE_PREFIX` and from Phase 1's bare codes, so a finding
#: can always be traced to the phase that raised it.
CODE_PREFIX = "FEATURE_"


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #

#: The observed value from `window` before the prediction time.
OP_LAG = "lag"
#: `value(T) - value(T - window)`. A difference, so the unit is unchanged and a
#: vertical datum cancels: two readings of the same gauge differ by the same
#: amount whatever surface they are measured from.
OP_CHANGE = "change"
#: `sum` of the window. Only defined for quantities where adding is meaningful.
OP_ACCUMULATION = "accumulation"
#: `accumulation / elapsed time`, i.e. a mean rate over the window.
OP_INTENSITY = "intensity"
#: An order statistic over the window.
OP_ROLLING = "rolling"
#: A deterministic function of the timestamp. Cannot leak: it reads no
#: observation, so it cannot encode one.
OP_CALENDAR = "calendar"
#: A value that does not vary in time and is not derivable from the records.
OP_STATIC = "static"

OPERATIONS = (
    OP_LAG,
    OP_CHANGE,
    OP_ACCUMULATION,
    OP_INTENSITY,
    OP_ROLLING,
    OP_CALENDAR,
    OP_STATIC,
)

#: How a rolling window relates to the prediction instant.
ALIGN_EXCLUDE_CURRENT = "exclude_current"
#: Window is `[T - window, T - base_interval]`; the observation at `T` is not in it.
ALIGN_INCLUDE_CURRENT = "include_current"

ALIGNMENTS = (ALIGN_EXCLUDE_CURRENT, ALIGN_INCLUDE_CURRENT)

#: How widely a feature's source reaches, narrowest first.
#:
#: `measurement`
#:     One `location|domain|quantity` series. Every temporal feature Phase 3
#:     builds is at this scope, and it is narrower than it strictly needs to be:
#:     nothing here reads across quantities, so a rainfall lag cannot become a
#:     water-level lag by accident.
#: `entity`
#:     One location, across all of its quantities. Reserved — no feature built
#:     today needs it, because no built feature combines two quantities.
#: `global`
#:     The timestamp alone. Calendar terms only.
ENTITY_SCOPES = ("measurement", "entity", "global")

ENTITY_SCOPE_MEANING: Mapping[str, str] = {
    "measurement": "one location + domain + quantity",
    "entity": "one location",
    "global": "timestamp only",
}

#: Reserved prefix on every target column. `feature_name` refuses to build a name
#: carrying it, so "is this column a target?" is answerable by a string test.
TARGET_PREFIX = "target_"


#: Operation -> the verb used in a feature name.
#:
#: A separate table rather than the operation constant reused as a name fragment,
#: because the two disagree: the operation is called `accumulation` and the
#: column is called `rainfall_accum_24h`. Writing that shortening in one place is
#: what keeps `feature_name` the only builder and keeps every accumulation column
#: named the same way.
_OPERATION_VERB: Mapping[str, str] = {
    OP_LAG: "lag",
    OP_CHANGE: "change",
    OP_ACCUMULATION: "accum",
    OP_INTENSITY: "intensity",
    OP_ROLLING: "rolling",
}


# --------------------------------------------------------------------------- #
# Availability
# --------------------------------------------------------------------------- #

#: The source series exists and can be read.
AVAILABLE = "available"
#: No series in this dataset reports the quantity the feature needs.
AVAILABLE_NO_SOURCE = "no_source_series"
#: The source series exists but its unit is not understood, so the number cannot
#: be given physical meaning. The value may still be *computed* where the
#: operation is unit-preserving, but it may not be *interpreted*.
AVAILABLE_UNDETERMINED_UNIT = "undetermined_source_unit"
#: The feature needs a relationship this project has not been given and must not
#: invent: a rating curve, a verified datum, a catchment boundary.
AVAILABLE_NO_APPROVED_RELATIONSHIP = "no_approved_relationship"
#: The series is present but has no usable history for this feature's window.
AVAILABLE_NO_HISTORY = "insufficient_history"

AVAILABILITY_STATUSES = (
    AVAILABLE,
    AVAILABLE_NO_SOURCE,
    AVAILABLE_UNDETERMINED_UNIT,
    AVAILABLE_NO_APPROVED_RELATIONSHIP,
    AVAILABLE_NO_HISTORY,
)


# --------------------------------------------------------------------------- #
# Quantities and their scope
# --------------------------------------------------------------------------- #

#: The domain that reports `quantity`.
#:
#: Phase 1 enforces one canonical quantity per domain (`domains.Observation`
#: refuses a `water_level` observation carrying `rainfall`), so for those four
#: domains the mapping is a bijection and this is an exact inverse. The `weather`
#: domain is the exception: Phase 1 lets it carry either weather quantity, which
#: is why `measurement_key` is three-level and Phase 2's two-level `series_key`
#: is not the right grouping for measurement-level feature work.
_DOMAIN_FOR_QUANTITY: Mapping[str, str] = {
    **{quantity: domain for domain, quantity in CANONICAL_QUANTITY.items()},
    QUANTITY_TEMPERATURE: "weather",
    QUANTITY_HUMIDITY: "weather",
}

#: Every quantity a Phase 3 feature can be built from, in a fixed order so that
#: configuration defaults and reports are reproducible.
SUPPORTED_QUANTITIES: tuple[str, ...] = (
    "rainfall",
    "water_level",
    "discharge",
    "inflow",
    QUANTITY_TEMPERATURE,
    QUANTITY_HUMIDITY,
)

#: Quantities for which summing over a window is physically meaningful.
#:
#: Narrow on purpose. A *sum* of levels is not a level, and a sum of a flow rate
#: is a volume — a different physical quantity in a different unit. Phase 2
#: declares the same narrow set as `preprocess_config.CUMULATIVE_QUANTITIES`,
#: because the question "does adding these make sense?" is the same question in
#: both phases, and answering it twice with two answers would be a defect.
ACCUMULABLE_QUANTITIES: tuple[str, ...] = ("rainfall",)

#: Quantities for which a mean rate over a window is physically meaningful.
INTENSITY_QUANTITIES: tuple[str, ...] = ("rainfall",)

#: Quantities that describe a level, and therefore carry the datum caveat.
LEVEL_QUANTITIES: tuple[str, ...] = ("water_level",)

#: Quantities that *drive* a catchment rather than describing its response.
#:
#: Rainfall, temperature and humidity are forcings: they are observed at the
#: moment a forecast is made, so a feature on them may legitimately read the
#: prediction instant. See `feature_config.CUTOFF_AT_PREDICTION`.
FORCING_QUANTITIES: tuple[str, ...] = ("rainfall", QUANTITY_TEMPERATURE, QUANTITY_HUMIDITY)

#: Quantities that are the *state* a forecast is about.
#:
#: Water level, discharge and inflow are the quantities being predicted. At the
#: prediction instant the current reading is the thing being forecast rather than
#: a known input, so a feature on one of these reads no later than the last
#: validated reading. See `feature_config.CUTOFF_ONE_STEP_BACK`.
STATE_QUANTITIES: tuple[str, ...] = ("water_level", "discharge", "inflow")


# --------------------------------------------------------------------------- #
# Calendar components
# --------------------------------------------------------------------------- #

#: Hour of the day. The diurnal cycle of the prediction time.
CAL_HOUR = "hour"
#: Day of the year. The annual cycle of the prediction time.
CAL_DOY = "doy"

CALENDAR_COMPONENTS: tuple[str, ...] = (CAL_HOUR, CAL_DOY)

#: Cyclical encodings. `sin` and `cos` of `2*pi*value/period`, evaluated from
#: the UTC instant only — never from an observation, so it cannot leak.
ENCODING_SIN = "sin"
ENCODING_COS = "cos"

CALENDAR_ENCODINGS: tuple[str, ...] = (ENCODING_SIN, ENCODING_COS)

#: Period of each enabled calendar component, in its own units.
#:
#: `hour` cycles over 24 units. `doy` cycles over 365.25 days: a leap year
#: averaged over four years, which is the constant the pre-Phase-1 `features`
#: layer already uses. Reusing it rather than switching to 365.2425 is
#: deliberate — the two paths should produce the same column for the same
#: information, and a 0.0075-day discrepancy in an annual harmonic is worth less
#: than the confusion of two different values for one named column.
CALENDAR_PERIODS: Mapping[str, float] = {
    CAL_HOUR: 24.0,
    CAL_DOY: 365.25,
}

#: Calendar components that were considered and are **not** enabled by default.
#:
#: Recorded rather than omitted, because the honest reason is a scientific one
#: and an unrecorded omission looks like an oversight.
EXCLUDED_CALENDAR_COMPONENTS: Mapping[str, str] = {
    "day_of_week": (
        "No hydrological mechanism is established here for a weekly cycle. A "
        "day-of-week term is defensible only for catchments whose flow is "
        "dominated by weekday abstractions or weekday traffic, and no catchment "
        "in this repository has been characterised. Adding it 'because it is "
        "easy' is exactly the failure this table exists to prevent."
    ),
    "month_of_year": (
        "Redundant with day_of_year. Month is a coarser quantisation of the "
        "same annual cycle, so a month term adds a collinear duplicate of "
        "information the annual harmonic already carries."
    ),
}


def domain_for_quantity(quantity: str) -> str:
    """The domain that reports `quantity`.

    Raises `KeyError` for a quantity Phase 3 has no feature vocabulary for,
    rather than inventing a domain for it.
    """
    try:
        return _DOMAIN_FOR_QUANTITY[quantity]
    except KeyError:
        raise KeyError(
            f"no Phase 1 domain reports quantity {quantity!r}; Phase 3 can build features "
            f"only from {SUPPORTED_QUANTITIES}"
        ) from None


def quantity_for_domain(domain: str) -> str | None:
    """The canonical quantity a domain reports, or `None` when it has no single one."""
    return CANONICAL_QUANTITY.get(domain)


def measurement_key(record: Observation) -> str:
    """One univariate measurement stream: location, domain *and* quantity.

    Phase 2's `preprocess_temporal.series_key` is `location|domain`, which is
    the right granularity for cadence inference, grid construction and resampling
    — all of which are about *when* readings arrive. It is not the right
    granularity for feature building, which is about *what is being measured*:
    a station reporting both temperature and humidity shares one Phase 2 series,
    so a key built on it would let a humidity lag resolve to a temperature
    reading. This key is strictly finer and never contradicts Phase 2 — each
    Phase 3 measurement series is a subset of a Phase 2 series.
    """
    quantity = record.quantity()
    if quantity is None:
        # Every observation carries at least one measurement, so this is
        # unreachable for a constructed record; the fallback keeps the key total
        # rather than raising inside a grouping loop.
        quantity = ""
    return f"{record.location_reference}|{record.domain}|{quantity}"


def split_measurement_key(key: str) -> tuple[str, str, str]:
    """Inverse of :func:`measurement_key`, for labels and report lines.

    Partitioned one separator at a time rather than with `split("|")` and a fixed
    length, so a location reference that itself contains a separator cannot make
    this raise in the middle of a grouping loop. A two-level key — the Phase 2
    `series_key` shape — degrades to `(location, domain, "")` rather than raising,
    which keeps a report line renderable for either key.
    """
    location, first, rest = key.partition("|")
    if not first:  # pragma: no cover - guarded by the builder
        return key, "", ""
    domain, second, quantity = rest.partition("|")
    if not second:
        return location, domain, ""
    return location, domain, quantity


def describe_measurement(key: str) -> str:
    """A measurement key rendered for humans."""
    location, domain, quantity = split_measurement_key(key)
    if quantity:
        return f"{location} [{domain}/{quantity}]"
    return f"{location} [{domain}]"


# --------------------------------------------------------------------------- #
# Window labels
# --------------------------------------------------------------------------- #


def window_label(seconds: float) -> str:
    """A short, stable label for a window of `seconds`.

    Hours win over days and days over minutes, so a 24-hour antecedent-rainfall
    window is labelled `24h` rather than `1d`. Hydrology names windows in hours,
    and a label that reads `1d` beside a column called `rainfall_accum_6h` is one
    more thing a reader has to translate. The choice is deterministic, which is
    what the naming contract needs; the *value* is not rounded or altered.

    Two windows that are the same number of seconds get the same label by
    construction, which is why the registry de-duplicates on seconds before it
    de-duplicates on names.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise TypeError(f"window seconds must be a real number, got {type(seconds).__name__}")
    value = float(seconds)
    if value <= 0:
        raise ValueError(f"window must be a positive number of seconds, got {seconds!r}")
    if value.is_integer() and int(value) % 3600 == 0:
        return f"{int(value) // 3600}h"
    if value.is_integer() and int(value) % 60 == 0:
        return f"{int(value) // 60}m"
    if value.is_integer():
        return f"{int(value)}s"
    return f"{value:g}s"


def feature_name(
    quantity: str,
    operation: str,
    *,
    window: float | None = None,
    statistic: str | None = None,
) -> str:
    """The one place a feature column name is built.

    Convention, applied uniformly:

    =============================  ==========================================
    Operation                      Name
    =============================  ==========================================
    lag                            `{quantity}_lag_{window}`
    change                         `{quantity}_change_{window}`
    accumulation                   `{quantity}_accum_{window}`
    intensity                      `{quantity}_intensity_{window}`
    rolling                        `{quantity}_rolling_{statistic}_{window}`
    =============================  ==========================================

    Calendar and static columns are *not* built here — they have their own
    builders, because their name components are not a quantity and a window.
    The target columns use a `target_` prefix that no feature name can begin
    with, so "is the target in my feature list?" is answerable by a string test
    as well as by construction.

    A rolling statistic must name a window; a lag, change, accumulation or
    intensity must not carry a statistic. Getting that wrong is a programming
    error, not a naming variant, so it raises.
    """
    if operation == OP_CALENDAR:
        raise ValueError(
            "use calendar_feature_name(component, encoding) for calendar features; their "
            "name is not built from a quantity and a window"
        )
    if operation == OP_STATIC:
        raise ValueError(
            "static features are declared in UNAVAILABLE_STATIC_CATALOGUE and are never "
            "built; a static feature has no window to name"
        )
    # The `target_` prefix is what lets a consumer answer "is my target in the
    # feature list?" with a string test instead of carrying a second list around.
    # That guarantee is only worth anything if it holds, so a quantity that would
    # produce such a name is refused rather than quietly shadowing a target column.
    if quantity == TARGET_PREFIX or quantity.startswith(TARGET_PREFIX):
        raise ValueError(
            f"quantity {quantity!r} would produce a feature name beginning with "
            f"{TARGET_PREFIX!r}, which is reserved for target columns; rename the quantity"
        )
    if operation in (OP_LAG, OP_CHANGE, OP_ACCUMULATION, OP_INTENSITY):
        if window is None:
            raise ValueError(f"a {operation} feature needs a window; got {quantity!r}")
        if statistic is not None:
            raise ValueError(
                f"a {operation} feature has no statistic; got {statistic!r} for {quantity!r}"
            )
        return f"{quantity}_{_OPERATION_VERB[operation]}_{window_label(window)}"
    if operation == OP_ROLLING:
        if window is None or not statistic:
            raise ValueError(
                f"a rolling feature needs both a window and a statistic; got "
                f"window={window!r} statistic={statistic!r}"
            )
        return f"{quantity}_rolling_{statistic}_{window_label(window)}"
    raise ValueError(f"unknown feature operation {operation!r}")


def calendar_feature_name(component: str, encoding: str) -> str:
    """The column name for a calendar component in a given encoding.

    `calendar_hour_sin`, `calendar_doy_cos`. The short spellings `hour` and `doy`
    are deliberate: the pre-Phase-1 `features` layer names its calendar columns
    the same way, so a model trained on either layer sees the same column name
    for the same quantity of information.
    """
    if component not in CALENDAR_COMPONENTS:
        raise ValueError(
            f"unknown calendar component {component!r}; expected one of {CALENDAR_COMPONENTS}"
        )
    if encoding not in CALENDAR_ENCODINGS:
        raise ValueError(
            f"unknown calendar encoding {encoding!r}; expected one of {CALENDAR_ENCODINGS}"
        )
    return f"calendar_{component}_{encoding}"


def target_name(quantity: str, horizon: float) -> str:
    """The column name for the target `horizon` ahead, in `quantity` units."""
    return f"target_{quantity}_{window_label(horizon)}"


# --------------------------------------------------------------------------- #
# Lineage
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Lineage:
    """Where one feature value came from, in machine-readable form.

    The point is auditability rather than documentation: given a fitted model and
    one column name, this answers "which readings, at which instants, at which
    station, in which unit, over which window" without a person re-deriving it.
    Every field is either a definite fact or `None` — never a default that
    looks like a fact.
    """

    source: str
    transformation: str
    entity_scope: str
    causal: bool
    window: str | None = None
    unit: str | None = None
    availability: str = AVAILABLE
    required_source_fields: tuple[str, ...] = ()
    target_of: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "transformation": self.transformation,
            "window": self.window,
            "entity_scope": self.entity_scope,
            "causal": self.causal,
            "unit": self.unit,
            "availability": self.availability,
            "required_source_fields": list(self.required_source_fields),
            "target_of": self.target_of,
        }

    def describe(self) -> str:
        parts = [f"source={self.source}", f"op={self.transformation}"]
        if self.window:
            parts.append(f"window={self.window}")
        parts.append(f"scope={self.entity_scope}")
        parts.append(f"causal={'true' if self.causal else 'false'}")
        parts.append(f"availability={self.availability}")
        return ", ".join(parts)


@dataclass(frozen=True)
class TargetLineage:
    """Where one target value came from.

    Separate from `Lineage` because the relationship is the opposite one: a
    target is, by construction, *not* available at prediction time, and a reader
    checking causality needs that stated rather than inferred from a window
    label.
    """

    source: str
    quantity: str
    horizon_seconds: float
    horizon_label: str
    entity_scope: str
    unit: str | None = None
    alignment: str = "exact"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "quantity": self.quantity,
            "horizon_seconds": self.horizon_seconds,
            "horizon_label": self.horizon_label,
            "entity_scope": self.entity_scope,
            "unit": self.unit,
            "alignment": self.alignment,
            "available_at_prediction_time": False,
        }

    def describe(self) -> str:
        return (
            f"target={self.source}, quantity={self.quantity}, "
            f"horizon={self.horizon_label} ({self.horizon_seconds:g}s), "
            f"alignment={self.alignment}, NOT available at prediction time"
        )


# --------------------------------------------------------------------------- #
# One feature
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FeatureDefinition:
    """Everything that is known about one feature before any data is read.

    Immutable, so a registry cannot be edited underneath a dataset that was built
    from it — the failure where a report describes different features from the
    ones in the matrix.
    """

    name: str
    operation: str
    quantity: str
    source_domain: str
    source_quantity: str
    description: str
    rationale: str
    #: Seconds. The lag offset for `lag`, the span for `change`, the width for
    #: `accumulation` / `intensity` / `rolling`; `None` for `calendar`.
    window_seconds: float | None = None
    #: `lag`, or the order statistic, or the calendar component.
    statistic: str | None = None
    #: Whether the observation at the prediction instant is inside the window.
    include_current: bool = False
    #: Declared expected unit. `None` means "whatever the source declares" —
    #: Phase 3 never converts, so the source's unit *is* the feature's unit.
    unit: str | None = None
    dtype: str = "float64"
    #: The requirement in `AVAILABILITY_STATUSES` that the data must satisfy
    #: before this feature can be built.
    availability_requirement: str = AVAILABLE
    #: `True` for every feature Phase 3 will build. A `False` here is a bug in
    #: this module, and the registry refuses to compile one.
    causal: bool = True
    #: `measurement` (one location + domain + quantity), `entity` (one location,
    #: across all its quantities) or `global` (a function of the timestamp).
    entity_scope: str = "measurement"
    #: Field paths on the Phase 1 `Observation` this feature reads.
    required_source_fields: tuple[str, ...] = ()
    #: Whether the feature is meaningful for synthetic/demo data. Always
    #: `True` here — the arithmetic is identical — but recorded explicitly so
    #: that a reader does not have to infer it, and so that a future feature
    #: whose *interpretation* depends on real gauge behaviour can opt out.
    synthetic_compatible: bool = True
    #: What happens when the required source observation is absent.
    missing_behaviour: str = "retain_missing"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("feature name must not be blank")
        if self.operation not in OPERATIONS:
            raise ValueError(
                f"feature {self.name!r} has unknown operation {self.operation!r}; "
                f"expected one of {OPERATIONS}"
            )
        if self.entity_scope not in ENTITY_SCOPES:
            raise ValueError(
                f"feature {self.name!r} has unknown entity scope {self.entity_scope!r}; "
                f"expected one of {ENTITY_SCOPES}"
            )
        if self.availability_requirement not in AVAILABILITY_STATUSES:
            raise ValueError(
                f"feature {self.name!r} has unknown availability requirement "
                f"{self.availability_requirement!r}"
            )
        if not self.causal:
            raise ValueError(
                f"feature {self.name!r} is declared non-causal. Phase 3 builds only "
                "point-in-time-correct features; a feature that reads the future belongs "
                "to a different phase and a different review"
            )
        if self.operation == OP_CALENDAR and self.entity_scope != "global":
            raise ValueError(
                f"calendar feature {self.name!r} must have entity scope 'global'; a "
                "calendar term is a function of the timestamp, not of one station"
            )

    @property
    def window_label(self) -> str | None:
        """The label used in the name, or `None` when the feature has no window."""
        if self.window_seconds is None:
            return None
        return window_label(self.window_seconds)

    @property
    def alignment(self) -> str | None:
        """How the window relates to the prediction instant, or `None` if not applicable."""
        if self.operation in (OP_LAG, OP_CALENDAR, OP_STATIC):
            return None
        if self.operation == OP_CHANGE:
            # A change is anchored on the prediction instant and reads the value
            # `window` before it, so the current reading is always the endpoint
            # and is *not* "inside a window" in the accumulation sense.
            return ALIGN_INCLUDE_CURRENT if self.include_current else ALIGN_EXCLUDE_CURRENT
        if self.operation in (OP_ACCUMULATION, OP_INTENSITY, OP_ROLLING):
            return ALIGN_INCLUDE_CURRENT if self.include_current else ALIGN_EXCLUDE_CURRENT
        return None  # pragma: no cover - every operation is covered above

    @property
    def is_temporal(self) -> bool:
        """True when the feature reads one or more observations."""
        return self.operation != OP_CALENDAR

    @property
    def lineage(self) -> Lineage:
        """The feature's provenance, derived from the definition.

        A property rather than a stored field, so the lineage a report publishes
        cannot drift from the definition it describes.
        """
        if self.operation == OP_CALENDAR:
            source = f"timestamp ({self.quantity}/{self.statistic})"
            transformation = f"deterministic_{self.quantity}_{self.statistic}"
            fields = ("observed_at",)
        elif self.operation == OP_STATIC:
            # A static value is not in the record stream at all, so it reads no
            # field of an `Observation`. Naming measurement fields here would
            # claim a read that never happens.
            source = f"static attribute {self.quantity} ({self.source_domain})"
            transformation = "static_attribute"
            fields = ()
        else:
            source = f"{self.source_domain}/{self.source_quantity}"
            transformation = f"{self.operation}" + (
                f"_{self.statistic}" if self.operation == OP_ROLLING else ""
            )
            fields = (
                "location_reference",
                "domain",
                "observed_at",
                f"measurements[{self.source_quantity}]",
            )
        return Lineage(
            source=source,
            transformation=transformation,
            entity_scope=self.entity_scope,
            causal=self.causal,
            window=self.window_label,
            unit=self.unit,
            availability=self.availability_requirement,
            required_source_fields=fields,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "operation": self.operation,
            "quantity": self.quantity,
            "source_domain": self.source_domain,
            "source_quantity": self.source_quantity,
            "window": self.window_label,
            "window_seconds": self.window_seconds,
            "statistic": self.statistic,
            "include_current": self.include_current,
            "alignment": self.alignment,
            "unit": self.unit,
            "dtype": self.dtype,
            "availability_requirement": self.availability_requirement,
            "causal": self.causal,
            "entity_scope": self.entity_scope,
            "required_source_fields": list(self.required_source_fields),
            "synthetic_compatible": self.synthetic_compatible,
            "missing_behaviour": self.missing_behaviour,
            "description": self.description,
            "rationale": self.rationale,
            "lineage": self.lineage.to_dict(),
        }

    def describe(self) -> str:
        scope = ENTITY_SCOPE_MEANING[self.entity_scope]
        line = (
            f"  - {self.name}: {self.description} "
            f"[source={self.source_domain}/{self.source_quantity}, "
            f"op={self.operation}"
        )
        if self.window_label:
            line += f", window={self.window_label}"
        if self.operation == OP_ROLLING and self.statistic:
            line += f", stat={self.statistic}"
        if self.alignment:
            line += f", align={self.alignment}"
        line += f", scope={scope}, dtype={self.dtype}]"
        return line


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FeatureRegistry:
    """An ordered, de-duplicated set of feature definitions.

    Frozen and ordered. The ordering is the column order of every dataset built
    from this registry, which is why it is declaration order and not, say, the
    order of a `set`. Two runs with the same configuration produce the same
    columns in the same positions.
    """

    definitions: tuple[FeatureDefinition, ...] = ()
    subject: str = "phase3_features"

    def __post_init__(self) -> None:
        index: dict[str, FeatureDefinition] = {}
        for definition in self.definitions:
            if definition.name in index:
                raise ValueError(
                    f"feature registry contains {definition.name!r} twice; names must be unique "
                    "so that a column in the matrix identifies exactly one definition"
                )
            index[definition.name] = definition
        object.__setattr__(self, "_index", index)

    # --- reading -----------------------------------------------------------

    def __len__(self) -> int:
        return len(self.definitions)

    def __iter__(self) -> Iterator[FeatureDefinition]:
        return iter(self.definitions)

    def __contains__(self, name: object) -> bool:
        return name in self._index

    def get(self, name: str) -> FeatureDefinition:
        """The definition called `name`.

        Raises `KeyError` naming the nearest available names, because a silent
        `None` here would produce a dataset that quietly lacks a declared column.
        """
        try:
            return self._index[name]
        except KeyError:
            close = [known for known in self._index if known.split("_")[0] == str(name).split("_")[0]]
            hint = f"; features on the same quantity: {sorted(close)}" if close else ""
            raise KeyError(
                f"no feature named {name!r} in this registry{hint}. Available: {self.names}"
            ) from None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(definition.name for definition in self.definitions)

    @property
    def quantities(self) -> tuple[str, ...]:
        """Distinct source quantities, in first-appearance order."""
        seen: list[str] = []
        for definition in self.definitions:
            if definition.quantity not in seen:
                seen.append(definition.quantity)
        return tuple(seen)

    def for_quantity(self, quantity: str) -> tuple[FeatureDefinition, ...]:
        return tuple(d for d in self.definitions if d.quantity == quantity)

    def for_operation(self, operation: str) -> tuple[FeatureDefinition, ...]:
        return tuple(d for d in self.definitions if d.operation == operation)

    def temporal(self) -> tuple[FeatureDefinition, ...]:
        """Every feature that reads an observation, in registry order."""
        return tuple(d for d in self.definitions if d.is_temporal)

    def calendar(self) -> tuple[FeatureDefinition, ...]:
        return self.for_operation(OP_CALENDAR)

    def names_for(self, operation: str, quantity: str | None = None) -> tuple[str, ...]:
        """Names of features for `operation`, optionally restricted to `quantity`."""
        return tuple(
            d.name
            for d in self.definitions
            if d.operation == operation and (quantity is None or d.quantity == quantity)
        )

    def requires_quantity(self, quantity: str) -> bool:
        return any(d.source_quantity == quantity for d in self.definitions)

    # --- reporting ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": FEATURE_CONTRACT_VERSION,
            "subject": self.subject,
            "feature_count": len(self.definitions),
            "features": [d.to_dict() for d in self.definitions],
            "names": list(self.names),
            "quantities": list(self.quantities),
        }

    def describe(self) -> str:
        lines = [
            f"Feature registry ({len(self.definitions)} feature(s), "
            f"contract {FEATURE_CONTRACT_VERSION}):"
        ]
        lines.extend(definition.describe() for definition in self.definitions)
        return "\n".join(lines)

    def lineage_table(self) -> list[dict[str, Any]]:
        """One row per feature, for a machine-readable lineage export."""
        return [d.lineage.to_dict() for d in self.definitions]


def _dedupe_by_window(seconds: Iterable[float]) -> tuple[float, ...]:
    """Order-preserving de-duplication of window lengths.

    De-duplicated on *seconds*, before anything looks at names, so `1d` and
    `24h` — the same window spelled two ways — collapse to one entry and cannot
    produce two columns holding the same number.
    """
    seen: list[float] = []
    for value in seconds:
        number = float(value)
        if not any(number == existing for existing in seen):
            seen.append(number)
    return tuple(seen)


def dedupe_windows(seconds: Iterable[float]) -> tuple[float, ...]:
    """Public wrapper around the window de-duplication, for callers and tests."""
    return _dedupe_by_window(seconds)


# --------------------------------------------------------------------------- #
# What is considered and refused
# --------------------------------------------------------------------------- #

#: Features a flood or inflow model would reasonably want, which this repository
#: has no verified data for or no approved relationship for.
#:
#: Listed as real :class:`FeatureDefinition` objects inside a real
#: :class:`FeatureRegistry`, so they are reported through the same machinery as
#: everything else — but they are **never** in the built feature set, and no
#: column, zero, midpoint or synthetic coordinate stands in for one.
#:
#: Two separate reasons appear here and the distinction matters. A static
#: geographic value is *absent*: nobody has supplied it, and a plausible-looking
#: number would be invented geography. A rating curve or a runoff coefficient is
#: *unapproved*: the relationship is real and well known, but this project has not
#: been given the specific curve for this catchment, and fitting one from the
#: observations would be model development inside the feature layer.
UNAVAILABLE_STATIC_CATALOGUE: FeatureRegistry = FeatureRegistry(
    subject="phase3_considered_unavailable",
    definitions=(
        FeatureDefinition(
            name="static_elevation",
            operation=OP_STATIC,
            quantity="elevation",
            source_domain=NOT_AVAILABLE,
            source_quantity="elevation",
            availability_requirement=AVAILABLE_NO_SOURCE,
            entity_scope="entity",
            description="Gauge elevation above a stated vertical datum.",
            rationale=(
                "Elevation controls how much rainfall a catchment can store before "
                "runoff begins, so it belongs in a runoff model. No elevation data "
                "and no vertical datum exists in this repository."
            ),
        ),
        FeatureDefinition(
            name="static_latitude",
            operation=OP_STATIC,
            quantity="latitude",
            source_domain=NOT_AVAILABLE,
            source_quantity="latitude",
            availability_requirement=AVAILABLE_NO_SOURCE,
            entity_scope="entity",
            description="Gauge latitude in degrees.",
            rationale=(
                "Latitude is a proxy for climate regime. There is no station "
                "registry in this repository, and no station may be given "
                "coordinates that were not supplied."
            ),
        ),
        FeatureDefinition(
            name="static_longitude",
            operation=OP_STATIC,
            quantity="longitude",
            source_domain=NOT_AVAILABLE,
            source_quantity="longitude",
            availability_requirement=AVAILABLE_NO_SOURCE,
            entity_scope="entity",
            description="Gauge longitude in degrees.",
            rationale=(
                "Longitude is a proxy for orographic regime. There is no station "
                "registry in this repository, and no station may be given "
                "coordinates that were not supplied."
            ),
        ),
        FeatureDefinition(
            name="static_river_distance",
            operation=OP_STATIC,
            quantity="river_distance",
            source_domain=NOT_AVAILABLE,
            source_quantity="river_distance",
            availability_requirement=AVAILABLE_NO_SOURCE,
            entity_scope="entity",
            description="Distance from the gauge to the nearest mapped channel.",
            rationale=(
                "Distance to the channel governs how quickly catchment response "
                "reaches the gauge. No channel network exists in this repository."
            ),
        ),
        FeatureDefinition(
            name="static_basin_identifier",
            operation=OP_STATIC,
            quantity="basin_identifier",
            source_domain=NOT_AVAILABLE,
            source_quantity="basin_identifier",
            availability_requirement=AVAILABLE_NO_SOURCE,
            entity_scope="entity",
            description="Identifier of the drainage basin a gauge belongs to.",
            rationale=(
                "Basins differ in area, slope and land cover, so a model pooled "
                "across basins needs this. No basin boundary and no basin registry "
                "exist in this repository."
            ),
        ),
        FeatureDefinition(
            name="static_catchment_area",
            operation=OP_STATIC,
            quantity="catchment_area",
            source_domain=NOT_AVAILABLE,
            source_quantity="catchment_area",
            availability_requirement=AVAILABLE_NO_SOURCE,
            entity_scope="entity",
            description="Drainage area upstream of the gauge.",
            rationale=(
                "Catchment area scales the rainfall-to-discharge relationship. It "
                "cannot be derived from the observations and is not present."
            ),
        ),
        FeatureDefinition(
            name="derived_discharge_from_water_level",
            operation=OP_STATIC,
            quantity="discharge",
            source_domain=NOT_AVAILABLE,
            source_quantity="discharge",
            availability_requirement=AVAILABLE_NO_APPROVED_RELATIONSHIP,
            entity_scope="measurement",
            description="Discharge derived from water level through a rating curve.",
            rationale=(
                "A rating curve relates stage to discharge at a gauge and is "
                "standard practice. Fitting one here would be model development "
                "inside the feature layer, and an unapproved curve would silently "
                "invent discharge. Discharge is used only where it is observed."
            ),
        ),
        FeatureDefinition(
            name="derived_inflow_from_rainfall",
            operation=OP_STATIC,
            quantity="inflow",
            source_domain=NOT_AVAILABLE,
            source_quantity="inflow",
            availability_requirement=AVAILABLE_NO_APPROVED_RELATIONSHIP,
            entity_scope="measurement",
            description="Inflow estimated from rainfall through a runoff coefficient.",
            rationale=(
                "The rational method relates rainfall to runoff through a "
                "coefficient specific to a catchment's area, slope and land cover. "
                "No catchment has been characterised here, so any coefficient would "
                "be invented. Inflow is used only where it is observed."
            ),
        ),
        FeatureDefinition(
            name="derived_water_level_datum_offset",
            operation=OP_STATIC,
            quantity="water_level",
            source_domain=NOT_AVAILABLE,
            source_quantity="water_level",
            availability_requirement=AVAILABLE_NO_APPROVED_RELATIONSHIP,
            entity_scope="measurement",
            description="Offset relating two gauges' levels to a common datum.",
            rationale=(
                "Converting millimetres to feet relabels a level and moves nothing "
                "on the ground, so levels from different gauges stay incomparable "
                "until a datum is established. No datum survey exists here, so "
                "levels are never pooled across gauges."
            ),
        ),
    ),
)

#: Total declared-but-unbuildable features, for report headers.
UNAVAILABLE_FEATURE_COUNT = len(UNAVAILABLE_STATIC_CATALOGUE)

#: How many of those the default report lists. Declared rather than recomputed at
#: each call site so a test can assert the two views really do differ by exactly the
#: relationship-derived entries, instead of silently converging on one number.
UNAVAILABLE_STATIC_COUNT = sum(
    1 for d in UNAVAILABLE_STATIC_CATALOGUE.definitions if d.availability_requirement == AVAILABLE_NO_SOURCE
)


def unavailable_catalogue(include_relationship_features: bool = False) -> FeatureRegistry:
    """The refused-feature catalogue, optionally narrowed.

    The default omits the relationship-derived entries. They are a different kind
    of absence — an unapproved equation rather than a missing measurement — and
    reporting them separately keeps "we have no elevation data" from being read
    as "we have no rating curve".
    """
    if include_relationship_features:
        return UNAVAILABLE_STATIC_CATALOGUE
    return FeatureRegistry(
        subject=UNAVAILABLE_STATIC_CATALOGUE.subject,
        definitions=tuple(
            d
            for d in UNAVAILABLE_STATIC_CATALOGUE.definitions
            if d.availability_requirement == AVAILABLE_NO_SOURCE
        ),
    )


__all__ = [
    "ACCUMULABLE_QUANTITIES",
    "ALIGN_EXCLUDE_CURRENT",
    "ALIGN_INCLUDE_CURRENT",
    "ALIGNMENTS",
    "AVAILABLE",
    "AVAILABLE_NO_APPROVED_RELATIONSHIP",
    "AVAILABLE_NO_HISTORY",
    "AVAILABLE_NO_SOURCE",
    "AVAILABLE_UNDETERMINED_UNIT",
    "AVAILABILITY_STATUSES",
    "CALENDAR_COMPONENTS",
    "CALENDAR_ENCODINGS",
    "CALENDAR_PERIODS",
    "CAL_DOY",
    "CAL_HOUR",
    "CODE_PREFIX",
    "ENCODING_COS",
    "ENCODING_SIN",
    "ENTITY_SCOPES",
    "ENTITY_SCOPE_MEANING",
    "EXCLUDED_CALENDAR_COMPONENTS",
    "FEATURE_CONTRACT_VERSION",
    "FORCING_QUANTITIES",
    "FeatureDefinition",
    "FeatureRegistry",
    "INTENSITY_QUANTITIES",
    "LEVEL_QUANTITIES",
    "Lineage",
    "MEASUREMENT_DOMAINS",
    "NOT_AVAILABLE",
    "OP_ACCUMULATION",
    "OP_CALENDAR",
    "OP_CHANGE",
    "OP_INTENSITY",
    "OP_LAG",
    "OP_ROLLING",
    "OP_STATIC",
    "OPERATIONS",
    "STATE_QUANTITIES",
    "SUPPORTED_QUANTITIES",
    "TARGET_PREFIX",
    "TargetLineage",
    "UNAVAILABLE_FEATURE_COUNT",
    "UNAVAILABLE_STATIC_COUNT",
    "UNAVAILABLE_STATIC_CATALOGUE",
    "WEATHER_QUANTITIES",
    "calendar_feature_name",
    "dedupe_windows",
    "describe_measurement",
    "domain_for_quantity",
    "feature_name",
    "measurement_key",
    "quantity_for_domain",
    "split_measurement_key",
    "target_name",
    "unavailable_catalogue",
    "window_label",
]