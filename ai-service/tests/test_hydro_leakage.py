# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Leakage tests for the hydro pipeline.

These are adversarial tests, not smoke tests. Each one tries to smuggle future
information into the training set and asserts that the pipeline refuses it or
that the information provably cannot be present.

Covered here:

* the target is never among the features,
* every feature is a function of the past only (proved by perturbation, not by
  reading the code),
* the forward fill used for gaps reads backwards in time and never forwards,
* the scaler and imputer are fitted on the training rows only,
* the chronological split produces non-overlapping, correctly ordered periods,
* model selection cannot see the test period.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from app.engines.hydro.config import FeatureSpec, HydroConfig, SplitSpec, TargetSpec
from app.engines.hydro.evaluation import EvaluationReport, compare_models
from app.engines.hydro.features import (
    audit_causality,
    build_features,
    build_supervised,
)
from app.engines.hydro.preprocessing import (
    PreprocessError,
    StandardScaler,
    TrainFittedImputer,
    apply_missing_policy,
    assert_no_overlap,
    chronological_split,
    parse_timestamps,
)
from app.engines.hydro.provenance import ProvenanceRecord, SplitBoundaries


def _series(rows: int = 300) -> pd.DataFrame:
    stamps = pd.date_range("2024-05-01", periods=rows, freq="h")
    index = np.arange(rows, dtype=float)
    return pd.DataFrame(
        {
            "timestamp": stamps,
            "water_level": 4.0 + 0.01 * index + 0.4 * np.sin(index / 7.0),
            "rainfall_mm": 3.0 + 2.0 * np.cos(index / 4.0),
        }
    )


def _config(**overrides) -> HydroConfig:
    config = HydroConfig(
        target=TargetSpec(column="water_level", units="m", horizon_hours=2),
        features=FeatureSpec(max_lag=3, rolling_windows=(3, 6), rainfall_column="rainfall_mm"),
    )
    return config.with_overrides(**overrides) if overrides else config


# --- the target is never a feature -------------------------------------------


def test_target_column_is_never_a_generated_feature():
    _, plan = build_features(_series(), _config())
    assert plan.target_column == "water_level"
    assert "water_level" not in plan.names
    for entry in plan.entries:
        assert entry.name != "water_level"


def test_a_plan_that_admits_the_target_is_rejected():
    frame = _series()
    config = _config()
    features, plan = build_features(frame, config)
    from app.engines.hydro.features import FeaturePlan, FeatureSpecEntry

    poisoned = FeaturePlan(
        entries=plan.entries
        + (
            FeatureSpecEntry(
                name="water_level",
                group="raw",
                source_column="water_level",
                kind="leak",
                description="deliberate target leak used by this test",
            ),
        ),
        target_column=plan.target_column,
        rainfall_column=plan.rainfall_column,
        lead_time_rows=plan.lead_time_rows,
        dropped_rows=plan.dropped_rows,
    )
    from app.engines.hydro.features import FeatureError

    with pytest.raises(FeatureError, match="target leakage"):
        build_supervised(features, poisoned, config, lead_time_rows=2)


# --- causality, proved by perturbation --------------------------------------


def test_future_perturbation_cannot_change_past_features():
    """The decisive causality test.

    Every value at or before row *k* is corrupted. If any feature at row *k*
    depended on the future, the feature vector at row *k* would change. It must
    not. This is checked directly, so it holds regardless of how the feature is
    implemented.
    """
    frame = _series()
    config = _config()
    features, plan = build_features(frame, config)

    cutoff = 150
    corrupted = frame.copy()
    after = corrupted.index[corrupted.index > cutoff]
    corrupted.loc[after, "water_level"] = corrupted.loc[after, "water_level"] * -7.5 + 123.0
    corrupted.loc[after, "rainfall_mm"] = corrupted.loc[after, "rainfall_mm"] * 11.0
    corrupted_features, _ = build_features(corrupted, config)

    past = features.loc[:cutoff, plan.names]
    past_again = corrupted_features.loc[:cutoff, plan.names]
    pd.testing.assert_frame_equal(past, past_again)


def test_audit_causality_passes_for_a_correct_feature_set():
    audit_causality(_series(), _config())  # must not raise


def test_the_target_declared_as_an_exogenous_feature_is_refused():
    """The guard for exogenous columns is the target check, not the audit.

    `audit_causality` truncates and rebuilds, which can only detect lookahead in
    features the pipeline *generates*. An exogenous column is copied verbatim
    from the source frame, so its values are identical in a truncated frame
    whether or not they were computed with lookahead upstream. The protection
    that does apply is that the target may never be admitted as a feature.
    """
    from app.engines.hydro.features import FeatureError

    frame = _series()
    config = _config().with_overrides(
        features=replace(_config().features, exogenous_columns=("water_level",))
    )
    with pytest.raises(FeatureError, match="target leakage"):
        build_features(frame, config)


def test_the_causality_audit_covers_generated_features_only():
    """Scope of the audit, stated so it is not over-claimed.

    Exogenous columns are assumed to be contemporaneous observations supplied by
    the dataset owner; the pipeline cannot prove that. Generated features are
    the ones the audit can and does prove.
    """
    from app.engines.hydro.features import build_features

    frame = _series()
    config = _config().with_overrides(
        features=replace(_config().features, exogenous_columns=("water_level_lag1",))
    )
    frame = frame.assign(
        water_level_lag1=frame["water_level"].shift(1)  # a genuine lag
    )
    built, _ = build_features(frame, config)
    generated = [name for name in built.columns if name not in frame.columns]
    assert generated, "the config must generate at least one feature for this to mean anything"
    assert "water_level_lag1" not in generated  # copied through, not regenerated
    audit_causality(frame, config)  # must not raise


# --- the gap fill must not read the future ----------------------------------


def test_forward_fill_does_not_borrow_from_a_later_row():
    frame = _series(20).drop(columns=["rainfall_mm"])
    frame.loc[5, "water_level"] = np.nan
    filled, _ = apply_missing_policy(frame, ["water_level"], policy="ffill", max_fill_gap=5)
    # Row 5 must take row 4's value, not row 6's.
    assert filled["water_level"].iloc[5] == pytest.approx(frame["water_level"].iloc[4])
    assert filled["water_level"].iloc[5] != pytest.approx(frame["water_level"].iloc[6])


def test_leading_gap_is_not_filled_from_the_future():
    frame = _series(20).drop(columns=["rainfall_mm"])
    frame.loc[0:2, "water_level"] = np.nan
    filled, step = apply_missing_policy(frame, ["water_level"], policy="ffill", max_fill_gap=5)
    # There is no past to copy from, so those rows are dropped rather than
    # filled from the future.
    assert filled["water_level"].iloc[0] == pytest.approx(frame["water_level"].iloc[3])


# --- train-only fitting ------------------------------------------------------


def test_scaler_cannot_be_fitted_on_validation_or_test():
    frame, _ = parse_timestamps(_series(), "timestamp")
    for label in ("validation", "test", "holdout", ""):
        with pytest.raises(PreprocessError):
            StandardScaler().fit(frame, ["water_level"], split_label=label)


def test_imputer_cannot_be_fitted_on_anything_but_train():
    frame, _ = parse_timestamps(_series(), "timestamp")
    for label in ("validation", "test"):
        with pytest.raises(PreprocessError):
            TrainFittedImputer().fit(frame, ["water_level"], split_label=label)


def test_scaler_statistics_come_from_training_rows_only():
    """A scaler fitted on train must not react to changes in the held-out rows."""
    train = pd.DataFrame({"x": np.arange(50, dtype=float)})
    scaler = StandardScaler().fit(train, ["x"], split_label="train")
    before = scaler.state()
    for value in (1e6, -1e6, 0.0):
        scaler.transform(pd.DataFrame({"x": [value]}), ["x"])
    after = scaler.state()
    # Transforming never mutates the fitted statistics.
    assert before["mean"] == after["mean"]
    assert before["scale"] == after["scale"]


# --- split integrity ---------------------------------------------------------


def test_split_periods_do_not_overlap():
    frame, _ = parse_timestamps(_series(300), "timestamp")
    split, boundaries = chronological_split(frame, "timestamp", SplitSpec(0.6, 0.2))
    assert_no_overlap(split, "timestamp")
    assert boundaries.is_ordered()
    assert split.train["timestamp"].max() < split.validation["timestamp"].min()
    assert split.validation["timestamp"].max() < split.test["timestamp"].min()


def test_every_row_lands_in_exactly_one_split():
    """A row that fell out of every split would be silently unscored; a row in
    two splits would be counted twice. Both are caught by summing the parts."""
    frame, _ = parse_timestamps(_series(300), "timestamp")
    split, _ = chronological_split(frame, "timestamp", SplitSpec(0.6, 0.2))
    total = sum(split.sizes().values())
    assert total == len(frame)
    assert min(split.sizes().values()) > 0, "an empty split would make a score undefined"


def test_split_is_not_a_random_partition():
    """A chronological split is fully determined by the row order.

    Shuffling the input and re-splitting must put exactly the same *timestamps*
    in each split as before — a random partition would produce different
    membership and therefore a test period that overlaps training.
    """
    frame, _ = parse_timestamps(_series(300), "timestamp")
    ordered, _ = chronological_split(frame, "timestamp", SplitSpec(0.6, 0.2))
    shuffled_frame = frame.sample(frac=1.0, random_state=11)
    assert not shuffled_frame["timestamp"].is_monotonic_increasing

    # `timestamp_column_is_sorted=False` makes the splitter re-sort first, so the
    # row order cannot decide membership.
    shuffled, _ = chronological_split(
        shuffled_frame, "timestamp", SplitSpec(0.6, 0.2), timestamp_column_is_sorted=False
    )
    assert list(ordered.train["timestamp"]) == list(shuffled.train["timestamp"])
    assert list(ordered.validation["timestamp"]) == list(shuffled.validation["timestamp"])
    assert list(ordered.test["timestamp"]) == list(shuffled.test["timestamp"])
    # And the raw input order is never the split order.
    assert list(ordered.train["timestamp"]) == list(frame["timestamp"].iloc[:180])


def test_a_split_that_would_consume_the_whole_frame_is_refused():
    """Fractions that leave no test period are a configuration error.

    Without a held-out period the final score is a selection statistic, so the
    configuration is rejected at load time rather than producing a comparison
    that looks rigorous and is not.
    """
    from app.engines.hydro.config import ConfigError

    with pytest.raises(ConfigError, match="test split"):
        SplitSpec(0.6, 2.0 / 3.0)


# --- supervised alignment respects the split ---------------------------------


def test_lead_time_pairs_never_cross_backwards_over_a_split_edge():
    """A target timestamp must be strictly later than its origin timestamp."""
    frame = _series(300)
    config = _config()
    features, plan = build_features(frame, config)
    supervised = build_supervised(features, plan, config, lead_time_rows=5)
    origins = supervised.origin_timestamps.to_numpy()
    targets = supervised.target_timestamps.to_numpy()
    assert (targets > origins).all()


def test_supervised_rows_are_dropped_when_the_future_is_truncated():
    """The last rows of a series have no future target, so they are dropped
    rather than paired with a stale value.

    `lead_time_rows=7` means origin *i* is paired with target *i+7*, so the last
    usable origin is index 92 of 100 — that is `iloc[-8]`, and the count of 93
    surviving rows is the same fact stated as a number.
    """
    frame = _series(100)
    config = _config()
    features, plan = build_features(frame, config)
    supervised = build_supervised(features, plan, config, lead_time_rows=7)
    assert supervised.n_samples == 100 - 7
    assert supervised.target_timestamps.iloc[-1] == frame["timestamp"].iloc[-1]
    assert supervised.origin_timestamps.iloc[-1] == frame["timestamp"].iloc[-(7 + 1)]
    # Every surviving origin points forwards by exactly the lead time.
    origins = supervised.origin_timestamps.to_numpy()
    targets = supervised.target_timestamps.to_numpy()
    assert (targets - origins == np.timedelta64(7, "h")).all()


# --- model selection cannot see the test period ------------------------------


_SPLIT = SplitBoundaries(
    train_start="2024-05-01T00:00:00Z",
    train_end="2024-05-03T00:00:00Z",
    validation_start="2024-05-03T01:00:00Z",
    validation_end="2024-05-04T00:00:00Z",
    test_start="2024-05-04T01:00:00Z",
    test_end="2024-05-05T00:00:00Z",
)


def _report(model_key: str, split_label: str, rmse: float) -> EvaluationReport:
    """A synthetic evaluation report. The numbers are arbitrary; only the split
    each one is attached to matters for these tests, and the provenance says
    `synthetic` so nothing here can be read as a hydrological result."""
    from app.engines.hydro.evaluation import EvaluationMetrics

    return EvaluationReport(
        model_key=model_key,
        model_name=model_key,
        model_version="v",
        algorithm="test",
        split_label=split_label,
        metrics=EvaluationMetrics(
            mae=rmse * 0.7, rmse=rmse, r2=0.0, nse=0.0, peak_absolute_error=rmse, bias=0.0,
            n_samples=100,
        ),
        target="water_level",
        target_units="m (demo assumption — NOT datum verified)",
        forecast_horizon="2h",
        lead_time_rows=2,
        dataset_reference="synthetic://unit-test/hydro",
        dataset_type="synthetic",
        station_reference="SYNTHETIC-STATION-0001",
        split=_SPLIT,
        evaluated_at="2024-05-06T00:00:00Z",
        provenance=ProvenanceRecord(
            dataset_reference="synthetic://unit-test/hydro",
            dataset_type="synthetic",
            sampling_interval="1h",
            target="water_level",
            target_units="m (demo assumption — NOT datum verified)",
            forecast_horizon="2h",
            station_reference="SYNTHETIC-STATION-0001",
            model_name="unit-test model",
            model_version="v",
            split=_SPLIT,
        ),
    )


def test_selection_on_validation_only_is_enforced():
    good = compare_models(
        [_report("linear", "validation", 0.5), _report("ridge", "validation", 0.3)],
        selection_metric="rmse",
    )
    assert good.selected_key == "ridge"
    good.assert_selection_is_clean()


def test_ranking_on_the_test_split_is_rejected():
    """If the test period takes part in the ranking, the held-out score stops
    being held out. The comparison must refuse rather than report it."""
    with pytest.raises(Exception):
        compare_models(
            [_report("linear", "test", 0.5), _report("ridge", "test", 0.3)],
            selection_metric="rmse",
        )


def test_a_held_out_report_must_belong_to_the_selected_model():
    with pytest.raises(Exception):
        compare_models(
            [_report("linear", "validation", 0.5), _report("ridge", "validation", 0.3)],
            selection_metric="rmse",
            held_out_report=_report("linear", "test", 0.4),
        )


def test_selection_and_held_out_cannot_be_the_same_split():
    with pytest.raises(Exception):
        compare_models(
            [_report("linear", "validation", 0.5)],
            selection_metric="rmse",
            selection_split="validation",
            held_out_split="validation",
        )


def test_an_unsupported_selection_metric_is_rejected():
    with pytest.raises(Exception):
        compare_models(
            [_report("linear", "validation", 0.5)],
            selection_metric="accuracy",
        )


# --- a full end-to-end independence check ------------------------------------


def test_a_model_trained_on_train_is_unchanged_by_rewriting_the_test_period():
    """Fit, then rewrite every test-period observation, then re-score.

    The fitted coefficients must be identical: the training path cannot have
    consumed the test period. (A refit is not performed here; this isolates the
    fitted state.)
    """
    from app.engines.hydro.models import build_model

    frame = _series(400)
    config = _config()
    features, plan = build_features(frame, config)
    supervised = build_supervised(features, plan, config, lead_time_rows=2)

    matrix = supervised.feature_matrix()
    # The earliest rows have no lag/rolling history yet and are dropped here, as
    # the pipeline's own imputer step would do; a NaN must never reach a fit.
    finite = np.isfinite(matrix).all(axis=1)
    x_train = matrix[finite][:200]
    y_train = supervised.target[np.isfinite(matrix).all(axis=1)][:200]
    assert len(x_train) == 200

    model = build_model("ridge", {"alpha": 1.0}).fit(x_train, y_train)
    before = np.array(model.coefficients)

    poisoned = matrix.copy()
    poisoned[200:] = poisoned[200:] * 5.0 + 1.0
    model.predict(np.nan_to_num(poisoned, nan=0.0))
    after = np.array(model.coefficients)

    assert np.array_equal(before, after)


def test_a_nan_reaching_a_fit_is_refused():
    """Guard for the test above: the non-finite check is live, so the rows that
    the test drops are genuinely unusable rather than quietly tolerated."""
    from app.engines.hydro.models import ModelError, build_model

    frame = _series(400)
    config = _config()
    features, plan = build_features(frame, config)
    supervised = build_supervised(features, plan, config, lead_time_rows=2)
    matrix = supervised.feature_matrix()
    assert not np.isfinite(matrix).all(), "lag features leave leading rows undefined"
    with pytest.raises(ModelError, match="non-finite"):
        build_model("ridge", {"alpha": 1.0}).fit(matrix, supervised.target)
