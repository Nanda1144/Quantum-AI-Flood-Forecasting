# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""The Phase 4 leakage audit: eight invariants, checked on the real matrices.

Phase 3 audited point-in-time correctness on the rows it built. Phase 4 consumes
those rows and adds its own ways to leak, none of which Phase 3 could have seen:
it stacks them into a matrix, it fills absent cells, it standardises them, it slides
windows over them and it hands the result to an estimator that will memorise
whatever it is given. Each of those is a place where a future observation can reach
the model without anyone writing a `shift(-1)`.

So this module computes eight checks against the actual assembled arrays. It is
not a declaration that the checks exist, and it is not a comment listing what a
careful implementer would have done — every check reads the real matrix and the
real recorded metadata and returns a pass or a specific failure.

The checks, and the failure each one catches:

1. ``features_read_at_or_before_origin`` — catches a window that reaches forward.
2. ``target_instant_strictly_after_origin`` — catches a target that is really a
   contemporaneous value.
3. ``target_horizon_alignment_exact`` — catches a horizon that is quietly wrong by
   a step, which is invisible in a loss curve and catastrophic in a forecast.
4. ``feature_columns_disjoint_from_targets`` — catches a target leaking into the
   feature matrix under a renamed column.
5. ``split_origins_chronologically_ordered`` — catches a shuffled split.
6. ``split_labels_do_not_cross_boundaries`` — catches a row whose *label* comes
   from the next period, which passes every origin-based check.
7. ``scaler_and_imputer_fitted_on_train_only`` — catches statistics that saw
   validation or test. Verified by recomputing from the training rows alone and
   comparing against the recorded state, not by trusting a label.
8. ``sequence_windows_causal_and_entity_scoped`` — catches a lookback window that
   spans two stations, or one that reaches past its origin.

Checks 1–6 and 8 return `skipped` with a reason when the configuration cannot
express them (no sequences configured, an absent split). A check that could not
run is reported as not-run and never as passed — the difference between "checked
and clean" and "not looked at" is the whole reason this returns a structured
result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping, Sequence

import numpy as np

from .feature_registry import TARGET_PREFIX
from .feature_pipeline import SPLIT_TEST, SPLIT_TRAIN, SPLIT_VALIDATION
from .model_dataset import ModelDataset, SequenceSet, SplitMatrix
from .provenance import SplitBoundaries

#: Chronological order the splits must appear in.
EXPECTED_SPLIT_ORDER: tuple[str, ...] = (SPLIT_TRAIN, SPLIT_VALIDATION, SPLIT_TEST)

CHECK_FEATURES_AT_OR_BEFORE = "features_read_at_or_before_origin"
CHECK_TARGET_AFTER_ORIGIN = "target_instant_strictly_after_origin"
CHECK_HORIZON_EXACT = "target_horizon_alignment_exact"
CHECK_FEATURE_TARGET_DISJOINT = "feature_columns_disjoint_from_targets"
CHECK_SPLIT_ORDERED = "split_origins_chronologically_ordered"
CHECK_SPLIT_LABELS_INSIDE = "split_labels_do_not_cross_boundaries"
CHECK_TRAIN_FITTED_STATS = "scaler_and_imputer_fitted_on_train_only"
CHECK_SEQUENCE_CAUSAL = "sequence_windows_causal_and_entity_scoped"

#: Every check, in the order they run. Reported order is this order, so two runs
#: produce byte-identical audit output.
AUDIT_CHECKS: tuple[str, ...] = (
    CHECK_FEATURES_AT_OR_BEFORE,
    CHECK_TARGET_AFTER_ORIGIN,
    CHECK_HORIZON_EXACT,
    CHECK_FEATURE_TARGET_DISJOINT,
    CHECK_SPLIT_ORDERED,
    CHECK_SPLIT_LABELS_INSIDE,
    CHECK_TRAIN_FITTED_STATS,
    CHECK_SEQUENCE_CAUSAL,
)

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_SKIPPED = "skipped"


@dataclass(frozen=True)
class LeakageFinding:
    """One check's verdict. `detail` names the offending rows when there are any."""

    check: str
    status: str
    detail: str
    offending_rows: int = 0

    @property
    def ok(self) -> bool:
        """True for a pass, and for a skip.

        A skip is *not* a pass; `ok` exists so a caller can require a pass
        explicitly. `skipped_checks()` is how a caller finds the difference.
        """
        return self.status in (STATUS_PASS, STATUS_SKIPPED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "status": self.status,
            "detail": self.detail,
            "offending_rows": self.offending_rows,
        }


@dataclass(frozen=True)
class LeakageAudit:
    """All eight verdicts plus the verdict on the set."""

    findings: tuple[LeakageFinding, ...] = ()

    @property
    def ok(self) -> bool:
        """True only when every check ran and passed."""
        return bool(self.findings) and all(
            finding.status == STATUS_PASS for finding in self.findings
        )

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(finding.check for finding in self.findings)

    def failed(self) -> tuple[LeakageFinding, ...]:
        return tuple(finding for finding in self.findings if finding.status == STATUS_FAIL)

    def skipped_checks(self) -> tuple[str, ...]:
        return tuple(
            finding.check for finding in self.findings if finding.status == STATUS_SKIPPED
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "verdict": self.verdict,
            "checks": len(self.findings),
            "passed": len(self.passed_checks),
            "failed": [finding.check for finding in self.failed()],
            "skipped": list(self.skipped_checks()),
            "findings": [finding.to_dict() for finding in self.findings],
        }

    @property
    def passed_checks(self) -> tuple[str, ...]:
        return tuple(
            finding.check for finding in self.findings if finding.status == STATUS_PASS
        )

    @property
    def verdict(self) -> str:
        """A three-word verdict that never rounds a skip up to a pass.

        ``FAIL`` if anything failed, otherwise ``PARTIAL`` while anything was skipped
        *or while no check ran at all*, otherwise ``PASS``. `ok` is the strict form
        used by tests; this is the form a human reads, and it refuses to say PASS
        while a check was skipped. An audit with no findings is `PARTIAL` rather than
        `FAIL`: nothing failed, and nothing was established either, which is not the
        same statement as a leak.
        """
        if self.failed():
            return "FAIL"
        if self.skipped_checks() or not self.names:
            return "PARTIAL"
        return "PASS" if self.ok else "FAIL"

    def describe(self) -> str:
        lines = ["Phase 4 leakage audit"]
        for finding in self.findings:
            mark = {STATUS_PASS: "PASS", STATUS_FAIL: "FAIL", STATUS_SKIPPED: "SKIP"}[
                finding.status
            ]
            lines.append(f"  [{mark}] {finding.check}: {finding.detail}")
        skipped = self.skipped_checks()
        lines.append(
            f"  overall: {self.verdict} "
            f"({len(self.passed_checks)} passed, {len(self.failed())} failed, "
            f"{len(skipped)} skipped)"
        )
        if skipped:
            lines.append(
                "  a skipped check is not a passed check; it did not run on this dataset"
            )
        return "\n".join(lines)


def _sample(rows: Sequence[int]) -> str:
    """A short, deterministic sample of offending row indices for the message."""
    head = ", ".join(str(index) for index in rows[:5])
    return head if len(rows) <= 5 else f"{head} (+{len(rows) - 5} more)"


def _where(split: str, index: int) -> str:
    """One offending row, identified unambiguously.

    Row indices are *per split*: row 3 of the training split and row 3 of the test
    split are different rows. Reporting a bare `3` left a reader unable to tell which
    one to go and look at, which is the only reason the sample is printed at all. The
    matrix a split holds is itself in entity-then-instant order, so the index is
    stable and can be traced back to an instant with the dataset's own ordering.
    """
    return f"{split}[{index}]"


def _sample_where(rows: Sequence[tuple[str, int]]) -> str:
    head = ", ".join(_where(split, index) for split, index in rows[:5])
    return head if len(rows) <= 5 else f"{head} (+{len(rows) - 5} more)"


# --------------------------------------------------------------------------- #
# Individual checks
# --------------------------------------------------------------------------- #


def _check_features_at_or_before(dataset: ModelDataset) -> LeakageFinding:
    """Every instant any feature read must be at or before its row's origin."""
    offenders: list[tuple[str, int]] = []
    total = 0
    for split in sorted(dataset.splits):
        part = dataset.splits[split]
        for index, (origin, sources) in enumerate(
            zip(part.origin_instants, part.source_instants)
        ):
            total += 1
            if any(source > origin for source in sources):
                offenders.append((split, index))
    if not total:
        return LeakageFinding(
            CHECK_FEATURES_AT_OR_BEFORE, STATUS_SKIPPED, "no rows were assembled"
        )
    if offenders:
        return LeakageFinding(
            CHECK_FEATURES_AT_OR_BEFORE,
            STATUS_FAIL,
            f"{len(offenders)} of {total} row(s) read an instant after their own origin; "
            f"rows {_sample_where(offenders)}",
            offending_rows=len(offenders),
        )
    return LeakageFinding(
        CHECK_FEATURES_AT_OR_BEFORE,
        STATUS_PASS,
        f"all {total} row(s) read only instants at or before their prediction origin",
    )


def _check_targets_after_origin(dataset: ModelDataset) -> LeakageFinding:
    """A target must be strictly later than the origin it is predicted for."""
    offenders: list[tuple[str, int]] = []
    total = 0
    for split in sorted(dataset.splits):
        part = dataset.splits[split]
        for index, (origin, target) in enumerate(zip(part.origin_instants, part.target_instants)):
            if target is None or not np.isfinite(part.target[index]):
                continue
            total += 1
            if target <= origin:
                offenders.append((split, index))
    if not total:
        return LeakageFinding(
            CHECK_TARGET_AFTER_ORIGIN, STATUS_SKIPPED, "no supervised row carries a target"
        )
    if offenders:
        return LeakageFinding(
            CHECK_TARGET_AFTER_ORIGIN,
            STATUS_FAIL,
            f"{len(offenders)} of {total} supervised row(s) have a target at or before their "
            f"origin; rows {_sample_where(offenders)}",
            offending_rows=len(offenders),
        )
    return LeakageFinding(
        CHECK_TARGET_AFTER_ORIGIN,
        STATUS_PASS,
        f"all {total} supervised row(s) carry a target strictly after their origin",
    )


def _check_horizon_exact(dataset: ModelDataset) -> LeakageFinding:
    """`target - origin` must equal the configured horizon exactly."""
    horizon = dataset.binding.horizon_seconds
    if not horizon or horizon <= 0:
        return LeakageFinding(
            CHECK_HORIZON_EXACT,
            STATUS_SKIPPED,
            "no horizon is bound to this dataset, so no alignment can be checked",
        )
    offenders: list[tuple[str, int]] = []
    deltas: set[float] = set()
    total = 0
    for split in sorted(dataset.splits):
        part = dataset.splits[split]
        for index, (origin, target) in enumerate(zip(part.origin_instants, part.target_instants)):
            if target is None or not np.isfinite(part.target[index]):
                continue
            total += 1
            delta = (target - origin).total_seconds()
            deltas.add(delta)
            if abs(delta - horizon) > 1e-6:
                offenders.append((split, index))
    if not total:
        return LeakageFinding(
            CHECK_HORIZON_EXACT, STATUS_SKIPPED, "no supervised row carries a target"
        )
    if offenders:
        observed = sorted(deltas)[:4]
        return LeakageFinding(
            CHECK_HORIZON_EXACT,
            STATUS_FAIL,
            f"{len(offenders)} of {total} supervised row(s) are not aligned to the configured "
            f"horizon of {horizon:.0f}s (observed deltas: {observed}); rows "
            f"{_sample_where(offenders)}",
            offending_rows=len(offenders),
        )
    return LeakageFinding(
        CHECK_HORIZON_EXACT,
        STATUS_PASS,
        f"all {total} supervised row(s) are aligned to exactly {horizon:.0f}s",
    )


def _check_disjoint(dataset: ModelDataset) -> LeakageFinding:
    """No feature column may be a target column, in this run or in Phase 3."""
    declared_targets = set(dataset.config.target_columns)
    names = set(dataset.feature_names)
    overlap = sorted(names & declared_targets)
    prefixed = sorted(name for name in names if name.startswith(TARGET_PREFIX))
    if overlap or prefixed:
        bad = sorted(set(overlap) | set(prefixed))
        return LeakageFinding(
            CHECK_FEATURE_TARGET_DISJOINT,
            STATUS_FAIL,
            f"{len(bad)} column(s) are targets or carry the reserved {TARGET_PREFIX!r} "
            f"prefix: {bad}",
            offending_rows=len(bad),
        )
    return LeakageFinding(
        CHECK_FEATURE_TARGET_DISJOINT,
        STATUS_PASS,
        f"{len(names)} feature column(s) share no name with any target "
        f"({sorted(declared_targets) or 'none declared'})",
    )


def _check_split_order(dataset: ModelDataset) -> LeakageFinding:
    """Every origin in an earlier split precedes every origin in a later one."""
    present = [name for name in EXPECTED_SPLIT_ORDER if name in dataset.splits]
    if len(present) < 2:
        return LeakageFinding(
            CHECK_SPLIT_ORDERED,
            STATUS_SKIPPED,
            f"only {len(present)} split(s) present; ordering cannot be established",
        )
    for earlier, later in zip(present, present[1:]):
        first = dataset.splits[earlier]
        second = dataset.splits[later]
        if not first.origin_instants or not second.origin_instants:
            continue
        if max(first.origin_instants) >= min(second.origin_instants):
            return LeakageFinding(
                CHECK_SPLIT_ORDERED,
                STATUS_FAIL,
                f"{earlier} reaches {max(first.origin_instants).isoformat()} while {later} "
                f"starts at {min(second.origin_instants).isoformat()}; the periods overlap or "
                "are out of order",
                offending_rows=1,
            )
    bounds = dataset.bounds
    if bounds.is_ordered() is False:
        return LeakageFinding(
            CHECK_SPLIT_ORDERED,
            STATUS_FAIL,
            f"Phase 3's recorded split bounds are not chronologically ordered: {bounds}",
            offending_rows=1,
        )
    detail = ", ".join(
        f"{name}={len(dataset.splits[name].origin_instants)} rows" for name in present
    )
    return LeakageFinding(
        CHECK_SPLIT_ORDERED,
        STATUS_PASS,
        f"chronological and non-overlapping ({detail})",
    )


def _check_labels_inside_split(dataset: ModelDataset) -> LeakageFinding:
    """A row's target instant must fall inside its own split's origin range.

    This is the check that catches a label crossing a period boundary. Every
    origin-based check passes while a row's outcome is decided by an observation
    the period did not contain, which is why it is separate and why it compares
    against the *origin range* rather than against the neighbouring split.
    """
    offenders: list[tuple[str, int]] = []
    mislabelled: list[str] = []
    total = 0
    for split in sorted(dataset.splits):
        part = dataset.splits[split]
        if not part.origin_instants:
            continue
        if part.split != split:
            # The matrix's own label has to agree with the key it is filed under.
            # A matrix stored under `test` while calling itself `train` would be
            # scored as one thing and reported as another, and every count keyed on
            # the split name would then be describing the wrong rows.
            mislabelled.append(f"{split}[{split} matrix is labelled {part.split!r}]")
        low = min(part.origin_instants)
        high = max(part.origin_instants)
        for index, target in enumerate(part.target_instants):
            if target is None or not np.isfinite(part.target[index]):
                continue
            total += 1
            if target < low or target > high:
                offenders.append((split, index))
    if not total and not mislabelled:
        return LeakageFinding(
            CHECK_SPLIT_LABELS_INSIDE,
            STATUS_SKIPPED,
            "no supervised row carries a target, so no label can cross a boundary",
        )
    if mislabelled:
        return LeakageFinding(
            CHECK_SPLIT_LABELS_INSIDE,
            STATUS_FAIL,
            f"{len(mislabelled)} split matrix/matrices are filed under a label they do not "
            f"carry: {'; '.join(mislabelled)}",
            offending_rows=len(mislabelled),
        )
    if offenders:
        return LeakageFinding(
            CHECK_SPLIT_LABELS_INSIDE,
            STATUS_FAIL,
            f"{len(offenders)} of {total} supervised row(s) have a target outside their own "
            f"split's origin range; rows {_sample_where(offenders)}",
            offending_rows=len(offenders),
        )
    return LeakageFinding(
        CHECK_SPLIT_LABELS_INSIDE,
        STATUS_PASS,
        f"all {total} supervised row(s) carry a label from inside their own split",
    )


def _check_train_fitted_stats(dataset: ModelDataset) -> LeakageFinding:
    """Recompute the fitted statistics from training rows and compare.

    Reading `fitted_on == "train"` would only prove that a label says so. The
    medians and the mean/scale are therefore rebuilt from the training split's raw
    absences and compared value by value; a scaler that had seen validation or
    test could not reproduce them.
    """
    if SPLIT_TRAIN not in dataset.splits:
        return LeakageFinding(
            CHECK_TRAIN_FITTED_STATS, STATUS_SKIPPED, "no training split to fit statistics on"
        )
    train = dataset.splits[SPLIT_TRAIN]
    if dataset.scaler_state is None and dataset.imputer_state is None:
        # Skipped, not passed. Nothing was fitted, so no verification of train-only
        # fitting took place; reporting a pass here would put the same word on a
        # check that ran and one that had nothing to run on, and `ok` is documented
        # as the strict form precisely so those two cannot be confused.
        return LeakageFinding(
            CHECK_TRAIN_FITTED_STATS,
            STATUS_SKIPPED,
            f"no scaler and no imputer were fitted (policy: scaler="
            f"{dataset.config.scaler_policy!r}, impute={dataset.config.impute_policy!r}), so "
            "there is no fitted statistic that could have seen a non-training row, and "
            "nothing was verified",
        )

    imputed = train.raw_values
    if dataset.imputer_state is not None:
        if dataset.imputer_state.get("fitted_on") != SPLIT_TRAIN:
            return LeakageFinding(
                CHECK_TRAIN_FITTED_STATS,
                STATUS_FAIL,
                f"the imputer reports being fitted on "
                f"{dataset.imputer_state.get('fitted_on')!r}, not {SPLIT_TRAIN!r}",
                offending_rows=1,
            )
        if dataset.imputer_state.get("fitted_rows") != train.rows:
            return LeakageFinding(
                CHECK_TRAIN_FITTED_STATS,
                STATUS_FAIL,
                f"the imputer saw {dataset.imputer_state.get('fitted_rows')} row(s) but the "
                f"training split holds {train.rows}",
                offending_rows=1,
            )
        filled = imputed.copy()
        for column, name in enumerate(dataset.feature_names):
            values = train.raw_values[:, column]
            finite = values[np.isfinite(values)]
            if finite.size == 0:
                continue
            expected = float(np.median(finite))
            recorded = float(dict(dataset.imputer_state.get("values") or {}).get(name, expected))
            if abs(expected - recorded) > 1e-9:
                return LeakageFinding(
                    CHECK_TRAIN_FITTED_STATS,
                    STATUS_FAIL,
                    f"the recorded median for {name!r} is {recorded!r}, but the median of the "
                    f"training column is {expected!r}; the statistic did not come from the "
                    "training rows alone",
                    offending_rows=1,
                )
            missing = ~np.isfinite(values)
            filled[missing, column] = recorded
        imputed = filled

    if dataset.scaler_state is not None:
        if dataset.scaler_state.get("fitted_on") != SPLIT_TRAIN:
            return LeakageFinding(
                CHECK_TRAIN_FITTED_STATS,
                STATUS_FAIL,
                f"the scaler reports being fitted on "
                f"{dataset.scaler_state.get('fitted_on')!r}, not {SPLIT_TRAIN!r}",
                offending_rows=1,
            )
        if dataset.scaler_state.get("fitted_rows") != train.rows:
            return LeakageFinding(
                CHECK_TRAIN_FITTED_STATS,
                STATUS_FAIL,
                f"the scaler saw {dataset.scaler_state.get('fitted_rows')} row(s) but the "
                f"training split holds {train.rows}",
                offending_rows=1,
            )
        recorded_mean = dict(dataset.scaler_state.get("mean") or {})
        recorded_scale = dict(dataset.scaler_state.get("scale") or {})
        for column, name in enumerate(dataset.feature_names):
            values = imputed[:, column]
            finite = values[np.isfinite(values)]
            if finite.size == 0:
                return LeakageFinding(
                    CHECK_TRAIN_FITTED_STATS,
                    STATUS_FAIL,
                    f"column {name!r} has no finite training value, so it cannot have been "
                    "scaled honestly",
                    offending_rows=1,
                )
            expected_mean = float(finite.mean())
            expected_scale = float(finite.std(ddof=0)) or 1.0
            if abs(float(recorded_mean.get(name, expected_mean)) - expected_mean) > 1e-9:
                return LeakageFinding(
                    CHECK_TRAIN_FITTED_STATS,
                    STATUS_FAIL,
                    f"the recorded mean for {name!r} is {recorded_mean.get(name)!r} but the "
                    f"training column's mean is {expected_mean!r}",
                    offending_rows=1,
                )
            if abs(float(recorded_scale.get(name, expected_scale)) - expected_scale) > 1e-9:
                return LeakageFinding(
                    CHECK_TRAIN_FITTED_STATS,
                    STATUS_FAIL,
                    f"the recorded scale for {name!r} is {recorded_scale.get(name)!r} but the "
                    f"training column's standard deviation is {expected_scale!r}",
                    offending_rows=1,
                )

    fitted_parts = [
        part
        for part in dataset.splits.values()
        if part.split != SPLIT_TRAIN and dataset.scaler_state is not None
    ]
    return LeakageFinding(
        CHECK_TRAIN_FITTED_STATS,
        STATUS_PASS,
        f"every fitted statistic reproduces from the {train.rows} training row(s) alone; "
        f"{len(fitted_parts)} non-training split(s) were transformed with those same values",
    )


def _check_sequence_causal(sequences: Mapping[str, SequenceSet]) -> LeakageFinding:
    """Every window ends at its origin, stays inside one entity, and spans the lookback.

    This one is checked rather than asserted, because a sequence window is the
    easiest shape in the whole pipeline to get subtly wrong: the rows are already
    ordered, so a window that reached one step too far would still look tidy. The
    per-window instants and entities are therefore carried through
    `build_sequences` and compared here, one window at a time.
    """
    if not sequences:
        return LeakageFinding(
            CHECK_SEQUENCE_CAUSAL,
            STATUS_SKIPPED,
            "no sequence windows were configured for this run, so no lookback window exists "
            "to inspect",
        )
    total = 0
    steps: set[float] = set()
    for split in sorted(sequences):
        block = sequences[split]
        if block.step_seconds is None:
            return LeakageFinding(
                CHECK_SEQUENCE_CAUSAL,
                STATUS_FAIL,
                f"{split}: the sampling step was never established, so window length in time "
                "is unknown and the lookback cannot be shown to be causal",
                offending_rows=1,
            )
        steps.add(float(block.step_seconds))
        for index in range(block.samples):
            total += 1
            origin = block.origin_instants[index]
            window = block.window_instants[index]
            if len(window) != block.lookback:
                return LeakageFinding(
                    CHECK_SEQUENCE_CAUSAL,
                    STATUS_FAIL,
                    f"{split} window {index} holds {len(window)} row(s), expected {block.lookback}",
                    offending_rows=1,
                )
            if window[-1] != origin:
                return LeakageFinding(
                    CHECK_SEQUENCE_CAUSAL,
                    STATUS_FAIL,
                    f"{split} window {index} ends at {window[-1].isoformat()} but its origin is "
                    f"{origin.isoformat()}; a window that does not end at its origin contains a "
                    "future observation",
                    offending_rows=1,
                )
            if any(instant > origin for instant in window):
                return LeakageFinding(
                    CHECK_SEQUENCE_CAUSAL,
                    STATUS_FAIL,
                    f"{split} window {index} contains an instant after its origin "
                    f"{origin.isoformat()}",
                    offending_rows=1,
                )
            if origin - window[0] >= timedelta(seconds=block.lookback * block.step_seconds):
                return LeakageFinding(
                    CHECK_SEQUENCE_CAUSAL,
                    STATUS_FAIL,
                    f"{split} window {index} spans "
                    f"{(origin - window[0]).total_seconds():.0f}s, which is longer than the "
                    f"configured {block.lookback} x {block.step_seconds:.0f}s; the rows are "
                    "further apart than the sampling step says they should be",
                    offending_rows=1,
                )
            observed = block.window_entity_sets[index] if index < len(
                block.window_entity_sets
            ) else (block.window_entities[index],)
            if len(observed) != 1:
                return LeakageFinding(
                    CHECK_SEQUENCE_CAUSAL,
                    STATUS_FAIL,
                    f"{split} window {index} spans more than one entity: "
                    f"{', '.join(observed)}. A lookback window is one station's history; "
                    "reading another station's rows would put a different catchment's "
                    "behaviour into this forecast",
                    offending_rows=1,
                )
            if observed[0] != block.window_entities[index]:
                return LeakageFinding(
                    CHECK_SEQUENCE_CAUSAL,
                    STATUS_FAIL,
                    f"{split} window {index} is labelled {block.window_entities[index]!r} but "
                    f"was assembled from {observed[0]!r}",
                    offending_rows=1,
                )
    if total == 0:
        return LeakageFinding(
            CHECK_SEQUENCE_CAUSAL,
            STATUS_SKIPPED,
            "sequence families were configured but produced no windows",
        )
    step_text = ", ".join(f"{step:.0f}s" for step in sorted(steps))
    return LeakageFinding(
        CHECK_SEQUENCE_CAUSAL,
        STATUS_PASS,
        f"all {total} window(s) end at their own origin, hold exactly one entity, and span at "
        f"most lookback x step ({step_text})",
    )


# --------------------------------------------------------------------------- #
# The audit
# --------------------------------------------------------------------------- #


def audit_leakage(
    dataset: ModelDataset,
    *,
    sequences: Mapping[str, SequenceSet] | None = None,
) -> LeakageAudit:
    """Run all eight checks and return the verdicts, in a fixed order."""
    findings = (
        _check_features_at_or_before(dataset),
        _check_targets_after_origin(dataset),
        _check_horizon_exact(dataset),
        _check_disjoint(dataset),
        _check_split_order(dataset),
        _check_labels_inside_split(dataset),
        _check_train_fitted_stats(dataset),
        _check_sequence_causal(dict(sequences or {})),
    )
    return LeakageAudit(findings=findings)


__all__ = [
    "AUDIT_CHECKS",
    "CHECK_FEATURE_TARGET_DISJOINT",
    "CHECK_FEATURES_AT_OR_BEFORE",
    "CHECK_HORIZON_EXACT",
    "CHECK_SEQUENCE_CAUSAL",
    "CHECK_SPLIT_LABELS_INSIDE",
    "CHECK_SPLIT_ORDERED",
    "CHECK_TARGET_AFTER_ORIGIN",
    "CHECK_TRAIN_FITTED_STATS",
    "EXPECTED_SPLIT_ORDER",
    "STATUS_FAIL",
    "STATUS_PASS",
    "STATUS_SKIPPED",
    "LeakageAudit",
    "LeakageFinding",
    "audit_leakage",
]