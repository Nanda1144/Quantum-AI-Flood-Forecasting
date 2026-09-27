# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Tests for `app.engines.hydro.evaluation`.

Every number asserted here is computed from an explicitly constructed array pair
in the test body. No expected metric is copied from a previous run, and none of
these tests asserts a hydrological result: the arrays are toy numbers used to
check the arithmetic of the metric functions.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from app.engines.hydro import training
from app.engines.hydro.evaluation import (
    HELD_OUT_SPLIT,
    SELECTION_SPLIT,
    SUPPORTED_METRICS,
    TRAIN_SPLIT,
    EvaluationError,
    EvaluationMetrics,
    EvaluationReport,
    bias,
    build_comparison_disclaimer,
    coefficient_of_determination,
    compare_models,
    compute_metrics,
    mean_absolute_error,
    nash_sutcliffe_efficiency,
    peak_absolute_error,
    root_mean_squared_error,
    selection_policy_note,
)
from app.engines.hydro.provenance import ProvenanceRecord, SplitBoundaries


# --- closed-form values ------------------------------------------------------


def test_mae_of_a_known_pair():
    assert mean_absolute_error([1.0, 2.0, 3.0], [1.0, 4.0, 0.0]) == pytest.approx(5.0 / 3.0)


def test_rmse_of_a_known_pair():
    assert root_mean_squared_error([0.0, 0.0], [3.0, 4.0]) == pytest.approx(np.sqrt(12.5))


def test_mae_and_rmse_are_zero_for_a_perfect_forecast():
    actual = [1.0, 5.0, -2.0, 8.0]
    assert mean_absolute_error(actual, actual) == pytest.approx(0.0)
    assert root_mean_squared_error(actual, actual) == pytest.approx(0.0)
    assert bias(actual, actual) == pytest.approx(0.0)
    assert peak_absolute_error(actual, actual) == pytest.approx(0.0)


def test_r_squared_is_one_for_a_perfect_forecast():
    actual = [1.0, 5.0, -2.0, 8.0, 3.0]
    assert coefficient_of_determination(actual, actual) == pytest.approx(1.0)


def test_r_squared_is_zero_at_the_mean():
    actual = [1.0, 2.0, 3.0, 4.0]
    predicted = [np.mean(actual)] * 4
    assert coefficient_of_determination(actual, predicted) == pytest.approx(0.0)


def test_r_squared_is_negative_when_worse_than_the_mean():
    actual = [1.0, 2.0, 3.0, 4.0]
    assert coefficient_of_determination(actual, [9.0, 9.0, 9.0, 9.0]) < 0.0


def test_nse_matches_r_squared_against_the_mean_baseline():
    actual = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
    predicted = [2.5, 1.5, 4.5, 2.0, 5.5, 8.0, 3.0, 5.0]
    assert nash_sutcliffe_efficiency(actual, predicted) == pytest.approx(
        coefficient_of_determination(actual, predicted)
    )


def test_nse_is_one_for_a_perfect_forecast():
    actual = [1.0, 2.0, 3.0]
    assert nash_sutcliffe_efficiency(actual, actual) == pytest.approx(1.0)


def test_bias_sign_follows_the_prediction_offset():
    assert bias([1.0, 2.0, 3.0], [2.0, 3.0, 4.0]) == pytest.approx(1.0)  # over-forecasting
    assert bias([1.0, 2.0, 3.0], [0.0, 1.0, 2.0]) == pytest.approx(-1.0)  # under-forecasting


def test_peak_absolute_error_finds_the_worst_row():
    assert peak_absolute_error([1.0, 2.0, 3.0], [1.0, 2.0, 9.0]) == pytest.approx(6.0)


# --- the metric bundle -------------------------------------------------------


def test_compute_metrics_returns_every_regression_metric():
    actual = [1.0, 2.0, 3.0, 4.0, 5.0]
    predicted = [1.2, 1.8, 3.4, 3.6, 5.5]
    metrics = compute_metrics(actual, predicted)
    assert metrics.n_samples == 5
    assert metrics.mae == pytest.approx(mean_absolute_error(actual, predicted))
    assert metrics.rmse == pytest.approx(root_mean_squared_error(actual, predicted))
    assert metrics.r2 == pytest.approx(coefficient_of_determination(actual, predicted))
    assert metrics.nse == pytest.approx(nash_sutcliffe_efficiency(actual, predicted))
    assert metrics.peak_absolute_error == pytest.approx(peak_absolute_error(actual, predicted))
    assert metrics.bias == pytest.approx(bias(actual, predicted))


def test_regression_metrics_contain_no_classification_scores():
    """Accuracy / precision / recall / F1 are deliberately absent.

    A regression forecast has no class labels, so reporting a classification
    score would be meaningless. `as_dict()` is asserted to have no such key so a
    later change cannot quietly reintroduce one.
    """
    metrics = compute_metrics([1.0, 2.0, 3.0], [1.1, 2.2, 2.8])
    keys = set(metrics.as_dict())
    for forbidden in ("accuracy", "precision", "recall", "f1", "f1_score"):
        assert forbidden not in keys
    # The serialised bundle is exactly the six computed scores. `n_samples` is a
    # count, not a score, so it is a dataclass field but not a reported metric —
    # a reader must not be able to mistake it for one.
    assert keys == {"mae", "rmse", "r2", "nse", "peak_absolute_error", "bias"}
    assert "n_samples" not in keys
    assert metrics.n_samples == 3


def test_metrics_reject_mismatched_lengths():
    with pytest.raises(EvaluationError):
        compute_metrics([1.0, 2.0, 3.0], [1.0, 2.0])


def test_metrics_reject_empty_input():
    with pytest.raises(EvaluationError):
        compute_metrics([], [])


def test_metrics_reject_non_finite_values():
    with pytest.raises(EvaluationError):
        compute_metrics([1.0, 2.0], [1.0, float("nan")])


def test_a_constant_actual_series_reports_zero_variance_scores():
    """A zero-variance baseline makes R² and NSE undefined.

    The module's documented choice is to report 0.0 — "explained nothing" —
    rather than NaN, ±inf, or a confident 1.0. The error metrics are still
    meaningful, so they are asserted separately to show the undefined pair is
    isolated to the two ratio metrics.
    """
    metrics = compute_metrics([5.0, 5.0, 5.0], [5.0, 5.0, 5.0])
    assert metrics.r2 == pytest.approx(0.0)
    assert metrics.nse == pytest.approx(0.0)
    assert metrics.mae == pytest.approx(0.0)
    assert metrics.rmse == pytest.approx(0.0)
    # A perfect forecast of a constant series must not be reported as R² = 1.0:
    # there is no variance to explain, so 1.0 would be an invented result.
    assert metrics.r2 != pytest.approx(1.0)


def test_score_dispatches_on_the_metric_name():
    metrics = compute_metrics([1.0, 2.0, 3.0], [1.0, 2.5, 3.2])
    assert metrics.score("rmse") == pytest.approx(metrics.rmse)
    assert metrics.score("mae") == pytest.approx(metrics.mae)
    assert metrics.score("r2") == pytest.approx(metrics.r2)
    assert metrics.score("nse") == pytest.approx(metrics.nse)
    with pytest.raises(EvaluationError):
        metrics.score("accuracy")


def test_supported_metrics_are_only_the_regression_ones():
    assert set(SUPPORTED_METRICS) == {"rmse", "mae", "r2", "nse"}


# --- comparison --------------------------------------------------------------


def _provenance() -> "ProvenanceRecord":
    """Synthetic provenance, so every report built here is auto-labelled.

    The numbers in these reports are toy values used to check the comparison
    logic. They are never presented as a hydrological result: the record says
    `synthetic`, and the table repeats the label on every row.
    """
    return ProvenanceRecord(
        dataset_reference="synthetic://unit-test/hydro",
        dataset_type="synthetic",
        sampling_interval="1h",
        target="water_level",
        target_units="m (demo assumption — NOT datum verified)",
        forecast_horizon="2h",
        station_reference="SYNTHETIC-STATION-0001",
        model_name="unit-test model",
        model_version="v1",
        split=SplitBoundaries(
            train_start="2024-01-01T00:00:00Z",
            train_end="2024-01-10T00:00:00Z",
            validation_start="2024-01-11T00:00:00Z",
            validation_end="2024-01-15T00:00:00Z",
            test_start="2024-01-16T00:00:00Z",
            test_end="2024-01-20T00:00:00Z",
            train_rows=100,
            validation_rows=50,
            test_rows=50,
        ),
    )


def _report(model_key: str, split_label: str, rmse: float) -> "EvaluationReport":
    return EvaluationReport(
        model_key=model_key,
        model_name=model_key,
        model_version="v1",
        algorithm="test",
        split_label=split_label,
        metrics=EvaluationMetrics(
            mae=rmse * 0.7, rmse=rmse, r2=0.5, nse=0.5,
            peak_absolute_error=rmse * 2.0, bias=0.0, n_samples=50,
        ),
        target="water_level",
        target_units="m (demo assumption — NOT datum verified)",
        forecast_horizon="2h",
        lead_time_rows=2,
        dataset_reference="synthetic://unit-test/hydro",
        dataset_type="synthetic",
        station_reference="SYNTHETIC-STATION-0001",
        split=SplitBoundaries(
            train_start="2024-01-01T00:00:00Z",
            train_end="2024-01-10T00:00:00Z",
            validation_start="2024-01-11T00:00:00Z",
            validation_end="2024-01-15T00:00:00Z",
            test_start="2024-01-16T00:00:00Z",
            test_end="2024-01-20T00:00:00Z",
        ),
        evaluated_at="2024-01-21T00:00:00Z",
        provenance=_provenance(),
        feature_list=("water_level_lag1",),
    )


def test_comparison_ranks_lowest_error_first():
    comparison = compare_models(
        [
            _report("linear", "validation", 0.9),
            _report("ridge", "validation", 0.4),
            _report("lgbm", "validation", 0.7),
        ],
        selection_metric="rmse",
    )
    assert [r.model_key for r in comparison.reports] == ["ridge", "lgbm", "linear"]
    assert comparison.selected_key == "ridge"


def test_ranking_on_a_skill_metric_selects_the_highest():
    """`higher_is_better` must genuinely reverse the order, otherwise selecting
    on R² would pick the worst model while reporting a confident comparison."""
    good = _report("good", "validation", 0.5)
    bad = _report("bad", "validation", 0.5)
    # r2 = 0.9 for the good model, 0.1 for the bad one; the RMSE tiebreak that
    # orders equal errors must not decide this.
    good = replace(good, metrics=replace(good.metrics, r2=0.9, nse=0.9))
    bad = replace(bad, metrics=replace(bad.metrics, r2=0.1, nse=0.1))
    comparison = compare_models(
        [good, bad], selection_metric="r2", higher_is_better=True
    )
    assert comparison.selected_key == "good"
    assert [r.model_key for r in comparison.reports] == ["good", "bad"]


def test_a_ranking_that_mixed_in_the_test_split_is_rejected():
    """The core anti-leakage guarantee: a candidate scored on the held-out split
    must not be rankable, or the held-out figure becomes a selection statistic."""
    with pytest.raises(EvaluationError) as excinfo:
        compare_models([_report("ridge", "test", 0.3)], selection_metric="rmse")
    assert "validation" in str(excinfo.value)


def test_a_held_out_score_for_a_model_that_did_not_win_is_rejected():
    with pytest.raises(EvaluationError) as excinfo:
        compare_models(
            [_report("linear", "validation", 0.5), _report("ridge", "validation", 0.3)],
            selection_metric="rmse",
            held_out_report=_report("linear", "test", 0.45),
        )
    assert "selected model" in str(excinfo.value)


def test_selection_and_held_out_cannot_be_the_same_split():
    with pytest.raises(EvaluationError) as excinfo:
        compare_models(
            [_report("ridge", "validation", 0.3)],
            selection_metric="rmse",
            selection_split="validation",
            held_out_split="validation",
        )
    assert "selection statistic" in str(excinfo.value)


def test_an_unknown_selection_metric_is_refused():
    """A metric this module does not compute must not be used to rank models."""
    with pytest.raises(EvaluationError) as excinfo:
        compare_models([_report("ridge", "validation", 0.3)], selection_metric="accuracy")
    assert "accuracy" in str(excinfo.value)


def test_comparison_of_nothing_selects_nothing():
    comparison = compare_models([], selection_metric="rmse")
    assert comparison.selected_key is None
    assert comparison.reports == ()
    assert "no candidate model was evaluated" in comparison.table()


def test_comparison_reports_a_held_out_score_separately():
    comparison = compare_models(
        [_report("linear", "validation", 0.5), _report("ridge", "validation", 0.3)],
        selection_metric="rmse",
        held_out_report=_report("ridge", "test", 0.45),
    )
    assert "validation" in comparison.table()
    assert "test" in comparison.held_out_table()
    assert comparison.held_out_report is not None
    assert comparison.held_out_report.metrics.rmse == pytest.approx(0.45)


def test_held_out_table_says_so_when_absent():
    comparison = compare_models([_report("linear", "validation", 0.5)])
    assert "no held-out score" in comparison.held_out_table()


def test_comparison_records_unevaluated_and_unavailable_models():
    comparison = compare_models(
        [_report("linear", "validation", 0.5)],
        unevaluated_keys=("xgboost",),
        unavailable={"xgboost": "xgboost.XGBRegressor"},
    )
    assert comparison.unevaluated_keys == ("xgboost",)
    assert comparison.unavailable == {"xgboost": "xgboost.XGBRegressor"}


def test_comparison_serialises_the_full_protocol():
    comparison = compare_models(
        [_report("ridge", "validation", 0.3)],
        selection_metric="rmse",
        held_out_report=_report("ridge", "test", 0.4),
    )
    payload = comparison.to_dict()
    assert payload["selection_split"] == "validation"
    assert payload["held_out_split"] == "test"
    assert payload["selected_key"] == "ridge"
    assert payload["held_out_report"]["split_label"] == "test"
    assert payload["reports"][0]["split_label"] == "validation"


# --- labelling ---------------------------------------------------------------


def test_comparison_disclaimer_is_present_for_non_real_data():
    """Every non-real dataset type gets a distinct, non-empty warning.

    `synthetic` and `unknown` are different situations and must not share
    wording: synthetic data is known to be simulated, while unknown data may be
    genuine but undocumented. Calling unknown data "synthetic" would be an
    accusation the pipeline cannot support.
    """
    synthetic = build_comparison_disclaimer("synthetic")
    assert synthetic is not None
    assert "synthetic/demo evaluation only" in synthetic
    assert "not a production or research result" in synthetic

    unknown = build_comparison_disclaimer("unknown")
    assert unknown is not None
    assert "UNKNOWN" in unknown
    assert "synthetic/demo evaluation only" not in unknown


def test_no_comparison_disclaimer_for_real_data():
    assert build_comparison_disclaimer("real") is None


def test_every_table_row_repeats_the_metric_label():
    """A number separated from its label is a number that can be screenshotted
    out of context, so the label is on the row itself."""
    comparison = compare_models(
        [_report("linear", "validation", 0.5), _report("ridge", "validation", 0.3)],
        selection_metric="rmse",
        held_out_report=_report("ridge", "test", 0.4),
    )
    table = comparison.table()
    assert table.count("synthetic/demo evaluation only") == 2
    assert comparison.held_out_table().count("synthetic/demo evaluation only") == 1


def test_selection_policy_note_explains_the_choice():
    """The note must state the direction of the metric, so a reader knows
    whether a larger or smaller number won."""
    assert "lowest RMSE" in selection_policy_note("rmse")
    assert "lowest MAE" in selection_policy_note("mae")


# --- split-aware metric labelling -------------------------------------------


def _real_report(split_label: str) -> "EvaluationReport":
    """A real-data report on an arbitrary split.

    The numbers are arbitrary on purpose: these tests assert the *label*, and a
    test that needed believable metrics would be a test that could be fooled.
    """
    return replace(
        _report("ridge", split_label, 0.3),
        provenance=replace(
            _provenance(),
            dataset_type="real",
            dataset_reference="shape-only",
            disclaimer=None,
        ),
    )


def test_held_out_report_of_real_data_is_labelled_a_measured_evaluation():
    report = _real_report(HELD_OUT_SPLIT)
    assert report.split_caveat is None
    assert report.metric_label == "measured evaluation"


def test_train_split_report_is_labelled_a_fit_statistic():
    """Regression guard.

    The label used to come from the provenance record alone, which knows the
    dataset but not the split. A train-split score of real data therefore read
    'measured evaluation' — the most flattering number available, presented as
    though it were an estimate of performance on unseen data.
    """
    report = _real_report(TRAIN_SPLIT)
    assert report.split_caveat is not None
    assert "NOT A HELD-OUT RESULT" in report.metric_label
    assert "fit statistic" in report.metric_label
    assert "measured evaluation" not in report.metric_label


def test_validation_split_report_is_labelled_a_selection_statistic():
    report = _real_report(SELECTION_SPLIT)
    assert "NOT A HELD-OUT RESULT" in report.metric_label
    assert "selection statistic" in report.metric_label
    assert "measured evaluation" not in report.metric_label


def test_an_unrecognised_split_is_not_assumed_to_be_held_out():
    """A typo must not silently promote a train-period score to a result."""
    report = _real_report("tset")
    assert "NOT A HELD-OUT RESULT" in report.metric_label
    assert "'tset'" in report.metric_label


def test_the_synthetic_label_takes_precedence_over_the_split_caveat():
    """The dataset caveat is the stronger claim: it says the numbers do not
    describe a hydrological result at all, which subsumes any statement about
    which split they came from.

    The label itself is the full provenance phrase, not the bare
    `synthetic/demo evaluation only` stem -- the existing tests assert
    containment, and appending a second clause here would be redundant.
    """
    report = _report("ridge", TRAIN_SPLIT, 0.3)
    assert report.split_caveat is not None
    assert "synthetic/demo evaluation only" in report.metric_label
    assert "not a production or research result" in report.metric_label
    assert "NOT A HELD-OUT RESULT" not in report.metric_label


def test_a_non_held_out_real_report_does_not_borrow_the_synthetic_phrase():
    """Guards the precedence rule against leaking the other way."""
    label = _real_report(TRAIN_SPLIT).metric_label
    assert "synthetic" not in label.lower()
    assert "measured evaluation" not in label.lower()


def test_the_split_caveat_reaches_the_serialised_report():
    """The label has to survive serialisation, since that is what a consumer
    reads. A caveat only present on the Python object protects nobody."""
    payload = _real_report(SELECTION_SPLIT).to_dict()
    assert "NOT A HELD-OUT RESULT" in payload["metric_label"]
    # The split is recorded alongside it, so the two can be cross-checked.
    assert payload["split_label"] == "validation"


def test_the_split_caveat_reaches_the_formatted_report():
    text = _real_report(TRAIN_SPLIT).format()
    assert "NOT A HELD-OUT RESULT" in text
    assert "fit statistic" in text


def test_split_names_are_defined_once():
    """`training` re-exports these rather than repeating the literals, so the two
    modules cannot drift into disagreeing about which split is held out."""
    assert training.SELECTION_SPLIT == SELECTION_SPLIT == "validation"
    assert training.HELD_OUT_SPLIT == HELD_OUT_SPLIT == "test"
    assert TRAIN_SPLIT == "train"
    assert "lowest NSE" in selection_policy_note("nse")
    # `nse` shares a formula with R² but is reported as an efficiency where
    # higher is better; the note must not inherit the error-metric wording.
    assert "highest R2" in selection_policy_note("r2")


def test_selection_policy_note_names_the_period_it_ranked_on():
    note = selection_policy_note("rmse")
    assert "among the executed candidates" in note
    assert "same period" in note
