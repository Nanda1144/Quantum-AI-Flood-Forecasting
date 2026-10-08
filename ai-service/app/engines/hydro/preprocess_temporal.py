# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 2 — timestamps, ordering, resampling, splitting and leakage checks.

The canonical representation
----------------------------
Every instant in this module becomes **UTC ISO-8601 with a trailing `Z`** — the
same string `domains.to_instant_iso` produces and the same form an
`Observation.observed_at` accepts. There is exactly one canonical form, so two
records compare with `==` instead of with a normalisation step somebody might
forget.

Timezone policy is never implicit
---------------------------------
`domains.parse_instant` already **refuses** a naive timestamp, and that refusal is
the right default; this module keeps it. The three policies in
`preprocess_config` differ only in how a naive value may be *resolved*, and
resolving one always counts it in `TimestampNormalizationReport.assumed_timezone`:

* `require_explicit` (default) — refuse. A naive timestamp is evidence that
  nobody recorded the zone, not evidence of UTC.
* `source_declared` — apply the offset the supplier's data dictionary states.
* `assume_utc` — apply UTC because the caller asked. Counted, reported, and
  never the default.

Resampling is right-labelled, and that is a causality guarantee
-------------------------------------------------------------
Collapsing an hourly series into daily bins has one subtlety that decides
whether the output is usable for forecasting at all. If a bin is labelled with
its **start** (`2024-01-01T00:00Z` holding the whole of 1 January), then a row
dated 00:00 carries information from 23:00 — a reading that did not exist when
that row's timestamp said it did.

So every bin this module emits is labelled with its **last contributing
instant**. A row dated `2024-01-01T23:00Z` aggregates 00:00–23:00 and therefore
depends on nothing later than itself. There is no "left-labelled" option: it is
the one labelling that is wrong, and offering it as a config flag would only make
it reachable.

Splitting
---------
Both strategies are chronological and neither shuffles:

* `global` (default) — boundaries chosen on absolute time so every entity shares
  them. Strongest guarantee: entity A cannot be in `train` for January while
  entity B is in `test` for the same January.
* `per_entity` — each entity split on its own row proportions. Legitimate for
  genuinely independent catchments, and `SplitReport.cross_entity_time_overlap`
  says out loud when one entity's test period overlaps another's training period.

An entity that cannot be given three non-empty periods is **reported and then
handled by policy** (`error`, or `report_and_drop`) — never silently discarded,
and never given a quietly-relaxed boundary.

Pure standard library. Phase 1 supplies `Observation`, `Measurement`,
`parse_instant`, `to_instant_iso` and `provenance.SplitBoundaries`; this module
adds no schema and no provenance system of its own.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from .domains import (
    QUALITY_MISSING,
    Measurement,
    Observation,
    SchemaError,
    parse_instant,
    to_instant_iso,
)
from .preprocess_config import (
    AGG_COUNT,
    AGG_FIRST,
    AGG_LAST,
    AGG_MAX,
    AGG_MEAN,
    AGG_MIN,
    AGG_SUM,
    INSUFFICIENT_ERROR,
    INSUFFICIENT_REPORT_AND_DROP,
    MIN_ROWS_PER_ENTITY,
    MISSING_BACKWARD_FILL,
    MISSING_DROP,
    MISSING_FORWARD_FILL,
    MISSING_LINEAR_BIDIRECTIONAL,
    MISSING_LINEAR_CAUSAL,
    MISSING_REJECT,
    MISSING_RETAIN,
    SPLIT_GLOBAL,
    SPLIT_PER_ENTITY,
    TIMEZONE_ASSUME_UTC,
    TIMEZONE_REQUIRE_EXPLICIT,
    TIMEZONE_SOURCE_DECLARED,
    AggregationRule,
    PreprocessConfig,
    PreprocessConfigError,
)
from .provenance import SplitBoundaries

# --------------------------------------------------------------------------- #
# Construction bounds
# --------------------------------------------------------------------------- #
#
# Safety limits on grid construction, deliberately not user-configurable: they
# stop a runaway allocation, and a caller who genuinely needs a denser grid than
# these allow should say so in a review rather than by widening a bound that
# every other caller silently depends on.

#: The largest number of slots a grid may contain, whatever the interval. Guards
#: `build_grid` directly, so a caller-supplied interval cannot allocate without
#: limit either.
MAX_GRID_SLOTS = 5_000_000

#: How far grid inference may expand a series relative to its record count before
#: the series is called irregular. 500x admits heavy dropout (a station reporting
#: once per 500 hours is still regular) while keeping a single near-duplicate
#: pair from inferring a microsecond cadence.
MAX_GRID_EXPANSION = 500

#: Floor for the expansion limit, so a very short series is not refused for being
#: short rather than for being irregular.
MIN_GRID_SLOTS = 64

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class TemporalError(ValueError):
    """Raised when a temporal operation cannot be performed honestly.

    Covers an unparseable instant, an irregular frequency, a resample with no
    aggregation rule, and a split that cannot be made without overlapping
    periods. Never raised for something a report could honestly describe instead.
    """


# --------------------------------------------------------------------------- #
# Timestamp normalisation
# --------------------------------------------------------------------------- #

#: How a timezone was established for one instant. Recorded per timestamp so
#: `assumed` is distinguishable from `explicit` at a glance.
TZ_EXPLICIT = "explicit"
TZ_DECLARED = "declared"
TZ_ASSUMED_UTC = "assumed_utc"


@dataclass(frozen=True)
class NormalizedInstant:
    """One timestamp, canonicalised, with its provenance intact."""

    original: str
    normalized: str
    timezone_policy: str
    timezone_source: str
    offset_applied: str | None = None
    assumed: bool = False

    @property
    def instant(self) -> datetime:
        """The parsed UTC instant."""
        return parse_instant(self.normalized)

    @property
    def was_naive(self) -> bool:
        """True when the source string carried no UTC offset.

        "Naive" describes the *source* string, so an explicit offset that merely
        differed from UTC does not make a timestamp naive. Only a value this
        module had to attach a zone to is naive.
        """
        return self.assumed or self.timezone_source != TZ_EXPLICIT

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_timestamp": self.original,
            "normalized_timestamp": self.normalized,
            "timezone_policy": self.timezone_policy,
            "timezone_source": self.timezone_source,
            "offset_applied": self.offset_applied,
            "assumed_timezone": self.assumed,
        }


def _parse_offset(text: str) -> timezone:
    """Turn `'+05:30'`, `'Z'`, `'-08:00'` or `'UTC'` into a `tzinfo`.

    Fixed offsets only. A named zone such as `Asia/Kolkata` would require a
    timezone database, which this module deliberately does not depend on — and a
    dependency that is present on a developer's machine and absent in a container
    is a reproducibility bug, not a convenience.
    """
    candidate = text.strip()
    if candidate.upper() in ("Z", "UTC", "GMT"):
        return timezone.utc
    if candidate.upper().startswith("UTC"):
        candidate = candidate[3:].strip() or "+00:00"
    body = candidate
    sign = 1
    if body[:1] in "+-":
        sign = -1 if body[0] == "-" else 1
        body = body[1:]
    body = body.replace(":", "")
    if not body.isdigit() or len(body) not in (2, 4, 6):
        raise PreprocessConfigError(
            f"source_timezone {text!r} is not a UTC offset like '+05:30'; named zones such as "
            "'Asia/Kolkata' need a timezone database, which this module does not depend on"
        )
    # Digits are HH, HHMM or HHMMSS depending on length. Decoding all three with
    # one fixed formula silently reads "+05:30" as five *minutes* thirty
    # seconds, which shifts a whole series by five and a half hours.
    if len(body) == 2:
        hours, minutes, seconds = int(body), 0, 0
    elif len(body) == 4:
        hours, minutes, seconds = int(body[:2]), int(body[2:]), 0
    else:
        hours, minutes, seconds = int(body[:2]), int(body[2:4]), int(body[4:6])
    delta = sign * timedelta(hours=hours, minutes=minutes, seconds=seconds)
    if not timedelta(hours=-26) < delta < timedelta(hours=26):
        raise PreprocessConfigError(f"source_timezone {text!r} is out of range: {delta}")
    return timezone(delta)


def _as_naive(text: str) -> datetime:
    """Parse a naive ISO-8601 string, tolerating a trailing `Z` on a naive body.

    `datetime.fromisoformat` on Python < 3.11 rejects a `Z` suffix outright, so the
    character is stripped rather than assumed absent. That is safe *here* because
    this function is only reached for input `domains.parse_instant` has already
    established is naive.
    """
    body = text[:-1] if text[-1:] in ("Z", "z") else text
    try:
        parsed = datetime.fromisoformat(body)
    except ValueError as exc:
        raise TemporalError(f"timestamp {text!r} is not a parseable ISO-8601 instant") from exc
    return parsed.replace(tzinfo=None)


def normalize_timestamp(value: str, config: PreprocessConfig) -> NormalizedInstant:
    """Canonicalise one timestamp string to UTC ISO-8601.

    Raises `TemporalError` for an unparseable value, and for a naive value under
    `require_explicit`. Neither is repaired: a rejected timestamp is reported by
    index so the caller knows which source row to fix.
    """
    if not isinstance(value, str) or not value.strip():
        raise TemporalError(f"timestamp must be a non-empty string, got {value!r}")
    original = value.strip()

    try:
        parsed = parse_instant(original)
    except SchemaError as exc:
        if "has no UTC offset" not in str(exc):
            raise TemporalError(
                f"timestamp {original!r} is not a parseable ISO-8601 instant"
            ) from exc
        return _resolve_naive(original, config)

    return NormalizedInstant(
        original=original,
        normalized=to_instant_iso(parsed),
        timezone_policy=config.timezone_policy,
        timezone_source=TZ_EXPLICIT,
        offset_applied=_offset_text(parsed),
        assumed=False,
    )


def _resolve_naive(original: str, config: PreprocessConfig) -> NormalizedInstant:
    """Apply the configured policy to a timestamp that carries no offset."""
    if config.timezone_policy == TIMEZONE_REQUIRE_EXPLICIT:
        raise TemporalError(
            f"timestamp {original!r} carries no UTC offset and timezone_policy is "
            f"{TIMEZONE_REQUIRE_EXPLICIT!r}; supply an explicit zone, or configure "
            "timezone_policy='source_declared' with a source_timezone taken from the supplier's "
            "data dictionary, or 'assume_utc' if UTC is genuinely correct. A naive timestamp is "
            "refused rather than assumed to be UTC, because a wrong assumption shifts the whole "
            "series while every downstream boundary still looks self-consistent."
        )

    if config.timezone_policy == TIMEZONE_SOURCE_DECLARED:
        zone = _parse_offset(config.source_timezone or "")
        moment = _as_naive(original).replace(tzinfo=zone)
        return NormalizedInstant(
            original=original,
            normalized=to_instant_iso(moment),
            timezone_policy=TIMEZONE_SOURCE_DECLARED,
            timezone_source=f"{TZ_DECLARED}:{config.source_timezone}",
            offset_applied=config.source_timezone,
            assumed=False,
        )

    moment = _as_naive(original).replace(tzinfo=timezone.utc)
    return NormalizedInstant(
        original=original,
        normalized=to_instant_iso(moment),
        timezone_policy=TIMEZONE_ASSUME_UTC,
        timezone_source=TZ_ASSUMED_UTC,
        offset_applied="+00:00",
        assumed=True,
    )


def _offset_text(moment: datetime) -> str:
    offset = moment.utcoffset()
    if offset is None:  # pragma: no cover - parse_instant guarantees an offset
        return ""
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"


@dataclass
class TimestampNormalizationReport:
    """How many instants were canonicalised, and how many zones were assumed."""

    #: How many changed-timestamp examples to keep. Enough to audit the
    #: transformation, few enough that a million-row ingest does not build a
    #: million-row report.
    #:
    #: Selection is *by content*, not by arrival: the retained examples are the
    #: `EXAMPLE_LIMIT` smallest under `_example_key`. Keeping the first N seen
    #: would make the report a function of the caller's row order.
    EXAMPLE_LIMIT = 5

    considered: int = 0
    #: Records whose timestamp text was actually rewritten. The complement of
    #: `already_canonical`, and with it a partition of `considered`.
    normalized: int = 0
    already_canonical: int = 0
    assumed_timezone: int = 0
    declared_timezone: int = 0
    explicit_offset: int = 0
    sources: dict[str, int] = field(default_factory=dict)
    examples: list[dict[str, str]] = field(default_factory=list)
    #: Rejections, as `(index, message)`.
    rejected: list[tuple[int, str]] = field(default_factory=list)

    @staticmethod
    def _example_key(example: dict[str, str]) -> tuple[str, str, str]:
        """Total order on examples, so selection does not depend on arrival."""
        return (
            example["normalized_timestamp"],
            example["original_timestamp"],
            example["timezone_source"],
        )

    def record(self, result: NormalizedInstant) -> None:
        self.considered += 1
        if result.normalized == result.original:
            self.already_canonical += 1
        else:
            self.normalized += 1
            self._offer_example(
                {
                    "original_timestamp": result.original,
                    "normalized_timestamp": result.normalized,
                    "timezone_source": result.timezone_source,
                }
            )
        self.sources[result.timezone_source] = self.sources.get(result.timezone_source, 0) + 1
        if result.assumed:
            self.assumed_timezone += 1
        elif result.timezone_source != TZ_EXPLICIT:
            self.declared_timezone += 1
        else:
            self.explicit_offset += 1

    def record_rejection(self, index: int, message: str) -> None:
        self.considered += 1
        self.rejected.append((index, message))

    @property
    def all_explicit(self) -> bool:
        """True when no instant relied on an assumed or a declared zone.

        The flag a reviewer wants: *did any timestamp in this dataset get its
        timezone from a human decision rather than from the source?*
        """
        return self.assumed_timezone == 0 and self.declared_timezone == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "normalized": self.normalized,
            "already_canonical": self.already_canonical,
            "assumed_timezone": self.assumed_timezone,
            "declared_timezone": self.declared_timezone,
            "explicit_offset": self.explicit_offset,
            "all_explicit": self.all_explicit,
            "timezone_sources": dict(sorted(self.sources.items())),
            "examples": list(self.finalise()),
            "rejected": [{"index": index, "error": message} for index, message in self.rejected],
        }

    def _offer_example(self, example: dict[str, str]) -> None:
        """Retain `example` if it belongs among the smallest few seen so far.

        Bounded at `EXAMPLE_LIMIT` without ever keeping every candidate, and
        independent of arrival order: after any prefix of the input the retained
        set is the `EXAMPLE_LIMIT` smallest of that prefix, so after the whole
        input it is the `EXAMPLE_LIMIT` smallest of the batch. Two runs over the
        same records in any order therefore retain the same examples.
        """
        if len(self.examples) < self.EXAMPLE_LIMIT:
            self.examples.append(example)
            return
        worst = max(range(len(self.examples)), key=lambda i: self._example_key(self.examples[i]))
        if self._example_key(example) < self._example_key(self.examples[worst]):
            self.examples[worst] = example

    def finalise(self) -> list[dict[str, str]]:
        """Order the retained examples by content and return them.

        `record()` keeps the smallest few by `_example_key`, so the *set* is
        already order-independent; this only puts it in ascending order, which
        `to_dict()`, `describe()` and a direct reader all need.

        Sorting rather than sorting-at-insert-time is what keeps `record()` a
        single pass: an ascending insert would be O(n) per example.
        """
        self.examples.sort(key=self._example_key)
        return self.examples

    def describe(self) -> str:
        lines = [
            f"TIMESTAMPS considered={self.considered} rewritten={self.normalized} "
            f"already_canonical={self.already_canonical} "
            f"explicit={self.explicit_offset} declared={self.declared_timezone} "
            f"assumed={self.assumed_timezone} rejected={len(self.rejected)}"
        ]
        lines.extend(
            f"    {item['original_timestamp']} -> {item['normalized_timestamp']}"
            f"  [{item['timezone_source']}]"
            for item in self.finalise()
        )
        lines.extend(f"    REJECTED row {index}: {message}" for index, message in self.rejected)
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #


def entity_key(observation: Observation) -> str:
    """The reporting entity a record belongs to: its location reference.

    The grouping key for **ordering and splitting** — "which gauge produced
    this?" Phase 1 already requires `location_reference` on every observation
    (`domains.Observation.__post_init__` refuses a blank one), so this can never
    be empty and a series can never be silently ungrouped.

    Deliberately *not* enough on its own for time-series work; see
    `series_key`.
    """
    return observation.location_reference


def series_key(observation: Observation) -> str:
    """One univariate series: a location *and* a domain, e.g. `S1|water_level`.

    The grouping key for everything that treats records as a time series:
    interval inference, grid construction, resampling and gap handling. It is a
    separate concept from `entity_key` because Phase 1 enforces a 1:1 mapping
    between domain and quantity (`domains.Observation.__post_init__` refuses a
    `water_level` observation carrying `rainfall`), so one station is really
    several independent series.

    Conflating them is not a cosmetic problem. A station reporting water level,
    inflow and rainfall each hour produces three records at the same instant;
    grouped by station alone, the deltas between consecutive records are
    `0s, 3600s, 0s, 3600s`, so no sampling interval can be inferred, no grid can
    be built, no gap can be located, and the missing-value stage quietly does
    nothing. Grouped by series, each of the three has a clean 3600s cadence and
    the real work happens.

    Splitting stays at station level on purpose: a station going offline takes
    all of its variables with it, so the validation window should be the same
    calendar window across them rather than three unrelated fractions.
    """
    return f"{observation.location_reference}|{observation.domain}"


def describe_series(series: str) -> str:
    """A series key rendered for humans, for report lines and error messages."""
    location, _, domain = series.partition("|")
    return f"{location} [{domain}]"


def record_order(record: Observation) -> tuple[Any, ...]:
    """A total order for records that share an entity and an instant.

    Without this, two records for one instant have no defined relative order and
    the output is "deterministic" only in the sense that the same input always
    happens to come out the same way. With it, the order depends only on the
    contents of the records, which is the property the phase-2 determinism tests
    actually assert.

    The instant is the parsed `datetime`, not the stored `observed_at` string.
    Phase 1 deliberately keeps the *original* offset in `observed_at` (see
    `domains.to_instant_iso`), so `2024-01-01T05:30:00+05:30` and
    `2024-01-01T00:00:00Z` are the same instant written two ways, and comparing
    them as strings would order one station's records wrongly.

    The trailing components are what make the order *total*. Keying only on
    (instant, domain, source, provenance) leaves two readings of the same instant
    from the same source comparing equal, and Python's stable sort then leaves
    them in whatever order the batch arrived in -- so the output would depend on
    how the caller happened to list its rows. Two records that agree on every
    component here carry identical values and are genuinely interchangeable, so
    nothing is left undecided and no `sort` is left to input order.
    """
    return (
        record.instant,
        record.domain,
        record.source_reference or "",
        record.provenance_reference or "",
        record.observed_at,
        tuple(
            (item.quantity, str(item.unit), str(item.value))
            for item in record.measurements
        ),
        record.dataset_reference or "",
    )


def canonical_record(record: Observation) -> Observation:
    """A copy of `record` whose `observed_at` is canonical UTC ISO-8601.

    Phase 1 stores the timestamp exactly as the source wrote it, which is the
    right call for provenance. It does mean two records for the same instant can
    hold different strings, so ordering and splitting on the raw string is
    unsound. This function is where Phase 2 pays that debt: it rewrites
    `observed_at` to the single canonical form and records what the source
    actually said in `notes`, so nothing is lost.

    A record whose `observed_at` is already canonical is returned unchanged, so
    this is cheap to call unconditionally.
    """
    canonical = to_instant_iso(record.instant)
    if canonical == record.observed_at:
        return record
    return replace(
        record,
        observed_at=canonical,
        notes=(
            f"{record.notes} | Phase 2 timestamp normalisation: source wrote "
            f"{record.observed_at!r}, canonical UTC form is {canonical!r}"
        ).strip(" |"),
    )


def sort_records(records: Sequence[Observation]) -> tuple[list[Observation], dict[str, Any]]:
    """Order records by `(entity, instant, …)`, deterministically.

    Two-level sort: entity first, then instant. A *global* sort by instant alone
    would interleave every station into one scrambled series, and the resulting
    frame looks ordered while no individual gauge is — which is worse than an
    obviously unsorted frame, because the mistake survives a visual check.
    """
    ordered = sorted(records, key=lambda item: (entity_key(item), *record_order(item)))
    detail: dict[str, Any] = {
        "entities": len({entity_key(item) for item in ordered}),
        "records": len(ordered),
        "grouped_by": ["entity", "instant"],
    }
    return ordered, detail


def assert_monotonic(records: Sequence[Observation]) -> None:
    """Raise unless each entity's instants are non-decreasing.

    Non-decreasing rather than strictly increasing, because two records for one
    instant are a duplicate/conflict question for the duplicate stage, not an
    ordering error. Ordering must not pre-empt that decision.
    """
    seen: dict[str, datetime] = {}
    for record in records:
        entity = entity_key(record)
        moment = record.instant
        previous = seen.get(entity)
        if previous is not None and moment < previous:
            raise TemporalError(
                f"records for entity {entity!r} are not in chronological order: "
                f"{to_instant_iso(moment)} follows {to_instant_iso(previous)}"
            )
        seen[entity] = moment


# --------------------------------------------------------------------------- #
# Duration / frequency parsing
# --------------------------------------------------------------------------- #

_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}

#: Long spellings accepted alongside the short ones. Checked before the short
#: table so that `parse_frequency("30min")` cannot be mis-read as 30 minutes times
#: something.
_LONG_UNITS = (
    ("sec", 1),
    ("secs", 1),
    ("second", 1),
    ("seconds", 1),
    ("min", 60),
    ("mins", 60),
    ("minute", 60),
    ("minutes", 60),
    ("hr", 3600),
    ("hrs", 3600),
    ("hour", 3600),
    ("hours", 3600),
    ("day", 86400),
    ("days", 86400),
    ("week", 604800),
    ("weeks", 604800),
)


@dataclass(frozen=True)
class Duration:
    """A positive, finite length of time in seconds."""

    seconds: float

    def __post_init__(self) -> None:
        if isinstance(self.seconds, bool) or not isinstance(self.seconds, (int, float)):
            raise TemporalError(f"Duration.seconds must be a number, got {type(self.seconds).__name__}")
        if not math.isfinite(self.seconds) or self.seconds <= 0:
            raise TemporalError(
                f"Duration must be a positive finite number of seconds, got {self.seconds!r}"
            )

    @property
    def as_timedelta(self) -> timedelta:
        return timedelta(seconds=self.seconds)

    def describe(self) -> str:
        for label, size in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60)):
            if self.seconds % size == 0:
                return f"{int(self.seconds // size)}{label}"
        return f"{self.seconds:g}s"

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.describe()


def parse_frequency(frequency: str) -> Duration:
    """Parse `'1H'`, `'30min'`, `'1D'`, `'1w'`, `'90s'` into a `Duration`.

    Raises `TemporalError` for anything else. A resampling frequency that cannot
    be parsed is a refusal to aggregate, not a default of one hour. Calendar
    frequencies are refused explicitly: a month has no fixed length, so "one
    monthly bin" cannot be defined without inventing a calendar.
    """
    if not isinstance(frequency, str) or not frequency.strip():
        raise TemporalError(f"frequency must be a non-empty string, got {frequency!r}")
    text = frequency.strip().lower()
    split = 0
    while split < len(text) and (text[split].isdigit() or text[split] in ".+-"):
        split += 1
    number_text = text[:split].strip()
    # Tolerate a space between the count and the unit ("2 hours"), which is how
    # both pandas and most people write it.
    unit_text = text[split:].strip()
    if not number_text or number_text in ("+", "-", "."):
        raise TemporalError(
            f"frequency {frequency!r} has no count; write it as a number followed by a unit, "
            "e.g. '1H', '30min' or '1D'"
        )
    try:
        count = float(number_text)
    except ValueError as exc:  # pragma: no cover - guarded by the character scan
        raise TemporalError(f"frequency {frequency!r} has an unreadable count {number_text!r}") from exc
    if not math.isfinite(count) or count <= 0:
        raise TemporalError(f"frequency {frequency!r} must be a positive count, got {number_text!r}")

    for name, size in _LONG_UNITS:
        if unit_text == name:
            return Duration(count * size)
    if unit_text in _UNIT_SECONDS:
        return Duration(count * _UNIT_SECONDS[unit_text])
    raise TemporalError(
        f"frequency unit {unit_text!r} in {frequency!r} is not recognised; supported units are "
        f"{sorted(_UNIT_SECONDS)} and the spellings "
        f"{tuple(name for name, _ in _LONG_UNITS)}. A calendar frequency such as 'month' is not "
        "supported: it has no fixed length, so bin boundaries would have to be invented."
    )


def infer_interval(records: Sequence[Observation]) -> Duration | None:
    """The modal gap between consecutive instants, or `None` if irregular.

    Requires the modal gap to cover at least 90% of deltas, matching
    `preprocessing.infer_sampling_interval`. A series whose spacing is only mostly
    regular returns `None` so that resampling, which would invent slots, stays
    disabled, and so provenance keeps the "unknown" state instead of asserting a
    cadence the data does not support.

    NOTE: superseded by `infer_base_interval` below. Kept because
    `preprocessing.infer_sampling_interval` and this function are two
    implementations of one idea and the disagreement is worth being able to
    demonstrate rather than having lost.
    """
    deltas = _consecutive_deltas(records)
    if not deltas:
        return None
    counts: dict[float, int] = {}
    for delta in deltas:
        counts[delta] = counts.get(delta, 0) + 1
    modal = max(counts.items(), key=lambda item: (item[1], -item[0]))[0]
    if counts[modal] / len(deltas) < 0.9:
        return None
    return Duration(modal)


def infer_base_interval(records: Sequence[Observation]) -> Duration | None:
    """The base sampling interval, or `None` when one cannot be inferred safely.

    **The base interval is the smallest positive gap between consecutive
    observations**, not the most common one. For a regularly sampled series with
    dropout, which is the normal condition for a real gauge network, those two
    rules disagree and the modal one is the wrong choice: a single three-hour hole
    in an hourly series drops the mode below 90%, and the entire missing-value
    stage then silently does nothing on the data that most needs it. The
    `missing_before` count for a real dataset comes out as zero, the report says
    "policy applied, nothing to do", and a reader has no way to tell that the
    stage never ran.

    The smallest observed spacing is also the more honest answer: it is the
    tightest upper bound on the cadence that the observations actually support.
    A station that reports hourly but skipped once has an observed minimum
    spacing of one hour, which is its true cadence.

    The risk of taking a minimum is that one freak near-duplicate pair infers a
    grid far finer than the truth, so `MAX_GRID_EXPANSION` caps the implied slot
    count. A series needing more slots than that is reported as irregular and
    left at native resolution rather than expanded. `interval_regularity`
    publishes how consistent the spacing actually was, so how much to trust this
    inference is visible in the report instead of hidden in it.
    """
    deltas = _consecutive_deltas(records)
    if not deltas:
        return None
    smallest = min(deltas)
    if smallest <= 0:  # pragma: no cover - deltas are strictly positive
        return None
    span = records[-1].instant - records[0].instant
    implied = int(span.total_seconds() / smallest) + 1
    if implied > max(MAX_GRID_EXPANSION * len(deltas), MIN_GRID_SLOTS):
        return None
    return Duration(smallest)


def interval_regularity(records: Sequence[Observation], interval: Duration) -> float:
    """The fraction of consecutive gaps that are exactly one `interval`.

    `1.0` is perfectly regular. A lower value quantifies how much the inferred
    cadence is an inference: a series at `0.86` has real holes in it, which is
    precisely why the missing-value stage has something to report.
    """
    deltas = _consecutive_deltas(records)
    if not deltas:
        return 0.0
    matched = sum(1 for delta in deltas if delta == interval.seconds)
    return matched / len(deltas)


def _consecutive_deltas(records: Sequence[Observation]) -> list[float]:
    """Positive second-gaps between consecutive instants, per series.

    Zero-length gaps are dropped rather than counted: several domains share one
    station's instants, so a zero here means "a different variable at the same
    moment", not "two samples at the same moment". Counting them would drag any
    regularity ratio toward zero and mask real gaps.
    """
    per_series: dict[str, list[datetime]] = {}
    for record in records:
        per_series.setdefault(series_key(record), []).append(record.instant)
    deltas: list[float] = []
    for moments in per_series.values():
        ordered = sorted(moments)
        deltas.extend(
            (later - earlier).total_seconds()
            for earlier, later in zip(ordered, ordered[1:])
            if (later - earlier).total_seconds() > 0
        )
    return deltas


# --------------------------------------------------------------------------- #
# The regular grid
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SeriesSlot:
    """One instant on a regular grid, with whatever was observed there.

    An empty `observations` tuple is a **gap**, not a zero and not an
    interpolation. Keeping the distinction in the type is what lets the missing
    policy say "retain" and mean it. The dataclass is frozen: a filling policy
    returns a new slot rather than editing this one, so a grid handed to the
    policy is unchanged and a report can be trusted about what it received.
    """

    instant: str
    observations: tuple[Observation, ...] = ()

    @property
    def moment(self) -> datetime:
        return parse_instant(self.instant)

    @property
    def is_gap(self) -> bool:
        return not self.observations

    def values_for(self, quantity: str) -> tuple[float, ...]:
        """Every value of `quantity` at this slot, in record order."""
        return tuple(
            float(item.value)
            for record in self.observations
            for item in record.measurements
            if item.quantity == quantity
        )

    def has_quantity(self, quantity: str) -> bool:
        return any(
            item.quantity == quantity
            for record in self.observations
            for item in record.measurements
        )

    def units_for(self, quantity: str) -> frozenset[str]:
        """Every unit `quantity` is declared in at this slot."""
        return frozenset(
            item.unit
            for record in self.observations
            for item in record.measurements
            if item.quantity == quantity
        )

    def with_observations(self, observations: Sequence[Observation]) -> "SeriesSlot":
        """A copy carrying additional observations."""
        return replace(self, observations=tuple(observations))


def build_grid(
    records: Sequence[Observation],
    interval: Duration,
    *,
    series: str | None = None,
) -> list[SeriesSlot]:
    """Place records onto a regular grid, leaving genuine gaps empty.

    The grid runs from the earliest observed instant to the latest, and every
    intervening step is a slot whether or not anything was observed there.
    Building the grid is what makes a data gap *visible*; it never fills one.

    Refuses to build more than `MAX_GRID_SLOTS` slots. The guard is here rather
    than only in `infer_base_interval` because a caller may pass any interval,
    including one that is not a multiple of the true cadence, and an allocation
    that depends on the caller having inferred the interval carefully is not a
    guard.
    """
    selected = records if series is None else [r for r in records if series_key(r) == series]
    if not selected:
        return []
    buckets: dict[datetime, list[Observation]] = {}
    for record in selected:
        buckets.setdefault(record.instant, []).append(record)
    moments = sorted(buckets)
    step = interval.as_timedelta
    slots: list[SeriesSlot] = []
    cursor = moments[0]
    while cursor <= moments[-1]:
        if len(slots) >= MAX_GRID_SLOTS:
            raise TemporalError(
                f"a grid for {len(selected)} record(s) over interval {interval.describe()} would "
                f"exceed MAX_GRID_SLOTS={MAX_GRID_SLOTS}. The interval is too fine for this span, "
                "so the grid is refused rather than truncated: a partial grid would report gaps "
                "that are really a truncation."
            )
        found = tuple(sorted(buckets.get(cursor, ()), key=record_order))
        slots.append(SeriesSlot(instant=to_instant_iso(cursor), observations=found))
        cursor += step
    return slots


# --------------------------------------------------------------------------- #
# Resampling
# --------------------------------------------------------------------------- #


def resample_entity(
    slots: Sequence[SeriesSlot],
    frequency: str,
    rules: Sequence[AggregationRule],
    *,
    series: str,
    domain: str,
    dataset_type: str,
) -> list[Observation]:
    """Collapse a regular grid into coarser bins, one record per non-empty bin.

    Bins are **right-labelled**: a bin ending at `T` is stamped `T`, so its value
    depends on nothing later than `T`. See the module docstring for why that is
    not optional.

    Three refusals, all of them load-bearing:

    * A quantity with **no declared rule** raises. It is not averaged, summed or
      dropped. A rainfall intensity summed over an hour is a *depth*; the same
      intensity averaged over an hour is a different quantity wearing the same
      name. Nothing in this repository knows which a source meant.
    * An **empty bin produces no record**. A day with no rain is `0 mm`; a day
      with no *report* is not, and the difference is the whole reason a
      hydrological dataset is trustworthy.
    * **Mixed source units within a bin raise.** Averaging metres and centimetres
      without converting them first is arithmetic on two different quantities.
      Unit normalisation (`preprocess_units`) runs before this function.
    """
    step = parse_frequency(frequency)
    source_step = _grid_step(slots)
    if source_step is None:
        raise TemporalError(
            f"series {describe_series(series)!r} cannot be resampled: its instants are not on a regular grid, so "
            "bin boundaries are undefined. Supply a series with a declared cadence, or leave "
            "resample_frequency unset to keep the source resolution."
        )
    if step.seconds < source_step.seconds:
        raise TemporalError(
            f"cannot resample series {describe_series(series)!r} from every {source_step.describe()} to "
            f"{frequency!r}: the requested frequency is finer than the source data. Upsampling "
            "would have to invent values."
        )
    if step.seconds % source_step.seconds != 0:
        raise TemporalError(
            f"cannot resample series {describe_series(series)!r} from every {source_step.describe()} to "
            f"{frequency!r}: the requested frequency is not an exact multiple of the source "
            "cadence, so bins would not line up with the observations"
        )

    by_quantity = {rule.quantity: rule for rule in rules}
    if not by_quantity:
        raise TemporalError(
            f"no AggregationRule was declared for series {describe_series(series)!r}; resampling without an "
            "aggregation rule would have to guess one per quantity"
        )

    observed_quantities = {
        item.quantity
        for slot in slots
        for record in slot.observations
        for item in record.measurements
    }
    uncovered = sorted(observed_quantities - set(by_quantity))
    if uncovered:
        raise TemporalError(
            f"series {describe_series(series)!r} carries quantity/quantities {uncovered} with no AggregationRule; "
            f"rules cover {sorted(by_quantity)}. Declare a rule for every quantity before "
            "resampling, rather than having this module choose an aggregation."
        )

    produced: list[Observation] = []
    for group in _group_into_bins(slots, step.seconds):
        present = [slot for slot in group if not slot.is_gap]
        if not present:
            continue
        label = group[-1].instant
        template = present[0].observations[0]
        measurements: list[Measurement] = []
        for quantity in sorted(by_quantity):
            rule = by_quantity[quantity]
            values: list[float] = []
            for slot in present:
                values.extend(slot.values_for(quantity))
            if not values:
                continue
            unit = _resolve_bin_unit(group, quantity, rule)
            measurements.append(
                Measurement(quantity=quantity, value=_aggregate(values, rule.function), unit=unit)
            )
        produced.append(
            Observation(
                domain=domain,
                location_reference=template.location_reference,
                observed_at=label,
                measurements=tuple(measurements),
                measurement_window=template.measurement_window,
                source_reference=template.source_reference,
                provenance_reference=template.provenance_reference,
                dataset_reference=template.dataset_reference,
                dataset_type=dataset_type,
                notes=(
                    f"Phase 2 resample: {frequency} bin over {len(group)} source slot(s) of "
                    f"{source_step.describe()}, right-labelled so the value depends on nothing "
                    "later than this instant. Aggregations: "
                    + ", ".join(f"{rule.quantity}={rule.function}" for rule in sorted(by_quantity.values(), key=lambda r: r.quantity))
                ),
            )
        )
    return produced


def _grid_step(slots: Sequence[SeriesSlot]) -> Duration | None:
    """The spacing of an already-regular grid, or `None` if it is not regular."""
    if len(slots) < 2:
        return None
    deltas = {
        (later.moment - earlier.moment).total_seconds() for earlier, later in zip(slots, slots[1:])
    }
    if len(deltas) != 1:
        return None
    only = deltas.pop()
    return Duration(only) if only > 0 else None


def _group_into_bins(slots: Sequence[SeriesSlot], bin_seconds: float) -> list[list[SeriesSlot]]:
    """Chop a right-labelled grid into consecutive bins.

    Bin boundaries are aligned to the **source** grid rather than to an arbitrary
    epoch, so a bin is never half empty purely because the series happened to
    start mid-bin. The final bin may be short; it is emitted as it is, because
    padding it with invented earlier instants would be worse.
    """
    if not slots:
        return []
    step = _grid_step(slots)
    if step is None:  # pragma: no cover - callers verify regularity first
        raise TemporalError("cannot bin a non-regular grid")
    per_bin = int(round(bin_seconds / step.seconds))
    return [list(slots[i : i + per_bin]) for i in range(0, len(slots), per_bin)]


def _aggregate(values: Sequence[float], function: str) -> float:
    """Apply one aggregation function to an ordered list of values."""
    if function == AGG_COUNT:
        return float(len(values))
    if function == AGG_SUM:
        return float(math.fsum(values))
    if function == AGG_MEAN:
        return float(math.fsum(values) / len(values))
    if function == AGG_MIN:
        return float(min(values))
    if function == AGG_MAX:
        return float(max(values))
    if function == AGG_FIRST:
        return float(values[0])
    if function == AGG_LAST:
        return float(values[-1])
    raise TemporalError(  # pragma: no cover - AggregationRule validates the vocabulary
        f"unknown aggregation function {function!r}"
    )


def _resolve_bin_unit(group: Sequence[SeriesSlot], quantity: str, rule: AggregationRule) -> str:
    """The unit the aggregated result carries, refusing a mixed-unit bin.

    A bin holding both `m` and `cm` cannot be aggregated meaningfully at all, so
    this raises whether or not `rule.unit` was declared — declaring an output
    unit does not make summing two different units correct.
    """
    units: set[str] = set()
    for slot in group:
        units |= slot.units_for(quantity)
    if len(units) > 1:
        raise TemporalError(
            f"bin ending {group[-1].instant} mixes units {sorted(units)} for quantity "
            f"{quantity!r}; aggregating them without converting first would add different "
            "physical quantities. Run unit normalisation before resampling."
        )
    if rule.unit:
        return rule.unit
    if units:
        return units.pop()
    raise TemporalError(
        f"bin ending {group[-1].instant} has no unit for quantity {quantity!r}; a value without a "
        "unit cannot be compared, converted or audited. Declare the resulting unit on the "
        "AggregationRule."
    )


# --------------------------------------------------------------------------- #
# Splitting
# --------------------------------------------------------------------------- #


#: Key under which `per_entity` publishes the span of the whole dataset. Named so
#: that it cannot be read as a partition boundary — see `_apply_per_entity`.
_ENVELOPE_KEY = "all_entities_envelope"


@dataclass(frozen=True)
class EntitySplit:
    """One entity's contiguous train / validation / test records."""

    entity: str
    train: tuple[Observation, ...]
    validation: tuple[Observation, ...]
    test: tuple[Observation, ...]

    @property
    def sizes(self) -> dict[str, int]:
        return {"train": len(self.train), "validation": len(self.validation), "test": len(self.test)}

    def parts(self) -> tuple[tuple[Observation, ...], ...]:
        return (self.train, self.validation, self.test)

    def to_dict(self) -> dict[str, Any]:
        return {"entity": self.entity, **self.sizes}


@dataclass
class SplitReport:
    """Everything a reviewer needs to confirm the split was honest."""

    strategy: str
    config: PreprocessConfig
    per_entity: dict[str, EntitySplit] = field(default_factory=dict)
    boundaries: dict[str, SplitBoundaries] = field(default_factory=dict)
    #: Entities excluded because they could not be given three non-empty periods,
    #: mapped to the record count that excluded them.
    insufficient: dict[str, int] = field(default_factory=dict)
    #: Why each excluded entity was excluded.
    insufficient_reason: dict[str, str] = field(default_factory=dict)
    train: list[Observation] = field(default_factory=list)
    validation: list[Observation] = field(default_factory=list)
    test: list[Observation] = field(default_factory=list)
    leakage_findings: list[str] = field(default_factory=list)

    @property
    def sizes(self) -> dict[str, int]:
        return {
            "train": len(self.train),
            "validation": len(self.validation),
            "test": len(self.test),
            "excluded_entities": len(self.insufficient),
        }

    @property
    def cross_entity_time_overlap(self) -> list[str]:
        """Entity pairs whose periods are not separated on absolute time.

        Possible under `per_entity`, where entity A's test period can fall inside
        entity B's training period. `global` cannot produce this, which is
        exactly why `global` is the default.
        """
        findings: list[str] = []
        names = sorted(self.per_entity)
        for position, first in enumerate(names):
            for second in names[position + 1 :]:
                a, b = self.per_entity[first], self.per_entity[second]
                if _periods_overlap(a.test, b.train):
                    findings.append(f"{first}.test overlaps {second}.train")
                if _periods_overlap(b.test, a.train):
                    findings.append(f"{second}.test overlaps {first}.train")
        return findings

    @property
    def is_leak_free(self) -> bool:
        return not self.leakage_findings

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        boundaries: dict[str, Any] = {}
        for name, value in sorted(self.boundaries.items()):
            payload = asdict(value)
            if name == _ENVELOPE_KEY:
                # The envelope fills all six edge fields with the same span and
                # the three `*_rows` fields with totals across every entity, which
                # reads exactly like a partition and is not one. Say so in the
                # payload, not only in the key and in `describe()`: this is the
                # machine-readable form, and a consumer parsing JSON never sees
                # the prose.
                payload["is_partition"] = False
                payload["note"] = (
                    "Span of every record, NOT a partition. Under "
                    "split_strategy='per_entity' the three periods overlap in "
                    "absolute time, so no single boundary triple describes them; "
                    "train_rows/validation_rows/test_rows are totals summed across "
                    "all entities, not counts within a window. Use per_entity for "
                    "the actual windows."
                )
                for field in (
                    "train_start",
                    "train_end",
                    "validation_start",
                    "validation_end",
                    "test_start",
                    "test_end",
                ):
                    payload.setdefault("envelope_" + field, payload.pop(field))
            boundaries[name] = payload
        return {
            "strategy": self.strategy,
            "sizes": self.sizes,
            "train_fraction": self.config.train_fraction,
            "validation_fraction": self.config.validation_fraction,
            "test_fraction": self.config.test_fraction,
            "boundaries": boundaries,
            "per_entity": {name: split.to_dict() for name, split in sorted(self.per_entity.items())},
            "insufficient_entities": dict(sorted(self.insufficient.items())),
            "insufficient_reasons": dict(sorted(self.insufficient_reason.items())),
            "cross_entity_time_overlap": list(self.cross_entity_time_overlap),
            "leakage_findings": list(self.leakage_findings),
            "is_leak_free": self.is_leak_free,
        }

    def describe(self) -> str:
        lines = [
            f"SPLIT strategy={self.strategy} train={len(self.train)} "
            f"validation={len(self.validation)} test={len(self.test)}"
        ]
        for name, boundaries in sorted(self.boundaries.items()):
            if name == _ENVELOPE_KEY:
                lines.append(
                    f"    {name}: {boundaries.train_start} .. {boundaries.test_end} "
                    "(span of every record, NOT a partition: under this strategy the three "
                    "periods overlap in absolute time)"
                )
                continue
            lines.append(
                f"    {name}: train {boundaries.train_start} -> {boundaries.train_end}"
                f" | validation {boundaries.validation_start} -> {boundaries.validation_end}"
                f" | test {boundaries.test_start} -> {boundaries.test_end}"
            )
        if self.insufficient:
            detail = ", ".join(
                f"{name} ({count} rows)" for name, count in sorted(self.insufficient.items())
            )
            lines.append(f"    EXCLUDED: {detail}")
            for name, reason in sorted(self.insufficient_reason.items()):
                lines.append(f"        {name}: {reason}")
        if self.leakage_findings:
            lines.append(f"    LEAKAGE FINDINGS: {list(self.leakage_findings)}")
        return "\n".join(lines)


def _periods_overlap(first: Sequence[Observation], second: Sequence[Observation]) -> bool:
    if not first or not second:
        return False
    return first[0].instant <= second[-1].instant and second[0].instant <= first[-1].instant


def _cut(total: int, config: PreprocessConfig) -> tuple[int, int]:
    """Row indices for train/validation, from the configured fractions.

    Mirrors `preprocessing.chronological_split`'s guards for the same reason: on a
    small frame, truncating `int(total * fraction)` would produce an empty split,
    and an empty split reads as "no test data" rather than as a configuration that
    does not fit this dataset.
    """
    if total < MIN_ROWS_PER_ENTITY:
        raise TemporalError(
            f"at least {MIN_ROWS_PER_ENTITY} records are needed for a 3-way split, got {total}"
        )
    train_end = int(total * config.train_fraction)
    train_end = max(1, min(train_end, total - 2))
    validation_end = train_end + int(total * config.validation_fraction)
    validation_end = max(train_end + 1, min(validation_end, total - 1))
    return train_end, validation_end


def _boundaries(
    train: Sequence[Observation],
    validation: Sequence[Observation],
    test: Sequence[Observation],
) -> SplitBoundaries:
    def edges(records: Sequence[Observation]) -> tuple[str | None, str | None]:
        if not records:
            return None, None
        # Canonical, not `observed_at`: Phase 1 preserves whatever offset the
        # source wrote, so a boundary published verbatim could read
        # `05:30+05:30` for a cut that is really `00:00Z`.
        return to_instant_iso(records[0].instant), to_instant_iso(records[-1].instant)

    train_start, train_end = edges(train)
    validation_start, validation_end = edges(validation)
    test_start, test_end = edges(test)
    return SplitBoundaries(
        train_start=train_start,
        train_end=train_end,
        validation_start=validation_start,
        validation_end=validation_end,
        test_start=test_start,
        test_end=test_end,
        train_rows=len(train),
        validation_rows=len(validation),
        test_rows=len(test),
    )


def _exclude(report: SplitReport, entity: str, count: int, reason: str) -> None:
    """Drop an entity under the configured policy, or refuse to continue."""
    if report.config.insufficient_group_policy == INSUFFICIENT_ERROR:
        raise TemporalError(
            f"entity {entity!r} cannot be given three non-empty splits: {reason}. Set "
            f"insufficient_group_policy={INSUFFICIENT_REPORT_AND_DROP!r} to exclude and report it "
            "instead of failing — but note that a whole gauge disappearing from a dataset is a "
            "decision someone should make deliberately, not a side effect of a ratio."
        )
    report.per_entity.pop(entity, None)
    report.insufficient[entity] = count
    report.insufficient_reason[entity] = reason


def split_records(records: Sequence[Observation], config: PreprocessConfig) -> SplitReport:
    """Split chronologically, either globally or per entity.

    Never shuffles, and there is no parameter that could introduce one: a
    randomised split of a hydrological series leaks future conditions into the
    training set, so the operation is not offered at any setting.

    Under `global`, boundaries are chosen on absolute time from the merged
    timeline, so every entity is cut at the same instants. Under `per_entity`,
    each entity is cut on its own row proportions and `cross_entity_time_overlap`
    reports whether that separated the entities in absolute time.
    """
    if not records:
        raise TemporalError("cannot split an empty record sequence")
    ordered, _ = sort_records(records)
    assert_monotonic(ordered)

    by_entity: dict[str, list[Observation]] = {}
    for record in ordered:
        by_entity.setdefault(entity_key(record), []).append(record)

    report = SplitReport(strategy=config.split_strategy, config=config)
    for entity, items in sorted(by_entity.items()):
        if len(items) < MIN_ROWS_PER_ENTITY:
            _exclude(
                report,
                entity,
                len(items),
                f"{len(items)} record(s) is fewer than the {MIN_ROWS_PER_ENTITY} a three-way "
                "split requires",
            )
            continue
        train_end, validation_end = _cut(len(items), config)
        report.per_entity[entity] = EntitySplit(
            entity=entity,
            train=tuple(items[:train_end]),
            validation=tuple(items[train_end:validation_end]),
            test=tuple(items[validation_end:]),
        )

    if not report.per_entity:
        raise TemporalError(
            f"no entity has at least {MIN_ROWS_PER_ENTITY} usable records; {len(report.insufficient)} "
            "were excluded and there is nothing left to split"
        )

    if config.split_strategy == SPLIT_GLOBAL:
        _apply_global(report)
    elif config.split_strategy == SPLIT_PER_ENTITY:
        _apply_per_entity(report)
    else:  # pragma: no cover - PreprocessConfig validates the vocabulary
        raise TemporalError(f"unknown split strategy {config.split_strategy!r}")

    _assert_usable(report)
    report.leakage_findings.extend(report.cross_entity_time_overlap)
    return report


def _apply_global(report: SplitReport) -> None:
    """Cut every entity at the same absolute instants.

    Boundaries come from the merged timeline, so a sparse station is cut at the
    same calendar window as a dense one instead of at its own row fractions. An
    entity that ends up with an empty band — because it has no records in one
    period at all — is excluded under the configured policy rather than being
    given a relaxed boundary of its own, which would defeat the point of a shared
    cut.
    """
    timeline = sorted(
        {record.instant for split in report.per_entity.values() for record in _flatten(split)}
    )
    train_end, validation_end = _cut(len(timeline), report.config)
    train_cut, validation_cut = timeline[train_end - 1], timeline[validation_end - 1]

    for entity in sorted(report.per_entity):
        items = _flatten(report.per_entity[entity])
        train = tuple(item for item in items if item.instant <= train_cut)
        validation = tuple(
            item for item in items if train_cut < item.instant <= validation_cut
        )
        test = tuple(item for item in items if item.instant > validation_cut)
        empty = [
            name
            for name, part in (("train", train), ("validation", validation), ("test", test))
            if not part
        ]
        if empty:
            _exclude(
                report,
                entity,
                len(items),
                f"under a global chronological cut it has no record(s) in the {', '.join(empty)} "
                f"period(s) beyond {to_instant_iso(train_cut)} / "
                f"{to_instant_iso(validation_cut)}; a station whose coverage does not span the "
                "shared cut cannot be split on shared boundaries",
            )
            continue
        report.per_entity[entity] = EntitySplit(
            entity=entity, train=train, validation=validation, test=test
        )

    if not report.per_entity:
        raise TemporalError(
            "no entity spans all three global periods; the configured fractions do not suit this "
            "dataset's coverage"
        )

    report.train = _flatten_many(report.per_entity, "train")
    report.validation = _flatten_many(report.per_entity, "validation")
    report.test = _flatten_many(report.per_entity, "test")
    report.boundaries = {"all_entities": _boundaries(report.train, report.validation, report.test)}


def _apply_per_entity(report: SplitReport) -> None:
    """Split each entity on its own row proportions, and say what that costs.

    Under this strategy the splits are per entity only. There is deliberately
    **no** aggregate `all_entities` boundary, because none exists: entity A's
    `test` period can sit inside entity B's `train` period, so any single
    `train_end < validation_start < test_end` triple computed by flattening the
    two would be a fiction. What is published instead is an *envelope* covering
    the union of every entity's records, named so that it cannot be mistaken for
    a partition, and `cross_entity_time_overlap` names each overlap individually.
    """
    for entity in sorted(report.per_entity):
        split = report.per_entity[entity]
        report.boundaries[entity] = _boundaries(split.train, split.validation, split.test)
        report.train.extend(split.train)
        report.validation.extend(split.validation)
        report.test.extend(split.test)
    order = lambda items: sorted(items, key=lambda item: (entity_key(item), item.instant))  # noqa: E731
    report.train = order(report.train)
    report.validation = order(report.validation)
    report.test = order(report.test)
    report.boundaries[_ENVELOPE_KEY] = _envelope(report)


def _flatten(split: EntitySplit) -> tuple[Observation, ...]:
    return split.train + split.validation + split.test


def _envelope(report: SplitReport) -> SplitBoundaries:
    """The span of every record, as an envelope rather than a partition.

    `train_start`/`validation_start`/`test_start` are all the earliest instant in
    the whole dataset and the three `_end` fields are all the latest, because
    under `per_entity` the three periods genuinely overlap. The row counts are
    still meaningful and are kept.
    """
    moments = sorted(
        record.instant for record in _flatten_many(report.per_entity, "all")
    )
    first = to_instant_iso(moments[0]) if moments else None
    last = to_instant_iso(moments[-1]) if moments else None
    return SplitBoundaries(
        train_start=first,
        train_end=last,
        validation_start=first,
        validation_end=last,
        test_start=first,
        test_end=last,
        train_rows=len(report.train),
        validation_rows=len(report.validation),
        test_rows=len(report.test),
    )


def _flatten_many(per_entity: dict[str, EntitySplit], part: str) -> list[Observation]:
    if part == "all":
        return [record for entity in sorted(per_entity) for record in _flatten(per_entity[entity])]
    return sorted(
        (record for entity in sorted(per_entity) for record in getattr(per_entity[entity], part)),
        key=lambda item: (entity_key(item), item.instant),
    )


def _assert_usable(report: SplitReport) -> None:
    """Every split must be non-empty, ordered, and mutually disjoint in time.

    The envelope published by `per_entity` is exempt from the ordering check by
    construction: it is an overlap by definition, and treating that as a leakage
    condition would make the strategy unusable. The per-entity boundaries, which
    *are* real partitions, are still checked.
    """
    for entity, split in report.per_entity.items():
        for name, part in zip(("train", "validation", "test"), split.parts()):
            if not part:  # pragma: no cover - exclusions happen before this point
                raise TemporalError(f"entity {entity!r} has an empty {name} split")
            assert_monotonic(part)
    for name, boundaries in report.boundaries.items():
        if name == _ENVELOPE_KEY:
            continue
        if not boundaries.is_ordered():
            raise TemporalError(
                f"split boundaries for {name!r} are not chronological: {boundaries}. This is a "
                "leakage condition and the split is refused."
            )


# --------------------------------------------------------------------------- #
# Imputation
# --------------------------------------------------------------------------- #

#: Policies that only ever read slots at or before the one being filled. Exported
#: so a test can assert the property directly against the vocabulary rather than
#: against a hand-written list.
CAUSAL_MISSING_POLICIES = frozenset({MISSING_FORWARD_FILL, MISSING_LINEAR_CAUSAL})
LEAKY_MISSING_POLICIES = frozenset({MISSING_BACKWARD_FILL, MISSING_LINEAR_BIDIRECTIONAL})


@dataclass
class MissingPolicyReport:
    """Imputation statistics, per the brief's audit requirement."""

    policy: str
    missing_before: int = 0
    missing_after: int = 0
    imputed: int = 0
    imputed_by_quantity: dict[str, int] = field(default_factory=dict)
    #: Gaps left unfilled because they exceeded `max_fill_gap` or had nothing to
    #: draw on.
    beyond_max_gap: int = 0
    leading_gap: int = 0
    leakage_sensitive: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return self.imputed > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "imputation_enabled": self.enabled,
            "missing_before": self.missing_before,
            "missing_after": self.missing_after,
            "imputed": self.imputed,
            "imputed_by_quantity": dict(sorted(self.imputed_by_quantity.items())),
            "beyond_max_gap": self.beyond_max_gap,
            "leading_gap": self.leading_gap,
            "leakage_sensitive": self.leakage_sensitive,
            "notes": list(self.notes),
        }


def apply_missing_policy(
    slots: Sequence[SeriesSlot],
    config: PreprocessConfig,
    *,
    quantities: Sequence[str],
) -> tuple[list[SeriesSlot], MissingPolicyReport]:
    """Apply the configured gap policy to one entity's grid.

    Three properties hold, and the tests assert each against the vocabulary rather
    than against a hand-picked policy:

    * **Causality.** `forward_fill` and `linear_causal` read only slots at or
      before the one being filled. `backward_fill` and `linear_bidirectional` read
      later slots, which is why the configuration refuses to select them without
      an explicit acknowledgement.
    * **Boundedness.** A gap longer than `max_fill_gap` slots is never filled, at
      any policy. A three-hour outage is plausibly flat; a three-week one is a
      missing season, and filling it produces a hydrograph nobody observed.
    * **Auditability.** Every value written is marked `quality_status='missing'`
      with a note naming the instant it was carried from, so a derived reading is
      never mistaken for an observed one downstream.
    """
    policy = config.missing_policy
    report = MissingPolicyReport(policy=policy, leakage_sensitive=policy in LEAKY_MISSING_POLICIES)
    gap_indices = [index for index, slot in enumerate(slots) if slot.is_gap]
    report.missing_before = len(gap_indices)

    if policy == MISSING_RETAIN:
        report.missing_after = len(gap_indices)
        report.notes.append(
            "gaps retained as gaps: no value was invented. A retained gap is a fact about the "
            "instrument, and Phase 3 must treat it as absent rather than as a zero."
        )
        return list(slots), report

    if policy == MISSING_REJECT:
        if gap_indices:
            raise TemporalError(
                f"{len(gap_indices)} gap(s) present under missing_policy='reject'; the first is at "
                f"{slots[gap_indices[0]].instant}. Configure an explicit policy, or leave 'retain' "
                "and let Phase 3 handle the absence."
            )
        return list(slots), report

    if policy == MISSING_DROP:
        kept = [slot for slot in slots if not slot.is_gap]
        report.notes.append(
            f"dropped {len(gap_indices)} gap slot(s); the series is contiguous but shorter, and "
            "the removed instants are not recoverable from the output"
        )
        return kept, report

    # `_fill_slots` accumulates `report.imputed` and `report.imputed_by_quantity`
    # as it writes, and sets `report.missing_after` from the grid it returns.
    return _fill_slots(slots, config, quantities, report)


def _fill_slots(
    slots: Sequence[SeriesSlot],
    config: PreprocessConfig,
    quantities: Sequence[str],
    report: MissingPolicyReport,
) -> tuple[list[SeriesSlot], MissingPolicyReport]:
    """Return `(filled_grid, report)` with gaps filled where the policy allows.

    The input grid is never mutated: `SeriesSlot` is frozen, so a filled slot is
    a *new* slot built with `replace`. That is what lets a caller keep the
    pre-fill grid and compare it against the output to audit what changed.
    """
    result: list[SeriesSlot] = []
    index = 0
    total = len(slots)
    while index < total:
        slot = slots[index]
        if not slot.is_gap:
            result.append(slot)
            index += 1
            continue

        run_start = index
        while index < total and slots[index].is_gap:
            index += 1
        run = list(slots[run_start:index])
        after = slots[index] if index < total else None

        additions, filled = _fill_run(run, result, after, config, quantities, report)
        report.imputed += filled
        for extra in additions.values():
            for record in extra:
                for item in record.measurements:
                    report.imputed_by_quantity[item.quantity] = (
                        report.imputed_by_quantity.get(item.quantity, 0) + 1
                    )
        for offset, hole in enumerate(run):
            extra = additions.get(offset)
            if extra:
                result.append(hole.with_observations(hole.observations + tuple(extra)))
            else:
                result.append(hole)
    report.missing_after = sum(1 for slot in result if slot.is_gap)
    return result, report


def _fill_run(
    run: Sequence[SeriesSlot],
    emitted: Sequence[SeriesSlot],
    after: SeriesSlot | None,
    config: PreprocessConfig,
    quantities: Sequence[str],
    report: MissingPolicyReport,
) -> tuple[dict[int, list[Observation]], int]:
    """Fill one contiguous run of gap slots.

    Returns `(additions, count)` where `additions` maps an index into `run` to the
    records written there. Nothing is mutated: the caller rebuilds the slots.
    """
    policy = config.missing_policy
    additions: dict[int, list[Observation]] = {}
    filled = 0
    too_long = len(run) > config.max_fill_gap

    def write(offset: int, donor: SeriesSlot, quantity: str, value: float) -> None:
        nonlocal filled
        additions.setdefault(offset, []).append(
            _filled_record(run[offset], donor, quantity, value)
        )
        filled += 1

    if policy == MISSING_FORWARD_FILL:
        previous = emitted[-1] if emitted else None
        if previous is None:
            report.leading_gap += len(run)
            report.notes.append(
                f"leading gap of {len(run)} slot(s) at {run[0].instant} not filled: a forward fill "
                "has no earlier value to carry, and borrowing a later one would put a future "
                "reading into the first row of the series"
            )
            return additions, filled
        if too_long:
            _record_too_long(report, run, config)
            return additions, filled
        for quantity in quantities:
            available = previous.values_for(quantity)
            if not available:
                continue
            for offset in range(len(run)):
                write(offset, previous, quantity, available[-1])
        return additions, filled

    if policy == MISSING_LINEAR_CAUSAL:
        return _linear_causal(run, emitted, quantities, too_long, additions, write)

    if policy == MISSING_BACKWARD_FILL:
        if after is None:
            report.beyond_max_gap += len(run)
            report.notes.append(
                f"trailing gap of {len(run)} slot(s) at {run[0].instant} not filled: a backward "
                "fill has no later value to carry"
            )
            return additions, filled
        if too_long:
            _record_too_long(report, run, config)
            return additions, filled
        for quantity in quantities:
            available = after.values_for(quantity)
            if not available:
                continue
            for offset in range(len(run)):
                write(offset, after, quantity, available[0])
        return additions, filled

    if policy == MISSING_LINEAR_BIDIRECTIONAL:
        return _linear_bidirectional(run, emitted, after, quantities, too_long, additions, write)

    raise TemporalError(f"unknown missing policy {policy!r}")  # pragma: no cover


def _record_too_long(report: MissingPolicyReport, run: Sequence[SeriesSlot], config: PreprocessConfig) -> None:
    """Note a gap that exceeded `max_fill_gap` and was therefore left alone."""
    report.beyond_max_gap += len(run)
    report.notes.append(
        f"gap of {len(run)} slot(s) at {run[0].instant} exceeds max_fill_gap="
        f"{config.max_fill_gap} and was left unfilled: a long outage is a missing period, "
        "not a flat line"
    )


def _filled_record(
    slot: SeriesSlot,
    donor: SeriesSlot,
    quantity: str,
    value: float,
) -> Observation:
    """Build a filled record for `slot`, carrying the donor's provenance.

    Marked `quality_status='missing'`, not `'ok'`. It is a value this repository
    derived, and Phase 3 must be able to tell derived rows from observed ones
    without re-deriving that fact. The donor's disclaimer is carried over, so a
    synthetic series cannot become real by being filled.
    """
    template = _donor_record(donor, quantity)
    return Observation(
        domain=template.domain,
        location_reference=template.location_reference,
        observed_at=slot.instant,
        measurements=(Measurement(quantity=quantity, value=value, unit=_unit_of(template, quantity)),),
        measurement_window=template.measurement_window,
        source_reference=template.source_reference,
        provenance_reference=template.provenance_reference,
        dataset_reference=template.dataset_reference,
        dataset_type=template.dataset_type,
        quality_status=QUALITY_MISSING,
        disclaimer=template.disclaimer,
        notes=(
            f"Phase 2 missing-value fill at preprocessing: no source record exists for this "
            f"instant. Value carried from {donor.instant}."
        ),
    )


def _donor_record(donor: SeriesSlot, quantity: str) -> Observation:
    for record in donor.observations:
        if any(item.quantity == quantity for item in record.measurements):
            return record
    raise TemporalError(  # pragma: no cover - guarded by values_for
        f"donor slot {donor.instant} has no record carrying {quantity!r}"
    )


def _unit_of(record: Observation, quantity: str) -> str:
    for item in record.measurements:
        if item.quantity == quantity:
            return item.unit
    raise TemporalError(  # pragma: no cover - guarded by the caller
        f"record at {record.observed_at} has no measurement {quantity!r}"
    )


def _linear_causal(
    run: Sequence[SeriesSlot],
    emitted: Sequence[SeriesSlot],
    quantities: Sequence[str],
    too_long: bool,
    additions: dict[int, list[Observation]],
    write,
) -> tuple[dict[int, list[Observation]], int]:
    """Extrapolate each hole from the two nearest **earlier** values.

    Strictly one-sided by construction: `emitted` is the already-built prefix and
    nothing after `run` is ever consulted. A gap at the very start has no prefix
    to extrapolate from and is left alone.
    """
    if too_long or len(emitted) < 2:
        return additions, 0
    anchor, last = emitted[-2], emitted[-1]
    span = (last.moment - anchor.moment).total_seconds()
    if span <= 0:  # pragma: no cover - slots are strictly increasing
        return additions, 0
    before = sum(len(items) for items in additions.values())
    for offset, hole in enumerate(run):
        for quantity in quantities:
            start_values = anchor.values_for(quantity)
            end_values = last.values_for(quantity)
            if not start_values or not end_values:
                continue
            rate = (end_values[-1] - start_values[-1]) / span
            slope = (hole.moment - last.moment).total_seconds()
            value = end_values[-1] + rate * slope
            if not math.isfinite(value):  # pragma: no cover - inputs are finite
                continue
            write(offset, last, quantity, value)
    return additions, sum(len(items) for items in additions.values()) - before


def _linear_bidirectional(
    run: Sequence[SeriesSlot],
    emitted: Sequence[SeriesSlot],
    after: SeriesSlot | None,
    quantities: Sequence[str],
    too_long: bool,
    additions: dict[int, list[Observation]],
    write,
) -> tuple[dict[int, list[Observation]], int]:
    """Interpolate between the surrounding values.

    Reads to the **right**, so every filled row depends on an instant later than
    itself. Selectable only with `allow_leakage_sensitive=True` plus an explicit
    acknowledgement, and the report records that it was used.
    """
    if too_long or after is None:
        return additions, 0
    before = sum(len(items) for items in additions.values())
    for offset in range(len(run)):
        for quantity in quantities:
            earlier = next(
                (slot for slot in reversed(emitted) if slot.has_quantity(quantity)), None
            )
            if earlier is None:
                continue
            earlier_values = earlier.values_for(quantity)
            later_values = after.values_for(quantity)
            if not earlier_values or not later_values:
                continue
            start, end = earlier.moment, after.moment
            span = (end - start).total_seconds()
            if span <= 0:  # pragma: no cover - slots are strictly increasing
                continue
            weight = (run[offset].moment - start).total_seconds() / span
            value = earlier_values[-1] + (later_values[-1] - earlier_values[-1]) * weight
            write(offset, earlier, quantity, value)
    return additions, sum(len(items) for items in additions.values()) - before


__all__ = [
    "CAUSAL_MISSING_POLICIES",
    "LEAKY_MISSING_POLICIES",
    "TZ_ASSUMED_UTC",
    "TZ_DECLARED",
    "TZ_EXPLICIT",
    "Duration",
    "EntitySplit",
    "MissingPolicyReport",
    "NormalizedInstant",
    "SeriesSlot",
    "SplitReport",
    "TemporalError",
    "TimestampNormalizationReport",
    "apply_missing_policy",
    "assert_monotonic",
    "build_grid",
    "canonical_record",
    "entity_key",
    "series_key",
    "describe_series",
    "infer_interval",
    "infer_base_interval",
    "interval_regularity",
    "normalize_timestamp",
    "parse_frequency",
    "record_order",
    "resample_entity",
    "sort_records",
    "split_records",
]