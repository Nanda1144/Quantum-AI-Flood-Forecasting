# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 4 evaluation: metric computation, per-split reporting, model comparison.

Phase 4 computes no metric of its own. `evaluation.py` already implements MAE,
RMSE, R², NSE, peak absolute error and bias from two arrays, with no defaults and
no fallbacks; re-implementing them here would give the project two definitions
that could drift apart, and a report that disagreed with itself would be worse
than either. So this module's first job is delegation, and its second is the thing
`evaluation.py` does not do: hold the *context* a metric needs to be read
honestly.

That context is the whole point of this module. A number without its target, its
horizon, its split, its row count and its data status is not a result — it is a
number. `EvaluationOutcome` carries all of them, and `ComparisonTable` refuses to
render a row whose status is not `evaluated` with a metric beside it.

**Unavailable is never zero.** Every status that is not `evaluated` has
`metrics = None`. A model that did not train appears in the table with its
blocker text and no metric column at all, which is the only way a reader cannot
mistake "we could not measure this" for "this model was perfect".

**MAPE is not reported, and the reason is on the record.**
`PERCENT_ERROR_UNAVAILABLE_REASON` explains it rather than leaving the omission to
be noticed: a water level is measured against a datum and legitimately passes
through it, so a percentage error divides by a quantity that can approach zero
while the numerator stays finite. The metric is not undefined by accident; it is
undefined for this class of target. A guarded implementation is available behind
an explicit opt-in that reports how many rows it had to exclude, because silently
dropping the rows where a metric is well defined is how a percentage error starts
looking flattering.

**Baseline comparison is a table, not a sentence.** `baseline_delta` is computed
per metric per split against the persistence row of the same table, and is
`None` whenever the baseline has no metric for that split. Whether a model beat
persistence is a fact about this dataset; whether it is *good* is not a question
this module answers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .evaluation import (
    EvaluationError,
    compute_metrics,
)
from .model_config import COMPUTABLE_METRICS, DEFAULT_METRICS
from .model_registry import (
    DATA_STATUS_MEASURED,
    DATA_STATUS_SYNTHETIC_DEMO,
    DATA_STATUS_UNKNOWN,
    EVALUATION_DONE,
    EVALUATION_FAILED,
    EVALUATION_INSUFFICIENT_ROWS,
    EVALUATION_NOT_RUN,
    EVALUATION_STATUSES,
)
from .provenance import SYNTHETIC_METRIC_DISCLAIMER

#: The label every metric from a synthetic/demo source must carry.
SYNTHETIC_EVALUATION_LABEL = SYNTHETIC_METRIC_DISCLAIMER

#: Why no percentage error is reported by default. On the record rather than
#: inferred from a missing column.
PERCENT_ERROR_UNAVAILABLE_REASON = (
    "MAPE is not reported for a water level. The target is measured against a datum "
    "and legitimately passes through it, so |actual| approaches zero while the "
    "absolute error stays finite and the ratio diverges. A percentage error is "
    "therefore not a well-defined measure for this class of target, and reporting "
    "one after silently dropping the rows where it happened to be finite would "
    "produce a flattering number with no stated denominator."
)

#: Metric names this module knows how to report. `evaluation.SUPPORTED_METRICS`
#: is the authority for what can be computed; this tuple is the authority for
#: what Phase 4 *reports*, and it is a subset by choice.
#:
#: Aliased from `model_config.COMPUTABLE_METRICS` so the configuration's
#: early "can this be computed?" check and this module's late one read the same
#: list. Two hand-maintained copies would eventually disagree, and the
#: configuration would then accept a metric this module refused.
REPORTABLE_METRICS: tuple[str, ...] = COMPUTABLE_METRICS

#: Metrics where a lower value is better. Stated explicitly so a reader never has
#: to infer direction from the metric's name.
LOWER_IS_BETTER: frozenset[str] = frozenset({"mae", "rmse", "peak_absolute_error"})
#: Metrics where a higher value is better. `nse` was previously listed under
#: `LOWER_IS_BETTER`, which is backwards: Nash-Sutcliffe efficiency is 1.0 for a
#: perfect forecast, 0.0 for the mean, and negative for anything worse than the
#: mean, so a *lower* NSE is a *worse* model. Ranking on it ascending would select
#: the worst candidate that produced a number.
HIGHER_IS_BETTER: frozenset[str] = frozenset({"r2", "nse"})
#: `bias` is two-sided — zero is the goal, not "lower" — so it is excluded above.
TWO_SIDED_METRICS: frozenset[str] = frozenset({"bias"})


def metric_direction(metric: str) -> str:
    """Whether a higher or a lower value of `metric` is the better model.

    Returns ``"higher"``, ``"lower"``, or raises. `bias` is deliberately not
    rankable: zero is the goal, and "the lowest bias" would happily select the
    model that under-predicts hardest. Every other reportable metric has a
    direction, and it is looked up here rather than inferred at the call site.
    """
    if metric in LOWER_IS_BETTER:
        return "lower"
    if metric in HIGHER_IS_BETTER:
        return "higher"
    if metric in TWO_SIDED_METRICS:
        raise ModelEvaluationError(
            f"{metric!r} is two-sided and cannot be ranked; choose a metric where one end of the "
            "range is the goal"
        )
    raise ModelEvaluationError(
        f"{metric!r} is not a reportable metric; known metrics are {list(REPORTABLE_METRICS)}"
    )


#: The full direction table, so a reader - or Phase 5's selector - can see all three
#: cases in one place instead of inferring membership from two sets and a raise.
METRIC_DIRECTIONS: Mapping[str, str] = {
    **{metric: "lower" for metric in sorted(LOWER_IS_BETTER)},
    **{metric: "higher" for metric in sorted(HIGHER_IS_BETTER)},
    **{metric: "unrankable" for metric in sorted(TWO_SIDED_METRICS)},
}

#: Rows whose |actual| is below this are excluded from the opt-in percentage
#: error, and the count is reported.
PERCENT_DENOMINATOR_FLOOR = 1e-9


class ModelEvaluationError(ValueError):
    """Raised when an evaluation cannot be performed honestly."""


def _finite_arrays(y_true: Sequence[float], y_pred: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    actual = np.asarray(list(y_true), dtype="float64").reshape(-1)
    predicted = np.asarray(list(y_pred), dtype="float64").reshape(-1)
    if actual.size != predicted.size:
        raise ModelEvaluationError(
            f"cannot score {actual.size} observation(s) against {predicted.size} prediction(s)"
        )
    if actual.size == 0:
        raise ModelEvaluationError("cannot score zero rows; an empty evaluation is not a score")
    return actual, predicted


def data_status(is_synthetic: bool, dataset_type: str) -> str:
    """The data-status label a comparison row carries.

    Conservative by construction: anything that is not a positively declared real
    dataset is not reported as measured.
    """
    if is_synthetic or dataset_type == "synthetic":
        return DATA_STATUS_SYNTHETIC_DEMO
    if dataset_type == "real":
        return DATA_STATUS_MEASURED
    return DATA_STATUS_UNKNOWN


def evaluation_label(status: str) -> str:
    """The sentence a reader must see next to a metric from this status."""
    if status == DATA_STATUS_SYNTHETIC_DEMO:
        return SYNTHETIC_EVALUATION_LABEL
    if status == DATA_STATUS_MEASURED:
        return "measured evaluation"
    return "unclassified data; metrics are not attributable to real hydrological performance"


# --------------------------------------------------------------------------- #
# Percentage error (opt-in, guarded, never the default)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PercentError:
    """A guarded percentage error, or an explicit refusal to produce one.

    `value is None` means no number was computed, and `status` says why. That is
    the only honest shape for a metric whose denominator can be zero: it is
    reported as absent rather than as a fabricated one.
    """

    value: float | None
    status: str
    excluded_rows: int
    included_rows: int
    denominator_floor: float
    reason: str = PERCENT_ERROR_UNAVAILABLE_REASON

    @property
    def available(self) -> bool:
        return self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": "mape",
            "value": self.value,
            "status": self.status,
            "excluded_rows": self.excluded_rows,
            "included_rows": self.included_rows,
            "denominator_floor": self.denominator_floor,
            "reason": self.reason,
        }


def mean_absolute_percentage_error(
    y_true: Sequence[float],
    y_pred: Sequence[float],
    *,
    enabled: bool = False,
    denominator_floor: float = PERCENT_DENOMINATOR_FLOOR,
) -> PercentError:
    """Percentage error, computed only when it was explicitly asked for.

    With `enabled=False` (the default for every configuration in this project) the
    result is a refusal carrying `PERCENT_ERROR_UNAVAILABLE_REASON`, not a number.
    With `enabled=True` the rows whose |actual| is at or below the floor are
    excluded and **counted**, so the reader can judge the result rather than
    inherit it.
    """
    if not enabled:
        return PercentError(
            value=None,
            status="not_reported",
            excluded_rows=0,
            included_rows=0,
            denominator_floor=denominator_floor,
        )
    actual, predicted = _finite_arrays(y_true, y_pred)
    usable = np.abs(actual) > denominator_floor
    included = int(np.count_nonzero(usable))
    if included == 0:
        return PercentError(
            value=None,
            status="no_rows_with_a_defined_denominator",
            excluded_rows=int(actual.size),
            included_rows=0,
            denominator_floor=denominator_floor,
        )
    value = float(np.mean(np.abs((actual[usable] - predicted[usable]) / actual[usable])) * 100.0)
    return PercentError(
        value=value,
        status="computed",
        excluded_rows=int(actual.size) - included,
        included_rows=included,
        denominator_floor=denominator_floor,
    )


# --------------------------------------------------------------------------- #
# One evaluation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EvaluationOutcome:
    """One model, one target, one horizon, one split.

    Either `metrics` is populated and `status` is `evaluated`, or `metrics` is
    `None` and `reason` says why. There is no third shape, and in particular no
    shape where a missing metric is present as `0.0`.
    """

    model_id: str
    model_family: str
    target: str
    target_units: str | None
    horizon: str | None
    split: str
    status: str = EVALUATION_DONE
    metrics: Mapping[str, float] | None = None
    n_samples: int = 0
    reason: str | None = None
    data_status: str = DATA_STATUS_UNKNOWN
    percent_error: PercentError | None = None
    #: Explicitly `False`, forever. Training completed; that is not evidence of
    #: operational fitness, and the field is here so the absence of that evidence
    #: is visible rather than unmentioned.
    production_ready_claimed: bool = False
    synthetic_demo: bool = True

    def __post_init__(self) -> None:
        if self.status not in EVALUATION_STATUSES:
            raise ModelEvaluationError(
                f"unknown evaluation status {self.status!r}; known statuses are {list(EVALUATION_STATUSES)}"
            )
        if self.status == EVALUATION_DONE:
            if self.metrics is None:
                raise ModelEvaluationError(
                    f"status {EVALUATION_DONE!r} requires metrics; refusing to report an "
                    "evaluation that has none"
                )
        elif self.metrics is not None:
            raise ModelEvaluationError(
                f"status {self.status!r} must carry metrics=None; a metric beside an "
                "unevaluated status is exactly the conflation this class exists to prevent"
            )

    @property
    def evaluated(self) -> bool:
        return self.status == EVALUATION_DONE

    @property
    def label(self) -> str:
        """The sentence that must accompany this outcome's metric."""
        return evaluation_label(self.data_status)

    def metric(self, name: str) -> float | None:
        if self.metrics is None:
            return None
        value = self.metrics.get(name)
        return None if value is None else float(value)

    def improvement_over(self, baseline: "EvaluationOutcome", name: str) -> float | None:
        """Signed improvement against a baseline, or `None` if it cannot be said.

        Positive means this model has the better value *for a metric where lower
        is better*; for the two-sided `bias` it is reported by the caller as the
        raw difference, because "closer to zero" is not the same statement as
        "lower". No interpretation is attached, because whether a difference on
        this synthetic/demo dataset means anything is not a question this module
        can answer.
        """
        mine = self.metric(name)
        theirs = baseline.metric(name)
        if mine is None or theirs is None:
            return None
        if name in TWO_SIDED_METRICS:
            return mine - theirs
        return theirs - mine

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model_id": self.model_id,
            "model_family": self.model_family,
            "target": self.target,
            "target_units": self.target_units,
            "horizon": self.horizon,
            "split": self.split,
            "status": self.status,
            "reason": self.reason,
            "n_samples": self.n_samples,
            "metrics": dict(self.metrics) if self.metrics is not None else None,
            "data_status": self.data_status,
            "evaluation_label": self.label,
            "percent_error": self.percent_error.to_dict() if self.percent_error else None,
            "synthetic_demo": self.synthetic_demo,
            "production_ready_claimed": self.production_ready_claimed,
        }
        return payload


def evaluate_predictions(
    *,
    model_id: str,
    model_family: str,
    target: str,
    target_units: str | None,
    horizon: str | None,
    split: str,
    y_true: Sequence[float],
    y_pred: Sequence[float],
    is_synthetic: bool,
    dataset_type: str = "unknown",
    report: Sequence[str] = DEFAULT_METRICS,
    percent_error_enabled: bool = False,
) -> EvaluationOutcome:
    """Score one prediction set, or record why it could not be scored.

    Every metric comes from `evaluation.compute_metrics`. The only filtering is on
    *which* of its metrics get reported, so that the reported set is the
    configured one and nothing else.
    """
    status = data_status(is_synthetic, dataset_type)

    def unscoreable(reason: str) -> EvaluationOutcome:
        return EvaluationOutcome(
            model_id=model_id,
            model_family=model_family,
            target=target,
            target_units=target_units,
            horizon=horizon,
            split=split,
            status=EVALUATION_INSUFFICIENT_ROWS,
            reason=reason,
            data_status=status,
            synthetic_demo=status == DATA_STATUS_SYNTHETIC_DEMO,
        )

    try:
        actual, predicted = _finite_arrays(y_true, y_pred)
    except ModelEvaluationError as exc:
        return unscoreable(str(exc))
    try:
        computed = compute_metrics(actual, predicted)
    except EvaluationError as exc:
        # The populations `compute_metrics` refuses are the same class of problem as
        # the ones `_finite_arrays` refuses: nothing to score. Letting that exception
        # escape would mean the same condition was sometimes recorded and sometimes
        # raised, in a different module's exception type, and a caller catching only
        # `ModelEvaluationError` would be surprised by it.
        return unscoreable(str(exc))
    available = computed.as_dict()
    unknown = [name for name in report if name not in available]
    if unknown:
        raise ModelEvaluationError(
            f"cannot report metric(s) {unknown}; evaluation computes {sorted(available)}. "
            "Add the metric to REPORTABLE_METRICS rather than reporting a number that "
            "was not computed."
        )
    return EvaluationOutcome(
        model_id=model_id,
        model_family=model_family,
        target=target,
        target_units=target_units,
        horizon=horizon,
        split=split,
        status=EVALUATION_DONE,
        metrics={name: available[name] for name in report},
        n_samples=int(actual.size),
        data_status=status,
        percent_error=mean_absolute_percentage_error(
            actual, predicted, enabled=percent_error_enabled
        ),
        synthetic_demo=status == DATA_STATUS_SYNTHETIC_DEMO,
    )


def unevaluated_outcome(
    *,
    model_id: str,
    model_family: str,
    target: str,
    target_units: str | None,
    horizon: str | None,
    split: str,
    status: str,
    reason: str,
    is_synthetic: bool,
    dataset_type: str = "unknown",
) -> EvaluationOutcome:
    """Build an outcome that states a failure instead of a number."""
    return EvaluationOutcome(
        model_id=model_id,
        model_family=model_family,
        target=target,
        target_units=target_units,
        horizon=horizon,
        split=split,
        status=status,
        reason=reason,
        data_status=data_status(is_synthetic, dataset_type),
        synthetic_demo=is_synthetic or dataset_type == "synthetic",
    )


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ComparisonRow:
    """One line of the model comparison table.

    `training_status` and `evaluation_status` are on the row rather than in a
    separate legend, because a table whose meaning depends on a legend elsewhere
    is a table that gets misread.
    """

    model_id: str
    model_family: str
    target: str
    horizon: str | None
    split: str
    training_status: str
    evaluation_status: str
    data_status: str
    synthetic_demo: bool
    n_samples: int = 0
    mae: float | None = None
    rmse: float | None = None
    r2: float | None = None
    bias: float | None = None
    #: (metric -> improvement over the persistence baseline). `None` when no
    #: baseline exists for this split, which is a different statement from "zero
    #: improvement".
    baseline_delta: Mapping[str, float | None] | None = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_family": self.model_family,
            "target": self.target,
            "horizon": self.horizon,
            "split": self.split,
            "training_status": self.training_status,
            "evaluation_status": self.evaluation_status,
            "data_status": self.data_status,
            "synthetic_demo": self.synthetic_demo,
            "n_samples": self.n_samples,
            "mae": self.mae,
            "rmse": self.rmse,
            "r2": self.r2,
            "bias": self.bias,
            "baseline_delta": (
                dict(self.baseline_delta) if self.baseline_delta is not None else None
            ),
            "notes": list(self.notes),
        }


#: The rendered table's column headers, in order, in the spelling the contract uses
#: for them. `MAE`/`RMSE`/`R2` are display names; the wire keys below are the
#: lowercase metric names.
#:
#: An earlier version of this constant omitted `model_family` and `synthetic_demo`,
#: which is harmless while nothing consumes it and not harmless the moment a renderer
#: does: the two columns that say *which model* and *what data* are exactly the ones a
#: like-for-like, honestly-labelled table cannot do without.
COMPARISON_COLUMNS: tuple[str, ...] = (
    "model_id",
    "model_family",
    "target",
    "horizon",
    "split",
    "training_status",
    "evaluation_status",
    "data_status",
    "synthetic_demo",
    "n_samples",
    "MAE",
    "RMSE",
    "R2",
    "bias",
)

#: The keys `ComparisonRow.to_dict` actually emits, in the same order. Kept beside
#: `COMPARISON_COLUMNS` so that a declaration can never name a column the serialiser
#: does not write, or omit one it does.
COMPARISON_FIELDS: tuple[str, ...] = (
    "model_id",
    "model_family",
    "target",
    "horizon",
    "split",
    "training_status",
    "evaluation_status",
    "data_status",
    "synthetic_demo",
    "n_samples",
    "mae",
    "rmse",
    "r2",
    "bias",
    "baseline_delta",
    "notes",
)


@dataclass(frozen=True)
class ComparisonTable:
    """Every model, split by split, with the persistence baseline on record.

    The baseline is stored as its own outcome rather than being subtracted away,
    so "the model got RMSE 0.42" can always be read next to "persistence got
    1.13". A comparison that reports only the difference makes the reader trust a
    number whose provenance they cannot see.
    """

    rows: tuple[ComparisonRow, ...] = ()
    baseline_model_id: str = "naive"
    target: str = ""
    horizon: str | None = None
    selection_metric: str = "rmse"
    selection_split: str = "validation"
    #: The model with the best `selection_metric` on `selection_split`, when one
    #: exists. Deliberately descriptive: `None` means nothing could be compared,
    #: not that the choice was contested.
    selected_model_id: str | None = None
    data_status: str = DATA_STATUS_UNKNOWN
    disclaimer: str | None = None
    #: Run-level notes that qualify every row. Held here rather than on
    #: `ComparisonRow` because they are properties of the comparison — the rows
    #: excluded for want of a baseline prediction, the imputation applied, the
    #: features dropped — and repeating them on each row would make the table
    #: unreadable while restating them per run would hide them.
    notes: tuple[str, ...] = ()

    def rows_for(self, split: str) -> tuple[ComparisonRow, ...]:
        return tuple(row for row in self.rows if row.split == split)

    def model_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for row in self.rows:
            if row.model_id not in seen:
                seen.append(row.model_id)
        return tuple(seen)

    def evaluated_model_ids(self) -> tuple[str, ...]:
        return tuple(
            row.model_id for row in self.rows if row.evaluation_status == EVALUATION_DONE
        )

    def unevaluated(self) -> tuple[ComparisonRow, ...]:
        return tuple(row for row in self.rows if row.evaluation_status != EVALUATION_DONE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "horizon": self.horizon,
            "baseline_model_id": self.baseline_model_id,
            "selection_metric": self.selection_metric,
            "selection_split": self.selection_split,
            "selected_model_id": self.selected_model_id,
            "data_status": self.data_status,
            "disclaimer": self.disclaimer,
            "notes": list(self.notes),
            "rows": [row.to_dict() for row in self.rows],
        }

    def describe(self) -> str:
        """Fixed-width table. `n/a` means unavailable, never zero.

        The model column shows the family, not the identifier. A `model_id` embeds
        the target column, the horizon and the seed, so it is forty-odd characters
        wide and would push every metric column off the screen. The family is what
        a reader compares across rows, and the full identifier stays in
        `ComparisonRow.model_id` / `to_dict()` for anything machine-read.
        """
        header = (
            f"{'model':<18}{'target':<26}{'hz':<7}{'split':<12}"
            f"{'MAE':>12}{'RMSE':>12}{'R2':>9}{'bias':>12}{'d vs base':>12}  status"
        )
        lines = [
            f"Model comparison - baseline: {self.baseline_model_id} "
            f"(selection metric {self.selection_metric} on {self.selection_split})",
            f"  data status : {self.data_status}",
        ]
        if self.disclaimer:
            lines.append(f"  disclaimer  : {self.disclaimer}")
        if self.notes:
            lines.append("")
            lines.append("  notes that qualify every figure below:")
            for note in self.notes:
                lines.append(f"    - {note}")
        lines.append("")
        lines.append(header)
        lines.append("-" * len(header))
        for row in self.rows:
            delta = None
            if row.baseline_delta:
                delta = row.baseline_delta.get(self.selection_metric)
            lines.append(
                f"{row.model_family:<18}{row.target:<26}{(row.horizon or '-'):<7}{row.split:<12}"
                f"{_cell(row.mae):>12}{_cell(row.rmse):>12}{_cell(row.r2):>9}"
                f"{_cell(row.bias):>12}{_cell(delta):>12}"
                f"  {row.training_status}/{row.evaluation_status}"
            )
        if self.selected_model_id:
            lines.append("")
            lines.append(
                f"  lowest {self.selection_metric} on {self.selection_split}: "
                f"{self.selected_model_id}"
            )
            lines.append(
                "  descriptive only; every figure above is "
                + (self.disclaimer or "measured on the available data")
            )
        return "\n".join(lines)


def _cell(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4g}"


def _row_notes(
    outcome: EvaluationOutcome,
    training: Sequence[str] | str | None,
) -> tuple[str, ...]:
    """The notes for one comparison row: what the run said, then why it scored nothing.

    A row whose `evaluation_status` is not `evaluated` has no numbers, and the
    reason it has no numbers is the whole content of that row. An earlier version
    took the notes only from `training_notes`, so a model that fitted perfectly well
    and then had too few evaluable rows reported `insufficient_rows` with no
    explanation at all — a status with no reason is a shrug in a table.

    `training` is accepted as a bare string as well as a sequence of them. Callers
    hold a single reason per model, so the string is the natural thing to have, and
    iterating it as a sequence of strings silently produced one note *per character* —
    a table row whose explanation was a tuple of single letters, which is both
    unreadable and useless to anything consuming the JSON. Normalising here means the
    mistake cannot be made quietly at the call site.
    """
    if isinstance(training, str):
        supplied: Sequence[str] = (training,)
    else:
        supplied = training or ()
    notes = [note for note in supplied if note and note.strip()]
    if not outcome.evaluated and outcome.reason:
        if outcome.reason not in notes:
            notes.append(outcome.reason)
    return tuple(notes)


def build_comparison(
    outcomes: Iterable[EvaluationOutcome],
    training_statuses: Mapping[str, str],
    training_notes: Mapping[str, tuple[str, ...] | str] | None = None,
    *,
    baseline_model_id: str = "naive",
    selection_metric: str = "rmse",
    selection_split: str = "validation",
    disclaimer: str | None = None,
    context_notes: Sequence[str] | None = None,
) -> ComparisonTable:
    """Turn evaluation outcomes into the comparison table.

    `training_statuses` is a separate input on purpose: a model can fail to train
    and still need a row, and a model that trained can still fail to evaluate. The
    two statuses are independent facts and the table keeps them apart.

    `context_notes` carries the facts that qualify every figure — rows excluded for
    want of a baseline prediction, imputation applied, features dropped. They are
    not attached to any one row because they apply to all of them, and a reader who
    looked only at the row would otherwise be reading an unqualified number.
    """
    collected = list(outcomes)
    by_model_split: dict[tuple[str, str], EvaluationOutcome] = {}
    for outcome in collected:
        by_model_split[(outcome.model_id, outcome.split)] = outcome

    baselines = {
        split: by_model_split.get((baseline_model_id, split))
        for split in {outcome.split for outcome in collected}
    }

    rows: list[ComparisonRow] = []
    for (model_id, split), outcome in sorted(by_model_split.items()):
        baseline = baselines.get(split)
        delta: dict[str, float | None] | None = None
        if baseline is not None and baseline.evaluated and outcome.evaluated:
            delta = {
                name: outcome.improvement_over(baseline, name)
                for name in REPORTABLE_METRICS
            }
        rows.append(
            ComparisonRow(
                model_id=model_id,
                model_family=outcome.model_family,
                target=outcome.target,
                horizon=outcome.horizon,
                split=split,
                training_status=training_statuses.get(model_id, "unknown"),
                evaluation_status=outcome.status,
                data_status=outcome.data_status,
                synthetic_demo=outcome.synthetic_demo,
                n_samples=outcome.n_samples,
                mae=outcome.metric("mae"),
                rmse=outcome.metric("rmse"),
                r2=outcome.metric("r2"),
                bias=outcome.metric("bias"),
                baseline_delta=delta,
                notes=_row_notes(outcome, (training_notes or {}).get(model_id)),
            )
        )

    selected = _select(
        rows,
        selection_metric=selection_metric,
        selection_split=selection_split,
        exclude=baseline_model_id,
    )
    status = collected[0].data_status if collected else DATA_STATUS_UNKNOWN
    return ComparisonTable(
        rows=tuple(rows),
        baseline_model_id=baseline_model_id,
        target=collected[0].target if collected else "",
        horizon=collected[0].horizon if collected else None,
        selection_metric=selection_metric,
        selection_split=selection_split,
        selected_model_id=selected,
        data_status=status,
        disclaimer=disclaimer,
        notes=tuple(context_notes or ()),
    )


def _select(rows: Sequence[ComparisonRow], *, selection_metric: str, selection_split: str, exclude: str) -> str | None:
    """The best `selection_metric` on `selection_split`, descriptively.

    Excludes the baseline from being "selected": the persistence baseline is a
    yardstick, and a run that selected it has learned that nothing beat "assume no
    change", which is a finding worth stating rather than a winner to announce.

    "Best" is resolved through `metric_direction` rather than by sorting ascending
    unconditionally. The previous version always took the lowest value, which was
    right for `rmse` and wrong for `r2` and `nse` - ranking those ascending
    selects the *worst* candidate that produced a number, and reports it as the
    winner. Ties break on `model_id` so two runs that score identically still
    produce one deterministic answer.
    """
    direction = metric_direction(selection_metric)
    candidates = [
        row
        for row in rows
        if row.split == selection_split
        and row.evaluation_status == EVALUATION_DONE
        and row.model_id != exclude
    ]
    scored = [(row, getattr(row, selection_metric)) for row in candidates]
    usable = [(row, value) for row, value in scored if value is not None]
    if not usable:
        return None
    if direction == "lower":
        usable.sort(key=lambda item: (item[1], item[0].model_id))
    else:
        usable.sort(key=lambda item: (-item[1], item[0].model_id))
    return usable[0][0].model_id


__all__ = [
    "COMPARISON_COLUMNS",
    "COMPARISON_FIELDS",
    "HIGHER_IS_BETTER",
    "LOWER_IS_BETTER",
    "METRIC_DIRECTIONS",
    "PERCENT_DENOMINATOR_FLOOR",
    "PERCENT_ERROR_UNAVAILABLE_REASON",
    "REPORTABLE_METRICS",
    "SYNTHETIC_EVALUATION_LABEL",
    "TWO_SIDED_METRICS",
    "ComparisonRow",
    "ComparisonTable",
    "EvaluationOutcome",
    "ModelEvaluationError",
    "PercentError",
    "build_comparison",
    "data_status",
    "evaluate_predictions",
    "evaluation_label",
    "mean_absolute_percentage_error",
    "unevaluated_outcome",
]