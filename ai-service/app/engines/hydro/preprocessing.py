# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Data validation, missing-value handling, chronological splitting and scaling.

Every function here is written for one rule above all others: **no future
observation may influence a past prediction.** Concretely that means

* Rows are ordered by time, never shuffled, and duplicate timestamps are
  reported rather than silently collapsed.
* Splits are contiguous time ranges. There is no random split, and no API
  accepts a seed for splitting.
* The imputer and the scaler are *fitted on the training rows only* and then
  reused verbatim. `TrainFittedImputer` / `StandardScaler` make this explicit by
  refusing to transform before `fit()` and by recording what they were fitted on.
* The target column is never used as a feature by this module. Supervised
  alignment (features at *t* → target at *t+h*) happens in `features.py`, which
  also guarantees the alignment runs forward in time.

Documented steps
----------------
Each transformation returns a `ProcessingStep` so the caller can print exactly
what happened to the data:

1. `validate_columns`    — required columns exist.
2. `parse_timestamps`    — timestamps parse to timezone-naive UTC instants.
3. `sort_chronologically`— rows ordered ascending by timestamp (stable).
4. `report_duplicates`   — duplicate timestamps detected and counted.
5. `apply_missing_policy`— NaN/None resolved per the configured policy.
6. `chronological_split` — contiguous train / validation / test ranges.
7. `StandardScaler.fit`  — mean/scale computed on training rows only.
8. `TrainFittedImputer`  — median/constant computed on training rows only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from .config import HydroConfig, SplitSpec
from .provenance import SplitBoundaries

#: Columns that are never usable as a model feature. The target is excluded by
#: `features.py`, not here, so that autoregressive lag features built *from the
#: target's own past* remain legal.
RESERVED_COLUMNS = frozenset({"__lead_time_rows__", "__split__", "__original_row__"})


class PreprocessError(ValueError):
    """Raised when the input data cannot be used for honest forecasting."""


@dataclass(frozen=True)
class ProcessingStep:
    """One documented preprocessing transformation."""

    name: str
    description: str
    rows_in: int
    rows_out: int
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def rows_dropped(self) -> int:
        return self.rows_in - self.rows_out

    def describe(self) -> str:
        return (
            f"[{self.name}] {self.description} "
            f"({self.rows_in} -> {self.rows_out} rows)"
        )


@dataclass(frozen=True)
class DuplicateReport:
    """Result of duplicate-timestamp detection."""

    duplicate_count: int
    duplicated_timestamps: tuple[str, ...]
    affected_row_count: int

    @property
    def has_duplicates(self) -> bool:
        return self.duplicate_count > 0


# --------------------------------------------------------------------------- #
# 1. Column validation
# --------------------------------------------------------------------------- #


def validate_columns(frame: pd.DataFrame, required: Sequence[str]) -> ProcessingStep:
    """Assert that every required column exists in `frame`.

    Unknown columns are never an error — a dataset may legitimately carry
    metadata the pipeline ignores. What is fatal is a *missing* required column,
    because silently proceeding would mean forecasting a different variable than
    the one declared in the provenance.
    """
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise PreprocessError(
            f"required column(s) missing from dataset: {missing}; "
            f"available columns: {list(frame.columns)}"
        )
    if frame.empty:
        raise PreprocessError("dataset is empty")
    return ProcessingStep(
        name="validate_columns",
        description=f"validated {len(required)} required column(s)",
        rows_in=len(frame),
        rows_out=len(frame),
        detail={"required": list(required), "available": list(frame.columns)},
    )


def reject_non_finite(frame: pd.DataFrame, columns: Sequence[str]) -> ProcessingStep:
    """Reject NaN/±inf in columns that must be finite before modelling.

    Forward-filling is a documented, explicit policy; silently tolerating an
    infinite value is not. This is applied after the missing-value policy has
    run, so anything still non-finite at this point is a genuine data error.
    """
    offenders: dict[str, int] = {}
    for column in columns:
        series = pd.to_numeric(frame[column], errors="coerce")
        bad = int((~np.isfinite(series.to_numpy(dtype="float64", na_value=np.nan))).sum())
        if bad:
            offenders[column] = bad
    if offenders:
        raise PreprocessError(f"non-finite values remain in column(s): {offenders}")
    return ProcessingStep(
        name="reject_non_finite",
        description=f"verified {len(columns)} column(s) contain only finite values",
        rows_in=len(frame),
        rows_out=len(frame),
        detail={"columns": list(columns)},
    )


# --------------------------------------------------------------------------- #
# 2-4. Timestamps, ordering, duplicates
# --------------------------------------------------------------------------- #


def parse_timestamps(frame: pd.DataFrame, column: str) -> tuple[pd.DataFrame, ProcessingStep]:
    """Parse `column` into timezone-naive UTC timestamps, in place on a copy.

    Naive-vs-aware mixing is rejected rather than guessed: a dataset whose
    timestamps silently shift by an offset would corrupt every chronological
    boundary and invalidate the whole evaluation.
    """
    if column not in frame.columns:
        raise PreprocessError(f"timestamp column {column!r} is not present in the dataset")

    raw = frame[column]
    try:
        parsed = pd.to_datetime(raw, errors="coerce", utc=True)
    except Exception as exc:
        # `errors="coerce"` is not a total guarantee across pandas versions:
        # a column whose dtype is not object-like at all (a bare `str` mixed in,
        # or a non-datetime dtype) raises instead of coercing. Either way the
        # answer is the same - the column is unusable - so it is reported the
        # same way, as a PreprocessError naming the column, rather than letting
        # an opaque pandas internal escape to the caller.
        raise PreprocessError(
            f"timestamp column {column!r} could not be parsed as a datetime "
            f"(pandas raised {type(exc).__name__}: {exc}); fix or remove the "
            "unparseable values before training"
        ) from exc
    unparsed = int(parsed.isna().sum())
    if unparsed:
        raise PreprocessError(
            f"{unparsed} row(s) in timestamp column {column!r} could not be parsed as a datetime; "
            "fix or remove them before training"
        )
    out = frame.copy()
    out[column] = parsed.dt.tz_convert(None)
    return out, ProcessingStep(
        name="parse_timestamps",
        description=f"parsed {column!r} as UTC timestamps",
        rows_in=len(frame),
        rows_out=len(out),
        detail={"column": column},
    )


def sort_chronologically(frame: pd.DataFrame, column: str) -> tuple[pd.DataFrame, ProcessingStep]:
    """Stable ascending sort by timestamp. Never shuffles.

    `kind="stable"` keeps the original relative order of equal timestamps, so a
    subsequent duplicate policy operates on a deterministic frame.
    """
    ordered = frame.sort_values(by=column, kind="stable", ascending=True).reset_index(drop=True)
    was_sorted = bool(ordered.equals(frame.reset_index(drop=True)))
    return ordered, ProcessingStep(
        name="sort_chronologically",
        description=(
            "already in chronological order"
            if was_sorted
            else "reordered rows into ascending chronological order"
        ),
        rows_in=len(frame),
        rows_out=len(ordered),
        detail={"column": column, "reordered": not was_sorted},
    )


def report_duplicates(frame: pd.DataFrame, column: str) -> DuplicateReport:
    """Count duplicated timestamps without modifying the frame.

    Detection is separate from removal on purpose: a dataset with duplicate
    timestamps is a data-quality fact the supplier must see, so the engine can
    report it and refuse to train rather than guessing which row is correct.
    """
    duplicated = frame[column][frame[column].duplicated(keep=False)]
    unique_duplicates = duplicated.drop_duplicates()
    return DuplicateReport(
        duplicate_count=int(len(unique_duplicates)),
        duplicated_timestamps=tuple(str(value) for value in unique_duplicates.tolist()),
        affected_row_count=int(len(duplicated)),
    )


def resolve_duplicates(
    frame: pd.DataFrame,
    column: str,
    *,
    keep: str = "last",
) -> tuple[pd.DataFrame, ProcessingStep]:
    """Keep one row per timestamp.

    `keep` must be an explicit choice by the caller. The default is `last`
    because for a gauge series the most recently recorded reading for a
    timestamp is normally the corrected one — but this is a *policy*, not a
    fact, and the step is always reported.
    """
    if keep not in ("first", "last"):
        raise PreprocessError(f"duplicate keep policy must be 'first' or 'last', got {keep!r}")
    before = len(frame)
    out = frame.drop_duplicates(subset=[column], keep=keep).reset_index(drop=True)
    return out, ProcessingStep(
        name="resolve_duplicates",
        description=f"kept the {keep} row for each duplicated timestamp",
        rows_in=before,
        rows_out=len(out),
        detail={"keep": keep, "dropped": before - len(out)},
    )


def infer_sampling_interval(frame: pd.DataFrame, column: str) -> str | None:
    """Infer the modal sampling interval, or `None` when it is not regular.

    Returns an ISO-8601-ish duration string such as `1h`, `30min`, `1D`. When
    the series is irregular the mode is still reported *only* if it covers the
    majority of deltas; otherwise `None` is returned so provenance keeps the
        "unknown" state instead of asserting a cadence the data does not support.
    """
    if len(frame) < 3:
        return None
    deltas = frame[column].diff().dropna()
    if deltas.empty:
        return None
    counts = deltas.value_counts()
    modal = counts.index[0]
    coverage = float(counts.iloc[0]) / float(len(deltas))
    if coverage < 0.9:
        return None
    seconds = int(modal.total_seconds())
    if seconds <= 0:
        return None
    if seconds % 86400 == 0:
        return f"{seconds // 86400}D"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}min"
    return f"{seconds}s"


# --------------------------------------------------------------------------- #
# 5. Missing values
# --------------------------------------------------------------------------- #


def apply_missing_policy(
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    policy: str = "ffill",
    max_fill_gap: int = 3,
    id_columns: Sequence[str] = (),
) -> tuple[pd.DataFrame, ProcessingStep]:
    """Resolve missing values in `columns` under an explicit, named policy.

    * `error` — any remaining NaN is a hard failure. Use it for small,
      hand-curated datasets where every value matters.
    * `drop`  — drop rows that still contain a NaN in a required column.
    * `ffill` — forward-fill, but never across a gap longer than
      `max_fill_gap` rows. Longer gaps are left as NaN so the caller can see
      that a genuine data gap survived; the result is then truncated to
      complete rows. Forward-fill only ever looks *backwards* in time, so it
      cannot leak a future value into a past row.
    """
    if policy not in ("ffill", "drop", "error"):
        raise PreprocessError(f"unknown missing-value policy {policy!r}")
    if max_fill_gap < 0:
        raise PreprocessError("max_fill_gap must be >= 0")

    work = frame.copy()
    before = len(work)
    detail: dict[str, Any] = {"policy": policy, "max_fill_gap": max_fill_gap}

    initial_missing = {
        column: int(pd.to_numeric(work[column], errors="coerce").isna().sum()) for column in columns
    }
    detail["missing_before"] = initial_missing

    if policy == "ffill":
        for column in columns:
            numeric = pd.to_numeric(work[column], errors="coerce")
            if id_columns:
                filled = numeric.groupby([work[c] for c in id_columns]).ffill(limit=max_fill_gap)
            else:
                filled = numeric.ffill(limit=max_fill_gap)
            work[column] = filled
    elif policy == "error":
        remaining = {c: initial_missing[c] for c in columns if initial_missing[c]}
        if remaining:
            raise PreprocessError(f"missing values present under policy 'error': {remaining}")
        detail["missing_after"] = {c: 0 for c in columns}
        return work, ProcessingStep(
            name="apply_missing_policy",
            description="verified no missing values (policy 'error')",
            rows_in=before,
            rows_out=len(work),
            detail=detail,
        )

    detail["missing_after"] = {
        column: int(pd.to_numeric(work[column], errors="coerce").isna().sum()) for column in columns
    }
    complete = work.dropna(subset=list(columns)).reset_index(drop=True)

    return complete, ProcessingStep(
        name="apply_missing_policy",
        description=f"resolved missing values under policy {policy!r}",
        rows_in=before,
        rows_out=len(complete),
        detail=detail,
    )


# --------------------------------------------------------------------------- #
# 6. Chronological split
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ChronologicalSplit:
    """Three contiguous, non-overlapping time ranges plus their boundaries."""

    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame

    def frames(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        return self.train, self.validation, self.test

    def sizes(self) -> dict[str, int]:
        return {
            "train": len(self.train),
            "validation": len(self.validation),
            "test": len(self.test),
        }


def chronological_split(
    frame: pd.DataFrame,
    column: str,
    split: SplitSpec,
    *,
    timestamp_column_is_sorted: bool = True,
) -> tuple[ChronologicalSplit, SplitBoundaries]:
    """Split into contiguous train / validation / test ranges by row position.

    `timestamp_column_is_sorted=False` sorts first, because splitting an
    unsorted frame by position would place arbitrary rows into the test period
    and leak future conditions into training. Either way the result is a set of
    contiguous time ranges — there is no shuffling anywhere in this function, and
    no parameter exists that could introduce one.
    """
    if not timestamp_column_is_sorted:
        frame, _ = sort_chronologically(frame, column)
    elif not frame[column].is_monotonic_increasing:
        frame, _ = sort_chronologically(frame, column)

    total = len(frame)
    if total < 3:
        raise PreprocessError(f"at least 3 rows are required for a 3-way split, got {total}")

    train_end = int(total * split.train_fraction)
    validation_end = train_end + int(total * split.validation_fraction)
    # Guard against a degenerate split when rounding truncates a small frame.
    train_end = max(1, min(train_end, total - 2))
    validation_end = max(train_end + 1, min(validation_end, total - 1))

    train = frame.iloc[:train_end].reset_index(drop=True)
    validation = frame.iloc[train_end:validation_end].reset_index(drop=True)
    test = frame.iloc[validation_end:].reset_index(drop=True)

    def bounds(part: pd.DataFrame) -> tuple[str | None, str | None]:
        if part.empty:
            return None, None
        return _iso(part[column].iloc[0]), _iso(part[column].iloc[-1])

    train_start, train_last = bounds(train)
    val_start, val_last = bounds(validation)
    test_start, test_last = bounds(test)

    boundaries = SplitBoundaries(
        train_start=train_start,
        train_end=train_last,
        validation_start=val_start,
        validation_end=val_last,
        test_start=test_start,
        test_end=test_last,
        train_rows=len(train),
        validation_rows=len(validation),
        test_rows=len(test),
    )
    if not boundaries.is_ordered():
        raise PreprocessError(
            "chronological split produced non-monotonic boundaries; this indicates a "
            "timestamp column that is not strictly increasing after sorting"
        )
    return ChronologicalSplit(train=train, validation=validation, test=test), boundaries


def _iso(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and value != value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def assert_no_overlap(split: ChronologicalSplit, column: str) -> None:
    """Raise if any two splits share a timestamp.

    Overlapping boundaries would mean a row influenced both fitting and scoring,
    which is exactly the leakage this module exists to prevent.
    """
    seen: set[Any] = set()
    for name, part in (("train", split.train), ("validation", split.validation), ("test", split.test)):
        stamps = set(part[column].tolist())
        overlap = stamps & seen
        if overlap:
            raise PreprocessError(
                f"{name} split shares {len(overlap)} timestamp(s) with an earlier split; "
                "this is target leakage"
            )
        seen |= stamps


# --------------------------------------------------------------------------- #
# 7-8. Train-fitted transforms
# --------------------------------------------------------------------------- #


class StandardScaler:
    """Per-column standardisation fitted on training rows only.

    `fit` must be called with the training slice before any `transform`. The
    stored `fitted_rows` is recorded so a reviewer can assert the scaler saw only
    training data; `assert_fitted_on` performs that assertion.
    """

    def __init__(self) -> None:
        self._mean: dict[str, float] = {}
        self._scale: dict[str, float] = {}
        self._fitted_rows = 0
        self._fitted_on: str | None = None

    @property
    def is_fitted(self) -> bool:
        return bool(self._mean)

    @property
    def fitted_rows(self) -> int:
        return self._fitted_rows

    @property
    def fitted_on(self) -> str | None:
        """Label of the split the scaler was fitted on (e.g. ``train``)."""
        return self._fitted_on

    def fit(self, frame: pd.DataFrame, columns: Sequence[str], *, split_label: str = "train") -> "StandardScaler":
        if split_label != "train":
            raise PreprocessError(
                f"StandardScaler may only be fitted on the training split, got {split_label!r}"
            )
        for column in columns:
            values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
            finite = values[np.isfinite(values)]
            if finite.size == 0:
                raise PreprocessError(f"cannot fit scaler: column {column!r} has no finite training values")
            mean = float(finite.mean())
            std = float(finite.std(ddof=0))
            # A constant column has zero spread; scale by 1.0 so it becomes
            # exactly 0 after centring instead of producing NaN/inf downstream.
            self._mean[column] = mean
            self._scale[column] = std if std > 0 else 1.0
        self._fitted_rows = len(frame)
        self._fitted_on = split_label
        return self

    def transform(self, frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
        if not self.is_fitted:
            raise PreprocessError("StandardScaler.transform called before fit")
        out = frame.copy()
        for column in columns:
            if column not in self._mean:
                raise PreprocessError(f"StandardScaler was not fitted on column {column!r}")
            values = pd.to_numeric(out[column], errors="coerce").astype("float64")
            out[column] = (values - self._mean[column]) / self._scale[column]
        return out

    def transform_matrix(self, matrix: np.ndarray, columns: Sequence[str]) -> np.ndarray:
        """Transform a raw numeric matrix using the fitted statistics."""
        if not self.is_fitted:
            raise PreprocessError("StandardScaler.transform_matrix called before fit")
        if matrix.shape[1] != len(columns):
            raise PreprocessError(
                f"matrix has {matrix.shape[1]} column(s) but {len(columns)} were named"
            )
        means = np.array([self._mean[c] for c in columns], dtype="float64")
        scales = np.array([self._scale[c] for c in columns], dtype="float64")
        return (matrix - means) / scales

    def assert_fitted_on(self, split_label: str) -> None:
        if not self.is_fitted:
            raise PreprocessError("scaler is not fitted")
        if self._fitted_on != split_label:
            raise PreprocessError(
                f"scaler was fitted on {self._fitted_on!r} but {split_label!r} was expected"
            )

    def state(self) -> dict[str, Any]:
        """Serialisable description of the fitted state (for artifacts)."""
        return {
            "kind": "standard",
            "columns": list(self._mean),
            "mean": dict(self._mean),
            "scale": dict(self._scale),
            "fitted_rows": self._fitted_rows,
            "fitted_on": self._fitted_on,
        }


class TrainFittedImputer:
    """Median/constant imputation fitted on training rows only.

    Like the scaler, `fit` refuses any split label other than `train`, and
    `assert_fitted_on` is available to tests that need to prove the
    validation/test frames were transformed with training statistics.
    """

    def __init__(self, strategy: str = "median") -> None:
        if strategy not in ("median", "constant", "zero"):
            raise PreprocessError(f"unknown imputer strategy {strategy!r}")
        self._strategy = strategy
        self._values: dict[str, float] = {}
        self._fitted_rows = 0
        self._fitted_on: str | None = None

    @property
    def strategy(self) -> str:
        return self._strategy

    @property
    def is_fitted(self) -> bool:
        return bool(self._values)

    @property
    def fitted_rows(self) -> int:
        return self._fitted_rows

    @property
    def fitted_on(self) -> str | None:
        return self._fitted_on

    def fit(
        self,
        frame: pd.DataFrame,
        columns: Sequence[str],
        *,
        split_label: str = "train",
        constant: float = 0.0,
    ) -> "TrainFittedImputer":
        if split_label != "train":
            raise PreprocessError(
                f"TrainFittedImputer may only be fitted on the training split, got {split_label!r}"
            )
        for column in columns:
            if self._strategy == "zero":
                self._values[column] = 0.0
                continue
            if self._strategy == "constant":
                self._values[column] = float(constant)
                continue
            values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
            finite = values[np.isfinite(values)]
            if finite.size == 0:
                raise PreprocessError(
                    f"cannot fit median imputer: column {column!r} has no finite training values"
                )
            self._values[column] = float(np.median(finite))
        self._fitted_rows = len(frame)
        self._fitted_on = split_label
        return self

    def transform(self, frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
        if not self.is_fitted:
            raise PreprocessError("TrainFittedImputer.transform called before fit")
        out = frame.copy()
        for column in columns:
            if column not in self._values:
                raise PreprocessError(f"imputer was not fitted on column {column!r}")
            values = pd.to_numeric(out[column], errors="coerce").astype("float64")
            out[column] = values.fillna(self._values[column])
        return out

    def assert_fitted_on(self, split_label: str) -> None:
        if not self.is_fitted:
            raise PreprocessError("imputer is not fitted")
        if self._fitted_on != split_label:
            raise PreprocessError(
                f"imputer was fitted on {self._fitted_on!r} but {split_label!r} was expected"
            )

    def state(self) -> dict[str, Any]:
        return {
            "kind": self._strategy,
            "columns": list(self._values),
            "values": dict(self._values),
            "fitted_rows": self._fitted_rows,
            "fitted_on": self._fitted_on,
        }


# --------------------------------------------------------------------------- #
# Top-level orchestration
# --------------------------------------------------------------------------- #


@dataclass
class PreprocessingResult:
    """Outcome of the full validation/preparation pass, with its step log."""

    frame: pd.DataFrame
    steps: list[ProcessingStep] = field(default_factory=list)
    duplicate_report: DuplicateReport | None = None
    sampling_interval: str | None = None

    def step_log(self) -> list[str]:
        return [step.describe() for step in self.steps]

    def record(self, step: ProcessingStep) -> None:
        self.steps.append(step)


def prepare_frame(frame: pd.DataFrame, config: HydroConfig, *, resolve_duplicate_timestamps: bool = True) -> PreprocessingResult:
    """Validate and clean a raw observation frame.

    This performs steps 1-5 of the documented pipeline. Feature building
    (`features.py`), splitting (`chronological_split`) and scaling happen after
    this returns, because they each need the cleaned, timestamp-sorted frame.
    """
    dataset = config.dataset
    target_column = config.target.column
    required = [dataset.timestamp_column, target_column, *config.features.exogenous_columns]
    if config.features.rainfall_column:
        required.append(config.features.rainfall_column)
    result = PreprocessingResult(frame=frame)
    result.record(validate_columns(frame, required))
    result.record(reject_non_finite(frame, [target_column]))

    cleaned, step = parse_timestamps(frame, dataset.timestamp_column)
    result.record(step)

    cleaned, step = sort_chronologically(cleaned, dataset.timestamp_column)
    result.record(step)

    result.duplicate_report = report_duplicates(cleaned, dataset.timestamp_column)
    if result.duplicate_report.has_duplicates:
        if not resolve_duplicate_timestamps:
            raise PreprocessError(
                f"dataset contains {result.duplicate_report.duplicate_count} duplicated timestamp(s) "
                f"({', '.join(result.duplicate_report.duplicated_timestamps[:5])}); "
                "resolve them in the source dataset or enable the documented 'last wins' policy"
            )
        cleaned, step = resolve_duplicates(cleaned, dataset.timestamp_column, keep="last")
        result.record(step)

    numeric_columns = [target_column, *config.features.exogenous_columns]
    if config.features.rainfall_column:
        numeric_columns.append(config.features.rainfall_column)
    cleaned, step = apply_missing_policy(
        cleaned,
        numeric_columns,
        policy=config.missing_policy,
        max_fill_gap=config.max_fill_gap,
        id_columns=dataset.id_columns,
    )
    result.record(step)

    result.sampling_interval = dataset.sampling_interval or infer_sampling_interval(
        cleaned, dataset.timestamp_column
    )
    result.frame = cleaned
    return result


def describe_preprocessing(steps: Iterable[ProcessingStep]) -> str:
    """Render a step log as a printable block."""
    return "\n".join(step.describe() for step in steps)


def utc_to_iso(value: datetime) -> str:
    """Format a datetime as ISO-8601 with a trailing `Z` (UTC)."""
    return value.astimezone(tz=None).isoformat() + "Z"
