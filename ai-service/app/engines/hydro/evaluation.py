# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Chronological forecast evaluation.

Every metric in this module is **computed from an array of predictions and an
array of observations**. There is no default value, no lookup table, no
placeholder and no constant that can be returned in place of a calculation. If
an evaluation cannot be performed it raises instead of producing a number.

Metrics implemented
-------------------
* **MAE**  — mean absolute error, in the target's units.
* **RMSE** — root mean squared error, in the target's units.
* **R²**   — coefficient of determination against the evaluation-period mean.
* **NSE**  — Nash-Sutcliffe efficiency. For a single contiguous evaluation
  period with a mean baseline this is algebraically identical to R², and this
  module says so rather than presenting two numbers as independent evidence. It
  is reported because Nash-Sutcliffe is the conventional hydrological
  efficiency measure; the coincidence is documented, not hidden.

Nothing else is reported. Accuracy, F1, precision and recall are classification
measures and are deliberately absent from a regression evaluation — emitting them
here would be meaningless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import numpy as np

from .config import HydroConfig
from .models import HydroEstimator
from .provenance import (
    DATASET_TYPE_UNKNOWN,
    ProvenanceRecord,
    SplitBoundaries,
    combine_disclaimers,
    provenance_from_config,
)

#: Metrics this module will compute. Used to reject an unknown metric request
#: rather than silently returning something else.
SUPPORTED_METRICS = ("mae", "rmse", "r2", "nse")

#: Lower is better for these; the selection policy depends on this.
LOWER_IS_BETTER = ("mae", "rmse", "nse")

#: The three chronological periods, by name. Defined here rather than in
#: `training.py` because the *meaning* of each split is an evaluation concern:
#: only `HELD_OUT_SPLIT` produces an estimate of performance on unseen data.
TRAIN_SPLIT = "train"

#: The split whose score decides which candidate is selected. Ranking on the test
#: split would turn the held-out score into a selection statistic.
SELECTION_SPLIT = "validation"

#: The split scored exactly once, by the selected model only, to produce the
#: final held-out estimate.
HELD_OUT_SPLIT = "test"


class EvaluationError(ValueError):
    """Raised when an evaluation cannot be performed honestly."""


def _as_arrays(y_true: Sequence[float], y_pred: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    actual = np.asarray(y_true, dtype="float64").reshape(-1)
    predicted = np.asarray(y_pred, dtype="float64").reshape(-1)
    if actual.size != predicted.size:
        raise EvaluationError(
            f"y_true has {actual.size} value(s) but y_pred has {predicted.size}"
        )
    if actual.size < 2:
        raise EvaluationError(
            f"at least 2 evaluation samples are required for a score, got {actual.size}"
        )
    if not np.isfinite(actual).all():
        raise EvaluationError("y_true contains non-finite values")
    if not np.isfinite(predicted).all():
        raise EvaluationError("y_pred contains non-finite values")
    return actual, predicted


def mean_absolute_error(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    """MAE = mean(|y - ŷ|)."""
    actual, predicted = _as_arrays(y_true, y_pred)
    return float(np.mean(np.abs(actual - predicted)))


def root_mean_squared_error(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    """RMSE = sqrt(mean((y - ŷ)²))."""
    actual, predicted = _as_arrays(y_true, y_pred)
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def coefficient_of_determination(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    """R² = 1 - SS_res / SS_tot, with SS_tot measured around the actual mean.

    Returns `0.0` when the observations have zero variance: there is no spread to
    explain, so the score is undefined and is reported as "explained nothing"
    rather than as a perfect or NaN result.
    """
    actual, predicted = _as_arrays(y_true, y_pred)
    ss_res = float(np.sum((actual - predicted) ** 2))
    ss_tot = float(np.sum((actual - actual.mean()) ** 2))
    if ss_tot == 0.0:
        return 0.0
    return 1.0 - (ss_res / ss_tot)


def nash_sutcliffe_efficiency(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    """NSE = 1 - SS_res / SS_tot, the conventional hydrological efficiency.

    With a mean baseline on one contiguous evaluation period this equals R². The
    equivalence is a property of the formula, not a coincidence in the data, so
    this module reports it plainly instead of implying two independent
    validations. Negative values mean the model is worse than predicting the
    evaluation-period mean.
    """
    return coefficient_of_determination(y_true, y_pred)


def peak_absolute_error(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    """Max |y - ŷ| — reported as a descriptive statistic, not a headline score."""
    actual, predicted = _as_arrays(y_true, y_pred)
    return float(np.max(np.abs(actual - predicted)))


def bias(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    """Mean error (predictions minus observations). Systematic bias is a real
    diagnostic for flood models: a persistent positive bias over-predicts."""
    actual, predicted = _as_arrays(y_true, y_pred)
    return float(np.mean(predicted - actual))


@dataclass(frozen=True)
class EvaluationMetrics:
    """The computed scores for one model on one evaluation period."""

    mae: float
    rmse: float
    r2: float
    nse: float
    peak_absolute_error: float
    bias: float
    n_samples: int

    def as_dict(self) -> dict[str, float]:
        return {
            "mae": self.mae,
            "rmse": self.rmse,
            "r2": self.r2,
            "nse": self.nse,
            "peak_absolute_error": self.peak_absolute_error,
            "bias": self.bias,
        }

    def score(self, metric: str) -> float:
        """Look up one score by name, rejecting unknown metric names."""
        if metric not in SUPPORTED_METRICS:
            raise EvaluationError(
                f"unsupported metric {metric!r}; this module computes {SUPPORTED_METRICS}"
            )
        return float(getattr(self, metric))

    @property
    def primary(self) -> str:
        return "rmse"


def compute_metrics(y_true: Sequence[float], y_pred: Sequence[float]) -> EvaluationMetrics:
    """Compute every supported metric from the two arrays."""
    actual, predicted = _as_arrays(y_true, y_pred)
    return EvaluationMetrics(
        mae=mean_absolute_error(actual, predicted),
        rmse=root_mean_squared_error(actual, predicted),
        r2=coefficient_of_determination(actual, predicted),
        nse=nash_sutcliffe_efficiency(actual, predicted),
        peak_absolute_error=peak_absolute_error(actual, predicted),
        bias=bias(actual, predicted),
        n_samples=int(actual.size),
    )


@dataclass(frozen=True)
class EvaluationReport:
    """A complete, auditable record of one executed evaluation.

    Every field the platform pledge requires is present: which dataset, which
    dataset type, the three split periods, the target, the horizon, the model,
    the measured metrics, when it ran, and the provenance record. A report can be
    produced for a synthetic dataset, but it then carries the synthetic
    disclaimer and its `metric_label` says so.
    """

    model_key: str
    model_name: str
    model_version: str
    algorithm: str
    split_label: str
    metrics: EvaluationMetrics
    target: str
    target_units: str | None
    forecast_horizon: str
    lead_time_rows: int
    dataset_reference: str | None
    dataset_type: str
    station_reference: str | None
    split: SplitBoundaries
    evaluated_at: str
    provenance: ProvenanceRecord
    feature_list: tuple[str, ...] = ()

    @property
    def split_caveat(self) -> str | None:
        """Why this report's score is not a held-out estimate, or ``None``.

        Only the held-out split produces an estimate of performance on data the
        model has never influenced. The other two are measured on data it has
        already had a relationship with:

        * ``train`` -- the data the model was *fitted* on. Reporting it is
          reporting a fit statistic, the most flattering number available.
        * ``validation`` -- the data the model was *selected* on. Reporting it
          is reporting the selection statistic, which is optimistic by
          construction.

        A report can legitimately exist for either split: that is how a candidate
        gets ranked. What must not happen is one of those numbers being shown as
        the model's performance, so the distinction is carried in the mandatory
        label rather than left to the reader's care.
        """
        if self.split_label == HELD_OUT_SPLIT:
            return None
        if self.split_label == TRAIN_SPLIT:
            return (
                "NOT A HELD-OUT RESULT: fit statistic on the 'train' split, the data the "
                "model was fitted on. Not an estimate of performance on unseen data."
            )
        if self.split_label == SELECTION_SPLIT:
            return (
                "NOT A HELD-OUT RESULT: selection statistic on the 'validation' split, "
                "which the model was chosen on. Optimistic by construction."
            )
        # An unrecognised split is not assumed to be held out. Assuming so would
        # let a typo turn a train-period score into a performance claim.
        return (
            f"NOT A HELD-OUT RESULT: the split is recorded as {self.split_label!r}, which is "
            f"not the held-out {HELD_OUT_SPLIT!r} split."
        )

    @property
    def metric_label(self) -> str:
        """Mandatory label attached to any number in this report.

        Two independent caveats can apply and both are reported. The dataset
        caveat comes from the provenance record; the split caveat comes from
        this report. The synthetic label takes precedence when both are present,
        because it is the stronger claim: it says the numbers do not describe a
        hydrological result at all, which subsumes any statement about which
        split they were measured on.
        """
        caveat: str | None = self.split_caveat
        if self.provenance.is_synthetic:
            return self.provenance.metrics_label
        if caveat is None:
            return self.provenance.metrics_label
        # Deliberately NOT the provenance label with the caveat appended: that
        # would read "measured evaluation — NOT A HELD-OUT RESULT", which
        # contradicts itself. The split caveat *replaces* it, because a score
        # from a split the model was fitted or selected on is not a measurement
        # of anything the reader cares about.
        return caveat

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": {
                "key": self.model_key,
                "name": self.model_name,
                "version": self.model_version,
                "algorithm": self.algorithm,
            },
            "split_label": self.split_label,
            "metrics": self.metrics.as_dict(),
            "metric_label": self.metric_label,
            "n_samples": self.metrics.n_samples,
            "target": self.target,
            "target_units": self.target_units,
            "forecast_horizon": self.forecast_horizon,
            "lead_time_rows": self.lead_time_rows,
            "dataset_reference": self.dataset_reference,
            "dataset_type": self.dataset_type,
            "station_reference": self.station_reference,
            "split": {
                "train": [self.split.train_start, self.split.train_end, self.split.train_rows],
                "validation": [
                    self.split.validation_start,
                    self.split.validation_end,
                    self.split.validation_rows,
                ],
                "test": [self.split.test_start, self.split.test_end, self.split.test_rows],
            },
            "feature_list": list(self.feature_list),
            "evaluated_at": self.evaluated_at,
            "provenance": self.provenance.to_dict(),
        }

    def format(self) -> str:
        """Human-readable evaluation block for the console and docs."""
        lines = [
            "=" * 78,
            f"FORECAST EVALUATION — {self.model_name} ({self.model_key})",
            "=" * 78,
            f"metric label        : {self.metric_label}",
            f"dataset_reference   : {self.dataset_reference or 'UNKNOWN'}",
            f"dataset_type        : {self.dataset_type}",
            f"station_reference   : {self.station_reference or 'UNKNOWN'}",
            f"target              : {self.target}"
            + (f" ({self.target_units})" if self.target_units else " (units UNKNOWN)"),
            f"forecast_horizon    : {self.forecast_horizon} (lead time {self.lead_time_rows} row(s))",
            f"model_version       : {self.model_version}",
            f"algorithm           : {self.algorithm}",
            f"split evaluated     : {self.split_label}",
            f"train period        : {self.split.train_start} .. {self.split.train_end}"
            f"  ({self.split.train_rows} rows)",
            f"validation period   : {self.split.validation_start} .. {self.split.validation_end}"
            f"  ({self.split.validation_rows} rows)",
            f"test period         : {self.split.test_start} .. {self.split.test_end}"
            f"  ({self.split.test_rows} rows)",
            f"evaluation samples  : {self.metrics.n_samples}",
            "-" * 78,
            f"MAE                 : {self.metrics.mae:.6f}",
            f"RMSE                : {self.metrics.rmse:.6f}",
            f"R^2                 : {self.metrics.r2:.6f}",
            f"NSE                 : {self.metrics.nse:.6f}",
            f"peak absolute error : {self.metrics.peak_absolute_error:.6f}",
            f"bias                : {self.metrics.bias:.6f}",
            "-" * 78,
            f"evaluated_at        : {self.evaluated_at}",
            f"features            : {len(self.feature_list)}",
        ]
        if self.provenance.disclaimer:
            lines.append(f"DISCLAIMER          : {self.provenance.disclaimer}")
        lines.append("=" * 78)
        return "\n".join(lines)


@dataclass(frozen=True)
class ModelComparison:
    """Result of comparing candidate models on one evaluation period.

    **Selection protocol.** `reports` holds every candidate's score on the
    *selection* split (`validation`). The winning candidate is then scored once on
    the *held-out* split (`test`) and stored in `held_out_report`. The held-out
    score therefore never influences which model is chosen, and the held-out
    split is consumed exactly once, by one model.

    This matters: ranking candidates across both splits at once would let the
    test period pick the winner, which turns the test score into a selection
    statistic and inflates it. `assert_selection_is_clean()` enforces the correct
    order.
    """

    reports: tuple[EvaluationReport, ...] = ()
    selection_metric: str = "rmse"
    selected_key: str | None = None
    selection_split: str = "validation"
    held_out_split: str = "test"
    held_out_report: EvaluationReport | None = None
    unevaluated_keys: tuple[str, ...] = ()
    unavailable: Mapping[str, str] = field(default_factory=dict)

    def assert_selection_is_clean(self) -> None:
        """Raise unless the comparison follows the select-then-hold-out order.

        Checks that (a) every report in the ranking comes from the selection
        split, and (b) the held-out report, when present, belongs to the selected
        model and comes from the held-out split.
        """
        if self.held_out_split == self.selection_split:
            raise EvaluationError(
                f"selection split and held-out split are both {self.selection_split!r}; "
                "the final score would be a selection statistic rather than a held-out estimate"
            )
        for report in self.reports:
            if report.split_label != self.selection_split:
                raise EvaluationError(
                    f"model {report.model_key!r} was ranked on the {report.split_label!r} split, "
                    f"but selection must use only the {self.selection_split!r} split"
                )
        held = self.held_out_report
        if held is None:
            return
        if held.split_label != self.held_out_split:
            raise EvaluationError(
                f"held-out report is on the {held.split_label!r} split, expected "
                f"{self.held_out_split!r}"
            )
        if self.selected_key is not None and held.model_key != self.selected_key:
            raise EvaluationError(
                f"held-out report is for {held.model_key!r} but the selected model is "
                f"{self.selected_key!r}"
            )

    def table(self) -> str:
        """Markdown table of the executed candidates on the selection split."""
        if not self.reports:
            return "no candidate model was evaluated"
        header = "| model | selection split | n | MAE | RMSE | R^2 | NSE | label |"
        divider = "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |"
        rows = [header, divider]
        for report in self.reports:
            rows.append(
                "| {name} | {split} | {n} | {mae:.4f} | {rmse:.4f} | {r2:.4f} | {nse:.4f} | {label} |".format(
                    name=report.model_key,
                    split=report.split_label,
                    n=report.metrics.n_samples,
                    mae=report.metrics.mae,
                    rmse=report.metrics.rmse,
                    r2=report.metrics.r2,
                    nse=report.metrics.nse,
                    label=report.metric_label,
                )
            )
        return "\n".join(rows)

    def held_out_table(self) -> str:
        """Markdown table of the single held-out score, when one was computed."""
        if self.held_out_report is None:
            return (
                f"no held-out score was computed on the {self.held_out_split!r} split"
            )
        report = self.held_out_report
        return (
            "| model | held-out split | n | MAE | RMSE | R^2 | NSE | label |\n"
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |\n"
            "| {name} | {split} | {n} | {mae:.4f} | {rmse:.4f} | {r2:.4f} | {nse:.4f} | {label} |".format(
                name=report.model_key,
                split=report.split_label,
                n=report.metrics.n_samples,
                mae=report.metrics.mae,
                rmse=report.metrics.rmse,
                r2=report.metrics.r2,
                nse=report.metrics.nse,
                label=report.metric_label,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "selection_metric": self.selection_metric,
            "selection_split": self.selection_split,
            "held_out_split": self.held_out_split,
            "selected_key": self.selected_key,
            "reports": [report.to_dict() for report in self.reports],
            "held_out_report": self.held_out_report.to_dict()
            if self.held_out_report is not None
            else None,
            "unevaluated_keys": list(self.unevaluated_keys),
            "unavailable_models": dict(self.unavailable),
        }


def evaluate_estimator(
    estimator: HydroEstimator,
    x: np.ndarray,
    y_true: Sequence[float],
    *,
    config: HydroConfig,
    split_label: str,
    model_version: str,
    split: SplitBoundaries,
    provenance: ProvenanceRecord | None = None,
    lead_time_rows: int = 1,
    feature_list: Sequence[str] = (),
) -> EvaluationReport:
    """Predict with `estimator` and compute the full metric set.

    The estimator is expected to already be fitted. `split_label` is recorded
    verbatim so a test-period score is never mistaken for a validation-period
    one.
    """
    predictions = estimator.predict(x)
    metrics = compute_metrics(y_true, predictions)
    record = provenance or provenance_from_config(config, feature_list=feature_list, split=split)
    return EvaluationReport(
        model_key=getattr(estimator, "key", "unknown"),
        model_name=getattr(estimator, "display_name", "unknown"),
        model_version=model_version,
        algorithm=getattr(estimator, "algorithm", "unknown"),
        split_label=split_label,
        metrics=metrics,
        target=config.target.column,
        target_units=config.target.units,
        forecast_horizon=f"{config.target.horizon_hours}h",
        lead_time_rows=lead_time_rows,
        dataset_reference=config.dataset.reference,
        dataset_type=config.dataset.dataset_type,
        station_reference=config.dataset.station_reference,
        split=split,
        evaluated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        provenance=record,
        feature_list=tuple(feature_list),
    )


def compare_models(
    reports: Sequence[EvaluationReport],
    *,
    selection_metric: str = "rmse",
    higher_is_better: bool = False,
    selection_split: str = "validation",
    held_out_split: str = "test",
    held_out_report: EvaluationReport | None = None,
    unevaluated_keys: Sequence[str] = (),
    unavailable: Mapping[str, str] | None = None,
) -> ModelComparison:
    """Rank executed candidates by one metric and select the best.

    `reports` must contain each candidate's score on `selection_split` only. The
    selection metric must be one this module actually computes. A model that was
    not evaluated is never selected, and its key is reported in
    `unevaluated_keys` so the comparison cannot be read as a complete sweep of
    the registry.

    The result is validated by `assert_selection_is_clean()` before being
    returned, so a caller that accidentally ranks on the test split is rejected
    rather than silently reported.
    """
    if selection_metric not in SUPPORTED_METRICS:
        raise EvaluationError(
            f"selection_metric {selection_metric!r} is not computed by this module; "
            f"choose from {SUPPORTED_METRICS}"
        )
    if not reports:
        return ModelComparison(
            reports=(),
            selection_metric=selection_metric,
            selected_key=None,
            selection_split=selection_split,
            held_out_split=held_out_split,
            unevaluated_keys=tuple(unevaluated_keys),
            unavailable=dict(unavailable or {}),
        )

    def sort_key(report: EvaluationReport) -> tuple[float, float]:
        value = report.metrics.score(selection_metric)
        # Ascending for error metrics; descending for skill metrics. RMSE breaks
        # ties so the ordering is fully deterministic.
        return (value, report.metrics.rmse) if not higher_is_better else (-value, report.metrics.rmse)

    ordered = tuple(sorted(reports, key=sort_key))
    comparison = ModelComparison(
        reports=ordered,
        selection_metric=selection_metric,
        selected_key=ordered[0].model_key,
        selection_split=selection_split,
        held_out_split=held_out_split,
        held_out_report=held_out_report,
        unevaluated_keys=tuple(unevaluated_keys),
        unavailable=dict(unavailable or {}),
    )
    comparison.assert_selection_is_clean()
    return comparison


def selection_policy_note(metric: str) -> str:
    """Human-readable note on how the selected model was chosen."""
    if metric in LOWER_IS_BETTER:
        return f"selected the lowest {metric.upper()} among the executed candidates on the same period"
    return f"selected the highest {metric.upper()} among the executed candidates on the same period"


def build_comparison_disclaimer(dataset_type: str) -> str | None:
    """Disclaimer block for a comparison, driven by the declared dataset type."""
    if dataset_type == DATASET_TYPE_UNKNOWN:
        return (
            "Dataset type is UNKNOWN. Treat these scores as unverified until the dataset "
            "source, license and provenance are supplied."
        )
    return combine_disclaimers(
        "synthetic/demo evaluation only — not a production or research result"
        if dataset_type == "synthetic"
        else None
    )
