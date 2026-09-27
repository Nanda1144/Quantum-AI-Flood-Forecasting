# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""End-to-end tests for the training pipeline.

The pipeline is run on SYNTHETIC/DEMO data only. The assertions are structural —
that the right stages ran, that the splits do not overlap, that the selected
model is the one the validation split chose, that the artifact refuses to be
called production-ready — and never a hydrological performance claim.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.engines.hydro.evaluation import SUPPORTED_METRICS
from app.engines.hydro.models import ModelError, registry_keys
from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER
from app.engines.hydro.training import (
    HELD_OUT_SPLIT,
    SELECTION_SPLIT,
    TrainingError,
    fit_pipeline,
    format_report,
    train,
)


@pytest.fixture(scope="module")
def result(shared_demo_config, shared_demo_frame):
    """One full training run, reused across assertions.

    Module-scoped because a run costs a complete pipeline pass and nothing here
    mutates the result. The frame is generated with a fixed `random_state`, so
    the numbers a test sees are identical on every run and no test asserts a
    hydrological result from them.
    """
    return train(
        shared_demo_config.with_overrides(model_name="ridge"),
        frame=shared_demo_frame,
        candidate_models=("linear", "ridge"),
    )


# --- the run produces a selection -------------------------------------------


def test_run_selects_a_model(result):
    assert result.selected_key in result.models
    assert result.comparison is not None
    assert result.comparison.selected_key == result.selected_key


def test_selection_uses_only_the_validation_split(result):
    comparison = result.comparison
    assert comparison.selection_split == SELECTION_SPLIT
    assert all(r.split_label == SELECTION_SPLIT for r in comparison.reports)
    comparison.assert_selection_is_clean()


def test_the_test_split_is_scored_exactly_once(result):
    held = result.comparison.held_out_report
    assert held is not None
    assert held.split_label == HELD_OUT_SPLIT
    assert held.model_key == result.selected_key
    # Only the selected model has a test report.
    with_test = [k for k, m in result.models.items() if m.test_report is not None]
    assert with_test == [result.selected_key]


def test_every_selected_metric_is_a_computed_regression_metric(result):
    for report in result.comparison.reports:
        assert report.metrics.n_samples > 0
        assert np.isfinite(report.metrics.rmse)
        assert report.metrics.mae >= 0
    assert result.comparison.selection_metric in SUPPORTED_METRICS


def test_synthetic_metrics_carry_the_synthetic_label(result):
    for report in result.comparison.reports:
        assert "synthetic/demo evaluation only" in report.metric_label
    held = result.comparison.held_out_report
    assert "synthetic/demo evaluation only" in held.metric_label


# --- split integrity in a real run ------------------------------------------


def test_splits_do_not_overlap_in_a_real_run(result):
    b = result.boundaries
    assert b.is_ordered() is True
    assert b.train_rows > 0 and b.validation_rows > 0 and b.test_rows > 0
    assert b.train_rows > b.validation_rows or b.train_rows >= b.validation_rows


def test_supervised_alignment_uses_the_configured_horizon(result):
    assert result.lead_time_rows >= 1
    assert result.plan.lead_time_rows == result.lead_time_rows


def test_scaler_and_imputer_were_fitted_on_train_only(result):
    for trained in result.models.values():
        assert trained.scaler.fitted_on == "train"
        assert trained.imputer.fitted_on == "train"


def test_preprocessing_log_lists_every_step(result):
    names = [step.name for step in result.preprocessing.steps]
    assert "parse_timestamps" in names
    assert "sort_chronologically" in names
    assert "apply_missing_policy" in names


# --- provenance --------------------------------------------------------------


def test_provenance_records_the_synthetic_dataset(result):
    assert result.provenance.dataset_type == "synthetic"
    assert result.provenance.is_synthetic is True
    assert result.provenance.disclaimer == SYNTHETIC_DATA_DISCLAIMER


def test_provenance_carries_the_real_split_boundaries(result):
    assert result.provenance.split is not None
    assert result.provenance.split.is_ordered() is True


def test_provenance_has_no_classification_metrics(result):
    keys = set(json.loads(json.dumps(result.provenance.to_dict())).get("evaluation_metrics") or {})
    for forbidden in ("accuracy", "precision", "recall", "f1"):
        assert forbidden not in keys


# --- the report --------------------------------------------------------------


def test_report_states_the_selection_protocol(result):
    text = format_report(result)
    assert SELECTION_SPLIT in text
    assert HELD_OUT_SPLIT in text
    assert "never influences the ranking" in text


def test_report_carries_the_synthetic_disclaimer(result):
    assert SYNTHETIC_DATA_DISCLAIMER in format_report(result)


def test_report_names_unevaluated_and_unavailable_models(demo_config, demo_frame):
    """A candidate that could not be scored must be named in the report.

    The distinction matters: a model quietly dropped looks identical to a model
    that was scored and lost, so a reader would see a two-model comparison and
    believe the sweep was complete. An unknown key and a key whose dependency is
    missing are also different failures, and both are reported.
    """
    from app.engines.hydro.models import unavailable_models

    run = train(
        demo_config,
        frame=demo_frame,
        candidate_models=("linear", "xgboost", "not-a-model"),
    )
    text = format_report(run)

    # The unknown key is recorded as not evaluated, with the section heading
    # that distinguishes it from a model that lost.
    assert "not evaluated" in text
    assert "not-a-model" in text

    expected_unavailable = {
        key: value
        for key, value in unavailable_models().items()
        if key in ("xgboost", "random_forest", "gradient_boosting")
    }
    if expected_unavailable:
        assert "unavailable in this environment" in text
        for key, value in expected_unavailable.items():
            assert key in text
            assert value in text  # the missing import path is named

    # Whatever happened to the extra candidates, the one executable candidate is
    # the selected model and the comparison is not empty.
    assert run.selected_key == "linear"
    assert run.comparison is not None
    assert [r.model_key for r in run.comparison.reports] == ["linear"]


def test_a_candidate_absent_from_the_environment_is_never_scored(demo_config, demo_frame):
    """A model listed but not run must not appear with a score.

    This is the failure mode where an unavailability is turned into a plausible
    number; the assertion is that the key has no report and is named instead.
    """
    from app.engines.hydro.models import unavailable_models

    missing = set(unavailable_models())
    if not missing:
        pytest.skip("every registered candidate is installed in this environment")

    run = train(
        demo_config,
        frame=demo_frame,
        candidate_models=("linear", *sorted(missing)),
    )
    assert run.selected_key == "linear"
    for key in missing:
        assert key not in run.models, f"{key} could not be executed but was reported as trained"
        assert key not in {r.model_key for r in run.comparison.reports}
    assert set(run.comparison.unavailable) & missing
    assert all(key in format_report(run) for key in missing)


# --- refusals ----------------------------------------------------------------


def test_run_refuses_an_unknown_model_key(demo_config, demo_frame):
    run = train(
        demo_config,
        frame=demo_frame,
        candidate_models=("linear", "definitely-not-a-model"),
    )
    assert "definitely-not-a-model" in run.comparison.unevaluated_keys
    assert run.selected_key == "linear"


def test_run_refuses_when_no_candidate_is_executable(demo_config, demo_frame):
    with pytest.raises(TrainingError):
        train(demo_config, frame=demo_frame, candidate_models=("not-a-model",))


def test_run_refuses_an_unsupported_selection_metric(demo_config, demo_frame):
    with pytest.raises((TrainingError, ValueError)):
        train(
            demo_config,
            frame=demo_frame,
            candidate_models=("linear",),
            selection_metric="accuracy",
        )


def test_run_refuses_a_frame_that_is_too_short(demo_config, demo_frame):
    with pytest.raises((TrainingError, ValueError)):
        train(demo_config, frame=demo_frame.head(12), candidate_models=("linear",))


def test_fit_pipeline_refuses_a_model_with_the_wrong_feature_width(result):
    """A fitted model must not accept a differently shaped matrix.

    Accepting it would silently broadcast coefficients across the wrong columns
    and produce a number that looks like a forecast of the trained model but is
    not one.
    """
    train_matrices = result.supervised["train"]
    trained = fit_pipeline(train_matrices, model_key="ridge", config=result.config)
    fitted_width = train_matrices.features.shape[1]
    assert fitted_width > 3

    with pytest.raises(ModelError, match="feature"):
        trained.estimator.fit(np.zeros((5, 3)), np.zeros(5))
    with pytest.raises(ModelError, match="feature"):
        trained.estimator.predict(np.zeros((5, fitted_width + 2)))


def test_fit_pipeline_fits_the_imputer_and_scaler_on_train_rows_only(result):
    """Both fitted objects record the split they were fitted on.

    This is the recorded fact, not a proof; `test_hydro_leakage.py` carries the
    perturbation test that proves no test-period value influenced a fit.
    """
    train_matrices = result.supervised["train"]
    trained = fit_pipeline(train_matrices, model_key="linear", config=result.config)
    assert trained.imputer.fitted_on == "train"
    assert trained.scaler.fitted_on == "train"
    assert list(trained.feature_names) == list(train_matrices.feature_names)


# --- helpers used only by this module ---------------------------------------
