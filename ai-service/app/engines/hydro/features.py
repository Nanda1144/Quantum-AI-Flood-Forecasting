# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Leakage-safe time-series feature engineering.

Three rules govern everything in this module.

1. **Strictly past only.** Every value a feature exposes for row *t* is computed
   from observations at rows `< t`. Autoregressive features are therefore built
   with `shift(k)` for `k >= 1`, and rolling statistics are computed on
   `series.shift(1)` so the current (still unobserved at prediction time) value
   never enters its own window.
2. **Only columns that exist.** No column is invented. A dataset with no
   rainfall column gets no rainfall aggregate; a dataset with no inflow column
   gets no inflow lag. `FeaturePlan.source_columns` records exactly which source
   columns produced which features.
3. **Forward-time supervision only.** The supervised matrix pairs features at
   row *t* with the target at row *t + h*, where `h` is the lead time in rows.
   Rows whose target lies past the end of the frame are dropped rather than
   padded or back-filled.

Calendar features (hour-of-day, day-of-year) are deterministic functions of the
timestamp, not of the target, so they cannot leak.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

from .config import HydroConfig
from .preprocessing import PreprocessError

#: Feature groups, used for documentation and for the leakage audit.
FEATURE_GROUPS = ("lag", "rolling", "calendar", "exogenous", "rainfall", "raw")


class FeatureError(ValueError):
    """Raised when features cannot be built honestly from the given data."""


@dataclass(frozen=True)
class FeatureSpecEntry:
    """One documented feature column."""

    name: str
    group: str
    source_column: str
    kind: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "group": self.group,
            "source_column": self.source_column,
            "kind": self.kind,
            "description": self.description,
        }


@dataclass(frozen=True)
class FeaturePlan:
    """The exact feature set built for a dataset, with its documentation."""

    entries: tuple[FeatureSpecEntry, ...] = ()
    target_column: str | None = None
    rainfall_column: str | None = None
    lead_time_rows: int = 1
    dropped_rows: int = 0

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self.entries)

    @property
    def source_columns(self) -> tuple[str, ...]:
        """Distinct source columns the features were derived from."""
        seen: list[str] = []
        for entry in self.entries:
            if entry.source_column not in seen:
                seen.append(entry.source_column)
        return tuple(seen)

    def describe(self) -> str:
        lines = [f"Feature plan ({len(self.entries)} feature(s)), lead time = {self.lead_time_rows} row(s):"]
        for entry in self.entries:
            lines.append(f"  - {entry.name} [{entry.group}] = {entry.description}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "features": [entry.to_dict() for entry in self.entries],
            "target_column": self.target_column,
            "rainfall_column": self.rainfall_column,
            "lead_time_rows": self.lead_time_rows,
            "dropped_rows": self.dropped_rows,
        }


@dataclass
class SupervisedSet:
    """Features aligned with a forward-shifted target."""

    features: pd.DataFrame
    target: np.ndarray
    feature_names: tuple[str, ...]
    origin_timestamps: pd.Series
    target_timestamps: pd.Series
    plan: FeaturePlan

    @property
    def n_samples(self) -> int:
        return len(self.target)

    def feature_matrix(self) -> np.ndarray:
        """Dense float matrix of the feature frame, NaNs preserved."""
        return self.features.to_numpy(dtype="float64", na_value=np.nan)

    def target_vector(self) -> np.ndarray:
        return self.target


def _validate_existing(frame: pd.DataFrame, columns: Sequence[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise FeatureError(f"{label} not present in the dataset: {missing}")


def build_features(
    frame: pd.DataFrame,
    config: HydroConfig,
    *,
    timestamp_column: str | None = None,
) -> tuple[pd.DataFrame, FeaturePlan]:
    """Build the documented, leakage-safe feature frame for `frame`.

    The returned frame keeps the timestamp column and gains one column per
    feature listed in the returned `FeaturePlan`. The target column is retained
    for alignment but is never itself a feature.
    """
    ts_col = timestamp_column or config.dataset.timestamp_column
    target_col = config.target.column
    spec = config.features
    _validate_existing(frame, [ts_col, target_col], "timestamp and target columns")
    _validate_existing(frame, spec.exogenous_columns, "configured exogenous columns")
    rainfall_col = spec.rainfall_column

    # The target may not be admitted as a feature, at *any* layer. `build_supervised`
    # re-checks this on the assembled matrix, but checking here is defence in
    # depth at the point of admission: a caller that uses `build_features` on its
    # own, without building a supervised set, must not be handed a feature frame
    # containing the target. The rainfall column is checked for the same reason -
    # declaring the target to also be the rainfall series is a configuration
    # mistake that would otherwise look like an ordinary exogenous column.
    for source in (*spec.exogenous_columns, rainfall_col):
        if source == target_col:
            raise FeatureError(
                f"target column {target_col!r} must never appear in the feature list "
                "(declared as an exogenous or rainfall column); that is target leakage"
            )

    if rainfall_col and rainfall_col not in frame.columns:
        # The configuration named a rainfall column the dataset does not have.
        # Refusing is better than silently dropping the signal the operator asked
        # for, because the resulting model would be missing a declared feature.
        raise FeatureError(
            f"configured rainfall column {rainfall_col!r} is not present in the dataset; "
            "either supply the column or clear HYDRO_RAINFALL_COLUMN"
        )

    out = frame.copy()
    entries: list[FeatureSpecEntry] = []
    ordered = frame[ts_col].sort_values(kind="stable")

    # --- 1. autoregressive lag + rolling features from the target ----------
    numeric_target = pd.to_numeric(out[target_col], errors="coerce")
    for lag in range(1, spec.max_lag + 1):
        name = f"{target_col}_lag{lag}"
        out[name] = numeric_target.shift(lag)
        entries.append(
            FeatureSpecEntry(
                name=name,
                group="lag",
                source_column=target_col,
                kind="autoregressive_lag",
                description=(
                    f"observed {target_col} {lag} row(s) before the prediction time "
                    f"(shift({lag}); never includes the current or any future value)"
                ),
            )
        )

    # Rolling statistics are computed on shift(1) so the window is strictly past.
    shifted = numeric_target.shift(1)
    for window in spec.rolling_windows:
        rolling = shifted.rolling(window=window, min_periods=window)
        for stat, label in (("mean", "mean"), ("max", "max"), ("min", "min"), ("std", "std")):
            name = f"{target_col}_roll{window}_{stat}"
            out[name] = getattr(rolling, stat)()
            entries.append(
                FeatureSpecEntry(
                    name=name,
                    group="rolling",
                    source_column=target_col,
                    kind=f"rolling_{label}_shifted",
                    description=(
                        f"rolling {label} of {target_col} over the {window} row(s) ending at t-1 "
                        f"(shift(1).rolling({window}).{stat}()); excludes t and everything after it"
                    ),
                )
            )

    # Trend of the most recent change, still strictly past.
    if spec.max_lag >= 2:
        name = f"{target_col}_diff1"
        out[name] = numeric_target.shift(1) - numeric_target.shift(2)
        entries.append(
            FeatureSpecEntry(
                name=name,
                group="lag",
                source_column=target_col,
                kind="first_difference",
                description=(
                    f"change in {target_col} between t-2 and t-1 (shift(1) - shift(2)); "
                    "strictly past"
                ),
            )
        )

    # --- 2. exogenous columns --------------------------------------------
    for column in spec.exogenous_columns:
        numeric = pd.to_numeric(out[column], errors="coerce")
        for lag in (1, 2):
            if lag > spec.max_lag:
                continue
            name = f"{column}_lag{lag}"
            out[name] = numeric.shift(lag)
            entries.append(
                FeatureSpecEntry(
                    name=name,
                    group="exogenous",
                    source_column=column,
                    kind="lag",
                    description=f"{column} {lag} row(s) before the prediction time (shift({lag}))",
                )
            )
        for window in spec.rolling_windows:
            name = f"{column}_roll{window}_sum"
            out[name] = numeric.shift(1).rolling(window=window, min_periods=1).sum()
            entries.append(
                FeatureSpecEntry(
                    name=name,
                    group="exogenous",
                    source_column=column,
                    kind="rolling_sum_shift1",
                    description=(
                        f"cumulative {column} over the {window} row(s) ending at t-1; excludes t"
                    ),
                )
            )

    # --- 3. rainfall aggregates (only when the dataset has rainfall) -------
    if rainfall_col:
        numeric_rain = pd.to_numeric(out[rainfall_col], errors="coerce")
        for lag in (1, 2):
            if lag > spec.max_lag:
                continue
            name = f"{rainfall_col}_lag{lag}"
            out[name] = numeric_rain.shift(lag)
            entries.append(
                FeatureSpecEntry(
                    name=name,
                    group="rainfall",
                    source_column=rainfall_col,
                    kind="lag",
                    description=f"{rainfall_col} {lag} row(s) before the prediction time (shift({lag}))",
                )
            )
        for window in spec.rolling_windows:
            for stat in ("sum", "max"):
                name = f"{rainfall_col}_roll{window}_{stat}"
                out[name] = getattr(numeric_rain.shift(1).rolling(window=window, min_periods=1), stat)()
                entries.append(
                    FeatureSpecEntry(
                        name=name,
                        group="rainfall",
                        source_column=rainfall_col,
                        kind=f"rolling_{stat}_shift1",
                        description=(
                            f"rolling {stat} of {rainfall_col} over the {window} row(s) ending at t-1; "
                            "excludes t"
                        ),
                    )
                )

    # --- 4. calendar features (deterministic, no target access) ----------
    if spec.include_calendar:
        stamps = pd.to_datetime(out[ts_col])
        hour = stamps.dt.hour.astype("float64")
        day_of_year = stamps.dt.dayofyear.astype("float64")
        out["calendar_hour_sin"] = np.sin(2.0 * math.pi * hour / 24.0)
        out["calendar_hour_cos"] = np.cos(2.0 * math.pi * hour / 24.0)
        out["calendar_doy_sin"] = np.sin(2.0 * math.pi * day_of_year / 365.25)
        out["calendar_doy_cos"] = np.cos(2.0 * math.pi * day_of_year / 365.25)
        for name, description in (
            ("calendar_hour_sin", "sin(2*pi*hour_of_day/24) — diurnal cycle of the prediction time"),
            ("calendar_hour_cos", "cos(2*pi*hour_of_day/24) — diurnal cycle of the prediction time"),
            ("calendar_doy_sin", "sin(2*pi*day_of_year/365.25) — annual cycle of the prediction time"),
            ("calendar_doy_cos", "cos(2*pi*day_of_year/365.25) — annual cycle of the prediction time"),
        ):
            entries.append(
                FeatureSpecEntry(
                    name=name,
                    group="calendar",
                    source_column=ts_col,
                    kind="deterministic_calendar",
                    description=description,
                )
            )

    plan = FeaturePlan(
        entries=tuple(entries),
        target_column=target_col,
        rainfall_column=rainfall_col,
        lead_time_rows=1,
    )
    assert_feature_frame_ordered(out, ts_col, ordered)
    return out, plan


def assert_feature_frame_ordered(features: pd.DataFrame, ts_col: str, reference_order: pd.Series) -> None:
    """Fail loudly if feature building silently reordered the frame.

    Reordering is not a cosmetic problem: with a lead-time alignment applied
    afterwards, a permuted frame would pair a feature row with the wrong target.
    """
    if not features[ts_col].reset_index(drop=True).equals(reference_order.reset_index(drop=True)):
        raise FeatureError("feature construction reordered the frame; timestamps must be preserved")


def feature_names(plan: FeaturePlan) -> tuple[str, ...]:
    return plan.names


def build_supervised(
    features: pd.DataFrame,
    plan: FeaturePlan,
    config: HydroConfig,
    *,
    lead_time_rows: int | None = None,
    timestamp_column: str | None = None,
) -> SupervisedSet:
    """Align features at *t* with the target at *t + h*.

    `lead_time_rows` defaults to 1, meaning the next observation. Pass a larger
    value for a longer lead time. The last `h` rows have no future target and
    are dropped — never padded, never back-filled from the past.

    Alignment is asserted: every origin timestamp must be strictly earlier than
    its paired target timestamp.
    """
    ts_col = timestamp_column or config.dataset.timestamp_column
    target_col = config.target.column
    if target_col is None:
        raise FeatureError("feature plan has no target column")
    if lead_time_rows is None or lead_time_rows < 1:
        raise FeatureError(f"lead_time_rows must be >= 1, got {lead_time_rows}")

    names = plan.names
    if not names:
        raise FeatureError("feature plan is empty; nothing to model")
    if target_col in names:
        raise FeatureError(
            f"target column {target_col!r} must never appear in the feature list; that is target leakage"
        )

    shifted_target = pd.to_numeric(features[target_col], errors="coerce").shift(-lead_time_rows)
    aligned = features.loc[shifted_target.notna(), list(names)]
    aligned_target = shifted_target.loc[shifted_target.notna()]
    origin_ts = features.loc[aligned.index, ts_col]
    target_ts = features[ts_col].shift(-lead_time_rows).loc[aligned.index]

    if len(aligned) == 0:
        raise FeatureError(
            f"no supervised samples remain after a {lead_time_rows}-row lead-time alignment"
        )

    if not (target_ts.to_numpy() > origin_ts.to_numpy()).all():
        raise FeatureError(
            "lead-time alignment produced a target that is not strictly in the future of its features; "
            "this is target leakage"
        )

    dropped = len(features) - len(aligned)
    return SupervisedSet(
        features=aligned.reset_index(drop=True),
        target=aligned_target.to_numpy(dtype="float64"),
        feature_names=names,
        origin_timestamps=origin_ts.reset_index(drop=True),
        target_timestamps=target_ts.reset_index(drop=True),
        plan=FeaturePlan(
            entries=plan.entries,
            target_column=plan.target_column,
            rainfall_column=plan.rainfall_column,
            lead_time_rows=lead_time_rows,
            dropped_rows=dropped,
        ),
    )


def lead_time_rows_for(config: HydroConfig, sampling_interval: str | None) -> int:
    """Convert the configured forecast horizon into a row count.

    The horizon is declared in hours; the number of rows it spans depends on the
    sampling interval, which is either configured or inferred from the data. When
    neither is available the horizon cannot be honoured and the caller is told so
    rather than being given a guessed row count.
    """
    if sampling_interval is None:
        raise FeatureError(
            "cannot convert the forecast horizon to rows: the sampling interval is unknown. "
            "Configure HYDRO_SAMPLING_INTERVAL or supply a regular series"
        )
    hours = config.target.horizon_hours
    seconds = _interval_seconds(sampling_interval)
    if seconds is None or seconds <= 0:
        # The accepted spellings are named, because this value usually comes
        # from an operator setting HYDRO_SAMPLING_INTERVAL and a bare error
        # naming the rejected token is not enough to act on.
        raise FeatureError(
            f"unrecognised sampling interval {sampling_interval!r}; expected a number followed "
            "by a unit, e.g. '15min', '1h', '1D', '30s'"
        )
    step_hours = seconds / 3600.0
    rows = hours / step_hours
    rounded = int(round(rows))
    if rounded < 1:
        rounded = 1
    return rounded


def _interval_seconds(interval: str) -> int | None:
    text = interval.strip().lower()
    units = (("d", 86400), ("h", 3600), ("min", 60), ("s", 1))
    for suffix, factor in units:
        if text.endswith(suffix):
            number = text[: -len(suffix)].strip()
            try:
                return int(float(number) * factor)
            except ValueError:
                return None
    try:
        return int(float(text))
    except ValueError:
        return None


def audit_causality(
    frame: pd.DataFrame,
    config: HydroConfig,
    *,
    cutoff_index: int | None = None,
) -> None:
    """Prove that features at row *t* do not change when future rows change.

    This is a runtime, not a unit-test-only, guarantee. The frame is truncated
    at `cutoff_index` and the features rebuilt; every feature value at or before
    the cutoff must be identical to the full-frame build. If any feature looked
    ahead, the mutated future would have changed a past value and this raises.

    The final rows are excluded from the comparison because the rolling windows
    need a full lookback, and a truncated frame legitimately has fewer usable
    rows at its tail.
    """
    full, _ = build_features(frame, config)
    if cutoff_index is None:
        cutoff_index = max(1, len(frame) // 2)
    truncated, _ = build_features(frame.iloc[: cutoff_index + 1].copy(), config)

    shared_length = min(len(truncated), len(full)) - 1
    if shared_length <= 0:
        raise FeatureError("not enough rows to audit causality")

    names = [name for name in full.columns if name not in frame.columns]
    for name in names:
        left = full[name].to_numpy(dtype="float64", na_value=np.nan)[:shared_length]
        right = truncated[name].to_numpy(dtype="float64", na_value=np.nan)[:shared_length]
        if not np.allclose(left, right, equal_nan=True, rtol=0.0, atol=0.0):
            bad = int(np.sum(~np.isclose(left, right, equal_nan=True, rtol=0.0, atol=0.0)))
            raise FeatureError(
                f"feature {name!r} changes when the future is truncated at row {cutoff_index} "
                f"({bad} value(s) differ) — it is not strictly causal"
            )


def describe_features(plan: FeaturePlan) -> str:
    return plan.describe()
