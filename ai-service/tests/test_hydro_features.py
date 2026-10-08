# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform . It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Tests for `app.engines.hydro.features`.

All inputs are SYNTHETIC/DEMO data. The subject of every test is *provenance of
a feature value*: which rows a feature is allowed to see, and that the
documentation matches the arithmetic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engines.hydro.config import FeatureSpec, HydroConfig, TargetSpec
from app.engines.hydro.features import (
    FeatureError,
    build_features,
    build_supervised,
    lead_time_rows_for,
)


def _small_frame(rows: int = 200) -> pd.DataFrame:
    stamps = pd.date_range("2024-03-01", periods=rows, freq="h")
    index = np.arange(rows, dtype=float)
    return pd.DataFrame(
        {
            "timestamp": stamps,
            "water_level": 3.0 + 0.01 * index + 0.3 * np.sin(index / 5.0),
            "rainfall_mm": np.abs(2.0 * np.cos(index / 3.0)),
            "upstream_level": 1.5 + 0.005 * index,
        }
    )


def _config(**overrides) -> HydroConfig:
    base = HydroConfig(
        target=TargetSpec(column="water_level", units="m", horizon_hours=2),
        features=FeatureSpec(
            max_lag=3,
            rolling_windows=(3, 6),
            exogenous_columns=("upstream_level",),
            rainfall_column="rainfall_mm",
        ),
    )
    return base.with_overrides(**overrides) if overrides else base


# --- feature construction ----------------------------------------------------


def test_features_contain_exactly_the_planned_columns():
    frame = _small_frame()
    features, plan = build_features(frame, _config())
    assert list(features.columns) == list(frame.columns) + list(plan.names)
    assert set(plan.names).isdisjoint(frame.columns)


def test_every_feature_is_documented():
    _, plan = build_features(_small_frame(), _config())
    assert len(plan.entries) == len(plan.names)
    for entry in plan.entries:
        assert entry.name
        assert entry.group
        assert entry.source_column
        assert entry.description, f"{entry.name} has no description"
    described = plan.describe()
    assert "lead time" in described
    assert "water_level_lag1" in described


def test_feature_groups_cover_lag_rolling_calendar_exogenous_rainfall():
    _, plan = build_features(_small_frame(), _config())
    groups = {entry.group for entry in plan.entries}
    assert groups == {"lag", "rolling", "calendar", "exogenous", "rainfall"}


def test_source_columns_are_the_real_columns_only():
    frame = _small_frame()
    _, plan = build_features(frame, _config())
    allowed = set(frame.columns)
    for entry in plan.entries:
        assert entry.source_column in allowed


def test_no_invented_column_when_rainfall_is_absent():
    frame = _small_frame().drop(columns=["rainfall_mm"])
    config = _config().with_overrides(
        features=FeatureSpec(max_lag=2, rolling_windows=(3,), rainfall_column=None)
    )
    _, plan = build_features(frame, config)
    assert "rainfall_mm" not in plan.source_columns
    assert all("rainfall" not in name for name in plan.names)
    assert not any(entry.group == "rainfall" for entry in plan.entries)


def test_missing_configured_rainfall_column_is_refused():
    frame = _small_frame().drop(columns=["rainfall_mm"])
    with pytest.raises(FeatureError, match="rainfall column"):
        build_features(frame, _config())


def test_missing_exogenous_column_is_refused():
    frame = _small_frame().drop(columns=["upstream_level"])
    with pytest.raises(FeatureError, match="exogenous"):
        build_features(frame, _config())


# --- the arithmetic itself ---------------------------------------------------


def test_lag_features_are_strictly_past():
    frame = _small_frame()
    features, _ = build_features(frame, _config())
    for lag in (1, 2, 3):
        expected = frame["water_level"].shift(lag)
        pd.testing.assert_series_equal(
            features[f"water_level_lag{lag}"], expected, check_names=False
        )


def test_rolling_features_exclude_the_current_row():
    frame = _small_frame()
    features, _ = build_features(frame, _config())
    window = 6
    # shift(1).rolling(w) must not include the value at t itself.
    expected = frame["water_level"].shift(1).rolling(window=window, min_periods=window).mean()
    pd.testing.assert_series_equal(
        features[f"water_level_roll{window}_mean"], expected, check_names=False
    )
    # Proof it is not the un-shifted version.
    unshifted = frame["water_level"].rolling(window=window, min_periods=window).mean()
    assert not np.allclose(
        features[f"water_level_roll{window}_mean"].to_numpy()[20:],
        unshifted.to_numpy()[20:],
        equal_nan=True,
    )


def test_rolling_max_and_min_bracket_the_past_window():
    frame = _small_frame()
    features, _ = build_features(frame, _config())
    for window in (3, 6):
        past = frame["water_level"].shift(1).rolling(window=window, min_periods=window)
        pd.testing.assert_series_equal(
            features[f"water_level_roll{window}_max"], past.max(), check_names=False
        )
        pd.testing.assert_series_equal(
            features[f"water_level_roll{window}_min"], past.min(), check_names=False
        )


def test_diff_feature_uses_only_the_past():
    frame = _small_frame()
    features, _ = build_features(frame, _config())
    expected = frame["water_level"].shift(1) - frame["water_level"].shift(2)
    pd.testing.assert_series_equal(features["water_level_diff1"], expected, check_names=False)


def test_rainfall_aggregates_are_shifted():
    frame = _small_frame()
    features, _ = build_features(frame, _config())
    expected = frame["rainfall_mm"].shift(1).rolling(window=3, min_periods=1).sum()
    pd.testing.assert_series_equal(features["rainfall_mm_roll3_sum"], expected, check_names=False)


def test_calendar_features_are_deterministic_in_the_timestamp():
    frame = _small_frame()
    features, _ = build_features(frame, _config())
    hour = frame["timestamp"].dt.hour.to_numpy(dtype=float)
    expected = np.sin(2.0 * np.pi * hour / 24.0)
    assert np.allclose(features["calendar_hour_sin"].to_numpy(), expected)


def test_feature_construction_preserves_row_order():
    frame = _small_frame()
    ordered, _ = build_features(frame, _config())
    assert ordered["timestamp"].tolist() == frame["timestamp"].tolist()


# --- supervised alignment ----------------------------------------------------


def test_supervised_pairs_features_at_t_with_target_at_t_plus_h():
    frame = _small_frame()
    config = _config()
    features, plan = build_features(frame, config)
    supervised = build_supervised(features, plan, config, lead_time_rows=4)
    assert supervised.n_samples == len(frame) - 4
    row = 10
    assert supervised.origin_timestamps.iloc[row] == frame["timestamp"].iloc[row]
    assert supervised.target_timestamps.iloc[row] == frame["timestamp"].iloc[row + 4]
    assert supervised.target[row] == pytest.approx(frame["water_level"].iloc[row + 4])


def test_supervised_target_is_strictly_in_the_future_of_its_features():
    frame = _small_frame()
    config = _config()
    features, plan = build_features(frame, config)
    supervised = build_supervised(features, plan, config, lead_time_rows=6)
    origins = supervised.origin_timestamps.to_numpy()
    targets = supervised.target_timestamps.to_numpy()
    assert (targets > origins).all()


def test_supervised_drops_the_tail_that_has_no_future_target():
    frame = _small_frame()
    config = _config()
    features, plan = build_features(frame, config)
    for lead in (1, 3, 7):
        supervised = build_supervised(features, plan, config, lead_time_rows=lead)
        assert supervised.n_samples == len(frame) - lead
        assert supervised.plan.dropped_rows == lead


def test_supervised_rejects_the_target_as_a_feature():
    frame = _small_frame()
    config = _config()
    features, plan = build_features(frame, config)
    poisoned = plan.__class__(
        entries=plan.entries + (plan.entries[0].__class__(
            name="water_level", group="raw", source_column="water_level",
            kind="leak", description="deliberate target leak for the test",
        ),),
        target_column=plan.target_column,
        rainfall_column=plan.rainfall_column,
        lead_time_rows=1,
    )
    with pytest.raises(FeatureError, match="target leakage"):
        build_supervised(features, poisoned, config, lead_time_rows=1)


def test_supervised_rejects_a_non_positive_lead_time():
    frame = _small_frame()
    config = _config()
    features, plan = build_features(frame, config)
    with pytest.raises(FeatureError, match="lead_time_rows"):
        build_supervised(features, plan, config, lead_time_rows=0)


# --- horizon conversion ------------------------------------------------------


@pytest.mark.parametrize(
    ("interval", "horizon_hours", "expected"),
    [
        ("1h", 6, 6),
        ("1h", 1, 1),
        ("30min", 3, 6),
        ("1D", 24, 1),   # daily data: one row spans the whole horizon
        ("1D", 48, 2),
        ("15min", 1, 4),
        ("30s", 1, 120),
        # A horizon shorter than the sampling interval still needs one row: a
        # lead time of zero rows would pair a row with itself, which is not a
        # forecast.
        ("6h", 1, 1),
    ],
)
def test_lead_time_rows_conversion(interval, horizon_hours, expected):
    from dataclasses import replace

    config = _config().with_overrides(
        target=replace(_config().target, horizon_hours=horizon_hours)
    )
    assert lead_time_rows_for(config, interval) == expected


def test_a_daily_interval_matches_what_the_inference_step_produces():
    """`infer_sampling_interval` emits '1D', and the horizon converter must read
    back exactly that spelling.

    Daily and multi-day records are ordinary hydrological data, and the two
    functions are the only places that know the format. If they disagree, a
    perfectly valid daily dataset is rejected by the pipeline's own output.
    """
    from dataclasses import replace

    from app.engines.hydro.preprocessing import infer_sampling_interval

    daily = pd.DataFrame(
        {"timestamp": pd.date_range("2024-01-01", periods=30, freq="D")}
    )
    interval = infer_sampling_interval(daily, "timestamp")
    assert interval == "1D"
    config = _config().with_overrides(
        target=replace(_config().target, horizon_hours=48)
    )
    assert lead_time_rows_for(config, interval) == 2

def test_lead_time_rows_refuses_when_interval_is_unknown():
    with pytest.raises(FeatureError, match="sampling interval is unknown"):
        lead_time_rows_for(_config(), None)


def test_lead_time_rows_rejects_an_unparseable_interval():
    with pytest.raises(FeatureError, match="unrecognised sampling interval"):
        lead_time_rows_for(_config(), "sometimes")


def test_a_bare_pandas_frequency_alias_is_refused_with_the_accepted_formats():
    """'D' is a pandas alias, not the documented duration spelling.

    It is rejected rather than guessed, and the message names the forms that
    work, because this value usually arrives from an operator setting
    HYDRO_SAMPLING_INTERVAL.
    """
    with pytest.raises(FeatureError) as excinfo:
        lead_time_rows_for(_config(), "D")
    message = str(excinfo.value)
    assert "expected a number followed by a unit" in message
    assert "'1D'" in message
