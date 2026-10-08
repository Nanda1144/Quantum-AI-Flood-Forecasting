# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 1 — structural validation and data-quality metadata for domain records.

Two layers, deliberately separate
--------------------------------
`domains.py` raises `SchemaError` the moment a record cannot be constructed at
all. This module answers a different question: *"before* anything is
constructed, what is wrong with this batch?"* Two entry points:

| Function | Input | Purpose |
| --- | --- | --- |
| `validate_observation_payload` | a raw mapping from a source | report **every** problem in one pass, so an ingest of 10,000 rows does not die on row 3 and hide 9,997 others |
| `validate_observation` | a constructed `Observation` | assess a record that already satisfies the schema |
| `check_collection` | a sequence of records | duplicates and conflicting values across records |
| `check_flood_events` / `check_risk_records` | event / risk sequences | the same two questions, per domain |

Relationship to `preprocessing.py`
---------------------------------
They answer different questions and both are needed:

* **Phase 1 (here)** — is this *shaped* like an observation, and is it
  self-consistent? Units present, instant qualified, domain matches the
  quantity, provenance declared.
* **Phase 2 (`preprocessing.py`)** — is this *frame* usable for training?
  Ordering, missing-value policy, chronological splitting, train-fitted
  scaling.

There is no overlap and no competition: this module never resamples, fills,
scales or splits, and `preprocessing` never inspects provenance.

The rule that shapes everything
-------------------------------
**A validator reports; it does not repair.** No duplicate is silently collapsed,
no conflicting pair is resolved to a winner, no missing value is filled. A source
that disagrees with itself produces a conflict report, not a guess. Silently
choosing one of two disagreeing gauge readings is how a dataset acquires a
history that never happened.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .domains import (
    CANONICAL_QUANTITY,
    DATA_DOMAINS,
    MEASUREMENT_DOMAINS,
    QUALITY_OK,
    QUALITY_REJECTED,
    QUALITY_SUSPECT,
    QUALITY_UNKNOWN,
    ColumnBinding,
    FloodEvent,
    Observation,
    RiskScoreRecord,
    SchemaError,
    domain_spec,
    parse_instant,
    unit_is_known,
)

# --------------------------------------------------------------------------- #
# Issue vocabulary
# --------------------------------------------------------------------------- #

#: A finding that makes the record unusable. Any error issue ⇒ the record is
#: rejected.
SEVERITY_ERROR = "error"
#: A finding that does not block use but must travel with the record.
SEVERITY_WARNING = "warning"

# Stable issue codes. They are written to `hydro_data_quality_report.issues`
# (JSONB) and are therefore a query surface, so they are treated as part of the
# contract: add, never re-spell.
CODE_MISSING_TIMESTAMP = "missing_timestamp"
CODE_INVALID_TIMESTAMP = "invalid_timestamp"
CODE_MISSING_LOCATION = "missing_location_reference"
CODE_MISSING_MEASUREMENT = "missing_measurement"
CODE_MISSING_UNIT = "missing_unit"
CODE_MISSING_QUANTITY = "missing_quantity"
CODE_UNKNOWN_UNIT = "unknown_unit"
CODE_NON_FINITE_VALUE = "non_finite_value"
CODE_NON_NUMERIC_VALUE = "non_numeric_value"
CODE_NEGATIVE_RAINFALL = "negative_rainfall"
CODE_NEGATIVE_FLOW = "negative_flow"
CODE_DOMAIN_QUANTITY_MISMATCH = "domain_quantity_mismatch"
CODE_UNKNOWN_DOMAIN = "unknown_domain"
CODE_UNKNOWN_DATASET_TYPE = "unknown_dataset_type"
CODE_MISSING_DISCLAIMER = "missing_disclaimer"
CODE_RATE_WITHOUT_WINDOW = "rate_without_measurement_window"
CODE_ABSENT_COLUMN = "absent_column"
CODE_UNMAPPED_COLUMN = "unmapped_column"
CODE_DUPLICATE_RECORD = "duplicate_record"
CODE_CONFLICTING_VALUES = "conflicting_values"
CODE_MISSING_SOURCE = "missing_source_reference"

#: Findings that do not block use but should be recorded.
NON_BLOCKING_CODES = frozenset(
    {
        CODE_UNKNOWN_UNIT,
        CODE_RATE_WITHOUT_WINDOW,
        CODE_ABSENT_COLUMN,
        CODE_UNMAPPED_COLUMN,
        CODE_MISSING_SOURCE,
    }
)


@dataclass(frozen=True)
class QualityIssue:
    """One finding, with a stable code so it can be queried rather than parsed."""

    code: str
    message: str
    severity: str = SEVERITY_ERROR

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("QualityIssue.code must not be blank")
        if self.severity not in (SEVERITY_ERROR, SEVERITY_WARNING):
            raise ValueError(
                f"severity must be {SEVERITY_ERROR!r} or {SEVERITY_WARNING!r}, "
                f"got {self.severity!r}"
            )

    @property
    def is_error(self) -> bool:
        return self.severity == SEVERITY_ERROR

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "severity": self.severity}


@dataclass(frozen=True)
class ValidationReport:
    """The complete set of findings for one record or one batch.

    `quality_status` is the single value a store should persist. It is derived,
    never guessed: one error ⇒ `rejected`; no errors but a warning ⇒ `suspect`;
    nothing found ⇒ `ok`.

    The third case needs `assessed`. An **empty** `ValidationReport()` means
    nobody inspected the subject, and it reports `unknown` rather than `ok`:
    certifying a record as clean because nothing has been checked yet is exactly
    the claim this project refuses to make. So "an assessment happened" is a
    separate fact from "no findings were produced", and every entry point in this
    module sets `assessed` rather than leaving it to be inferred from emptiness.
    """

    issues: tuple[QualityIssue, ...] = ()
    subject: str = ""
    assessed: bool = False

    @property
    def errors(self) -> tuple[QualityIssue, ...]:
        return tuple(issue for issue in self.issues if issue.is_error)

    @property
    def warnings(self) -> tuple[QualityIssue, ...]:
        return tuple(issue for issue in self.issues if not issue.is_error)

    @property
    def ok(self) -> bool:
        """True when no *error* finding was recorded. Warnings still allow `ok`."""
        return not self.errors

    @property
    def has_rejection(self) -> bool:
        """True when this report rejects its subject."""
        return bool(self.errors)

    @property
    def quality_status(self) -> str:
        if self.errors:
            return QUALITY_REJECTED
        if self.warnings:
            return QUALITY_SUSPECT
        return QUALITY_OK if self.assessed else QUALITY_UNKNOWN

    def codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues)

    def has(self, code: str) -> bool:
        return any(issue.code == code for issue in self.issues)

    def describe(self) -> str:
        if not self.issues:
            if not self.assessed:
                return f"[{self.subject}] not assessed"
            return f"[{self.subject}] no findings"
        lines = [f"[{self.subject}] {len(self.errors)} error(s), {len(self.warnings)} warning(s)"]
        lines.extend(f"    {issue.severity.upper()}: {issue.code}: {issue.message}" for issue in self.issues)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "assessed": self.assessed,
            "quality_status": self.quality_status,
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def summarise(reports: Sequence[ValidationReport]) -> dict[str, Any]:
    """Aggregate a batch of reports into the counters a quality record stores.

    `records_checked` counts every subject, including the ones that produced no
    findings, so the ratio `records_rejected / records_checked` is meaningful.
    Reports for an uninspected subject are not counted as `ok` — see
    `ValidationReport.quality_status`, which returns `unknown` for an empty
    report.
    """
    code_counts: dict[str, int] = {}
    for report in reports:
        for issue in report.issues:
            code_counts[issue.code] = code_counts.get(issue.code, 0) + 1
    rejected = sum(1 for report in reports if report.has_rejection)
    return {
        "records_checked": len(reports),
        "records_rejected": rejected,
        "records_clean": sum(1 for report in reports if report.quality_status == QUALITY_OK),
        "records_suspect": sum(1 for report in reports if report.quality_status == QUALITY_SUSPECT),
        "issue_counts": dict(sorted(code_counts.items())),
        "quality_status": QUALITY_REJECTED if rejected else QUALITY_OK,
    }


# --------------------------------------------------------------------------- #
# Payload validation (pre-construction)
# --------------------------------------------------------------------------- #


#: The keys `Observation.to_dict()` / `from_dict()` agree on. Supplied here so
#: that a binding check can tell a record's own metadata apart from an extra
#: column that arrived from a source.
RECORD_PAYLOAD_KEYS = frozenset(
    {
        "domain",
        "location_reference",
        "observed_at",
        "measurements",
        "measurement_window",
        "source_reference",
        "provenance_reference",
        "dataset_reference",
        "dataset_type",
        "quality_status",
        "disclaimer",
        "notes",
    }
)


def _looks_like_number(value: Any) -> bool:
    """True when `value` could be read as a real number.

    Strings are accepted because CSV exports carry everything as text, but `bool`
    is refused explicitly: `True` would otherwise coerce to `1.0` and become a
    plausible-looking measurement of 1.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value)
        except ValueError:
            return False
        return True
    return False


def validate_observation_payload(
    payload: Any,
    *,
    bindings: Sequence[ColumnBinding] = (),
    timestamp_column: str = "timestamp",
) -> ValidationReport:
    """Report every structural problem in a raw source mapping.

    Nothing is constructed and nothing is repaired. The function is total: it
    returns a report for *any* input, including `None`, a list, or a mapping of
    the wrong shape, so a batch ingest always learns what was wrong with the
    rows it could not use.

    When `bindings` are supplied, bound columns that the payload does not carry
    are reported as `absent_column` — the honest reading being "this source did
    not report this domain for this row", which is different from a zero and very
    different from a measurement.

    Both payload shapes are accepted: the record form, where the instant is
    `observed_at`, and the wide source row, where it is `timestamp_column`. That
    is not leniency for its own sake — `ingest_observations` validates a payload
    and then hands it to `Observation.from_dict`, so a validator that looked at
    one key while the builder read the other would reject every clean row.
    """
    subject = "observation-payload"
    if not isinstance(payload, Mapping):
        return ValidationReport(
            issues=(
                QualityIssue(
                    code=CODE_MISSING_MEASUREMENT,
                    message=(
                        f"expected a mapping, got {type(payload).__name__}; a record that is "
                        "not a mapping cannot be validated field-by-field"
                    ),
                ),
            ),
            subject=subject,
            assessed=True,
        )

    issues: list[QualityIssue] = []

    # --- timestamp ---------------------------------------------------------
    # `observed_at` is the record schema's name; `timestamp_column` is whatever
    # the dataset owner called it. Prefer the record key when both are present,
    # because that is the field the constructor will read.
    timestamp_key = "observed_at" if "observed_at" in payload else timestamp_column
    if payload.get(timestamp_key) in (None, ""):
        issues.append(
            QualityIssue(
                code=CODE_MISSING_TIMESTAMP,
                message=f"required column {timestamp_key!r} is absent or empty",
            )
        )
    else:
        try:
            parse_instant(str(payload[timestamp_key]))
        except SchemaError as exc:
            issues.append(
                QualityIssue(code=CODE_INVALID_TIMESTAMP, message=str(exc))
            )

    # --- location ----------------------------------------------------------
    location = payload.get("location_reference")
    if location is None or (isinstance(location, str) and not location.strip()):
        issues.append(
            QualityIssue(
                code=CODE_MISSING_LOCATION,
                message=(
                    "no location_reference; an observation that cannot be attributed to a "
                    "station, reach or catchment cannot be used"
                ),
            )
        )

    # --- domain ------------------------------------------------------------
    domain = payload.get("domain")
    if domain not in DATA_DOMAINS:
        issues.append(
            QualityIssue(
                code=CODE_UNKNOWN_DOMAIN,
                message=f"domain {domain!r} is not one of {DATA_DOMAINS}",
            )
        )
    elif domain not in MEASUREMENT_DOMAINS:
        issues.append(
            QualityIssue(
                code=CODE_UNKNOWN_DOMAIN,
                message=(
                    f"domain {domain!r} does not carry measurements; build a FloodEvent or "
                    "RiskScoreRecord for it"
                ),
            )
        )

    # --- measurements ------------------------------------------------------
    raw_measurements = payload.get("measurements")
    if raw_measurements is None or (
        isinstance(raw_measurements, Sequence)
        and not isinstance(raw_measurements, (str, bytes))
        and not raw_measurements
    ):
        issues.append(
            QualityIssue(
                code=CODE_MISSING_MEASUREMENT,
                message="no measurements; an empty measurement set is a gap, not a reading",
            )
        )
    elif isinstance(raw_measurements, Sequence) and not isinstance(raw_measurements, (str, bytes)):
        canonical = CANONICAL_QUANTITY.get(domain) if isinstance(domain, str) else None
        seen: list[str] = []
        for index, item in enumerate(raw_measurements):
            if not isinstance(item, Mapping):
                issues.append(
                    QualityIssue(
                        code=CODE_MISSING_QUANTITY,
                        message=f"measurement[{index}] must be a mapping, got {type(item).__name__}",
                    )
                )
                continue
            quantity = item.get("quantity")
            if quantity is None or (isinstance(quantity, str) and not quantity.strip()):
                issues.append(
                    QualityIssue(
                        code=CODE_MISSING_QUANTITY,
                        message=f"measurement[{index}] has no quantity",
                    )
                )
                continue
            seen.append(quantity)
            unit = item.get("unit")
            if unit is None or (isinstance(unit, str) and not unit.strip()):
                issues.append(
                    QualityIssue(
                        code=CODE_MISSING_UNIT,
                        message=(
                            f"measurement {quantity!r} has no unit; an unlabelled number cannot "
                            "be compared, converted or audited"
                        ),
                    )
                )
            elif not unit_is_known(str(unit)):
                issues.append(
                    QualityIssue(
                        code=CODE_UNKNOWN_UNIT,
                        message=(
                            f"unit {unit!r} is not one this repository has seen declared; it is "
                            "recorded as declared and is NOT converted or guessed. Confirm it "
                            "with the dataset owner.",
                        ),
                        severity=SEVERITY_WARNING,
                    )
                )
            value = item.get("value")
            if value is None:
                issues.append(
                    QualityIssue(
                        code=CODE_MISSING_MEASUREMENT,
                        message=f"measurement {quantity!r} has a null value",
                    )
                )
                continue
            if not _looks_like_number(value):
                issues.append(
                    QualityIssue(
                        code=CODE_NON_NUMERIC_VALUE,
                        message=f"measurement {quantity!r} holds {value!r}, which is not a number",
                    )
                )
                continue
            numeric = float(value)
            if not math.isfinite(numeric):
                # Reached by a float NaN/inf, or by the strings "nan"/"inf" that
                # some exports use as missing-value sentinels.
                issues.append(
                    QualityIssue(
                        code=CODE_NON_FINITE_VALUE,
                        message=(
                            f"measurement {quantity!r} holds {value!r}; NaN and infinity are not "
                            "measurements"
                        ),
                    )
                )
                continue
            issues.extend(_range_findings(domain, quantity, numeric))
        duplicates = sorted({q for q in seen if seen.count(q) > 1})
        if duplicates:
            issues.append(
                QualityIssue(
                    code=CODE_MISSING_QUANTITY,
                    message=(
                        f"duplicate quantity/quantities in one record: {duplicates}; two values "
                        "for one quantity at one instant are ambiguous"
                    ),
                )
            )
        if canonical is not None:
            unexpected = [q for q in seen if q != canonical]
            if unexpected:
                issues.append(
                    QualityIssue(
                        code=CODE_DOMAIN_QUANTITY_MISMATCH,
                        message=f"domain {domain!r} accepts only {canonical!r}, found {sorted(set(unexpected))}",
                    )
                )
        window = payload.get("measurement_window")
        if any(
            isinstance(item, Mapping) and _looks_like_number(item.get("value")) and item.get("unit")
            and str(item.get("unit")).strip().lower().endswith(("/h", "/hr"))
            for item in raw_measurements
        ) and not (isinstance(window, str) and window.strip()):
            issues.append(
                QualityIssue(
                    code=CODE_RATE_WITHOUT_WINDOW,
                    message=(
                        "a per-hour rate was recorded without a measurement_window; a rate "
                        "cannot be accumulated over an undeclared window. Accumulation itself "
                        "is Phase 3 work and is NOT computed here."
                    ),
                    severity=SEVERITY_WARNING,
                )
            )

    # --- provenance --------------------------------------------------------
    dataset_type = payload.get("dataset_type", "unknown")
    if dataset_type not in ("real", "synthetic", "unknown"):
        issues.append(
            QualityIssue(
                code=CODE_UNKNOWN_DATASET_TYPE,
                message=f"dataset_type {dataset_type!r} is not 'real', 'synthetic' or 'unknown'",
            )
        )
    elif dataset_type in ("synthetic", "unknown") and not payload.get("disclaimer"):
        issues.append(
            QualityIssue(
                code=CODE_MISSING_DISCLAIMER,
                message=(
                    f"dataset_type is {dataset_type!r} but no disclaimer is attached; "
                    "non-real data must carry its warning before it is stored"
                ),
            )
        )
    if not payload.get("source_reference"):
        issues.append(
            QualityIssue(
                code=CODE_MISSING_SOURCE,
                message=(
                    "no source_reference; the record says what the value is but not where it "
                    "came from"
                ),
                severity=SEVERITY_WARNING,
            )
        )

    # --- column bindings ---------------------------------------------------
    if bindings:
        for binding in bindings:
            if binding.column not in payload:
                issues.append(
                    QualityIssue(
                        code=CODE_ABSENT_COLUMN,
                        message=(
                            f"bound column {binding.column!r} ({binding.domain}) is absent from "
                            "this row; the source did not report this domain here"
                        ),
                        severity=SEVERITY_WARNING,
                    )
                )
        # A record-form payload carries the record schema's own keys, which are
        # claimed by definition. Reporting those as unmapped columns would bury
        # the one finding that matters — a genuine extra column from the source.
        claimed = (
            {binding.column for binding in bindings}
            | {timestamp_column}
            | set(RECORD_PAYLOAD_KEYS)
        )
        for column in sorted(key for key in payload if key not in claimed):
            issues.append(
                QualityIssue(
                    code=CODE_UNMAPPED_COLUMN,
                    message=(
                        f"column {column!r} is present but not bound to any domain; an unmapped "
                        "column is usually a real observation this schema was not told about"
                    ),
                    severity=SEVERITY_WARNING,
                )
            )

    return ValidationReport(issues=tuple(issues), subject=subject, assessed=True)


def _range_findings(domain: Any, quantity: str, value: float) -> list[QualityIssue]:
    """Domain-level magnitude findings.

    Only the two rules that are true regardless of datum, convention or source:
    rainfall and volumetric flow are magnitudes and cannot be negative. A negative
    *water level* is not judged here — stage is relative to an unknown datum, so
    its sign carries no information this repository has. Range and plausibility
    policy beyond this belongs to Phase 2.
    """
    findings: list[QualityIssue] = []
    if domain == "rainfall" and quantity == "rainfall" and value < 0:
        findings.append(
            QualityIssue(
                code=CODE_NEGATIVE_RAINFALL,
                message=(
                    f"rainfall of {value} is negative; a precipitation depth or intensity is "
                    "non-negative. A negative cell is usually a missing-value sentinel (for "
                    "example -999) rather than a measurement."
                ),
            )
        )
    if domain in ("discharge", "inflow") and value < 0:
        findings.append(
            QualityIssue(
                code=CODE_NEGATIVE_FLOW,
                message=(
                    f"{domain} of {value} is negative; a volumetric flow magnitude is "
                    "non-negative. Confirm the sign convention with the dataset owner."
                ),
            )
        )
    return findings


# --------------------------------------------------------------------------- #
# Record validation (post-construction)
# --------------------------------------------------------------------------- #


def validate_observation(observation: Observation) -> ValidationReport:
    """Assess a constructed observation.

    Only checks that need the constructed record: cross-field consistency and
    metadata completeness. Shape was already guaranteed by the constructor, and
    re-reporting it here would double-count in a batch summary.
    """
    subject = f"observation:{observation.domain}:{observation.location_reference}:{observation.observed_at}"
    issues: list[QualityIssue] = []

    for measurement in observation.measurements:
        if not measurement.unit_is_recognised:
            issues.append(
                QualityIssue(
                    code=CODE_UNKNOWN_UNIT,
                    message=(
                        f"unit {measurement.unit!r} is not one this repository has seen declared; "
                        "recorded as declared, NOT converted"
                    ),
                    severity=SEVERITY_WARNING,
                )
            )
        issues.extend(_range_findings(observation.domain, measurement.quantity, float(measurement.value)))
        if measurement.is_rate and observation.measurement_window is None:
            issues.append(
                QualityIssue(
                    code=CODE_RATE_WITHOUT_WINDOW,
                    message=(
                        f"quantity {measurement.quantity!r} is a per-hour rate but no "
                        "measurement_window was declared, so it cannot be accumulated "
                        "unambiguously later. Accumulation is Phase 3 work."
                    ),
                    severity=SEVERITY_WARNING,
                )
            )

    if observation.source_reference is None:
        issues.append(
            QualityIssue(
                code=CODE_MISSING_SOURCE,
                message="no source_reference recorded for this observation",
                severity=SEVERITY_WARNING,
            )
        )

    if (
        observation.dataset_type in ("synthetic", "unknown")
        and observation.disclaimer is None
    ):  # pragma: no cover - unreachable via the constructor
        issues.append(
            QualityIssue(
                code=CODE_MISSING_DISCLAIMER,
                message="non-real observation without a disclaimer",
            )
        )

    spec = domain_spec(observation.domain)
    if not spec.present_in_repository and observation.dataset_type == "real":
        # Not an error: a real record may legitimately arrive later. But this
        # repository has never held one, so it is worth saying so on the record.
        issues.append(
            QualityIssue(
                code=CODE_MISSING_SOURCE,
                message=(
                    f"domain {observation.domain!r} has no data in this repository "
                    f"({spec.availability_note})"
                ),
                severity=SEVERITY_WARNING,
            )
        )

    return ValidationReport(issues=tuple(issues), subject=subject, assessed=True)


# --------------------------------------------------------------------------- #
# Collection validation (duplicates and conflicts)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ConflictReport:
    """Duplicates and conflicting values found in a collection.

    `resolve` is not offered, and that is the design. Choosing between two
    disagreeing readings of the same instant is a dataset owner's decision that
    needs a citation — the same reason `preprocessing.resolve_duplicates` requires
    an explicit `keep` policy rather than defaulting.
    """

    subject: str
    checked: int = 0
    duplicate_keys: tuple[str, ...] = ()
    conflicting_keys: tuple[str, ...] = ()
    issues: tuple[QualityIssue, ...] = ()

    @property
    def has_duplicates(self) -> bool:
        return bool(self.duplicate_keys)

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicting_keys)

    @property
    def ok(self) -> bool:
        """True when the collection has no duplicate and no conflicting key."""
        return not self.has_duplicates and not self.has_conflicts

    def codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues)

    def has(self, code: str) -> bool:
        return any(issue.code == code for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "checked": self.checked,
            "duplicate_keys": list(self.duplicate_keys),
            "conflicting_keys": list(self.conflicting_keys),
            "has_duplicates": self.has_duplicates,
            "has_conflicts": self.has_conflicts,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _observation_key(observation: Observation) -> str:
    """Identity of an observation for duplicate/conflict purposes.

    `domain + location + instant`. The dataset reference is deliberately excluded:
    the same gauge instant reported by two datasets is a *merge* decision for the
    dataset owner, and conflating them here would hide the disagreement.
    """
    return f"{observation.domain}|{observation.location_reference}|{observation.observed_at}"


def check_observation_collection(
    observations: Sequence[Observation],
    *,
    subject: str = "observations",
) -> ConflictReport:
    """Find duplicate and conflicting observations.

    * **Duplicate** — the same `domain + location + instant` appears more than
      once with *identical* values. Reported, not collapsed.
    * **Conflict** — the same key appears more than once with *different* values.
      This is the serious one: a source that disagrees with itself at a single
      instant. It is always an error, because either reading may be the wrong one
      and the module has no basis to choose.
    """
    buckets: dict[str, list[Observation]] = {}
    for observation in observations:
        buckets.setdefault(_observation_key(observation), []).append(observation)

    duplicates: list[str] = []
    conflicts: list[str] = []
    issues: list[QualityIssue] = []
    for key, group in buckets.items():
        if len(group) < 2:
            continue
        signatures = {
            tuple(sorted((m.quantity, float(m.value), m.unit) for m in item.measurements))
            for item in group
        }
        if len(signatures) == 1:
            duplicates.append(key)
            issues.append(
                QualityIssue(
                    code=CODE_DUPLICATE_RECORD,
                    message=(
                        f"{len(group)} records share {key} with identical values; not collapsed — "
                        "the dataset owner decides which row survives"
                    ),
                )
            )
        else:
            conflicts.append(key)
            issues.append(
                QualityIssue(
                    code=CODE_CONFLICTING_VALUES,
                    message=(
                        f"{len(group)} records share {key} but disagree on their values; this "
                        "repository will not pick a winner, because either reading may be wrong"
                    ),
                )
            )

    return ConflictReport(
        subject=subject,
        checked=len(observations),
        duplicate_keys=tuple(sorted(duplicates)),
        conflicting_keys=tuple(sorted(conflicts)),
        issues=tuple(issues),
    )


def check_flood_events(events: Sequence[FloodEvent], *, subject: str = "flood_events") -> ConflictReport:
    """Duplicate and conflicting event references.

    Events are keyed by `event_reference` alone, because one event is one event
    at one area: two records claiming the same reference are either a duplicate
    import or a genuine disagreement about what happened.
    """
    buckets: dict[str, list[FloodEvent]] = {}
    for event in events:
        buckets.setdefault(event.event_reference, []).append(event)

    duplicates: list[str] = []
    conflicts: list[str] = []
    issues: list[QualityIssue] = []
    for key, group in buckets.items():
        if len(group) < 2:
            continue
        signatures = {
            (item.area_reference, item.started_at, item.ended_at, item.severity, item.status)
            for item in group
        }
        if len(signatures) == 1:
            duplicates.append(key)
            issues.append(
                QualityIssue(
                    code=CODE_DUPLICATE_RECORD,
                    message=f"{len(group)} flood events share reference {key!r} with identical fields",
                )
            )
        else:
            conflicts.append(key)
            issues.append(
                QualityIssue(
                    code=CODE_CONFLICTING_VALUES,
                    message=(
                        f"{len(group)} flood events share reference {key!r} but disagree on area, "
                        "dates or severity; this repository will not pick a winner"
                    ),
                )
            )
    return ConflictReport(
        subject=subject,
        checked=len(events),
        duplicate_keys=tuple(sorted(duplicates)),
        conflicting_keys=tuple(sorted(conflicts)),
        issues=tuple(issues),
    )


def check_risk_records(
    records: Sequence[RiskScoreRecord], *, subject: str = "risk_records"
) -> ConflictReport:
    """Duplicate and conflicting risk records, keyed by area + assessment instant.

    Re-assessing an area is legitimate — that is what a new forecast does — so two
    records for the same area are only a problem when they claim the *same*
    instant.
    """
    buckets: dict[str, list[RiskScoreRecord]] = {}
    for record in records:
        buckets.setdefault(f"{record.area_reference}|{record.assessed_at or 'unknown'}", []).append(record)

    duplicates: list[str] = []
    conflicts: list[str] = []
    issues: list[QualityIssue] = []
    for key, group in buckets.items():
        if len(group) < 2:
            continue
        signatures = {
            (item.risk_score, item.risk_level, item.threshold, item.threshold_policy, item.status)
            for item in group
        }
        if len(signatures) == 1:
            duplicates.append(key)
            issues.append(
                QualityIssue(
                    code=CODE_DUPLICATE_RECORD,
                    message=f"{len(group)} risk records share {key!r} with identical values",
                )
            )
        else:
            conflicts.append(key)
            issues.append(
                QualityIssue(
                    code=CODE_CONFLICTING_VALUES,
                    message=(
                        f"{len(group)} risk records share {key!r} but disagree; two assessments "
                        "of one instant must be reconciled by the owner, not averaged"
                    ),
                )
            )
    return ConflictReport(
        subject=subject,
        checked=len(records),
        duplicate_keys=tuple(sorted(duplicates)),
        conflicting_keys=tuple(sorted(conflicts)),
        issues=tuple(issues),
    )


# --------------------------------------------------------------------------- #
# Batch entry point
# --------------------------------------------------------------------------- #


@dataclass
class IngestReport:
    """Outcome of validating a batch of raw payloads.

    `accepted` holds the records that were built and are usable. `failures` holds
    `(index, SchemaError)` for the rows that could not be built at all — they are
    kept, not dropped, so a caller can report exactly which source rows were
    refused and why.
    """

    subject: str
    records: list[Observation] = field(default_factory=list)
    failures: list[tuple[int, str]] = field(default_factory=list)
    reports: list[ValidationReport] = field(default_factory=list)
    conflicts: ConflictReport | None = None

    @property
    def accepted_count(self) -> int:
        return len(self.records)

    def rejected(self) -> tuple[Any, ...]:
        """Accepted records that the conflict check refuses.

        Observations only, because the conflicting-key format is
        `_observation_key`. For another record type the caller reads
        `conflicts.conflicting_keys` directly rather than being handed an empty
        tuple that would read as "no problem found".
        """
        if self.conflicts is None or not self.conflicts.has_conflicts:
            return ()
        if not self.records or not isinstance(self.records[0], Observation):
            return ()
        conflicted = set(self.conflicts.conflicting_keys)
        return tuple(
            record for record in self.records if _observation_key(record) in conflicted
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "accepted_count": self.accepted_count,
            "failure_count": len(self.failures),
            "failures": [{"index": index, "error": message} for index, message in self.failures],
            "summaries": [report.to_dict() for report in self.reports],
            "conflicts": self.conflicts.to_dict() if self.conflicts is not None else None,
        }


#: Which conflict check belongs to which record type. Without this the `build`
#: parameter would be a half-promise: a caller could hand in a flood-event
#: builder and quietly lose the duplicate and conflict check that flood events
#: have, which is the one thing the batch entry point exists to guarantee.
_CONFLICT_CHECKS = {
    Observation: check_observation_collection,
    FloodEvent: check_flood_events,
    RiskScoreRecord: check_risk_records,
}


def ingest_observations(
    payloads: Iterable[Any],
    *,
    subject: str = "observations",
    build: Any = None,
) -> IngestReport:
    """Validate a batch, build what can be built, and report everything else.

    `build` is the callable that turns an accepted payload into a record. It
    defaults to `Observation.from_dict` and exists so that flood events and risk
    records — whose constructors take different arguments — can reuse the same
    reporting machinery without a second implementation of it. The matching
    duplicate/conflict check is selected from the record type, so supplying a
    builder for another domain never silently drops it.

    An empty batch leaves `conflicts` as `None`: no records means nothing was
    checked, and `None` says that, where an empty report would look like a clean
    result.

    The function never raises for bad input. An exception here would abandon the
    findings for every row after the failing one, which is the opposite of what an
    ingest needs.
    """
    outcome = IngestReport(subject=subject)
    factory = build if build is not None else Observation.from_dict

    for index, payload in enumerate(payloads):
        report = validate_observation_payload(payload)
        outcome.reports.append(report)
        if not report.ok:
            outcome.failures.append((index, report.describe()))
            continue
        try:
            outcome.records.append(factory(payload))
        except (SchemaError, TypeError, ValueError) as exc:
            outcome.failures.append((index, f"{type(exc).__name__}: {exc}"))

    checker = _CONFLICT_CHECKS.get(type(outcome.records[0])) if outcome.records else None
    if checker is not None:
        outcome.conflicts = checker(outcome.records, subject=subject)
    return outcome


__all__ = [
    "CODE_ABSENT_COLUMN",
    "CODE_CONFLICTING_VALUES",
    "CODE_DOMAIN_QUANTITY_MISMATCH",
    "CODE_DUPLICATE_RECORD",
    "CODE_INVALID_TIMESTAMP",
    "CODE_MISSING_DISCLAIMER",
    "CODE_MISSING_LOCATION",
    "CODE_MISSING_MEASUREMENT",
    "CODE_MISSING_QUANTITY",
    "CODE_MISSING_SOURCE",
    "CODE_MISSING_TIMESTAMP",
    "CODE_MISSING_UNIT",
    "CODE_NEGATIVE_FLOW",
    "CODE_NEGATIVE_RAINFALL",
    "CODE_NON_FINITE_VALUE",
    "CODE_NON_NUMERIC_VALUE",
    "CODE_RATE_WITHOUT_WINDOW",
    "CODE_UNKNOWN_DATASET_TYPE",
    "CODE_UNKNOWN_DOMAIN",
    "CODE_UNKNOWN_UNIT",
    "CODE_UNMAPPED_COLUMN",
    "NON_BLOCKING_CODES",
    "RECORD_PAYLOAD_KEYS",
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "ConflictReport",
    "IngestReport",
    "QualityIssue",
    "ValidationReport",
    "check_flood_events",
    "check_observation_collection",
    "check_risk_records",
    "ingest_observations",
    "summarise",
    "validate_observation",
    "validate_observation_payload",
]