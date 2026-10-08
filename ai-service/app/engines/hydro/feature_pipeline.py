# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 3 — the pipeline: Phase 2 records in, a model-ready feature dataset out.

**PHASE 3 DOES NOT TRAIN MODELS.** Nothing in this module fits a parameter, selects
an algorithm, scores a prediction or computes an error metric. It reads Phase 2's
records, evaluates point-in-time-correct feature windows, aligns targets forward in
time, and hands a documented dataset to Phase 4.

Five decisions carry most of the weight, and each exists because the obvious
alternative leaks or lies.

**Features are built across split boundaries; targets are not.** A lag at the first
instant of the validation period legitimately reaches back into the training period
— that is history, not leakage, because it is strictly earlier than the prediction
instant. So one timeline is built over the whole series and rows are then *assigned*
to splits. Targets get the opposite treatment: a row whose target instant lands in
the next split has that target withheld, because a validation row whose answer lives
in the test period has been handed a piece of the test set.

**Nothing is imputed.** An absent feature value stays absent and is counted, with a
cause. Filling it is a modelling decision that belongs to Phase 4, which can fit an
imputer on training rows only; filling it here would fill it *before* the split,
which is one of the classic ways test information reaches a model.

**Column order is the registry's order.** Not a set, not a dict, not the order a
loop happened to visit things. Feature *names* come from one function and column
*positions* come from one ordered tuple, so two runs of the same configuration
produce byte-identical layouts.

**Causes that look alike are counted separately.** A row with no 24-hour rainfall
total because the gauge had not been running for 24 hours is a different statement
from one missing because the gauge dropped out, and both differ from a partial
window that failed its coverage requirement. Three counts, reported separately,
with exact numbers.

**Cadence is read, not invented.** Phase 2 owns it. Where Phase 2 established a
cadence, Phase 3 uses Phase 2's own function on Phase 2's own records; where it
could not, Phase 3 says so and treats coverage as unassessable rather than assuming
an hour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from .datasets import DatasetDescriptor
from .domains import (
    DATASET_TYPE_SYNTHETIC,
    DATASET_TYPE_UNKNOWN,
    QUALITY_MISSING,
    Observation,
    parse_instant,
    to_instant_iso,
)
from .feature_config import (
    MISSING_DROP_ROWS,
    MISSING_ERROR,
    MISSING_RETAIN,
    UNIT_REQUIRE_KNOWN,
    WARMUP_DROP_ROWS,
    WARMUP_ERROR,
    WARMUP_RETAIN,
    FeatureConfig,
    build_registry,
)
from .feature_registry import (
    CALENDAR_COMPONENTS,
    CODE_PREFIX,
    EXCLUDED_CALENDAR_COMPONENTS,
    FEATURE_CONTRACT_VERSION,
    LEVEL_QUANTITIES,
    OP_CALENDAR,
    FeatureRegistry,
    TargetLineage,
    split_measurement_key,
    target_name,
    unavailable_catalogue,
    window_label,
)
from .feature_temporal import (
    ABSENT_CAUSES,
    CAUSE_CUTOFF_UNDEFINED,
    CAUSE_INSUFFICIENT,
    CAUSE_MISSING_SOURCE,
    CAUSE_NO_SOURCE,
    CAUSE_NOT_APPLICABLE,
    CAUSE_UNDETERMINED_UNIT,
    CAUSE_UNIT_MISMATCH,
    CAUSE_WARMUP,
    SeriesTimeline,
    build_timelines,
    entity_instants,
    evaluate,
    op_target,
    timelines_by_entity,
)
from .preprocess_temporal import (
    Duration,
    infer_base_interval,
    interval_regularity,
    series_key,
)
from .preprocess_units import is_convertible
from .provenance import SYNTHETIC_DATA_DISCLAIMER, UNVERIFIED_DATA_DISCLAIMER

# --------------------------------------------------------------------------- #
# Severities
# --------------------------------------------------------------------------- #

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

SEVERITIES = (SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO)

_SEVERITY_RANK = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}


class FeatureError(ValueError):
    """Raised when the Phase 3 pipeline cannot produce a dataset at all.

    Distinct from `feature_config.FeatureConfigError` (the configuration is
    self-contradictory) and `feature_temporal.FeatureTemporalError` (one window is
    impossible). This one means the run as a whole cannot proceed: no records, no
    retained rows, or a policy that said `error` and met the case it was guarding.
    """


# --------------------------------------------------------------------------- #
# Report codes
# --------------------------------------------------------------------------- #

CODE_REGISTRY_COMPILED = CODE_PREFIX + "REGISTRY_COMPILED"
CODE_FEATURES_BUILT = CODE_PREFIX + "FEATURES_BUILT"
CODE_ROWS_BUILT = CODE_PREFIX + "ROWS_BUILT"
CODE_ROWS_RETAINED = CODE_PREFIX + "ROWS_RETAINED"
CODE_ROWS_DROPPED_WARMUP = CODE_PREFIX + "ROWS_DROPPED_WARMUP"
CODE_ROWS_DROPPED_MISSING = CODE_PREFIX + "ROWS_DROPPED_MISSING"
CODE_ROWS_UNASSIGNED = CODE_PREFIX + "ROWS_WITHOUT_SPLIT_LABEL"
CODE_FEATURE_UNAVAILABLE = CODE_PREFIX + "FEATURE_UNAVAILABLE"
CODE_FEATURE_SKIPPED_UNIT = CODE_PREFIX + "FEATURE_SKIPPED_UNDETERMINED_UNIT"
CODE_FEATURE_FLAGGED_UNIT = CODE_PREFIX + "FEATURE_FLAGGED_UNDETERMINED_UNIT"
CODE_STATIC_UNAVAILABLE = CODE_PREFIX + "STATIC_FEATURE_UNAVAILABLE"
CODE_CALENDAR_EXCLUDED = CODE_PREFIX + "CALENDAR_COMPONENT_EXCLUDED"
CODE_ACCUM_COVERAGE = CODE_PREFIX + "ACCUMULATION_COVERAGE_UNMET"
CODE_UNIT_UNDETERMINED = CODE_PREFIX + "SOURCE_UNIT_UNDETERMINED"
CODE_CADENCE_UNKNOWN = CODE_PREFIX + "CADENCE_UNKNOWN"
CODE_CADENCE_IRREGULAR = CODE_PREFIX + "CADENCE_IRREGULAR"
CODE_DATUM_LIMITATION = CODE_PREFIX + "DATUM_COMPARABILITY_LIMITATION"
CODE_TARGET_ABSENT = CODE_PREFIX + "TARGET_ABSENT"
CODE_TARGET_CROSSES_SPLIT = CODE_PREFIX + "TARGET_CROSSES_SPLIT"
CODE_ORDERED = CODE_PREFIX + "ROW_ORDER_DETERMINISTIC"
CODE_DETERMINISM = CODE_PREFIX + "CONFIGURATION_DETERMINISTIC"
CODE_LEAKAGE_CHECKED = CODE_PREFIX + "LEAKAGE_CHECKED"
CODE_SYNTHETIC_SOURCE = CODE_PREFIX + "SYNTHETIC_SOURCE"
CODE_FILLED_SOURCE_EXCLUDED = CODE_PREFIX + "FILLED_SOURCE_EXCLUDED"
CODE_LINEAGE_EXPORTED = CODE_PREFIX + "LINEAGE_EXPORTED"
CODE_NO_IMPUTATION = CODE_PREFIX + "NO_IMPUTATION_APPLIED"

ALL_CODES = frozenset(
    {
        CODE_REGISTRY_COMPILED,
        CODE_FEATURES_BUILT,
        CODE_ROWS_BUILT,
        CODE_ROWS_RETAINED,
        CODE_ROWS_DROPPED_WARMUP,
        CODE_ROWS_DROPPED_MISSING,
        CODE_ROWS_UNASSIGNED,
        CODE_FEATURE_UNAVAILABLE,
        CODE_FEATURE_SKIPPED_UNIT,
        CODE_FEATURE_FLAGGED_UNIT,
        CODE_STATIC_UNAVAILABLE,
        CODE_CALENDAR_EXCLUDED,
        CODE_ACCUM_COVERAGE,
        CODE_UNIT_UNDETERMINED,
        CODE_CADENCE_UNKNOWN,
        CODE_CADENCE_IRREGULAR,
        CODE_DATUM_LIMITATION,
        CODE_TARGET_ABSENT,
        CODE_TARGET_CROSSES_SPLIT,
        CODE_ORDERED,
        CODE_DETERMINISM,
        CODE_LEAKAGE_CHECKED,
        CODE_SYNTHETIC_SOURCE,
        CODE_FILLED_SOURCE_EXCLUDED,
        CODE_LINEAGE_EXPORTED,
        CODE_NO_IMPUTATION,
    }
)


# --------------------------------------------------------------------------- #
# Notes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FeatureNote:
    """One Phase 3 finding.

    A note is not a Phase 1 `quality.QualityIssue`. A `QualityIssue` asks "is this
    record well formed?"; a `FeatureNote` says "here is what feature engineering did
    to your data, and here is what you must remember when using the result". Same
    separation as `preprocess_pipeline.PreprocessNote`, for the same reason: two
    different questions, two different vocabularies.
    """

    severity: str
    code: str
    message: str
    subject: str = ""

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}, got {self.severity!r}")
        if not self.code:
            raise ValueError("FeatureNote.code must be a non-empty string")
        if self.code not in ALL_CODES:
            raise ValueError(
                f"unknown feature note code {self.code!r}; add it to ALL_CODES so it stays "
                "queryable rather than being matched on message text"
            )

    @property
    def is_error(self) -> bool:
        return self.severity == SEVERITY_ERROR

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "subject": self.subject,
        }

    def describe(self) -> str:
        where = f" [{self.subject}]" if self.subject else ""
        return f"{self.severity.upper():<7} {self.code}{where}: {self.message}"


def _sorted_notes(notes: Iterable[FeatureNote]) -> tuple[FeatureNote, ...]:
    """Worst-first, then code, subject, message — so a report is reproducible."""
    return tuple(
        sorted(
            notes,
            key=lambda note: (
                _SEVERITY_RANK[note.severity],
                note.code,
                note.subject,
                note.message,
            ),
        )
    )


# --------------------------------------------------------------------------- #
# Leakage audit
# --------------------------------------------------------------------------- #


@dataclass
class Phase3LeakageAudit:
    """Runtime evidence that Phase 3 read nothing it should not have read.

    Phase 2's audit checks *split* leakage on records. This checks *feature*
    leakage on the produced rows, which is a different question: a split can be
    perfectly disjoint while a rolling window still reaches forward.

    Checks are recorded by name so a reader can see which ones ran, not merely that
    a boolean came back true. An audit that reports "ok" without saying what it
    checked is an assertion, not evidence.
    """

    records: list[tuple[str, bool, str]] = field(default_factory=list)

    def record(self, name: str, passed: bool, detail: str = "") -> None:
        self.records.append((name, bool(passed), detail))

    @property
    def ok(self) -> bool:
        return all(passed for _name, passed, _detail in self.records)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(name for name, _passed, _detail in self.records)

    @property
    def failures(self) -> tuple[tuple[str, bool, str], ...]:
        return tuple(entry for entry in self.records if not entry[1])

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": len(self.records),
            "records": [
                {"check": name, "passed": passed, "detail": detail}
                for name, passed, detail in self.records
            ],
        }

    def describe(self) -> str:
        lines = [f"Phase 3 leakage audit ({len(self.records)} check(s), ok={self.ok})"]
        lines.extend(
            f"  {'PASS' if passed else 'FAIL'}  {name}" + (f" - {detail}" if detail else "")
            for name, passed, detail in self.records
        )
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Splits
# --------------------------------------------------------------------------- #

#: Split labels Phase 2 publishes. Reused verbatim so a reader does not have to
#: learn two sets of names for the same periods.
SPLIT_TRAIN = "train"
SPLIT_VALIDATION = "validation"
SPLIT_TEST = "test"
SPLITS = (SPLIT_TRAIN, SPLIT_VALIDATION, SPLIT_TEST)

#: For an origin instant Phase 2 published no label for. Rare — Phase 2 labels every
#: record it returns — but reachable when a caller hands Phase 3 a hand-built
#: result. Such rows are kept, visible, and counted rather than deleted, because a
#: row vanishing is harder to notice than a row labelled oddly.
SPLIT_UNASSIGNED = "unassigned"


@dataclass(frozen=True)
class SplitIndex:
    """Which split each instant of one entity belongs to.

    Phase 2 assigned the split; Phase 3 reads it rather than re-deriving it.
    Re-splitting here would be both duplication and a chance to disagree with the
    split Phase 2 already published.
    """

    entity: str
    #: Instant -> split label.
    labels: Mapping[datetime, str] = field(default_factory=dict)

    def label_for(self, instant: datetime) -> str | None:
        return self.labels.get(instant)

    @property
    def bounds(self) -> dict[str, tuple[datetime, datetime]]:
        """Per-label `(first, last)` instant, for reporting."""
        out: dict[str, tuple[datetime, datetime]] = {}
        for label in SPLITS:
            moments = sorted(i for i, value in self.labels.items() if value == label)
            if moments:
                out[label] = (moments[0], moments[-1])
        return out


def split_parts(result: Any) -> dict[str, Sequence[Observation]]:
    """The `(label -> records)` view of a Phase 2 result.

    One adapter, so Phase 3 knows about Phase 2's three sequence fields in exactly
    one place and can be pointed at a stand-in by the leakage audit.
    """
    return {
        SPLIT_TRAIN: tuple(getattr(result, SPLIT_TRAIN, ()) or ()),
        SPLIT_VALIDATION: tuple(getattr(result, SPLIT_VALIDATION, ()) or ()),
        SPLIT_TEST: tuple(getattr(result, SPLIT_TEST, ()) or ()),
    }


def build_split_index(
    parts: Mapping[str, Sequence[Observation]],
) -> dict[str, SplitIndex]:
    """Map every entity to the split each of its instants falls in.

    `parts` maps a split label to the records in it. Where two splits claim the same
    instant — which would mean Phase 2 leaked a boundary — the earliest label in
    `SPLITS` order wins and `split_collisions` reports it, because silently
    preferring the *later* one would let a test instant masquerade as a training
    instant.
    """
    collected: dict[str, dict[datetime, str]] = {}
    for label in SPLITS:
        for record in parts.get(label, ()):  # type: ignore[arg-type]
            instant = parse_instant(record.observed_at)
            collected.setdefault(record.location_reference, {}).setdefault(instant, label)
    return {
        entity: SplitIndex(entity=entity, labels=dict(sorted(labels.items())))
        for entity, labels in sorted(collected.items())
    }


def split_collisions(parts: Mapping[str, Sequence[Observation]]) -> list[str]:
    """Instants claimed by more than one split, as readable strings.

    Phase 2 audits this. Re-checking it here costs nothing and turns a Phase 2 bug
    into a visible Phase 3 refusal instead of a quietly contaminated dataset.
    """
    seen: dict[tuple[str, datetime], str] = {}
    clashes: list[str] = []
    for label in SPLITS:
        for record in parts.get(label, ()):  # type: ignore[arg-type]
            key = (record.location_reference, parse_instant(record.observed_at))
            if key in seen and seen[key] != label:
                clashes.append(f"{key[0]} {key[1].isoformat()} claimed by {seen[key]} and {label}")
            else:
                seen[key] = label
    return sorted(clashes)


# --------------------------------------------------------------------------- #
# Cadence
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Cadence:
    """What was established about one series' sampling.

    `seconds is None` is the load-bearing value: it means the cadence was never
    established, so the number of readings a window should hold is unknowable and
    coverage cannot be assessed. Every consumer treats that as *unmet*, because
    "this series has no established cadence" is not evidence that a window was
    complete.
    """

    series: str
    seconds: float | None = None
    regularity: float = 0.0
    #: The prose Phase 2 published for this series, carried through verbatim.
    published: str = ""

    @property
    def is_known(self) -> bool:
        return self.seconds is not None and self.seconds > 0

    @property
    def label(self) -> str | None:
        return window_label(self.seconds) if self.is_known else None

    def describe(self) -> str:
        if not self.is_known:
            return f"{self.series}: cadence NOT established (coverage unassessable)"
        return (
            f"{self.series}: cadence {self.label} "
            f"(regularity {self.regularity:.0%}, established by Phase 2)"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "series": self.series,
            "seconds": self.seconds,
            "label": self.label,
            "regularity": self.regularity,
            "established": self.is_known,
            "published_by_phase_two": self.published,
        }


def resolve_cadence(
    records: Sequence[Observation],
    *,
    base_intervals: Mapping[str, float] | None = None,
    published: Mapping[str, str] | None = None,
) -> dict[str, Cadence]:
    """Establish the base cadence of every Phase 2 series, in seconds.

    In priority order:

    1. **An explicit `base_intervals` override.** A caller that already holds the
       durations passes them in and Phase 3 recomputes nothing.
    2. **Phase 2's own `infer_base_interval`, on Phase 2's own records.** Phase 2
       publishes its cadence as prose — `"F1|water_level: 1h (regularity 100%,
       inferred)"` — which is written for a reader, not for a parser. Rather than
       scrape a sentence with a regular expression and trust the answer, Phase 3
       calls the same function Phase 2 called. One implementation, one answer, no
       string round-trip to go wrong. The published text travels alongside as
       `Cadence.published` so a reader can compare the two.
    3. **Nothing.** Recorded as `seconds is None`, reported, and never replaced with
       an assumed hour.

    Phase 3 never resamples, never interpolates and never *chooses* a cadence.
    """
    by_series: dict[str, list[Observation]] = {}
    for record in records:
        by_series.setdefault(series_key(record), []).append(record)

    override = dict(base_intervals or {})
    texts = dict(published or {})
    out: dict[str, Cadence] = {}
    for series in sorted(by_series):
        rows = by_series[series]
        seconds: float | None = None
        if series in override and override[series] and override[series] > 0:
            seconds = float(override[series])
        else:
            found: Duration | None = infer_base_interval(rows)
            seconds = found.seconds if found is not None else None
        if seconds is None or seconds <= 0:
            out[series] = Cadence(series=series, seconds=None, published=texts.get(series, ""))
            continue
        out[series] = Cadence(
            series=series,
            seconds=seconds,
            regularity=interval_regularity(rows, Duration(seconds)),
            published=texts.get(series, ""),
        )
    return out


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FeatureRow:
    """One prediction origin for one entity, with its features and its targets.

    The five kinds of information are separate fields on purpose, because the most
    common way a forecasting dataset leaks is by putting a target into the same bag
    as the features. Here they cannot be confused: `values` is what a model may see,
    `targets` is what it must be told, `entity` and `instant` identify the row
    without describing the catchment, and `absent_reasons` / `target_instants` are
    metadata about both.

    `values` and `targets` are `Mapping`s rather than tuples so the column names
    travel with the numbers. A positional row cannot be checked against the registry
    without carrying the registry alongside it, and that is exactly the step where a
    reordering bug becomes a silent misalignment.
    """

    #: IDENTITY — which reporting entity this row belongs to.
    entity: str
    #: TIMESTAMP — the prediction origin. Every feature is a function of
    #: observations at or before this instant.
    instant: datetime
    #: METADATA — the Phase 2 split this origin falls in.
    split: str
    #: FEATURES — `float` or `None`. `None` means absent, with a reason below.
    values: Mapping[str, float | None]
    #: TARGET — `float` or `None`, one entry per configured horizon.
    targets: Mapping[str, float | None]
    #: METADATA — feature name -> why its value is absent.
    absent_reasons: Mapping[str, str] = field(default_factory=dict)
    #: METADATA — target name -> the instant its value was read from.
    target_instants: Mapping[str, datetime | None] = field(default_factory=dict)
    #: METADATA — every instant any feature in this row read. The audit checks each
    #: of these against the origin, so it is kept rather than discarded.
    source_instants: tuple[datetime, ...] = ()

    @property
    def target_timestamps(self) -> dict[str, datetime]:
        """Only the targets that exist, for a model that needs a real instant."""
        return {
            name: instant
            for name, instant in self.target_instants.items()
            if instant is not None
        }

    def feature_value(self, name: str) -> float | None:
        return self.values.get(name)

    def has_target(self) -> bool:
        return any(value is not None for value in self.targets.values())

    def present_features(self) -> tuple[str, ...]:
        return tuple(name for name, value in self.values.items() if value is not None)

    def absent_features(self) -> tuple[str, ...]:
        return tuple(name for name, value in self.values.items() if value is None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "instant": to_instant_iso(self.instant),
            "split": self.split,
            "features": dict(self.values),
            "targets": dict(self.targets),
            "absent_reasons": dict(self.absent_reasons),
            "target_instants": {
                name: (to_instant_iso(instant) if instant else None)
                for name, instant in self.target_instants.items()
            },
        }


# --------------------------------------------------------------------------- #
# The dataset
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FeatureDataset:
    """Every feature row Phase 3 produced, with its registry and lineage.

    Frozen, and holding an *ordered tuple* of rows. The row order is
    `(entity, instant)`, so it is a property of the data and the configuration
    rather than of the order records happened to arrive in.
    """

    rows: tuple[FeatureRow, ...] = ()
    registry: FeatureRegistry | None = None
    config: FeatureConfig | None = None
    dataset: DatasetDescriptor | None = None
    #: Measurement key (`location|domain|quantity`) -> the unit Phase 2 left it in.
    units: Mapping[str, str] = field(default_factory=dict)
    #: Measurement key -> whether that unit is interpretable.
    source_unit_understood: Mapping[str, bool] = field(default_factory=dict)
    #: Feature name -> lineage, mirroring the registry and recording the resolved
    #: source unit and cutoff actually applied at build time.
    lineage: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    #: Target column name -> its lineage.
    target_lineage: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    #: Feature name -> why it could not be built for any entity.
    unavailable: Mapping[str, str] = field(default_factory=dict)
    #: Per-feature `(cause -> count)` of absent values.
    absent_causes: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    #: Per-feature count of present values.
    present_counts: Mapping[str, int] = field(default_factory=dict)
    #: Per-target count of present values.
    target_counts: Mapping[str, int] = field(default_factory=dict)
    #: Rows per split.
    split_counts: Mapping[str, int] = field(default_factory=dict)
    #: Rows per split carrying at least one target.
    supervised_counts: Mapping[str, int] = field(default_factory=dict)
    #: Per-entity row counts.
    entity_counts: Mapping[str, int] = field(default_factory=dict)
    #: Per-split origin and target bounds, for a reader confirming the split.
    split_bounds: Mapping[str, Any] = field(default_factory=dict)
    #: Rows removed by a policy, keyed by the policy that removed them.
    dropped: Mapping[str, int] = field(default_factory=dict)
    #: Findings from the runtime point-in-time audit.
    leakage_findings: tuple[str, ...] = ()

    # --- shape --------------------------------------------------------------

    @property
    def feature_columns(self) -> tuple[str, ...]:
        """Column order for the feature matrix: the registry's order."""
        return self.registry.names if self.registry is not None else ()

    @property
    def target_columns(self) -> tuple[str, ...]:
        """Column order for the target matrix: configuration horizon order."""
        if self.config is None:
            return ()
        return tuple(
            target_name(self.config.target_quantity, seconds)
            for seconds in self.config.target_seconds
        )

    def __len__(self) -> int:
        return len(self.rows)

    def by_split(self, split: str) -> tuple[FeatureRow, ...]:
        return tuple(row for row in self.rows if row.split == split)

    def supervised(self, split: str | None = None) -> tuple[FeatureRow, ...]:
        """Rows that carry a target, optionally restricted to one split.

        Filtering is explicit and opt-in rather than automatic: a row without a
        target is not bad data — it is a warm-up or tail row — and deleting it
        before a reader has seen the count would be the silent removal this project
        refuses to do. The count is in `report.rows_without_target` either way.
        """
        rows = self.rows if split is None else self.by_split(split)
        return tuple(row for row in rows if row.has_target())

    def supervised_by_split(self) -> dict[str, tuple[FeatureRow, ...]]:
        return {
            split: self.supervised(split)
            for split in SPLITS
            if split in self.split_counts
        }

    # --- matrices -----------------------------------------------------------

    def feature_matrix(
        self, rows: Sequence[FeatureRow] | None = None
    ) -> tuple[tuple[float | None, ...], ...]:
        """Row-major feature values in `feature_columns` order.

        Plain tuples of `float | None` rather than a NumPy array: Phase 3 has no
        dependency on NumPy, `None` survives as a genuine absence instead of
        becoming a `NaN` that later code must remember to special-case, and Phase 4
        is where a dense matrix belongs.
        """
        chosen = self.rows if rows is None else rows
        columns = self.feature_columns
        return tuple(tuple(row.values.get(name) for name in columns) for row in chosen)

    def target_matrix(
        self, rows: Sequence[FeatureRow] | None = None
    ) -> tuple[tuple[float | None, ...], ...]:
        chosen = self.rows if rows is None else rows
        columns = self.target_columns
        return tuple(tuple(row.targets.get(name) for name in columns) for row in chosen)

    def identity_matrix(
        self, rows: Sequence[FeatureRow] | None = None
    ) -> tuple[tuple[str, ...], ...]:
        """`(entity, instant, split)` per row — the non-numeric columns."""
        chosen = self.rows if rows is None else rows
        return tuple((row.entity, to_instant_iso(row.instant), row.split) for row in chosen)

    def column(self, name: str) -> tuple[float | None, ...]:
        """One feature column, in row order. Raises for an unknown name."""
        if self.registry is None or name not in self.registry:
            raise KeyError(f"no feature column {name!r} in this dataset")
        return tuple(row.values.get(name) for row in self.rows)

    # --- honesty ------------------------------------------------------------

    @property
    def is_synthetic(self) -> bool:
        """Whether the source data is synthetic.

        The dataset descriptor wins whenever it says anything. Only when it is
        silent *and* the data is visibly unclassified — no descriptor, or a
        descriptor whose type is `unknown` — does the presence of an
        uninterpretable unit tip this to `True`.

        That is deliberately the conservative direction. A tidy synthetic dataset
        with clean units must never be reported as real, and a real dataset whose
        descriptor says so is never second-guessed on the strength of one unit
        string.
        """
        if self.dataset is not None:
            if self.dataset.dataset_type == DATASET_TYPE_SYNTHETIC:
                return True
            if self.dataset.dataset_type != DATASET_TYPE_UNKNOWN:
                return False
        return any(not is_convertible(unit) for unit in self.units.values() if unit)

    def disclaimer(self) -> str | None:
        """The disclaimer a Phase 4 consumer must carry.

        Never `None` for a synthetic or unclassified source, because a feature
        dataset derived from demo data that reaches a model with no label is the
        failure this whole package is organised against.
        """
        if self.dataset is not None:
            if self.dataset.disclaimer:
                return self.dataset.disclaimer
            if self.dataset.dataset_type == DATASET_TYPE_SYNTHETIC:
                return SYNTHETIC_DATA_DISCLAIMER
            if self.dataset.dataset_type != DATASET_TYPE_UNKNOWN:
                return None
        return UNVERIFIED_DATA_DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": FEATURE_CONTRACT_VERSION,
            "rows": len(self.rows),
            "feature_columns": list(self.feature_columns),
            "target_columns": list(self.target_columns),
            "units": dict(sorted(self.units.items())),
            "source_unit_understood": dict(sorted(self.source_unit_understood.items())),
            "lineage": {name: dict(info) for name, info in sorted(self.lineage.items())},
            "target_lineage": {
                name: dict(info) for name, info in sorted(self.target_lineage.items())
            },
            "unavailable": dict(sorted(self.unavailable.items())),
            "absent_causes": {
                name: dict(sorted(causes.items()))
                for name, causes in sorted(self.absent_causes.items())
            },
            "present_counts": dict(sorted(self.present_counts.items())),
            "target_counts": dict(sorted(self.target_counts.items())),
            "split_counts": dict(sorted(self.split_counts.items())),
            "supervised_counts": dict(sorted(self.supervised_counts.items())),
            "entity_counts": dict(sorted(self.entity_counts.items())),
            "split_bounds": dict(sorted(self.split_bounds.items())),
            "dropped": dict(sorted(self.dropped.items())),
            "leakage_findings": list(self.leakage_findings),
            "is_synthetic": self.is_synthetic,
            "disclaimer": self.disclaimer(),
        }


@dataclass(frozen=True)
class ModelReadyDataset:
    """The Phase 3 to Phase 4 handoff.

    A Phase 2 `PreprocessingResult` is the Phase 2 to Phase 3 handoff, and it carries
    exactly what Phase 3 needs. This carries exactly what Phase 4 needs, and states
    the same things: the rows, the contract version, the column order, per-column
    lineage and units, the split each row belongs to, and the disclaimer that
    travels with the result.

    It carries nothing Phase 4 must not have yet — no fitted scaler, no fitted
    imputer, no chosen algorithm, no score. Fitting anything on these rows before
    the split would put test information into the model's inputs, which is why none
    of it lives here.
    """

    dataset: FeatureDataset
    contract_version: str = FEATURE_CONTRACT_VERSION

    @property
    def feature_columns(self) -> tuple[str, ...]:
        return self.dataset.feature_columns

    @property
    def target_columns(self) -> tuple[str, ...]:
        return self.dataset.target_columns

    def to_dict(self) -> dict[str, Any]:
        """The machine-readable form, including one real sample row per split.

        The `samples` entries are the shape a consumer can rely on: identity
        columns, timestamp, features, targets, metadata. They are real rows, not
        illustrations, so a reader checking the contract is checking the data.
        """
        payload = self.dataset.to_dict()
        payload["samples"] = {
            split: [row.to_dict() for row in rows[:1]]
            for split, rows in self.dataset.supervised_by_split().items()
            if rows
        }
        payload["lineage_rows"] = [
            {"feature": name, **dict(self.dataset.lineage.get(name) or {})}
            for name in self.feature_columns
        ]
        payload["target_lineage_rows"] = [
            {"target": name, **dict(self.dataset.target_lineage.get(name) or {})}
            for name in self.target_columns
        ]
        return payload

    def describe(self) -> str:
        lines = [
            f"Model-ready feature dataset (contract {self.contract_version})",
            f"  rows              : {len(self.dataset)}",
            "  supervised rows   : "
            f"{sum(len(r) for r in self.dataset.supervised_by_split().values())}",
            f"  feature columns   : {len(self.feature_columns)}",
            f"  target columns    : {', '.join(self.target_columns) or '(none)'}",
            "  per split         : "
            + ", ".join(f"{k}={v}" for k, v in sorted(self.dataset.split_counts.items())),
            f"  synthetic         : {self.dataset.is_synthetic}",
        ]
        disclaimer = self.dataset.disclaimer()
        if disclaimer:
            lines.append(f"  disclaimer        : {disclaimer}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FeatureQualityReport:
    """What Phase 3 did to the data, and what a reviewer must remember.

    Read `rows_built - sum(dropped.values()) == rows_retained` first. Every other
    number here is a breakdown of one of those, and a report whose parts do not add
    up to its whole is the class of bug this object exists to make visible.
    """

    config: FeatureConfig
    registry: FeatureRegistry
    records_in: int = 0
    dataset: DatasetDescriptor | None = None
    entities: tuple[str, ...] = ()
    measurements: tuple[str, ...] = ()
    rows_built: int = 0
    rows_retained: int = 0
    rows_without_target: int = 0
    #: Policy name -> rows it removed.
    dropped: Mapping[str, int] = field(default_factory=dict)
    #: Feature name -> number of present values.
    feature_counts: Mapping[str, int] = field(default_factory=dict)
    #: Feature name -> `(cause -> count)` of absent values.
    absent_causes: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    #: Target column -> present count.
    target_counts: Mapping[str, int] = field(default_factory=dict)
    #: Rows per split, and rows per split carrying a target.
    split_counts: Mapping[str, int] = field(default_factory=dict)
    supervised_counts: Mapping[str, int] = field(default_factory=dict)
    #: Rows per entity.
    entity_counts: Mapping[str, int] = field(default_factory=dict)
    #: Measurement key -> unit Phase 2 left it in.
    units: Mapping[str, str] = field(default_factory=dict)
    #: Series -> cadence, as Phase 3 resolved it.
    cadence: Mapping[str, Cadence] = field(default_factory=dict)
    #: Series whose cadence was never established.
    unknown_cadence: tuple[str, ...] = ()
    #: Series whose established cadence sits over real gaps.
    irregular_cadence: tuple[str, ...] = ()
    #: Features declared but never built, with the reason each was unavailable.
    unavailable: Mapping[str, str] = field(default_factory=dict)
    #: Records excluded from features because Phase 2 marked them filled.
    filled_records_excluded: int = 0
    #: Records whose `dataset_type` says the data is synthetic.
    synthetic_records: int = 0
    leakage: Phase3LeakageAudit = field(default_factory=Phase3LeakageAudit)
    notes: tuple[FeatureNote, ...] = ()

    # --- derived ------------------------------------------------------------

    @property
    def errors(self) -> tuple[FeatureNote, ...]:
        return tuple(note for note in self.notes if note.is_error)

    @property
    def warnings(self) -> tuple[FeatureNote, ...]:
        return tuple(note for note in self.notes if note.severity == SEVERITY_WARNING)

    @property
    def infos(self) -> tuple[FeatureNote, ...]:
        return tuple(note for note in self.notes if note.severity == SEVERITY_INFO)

    @property
    def is_synthetic(self) -> bool:
        if self.dataset is not None and self.dataset.dataset_type == DATASET_TYPE_SYNTHETIC:
            return True
        return self.synthetic_records > 0

    @property
    def disclaimer(self) -> str | None:
        if self.dataset is not None and self.dataset.disclaimer:
            return self.dataset.disclaimer
        if self.is_synthetic:
            return SYNTHETIC_DATA_DISCLAIMER
        return UNVERIFIED_DATA_DISCLAIMER

    @property
    def rows_reconciled(self) -> bool:
        """Whether every built row is either retained or accounted for as dropped."""
        return self.rows_built - sum(self.dropped.values()) == self.rows_retained

    @property
    def completed(self) -> bool:
        """A run that produced rows, reconciled them, and passed its leakage audit."""
        return (
            not self.errors
            and self.rows_retained > 0
            and self.rows_reconciled
            and self.leakage.ok
        )

    # --- serialisation ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "phase3-feature-engineering",
            "completed": self.completed,
            "trains_models": False,
            "disclaimer": self.disclaimer,
            "config": self.config.to_dict(),
            "registry": self.registry.to_dict(),
            "counts": {
                "records_in": self.records_in,
                "entities": len(self.entities),
                "measurements": len(self.measurements),
                "features_declared": len(self.registry),
                "features_unavailable": len(self.unavailable),
                "rows_built": self.rows_built,
                "rows_retained": self.rows_retained,
                "rows_without_target": self.rows_without_target,
                "rows_reconciled": self.rows_reconciled,
                "dropped": dict(sorted(self.dropped.items())),
                "split": dict(self.split_counts),
                "supervised": dict(self.supervised_counts),
                "entities_detail": dict(sorted(self.entity_counts.items())),
                "filled_records_excluded": self.filled_records_excluded,
                "synthetic_records": self.synthetic_records,
            },
            "units": dict(sorted(self.units.items())),
            "cadence": {
                series: entry.to_dict() for series, entry in sorted(self.cadence.items())
            },
            "unknown_cadence": list(self.unknown_cadence),
            "irregular_cadence": list(self.irregular_cadence),
            "unavailable": dict(sorted(self.unavailable.items())),
            "feature_counts": dict(sorted(self.feature_counts.items())),
            "absent_causes": {
                name: dict(sorted(causes.items()))
                for name, causes in sorted(self.absent_causes.items())
            },
            "target_counts": dict(sorted(self.target_counts.items())),
            "leakage": self.leakage.to_dict(),
            "notes": [note.to_dict() for note in self.notes],
        }

    def describe(self) -> str:
        lines = [
            f"Feature engineering report ({self.config.subject}):",
            f"  records in       : {self.records_in}",
            f"  entities         : {len(self.entities)}  {list(self.entities)}",
            f"  measurements     : {len(self.measurements)}",
            f"  features built   : {len(self.registry) - len(self.unavailable)}"
            f" of {len(self.registry)} declared"
            + (f"  (unavailable: {sorted(self.unavailable)})" if self.unavailable else ""),
            f"  rows built       : {self.rows_built}",
            f"  rows retained    : {self.rows_retained} (reconciled: {self.rows_reconciled})",
        ]
        if self.dropped:
            lines.append(
                "  rows dropped     : "
                + ", ".join(f"{k}={v}" for k, v in sorted(self.dropped.items()))
            )
        lines.append(f"  rows w/o target  : {self.rows_without_target}")
        lines.append(
            "  per split        : "
            + ", ".join(f"{k}={v}" for k, v in sorted(self.split_counts.items()))
        )
        if self.absent_causes:
            worst = sorted(
                ((name, sum(causes.values())) for name, causes in self.absent_causes.items()),
                key=lambda pair: (-pair[1], pair[0]),
            )[:5]
            lines.append(
                "  most absent      : " + ", ".join(f"{name}={count}" for name, count in worst)
            )
        if self.unknown_cadence:
            lines.append(
                "  cadence unknown  : "
                + ", ".join(self.unknown_cadence)
                + "  (coverage treated as unassessable, i.e. unmet)"
            )
        if self.irregular_cadence:
            lines.append("  cadence irregular: " + ", ".join(self.irregular_cadence))
        lines.append(
            f"  filled excluded  : {self.filled_records_excluded} record(s) whose value came from "
            "a gap policy rather than an observation"
        )
        lines.append(
            f"  leakage audit    : ok={self.leakage.ok} ({len(self.leakage.records)} check(s))"
        )
        lines.append(
            f"  synthetic        : {self.is_synthetic} ({self.synthetic_records} record(s))"
        )
        lines.append(
            f"  errors/warnings  : {len(self.errors)}/{len(self.warnings)}"
        )
        for note in self.notes:
            lines.append(f"    {note.describe()}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# The result
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FeatureResult:
    """What Phase 3 hands to Phase 4.

    Three parts and no fourth: the rows, the report describing them, and the
    registry defining them. `contract` is the same rows packaged with the column
    order and lineage a consumer needs, so a caller does not have to know which of
    the three to reach for.
    """

    dataset: FeatureDataset
    report: FeatureQualityReport

    @property
    def registry(self) -> FeatureRegistry | None:
        return self.dataset.registry

    @property
    def contract(self) -> ModelReadyDataset:
        return ModelReadyDataset(dataset=self.dataset)

    @property
    def is_synthetic(self) -> bool:
        return self.report.is_synthetic

    @property
    def disclaimer(self) -> str | None:
        return self.report.disclaimer

    @property
    def completed(self) -> bool:
        return self.report.completed

    def __len__(self) -> int:
        return len(self.dataset)

    def by_split(self, split: str) -> tuple[FeatureRow, ...]:
        return self.dataset.by_split(split)

    def to_dict(self) -> dict[str, Any]:
        return {"report": self.report.to_dict(), "contract": self.contract.to_dict()}

    def describe(self) -> str:
        return self.report.describe()


# --------------------------------------------------------------------------- #
# The pipeline
# --------------------------------------------------------------------------- #

#: Causes that mean "the data is not there", as opposed to "the data had not
#: arrived yet". A warm-up row is a statement about the beginning of the record; a
#: missing-source row is a statement about a hole in it. Policies treat them
#: separately, and `rows_without_target` is counted separately again.
GAP_CAUSES = frozenset(
    {
        CAUSE_MISSING_SOURCE,
        CAUSE_INSUFFICIENT,
        CAUSE_UNDETERMINED_UNIT,
        CAUSE_UNIT_MISMATCH,
        CAUSE_NOT_APPLICABLE,
        CAUSE_NO_SOURCE,
        CAUSE_CUTOFF_UNDEFINED,
    }
)


@dataclass(frozen=True)
class _TruncatedResult:
    """A Phase 2 result cut off at an instant, for the behavioural leakage audit.

    Carries only what `build_features` reads. Deliberately *not* a
    `PreprocessingResult`: reusing the real class would mean re-running Phase 2 or
    constructing one with a report that lies about what was in it.
    """

    train: tuple[Observation, ...] = ()
    validation: tuple[Observation, ...] = ()
    test: tuple[Observation, ...] = ()
    report: Any = None

    def __len__(self) -> int:
        return len(self.train) + len(self.validation) + len(self.test)


def _unit_understood(timeline: SeriesTimeline | None) -> bool:
    """Whether this measurement's unit can be interpreted.

    A timeline with mixed units is never "understood": combining `m` and `cm` in one
    series is a Phase 2 finding, and treating the series as if one of them were
    canonical would pick a winner silently.
    """
    if timeline is None or not timeline.has_uniform_unit:
        return False
    return is_convertible(timeline.unit or "")


def _target_columns(config: FeatureConfig) -> tuple[str, ...]:
    if not config.target_quantity:
        return ()
    return tuple(
        target_name(config.target_quantity, seconds) for seconds in config.target_seconds
    )


def _unavailable_features(
    registry: FeatureRegistry,
    timelines: Mapping[str, SeriesTimeline],
) -> dict[str, str]:
    """Declared features for which this dataset holds no source series at all.

    "At all" is the operative phrase: an entity that lacks `discharge` gets
    `CAUSE_NO_SOURCE` on its own rows, which is a different and less alarming
    statement than the configuration declaring a quantity the whole dataset lacks.
    """
    present = {
        (split_measurement_key(key)[1], split_measurement_key(key)[2]) for key in timelines
    }
    out: dict[str, str] = {}
    for definition in registry:
        if definition.operation == OP_CALENDAR:
            continue
        if (definition.source_domain, definition.source_quantity) in present:
            continue
        out[definition.name] = (
            f"no {definition.source_domain}/{definition.source_quantity} series exists in this "
            f"dataset, so {definition.name!r} has no source. No substitute was invented"
        )
    return dict(sorted(out.items()))


def _calendar_exclusion_notes() -> list[FeatureNote]:
    """One info note per calendar component that was deliberately left out.

    Emitted whether or not the configuration would have asked for it, because the
    decision to exclude `day_of_week` is a modelling judgement a reader deserves to
    see rather than infer from a missing column.
    """
    return [
        FeatureNote(
            severity=SEVERITY_INFO,
            code=CODE_CALENDAR_EXCLUDED,
            message=(
                f"calendar component {component!r} is deliberately not emitted: {reason}"
            ),
            subject=component,
        )
        for component in CALENDAR_COMPONENTS
        if component in EXCLUDED_CALENDAR_COMPONENTS
    ]


def build_features(
    result: Any,
    config: FeatureConfig | None = None,
    *,
    dataset: DatasetDescriptor | None = None,
    base_intervals: Mapping[str, float] | None = None,
    subject: str = "phase3_features",
) -> FeatureResult:
    """Run Phase 3 over a Phase 2 `PreprocessingResult`.

    Reads the three split sequences Phase 2 produced, builds one causal timeline per
    measurement, evaluates every declared feature at every origin instant, aligns
    targets forward, assigns rows to splits, and reports what it could not build and
    why.

    Passing no `config` gives the conservative configuration: no imputation,
    full-coverage accumulation requirements, forcing features that may read the
    prediction instant and state features that may not, and missing and warm-up
    values retained with a recorded cause rather than deleted.

    **PHASE 3 DOES NOT TRAIN MODELS.** No parameter is fitted, no algorithm
    selected, no prediction scored and no error metric computed. The only output is
    data and an account of how it was produced.

    Raises `FeatureError` for no records, for zero retained rows, and for a
    `missing_policy` or `warmup_policy` of `error` that met the case it was
    guarding. Nothing is repaired on the way past.
    """
    settings = config if config is not None else FeatureConfig(subject=subject)
    registry = build_registry(settings)

    parts = split_parts(result)
    records = [record for label in SPLITS for record in parts[label]]
    phase_two_report = getattr(result, "report", None)
    descriptor = dataset
    if descriptor is None and phase_two_report is not None:
        descriptor = getattr(phase_two_report, "dataset", None)

    if not records:
        raise FeatureError(
            "Phase 3 received no records. An empty batch is not a dataset, and reporting a "
            "clean run over zero rows would claim a feature build that never happened."
        )

    notes: list[FeatureNote] = [
        FeatureNote(
            severity=SEVERITY_INFO,
            code=CODE_REGISTRY_COMPILED,
            message=(
                f"compiled {len(registry)} feature definition(s) from configuration "
                f"{settings.subject!r}; the registry order is the column order of every matrix"
            ),
        ),
        FeatureNote(
            severity=SEVERITY_INFO,
            code=CODE_NO_IMPUTATION,
            message=(
                "no value was imputed, forward-filled, interpolated or back-filled. Absent "
                "values are absent with a recorded cause. Fitting an imputer is Phase 4's "
                "decision and must happen on training rows only — doing it here would fill "
                "every split before the split existed"
            ),
        ),
    ]

    # --- split integrity ----------------------------------------------------

    for clash in split_collisions(parts):
        notes.append(
            FeatureNote(
                severity=SEVERITY_ERROR,
                code=CODE_LEAKAGE_CHECKED,
                message=(
                    f"{clash}. A record claimed by two splits means the chronological split is "
                    "not disjoint, and no feature dataset can be built on top of it"
                ),
                subject=clash.split()[0],
            )
        )

    # --- cadence ------------------------------------------------------------

    cadence = resolve_cadence(
        records,
        base_intervals=base_intervals,
        published=getattr(phase_two_report, "intervals", None) or {},
    )
    intervals = {
        series: entry.seconds for series, entry in cadence.items() if entry.is_known
    }
    unknown_cadence = tuple(sorted(s for s, e in cadence.items() if not e.is_known))
    irregular_cadence = tuple(
        sorted(s for s, e in cadence.items() if e.is_known and e.regularity < 1.0)
    )
    for series in unknown_cadence:
        notes.append(
            FeatureNote(
                severity=SEVERITY_WARNING,
                code=CODE_CADENCE_UNKNOWN,
                message=(
                    f"{series}: no safe base interval could be established, so the number of "
                    "readings a window should hold is unknowable. Every coverage requirement is "
                    "therefore treated as UNMET rather than assumed satisfied, and a "
                    "one-step-back cutoff falls back to the prediction instant"
                ),
                subject=series,
            )
        )
    for series in irregular_cadence:
        entry = cadence[series]
        notes.append(
            FeatureNote(
                severity=SEVERITY_WARNING,
                code=CODE_CADENCE_IRREGULAR,
                message=(
                    f"{series}: cadence {entry.label} covers only {entry.regularity:.0%} of the "
                    "gaps between readings, so the series has holes in it. Windows over it will "
                    "fail their coverage requirement, which is the honest outcome"
                ),
                subject=series,
            )
        )
    notes.extend(_calendar_exclusion_notes())

    # --- source honesty -----------------------------------------------------

    filled = sum(1 for record in records if record.quality_status == QUALITY_MISSING)
    synthetic_records = sum(
        1 for record in records if record.dataset_type == DATASET_TYPE_SYNTHETIC
    )
    unclassified_records = sum(
        1 for record in records if record.dataset_type == DATASET_TYPE_UNKNOWN
    )
    if filled:
        notes.append(
            FeatureNote(
                severity=SEVERITY_INFO,
                code=CODE_FILLED_SOURCE_EXCLUDED,
                message=(
                    f"{filled} record(s) carried Phase 2's 'missing' quality status and were "
                    "excluded from every feature. A value produced by a gap policy is not an "
                    "observation: feeding it to a lag would teach a model that an imputed number "
                    "was measured, and feeding it to an accumulation would inflate a total"
                ),
            )
        )
    if synthetic_records:
        notes.append(
            FeatureNote(
                severity=SEVERITY_WARNING,
                code=CODE_SYNTHETIC_SOURCE,
                message=(
                    f"{synthetic_records} of {len(records)} record(s) are marked synthetic. "
                    f"{SYNTHETIC_DATA_DISCLAIMER} The arithmetic below is correct for the data it "
                    "was given; it is not evidence that these features carry hydrological signal"
                ),
            )
        )
    elif unclassified_records == len(records):
        notes.append(
            FeatureNote(
                severity=SEVERITY_WARNING,
                code=CODE_SYNTHETIC_SOURCE,
                message=(
                    "every record's dataset_type is 'unknown', so nobody has classified this "
                    f"data. {UNVERIFIED_DATA_DISCLAIMER}"
                ),
            )
        )
    if any(quantity in settings.quantities for quantity in LEVEL_QUANTITIES):
        notes.append(
            FeatureNote(
                severity=SEVERITY_WARNING,
                code=CODE_DATUM_LIMITATION,
                message=(
                    "water-level datum compatibility between locations is unverified. No datum "
                    "conversion is applied and none is invented, so water_level_* features are "
                    "comparable WITHIN one location only. A model trained across stations on raw "
                    "levels is reading each gauge's arbitrary zero as though it were shared. "
                    "water_level_change_* features are unaffected, because a difference cancels "
                    "any datum offset"
                ),
                subject="water_level",
            )
        )

    # --- timelines ----------------------------------------------------------

    timelines = build_timelines(records, base_intervals=intervals)
    grouped = timelines_by_entity(timelines)
    split_indexes = build_split_index(parts)
    units = {key: (timeline.unit or "") for key, timeline in timelines.items()}
    unit_ok = {key: _unit_understood(t) for key, t in timelines.items()}

    for key, understood in sorted(unit_ok.items()):
        if understood:
            continue
        notes.append(
            FeatureNote(
                severity=SEVERITY_WARNING,
                code=CODE_UNIT_UNDETERMINED,
                message=(
                    f"{key}: unit {units[key]!r} is not interpretable, so no conversion, "
                    "comparison or rate may be derived from it. "
                    + (
                        "unit_policy='require_known' therefore leaves every feature on this "
                        "measurement absent."
                        if settings.unit_policy == UNIT_REQUIRE_KNOWN
                        else "unit_policy='flag_undetermined' computes values that are pure "
                        "arithmetic on the raw numbers, and leaves every unit-dependent "
                        "operation absent."
                    )
                ),
                subject=key,
            )
        )

    unavailable = _unavailable_features(registry, timelines)
    for name, reason in sorted(unavailable.items()):
        notes.append(
            FeatureNote(
                severity=SEVERITY_WARNING,
                code=CODE_FEATURE_UNAVAILABLE,
                message=reason,
                subject=name,
            )
        )
    for definition in unavailable_catalogue():
        notes.append(
            FeatureNote(
                severity=SEVERITY_INFO,
                code=CODE_STATIC_UNAVAILABLE,
                message=(
                    f"declared unavailable and deliberately not built: {definition.description} "
                    f"Required source property: {definition.availability_requirement!r}. It is "
                    "reported rather than omitted so the gap stays visible instead of silent"
                ),
                subject=definition.name,
            )
        )

    # --- build rows ---------------------------------------------------------

    calendar_defs = registry.calendar()
    temporal_defs = registry.temporal()
    horizon_labels = ", ".join(
        window_label(seconds) or f"{seconds:g}s" for seconds in settings.target_seconds
    )
    rows: list[FeatureRow] = []
    unassigned = 0
    target_absent = 0
    target_crosses = 0
    coverage_unmet = 0
    skipped_by_unit: set[str] = set()
    flagged_by_unit: set[str] = set()

    for entity in sorted(grouped):
        keys = grouped[entity]
        entity_timelines = [timelines[key] for key in keys]
        origins = entity_instants(entity_timelines)
        index = split_indexes.get(entity)
        target_timeline = _target_timeline(timelines, keys, settings.target_quantity)

        for origin in origins:
            label = index.label_for(origin) if index is not None else None
            if label is None:
                label = SPLIT_UNASSIGNED
                unassigned += 1

            values: dict[str, float | None] = {}
            reasons: dict[str, str] = {}
            read: list[datetime] = []

            for definition in calendar_defs:
                outcome = evaluate(
                    definition, None, origin, settings, unit_is_understood=True
                )
                values[definition.name] = outcome.value
                read.extend(outcome.instants)

            for definition in temporal_defs:
                key = f"{entity}|{definition.source_domain}|{definition.source_quantity}"
                timeline = timelines.get(key)
                if definition.name in unavailable or timeline is None:
                    values[definition.name] = None
                    reasons[definition.name] = CAUSE_NO_SOURCE
                    continue
                understood = unit_ok.get(key, False)
                if settings.unit_policy == UNIT_REQUIRE_KNOWN and not understood:
                    values[definition.name] = None
                    reasons[definition.name] = CAUSE_UNDETERMINED_UNIT
                    skipped_by_unit.add(definition.name)
                    continue
                if not understood:
                    flagged_by_unit.add(definition.name)
                outcome = evaluate(
                    definition, timeline, origin, settings, unit_is_understood=understood
                )
                values[definition.name] = outcome.value
                if outcome.reason is not None:
                    reasons[definition.name] = outcome.reason
                    if outcome.reason == CAUSE_INSUFFICIENT:
                        coverage_unmet += 1
                read.extend(outcome.instants)

            targets: dict[str, float | None] = {}
            target_instants: dict[str, datetime | None] = {}
            for seconds in settings.target_seconds:
                name = target_name(settings.target_quantity, seconds)
                if target_timeline is None:
                    targets[name] = None
                    target_instants[name] = None
                    target_absent += 1
                    continue
                outcome = op_target(
                    target_timeline,
                    origin,
                    seconds,
                    settings.target_alignment,
                    settings.target_tolerance_seconds,
                )
                source_instant = outcome.instants[0] if outcome.instants else None
                destination = index.label_for(source_instant) if (
                    index is not None and source_instant is not None
                ) else None
                if outcome.value is None:
                    targets[name] = None
                    target_instants[name] = None
                    target_absent += 1
                elif destination is not None and destination != label:
                    # The answer lives in a later split. Keeping it would hand a
                    # training or validation row a piece of the test period.
                    targets[name] = None
                    target_instants[name] = None
                    target_crosses += 1
                else:
                    targets[name] = outcome.value
                    target_instants[name] = source_instant

            rows.append(
                FeatureRow(
                    entity=entity,
                    instant=origin,
                    split=label,
                    values=dict(values),
                    targets=dict(targets),
                    absent_reasons=dict(reasons),
                    target_instants=dict(target_instants),
                    source_instants=tuple(sorted(set(read))),
                )
            )

    if unassigned:
        notes.append(
            FeatureNote(
                severity=SEVERITY_WARNING,
                code=CODE_ROWS_UNASSIGNED,
                message=(
                    f"{unassigned} origin instant(s) carried no split label from Phase 2. Those "
                    f"rows are kept and labelled {SPLIT_UNASSIGNED!r} rather than deleted, and "
                    "they are excluded from every per-split view"
                ),
            )
        )

    # --- row policies -------------------------------------------------------

    policy_counts: dict[str, int] = {}
    kept = _apply_warmup_policy(rows, settings, policy_counts, CODE_ROWS_DROPPED_WARMUP)
    kept = _apply_missing_policy(kept, settings, policy_counts, CODE_ROWS_DROPPED_MISSING)

    if not kept:
        raise FeatureError(
            "Phase 3 built feature rows but retained none of them. "
            + (
                "Every row was removed by a named policy; set missing_policy='retain' and "
                "warmup_policy='retain' to see them."
                if policy_counts
                else "The dataset produced no prediction origins at all."
            )
        )

    # --- counts -------------------------------------------------------------

    feature_counts: dict[str, int] = {name: 0 for name in registry.names}
    causes: dict[str, dict[str, int]] = {}
    for row in kept:
        for name, value in row.values.items():
            if value is None:
                bucket = causes.setdefault(name, {})
                reason = row.absent_reasons.get(name, CAUSE_MISSING_SOURCE)
                bucket[reason] = bucket.get(reason, 0) + 1
            else:
                feature_counts[name] = feature_counts.get(name, 0) + 1

    target_counts: dict[str, int] = {name: 0 for name in _target_columns(settings)}
    split_counts: dict[str, int] = {}
    supervised_counts: dict[str, int] = {}
    entity_counts: dict[str, int] = {}
    without_target = 0
    for row in kept:
        split_counts[row.split] = split_counts.get(row.split, 0) + 1
        entity_counts[row.entity] = entity_counts.get(row.entity, 0) + 1
        if row.has_target():
            supervised_counts[row.split] = supervised_counts.get(row.split, 0) + 1
        else:
            without_target += 1
        for name, value in row.targets.items():
            if value is not None:
                target_counts[name] = target_counts.get(name, 0) + 1

    split_bounds = _split_bounds(kept)

    # --- lineage ------------------------------------------------------------

    lineage = _feature_lineage(registry, timelines, units, unit_ok, settings)
    target_lineage = _target_lineage_dict(settings, timelines, units)
    notes.append(
        FeatureNote(
            severity=SEVERITY_INFO,
            code=CODE_LINEAGE_EXPORTED,
            message=(
                f"lineage exported for {len(lineage)} feature(s) and {len(target_lineage)} "
                "target column(s), each naming its source domain, source quantity, entity scope, "
                "window, alignment, cutoff policy and the unit actually resolved at build time"
            ),
        )
    )

    # --- narrative ----------------------------------------------------------

    if coverage_unmet:
        notes.append(
            FeatureNote(
                severity=SEVERITY_WARNING,
                code=CODE_ACCUM_COVERAGE,
                message=(
                    f"{coverage_unmet} accumulation or intensity value(s) were withheld because "
                    "their window covered less than "
                    f"{settings.accumulation_min_coverage:g} of the slots the cadence implies. A "
                    "partial sum is smaller than the truth and still looks like a total, so it "
                    "is reported as absent rather than as a number"
                ),
            )
        )
    if target_crosses:
        notes.append(
            FeatureNote(
                severity=SEVERITY_INFO,
                code=CODE_TARGET_CROSSES_SPLIT,
                message=(
                    f"{target_crosses} target value(s) were withheld because the instant they "
                    "were read from carries a different split label from the row's own origin. "
                    "Keeping them would hand a training or validation row an answer from a "
                    "period it must not see"
                ),
            )
        )
    if target_absent:
        notes.append(
            FeatureNote(
                severity=SEVERITY_INFO,
                code=CODE_TARGET_ABSENT,
                message=(
                    f"{target_absent} target value(s) are absent because no reading exists at "
                    f"origin + {horizon_labels} under alignment "
                    f"{settings.target_alignment!r}. The final horizon-length of every series has "
                    "no target by construction, which is why the supervised row count is lower "
                    "than the retained row count"
                ),
            )
        )
    for name in sorted(skipped_by_unit):
        notes.append(
            FeatureNote(
                severity=SEVERITY_WARNING,
                code=CODE_FEATURE_SKIPPED_UNIT,
                message=(
                    "left absent on every row because its source unit is not interpretable and "
                    "unit_policy='require_known'"
                ),
                subject=name,
            )
        )
    for name in sorted(flagged_by_unit - skipped_by_unit):
        notes.append(
            FeatureNote(
                severity=SEVERITY_WARNING,
                code=CODE_FEATURE_FLAGGED_UNIT,
                message=(
                    "computed on a source unit that is not interpretable. The arithmetic is exact "
                    "on the raw numbers, but the value's physical meaning is unestablished. Every "
                    "unit-dependent operation over this feature stayed absent"
                ),
                subject=name,
            )
        )
    notes.append(
        FeatureNote(
            severity=SEVERITY_INFO,
            code=CODE_ROWS_BUILT,
            message=(
                f"built {len(rows)} row(s) across {len(entity_counts)} entity/entities and "
                f"{len(registry)} declared column(s), of which "
                f"{len(registry) - len(unavailable)} could be sourced"
            ),
        )
    )
    notes.append(
        FeatureNote(
            severity=SEVERITY_INFO,
            code=CODE_ROWS_RETAINED,
            message=(
                f"retained {len(kept)} row(s), of which {sum(supervised_counts.values())} carry at "
                f"least one target. Removed: "
                + (
                    ", ".join(f"{k}={v}" for k, v in sorted(policy_counts.items()))
                    if policy_counts
                    else "nothing"
                )
            ),
        )
    )
    notes.append(
        FeatureNote(
            severity=SEVERITY_INFO,
            code=CODE_FEATURES_BUILT,
            message=(
                "features, targets, identity columns and metadata are kept in separate fields of "
                "every row, so a target cannot reach the feature matrix by accident"
            ),
        )
    )
    notes.append(
        FeatureNote(
            severity=SEVERITY_INFO,
            code=CODE_ORDERED,
            message=(
                "rows are ordered by (entity, prediction instant) and columns by the registry. "
                "Neither order depends on the order records arrived in, on a set, or on dict "
                "iteration, so a permuted input produces byte-identical output"
            ),
        )
    )
    notes.append(
        FeatureNote(
            severity=SEVERITY_INFO,
            code=CODE_DETERMINISM,
            message=(
                "every name, position, count and note in this report is derived from the "
                "configuration and the data alone, so the same inputs reproduce this report "
                "exactly, including the order of its notes"
            ),
        )
    )

    audit = _audit(kept, registry, settings, split_indexes)

    # --- assemble -----------------------------------------------------------

    dataset_object = FeatureDataset(
        rows=tuple(kept),
        registry=registry,
        config=settings,
        dataset=descriptor,
        units=dict(sorted(units.items())),
        source_unit_understood=dict(sorted(unit_ok.items())),
        lineage=lineage,
        target_lineage=target_lineage,
        unavailable=dict(sorted(unavailable.items())),
        absent_causes=_sorted_causes(causes),
        present_counts=dict(sorted(feature_counts.items())),
        target_counts=dict(sorted(target_counts.items())),
        split_counts=dict(sorted(split_counts.items())),
        supervised_counts=dict(sorted(supervised_counts.items())),
        entity_counts=dict(sorted(entity_counts.items())),
        split_bounds=split_bounds,
        dropped=dict(sorted(policy_counts.items())),
        leakage_findings=tuple(
            f"{name}: {detail}" for name, _passed, detail in audit.failures
        ),
    )

    report = FeatureQualityReport(
        config=settings,
        registry=registry,
        records_in=len(records),
        dataset=descriptor,
        entities=tuple(sorted(grouped)),
        measurements=tuple(sorted(timelines)),
        rows_built=len(rows),
        rows_retained=len(kept),
        rows_without_target=without_target,
        dropped=dict(sorted(policy_counts.items())),
        feature_counts=dict(sorted(feature_counts.items())),
        absent_causes=_sorted_causes(causes),
        target_counts=dict(sorted(target_counts.items())),
        split_counts=dict(sorted(split_counts.items())),
        supervised_counts=dict(sorted(supervised_counts.items())),
        entity_counts=dict(sorted(entity_counts.items())),
        units=dict(sorted(units.items())),
        cadence=dict(sorted(cadence.items())),
        unknown_cadence=unknown_cadence,
        irregular_cadence=irregular_cadence,
        unavailable=dict(sorted(unavailable.items())),
        filled_records_excluded=filled,
        synthetic_records=synthetic_records,
        leakage=audit,
        notes=_sorted_notes(notes),
    )

    return FeatureResult(dataset=dataset_object, report=report)


# --------------------------------------------------------------------------- #
# Pipeline helpers
# --------------------------------------------------------------------------- #


def _target_timeline(
    timelines: Mapping[str, SeriesTimeline],
    keys: Sequence[str],
    quantity: str,
) -> SeriesTimeline | None:
    """The series this entity's target is read from, or `None` if there is none."""
    if not quantity:
        return None
    for key in keys:
        if key.endswith(f"|{quantity}"):
            return timelines[key]
    return None


def _apply_warmup_policy(
    rows: Sequence[FeatureRow],
    config: FeatureConfig,
    policy_counts: dict[str, int],
    code: str,
) -> list[FeatureRow]:
    """Drop or reject rows whose long windows reach back before the data began.

    Warm-up is a normal condition at the start of a series, not bad data: a 24-hour
    rainfall accumulation cannot exist at hour three of a gauge that has been
    reporting for three hours. So the default is to keep the row and mark the
    feature absent, and both other policies say so out loud rather than deleting
    quietly. `error` exists for the case where a downstream consumer genuinely
    cannot accept a partially warm row and needs to hear about it.
    """
    if config.warmup_policy == WARMUP_RETAIN:
        return list(rows)
    offenders: list[str] = []
    keep: list[FeatureRow] = []
    for row in rows:
        culprits = sorted(
            name
            for name, reason in row.absent_reasons.items()
            if reason == CAUSE_WARMUP
        )
        if not culprits:
            keep.append(row)
            continue
        offenders.append(
            f"{row.entity} {to_instant_iso(row.instant)} [{', '.join(culprits[:4])}]"
        )
    if config.warmup_policy == WARMUP_ERROR and offenders:
        raise FeatureError(
            f"warmup_policy='error' and {len(offenders)} row(s) were still in warm-up. Warm-up "
            "is a normal condition at the start of a series, not bad data: a 24-hour "
            "accumulation cannot exist at hour three. Supply more history, set "
            "warmup_policy='retain' and let Phase 4 decide how to handle the absence, or use "
            "'drop_rows' to remove them explicitly. First offenders: " + "; ".join(offenders[:5])
        )
    policy_counts[code] = policy_counts.get(code, 0) + len(offenders)
    return keep


def _apply_missing_policy(
    rows: Sequence[FeatureRow],
    config: FeatureConfig,
    policy_counts: dict[str, int],
    code: str,
) -> list[FeatureRow]:
    """Drop or reject rows that lost a source reading the window actually reached.

    Deliberately distinct from warm-up. A gap is a statement about the *inside* of a
    record — the gauge was there and then was not — so a caller who wants to be told
    about outages gets a different count from one who wants to be told about series
    that have not warmed up yet.

    `retain` is the default and it retains without filling: the value stays `None`.
    Filling here would fill every split at once, before the split existed, which is
    the single most common way imputed values leak test information into training.
    """
    if config.missing_policy == MISSING_RETAIN:
        return list(rows)
    offenders: list[str] = []
    keep: list[FeatureRow] = []
    for row in rows:
        culprits = sorted(
            name
            for name, reason in row.absent_reasons.items()
            if reason in GAP_CAUSES
        )
        if not culprits:
            keep.append(row)
            continue
        offenders.append(
            f"{row.entity} {to_instant_iso(row.instant)} [{', '.join(culprits[:4])}]"
        )
    if config.missing_policy == MISSING_ERROR and offenders:
        raise FeatureError(
            f"missing_policy='error' and {len(offenders)} row(s) still had an absent source "
            "value. Fix the upstream gap handling or set missing_policy='retain'; silently "
            "filling these here would fill them before the split, which is how imputed values "
            "reach the training set from the test period. First offenders: "
            + "; ".join(offenders[:5])
        )
    policy_counts[code] = policy_counts.get(code, 0) + len(offenders)
    return keep


def _sorted_causes(causes: Mapping[str, Mapping[str, int]]) -> dict[str, dict[str, int]]:
    return {
        name: dict(sorted(bucket.items()))
        for name, bucket in sorted(causes.items())
        if bucket
    }


def _split_bounds(rows: Sequence[FeatureRow]) -> dict[str, dict[str, Any]]:
    """Per-split origin and target instants, so a reader can confirm the split."""
    out: dict[str, dict[str, Any]] = {}
    for label in SPLITS + (SPLIT_UNASSIGNED,):
        here = [row for row in rows if row.split == label]
        if not here:
            continue
        targets = sorted(
            instant for row in here for instant in row.target_timestamps.values()
        )
        out[label] = {
            "rows": len(here),
            "origin_first": to_instant_iso(min(row.instant for row in here)),
            "origin_last": to_instant_iso(max(row.instant for row in here)),
            "target_first": to_instant_iso(targets[0]) if targets else None,
            "target_last": to_instant_iso(targets[-1]) if targets else None,
        }
    return out


def _feature_lineage(
    registry: FeatureRegistry,
    timelines: Mapping[str, SeriesTimeline],
    units: Mapping[str, str],
    unit_ok: Mapping[str, bool],
    config: FeatureConfig,
) -> dict[str, dict[str, Any]]:
    """Registry lineage, plus what this particular build resolved.

    The registry already knows the window, the operation and the entity scope. What
    only the build knows is which units the sources actually carried and which
    cutoff policy was applied — so those are added here, and a reader auditing a
    fitted model can tell "3-hour accumulation of rainfall" from "3-hour accumulation
    of a column labelled UNDETERMINED" without guessing.
    """
    out: dict[str, dict[str, Any]] = {}
    for definition in registry:
        entry = dict(definition.lineage.to_dict())
        if definition.is_temporal:
            keys = [
                key
                for key in timelines
                if key.endswith(f"|{definition.source_quantity}")
                and f"|{definition.source_domain}|" in key
            ]
            entry["resolved_source_units"] = sorted(
                {units[key] for key in keys if units.get(key)}
            )
            entry["source_unit_understood"] = (
                all(unit_ok.get(key, False) for key in keys) if keys else None
            )
            entry["source_measurement_count"] = len(keys)
            entry["cutoff_policy"] = config.cutoff_for(definition.source_quantity)
        out[definition.name] = entry
    return dict(sorted(out.items()))


def _target_lineage_dict(
    config: FeatureConfig,
    timelines: Mapping[str, SeriesTimeline],
    units: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Target lineage, stating plainly that a target is not available at prediction time."""
    if not config.target_quantity:
        return {}
    source_keys = [key for key in timelines if key.endswith(f"|{config.target_quantity}")]
    found = sorted({units[key] for key in source_keys if units.get(key)})
    out: dict[str, dict[str, Any]] = {}
    for seconds in config.target_seconds:
        name = target_name(config.target_quantity, seconds)
        out[name] = TargetLineage(
            source=config.target_quantity,
            quantity=config.target_quantity,
            horizon_seconds=seconds,
            horizon_label=window_label(seconds) or f"{seconds:g}s",
            entity_scope="entity",
            unit=found[0] if len(found) == 1 else None,
            alignment=config.target_alignment,
        ).to_dict()
    return dict(sorted(out.items()))


def _audit(
    kept: Sequence[FeatureRow],
    registry: FeatureRegistry,
    config: FeatureConfig,
    split_indexes: Mapping[str, SplitIndex],
) -> Phase3LeakageAudit:
    """Check the produced rows against the point-in-time contract.

    Each check is recorded by name. The first two are structural facts about the
    rows — every feature read at or before its own origin, every target strictly
    after it — and would fail the moment an operation reached past its cutoff. The
    rest are invariants a reader depends on: targets separated from features, target
    instants inside their own split, and an order that does not depend on arrival
    order.
    """
    audit = Phase3LeakageAudit()

    future = [
        f"{row.entity} {to_instant_iso(row.instant)}"
        for row in kept
        if any(instant > row.instant for instant in row.source_instants)
    ]
    audit.record(
        "features_read_at_or_before_origin",
        not future,
        "no feature read any instant later than its own prediction origin"
        if not future
        else f"{len(future)} row(s) read the future, e.g. {future[0]}",
    )

    backwards = [
        f"{row.entity} {to_instant_iso(row.instant)} {name}"
        for row in kept
        for name, instant in row.target_instants.items()
        if instant is not None and instant <= row.instant
    ]
    audit.record(
        "targets_strictly_after_origin",
        not backwards,
        "every target instant is strictly later than the row's origin, so no target is "
        "reachable from its own feature row"
        if not backwards
        else f"{len(backwards)} target(s) were not in the future, e.g. {backwards[0]}",
    )

    overlap = set(registry.names) & set(_target_columns(config))
    audit.record(
        "target_columns_disjoint_from_features",
        not overlap,
        "no column name is both a feature and a target"
        if not overlap
        else f"overlapping names: {sorted(overlap)}",
    )

    # Only *retained* targets are examined. A target column set to `None` is an
    # absent target, not a mislabelled one, and counting those here would make the
    # check fire on every tail row and hide the rows it is meant to catch.
    unlabelled = [
        f"{row.entity} {to_instant_iso(row.instant)} {name}"
        for row in kept
        for name, instant in row.target_timestamps.items()
        if row.split == SPLIT_UNASSIGNED
        or instant not in split_indexes.get(row.entity, SplitIndex(row.entity)).labels
    ]
    audit.record(
        "retained_target_instants_carry_a_split_label",
        not unlabelled,
        "every retained target instant resolves to a split label on the same entity, so the "
        "row's own split was a real comparison rather than an assumption"
        if not unlabelled
        else f"{len(unlabelled)} target(s) had no split label, e.g. {unlabelled[0]}",
    )

    crossing = [
        f"{row.entity} {to_instant_iso(row.instant)} {name}"
        for row in kept
        for name, instant in row.target_timestamps.items()
        if split_indexes.get(row.entity, SplitIndex(row.entity)).labels.get(instant, row.split)
        != row.split
    ]
    audit.record(
        "targets_inside_own_split",
        not crossing,
        "every retained target instant carries the same split label as its row"
        if not crossing
        else f"{len(crossing)} target(s) cross a split boundary, e.g. {crossing[0]}",
    )

    ordered = all(
        (a.entity, a.instant) < (b.entity, b.instant) for a, b in zip(kept, kept[1:])
    )
    audit.record(
        "row_order_is_entity_then_instant",
        ordered,
        "rows are strictly ordered by (entity, prediction instant)"
        if ordered
        else "rows are not in (entity, instant) order",
    )

    audit.record(
        "column_order_is_registry_order",
        registry.names == tuple(d.name for d in registry.definitions),
        f"{len(registry)} column(s) in registry order",
    )

    audit.record(
        "imputation_absent",
        True,
        "no feature value was filled: every None in the matrix is a recorded absent value, "
        "and the audit cannot detect a fill, which is why the policy is asserted by "
        "construction rather than by check",
    )

    return audit


def audit_point_in_time(
    result: Any,
    config: FeatureConfig | None = None,
    *,
    probes: int = 5,
    base_intervals: Mapping[str, float] | None = None,
) -> tuple[str, ...]:
    """Decide the leakage question by experiment rather than by argument.

    The structural check inside `_audit` proves no operation was handed an instant
    later than its cutoff. This proves the stronger, behavioural claim: **a feature
    computed at time `T` is unchanged when the data after `T` is deleted.**

    For each probe instant the records after it are removed, features are rebuilt from
    the truncated history, and every row at or before the probe is compared against
    the full build. Any difference is a feature that read the future, whatever its
    window claims. A feature that passes cannot be reading ahead, because there is
    nothing left ahead to read.

    Returns a tuple of findings, empty when the audit passes.
    """
    settings = config if config is not None else FeatureConfig()
    full = build_features(result, settings, base_intervals=base_intervals)
    reference = {(row.entity, row.instant): row for row in full.dataset.rows}
    instants = sorted({row.instant for row in full.dataset.rows})
    if not instants:
        return ("no rows were built, so there is nothing to audit",)

    step = max(1, len(instants) // max(1, probes))
    probe_points = instants[::step][:probes] if step < len(instants) else instants

    findings: list[str] = []
    parts = split_parts(result)
    for probe in probe_points:
        truncated = _TruncatedResult(
            **{
                label: tuple(
                    record
                    for record in records
                    if parse_instant(record.observed_at) <= probe
                )
                for label, records in parts.items()
            },
            report=getattr(result, "report", None),
        )
        rebuilt = build_features(truncated, settings, base_intervals=base_intervals)
        for row in rebuilt.dataset.rows:
            original = reference.get((row.entity, row.instant))
            if original is None:
                findings.append(
                    f"{row.entity} {to_instant_iso(row.instant)} exists in the truncated build "
                    "but not in the full build"
                )
                continue
            for name, value in row.values.items():
                if original.values.get(name) != value:
                    findings.append(
                        f"{row.entity} {to_instant_iso(row.instant)} feature {name!r} changed from "
                        f"{original.values.get(name)!r} to {value!r} once data after "
                        f"{to_instant_iso(probe)} was deleted: it was reading the future"
                    )
    return tuple(findings[:20])


__all__ = [
    "ABSENT_CAUSES",
    "ALL_CODES",
    "CODE_ACCUM_COVERAGE",
    "CODE_CADENCE_IRREGULAR",
    "CODE_CADENCE_UNKNOWN",
    "CODE_CALENDAR_EXCLUDED",
    "CODE_DATUM_LIMITATION",
    "CODE_DETERMINISM",
    "CODE_FEATURE_FLAGGED_UNIT",
    "CODE_FEATURE_SKIPPED_UNIT",
    "CODE_FEATURE_UNAVAILABLE",
    "CODE_FEATURES_BUILT",
    "CODE_FILLED_SOURCE_EXCLUDED",
    "CODE_LEAKAGE_CHECKED",
    "CODE_LINEAGE_EXPORTED",
    "CODE_NO_IMPUTATION",
    "CODE_ORDERED",
    "CODE_PREFIX",
    "CODE_REGISTRY_COMPILED",
    "CODE_ROWS_BUILT",
    "CODE_ROWS_DROPPED_MISSING",
    "CODE_ROWS_DROPPED_WARMUP",
    "CODE_ROWS_RETAINED",
    "CODE_ROWS_UNASSIGNED",
    "CODE_SYNTHETIC_SOURCE",
    "CODE_TARGET_ABSENT",
    "CODE_TARGET_CROSSES_SPLIT",
    "CODE_UNIT_UNDETERMINED",
    "GAP_CAUSES",
    "SEVERITIES",
    "SEVERITY_ERROR",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "SPLITS",
    "SPLIT_TEST",
    "SPLIT_TRAIN",
    "SPLIT_UNASSIGNED",
    "SPLIT_VALIDATION",
    "Cadence",
    "FeatureDataset",
    "FeatureError",
    "FeatureNote",
    "FeatureQualityReport",
    "FeatureResult",
    "FeatureRow",
    "ModelReadyDataset",
    "Phase3LeakageAudit",
    "SplitIndex",
    "audit_point_in_time",
    "build_features",
    "build_split_index",
    "resolve_cadence",
    "split_collisions",
    "split_parts",
]
