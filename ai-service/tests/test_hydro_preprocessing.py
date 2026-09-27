# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Tests for `app.engines.hydro.preprocessing`.

All inputs are SYNTHETIC/DEMO data. Nothing here measures hydrological skill.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engines.hydro.config import SplitSpec
from app.engines.hydro.preprocessing import (
    DuplicateReport,
    PreprocessError,
    StandardScaler,
    TrainFittedImputer,
    apply_missing_policy,
    assert_no_overlap,
    chronological_split,
    infer_sampling_interval,
    parse_timestamps,
    prepare_frame,
    report_duplicates,
    reject_non_finite,
    resolve_duplicates,
    sort_chronologically,
    validate_columns,
)


def _frame(rows: int = 40) -> pd.DataFrame:
    stamps = pd.date_range("2024-01-01", periods=rows, freq="h")
    return pd.DataFrame(
        {
            "timestamp": [s.isoformat() for s in stamps],
            "water_level": np.linspace(3.0, 5.0, rows),
        }
    )


# --- column validation -------------------------------------------------------


def test_validate_columns_accepts_present_columns():
    step = validate_columns(_frame(), ["timestamp", "water_level"])
    assert step.rows_in == step.rows_out


def test_validate_columns_rejects_missing_column():
    with pytest.raises(PreprocessError, match="required column"):
        validate_columns(_frame(), ["timestamp", "water_level", "inflow"])


def test_validate_columns_rejects_empty_frame():
    empty = pd.DataFrame({"timestamp": [], "water_level": []})
    with pytest.raises(PreprocessError, match="empty"):
        validate_columns(empty, ["timestamp", "water_level"])


def test_reject_non_finite_catches_nan_and_inf():
    frame = _frame()
    frame.loc[3, "water_level"] = np.nan
    with pytest.raises(PreprocessError, match="non-finite"):
        reject_non_finite(frame, ["water_level"])

    frame = _frame()
    frame.loc[3, "water_level"] = np.inf
    with pytest.raises(PreprocessError, match="non-finite"):
        reject_non_finite(frame, ["water_level"])


# --- timestamps and ordering -------------------------------------------------


def test_parse_timestamps_produces_naive_utc():
    frame = pd.DataFrame({"timestamp": ["2024-01-01T05:00:00+05:30"], "water_level": [1.0]})
    out, step = parse_timestamps(frame, "timestamp")
    assert step.rows_in == 1
    # 05:00 IST == 23:30 UTC the previous day: the offset is applied, not dropped.
    assert out["timestamp"].iloc[0] == pd.Timestamp("2024-01-01T05:00:00+05:30").tz_convert(None)


def test_parse_timestamps_rejects_unparseable_values():
    frame = pd.DataFrame({"timestamp": ["2024-01-01", "not-a-date"], "water_level": [1.0, 2.0]})
    with pytest.raises(PreprocessError, match="could not be parsed"):
        parse_timestamps(frame, "timestamp")


def test_parse_timestamps_rejects_absent_column():
    with pytest.raises(PreprocessError, match="not present"):
        parse_timestamps(_frame(), "observed_at")


def test_sort_chronologically_orders_rows():
    frame = _frame()
    shuffled = frame.iloc[::-1].reset_index(drop=True)
    ordered, step = sort_chronologically(shuffled, "timestamp")
    assert ordered["timestamp"].is_monotonic_increasing
    assert step.detail["reordered"] is True
    assert ordered["water_level"].iloc[0] == pytest.approx(3.0)


def test_sort_chronologically_reports_no_change_when_already_ordered():
    _, step = sort_chronologically(_frame(), "timestamp")
    assert step.detail["reordered"] is False
    assert "already in chronological order" in step.description


# --- duplicates --------------------------------------------------------------


def test_report_duplicates_counts_affected_rows():
    frame = _frame()
    frame = pd.concat([frame, frame.tail(3)], ignore_index=True)
    report = report_duplicates(frame, "timestamp")
    assert report.has_duplicates is True
    assert report.duplicate_count == 3
    assert report.affected_row_count == 6


def test_report_duplicates_finds_none_in_clean_frame():
    report = report_duplicates(_frame(), "timestamp")
    assert report == DuplicateReport(duplicate_count=0, duplicated_timestamps=(), affected_row_count=0)


def test_resolve_duplicates_keeps_last_by_default():
    frame = _frame()
    frame = pd.concat([frame, frame.tail(2)], ignore_index=True)
    frame.loc[len(frame) - 1, "water_level"] = 99.0
    out, step = resolve_duplicates(frame, "timestamp")
    assert len(out) == 40
    assert step.detail["dropped"] == 2
    # 'last wins' is a documented policy, so the later reading survives.
    assert out["water_level"].iloc[-1] == pytest.approx(99.0)


def test_resolve_duplicates_rejects_implicit_policy():
    with pytest.raises(PreprocessError, match="keep policy"):
        resolve_duplicates(_frame(), "timestamp", keep="mean")


# --- sampling interval -------------------------------------------------------


@pytest.mark.parametrize(
    ("freq", "expected"),
    [("h", "1h"), ("30min", "30min"), ("D", "1D")],
)
def test_infer_sampling_interval_regular_series(freq, expected):
    stamps = pd.date_range("2024-01-01", periods=50, freq=freq)
    frame = pd.DataFrame({"timestamp": stamps})
    assert infer_sampling_interval(frame, "timestamp") == expected


def test_infer_sampling_interval_returns_none_for_irregular_series():
    stamps = pd.to_datetime(
        [
            "2024-01-01T00:00",
            "2024-01-01T01:00",
            "2024-01-01T05:00",
            "2024-01-01T06:00",
            "2024-01-01T20:00",
            "2024-01-02T01:00",
        ]
    )
    frame = pd.DataFrame({"timestamp": stamps})
    # Irregular cadence must stay unknown rather than being asserted as a rate.
    assert infer_sampling_interval(frame, "timestamp") is None


def test_infer_sampling_interval_needs_enough_rows():
    frame = pd.DataFrame({"timestamp": pd.to_datetime(["2024-01-01", "2024-01-02"])})
    assert infer_sampling_interval(frame, "timestamp") is None


# --- missing values ----------------------------------------------------------


def test_ffill_policy_fills_small_gaps():
    frame = _frame()
    frame.loc[4:5, "water_level"] = np.nan
    out, step = apply_missing_policy(frame, ["water_level"], policy="ffill", max_fill_gap=3)
    assert len(out) == 40
    assert out["water_level"].isna().sum() == 0
    assert step.detail["missing_before"]["water_level"] == 2
    # Forward fill carries the value from t-1 only: it never looks ahead.
    assert out["water_level"].iloc[4] == pytest.approx(frame["water_level"].iloc[3])


def test_ffill_policy_drops_rows_beyond_max_gap():
    frame = _frame()
    frame.loc[4:8, "water_level"] = np.nan  # gap of 5 > max_fill_gap 3
    out, step = apply_missing_policy(frame, ["water_level"], policy="ffill", max_fill_gap=3)
    # The first 3 rows of the gap are filled, the remaining 2 are dropped.
    assert len(out) == 38
    assert step.rows_dropped == 2


def test_drop_policy_removes_incomplete_rows():
    frame = _frame()
    frame.loc[[2, 7], "water_level"] = np.nan
    out, _ = apply_missing_policy(frame, ["water_level"], policy="drop")
    assert len(out) == 38


def test_error_policy_raises_on_any_gap():
    frame = _frame()
    frame.loc[2, "water_level"] = np.nan
    with pytest.raises(PreprocessError, match="policy 'error'"):
        apply_missing_policy(frame, ["water_level"], policy="error")


def test_unknown_missing_policy_is_rejected():
    with pytest.raises(PreprocessError, match="unknown missing-value policy"):
        apply_missing_policy(_frame(), ["water_level"], policy="magic")


# --- chronological split -----------------------------------------------------


def test_chronological_split_produces_contiguous_ordered_ranges():
    frame = _frame(100)
    parsed, _ = parse_timestamps(frame, "timestamp")
    split, boundaries = chronological_split(parsed, "timestamp", SplitSpec(0.6, 0.2))
    assert split.sizes() == {"train": 60, "validation": 20, "test": 20}
    assert boundaries.is_ordered() is True
    # Boundaries must be strictly increasing, never overlapping.
    assert parsed["timestamp"].iloc[59] < split.validation["timestamp"].iloc[0]
    assert split.validation["timestamp"].iloc[-1] < split.test["timestamp"].iloc[0]


def test_chronological_split_never_shuffles():
    frame = _frame(60)
    parsed, _ = parse_timestamps(frame, "timestamp")
    split, _ = chronological_split(parsed, "timestamp", SplitSpec(0.5, 0.25))
    # Train is exactly the first half of the series, in original order.
    assert split.train["timestamp"].tolist() == parsed["timestamp"].iloc[:30].tolist()
    assert split.test["timestamp"].tolist() == parsed["timestamp"].iloc[45:].tolist()


def test_chronological_split_sorts_unsorted_input_first():
    frame = _frame(60)
    frame = frame.sample(frac=1.0, random_state=3).reset_index(drop=True)
    parsed, _ = parse_timestamps(frame, "timestamp")
    split, boundaries = chronological_split(
        parsed, "timestamp", SplitSpec(0.5, 0.25), timestamp_column_is_sorted=False
    )
    assert split.train["timestamp"].is_monotonic_increasing
    assert split.validation["timestamp"].is_monotonic_increasing
    assert split.test["timestamp"].is_monotonic_increasing
    assert boundaries.is_ordered() is True


def test_chronological_split_rejects_tiny_frames():
    frame, _ = parse_timestamps(_frame(2), "timestamp")
    with pytest.raises(PreprocessError, match="at least 3 rows"):
        chronological_split(frame, "timestamp", SplitSpec(0.6, 0.2))


def test_assert_no_overlap_passes_for_real_split():
    frame = _frame(90)
    parsed, _ = parse_timestamps(frame, "timestamp")
    split, _ = chronological_split(parsed, "timestamp", SplitSpec(0.6, 0.2))
    assert_no_overlap(split, "timestamp")  # must not raise


def test_assert_no_overlap_detects_a_leaky_split():
    frame = _frame(90)
    parsed, _ = parse_timestamps(frame, "timestamp")
    split, _ = chronological_split(parsed, "timestamp", SplitSpec(0.6, 0.2))
    leaked = type(split)(
        train=split.train,
        validation=pd.concat([split.validation, split.train.tail(2)], ignore_index=True),
        test=split.test,
    )
    with pytest.raises(PreprocessError, match="target leakage"):
        assert_no_overlap(leaked, "timestamp")


# --- train-fitted transforms -------------------------------------------------


def test_scaler_refuses_to_transform_before_fit():
    scaler = StandardScaler()
    with pytest.raises(PreprocessError, match="before fit"):
        scaler.transform(_frame(), ["water_level"])


def test_scaler_refuses_to_fit_on_anything_but_train():
    frame = _frame()
    with pytest.raises(PreprocessError, match="only be fitted on the training split"):
        StandardScaler().fit(frame, ["water_level"], split_label="validation")
    with pytest.raises(PreprocessError, match="only be fitted on the training split"):
        StandardScaler().fit(frame, ["water_level"], split_label="test")


def test_scaler_records_the_split_it_was_fitted_on():
    frame = _frame(50)
    scaler = StandardScaler().fit(frame, ["water_level"], split_label="train")
    assert scaler.fitted_on == "train"
    assert scaler.fitted_rows == 50
    scaler.assert_fitted_on("train")
    with pytest.raises(PreprocessError, match="was fitted on 'train'"):
        scaler.assert_fitted_on("test")


def test_scaler_uses_training_statistics_only():
    # Training rows are 0..9; validation rows are wildly different. If the scaler
    # refitted on the full frame, the validation row would not be ~1.
    train = pd.DataFrame({"water_level": np.arange(10, dtype=float)})
    validation = pd.DataFrame({"water_level": [100.0]})
    scaler = StandardScaler().fit(train, ["water_level"], split_label="train")
    out = scaler.transform(validation, ["water_level"])
    expected = (100.0 - 4.5) / float(np.std(np.arange(10, dtype=float), ddof=0))
    assert out["water_level"].iloc[0] == pytest.approx(expected)
    # ... and it is far from the 0 a full-frame fit would have produced.
    assert out["water_level"].iloc[0] > 5.0


def test_scaler_handles_a_constant_column_without_producing_nan():
    train = pd.DataFrame({"water_level": np.full(10, 7.0)})
    scaler = StandardScaler().fit(train, ["water_level"], split_label="train")
    out = scaler.transform(pd.DataFrame({"water_level": [7.0, 9.0]}), ["water_level"])
    assert np.isfinite(out["water_level"].to_numpy()).all()
    assert out["water_level"].iloc[0] == pytest.approx(0.0)


def test_scaler_transform_matrix_rejects_wrong_width():
    train = _frame(20)
    scaler = StandardScaler().fit(train, ["water_level"], split_label="train")
    with pytest.raises(PreprocessError, match="column"):
        scaler.transform_matrix(np.zeros((3, 2)), ["water_level"])


def test_imputer_uses_training_median_only():
    train = pd.DataFrame({"water_level": [1.0, 2.0, 3.0, np.nan, 5.0]})
    validation = pd.DataFrame({"water_level": [np.nan, 100.0]})
    imputer = TrainFittedImputer("median").fit(train, ["water_level"], split_label="train")
    out = imputer.transform(validation, ["water_level"])
    # Training median (1,2,3,5 -> 2.5) is reused, not the validation median.
    assert out["water_level"].iloc[0] == pytest.approx(2.5)
    assert imputer.fitted_on == "train"
    assert imputer.strategy == "median"


def test_imputer_refits_are_rejected():
    frame = _frame()
    imputer = TrainFittedImputer()
    with pytest.raises(PreprocessError, match="only be fitted on the training split"):
        imputer.fit(frame, ["water_level"], split_label="test")
    with pytest.raises(PreprocessError, match="before fit"):
        imputer.transform(frame, ["water_level"])


def test_imputer_rejects_unknown_strategy():
    with pytest.raises(PreprocessError, match="unknown imputer strategy"):
        TrainFittedImputer("magic")


# --- end-to-end preparation --------------------------------------------------


def test_prepare_frame_runs_every_documented_step(demo_frame, demo_config):
    result = prepare_frame(demo_frame, demo_config)
    names = [step.name for step in result.steps]
    assert names == [
        "validate_columns",
        "reject_non_finite",
        "parse_timestamps",
        "sort_chronologically",
        "apply_missing_policy",
    ]
    assert result.sampling_interval == "1h"
    assert result.frame["timestamp"].is_monotonic_increasing
    assert result.step_log()  # a printable log exists for every run


def test_prepare_frame_dedupes_and_reports(demo_frame, demo_config):
    doubled = pd.concat([demo_frame, demo_frame.tail(10)], ignore_index=True)
    result = prepare_frame(doubled, demo_config)
    assert result.duplicate_report is not None
    assert result.duplicate_report.has_duplicates is True
    assert "resolve_duplicates" in [step.name for step in result.steps]
    assert result.frame["timestamp"].is_monotonic_increasing


def test_prepare_frame_can_refuse_duplicates_instead(demo_frame, demo_config):
    doubled = pd.concat([demo_frame, demo_frame.tail(10)], ignore_index=True)
    with pytest.raises(PreprocessError, match="duplicated timestamp"):
        prepare_frame(doubled, demo_config, resolve_duplicate_timestamps=False)


def test_prepare_frame_rejects_a_frame_missing_the_target(demo_frame, demo_config):
    with pytest.raises(PreprocessError, match="required column"):
        prepare_frame(demo_frame.drop(columns=["water_level"]), demo_config)


def test_prepare_frame_rejects_unparseable_timestamps(demo_frame, demo_config):
    """A corrupt timestamp must stop the pipeline, not be silently coerced.

    The column is rebuilt as `object` first: pandas refuses to store a string in
    a `datetime64` column at all, so corrupting one in place is not possible and
    the realistic case (a CSV read that kept a bad row as text) has to be
    constructed directly.
    """
    stamps = demo_frame["timestamp"].astype("object")
    stamps.iloc[10] = "yesterday"
    broken = demo_frame.assign(timestamp=stamps)
    with pytest.raises(PreprocessError, match="could not be parsed"):
        prepare_frame(broken, demo_config)


def test_prepare_frame_rejects_a_column_that_is_not_datetime_like(demo_frame, demo_config):
    """A whole column of non-dates is a different failure from one bad row, and
    must be reported the same way rather than escaping as a pandas internal."""
    stamps = pd.Series(["yesterday"] * len(demo_frame), index=demo_frame.index, dtype="object")
    broken = demo_frame.assign(timestamp=stamps)
    with pytest.raises(PreprocessError, match="could not be parsed"):
        prepare_frame(broken, demo_config)
