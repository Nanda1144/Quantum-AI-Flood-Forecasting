# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 3 — causal window arithmetic over Phase 2 records.

Every number this module produces is a function of observations at instants
**strictly at or before** a stated cutoff. That is the whole contract, and it is
enforced structurally rather than by convention: each operation is expressed as
a *slice of a series that ends at the cutoff*, and no operation is handed the
observations after it. There is no way to write a forward-looking window here
without deliberately reaching past the end of a slice, because a slice does not
contain anything past its end.

Three design choices carry most of the weight.

**Lookups are by instant, not by row offset.** `value_at(series, instant)`
resolves the reading at one specific instant. A row-based lag — the `shift(k)`
idiom — is only equivalent to a lag *when the cadence is regular*, and the moment
it is not, `shift(1)` silently means "the previous reading, whenever that was".
On a gauge that dropped two hours, `water_level_lag_1h` built that way is really
a three-hour lag wearing a one-hour name. Phase 3 therefore treats a missing
instant as a missing instant, which is also what keeps feature missingness visible
instead of quietly re-pointed.

**Entity isolation is structural, not a filter.** A `SeriesTimeline` is built per
`(location, domain, quantity)` and an operation receives one timeline. There is
no code path by which station A's readings can reach station B's features,
because no operation ever holds two timelines at once. This is why the leakage
tests can assert isolation as a property of the design rather than re-derive it.

**A window that cannot be filled reports why.** Every result is a
`WindowResult` carrying a value, a *reason* it is absent, and how many
observations the window actually covered. That distinction is what lets the
report separate a warm-up row (the series began later than the window reaches
back to) from a genuinely missing reading (the series existed and the reading was
not there) from an under-covered accumulation (a partial sum that would
under-report the quantity it is named after). Three causes, three different
meanings, and conflating them is how a dataset acquires a silent bias.

This module does not compute features. It computes the *values* that features
are made of, given a definition and a timeline. Naming, ordering and reporting
belong to `feature_pipeline`; policies belong to `feature_config`.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable, Mapping, Sequence

from .domains import Observation, parse_instant
from .feature_config import (
    CUTOFF_AT_PREDICTION,
    CUTOFF_ONE_STEP_BACK,
    FeatureConfig,
    STATISTICS_NEEDING_TWO,
    STAT_MAX,
    STAT_MEAN,
    STAT_MIN,
    STAT_STD,
    TARGET_AT_OR_BEFORE,
    TARGET_EXACT,
    UNIT_REQUIRE_KNOWN,
)
from .feature_registry import (
    OP_ACCUMULATION,
    OP_CALENDAR,
    OP_CHANGE,
    OP_INTENSITY,
    OP_LAG,
    OP_ROLLING,
    split_measurement_key,
)


class FeatureTemporalError(ValueError):
    """Raised when a temporal operation is impossible rather than merely absent.

    Distinct from `feature_config.FeatureConfigError` (the configuration is
    self-contradictory) and `feature_pipeline.FeatureError` (the pipeline cannot
    run). This one means: the request cannot be satisfied at all, as opposed to
    the request being satisfiable with an absent answer.
    """


# --------------------------------------------------------------------------- #
# Why a value is absent
# --------------------------------------------------------------------------- #

#: The series began later than the window reaches back to, so no earlier reading
#: has ever existed for this entity. No policy can fix this except by having more
#: history, and it is the normal state of the first rows of every series.
CAUSE_WARMUP = "warmup"

#: The series existed and the window reached into it, but the required reading
#: was not there — a gap Phase 2 was told to retain, a record dropped by a
#: policy, or a cadence irregularity. This is a statement about the data.
CAUSE_MISSING_SOURCE = "missing_source"

#: The window is real but not enough of it was observed to support the operation:
#: a standard deviation needs two observations, and an accumulation whose
#: coverage requirement is not met produces a number that would under-report the
#: quantity it is named after.
CAUSE_INSUFFICIENT = "insufficient"

#: The source unit could not be interpreted and the policy refuses the operation.
CAUSE_UNDETERMINED_UNIT = "undetermined_unit"

#: The operation needs two readings in comparable units and they are not.
CAUSE_UNIT_MISMATCH = "unit_mismatch"

#: The operation is not applicable to this quantity at all — an accumulation of a
#: level, for instance.
CAUSE_NOT_APPLICABLE = "not_applicable"

#: There is no series for this quantity at this entity. Distinct from
#: `CAUSE_MISSING_SOURCE` in the way that matters: a missing reading is a hole in
#: a record that exists, while this is a column the dataset never had. Only the
#: pipeline can tell them apart, because only it knows which timelines were built.
CAUSE_NO_SOURCE = "no_source_series"

#: A `one_step_back` cutoff could not be placed: the series has no established
#: cadence, and nothing was observed before the origin to stand in for the
#: previous step. Reported rather than silently evaluated against the origin,
#: because a state window that includes the prediction instant contains the
#: quantity being predicted — and a value labelled "the mean level over the six
#: hours before T" that is really "the level at T" is worse than no value at all,
#: because it looks like the former to everything downstream.
CAUSE_CUTOFF_UNDEFINED = "cutoff_undefined"

ABSENT_CAUSES = (
    CAUSE_WARMUP,
    CAUSE_MISSING_SOURCE,
    CAUSE_INSUFFICIENT,
    CAUSE_UNDETERMINED_UNIT,
    CAUSE_UNIT_MISMATCH,
    CAUSE_NOT_APPLICABLE,
    CAUSE_NO_SOURCE,
    CAUSE_CUTOFF_UNDEFINED,
)


@dataclass(frozen=True)
class Reading:
    """One observation, reduced to what a window needs.

    Holding the instant as a `datetime` and the value as a `float` keeps the
    window arithmetic free of `Observation`'s validation surface, which has
    already run and must not re-run per feature.
    """

    instant: datetime
    value: float
    unit: str
    #: Phase 2's `quality_status`. A record Phase 2 marked `missing` carries a
    #: filled or retained value whose provenance is a policy decision, not an
    #: observation, so the pipeline can exclude it from features.
    quality_status: str = "ok"
    source_reference: str | None = None

    @property
    def is_filled(self) -> bool:
        return self.quality_status == "missing"


@dataclass(frozen=True)
class WindowResult:
    """The outcome of one window computation, present or absent with a reason.

    An absent result is a *result*, not a failure. It carries `reason` so the
    report can distinguish the causes, and `observations` so coverage is
    measurable rather than assumed.
    """

    value: float | None
    reason: str | None = None
    #: How many readings the window actually contained.
    observations: int = 0
    #: How many the window expected, from the known cadence. `None` when the
    #: cadence is unknown and coverage therefore cannot be assessed at all.
    expected: int | None = None
    #: The instants the window covered, earliest first. Empty when nothing was
    #: there. Retained so a report can show *which* readings produced a number.
    instants: tuple[datetime, ...] = ()
    #: The newest instant this result is allowed to depend on. A leaked feature
    #: would show up here as a value later than its own cutoff.
    cutoff: datetime | None = None

    @property
    def is_present(self) -> bool:
        return self.value is not None

    @property
    def coverage(self) -> float | None:
        """Fraction of expected slots observed, or `None` when unassessable."""
        if self.expected is None or self.expected <= 0:
            return None
        return self.observations / self.expected

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "reason": self.reason,
            "observations": self.observations,
            "expected": self.expected,
            "coverage": self.coverage,
        }


ABSENT = WindowResult(value=None, reason=None)


def _absent(reason: str, **kwargs: Any) -> WindowResult:
    return WindowResult(value=None, reason=reason, **kwargs)


# --------------------------------------------------------------------------- #
# Series timelines
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SeriesTimeline:
    """One entity's readings for one measurement, in instant order.

    Sorted and de-duplicated on construction. De-duplication is by instant and
    resolves to the *first* reading, because Phase 2 has already removed exact
    duplicates and refused conflicts; anything still sharing an instant here is a
    caller error, and taking the first deterministically keeps it from becoming
    a silent source of variation.

    Two views are precomputed because both window directions are needed on every
    call and neither is cheap to recompute:

    * `_instants` ascending, for `value_at` and for boundary searches.
    * `_prefix_sum` cumulative over `_instants`, so a range sum is one subtraction
      rather than a walk. This is what keeps a 24-hour accumulation O(1) instead
      of O(window), and is the only place the module uses extra memory for speed.
    """

    key: str
    location: str
    domain: str
    quantity: str
    unit: str | None
    readings: tuple[Reading, ...] = ()
    #: Seconds between consecutive readings, when Phase 2 established one.
    base_interval_seconds: float | None = None

    def __post_init__(self) -> None:
        ordered = sorted(self.readings, key=lambda reading: reading.instant)
        instants: list[datetime] = []
        unique: list[Reading] = []
        for reading in ordered:
            if instants and reading.instant == instants[-1]:
                continue
            instants.append(reading.instant)
            unique.append(reading)
        object.__setattr__(self, "readings", tuple(unique))
        object.__setattr__(self, "_instants", tuple(instants))

        prefix: list[float] = []
        running = 0.0
        for reading in unique:
            running += reading.value
            prefix.append(running)
        object.__setattr__(self, "_prefix_sum", tuple(prefix))

        units = {reading.unit for reading in unique}
        object.__setattr__(self, "_units", units)

    # --- basics -----------------------------------------------------------

    def __len__(self) -> int:
        return len(self.readings)

    @property
    def is_empty(self) -> bool:
        return not self.readings

    @property
    def first_instant(self) -> datetime | None:
        return self._instants[0] if self._instants else None

    @property
    def last_instant(self) -> datetime | None:
        return self._instants[-1] if self._instants else None

    @property
    def units_seen(self) -> tuple[str, ...]:
        return tuple(sorted(self._units))

    @property
    def has_uniform_unit(self) -> bool:
        """Whether every reading in this series carries the same unit.

        A sum or a difference across mixed units is arithmetic on incompatible
        numbers. Phase 2 normally prevents this by refusing a mixed-unit
        resampling bin, but a series assembled across batches can still arrive
        mixed, and the window operations here refuse rather than convert.
        """
        return len(self._units) <= 1

    # --- point lookups -----------------------------------------------------

    def index_of(self, instant: datetime) -> int | None:
        """Position of the reading at exactly `instant`, or `None`."""
        position = bisect_left(self._instants, instant)
        if position < len(self._instants) and self._instants[position] == instant:
            return position
        return None

    def value_at(self, instant: datetime) -> Reading | None:
        """The reading at exactly `instant`, or `None`.

        Exactly. Not "at or before", not "the nearest". A lag means a stated
        distance in time, and on an irregular series there may be no reading at
        that distance — in which case the honest answer is that the feature does
        not exist for this row, and the report says so.
        """
        position = self.index_of(instant)
        return None if position is None else self.readings[position]

    def latest_at_or_before(self, instant: datetime) -> Reading | None:
        """The newest reading at or before `instant`, or `None`."""
        position = bisect_right(self._instants, instant)
        return None if position == 0 else self.readings[position - 1]

    # --- range access ------------------------------------------------------

    def readings_in(
        self, start: datetime, end: datetime, *, inclusive_start: bool = True
    ) -> list[Reading]:
        """Readings within `[start, end]`, honouring the start's inclusivity.

        The end is always exclusive of anything after it, which is what makes a
        window causal: the caller passes the cutoff as `end` and this function
        cannot return a later reading even if asked for one.
        """
        left = bisect_right(self._instants, start) if not inclusive_start else bisect_left(
            self._instants, start
        )
        right = bisect_right(self._instants, end)
        if right <= left:
            return []
        return list(self.readings[left:right])

    def sum_in(
        self, start: datetime, end: datetime, *, inclusive_start: bool = True
    ) -> tuple[float, int]:
        """`(sum, count)` over the half-open range, in O(log n) + O(1)."""
        left = bisect_right(self._instants, start) if not inclusive_start else bisect_left(
            self._instants, start
        )
        right = bisect_right(self._instants, end)
        if right <= left:
            return 0.0, 0
        prefix = self._prefix_sum
        total = prefix[right - 1] - (prefix[left - 1] if left > 0 else 0.0)
        return total, right - left

    def expected_slots(self, window_seconds: float) -> int | None:
        """How many readings a `window_seconds` window should hold.

        `None` when the cadence is unknown. Reporting coverage against a cadence
        nobody established would be inventing one, so the caller receives `None`
        and must treat coverage as unassessable rather than as perfect.
        """
        if self.base_interval_seconds is None or self.base_interval_seconds <= 0:
            return None
        ratio = window_seconds / self.base_interval_seconds
        if not math.isfinite(ratio) or ratio <= 0:
            return None
        return max(1, int(round(ratio)))


def build_timelines(
    records: Iterable[Observation],
    *,
    base_intervals: Mapping[str, float] | None = None,
    exclude_filled: bool = True,
) -> dict[str, SeriesTimeline]:
    """Group records into one :class:`SeriesTimeline` per measurement.

    `base_intervals` maps a Phase 2 `series_key` (`location|domain`) to the
    cadence Phase 2 inferred, in seconds. Phase 3 does not re-infer it: Phase 2
    owns cadence, and re-deriving it here would give two answers to one question.

    `exclude_filled` drops readings whose `quality_status` is Phase 2's
    `missing`, which marks a slot the gap policy filled. A filled slot is a policy
    decision, not an observation; feeding it to a lag would teach a model that an
    imputed number was measured, and feeding it to an accumulation would inflate
    a rainfall total. Default on, and reported when it changes anything.

    **One timeline per *measurement*, not per record.** A record carrying both a
    temperature and a humidity reading yields two timelines, not zero and not one.
    Iterating the measurements rather than asking the domain for its canonical
    quantity matters for exactly the reason the three-level key exists: `weather`
    has no single canonical quantity, so `Observation.quantity()` returns `None`
    for it, and a build keyed on that would drop every wide weather record on the
    floor without a word — leaving the temperature and humidity columns permanently
    empty while the report cheerfully said the features were built. Splitting the
    record is also what keeps a humidity lag from resolving to a temperature
    reading. Phase 1's validated data is one quantity per record, so for the normal
    case this loop runs exactly once and nothing changes.
    """
    buckets: dict[str, list[Reading]] = {}
    meta: dict[str, tuple[str, str, str, str | None]] = {}
    for record in records:
        if exclude_filled and record.quality_status == "missing":
            continue
        instant = parse_instant(record.observed_at)
        for measurement in record.measurements:
            key = (
                f"{record.location_reference}|{record.domain}|{measurement.quantity}"
            )
            buckets.setdefault(key, []).append(
                Reading(
                    instant=instant,
                    value=float(measurement.value),
                    unit=measurement.unit,
                    quality_status=record.quality_status,
                    source_reference=record.source_reference,
                )
            )
            meta.setdefault(
                key,
                (record.location_reference, record.domain, measurement.quantity, measurement.unit),
            )

    intervals = base_intervals or {}
    timelines: dict[str, SeriesTimeline] = {}
    for key in sorted(buckets):
        location, domain, quantity, unit = meta[key]
        phase_two_series = f"{location}|{domain}"
        timelines[key] = SeriesTimeline(
            key=key,
            location=location,
            domain=domain,
            quantity=quantity,
            unit=unit,
            readings=tuple(buckets[key]),
            base_interval_seconds=intervals.get(phase_two_series),
        )
    return timelines


def timelines_by_entity(
    timelines: Mapping[str, SeriesTimeline],
) -> dict[str, tuple[str, ...]]:
    """Measurement keys grouped by location, each sorted.

    The feature grid is per *location*, because a forecast is issued for a
    catchment, but each feature is read from one measurement key and no other.
    Grouping by location here and looking up per key in the pipeline is what makes
    "features for one station may not use another station's readings" a structural
    property rather than a filter that could be forgotten.
    """
    grouped: dict[str, list[str]] = {}
    for key in sorted(timelines):
        grouped.setdefault(timelines[key].location, []).append(key)
    return {location: tuple(keys) for location, keys in sorted(grouped.items())}


def entity_instants(timelines: Sequence[SeriesTimeline]) -> tuple[datetime, ...]:
    """Every distinct instant at which any of `timelines` has a reading.

    The origin grid for one entity. A feature row exists at each of these
    instants, because each is a moment at which *something* about the catchment
    was observed and a forecast could have been issued.
    """
    seen: set[datetime] = set()
    for timeline in timelines:
        for reading in timeline.readings:
            seen.add(reading.instant)
    return tuple(sorted(seen))


# --------------------------------------------------------------------------- #
# Cutoffs
# --------------------------------------------------------------------------- #


def resolve_cutoff(
    config: FeatureConfig,
    quantity: str,
    origin: datetime,
    base_interval_seconds: float | None,
    previous_instant: datetime | None = None,
) -> tuple[datetime, str, bool]:
    """`(cutoff, policy_applied, policy_was_downgraded)` for one origin.

    The third element is `True` when the cutoff could not be placed the way the
    configuration asked and something else was substituted — which happens only
    when the cadence is unknown. It says the *policy* was downgraded, not that the
    cadence is unknown: for a forcing the cadence is irrelevant to the cutoff, so
    the policy is applied as requested and the flag stays `False` however irregular
    the series is. A reader wanting the cadence itself should ask
    `feature_pipeline.resolve_cadence`, which is where it is established.

    The origin instant itself is always a permitted cutoff, so the returned
    datetime is never later than `origin` and never depends on any observation
    after it. A feature can therefore only ever be a function of the past by
    construction of this value.

    **The unknown-cadence fallback differs by cutoff class, and the difference is
    the whole point.** With no established step there is no "one step back" to go
    to, and guessing one — the usual answer being an hour — would be inventing a
    quantity out of a convention. So each class falls back to something already
    known rather than to a guess:

    * a *forcing* falls back to `origin`, which is conservative in the causal
      direction. Rainfall at the prediction instant is an observation, and a
      forcing is allowed to read it.
    * a *state* falls back to `previous_instant` — the newest reading strictly
      before the origin, supplied by the caller from the series itself. Falling
      back to `origin` here would be catastrophic rather than merely loose: a
      water-level rolling mean ending at `T` would then average the water level
      at `T`, which is the quantity being predicted. That is not a subtle
      imprecision; it is the answer, wearing a feature's name. The Phase 3
      leakage audit catches exactly this when a truncated series leaves the
      cadence unresolvable, which is how it was found.

    When there is no earlier reading either, the cutoff cannot be honoured at all,
    and `evaluate` refuses the feature outright rather than evaluating a window
    that would contain the prediction instant.
    """
    policy = config.cutoff_for(quantity)
    if policy == CUTOFF_AT_PREDICTION:
        return origin, CUTOFF_AT_PREDICTION, False
    if base_interval_seconds is None or base_interval_seconds <= 0:
        if policy == CUTOFF_ONE_STEP_BACK and previous_instant is not None:
            if previous_instant < origin:
                return previous_instant, CUTOFF_ONE_STEP_BACK, True
        # Undefined step: stay at the origin rather than assume one.
        return origin, CUTOFF_AT_PREDICTION, True
    return (
        origin - timedelta(seconds=base_interval_seconds),
        CUTOFF_ONE_STEP_BACK,
        False,
    )


# --------------------------------------------------------------------------- #
# The operations
# --------------------------------------------------------------------------- #


def op_lag(
    timeline: SeriesTimeline,
    origin: datetime,
    cutoff: datetime,
    lag_seconds: float,
) -> WindowResult:
    """The reading exactly `lag_seconds` before `origin`.

    A lag names a distance in time, so it is resolved by instant and not by row
    position. The `min(cutoff, origin - lag)` clamp is redundant for a well-formed
    configuration and is kept as a structural guarantee: even a misconfigured lag
    of zero cannot make this read the origin instant, which is the one reading a
    state-quantity feature must never see.

    Warm-up and missingness are distinguished here and only here, because this is
    the one operation where both are unambiguous: if the requested instant is
    before the series began, the cause is warm-up; if it is within the series but
    unoccupied, the cause is a missing source reading.
    """
    wanted = min(origin - timedelta(seconds=lag_seconds), cutoff)
    reading = timeline.value_at(wanted)
    if reading is not None:
        return WindowResult(
            value=reading.value,
            observations=1,
            expected=1,
            instants=(wanted,),
            cutoff=cutoff,
        )
    first = timeline.first_instant
    if first is not None and wanted < first:
        return _absent(
            CAUSE_WARMUP, observations=0, expected=1, cutoff=cutoff
        )
    return _absent(CAUSE_MISSING_SOURCE, observations=0, expected=1, cutoff=cutoff)


def op_change(
    timeline: SeriesTimeline, origin: datetime, cutoff: datetime, span_seconds: float
) -> WindowResult:
    """`value(cutoff) - value(cutoff - span)`.

    The most recent observed change. Both endpoints must carry the same unit: a
    difference across two units is not a small error, it is a number with no
    meaning, and this refuses rather than converting.

    Taking the difference rather than the ratio also cancels any vertical datum,
    which is why a `water_level_change_*` feature is comparable within one gauge
    even though two gauges' levels are not comparable at all.
    """
    endpoint = cutoff
    start = cutoff - timedelta(seconds=span_seconds)
    if timeline.first_instant is not None and endpoint < timeline.first_instant:
        return _absent(CAUSE_WARMUP, cutoff=cutoff)
    if timeline.first_instant is not None and start < timeline.first_instant:
        return _absent(CAUSE_WARMUP, cutoff=cutoff)

    later = timeline.value_at(endpoint)
    if later is None:
        return _absent(CAUSE_MISSING_SOURCE, cutoff=cutoff)
    earlier = timeline.value_at(start)
    if earlier is None:
        return _absent(CAUSE_MISSING_SOURCE, observations=1, expected=2, cutoff=cutoff)
    if later.unit != earlier.unit:
        return _absent(CAUSE_UNIT_MISMATCH, observations=2, expected=2, cutoff=cutoff)
    return WindowResult(
        value=later.value - earlier.value,
        observations=2,
        expected=2,
        instants=(start, endpoint),
        cutoff=cutoff,
    )


def op_accumulation(
    timeline: SeriesTimeline,
    origin: datetime,
    cutoff: datetime,
    window_seconds: float,
    min_coverage: float,
) -> WindowResult:
    """Total over `(cutoff - window, cutoff]`, subject to a coverage requirement.

    The window is **open on the left**. That is not a stylistic choice: a window
    of width `w` on a series sampled every `base` must contain exactly
    `w / base` readings, and `[T-w, T]` would contain one more. Closing the left
    end makes this operation agree with `pandas.Series.rolling(w)` slot for slot,
    which is what lets a Phase 3 window be cross-checked against the pre-Phase-1
    `features` layer — and it is what makes `expected_slots` the true count. With
    the wrong endpoint convention, a six-hour window with one hour missing holds
    seven slots of which six are occupied, and a full-coverage requirement passes
    on a window that has a hole in it.

    The coverage requirement is the point of this operation. A sum over a window
    with holes in it is *smaller than the truth* and still looks like a total, so
    the default requires every expected slot to be present. A partial window is
    reported as `insufficient`, never quietly summed.

    With no known cadence, coverage cannot be assessed at all — and an
    unassessable coverage requirement is treated as unmet, because "the data has
    no established cadence" is not evidence that the window was complete.
    """
    if not timeline.has_uniform_unit:
        return _absent(CAUSE_UNIT_MISMATCH, cutoff=cutoff)
    start = cutoff - timedelta(seconds=window_seconds)
    expected = timeline.expected_slots(window_seconds)
    readings = timeline.readings_in(start, cutoff, inclusive_start=False)
    count = len(readings)

    # Warm-up is decided by what the window actually holds, not by comparing the
    # window's edge against the series start. A boundary comparison looks simpler
    # and is wrong twice: it rejects a window that is already full when the series
    # began mid-window, and it reports `observations=0` for a window that plainly
    # holds readings. The shortfall test below is the same question asked the only
    # way it can be answered correctly — and it reuses the coverage machinery that
    # is the point of this operation.
    if expected is None:
        return _absent(CAUSE_INSUFFICIENT, observations=count, cutoff=cutoff)
    if count < expected * min_coverage:
        return _absent(
            _shortfall_reason(timeline, start, cutoff, count),
            observations=count,
            expected=expected,
            cutoff=cutoff,
        )
    return WindowResult(
        value=math.fsum(reading.value for reading in readings),
        observations=count,
        expected=expected,
        instants=tuple(reading.instant for reading in readings),
        cutoff=cutoff,
    )


def _shortfall_reason(
    timeline: SeriesTimeline,
    start: datetime,
    cutoff: datetime,
    count: int,
) -> str:
    """Warm-up, or a hole in the series?

    The two are kept apart because they call for different responses: warm-up is
    fixed by collecting more history, a hole is fixed by fixing the sensor or the
    gap policy. Reporting the first as the second sends an operator to debug a
    gauge that was working perfectly.

    Decided by asking whether the series had *started* when the window opened. If
    it had not, whatever is missing was never there to be counted. If it had, the
    readings are absent from a series that was running, and the cause is
    `missing_source`.

    A window reaching past the **end** of the series is not warm-up either, and
    this is the distinction worth being careful about. Warm-up is a statement about
    the beginning of a record; the end of a record is simply where the data stops,
    and a window that overruns it is short for the same reason any hole is. It also
    does not arise in a well-formed dataset: Phase 3 only builds a row at an origin
    instant where *some* series has a reading, so a target-bearing row always sits
    inside at least one series. The branch is still written down because a caller
    holding a partial series must not be told the history was too short when it was
    too long.
    """
    first = timeline.first_instant
    if first is not None and first > start:
        return CAUSE_WARMUP
    return CAUSE_MISSING_SOURCE


def op_intensity(
    timeline: SeriesTimeline,
    origin: datetime,
    cutoff: datetime,
    window_seconds: float,
    min_coverage: float,
    unit_is_understood: bool,
) -> WindowResult:
    """Mean rate over the window, in source units per hour.

    Refused outright when the source unit is not understood. The arithmetic would
    produce a number and the number would be meaningless: dividing an amount of
    unstated units by an hour yields a quantity whose units nobody can name, and a
    model will fit it as confidently as any other column.

    Dividing by the **nominal** window rather than the observed span is
    deliberate, and only sound because the coverage requirement above has already
    established that the window is complete. A rate taken over a partly empty
    window would be scaled by the fraction that was missing, which is exactly the
    error the coverage rule exists to prevent.
    """
    if not unit_is_understood:
        return _absent(CAUSE_UNDETERMINED_UNIT, cutoff=cutoff)
    accumulation = op_accumulation(
        timeline, origin, cutoff, window_seconds, min_coverage
    )
    if not accumulation.is_present:
        return accumulation
    hours = window_seconds / 3600.0
    return WindowResult(
        value=accumulation.value / hours,
        reason=None,
        observations=accumulation.observations,
        expected=accumulation.expected,
        instants=accumulation.instants,
        cutoff=cutoff,
    )


def _statistic(values: Sequence[float], statistic: str) -> float | None:
    if not values:
        return None
    if statistic == STAT_MEAN:
        return math.fsum(values) / len(values)
    if statistic == STAT_MIN:
        return min(values)
    if statistic == STAT_MAX:
        return max(values)
    if statistic == STAT_STD:
        if len(values) < 2:
            return None
        # Sample standard deviation: the *observed* spread of what was seen, not
        # an estimate of a population from one or two readings. Bessel-corrected,
        # so a two-point window gives the difference between the points rather
        # than zero.
        mean = math.fsum(values) / len(values)
        variance = math.fsum((value - mean) ** 2 for value in values) / (len(values) - 1)
        return math.sqrt(variance) if variance > 0 else 0.0
    raise FeatureTemporalError(f"unknown rolling statistic {statistic!r}")


def op_rolling(
    timeline: SeriesTimeline,
    origin: datetime,
    cutoff: datetime,
    window_seconds: float,
    statistic: str,
    min_coverage: float,
) -> WindowResult:
    """An order statistic over `[cutoff - window, cutoff]`.

    A rolling statistic is descriptive rather than integral, so a partly observed
    window still answers a real question — "what was the range of the levels we
    actually saw" — and `rolling_min_coverage` defaults to `0.0`. A mean over what
    was observed is a mean of what was observed, and the observation count is
    carried out so the report can show how thin it was.

    The window is open on the left, `(cutoff - window, cutoff]`, so it holds
    exactly `window / base` readings and agrees with `pandas.Series.rolling(w)`.
    See `op_accumulation` for why the endpoint convention is load-bearing rather
    than cosmetic.

    `std` is the exception: it is undefined from one reading, and reporting `0.0`
    would claim two identical readings when there is only one.
    """
    if not timeline.has_uniform_unit:
        return _absent(CAUSE_UNIT_MISMATCH, cutoff=cutoff)
    start = cutoff - timedelta(seconds=window_seconds)
    expected = timeline.expected_slots(window_seconds)
    readings = timeline.readings_in(start, cutoff, inclusive_start=False)
    count = len(readings)
    if count == 0:
        # Nothing in the window at all. Which cause that is depends on whether the
        # series had started; see `_shortfall_reason`.
        return _absent(
            _shortfall_reason(timeline, start, cutoff, 0),
            observations=0,
            expected=expected,
            cutoff=cutoff,
        )
    if expected is None:
        # Cadence unknown: a statistic is still computable, but coverage cannot be
        # confirmed, so a caller demanding full coverage gets nothing.
        if min_coverage > 0:
            return _absent(CAUSE_INSUFFICIENT, observations=count, cutoff=cutoff)
    elif count < expected * min_coverage:
        return _absent(
            _shortfall_reason(timeline, start, cutoff, count),
            observations=count,
            expected=expected,
            cutoff=cutoff,
        )

    if statistic in STATISTICS_NEEDING_TWO and count < 2:
        return _absent(CAUSE_INSUFFICIENT, observations=count, expected=expected, cutoff=cutoff)

    value = _statistic([reading.value for reading in readings], statistic)
    if value is None:  # pragma: no cover - guarded above
        return _absent(CAUSE_INSUFFICIENT, observations=count, expected=expected, cutoff=cutoff)
    return WindowResult(
        value=value,
        observations=count,
        expected=expected,
        instants=tuple(reading.instant for reading in readings),
        cutoff=cutoff,
    )


def op_target(
    timeline: SeriesTimeline,
    origin: datetime,
    horizon_seconds: float,
    alignment: str,
    tolerance_seconds: float | None,
) -> WindowResult:
    """The quantity at `origin + horizon` — the thing being predicted.

    `TARGET_EXACT` requires a reading at precisely that instant. On a regular
    cadence that is free; on an irregular one it means some rows have no target,
    which is the truth, since at an irregular instant there is no observation to
    predict.

    `TARGET_AT_OR_BEFORE` takes the newest reading at or before the horizon
    within an explicit tolerance, and reports the shortfall it accepted by leaving
    `observations=1, expected=2` — a visible mismatch rather than a target that
    quietly means something other than what its column says.

    A target is the one result here whose value is *later* than the origin, and
    that is the definition of what a target is. It is deliberately never returned
    from any operation the pipeline places in the feature matrix.
    """
    horizon_instant = origin + timedelta(seconds=horizon_seconds)
    if alignment == TARGET_EXACT:
        reading = timeline.value_at(horizon_instant)
        if reading is None:
            return _absent(
                CAUSE_MISSING_SOURCE, expected=1, cutoff=horizon_instant
            )
        return WindowResult(
            value=reading.value,
            observations=1,
            expected=1,
            instants=(horizon_instant,),
            cutoff=horizon_instant,
        )

    if alignment != TARGET_AT_OR_BEFORE:  # pragma: no cover - validated in config
        raise FeatureTemporalError(f"unknown target alignment {alignment!r}")
    if tolerance_seconds is None or tolerance_seconds <= 0:
        raise FeatureTemporalError(
            "target alignment 'at_or_before' requires a positive tolerance"
        )
    earliest = horizon_instant - timedelta(seconds=tolerance_seconds)
    reading = timeline.latest_at_or_before(horizon_instant)
    if reading is None or reading.instant < earliest:
        return _absent(CAUSE_MISSING_SOURCE, expected=1, cutoff=horizon_instant)
    exact = reading.instant == horizon_instant
    return WindowResult(
        value=reading.value,
        observations=1,
        expected=1 if exact else 2,
        instants=(reading.instant,),
        cutoff=horizon_instant,
    )


def op_calendar(definition: Any, origin: datetime) -> WindowResult:
    """`sin` or `cos` of a cyclic component of the prediction instant.

    A function of the timestamp alone, so it cannot encode an observation. That is
    worth stating rather than assuming: a calendar term has *nowhere else* to get
    information from, which is why it is classified as safe by construction rather
    than by test.

    The encoding is cyclic so that hour 23 and hour 0 are neighbours rather than
    opposites — on a raw integer they are the two extremes of the range, and a
    linear model reads that as "as far apart as possible".

    `doy` is 1-based, matching `datetime.timetuple().tm_yday` and the pre-Phase-1
    `features` layer's `pandas.Series.dt.dayofyear`. The two agree because both
    are 1-based, not in spite of it: with a 365.25-day period the choice of origin
    is a small rotation, but two layers that disagree by one rotation would make
    cross-checking them pointless.

    The prediction instant itself is the cutoff, which is trivially correct for a
    feature that is a function of that instant: reading the clock is not peeking at
    the future.
    """
    from .feature_registry import (
        CALENDAR_PERIODS,
        CAL_HOUR,
        ENCODING_COS,
        ENCODING_SIN,
    )

    component = definition.quantity
    encoding = definition.statistic
    if component not in CALENDAR_PERIODS or encoding not in (ENCODING_SIN, ENCODING_COS):
        raise FeatureTemporalError(
            f"calendar feature {definition.name!r} declares component {component!r} and encoding "
            f"{encoding!r}, which are not a supported pair"
        )
    period = CALENDAR_PERIODS[component]
    position = float(origin.hour) if component == CAL_HOUR else float(origin.timetuple().tm_yday)
    angle = 2.0 * math.pi * position / period
    value = math.sin(angle) if encoding == ENCODING_SIN else math.cos(angle)
    return WindowResult(
        value=value,
        observations=1,
        expected=1,
        instants=(origin,),
        cutoff=origin,
    )


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #


def evaluate(
    definition: Any,
    timeline: SeriesTimeline | None,
    origin: datetime,
    config: FeatureConfig,
    *,
    unit_is_understood: bool,
) -> WindowResult:
    """Run the operation `definition` calls for, at `origin`, on `timeline`.

    One dispatch point, so there is no chance of a feature being computed by a
    different path than its registry entry describes.

    `timeline` is `None` only for `OP_CALENDAR`, which reads the timestamp rather
    than a series. Requiring it to be `None` there — rather than quietly ignoring
    whatever was passed — means a bug that handed a calendar feature a series can
    be detected rather than papered over.
    """
    if definition.operation == OP_CALENDAR:
        if timeline is not None:
            raise FeatureTemporalError(
                f"calendar feature {definition.name!r} was handed a series timeline; a calendar "
                "term is a function of the timestamp and must be evaluated without one"
            )
        return op_calendar(definition, origin)
    if timeline is None:  # pragma: no cover - guarded by every caller
        raise FeatureTemporalError(
            f"feature {definition.name!r} has operation {definition.operation!r} and needs a "
            "series timeline, but none was supplied"
        )

    # The newest reading strictly before the origin. Asked a microsecond early
    # because `latest_at_or_before` is inclusive, and the reading at the origin is
    # exactly the one a state cutoff must not use. Only consulted when the cadence
    # is unresolvable, but cheap enough to always compute, and having it here is
    # what stops `resolve_cutoff` from falling back to the origin for a state
    # quantity. See that function for why that fallback is not acceptable.
    earlier = timeline.latest_at_or_before(origin - timedelta(microseconds=1))
    requested = config.cutoff_for(definition.source_quantity)
    cutoff, _policy, cadence_unknown = resolve_cutoff(
        config,
        definition.source_quantity,
        origin,
        timeline.base_interval_seconds,
        None if earlier is None else earlier.instant,
    )
    if requested == CUTOFF_ONE_STEP_BACK and cadence_unknown and earlier is None:
        # A one-step-back cutoff that cannot be placed, on a series with nothing
        # before the origin. Evaluating anyway would put the prediction instant
        # itself inside the window — the water level at `T` inside a feature that
        # claims to summarize the six hours *before* `T`. There is no correct
        # value here, only a wrong one, so the feature is absent and says why.
        return _absent(CAUSE_CUTOFF_UNDEFINED, cutoff=origin)
    window = definition.window_seconds

    if definition.operation == OP_ROLLING:
        return op_rolling(
            timeline,
            origin,
            cutoff,
            window,
            definition.statistic,
            config.rolling_min_coverage,
        )
    if definition.operation == OP_ACCUMULATION:
        return op_accumulation(
            timeline, origin, cutoff, window, config.accumulation_min_coverage
        )
    if definition.operation == OP_INTENSITY:
        return op_intensity(
            timeline,
            origin,
            cutoff,
            window,
            config.accumulation_min_coverage,
            unit_is_understood,
        )
    if definition.operation == OP_CHANGE:
        return op_change(timeline, origin, cutoff, window)
    if definition.operation == OP_LAG:
        return op_lag(timeline, origin, cutoff, window)
    raise FeatureTemporalError(
        f"definition {definition.name!r} has operation {definition.operation!r}, which has no "
        "window evaluation. Calendar and static features are computed from the timestamp, "
        "not from observations."
    )


__all__ = [
    "ABSENT",
    "ABSENT_CAUSES",
    "CAUSE_INSUFFICIENT",
    "CAUSE_MISSING_SOURCE",
    "CAUSE_NO_SOURCE",
    "CAUSE_CUTOFF_UNDEFINED",
    "CAUSE_NOT_APPLICABLE",
    "CAUSE_UNDETERMINED_UNIT",
    "CAUSE_UNIT_MISMATCH",
    "CAUSE_WARMUP",
    "FeatureTemporalError",
    "Reading",
    "SeriesTimeline",
    "WindowResult",
    "build_timelines",
    "entity_instants",
    "evaluate",
    "op_accumulation",
    "op_calendar",
    "op_change",
    "op_intensity",
    "op_lag",
    "op_rolling",
    "op_target",
    "resolve_cutoff",
    "split_measurement_key",
    "timelines_by_entity",
]
