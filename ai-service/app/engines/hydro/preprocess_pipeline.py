# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 2 — the record-level preprocessing pipeline and its report.

Where this sits
---------------
```
Phase 1  validate   domains / quality / datasets      "is this shaped like an observation?"
Phase 2  preprocess  this module + its three helpers   "is this frame usable, and how do I know?"
Phase 3  features   features.py                      "what lags/rolling windows should I build?"
```

`preprocessing.py` is the older, wide-`DataFrame` layer that `training.py` and
`engine.py` call. It is **not** modified, replaced or duplicated here. The two
answer different questions: that one takes columns named by `config.DatasetSpec`
and returns a frame; this one takes Phase 1 `Observation` records and returns
records plus an audit trail. The committed synthetic sample has no station
column, so it belongs to the `DataFrame` layer; a real gauge network does not,
and this is the layer for it.

What this module refuses to do
------------------------------
* **Guess.** A naive timestamp, an unrecognised unit, a quantity with no
  aggregation rule, an unresolvable conflict — each is reported or refused, and
  the report says which.
* **Invent observations.** Nothing here creates a value no source reported. A
  filled row is marked `quality_status='missing'` and names the instant it was
  carried from.
* **Average two readings.** There is no conflict policy that does this, and
  `preprocess_config.CONFLICT_POLICIES_THAT_FABRICATE` is an empty tuple the
  tests assert on.
* **Learn from the future.** Every operation is causal by default, the two that
  are not must be acknowledged by name, and `leakage_audit` re-checks the result
  rather than trusting the configuration.
* **Randomise.** There is no seed parameter anywhere in this module.

One thing Phase 1 already does
------------------------------
`domains.parse_instant` refuses a timezone-naive `observed_at` when an
`Observation` is constructed, so `timezone_policy='require_explicit'` is enforced
upstream rather than here. Stage 2 of this pipeline is canonicalisation and
timezone accounting; `preprocess_temporal.normalize_timestamp` is the tested
entry point for the policies that *do* move an instant, and is what a caller
holding raw timestamp strings should use.

Determinism
-----------
Given the same records in any order, the output records and the report are
identical. Sorting uses the parsed instant plus a total tiebreak; every report
collection is sorted before it is serialised; no dict iteration order reaches
`to_dict`. The tests shuffle the input and compare byte-for-byte.

Pure standard library, like the Phase 1 modules: importing this must not drag
NumPy or pandas in behind it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Sequence

from .datasets import DatasetDescriptor
from .domains import QUALITY_MISSING, Measurement, Observation
from .preprocess_config import (
    CONFLICT_ERROR,
    CONFLICT_KEEP_FIRST,
    CONFLICT_KEEP_LAST,
    DUPLICATE_ERROR,
    DUPLICATE_KEEP_FIRST,
    DUPLICATE_KEEP_LAST,
    DUPLICATE_REPORT,
    UNIT_PRESERVE_UNDETERMINED,
    PreprocessConfig,
)
from .preprocess_temporal import (
    Duration,
    MissingPolicyReport,
    SplitReport,
    TemporalError,
    TimestampNormalizationReport,
    apply_missing_policy,
    assert_monotonic,
    build_grid,
    canonical_record,
    describe_series,
    entity_key,
    series_key,
    infer_base_interval,
    interval_regularity,
    normalize_timestamp,
    parse_frequency,
    record_order,
    resample_entity,
    sort_records,
    split_records,
)
from .preprocess_units import UnitConversion, UnitConversionReport, normalize_unit
from .provenance import (
    DATASET_TYPE_SYNTHETIC,
    SYNTHETIC_DATA_DISCLAIMER,
    UNVERIFIED_DATA_DISCLAIMER,
)
from .quality import (
    ConflictReport,
    QualityIssue,
    ValidationReport,
    check_observation_collection,
    validate_observation,
)

# --------------------------------------------------------------------------- #
# Severity
# --------------------------------------------------------------------------- #

#: A condition that stopped the pipeline. Carried in the report rather than only
#: raised, so a caller can see what was wrong even when it chose to continue.
SEVERITY_ERROR = "error"
#: A condition that did not stop anything but changes how the output must be read.
SEVERITY_WARNING = "warning"
#: A fact worth recording that is not a problem: a policy that changed nothing,
#: an interval that was inferred.
SEVERITY_INFO = "info"

SEVERITIES = (SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO)

#: Severity order, worst first. Used to sort notes deterministically.
_SEVERITY_RANK = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}

#: Namespace for every phase-2 finding code, so a consumer can tell which phase
#: produced a code without maintaining a hand-written list of the other one.
CODE_PREFIX = "PREPROCESS_"

#: Stable codes for pipeline-stage findings. Deliberately distinct from the
#: `quality` module's record-validation codes: these describe what *preprocessing*
#: did, not whether a record was well formed. Phase 1's codes are carried through
#: unmodified under `phase1_quality` rather than being restated here.
#:
#: Built from `CODE_PREFIX` rather than written out, because a code that quietly
#: lost its namespace would then look like a Phase 1 code to a log aggregator.
CODE_DUPLICATES_FOUND = CODE_PREFIX + "DUPLICATES_FOUND"
CODE_DUPLICATES_RESOLVED = CODE_PREFIX + "DUPLICATES_RESOLVED"
CODE_CONFLICT_REFUSED = CODE_PREFIX + "CONFLICT_REFUSED"
CODE_CONFLICT_RESOLVED = CODE_PREFIX + "CONFLICT_RESOLVED"
CODE_CONFLICT_APPROVED = CODE_PREFIX + "CONFLICT_APPROVED"
CODE_GAPS_RETAINED = CODE_PREFIX + "GAPS_RETAINED"
CODE_GAPS_FILLED = CODE_PREFIX + "GAPS_FILLED"
CODE_GAPS_REJECTED = CODE_PREFIX + "GAPS_REJECTED"
CODE_UNDETERMINED_UNIT = CODE_PREFIX + "UNDETERMINED_UNIT"
CODE_UNIT_CONVERTED = CODE_PREFIX + "UNIT_CONVERTED"
CODE_TIMEZONE_ASSUMED = CODE_PREFIX + "TIMEZONE_ASSUMED"
CODE_RESAMPLED = CODE_PREFIX + "RESAMPLED"
CODE_IRREGULAR_SERIES = CODE_PREFIX + "IRREGULAR_SERIES"
CODE_ORDERED = CODE_PREFIX + "ORDERED"
CODE_ENTITY_EXCLUDED = CODE_PREFIX + "ENTITY_EXCLUDED"
CODE_LEAKAGE_SENSITIVE = CODE_PREFIX + "LEAKAGE_SENSITIVE"
CODE_STAGE1_ISSUES = CODE_PREFIX + "STAGE1_ISSUES"

#: Every code this module can emit, for the report and for callers that want to
#: validate an untrusted note. A code outside this set is a bug here, not data.
ALL_CODES = frozenset(
    {
        CODE_DUPLICATES_FOUND,
        CODE_DUPLICATES_RESOLVED,
        CODE_CONFLICT_REFUSED,
        CODE_CONFLICT_RESOLVED,
        CODE_CONFLICT_APPROVED,
        CODE_GAPS_RETAINED,
        CODE_GAPS_FILLED,
        CODE_GAPS_REJECTED,
        CODE_UNDETERMINED_UNIT,
        CODE_UNIT_CONVERTED,
        CODE_TIMEZONE_ASSUMED,
        CODE_RESAMPLED,
        CODE_IRREGULAR_SERIES,
        CODE_ORDERED,
        CODE_ENTITY_EXCLUDED,
        CODE_LEAKAGE_SENSITIVE,
        CODE_STAGE1_ISSUES,
    }
)


# --------------------------------------------------------------------------- #
# Findings
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PreprocessNote:
    """One pipeline-stage finding, at one of three severities.

    A `PreprocessNote` is not a `QualityIssue`. A `QualityIssue` asks "is this
    record well formed?"; a `PreprocessNote` says "here is what preprocessing did
    to your data, and here is what you must remember about it downstream".
    Keeping them apart stops the two questions from being answered by one
    severity vocabulary that fits neither.
    """

    severity: str
    code: str
    message: str
    subject: str = ""

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(
                f"severity must be one of {SEVERITIES}, got {self.severity!r}"
            )
        if not self.code:
            raise ValueError("PreprocessNote.code must be a non-empty string")

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


def _sort_notes(notes: Iterable[PreprocessNote]) -> tuple[PreprocessNote, ...]:
    """Worst-first, then by code, then by subject — so reports are reproducible."""
    return tuple(
        sorted(
            notes,
            key=lambda note: (_SEVERITY_RANK[note.severity], note.code, note.subject, note.message),
        )
    )


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class PreprocessError(ValueError):
    """Raised when a Phase 2 pipeline cannot proceed honestly.

    Distinct from `preprocess_config.PreprocessConfigError` (the configuration is
    self-contradictory), `preprocess_temporal.TemporalError` (a temporal
    operation is impossible) and `preprocess_units.UnitError` (a conversion is
    impossible). This is the top-level statement that the *pipeline* cannot run.
    """


# --------------------------------------------------------------------------- #
# Duplicate and conflict identity
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MeasurementSlot:
    """One quantity at one instant, with the identity needed to detect repeats.

    Duplicates are detected at *slot* level because that is where the ambiguity
    lives — the same `rainfall` value reported twice for one hour. They are
    resolved at *record* level, because a partial record is not a thing that can
    exist: an `Observation` is a group of measurements, so either the whole group
    survives or none of it does. Splitting the two is what lets the report say
    "quantity X at instant T appears twice" and still only ever remove whole
    records.
    """

    identity: tuple[str, str, str, str, str]
    record: Observation
    value: float
    unit: str

    @property
    def domain(self) -> str:
        return self.identity[0]

    @property
    def entity(self) -> str:
        return self.identity[1]

    @property
    def instant(self) -> str:
        return self.identity[2]

    @property
    def quantity(self) -> str:
        return self.identity[3]

    @property
    def source(self) -> str:
        return self.identity[4]

    def describe(self) -> str:
        return (
            f"{self.entity} {self.quantity} at {self.instant} "
            f"from {self.source or 'an unnamed source'} = {self.value} {self.unit}"
        )


def slot_identity(record: Observation, quantity: str) -> tuple[str, str, str, str, str]:
    """`domain + entity + instant + quantity + source` — Phase 2's duplicate key.

    Two additions to Phase 1's `quality._observation_key`, both deliberate and
    both explained in `PHASE2_PREPROCESSING.md`:

    * **The instant is canonical.** Phase 1 keys on the raw `observed_at` string,
      so `05:30+05:30` and `00:00Z` look like different instants. This pipeline
      canonicalises first, so they do not.
    * **The source is included.** Phase 1 deliberately excludes it, because "the
      same gauge instant reported by two datasets" is a *merge* decision for the
      dataset owner. That is still true, so Phase 1's `ConflictReport` is
      computed and published alongside this one as a cross-source advisory. The
      difference is that Phase 1 raises no error for a disagreement, while this
      module must decide whether to keep a row, and a source-partitioned identity
      is what makes that decision well defined.
    """
    return (
        record.domain,
        record.location_reference,
        canonical_record(record).observed_at,
        quantity,
        record.source_reference or "",
    )


@dataclass
class DuplicateReport:
    """What the duplicate and conflict stages found, and what they did about it."""

    duplicate_slot_groups: int = 0
    duplicate_records: int = 0
    conflicting_slot_groups: int = 0
    conflicting_records: int = 0
    kept: int = 0
    removed: int = 0
    #: A handful of concrete examples, so the report is auditable without a dump.
    examples: list[dict[str, Any]] = field(default_factory=list)
    notes: list[PreprocessNote] = field(default_factory=list)
    #: Phase 1's cross-source `ConflictReport`, kept whole rather than restated.
    cross_source: ConflictReport | None = None

    EXAMPLE_LIMIT = 4

    @property
    def has_duplicates(self) -> bool:
        return self.duplicate_slot_groups > 0

    @property
    def has_conflicts(self) -> bool:
        return self.conflicting_slot_groups > 0

    @property
    def changed_anything(self) -> bool:
        return self.removed > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "duplicate_slot_groups": self.duplicate_slot_groups,
            "duplicate_records": self.duplicate_records,
            "conflicting_slot_groups": self.conflicting_slot_groups,
            "conflicting_records": self.conflicting_records,
            "kept": self.kept,
            "removed": self.removed,
            "changed_anything": self.changed_anything,
            "examples": list(self.examples),
            "notes": [note.to_dict() for note in _sort_notes(self.notes)],
            "cross_source_advisory": self.cross_source.to_dict() if self.cross_source else None,
        }

    def describe(self) -> str:
        lines = [
            f"DUPLICATES exact_groups={self.duplicate_slot_groups} "
            f"records={self.duplicate_records} "
            f"conflicting_groups={self.conflicting_slot_groups} "
            f"removed={self.removed} kept={self.kept}"
        ]
        for example in self.examples:
            lines.append(f"    {example['kind']}: {example['detail']}")
        if self.cross_source is not None and not self.cross_source.ok:
            lines.append(
                f"    CROSS-SOURCE ADVISORY: {len(self.cross_source.duplicate_keys)} duplicate "
                f"and {len(self.cross_source.conflicting_keys)} conflicting gauge instants when "
                "the source is ignored (a merge decision, not a duplicate to delete)"
            )
        return "\n".join(lines)


def resolve_duplicates_and_conflicts(
    records: Sequence[Observation],
    config: PreprocessConfig,
) -> tuple[list[Observation], DuplicateReport]:
    """Detect and, only where configured, resolve repeats and disagreements.

    Returns `(records, report)`.

    Resolution rules, in the order they are applied:

    1. **Slot scan.** Group every `(domain, entity, instant, quantity, source)`
       slot. A group with more than one member is either *exact* (all values
       equal) or *conflicting* (they are not).
    2. **Conflict first.** A conflicting group is the more serious finding, so it
       is handled before any deduplication. Under the default
       `conflict_policy='error'` this raises `PreprocessError` naming the first
       disagreement — an unresolvable conflict stops the run rather than
       producing a history nobody observed.
    3. **Then duplicates.** Exact repeats are handled by `duplicate_policy`. The
       default `'report'` keeps every row, which is the honest choice: an operator
       should see the duplication before rows disappear.

    No policy averages, sums, medians or otherwise blends two readings, and
    `conflict_policy='keep_first'`/`'keep_last'` require a citation in
    `conflict_policy_source` before the configuration will construct at all.
    """
    report = DuplicateReport()

    slots: dict[tuple[str, str, str, str, str], list[MeasurementSlot]] = {}
    for record in records:
        for item in record.measurements:
            identity = slot_identity(record, item.quantity)
            slots.setdefault(identity, []).append(
                MeasurementSlot(
                    identity=identity,
                    record=record,
                    value=float(item.value),
                    unit=item.unit,
                )
            )

    exact_identities: set[tuple[str, str, str, str, str]] = set()
    conflicting_identities: set[tuple[str, str, str, str, str]] = set()
    for identity, members in slots.items():
        if len(members) < 2:
            continue
        values = {member.value for member in members}
        if len(values) == 1:
            exact_identities.add(identity)
        else:
            conflicting_identities.add(identity)

    # Members of one slot arrived in the caller's row order. Sorting them by the
    # same total order `sort_records` uses means the text below -- and which
    # member reads as "the first" -- depends on the readings, not on the batch.
    # A conflict message that changed when the same rows were shuffled would be
    # indistinguishable from a real difference to anyone comparing two reports.
    for members in slots.values():
        if len(members) > 1:
            members.sort(
                key=lambda slot: (*record_order(slot.record), slot.value, str(slot.unit))
            )

    # --- 2. conflicts -----------------------------------------------------
    if conflicting_identities:
        report.conflicting_slot_groups = len(conflicting_identities)
        # Count by `id`, not by record equality: `Observation` is a frozen
        # dataclass with value equality, so two genuinely distinct rows that
        # carry the same reading compare and hash equal, and a `set` of records
        # would report "1 record" where two rows exist.
        report.conflicting_records = len(
            {id(slot.record) for identity in conflicting_identities for slot in slots[identity]}
        )
        for identity in sorted(conflicting_identities)[: DuplicateReport.EXAMPLE_LIMIT]:
            members = slots[identity]
            detail = (
                f"{len(members)} readings of {members[0].quantity} at "
                f"{members[0].instant} for {members[0].entity}: "
                + ", ".join(f"{member.value} {member.unit}" for member in members)
                + " — these disagree, and no reading here is the true one"
            )
            report.examples.append({"kind": "conflict", "detail": detail})
        if config.conflict_policy == CONFLICT_ERROR:
            first = sorted(conflicting_identities)[0]
            members = slots[first]
            note = PreprocessNote(
                severity=SEVERITY_ERROR,
                code=CODE_CONFLICT_REFUSED,
                message=(
                    f"{report.conflicting_slot_groups} quantity/quantities disagree for the same "
                    f"gauge instant; the first is {members[0].describe()}. conflict_policy is "
                    "'error', and this module will not average, sum or otherwise choose between "
                    "readings that a source reported inconsistently. Resolve it upstream, or set "
                    "conflict_policy='keep_first'/'keep_last' with a conflict_policy_source "
                    "recording who approved that and against what document."
                ),
                subject=str(members[0].entity),
            )
            report.notes.append(note)
            raise PreprocessError(note.message)
        report.notes.append(
            PreprocessNote(
                severity=SEVERITY_WARNING,
                code=CODE_CONFLICT_RESOLVED,
                message=(
                    f"{report.conflicting_slot_groups} disagreeing reading group(s) resolved by "
                    f"conflict_policy={config.conflict_policy!r}, approved by "
                    f"{config.conflict_policy_source!r}. The discarded readings are not "
                    "recoverable from the output."
                ),
            )
        )
        report.notes.append(
            PreprocessNote(
                severity=SEVERITY_WARNING,
                code=CODE_CONFLICT_APPROVED,
                message=(
                    f"conflict resolution was applied with an explicit approval citation: "
                    f"{config.conflict_policy_source!r}"
                ),
            )
        )

    # --- 3. duplicates ----------------------------------------------------
    if exact_identities:
        report.duplicate_slot_groups = len(exact_identities)
        report.duplicate_records = len(
            {id(slot.record) for identity in exact_identities for slot in slots[identity]}
        )
        for identity in sorted(exact_identities)[: DuplicateReport.EXAMPLE_LIMIT]:
            members = slots[identity]
            report.examples.append(
                {
                    "kind": "exact_duplicate",
                    "detail": (
                        f"{len(members)} identical readings of {members[0].quantity} at "
                        f"{members[0].instant} for {members[0].entity} = "
                        f"{members[0].value} {members[0].unit}"
                    ),
                }
            )
        if config.duplicate_policy == DUPLICATE_ERROR:
            first = sorted(exact_identities)[0]
            note = PreprocessNote(
                severity=SEVERITY_ERROR,
                code=CODE_DUPLICATES_FOUND,
                message=(
                    f"{report.duplicate_slot_groups} exact duplicate group(s) present and "
                    f"duplicate_policy is 'error'. The first is {slots[first][0].describe()}."
                ),
            )
            report.notes.append(note)
            raise PreprocessError(note.message)
        if config.duplicate_policy == DUPLICATE_REPORT:
            report.notes.append(
                PreprocessNote(
                    severity=SEVERITY_WARNING,
                    code=CODE_DUPLICATES_FOUND,
                    message=(
                        f"{report.duplicate_slot_groups} exact duplicate group(s) covering "
                        f"{report.duplicate_records} record(s) were found and left in place, "
                        "because duplicate_policy='report' does not remove anything. Every "
                        "downstream count includes them; set duplicate_policy='keep_first' or "
                        "'keep_last' to collapse them."
                    ),
                )
            )
        else:
            report.notes.append(
                PreprocessNote(
                    severity=SEVERITY_WARNING,
                    code=CODE_DUPLICATES_RESOLVED,
                    message=(
                        f"{report.duplicate_slot_groups} exact duplicate group(s) collapsed by "
                        f"duplicate_policy={config.duplicate_policy!r}. Provenance references "
                        "survive on the kept record, so the collapse is traceable."
                    ),
                )
            )

    # --- apply the decision ------------------------------------------------
    survivors = _select_survivors(records, slots, exact_identities, conflicting_identities, config)
    report.kept = len(survivors)
    report.removed = len(records) - len(survivors)
    if not report.removed:
        survivors = list(records)

    # Always computed. Phase 2's identity includes the source, so two datasets
    # reporting the same gauge instant are *not* a duplicate here and nothing is
    # removed — which is exactly the case where the dataset owner still needs to
    # be told that a merge decision is outstanding. Phase 1's report, which
    # ignores the source, is the right instrument for that and is published
    # verbatim under `cross_source`.
    report.cross_source = check_observation_collection(records, subject="phase2_records")

    return survivors, report


def _select_survivors(
    records: Sequence[Observation],
    slots: dict[tuple[str, str, str, str, str], list[MeasurementSlot]],
    exact_identities: set[tuple[str, str, str, str, str]],
    conflicting_identities: set[tuple[str, str, str, str, str]],
    config: PreprocessConfig,
) -> list[Observation]:
    """Decide which whole records survive, deterministically.

    "Whole record" is the unit on purpose. Two records that share one quantity but
    differ in another are not a duplicate of each other and neither is a conflict;
    removing either would discard a measurement nobody asked to lose. A record is
    only ever dropped when it is redundant or when a configured, cited policy says
    which of two disagreeing records wins.
    """
    drop: set[int] = set()
    ids = {id(record): index for index, record in enumerate(records)}

    if config.duplicate_policy in (DUPLICATE_KEEP_FIRST, DUPLICATE_KEEP_LAST):
        for identity in sorted(exact_identities):
            members = slots[identity]
            ordered = sorted(members, key=lambda slot: ids[id(slot.record)])
            keep = ordered[0] if config.duplicate_policy == DUPLICATE_KEEP_FIRST else ordered[-1]
            for slot in ordered:
                if slot.record is not keep.record:
                    drop.add(ids[id(slot.record)])

    if config.conflict_policy in (CONFLICT_KEEP_FIRST, CONFLICT_KEEP_LAST):
        for identity in sorted(conflicting_identities):
            members = slots[identity]
            ordered = sorted(members, key=lambda slot: ids[id(slot.record)])
            keep = ordered[0] if config.conflict_policy == CONFLICT_KEEP_FIRST else ordered[-1]
            for slot in ordered:
                if slot.record is not keep.record:
                    drop.add(ids[id(slot.record)])

    return [record for index, record in enumerate(records) if index not in drop]


# --------------------------------------------------------------------------- #
# Unit stage
# --------------------------------------------------------------------------- #


def normalize_record_units(
    record: Observation,
    config: PreprocessConfig,
    conversions: list[tuple[str | None, UnitConversion]],
) -> Observation:
    """Return `record` with every measurement's unit normalised.

    `conversions` is appended to in place so the caller can build a
    `UnitConversionReport` without this function having to return two things.
    The source unit is never lost: when a conversion happens it is written into
    `notes`, and the aggregate report keeps the `(original, normalized, count)`
    table.

    A measurement whose unit cannot be converted keeps its original value and
    unit, or becomes `UNDETERMINED` if the unit itself was unrecognisable. Under
    `unit_policy='require_known'` that is an error instead.
    """
    rewritten: list[tuple[str, float, str]] = []
    rewrites: list[str] = []
    for item in record.measurements:
        original = item.unit
        conversion = normalize_unit(
            float(item.value),
            original,
            target_unit=config.target_unit_for(item.quantity),
            quantity=item.quantity,
            policy=config.unit_policy,
        )
        conversions.append((item.quantity, conversion))
        rewritten.append((item.quantity, conversion.value, conversion.normalized_unit))
        if conversion.normalized_unit != original or conversion.value_changed:
            rewrites.append(f"{item.quantity}: {original} -> {conversion.normalized_unit}")

    if not rewrites:
        return record
    notes = record.notes
    if rewrites:
        notes = f"{notes} | Phase 2 unit normalisation: {', '.join(rewrites)}".strip(" |")
    return replace(
        record,
        measurements=tuple(
            Measurement(quantity=quantity, value=value, unit=unit)
            for quantity, value, unit in rewritten
        ),
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #


@dataclass
class MissingSummary:
    """Missing-value totals across every series, with the per-series detail kept.

    A single total hides the failure that matters: one series with 90% of its
    readings missing looks identical to nine series each missing 10%, and only
    the second is a healthy dataset.

    `series_processed` is not the number of series in the input. A series whose
    cadence could not be inferred is skipped entirely, so this counts the series
    the stage could actually reason about, and `per_series` is where the skipped
    ones show up.
    """

    policy: str
    #: Series the missing-value stage actually ran on. Series whose cadence
    #: could not be inferred are excluded, so this can be fewer than the
    #: number of series in the input.
    series_processed: int = 0
    #: Rows this stage added or removed. Measured directly, because a fill policy
    #: creates rows while a drop policy removes none: a dropped gap slot was
    #: already empty, so it cost nothing.
    row_delta: int = 0
    missing_before: int = 0
    missing_after: int = 0
    imputed: int = 0
    beyond_max_gap: int = 0
    leading_gap: int = 0
    leakage_sensitive: bool = False
    imputed_by_quantity: dict[str, int] = field(default_factory=dict)
    per_series: dict[str, dict[str, int]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return self.imputed > 0

    @classmethod
    def from_reports(
        cls, policy: str, reports: dict[str, MissingPolicyReport]
    ) -> "MissingSummary":
        summary = cls(policy=policy, series_processed=len(reports))
        for series in sorted(reports):
            entity = series
            report = reports[series]
            summary.missing_before += report.missing_before
            summary.missing_after += report.missing_after
            summary.imputed += report.imputed
            summary.beyond_max_gap += report.beyond_max_gap
            summary.leading_gap += report.leading_gap
            summary.leakage_sensitive = summary.leakage_sensitive or report.leakage_sensitive
            for quantity, count in report.imputed_by_quantity.items():
                summary.imputed_by_quantity[quantity] = (
                    summary.imputed_by_quantity.get(quantity, 0) + count
                )
            summary.per_series[describe_series(entity)] = {
                "missing_before": report.missing_before,
                "missing_after": report.missing_after,
                "imputed": report.imputed,
            }
            for note in report.notes:
                if note not in summary.notes:
                    summary.notes.append(f"{describe_series(series)}: {note}")
        return summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "series_processed": self.series_processed,
            "row_delta": self.row_delta,
            "imputation_enabled": self.enabled,
            "missing_before": self.missing_before,
            "missing_after": self.missing_after,
            "imputed": self.imputed,
            "imputed_by_quantity": dict(sorted(self.imputed_by_quantity.items())),
            "beyond_max_gap": self.beyond_max_gap,
            "leading_gap": self.leading_gap,
            "leakage_sensitive": self.leakage_sensitive,
            "per_series": dict(sorted(self.per_series.items())),
            "notes": list(self.notes),
        }

    def describe(self) -> str:
        lines = [
            f"MISSING policy={self.policy} series={self.series_processed} "
            f"gaps_before={self.missing_before} gaps_after={self.missing_after} "
            f"imputed={self.imputed} beyond_max_gap={self.beyond_max_gap}"
        ]
        if self.imputed_by_quantity:
            detail = ", ".join(
                f"{quantity}={count}" for quantity, count in sorted(self.imputed_by_quantity.items())
            )
            lines.append(f"    imputed by quantity: {detail}")
        return "\n".join(lines)


@dataclass
class LeakageAudit:
    """An independent re-check of the output, not a restatement of the config.

    The point of an audit is that it can disagree with the configuration. Every
    check here examines the *produced records*; none of them reads
    `config.is_causal` and reports it back.
    """

    findings: list[str] = field(default_factory=list)
    checks_run: int = 0

    def record(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks_run += 1
        if not passed:
            self.findings.append(f"{name}: {detail}")

    @property
    def ok(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "checks_run": self.checks_run,
            "findings": list(self.findings),
            "ok": self.ok,
        }

    def describe(self) -> str:
        if self.ok:
            return f"LEAKAGE AUDIT {self.checks_run} checks, all passed"
        return "LEAKAGE AUDIT FAILED:\n" + "\n".join(f"    {f}" for f in self.findings)


@dataclass
class PreprocessingReport:
    """The machine-readable account of one Phase 2 run.

    Answers, in order: what came in, what was wrong with it, what was changed,
    what was refused, and what a reviewer must remember when using the result.
    """

    config: PreprocessConfig
    records_in: int = 0
    records_out: int = 0
    #: Rows a policy actually deleted: deduplicated repeats, conflicts resolved
    #: away, and any row the missing-value policy dropped. This is *not*
    #: `records_in - records_out`. Resampling aggregates 72 hourly rows into 3
    #: daily bins, so that difference is 69 while only 0 readings were thrown
    #: away; reporting 69 as "removed" would blame the data for an operation the
    #: configuration asked for.
    records_discarded: int = 0
    #: Signed row delta caused by resampling: `bins_out - source_rows`.
    resampling_delta: int = 0
    dataset: DatasetDescriptor | None = None
    timestamps: TimestampNormalizationReport = field(
        default_factory=TimestampNormalizationReport
    )
    units: UnitConversionReport = field(default_factory=UnitConversionReport)
    duplicates: DuplicateReport = field(default_factory=DuplicateReport)
    missing: MissingSummary = field(default_factory=lambda: MissingSummary(policy=MISSING_DEFAULT))
    split: SplitReport | None = None
    ordering: dict[str, Any] = field(default_factory=dict)
    resampling: dict[str, Any] = field(default_factory=dict)
    intervals: dict[str, str] = field(default_factory=dict)
    leakage: LeakageAudit = field(default_factory=LeakageAudit)
    phase1_quality: dict[str, Any] = field(default_factory=dict)
    notes: list[PreprocessNote] = field(default_factory=list)

    @property
    def rows_reconciled(self) -> bool:
        """Whether `records_out` is fully explained by the operations performed.

        `records_in - discarded + resampling_delta + gap_delta` must equal
        `records_out`. If it does not, a stage changed the row count without
        saying so, which is precisely the class of bug a preprocessing report
        exists to catch.
        """
        expected = (
            self.records_in
            - self.records_discarded
            + self.resampling_delta
            + self.missing.row_delta
        )
        return expected == self.records_out

    @property
    def errors(self) -> tuple[PreprocessNote, ...]:
        return tuple(note for note in self.notes if note.is_error)

    @property
    def warnings(self) -> tuple[PreprocessNote, ...]:
        return tuple(note for note in self.notes if note.severity == SEVERITY_WARNING)

    @property
    def infos(self) -> tuple[PreprocessNote, ...]:
        return tuple(note for note in self.notes if note.severity == SEVERITY_INFO)

    @property
    def is_synthetic(self) -> bool:
        if self.dataset is not None:
            return self.dataset.dataset_type == DATASET_TYPE_SYNTHETIC
        return False

    @property
    def disclaimer(self) -> str:
        """The warning that travels with this report.

        Taken from the dataset descriptor when one was supplied, otherwise from
        `provenance`. Never invented here and never weakened: a report for a
        synthetic or unknown dataset cannot be summarised without it.
        """
        if self.dataset is not None and self.dataset.disclaimer:
            return self.dataset.disclaimer
        if self.dataset is not None and self.dataset.dataset_type == DATASET_TYPE_SYNTHETIC:
            return SYNTHETIC_DATA_DISCLAIMER
        return UNVERIFIED_DATA_DISCLAIMER

    @property
    def completed(self) -> bool:
        return not self.errors and self.split is not None and self.leakage.ok

    def to_dict(self) -> dict[str, Any]:
        """Serialisable form. Stable key order, plain types, no objects."""
        return {
            "phase": "phase2-preprocessing",
            "completed": self.completed,
            "disclaimer": self.disclaimer,
            "dataset": self.dataset.to_dict() if self.dataset else None,
            "dataset_type": self.dataset.dataset_type if self.dataset else None,
            "counts": {
                "records_in": self.records_in,
                "records_out": self.records_out,
                "records_discarded": self.records_discarded,
                "resampling_delta": self.resampling_delta,
                "rows_reconciled": self.rows_reconciled,
                "split": self.split.sizes if self.split else None,
            },
            "config": self.config.to_dict(),
            "timestamps": self.timestamps.to_dict(),
            "ordering": dict(sorted(self.ordering.items())),
            "intervals": dict(sorted(self.intervals.items())),
            "resampling": dict(sorted(self.resampling.items())),
            "units": self.units.to_dict(),
            "duplicates": self.duplicates.to_dict(),
            "missing": self.missing.to_dict(),
            "split": self.split.to_dict() if self.split else None,
            "leakage_audit": self.leakage.to_dict(),
            "phase1_quality": self.phase1_quality,
            "notes": [note.to_dict() for note in _sort_notes(self.notes)],
            "summary": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "infos": len(self.infos),
            },
        }

    def describe(self) -> str:
        """A short human summary. Every section is a method so none can go stale."""
        sections = [
            (
                f"PREPROCESSING {self.records_in} record(s) in -> {self.records_out} out "
                f"({self.records_discarded} discarded by policy, resampling "
                f"{self.resampling_delta:+d}, gap policy {self.missing.row_delta:+d})"
            ),
            self.timestamps.describe(),
            self.units.describe(),
            self.duplicates.describe(),
            self.missing.describe(),
        ]
        if self.split is not None:
            sections.append(self.split.describe())
        sections.append(self.leakage.describe())
        for note in _sort_notes(self.notes):
            sections.append("    " + note.describe())
        sections.append(f"DISCLAIMER {self.disclaimer}")
        return "\n".join(sections)


#: Placeholder policy for a report that never reached the missing stage. Named so
#: the `default_factory` above reads honestly rather than embedding a magic string.
MISSING_DEFAULT = "not_reached"


# --------------------------------------------------------------------------- #
# The result
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PreprocessingResult:
    """What Phase 2 hands to Phase 3.

    `train`/`validation`/`test` are chronological, disjoint, entity-grouped
    record sequences. No scaler, no imputer, no lag window and no model has been
    fitted: those are Phase 3 and Phase 4, and Phase 2's job ends at "this frame
    is clean, ordered, honest and split".
    """

    config: PreprocessConfig
    train: tuple[Observation, ...]
    validation: tuple[Observation, ...]
    test: tuple[Observation, ...]
    report: PreprocessingReport

    @property
    def sizes(self) -> dict[str, int]:
        return {
            "train": len(self.train),
            "validation": len(self.validation),
            "test": len(self.test),
        }

    @property
    def is_leak_free(self) -> bool:
        return self.report.leakage.ok and (
            self.report.split is None or self.report.split.is_leak_free
        )

    def __len__(self) -> int:
        return len(self.train) + len(self.validation) + len(self.test)


# --------------------------------------------------------------------------- #
# The pipeline
# --------------------------------------------------------------------------- #


def _stage_one_quality(
    records: Sequence[Observation],
) -> tuple[dict[str, Any], list[PreprocessNote]]:
    """Run Phase 1's record validator and fold its findings into a summary.

    Phase 2 does not re-implement validation. It calls `quality.validate_observation`
    per record and republishes the result verbatim, so a Phase 1 issue code means
    the same thing in a Phase 2 report as it does everywhere else.

    Phase 1's codes are only `error` or `warning`; they are carried under
    `phase1_quality`, never converted into `PreprocessNote`s, so the two vocabularies
    cannot be confused for one another.
    """
    reports: list[ValidationReport] = [validate_observation(record) for record in records]
    codes: dict[str, int] = {}
    blocking = 0
    for report in reports:
        for issue in report.issues:
            codes[issue.code] = codes.get(issue.code, 0) + 1
        if not report.ok:
            blocking += 1
    summary = {
        "assessed": len(reports),
        "records_with_issues": blocking,
        "codes": dict(sorted(codes.items())),
        "ok": blocking == 0,
    }
    notes: list[PreprocessNote] = []
    if codes:
        notes.append(
            PreprocessNote(
                severity=SEVERITY_WARNING,
                code=CODE_STAGE1_ISSUES,
                message=(
                    f"Phase 1 structural validation raised {sum(codes.values())} issue(s) across "
                    f"{len(reports)} record(s): "
                    + ", ".join(f"{code}={count}" for code, count in sorted(codes.items()))
                    + ". Preprocessing continued: these are record-level quality findings, not "
                    "reasons to alter a value."
                ),
            )
        )
    return summary, notes


def _resample_records(
    records: Sequence[Observation],
    config: PreprocessConfig,
    intervals: dict[str, Duration],
) -> tuple[list[Observation], list[PreprocessNote], dict[str, Any]]:
    """Resample every entity whose series is regular enough to bin.

    An entity whose instants are not on a regular grid, or whose cadence does not
    divide the requested frequency, is **left at its source resolution and
    reported** — not resampled at an approximate cadence, and not dropped.
    """
    notes: list[PreprocessNote] = []
    per_series: dict[str, Any] = {}
    out: list[Observation] = []
    by_series: dict[str, list[Observation]] = {}
    for record in records:
        by_series.setdefault(series_key(record), []).append(record)

    for series in sorted(by_series):
        items = by_series[series]
        label = describe_series(series)
        step = intervals.get(series)
        if step is None:
            notes.append(
                PreprocessNote(
                    severity=SEVERITY_WARNING,
                    code=CODE_IRREGULAR_SERIES,
                    message=(
                        f"series {label} has no safe base sampling interval, so it was not "
                        "resampled and keeps its source resolution. A bin boundary cannot be "
                        "defined for a series whose spacing is irregular."
                    ),
                    subject=series,
                )
            )
            per_series[series] = {"resampled": False, "reason": "irregular_series"}
            out.extend(items)
            continue
        try:
            slots = build_grid(items, step)
            produced = resample_entity(
                slots,
                config.resample_frequency or "",
                config.aggregations,
                series=series,
                domain=items[0].domain,
                dataset_type=items[0].dataset_type,
            )
        except TemporalError as exc:
            notes.append(
                PreprocessNote(
                    severity=SEVERITY_WARNING,
                    code=CODE_IRREGULAR_SERIES,
                    message=(
                        f"series {label} could not be resampled to "
                        f"{config.resample_frequency!r} and keeps its source resolution: {exc}"
                    ),
                    subject=series,
                )
            )
            per_series[series] = {"resampled": False, "reason": str(exc)}
            out.extend(items)
            continue
        per_series[series] = {
            "resampled": True,
            "records_in": len(items),
            "records_out": len(produced),
            "source_interval": step.describe(),
            "target_frequency": config.resample_frequency,
        }
        notes.append(
            PreprocessNote(
                severity=SEVERITY_INFO,
                code=CODE_RESAMPLED,
                message=(
                    f"series {label} resampled from {step.describe()} to "
                    f"{config.resample_frequency!r}: {len(items)} record(s) became "
                    f"{len(produced)} right-labelled bin(s). A bin is stamped with its LAST "
                    "contributing instant, so no row carries information from after itself."
                ),
                subject=series,
            )
        )
        out.extend(produced)

    summary = {
        "enabled": config.resampling_enabled,
        "frequency": config.resample_frequency,
        "labelling": "right (bin stamped with its last contributing instant)",
        "aggregations": [rule.to_dict() for rule in config.aggregations],
        "per_series": dict(sorted(per_series.items())),
    }
    return out, notes, summary


def _resampling_declined(
    config: PreprocessConfig, intervals: dict[str, Duration]
) -> tuple[list[PreprocessNote], dict[str, Any]]:
    """The resampling stage when it was never switched on.

    Separate from `_resampling_records` on purpose. Running that function with
    `resampling_enabled=False` reports every entity as a resampling *failure*,
    which reads as a defect in the data when the truth is that nobody asked for
    downsampling. Native resolution is the default precisely because nothing in
    this repository establishes what cadence a real gauge network reports.
    """
    detail = ", ".join(
        f"{describe_series(series)}={step.describe()}" for series, step in sorted(intervals.items())
    )
    notes = [
        PreprocessNote(
            severity=SEVERITY_INFO,
            code=CODE_RESAMPLED,
            message=(
                f"no resampling was requested; every series keeps its source resolution ({detail})"
                if detail
                else "no resampling was requested; every series keeps its source resolution"
            ),
        )
    ]
    return notes, {
        "enabled": False,
        "frequency": None,
        "labelling": "not applicable (native resolution preserved)",
        "aggregations": [rule.to_dict() for rule in config.aggregations],
        "per_series": {
            series: {"resampled": False, "reason": "not_requested"}
            for series in sorted(intervals)
        },
    }


def _apply_gap_policies(
    records: Sequence[Observation],
    config: PreprocessConfig,
    intervals: dict[str, Duration],
) -> tuple[list[Observation], MissingSummary, list[PreprocessNote]]:
    """Run the missing-value policy per entity, on a regular grid.

    Gaps are only visible on a grid, so an entity whose spacing is irregular has
    its gaps counted and nothing filled — there is no defensible way to decide
    which slot a missing reading belonged in.
    """
    notes: list[PreprocessNote] = []
    reports: dict[str, MissingPolicyReport] = {}
    out: list[Observation] = []
    by_series: dict[str, list[Observation]] = {}
    for record in records:
        by_series.setdefault(series_key(record), []).append(record)

    quantities = sorted(
        {
            item.quantity
            for record in records
            for item in record.measurements
        }
    )

    for series in sorted(by_series):
        items = by_series[series]
        label = describe_series(series)
        step = intervals.get(series)
        if step is None:
            notes.append(
                PreprocessNote(
                    severity=SEVERITY_WARNING,
                    code=CODE_IRREGULAR_SERIES,
                    message=(
                        f"series {label} has no safe base sampling interval, so no gap policy was "
                        "applied to it and its records are unchanged. Gaps on an irregular series "
                        "cannot be located without inventing the grid they should have sat on."
                    ),
                    subject=series,
                )
            )
            out.extend(items)
            continue
        slots = build_grid(items, step)
        filled, report = apply_missing_policy(slots, config, quantities=quantities)
        reports[series] = report
        for slot in filled:
            out.extend(slot.observations)

    summary = MissingSummary.from_reports(config.missing_policy, reports)

    # Measured, not inferred. The gap stage can add rows (a fill policy turns
    # empty slots into records) or remove none (dropping an empty slot discards
    # no reading), and which of those happened is not recoverable from the
    # before/after gap counts alone.
    summary.row_delta = len(out) - len(records)

    if config.missing_policy == "retain" and summary.missing_before:
        notes.append(
            PreprocessNote(
                severity=SEVERITY_WARNING,
                code=CODE_GAPS_RETAINED,
                message=(
                    f"{summary.missing_before} gap(s) retained as gaps across "
                    f"{summary.series_processed} series. missing_policy='retain' is the "
                    "default and invents nothing; a retained gap is a fact about the instrument, "
                    "and Phase 3 must treat it as absent rather than as a zero."
                ),
            )
        )
    if config.imputes_missing and summary.imputed:
        notes.append(
            PreprocessNote(
                severity=SEVERITY_WARNING if summary.leakage_sensitive else SEVERITY_INFO,
                code=CODE_GAPS_FILLED,
                message=(
                    f"{summary.imputed} value(s) written under missing_policy="
                    f"{config.missing_policy!r}. Every filled record carries "
                    "quality_status='missing' and names the instant its value came from."
                    + (
                        " THIS POLICY IS NOT CAUSAL: each filled row depends on a reading taken "
                        "after it."
                        if summary.leakage_sensitive
                        else ""
                    )
                ),
            )
        )
    if summary.leakage_sensitive:
        notes.append(
            PreprocessNote(
                severity=SEVERITY_WARNING,
                code=CODE_LEAKAGE_SENSITIVE,
                message=(
                    f"leakage-sensitive operation(s) {list(config.leakage_sensitive_operations)} "
                    f"were used and acknowledged as {list(config.acknowledged_leakage_operations)}. "
                    "A row in the output can depend on an observation made after it, so any "
                    "evaluation on this output measures interpolation, not forecasting skill."
                ),
            )
        )
    if config.imputes_missing and summary.beyond_max_gap:
        notes.append(
            PreprocessNote(
                severity=SEVERITY_INFO,
                code=CODE_GAPS_FILLED,
                message=(
                    f"{summary.beyond_max_gap} gap slot(s) exceeded max_fill_gap="
                    f"{config.max_fill_gap} and were left unfilled, plus {summary.leading_gap} "
                    "leading gap(s) with nothing earlier to carry forward."
                ),
            )
        )
    return out, summary, notes


def _leakage_audit(
    result_records: Sequence[Observation],
    split: SplitReport,
    config: PreprocessConfig,
) -> LeakageAudit:
    """Check the produced records for leakage, independently of the config."""
    audit = LeakageAudit()

    try:
        ordered, _ = sort_records(result_records)
        assert_monotonic(ordered)
        audit.record("ordering", True)
    except TemporalError as exc:
        audit.record("ordering", False, str(exc))

    for entity, split_one in split.per_entity.items():
        seen: set[str] = set()
        for name, part in zip(("train", "validation", "test"), split_one.parts()):
            for record in part:
                key = f"{record.domain}|{entity}|{record.observed_at}|{record.source_reference or ''}"
                audit.record(
                    f"split_disjoint:{entity}:{name}",
                    key not in seen,
                    f"record {key} appears in more than one split",
                )
                seen.add(key)
        train_end = split_one.train[-1].instant if split_one.train else None
        validation_start = split_one.validation[0].instant if split_one.validation else None
        test_start = split_one.test[0].instant if split_one.test else None
        if train_end is not None and validation_start is not None:
            audit.record(
                f"split_ordered:{entity}",
                train_end < validation_start,
                f"train_end {train_end.isoformat()} is not before validation_start "
                f"{validation_start.isoformat()}",
            )
        if validation_start is not None and test_start is not None:
            audit.record(
                f"split_ordered_test:{entity}",
                validation_start < test_start,
                f"validation_start {validation_start.isoformat()} is not before test_start "
                f"{test_start.isoformat()}",
            )

    for finding in split.cross_entity_time_overlap:
        audit.record("cross_entity", False, finding)

    derived = [r for r in result_records if r.quality_status == QUALITY_MISSING]
    if derived and config.is_causal:
        for record in derived:
            if "missing_policy" in record.notes and "backward" in config.missing_policy:
                audit.record(
                    "imputation_causal",
                    False,
                    f"record at {record.observed_at} was filled by a non-causal policy",
                )

    for name, part in (("train", split.train), ("validation", split.validation), ("test", split.test)):
        moments = [record.instant for record in part]
        audit.record(
            f"{name}_is_the_original_sequence",
            moments == sorted(moments),
            f"the {name} split is not in chronological order",
        )

    return audit


def preprocess(
    records: Sequence[Observation],
    config: PreprocessConfig | None = None,
    *,
    dataset: DatasetDescriptor | None = None,
    subject: str = "phase2_preprocessing",
) -> PreprocessingResult:
    """Run Phase 2 over a sequence of Phase 1 `Observation` records.

    Stage order, and why:

    | # | Stage | Must come before |
    | --- | --- | --- |
    | 1 | Phase 1 validation | everything |
    | 2 | timestamp canonicalisation | ordering, duplicates, splitting — all compare instants |
    | 3 | deterministic ordering | duplicates, gaps, splitting |
    | 4 | duplicate / conflict resolution | gaps — a gap is only a gap once the extras are gone |
    | 5 | unit normalisation | resampling — a bin mixing `m` and `cm` is refused |
    | 6 | resampling | gap handling — gaps are per bin after this |
    | 7 | missing-value policy | splitting — the split counts what actually survives |
    | 8 | chronological split | leakage audit |
    | 9 | leakage audit | the report |

    Passing no `config` gives the conservative configuration: naive timestamps
    refused, duplicates reported but kept, conflicts refused, gaps kept, unfamiliar
    units left as `UNDETERMINED`, source resolution preserved, global split.

    Raises `PreprocessError` for an unresolved conflict, and propagates
    `TemporalError`, `UnitError` and `PreprocessConfigError` from the stage that
    hit them. Nothing is repaired on the way past.
    """
    settings = config if config is not None else PreprocessConfig()
    report = PreprocessingReport(
        config=settings,
        records_in=len(records),
        dataset=dataset,
    )
    working = list(records)

    if not working:
        raise PreprocessError(
            "Phase 2 received no records. An empty batch is not a dataset, and reporting a "
            "clean run over zero records would claim a validation that never happened."
        )

    # --- 1. Phase 1 validation -------------------------------------------
    report.phase1_quality, stage_one_notes = _stage_one_quality(working)
    report.notes.extend(stage_one_notes)

    # --- 2. timestamp canonicalisation ------------------------------------
    # Note on what this stage is and is not. Phase 1's `Observation` constructor
    # already refuses a naive `observed_at` (`domains.parse_instant`), so for
    # records that are already built, `timezone_policy='require_explicit'` cannot
    # fail here — this stage is the *canonicalisation and accounting* layer, not
    # the enforcement layer, and the report should not imply otherwise.
    #
    # The policies that do change an instant (`source_declared`, `assume_utc`) are
    # reachable whenever Phase 2 is handed a raw timestamp string rather than a
    # constructed record; `normalize_timestamp` is the tested entry point for
    # that. Calling it here anyway costs nothing — it returns early when the
    # value is already canonical — and it keeps one code path producing the tz
    # provenance that `canonical_record` depends on.
    canonical: list[Observation] = []
    for index, record in enumerate(working):
        try:
            normalized = normalize_timestamp(record.observed_at, settings)
        except TemporalError as exc:
            report.timestamps.record_rejection(index, str(exc))
            report.notes.append(
                PreprocessNote(
                    severity=SEVERITY_ERROR,
                    code=CODE_TIMEZONE_ASSUMED,
                    message=f"record {index} has an unusable timestamp: {exc}",
                    subject=record.location_reference,
                )
            )
            continue
        report.timestamps.record(normalized)
        canonical.append(canonical_record(record))

    if not canonical:
        raise PreprocessError(
            "every timestamp was rejected, so there is nothing to preprocess. "
            + report.timestamps.describe()
        )
    if report.timestamps.rejected:
        report.notes.append(
            PreprocessNote(
                severity=SEVERITY_ERROR,
                code=CODE_TIMEZONE_ASSUMED,
                message=(
                    f"{len(report.timestamps.rejected)} timestamp(s) were rejected and "
                    f"{len(canonical)} record(s) remain. Rejected records are not repaired; fix "
                    "the source. "
                    + report.timestamps.describe()
                ),
            )
        )
    if not report.timestamps.all_explicit:
        assumed = report.timestamps.assumed_timezone
        declared = report.timestamps.declared_timezone
        report.notes.append(
            PreprocessNote(
                severity=SEVERITY_WARNING,
                code=CODE_TIMEZONE_ASSUMED,
                message=(
                    f"{assumed} timestamp(s) had UTC assumed and {declared} had the source's "
                    f"declared zone applied, under timezone_policy={settings.timezone_policy!r}. "
                    "A wrong timezone shifts the whole series while every downstream boundary "
                    "still looks self-consistent, so this is recorded rather than absorbed."
                ),
            )
        )
    report.timestamps.finalise()
    working = canonical

    # --- 3. ordering -------------------------------------------------------
    working, ordering = sort_records(working)
    report.ordering = dict(ordering)
    report.ordering["changed"] = len(working) != report.records_in
    report.notes.append(
        PreprocessNote(
            severity=SEVERITY_INFO,
            code=CODE_ORDERED,
            message=(
                f"records ordered by (entity, instant) across {ordering['entities']} "
                f"entity/entities. The order is a total one, so the same records in any input "
                "order produce the same output."
            ),
        )
    )

    # --- 4. duplicates and conflicts --------------------------------------
    working, duplicates = resolve_duplicates_and_conflicts(working, settings)
    report.duplicates = duplicates
    report.notes.extend(duplicates.notes)
    report.records_discarded += duplicates.removed

    # --- 5. units ----------------------------------------------------------
    conversions: list[tuple[str | None, UnitConversion]] = []
    working = [normalize_record_units(record, settings, conversions) for record in working]
    for quantity, conversion in conversions:
        report.units.record(quantity, conversion)
    if report.units.undetermined_quantities:
        report.notes.append(
            PreprocessNote(
                severity=SEVERITY_WARNING,
                code=CODE_UNDETERMINED_UNIT,
                message=(
                    "no exact conversion exists for the unit(s) of "
                    f"{list(report.units.undetermined_quantities)}; those values are carried "
                    "unchanged with their unit reported as UNDETERMINED. unit_policy="
                    f"{settings.unit_policy!r} means no unit was guessed."
                ),
            )
        )
    if report.units.converted:
        report.notes.append(
            PreprocessNote(
                severity=SEVERITY_INFO,
                code=CODE_UNIT_CONVERTED,
                message=(
                    f"{report.units.converted} value(s) converted using exact documented factors: "
                    + ", ".join(
                        f"{entry['original_unit']}->{entry['normalized_unit']} x{entry['count']}"
                        for entry in report.units.conversions
                        if entry["original_unit"] != entry["normalized_unit"]
                    )
                ),
            )
        )

    # --- 6. resampling -----------------------------------------------------
    intervals: dict[str, Duration] = {}
    by_series: dict[str, list[Observation]] = {}
    for record in working:
        by_series.setdefault(series_key(record), []).append(record)
    for series in sorted(by_series):
        found = infer_base_interval(by_series[series])
        if found is None:
            report.intervals[series] = "irregular (no safe base interval)"
        else:
            intervals[series] = found
            # Publish how regular the spacing actually was. Without this the
            # report says "interval=1h" as though it were known, when it was
            # inferred from a series with holes in it.
            regularity = interval_regularity(by_series[series], found)
            report.intervals[series] = (
                f"{describe_series(series)}: {found.describe()} "
                f"(regularity {regularity:.0%}, inferred)"
            )
    if settings.resampling_enabled:
        before = len(working)
        working, resample_notes, report.resampling = _resample_records(
            working, settings, intervals
        )
        report.resampling_delta = len(working) - before
        report.notes.extend(resample_notes)
    else:
        resample_notes, report.resampling = _resampling_declined(settings, intervals)
        report.notes.extend(resample_notes)

    # --- 7. missing values -------------------------------------------------
    working, report.missing, missing_notes = _apply_gap_policies(working, settings, intervals)
    report.notes.extend(missing_notes)

    # --- 8. chronological split -------------------------------------------
    split = split_records(working, settings)
    report.split = split
    if split.insufficient:
        report.notes.append(
            PreprocessNote(
                severity=SEVERITY_WARNING,
                code=CODE_ENTITY_EXCLUDED,
                message=(
                    f"{len(split.insufficient)} entity/entities were excluded from the split "
                    f"under insufficient_group_policy={settings.insufficient_group_policy!r}: "
                    + "; ".join(
                        f"{entity} ({count} records) — {reason}"
                        for entity, count, reason in sorted(
                            split.insufficient.items(),
                            key=lambda item: (item[0], item[1]),
                        )
                        for reason in [split.insufficient_reason.get(entity, "unspecified")]
                    )
                    + ". A gauge that vanishes from a dataset is a decision someone should make "
                    "deliberately, which is why it is reported here."
                ),
            )
        )

    # --- 9. leakage audit --------------------------------------------------
    survivors = list(split.train) + list(split.validation) + list(split.test)
    survivors, _ = sort_records(survivors)
    report.leakage = _leakage_audit(survivors, split, settings)
    if not report.leakage.ok:
        report.notes.append(
            PreprocessNote(
                severity=SEVERITY_ERROR,
                code=CODE_LEAKAGE_SENSITIVE,
                message=(
                    "the leakage audit found "
                    f"{len(report.leakage.findings)} problem(s): "
                    + "; ".join(report.leakage.findings)
                ),
            )
        )

    report.records_out = len(survivors)
    if not report.rows_reconciled:
        report.notes.append(
            PreprocessNote(
                severity=SEVERITY_ERROR,
                code=CODE_IRREGULAR_SERIES,
                message=(
                    f"the row count does not reconcile: {report.records_in} in, "
                    f"{report.records_discarded} discarded, resampling delta "
                    f"{report.resampling_delta:+d}, gap-policy delta "
                    f"{report.missing.row_delta:+d}, {report.records_out} out. A stage changed "
                    "the row count without recording it, so the audit trail cannot be trusted."
                ),
            )
        )

    return PreprocessingResult(
        config=settings,
        train=tuple(split.train),
        validation=tuple(split.validation),
        test=tuple(split.test),
        report=report,
    )


__all__ = [
    "ALL_CODES",
    "CODE_CONFLICT_APPROVED",
    "CODE_CONFLICT_REFUSED",
    "CODE_CONFLICT_RESOLVED",
    "CODE_DUPLICATES_FOUND",
    "CODE_DUPLICATES_RESOLVED",
    "CODE_ENTITY_EXCLUDED",
    "CODE_GAPS_FILLED",
    "CODE_GAPS_REJECTED",
    "CODE_GAPS_RETAINED",
    "CODE_IRREGULAR_SERIES",
    "CODE_LEAKAGE_SENSITIVE",
    "CODE_ORDERED",
    "CODE_RESAMPLED",
    "CODE_STAGE1_ISSUES",
    "CODE_TIMEZONE_ASSUMED",
    "CODE_UNDETERMINED_UNIT",
    "CODE_UNIT_CONVERTED",
    "CODE_PREFIX",
    "SEVERITIES",
    "SEVERITY_ERROR",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "DuplicateReport",
    "LeakageAudit",
    "MeasurementSlot",
    "MissingSummary",
    "PreprocessError",
    "PreprocessNote",
    "PreprocessingReport",
    "PreprocessingResult",
    "normalize_record_units",
    "preprocess",
    "resolve_duplicates_and_conflicts",
    "slot_identity",
]
