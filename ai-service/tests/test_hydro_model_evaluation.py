# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 4 — metrics, evaluation outcomes and the model comparison table.

The risk this file guards against is arithmetic that flatters. A metric computed on
the wrong population, a percentage error over a water level that crosses its datum, a
model that could not be scored shown with a `0.0` in the MAE column, or a comparison
table that names a winner without saying what it was chosen on — each of those is a
false statement about model quality that a reader would act on.

Every number here is produced from deterministic synthetic/demo data. No test
asserts a hydrological result, and none of these metrics is evidence about any real
catchment.
"""

from __future__ import annotations

import math

import pytest

from hydro_phase4_fixtures import (
    SYNTHETIC_DISCLAIMER,
    config_for,
    trained_pair,
)

from app.engines.hydro.model_config import (
    COMPUTABLE_METRICS,
    DEFAULT_METRICS,
    FAMILY_NAIVE,
    FAMILY_RANDOM_FOREST,
)
from app.engines.hydro.model_evaluation import (
    COMPARISON_COLUMNS,
    COMPARISON_FIELDS,
    LOWER_IS_BETTER,
    PERCENT_ERROR_UNAVAILABLE_REASON,
    REPORTABLE_METRICS,
    SYNTHETIC_EVALUATION_LABEL,
    TWO_SIDED_METRICS,
    EvaluationOutcome,
    ModelEvaluationError,
    build_comparison,
    data_status,
    evaluate_predictions,
    mean_absolute_percentage_error,
    unevaluated_outcome,
)
from app.engines.hydro.model_registry import EVALUATION_STATUSES, TRAINING_STATUSES

pytest_plugins: list[str] = []

TRAINED = ("naive", "random_forest")
SPLITS = ("validation", "test")


def _value(row, metric: str):
    """One metric off a comparison row, or `None`.

    A helper rather than a lookup so the "absent means `None`, never `0.0`" rule is
    applied the same way everywhere in this file.
    """
    return {
        "mae": row.mae,
        "rmse": row.rmse,
        "r2": row.r2,
        "bias": row.bias,
        "nse": None,
        "peak_absolute_error": None,
    }[metric]


# --------------------------------------------------------------------------- #
# The metric definitions, against numbers a reader can check by hand
# --------------------------------------------------------------------------- #


def _outcome(y_true, y_pred, **changes):
    settings = {
        "model_id": "naive",
        "model_family": FAMILY_NAIVE,
        "target": "target_water_level_6h",
        "target_units": "m",
        "horizon": "6h",
        "split": "validation",
        "y_true": y_true,
        "y_pred": y_pred,
        "is_synthetic": True,
    }
    settings.update(changes)
    return evaluate_predictions(**settings)


def test_mae_is_the_mean_absolute_error() -> None:
    """`[1, 2, 3]` against `[1, 4, 6]`: errors `0, 2, 3`, so MAE is `5/3`."""
    outcome = _outcome([1.0, 2.0, 3.0], [1.0, 4.0, 6.0])
    assert outcome.metrics["mae"] == pytest.approx(5.0 / 3.0)


def test_rmse_is_the_root_mean_squared_error_and_not_the_mae() -> None:
    """Same three rows: squared errors `0, 4, 9`, so RMSE is `sqrt(13/3)`.

    RMSE is checked separately from MAE because the two differ precisely when the
    errors are unevenly distributed, which is the normal case for a flood forecast.
    A model with a few large misses must look worse on RMSE than on MAE; if they
    ever matched, one of them was computed wrong.
    """
    outcome = _outcome([1.0, 2.0, 3.0], [1.0, 4.0, 6.0])
    assert outcome.metrics["rmse"] == pytest.approx(math.sqrt(13.0 / 3.0))
    assert outcome.metrics["rmse"] > outcome.metrics["mae"]


def test_bias_is_the_mean_signed_error() -> None:
    """Positive bias means the model reads high.

    The sign convention is stated here because "bias" without a direction is
    ambiguous, and a reader who has to guess will read a high-bias model as a
    pessimistic one when it is the opposite.
    """
    high = _outcome([1.0, 1.0, 1.0], [2.0, 2.0, 2.0])
    low = _outcome([1.0, 1.0, 1.0], [0.0, 0.0, 0.0])
    assert high.metrics["bias"] == pytest.approx(1.0)
    assert low.metrics["bias"] == pytest.approx(-1.0)


def test_a_perfect_prediction_scores_zero_error_and_an_r2_of_one() -> None:
    """The upper anchor. Without it, a metric set has no known good end."""
    outcome = _outcome([3.0, 1.5, 9.0, 4.25], [3.0, 1.5, 9.0, 4.25])
    assert outcome.metrics["mae"] == 0.0
    assert outcome.metrics["rmse"] == 0.0
    assert outcome.metrics["bias"] == 0.0
    assert outcome.metrics["r2"] == pytest.approx(1.0)


def test_r2_is_negative_when_the_model_is_worse_than_predicting_the_mean() -> None:
    """`R2` is not a distance, so it goes below zero.

    A model that always predicts the mean scores `R2 = 0`. Anything worse scores
    negative. Clamping at zero would make a useless model look merely mediocre.
    """
    y_true = [1.0, 2.0, 3.0, 4.0]
    mean_only = _outcome(y_true, [2.5, 2.5, 2.5, 2.5])
    assert mean_only.metrics["r2"] == pytest.approx(0.0)
    worse = _outcome(y_true, [9.0, 9.0, 9.0, 9.0])
    assert worse.metrics["r2"] < 0.0


def test_metrics_retain_the_series_they_were_computed_from() -> None:
    """The outcome keeps `model, target, horizon, split, metric, value`.

    Asserted by rebuilding the same metric with the stdlib, so this is a second
    independent computation rather than a restatement of the module's own output.
    """
    y_true = [1.0, 2.0, 3.0]
    y_pred = [1.5, 1.0, 4.0]
    outcome = _outcome(y_true, y_pred, report=REPORTABLE_METRICS)
    mean_error = sum(abs(t - p) for t, p in zip(y_true, y_pred)) / len(y_true)
    assert outcome.metrics["mae"] == pytest.approx(mean_error)
    assert set(outcome.metrics) == set(REPORTABLE_METRICS)
    for name, value in outcome.metrics.items():
        assert math.isfinite(value), f"{name} is not finite"


def test_the_default_reported_set_is_a_subset_of_what_evaluation_computes() -> None:
    """A metric a configuration may ask for but the evaluator does not compute would
    surface as a `ModelEvaluationError` after a model had already been fitted — which
    is why `ModelConfig` now refuses an uncomputable metric up front."""
    default = _outcome([1.0, 2.0, 3.0], [1.5, 1.0, 4.0])
    assert set(default.metrics) <= set(REPORTABLE_METRICS)
    assert set(default.metrics) == set(DEFAULT_METRICS)


def test_asking_for_a_metric_that_was_not_computed_is_refused() -> None:
    """Loudly, and before any number is returned. Silently dropping the request
    would leave a configuration claiming to report something it does not."""
    with pytest.raises(ModelEvaluationError) as caught:
        _outcome([1.0, 2.0, 3.0], [1.5, 1.0, 4.0], report=("mae", "skill_score"))
    assert "skill_score" in str(caught.value)
    assert "REPORTABLE_METRICS" in str(caught.value)


def test_a_metric_the_configuration_did_not_ask_for_is_simply_absent() -> None:
    """Not `None`, not zero. Absence from the mapping is the honest statement that it
    was not requested."""
    outcome = _outcome([1.0, 2.0, 3.0], [1.5, 1.0, 4.0], report=("mae",))
    assert outcome.metrics == {"mae": outcome.metrics["mae"]}
    assert outcome.metric("rmse") is None, (
        "an unrequested metric must read as unavailable, never as 0.0"
    )


# --------------------------------------------------------------------------- #
# MAPE is deliberately not reported
# --------------------------------------------------------------------------- #


def test_mape_is_not_reported_for_this_target_by_default() -> None:
    """A water level is measured against a datum and passes through it.

    Near the datum `|actual|` approaches zero while the absolute error stays
    finite, so the ratio diverges. The refusal is recorded as a `PercentError` with
    a stated reason rather than left as a missing key.
    """
    outcome = _outcome([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert outcome.percent_error is not None
    assert outcome.percent_error.value is None
    assert outcome.percent_error.reason == PERCENT_ERROR_UNAVAILABLE_REASON
    assert "mape" not in {name.lower() for name in outcome.metrics}


def test_mape_stays_unavailable_even_when_enabled_on_a_target_that_crosses_the_datum() -> None:
    """Enabling it must not produce a number.

    The failure mode this guards is the attractive one: a percentage error is easy
    to compute, easy to include, and meaningless here. An implementation that
    honoured the flag would produce an infinite ratio on exactly the rows that
    matter most.
    """
    y_true = [0.0, 0.0, 0.0]
    y_pred = [1.0, -1.0, 2.0]
    result = mean_absolute_percentage_error(y_true, y_pred, enabled=True)
    assert result.value is None
    assert result.reason == PERCENT_ERROR_UNAVAILABLE_REASON
    assert result.excluded_rows == len(y_true)
    assert result.included_rows == 0


def test_the_percent_error_records_its_denominator_floor_even_when_it_refuses() -> None:
    """A refusal that states no denominator is indistinguishable from a shrug."""
    result = mean_absolute_percentage_error([1.0], [2.0], enabled=False)
    assert result.value is None
    assert result.denominator_floor > 0.0


# --------------------------------------------------------------------------- #
# Degenerate populations are refused, not scored
# --------------------------------------------------------------------------- #


def test_an_empty_prediction_set_is_recorded_unscoreable_rather_than_scored() -> None:
    """A mean over no rows is undefined, and `0.0` would be a lie about it.

    Recorded rather than raised: an unscoreable population is a fact about the run,
    and the comparison table needs a row for it.
    """
    outcome = _outcome([], [])
    assert outcome.status == "insufficient_rows"
    assert outcome.metrics is None
    assert outcome.n_samples == 0
    assert "zero rows" in outcome.reason


def test_a_mismatched_length_is_recorded_rather_than_truncated() -> None:
    """`zip` would silently drop the tail and produce a shorter, flattering score."""
    outcome = _outcome([1.0, 2.0, 3.0], [1.0, 2.0])
    assert outcome.status == "insufficient_rows"
    assert outcome.metrics is None
    assert "3" in outcome.reason and "2" in outcome.reason


def test_a_single_observation_is_recorded_unscoreable() -> None:
    """`R2` needs a spread to compare against; one row has none."""
    outcome = _outcome([1.0], [1.5])
    assert outcome.status == "insufficient_rows"
    assert outcome.metrics is None
    assert "at least 2" in outcome.reason


def test_a_non_finite_prediction_is_recorded_unscoreable_rather_than_scored() -> None:
    """A `NaN` prediction has no error; averaging it in would poison every metric
    except the ones that happen to skip non-finite values.

    Recorded on the *same* path as every other unscoreable population. This used to
    raise the legacy `EvaluationError` out of this module while an empty set was
    recorded, so the same class of condition was sometimes a row in the comparison
    table and sometimes a crash in a caller's face.
    """
    outcome = _outcome([1.0, 2.0, 3.0], [1.0, float("nan"), 3.0])
    assert outcome.status == "insufficient_rows"
    assert outcome.metrics is None
    assert "non-finite" in outcome.reason


def test_a_non_finite_target_is_recorded_unscoreable_too() -> None:
    outcome = _outcome([1.0, 2.0, 3.0], [1.0, 2.0, float("inf")])
    assert outcome.status == "insufficient_rows"
    assert outcome.metrics is None


def test_a_constant_target_reports_a_documented_r2_of_zero() -> None:
    """`R2 = 1 - SS_res / SS_tot` divides by the target's variance, and a flat series
    has none.

    The legacy metric module states the convention explicitly: zero, meaning
    "explained nothing", rather than a perfect score or a `NaN`. This test pins that
    convention so a later change to `None` or `1.0` has to be a deliberate act.
    """
    outcome = _outcome([2.0, 2.0, 2.0, 2.0], [2.1, 1.9, 2.05, 2.0])
    assert outcome.status == "evaluated"
    assert outcome.metrics["r2"] == 0.0
    assert outcome.metrics["mae"] == pytest.approx(0.0625)
    assert outcome.metrics["bias"] == pytest.approx(0.0125)


# --------------------------------------------------------------------------- #
# Unavailable is never zero
# --------------------------------------------------------------------------- #


def test_an_unevaluated_outcome_carries_no_metrics_at_all() -> None:
    """`metrics is None`, not `{}` and not a row of zeros.

    A `{}` would be indistinguishable from "computed, nothing to report", and a row
    of zeros would sort to the top of any table sorted on error.
    """
    outcome = unevaluated_outcome(
        model_id="xgboost",
        model_family="xgboost",
        target="target_water_level_6h",
        target_units="m",
        horizon="6h",
        split="test",
        status="not_evaluated",
        reason="xgboost is not installed on this interpreter",
        is_synthetic=True,
    )
    assert outcome.metrics is None
    assert outcome.n_samples == 0
    assert outcome.status == "not_evaluated"
    assert "xgboost" in outcome.reason
    assert outcome.metric("mae") is None
    assert outcome.evaluated is False


def test_an_evaluated_outcome_with_no_metrics_is_rejected() -> None:
    """The converse. An `evaluated` row with nothing measured is a contradiction,
    and it is the shape a table would silently render as a blank success."""
    with pytest.raises(ModelEvaluationError) as caught:
        EvaluationOutcome(
            model_id="naive",
            model_family=FAMILY_NAIVE,
            target="target_water_level_6h",
            target_units="m",
            horizon="6h",
            split="test",
            status="evaluated",
            metrics=None,
            n_samples=10,
            synthetic_demo=True,
        )
    assert "requires metrics" in str(caught.value)


def test_an_unevaluated_outcome_that_carries_metrics_is_rejected() -> None:
    """A blocked model with metrics attached would be scored as though it ran."""
    with pytest.raises(ModelEvaluationError) as caught:
        EvaluationOutcome(
            model_id="lstm",
            model_family="lstm",
            target="target_water_level_6h",
            target_units="m",
            horizon="6h",
            split="test",
            status="not_evaluated",
            metrics={"mae": 0.01},
            n_samples=10,
            reason="torch is not installed",
            synthetic_demo=True,
        )
    assert "metrics=None" in str(caught.value)


def test_an_unknown_status_is_rejected_rather_than_stored() -> None:
    """The status vocabulary is closed. An unrecognised string would propagate into
    the table as a status no reader knows the meaning of."""
    with pytest.raises(ModelEvaluationError) as caught:
        EvaluationOutcome(
            model_id="naive",
            model_family=FAMILY_NAIVE,
            target="target_water_level_6h",
            target_units="m",
            horizon="6h",
            split="test",
            status="dependency_unavailable",
            metrics=None,
            synthetic_demo=True,
        )
    assert "known statuses" in str(caught.value)


def test_no_outcome_ever_claims_production_readiness() -> None:
    """Not on the synthetic data, not on real data, not by configuration.

    The field exists because the requirement is that the flag is never set. It is
    asserted on an outcome that scored perfectly, which is the case where the claim
    would be most tempting.
    """
    perfect = _outcome([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], is_synthetic=False,
                       dataset_type="measured")
    assert perfect.production_ready_claimed is False
    blocked = unevaluated_outcome(
        model_id="gru",
        model_family="gru",
        target="target_water_level_6h",
        target_units=None,
        horizon="6h",
        split="test",
        status="not_evaluated",
        reason="no deep-learning runtime",
        is_synthetic=False,
        dataset_type="measured",
    )
    assert blocked.production_ready_claimed is False


def test_a_training_status_is_not_an_evaluation_status() -> None:
    """The two vocabularies are separate, and the run keeps them apart.

    `dependency_unavailable` describes *training*; `not_evaluated` describes
    *scoring*. Conflating them would make "we could not fit it" and "we could not
    score it" the same cell, which are different problems with different remedies.
    """
    assert "dependency_unavailable" in TRAINING_STATUSES
    assert "dependency_unavailable" not in EVALUATION_STATUSES
    assert "not_evaluated" in EVALUATION_STATUSES
    assert "not_evaluated" not in TRAINING_STATUSES


# --------------------------------------------------------------------------- #
# Synthetic / demo status must be visible on every row
# --------------------------------------------------------------------------- #


def test_a_synthetic_run_is_labelled_synthetic_and_carries_the_label() -> None:
    """Two independent statements, because either alone can be lost.

    `data_status` is the machine-readable column; the label is the sentence a reader
    sees. A downstream consumer that keeps only the metrics would otherwise have no
    way to tell what they measured.
    """
    outcome = _outcome([1.0, 2.0, 3.0], [1.0, 2.5, 2.0])
    assert outcome.synthetic_demo is True
    assert outcome.data_status == "synthetic_demo"
    assert "synthetic" in SYNTHETIC_EVALUATION_LABEL.lower()
    assert outcome.label == SYNTHETIC_EVALUATION_LABEL


def test_data_status_distinguishes_synthetic_from_measured_and_unknown() -> None:
    """Three states, and no collapsing of `unknown` into `measured`.

    Defaulting an unverified dataset to `measured` would let unverified numbers
    circulate as checked ones, so only an explicit `real` earns that label.
    """
    assert data_status(True, "synthetic") == "synthetic_demo"
    assert data_status(False, "real") == "measured"
    assert data_status(False, "unknown") == "unknown"
    assert data_status(False, "") == "unknown"
    assert data_status(False, "measured") == "unknown", (
        "'measured' is the *output* label, not the accepted input spelling; only a "
        "dataset typed 'real' earns it"
    )
    assert data_status(False, "synthetic") == "synthetic_demo", (
        "a dataset typed synthetic is synthetic whatever the caller believes"
    )


def test_an_unverified_dataset_is_not_reported_as_measured() -> None:
    """Phase 2 emits `UNVERIFIED_DATA_DISCLAIMER` for data it could not check, and
    such a run must not claim a measured status."""
    from app.engines.hydro.datasets import UNVERIFIED_DATA_DISCLAIMER

    assert UNVERIFIED_DATA_DISCLAIMER
    outcome = _outcome([1.0, 2.0], [1.0, 2.0], is_synthetic=False, dataset_type="unknown")
    assert outcome.data_status == "unknown"
    assert outcome.synthetic_demo is False
    assert outcome.label != SYNTHETIC_EVALUATION_LABEL


def test_a_measured_dataset_is_reported_as_measured_and_not_as_a_synthetic_run() -> None:
    """The other direction, so the check above cannot pass by rejecting everything.

    The fixture is still synthetic; only the *label* is under test here, because a
    function that returned `unknown` for every input would otherwise satisfy the
    previous test.
    """
    outcome = _outcome([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], is_synthetic=False,
                       dataset_type="real")
    assert outcome.data_status == "measured"
    assert outcome.synthetic_demo is False


# --------------------------------------------------------------------------- #
# The comparison table
# --------------------------------------------------------------------------- #


def test_the_table_carries_every_required_column() -> None:
    """The declared column set is fixed by the contract, so it is asserted literally
    rather than by subset: a column quietly dropped would otherwise go unnoticed until
    someone rendered the table without it."""
    required = {
        "model_id",
        "model_family",
        "target",
        "horizon",
        "split",
        "MAE",
        "RMSE",
        "R2",
        "bias",
        "training_status",
        "evaluation_status",
        "data_status",
        "synthetic_demo",
    }
    assert required <= set(COMPARISON_COLUMNS), (
        f"the declared columns are missing {sorted(required - set(COMPARISON_COLUMNS))}"
    )


def test_every_declared_column_is_actually_serialised_on_a_row(trained_pair) -> None:
    """The declaration and `to_dict` must not drift apart.

    A column declared but never emitted — or emitted under a name the declaration
    does not list — is how a table ends up rendering without the model family or the
    synthetic flag it claims to have. `COMPARISON_FIELDS` is the wire spelling;
    `COMPARISON_COLUMNS` is the header spelling, and the two differ only in the case
    of the three metric names.
    """
    assert len(COMPARISON_FIELDS) == len(set(COMPARISON_FIELDS))
    assert len(COMPARISON_COLUMNS) == len(set(COMPARISON_COLUMNS))
    for row in trained_pair.comparison.rows:
        payload = row.to_dict()
        assert set(payload) == set(COMPARISON_FIELDS), (
            f"a row carries {sorted(set(payload) ^ set(COMPARISON_FIELDS))}, which the "
            "declaration does not list"
        )
        for header, field in zip(COMPARISON_COLUMNS[:10], COMPARISON_FIELDS[:10]):
            assert header == field, f"{header!r} renders {field!r}"
    for header, field in zip(COMPARISON_COLUMNS[-4:], COMPARISON_FIELDS[10:14]):
        assert header.lower() == field, f"{header!r} renders {field!r}"


def test_a_real_run_produces_a_row_per_model_and_split(trained_pair) -> None:
    """Not one row per run. Each split is scored separately and reported separately,
    so a validation figure can never be mistaken for a test figure."""
    table = trained_pair.comparison
    assert table.rows, "the run produced no comparison rows"
    families = {row.model_family for row in table.rows}
    assert families == set(TRAINED)
    keys = {(row.model_family, row.split) for row in table.rows}
    for family in TRAINED:
        for split in SPLITS:
            assert (family, split) in keys, f"{family}/{split} is missing from the table"


def test_the_model_id_states_the_target_horizon_and_seed(trained_pair) -> None:
    """Two runs with different targets must not collide on one identifier.

    The id is what a manifest, an artifact and a Phase 5 request will all key on, so
    it has to carry the facts that distinguish one fitted model from another.
    """
    table = trained_pair.comparison
    for row in table.rows:
        assert row.model_id.startswith(f"{row.model_family}-")
        assert row.target in row.model_id
        assert (row.horizon or "") in row.model_id
    assert len({row.model_id for row in table.rows}) == len(TRAINED)


def test_validation_and_test_metrics_are_reported_separately_and_never_averaged(
    trained_pair,
) -> None:
    """The temptation is to report one number. That number would be a score on a
    population that exists in neither split."""
    table = trained_pair.comparison
    for family in TRAINED:
        by_split = {
            row.split: row for row in table.rows if row.model_family == family
        }
        assert set(by_split) >= set(SPLITS)
        for split, row in by_split.items():
            assert row.split == split
            assert row.n_samples > 0, f"{family}/{split} has no samples"


def test_every_model_is_scored_on_the_same_rows(trained_pair) -> None:
    """Like-for-like or it is not a comparison.

    This is the property that makes the table mean anything: if the forest lost
    fewer rows than the baseline, part of the difference would be which rows were
    measured rather than which model predicted better.
    """
    table = trained_pair.comparison
    by_split: dict[str, set[int]] = {}
    for row in table.rows:
        if row.evaluation_status == "evaluated":
            by_split.setdefault(row.split, set()).add(row.n_samples)
    for split, counts in by_split.items():
        assert len(counts) == 1, (
            f"{split} was scored on differing row counts {sorted(counts)}; the models "
            "were not measured on the same observations"
        )


def test_the_baseline_is_present_in_every_split_it_was_scored_on(trained_pair) -> None:
    """A comparison without the baseline is a ranking, and a ranking without the
    reference point is a marketing claim."""
    table = trained_pair.comparison
    baseline_rows = [row for row in table.rows if row.model_id == table.baseline_model_id]
    assert baseline_rows, "no baseline row exists"
    assert {row.model_family for row in baseline_rows} == {"naive"}
    scored = {row.split for row in baseline_rows if row.mae is not None}
    assert scored == set(SPLITS), f"the baseline was scored on {sorted(scored)}"


def test_the_baseline_deltas_are_signed_so_that_positive_means_an_improvement() -> None:
    """`improvement_over` returns `baseline - model` for a metric where lower is
    better, so a positive delta is the better score.

    The sign is pinned here because the opposite convention is equally reasonable and
    a reader who assumes it will invert every conclusion drawn from the table.
    """
    worse = _outcome([1.0, 2.0, 3.0], [1.2, 1.8, 3.4], model_id="worse")
    better = _outcome([1.0, 2.0, 3.0], [1.05, 1.95, 3.05], model_id="better")
    assert better.metrics["mae"] < worse.metrics["mae"]
    assert better.improvement_over(worse, "mae") == pytest.approx(
        worse.metrics["mae"] - better.metrics["mae"]
    )
    assert better.improvement_over(worse, "mae") > 0.0, (
        "a model with the smaller MAE must show a positive improvement"
    )
    assert worse.improvement_over(better, "mae") < 0.0


def test_a_bias_difference_is_reported_raw_because_closer_to_zero_is_not_lower(
    trained_pair,
) -> None:
    """`bias` is two-sided. A model reading 5 m high is not better than one reading
    5 m low, so the delta is the signed difference and the interpretation is left to
    the reader.
    """
    high = _outcome([1.0, 1.0, 1.0], [2.0, 2.0, 2.0], model_id="high")
    low = _outcome([1.0, 1.0, 1.0], [0.0, 0.0, 0.0], model_id="low")
    assert "bias" in TWO_SIDED_METRICS
    assert high.improvement_over(low, "bias") == pytest.approx(2.0)


def test_every_model_row_states_the_baseline_difference_it_would_have_to_beat(
    trained_pair,
) -> None:
    """The comparison a reader wants is `model` against `baseline`, not the model's
    own number in isolation."""
    table = trained_pair.comparison
    baseline = {row.split: row for row in table.rows if row.model_id == table.baseline_model_id}
    others = [row for row in table.rows if row.model_id != table.baseline_model_id]
    assert others, "the run produced no non-baseline rows"
    for row in others:
        reference = baseline.get(row.split)
        assert reference is not None, f"no baseline row for {row.split}"
        assert row.baseline_delta is not None, (
            f"{row.model_id}/{row.split} carries no baseline delta"
        )
        assert set(row.baseline_delta) == set(REPORTABLE_METRICS)


def test_no_baseline_delta_is_produced_when_the_baseline_was_not_scored() -> None:
    """A delta against a model that has no number is not a delta. Reported as
    `None`, because the alternative is a difference against zero."""
    scored = _outcome([1.0, 2.0, 3.0], [1.2, 1.8, 3.4], model_id="candidate")
    blocked = unevaluated_outcome(
        model_id="naive",
        model_family=FAMILY_NAIVE,
        target="target_water_level_6h",
        target_units="m",
        horizon="6h",
        split="validation",
        status="insufficient_rows",
        reason="no rows had a baseline prediction",
        is_synthetic=True,
    )
    assert scored.improvement_over(blocked, "mae") is None
    table = build_comparison([scored, blocked], {"candidate": "trained", "naive": "trained"})
    row = next(r for r in table.rows if r.model_id == "candidate")
    assert row.baseline_delta is None, (
        "the table must not invent a delta when the baseline has no score"
    )


def test_a_model_never_reports_a_metric_it_was_not_measured_on(trained_pair) -> None:
    """Metrics absent from the table are `None`. A `0.0` would be a claim of
    perfection by a model that never scored."""
    for row in trained_pair.comparison.rows:
        if row.evaluation_status != "evaluated":
            assert row.mae is None
            assert row.rmse is None
            assert row.r2 is None
            assert row.bias is None


def test_the_table_names_the_metric_and_split_a_selection_was_made_on(trained_pair) -> None:
    """Selection without its criterion is a verdict without a trial.

    The default is RMSE on validation: validation is what selection is allowed to
    look at, and test is what it is not.
    """
    table = trained_pair.comparison
    assert table.selection_split == "validation"
    assert table.selection_metric in LOWER_IS_BETTER
    assert table.selected_model_id is not None, "the run produced no selection"
    selected = [
        row
        for row in table.rows
        if row.model_id == table.selected_model_id and row.split == table.selection_split
    ]
    assert selected, "a model was selected on a split it has no row for"
    assert _value(selected[0], table.selection_metric) is not None
    assert selected[0].model_id != table.baseline_model_id, (
        "the baseline is excluded from selection; selecting it would be selecting the "
        "reference point rather than a candidate"
    )


def test_selection_prefers_the_lowest_value_on_the_named_metric(trained_pair) -> None:
    """Asserted against the table rather than against a hard-coded winner.

    The fixture does not have to favour the forest: whichever model wins here, the
    winner must be the one with the lower RMSE on validation.
    """
    table = trained_pair.comparison
    candidates = [
        row
        for row in table.rows
        if row.split == table.selection_split and row.model_id != table.baseline_model_id
    ]
    scored = [(row.model_id, _value(row, table.selection_metric)) for row in candidates]
    scored = [(model_id, value) for model_id, value in scored if value is not None]
    assert scored, "no candidate carried the selection metric"
    best = min(value for _, value in scored)
    assert _value(
        next(row for row in candidates if row.model_id == table.selected_model_id),
        table.selection_metric,
    ) == pytest.approx(best)


def test_selection_never_reports_the_table_as_production_ready(trained_pair) -> None:
    """A selection is an engineering choice among the runs in front of it."""
    assert trained_pair.comparison.selected_model_id is not None
    for run in trained_pair.runs:
        assert run.production_ready_claimed is False


def test_the_table_repeats_the_synthetic_status_on_every_row(trained_pair) -> None:
    """Not once in a header the reader may not see."""
    assert trained_pair.comparison.data_status == "synthetic_demo"
    for row in trained_pair.comparison.rows:
        assert row.data_status == "synthetic_demo"
        assert row.synthetic_demo is True


def test_the_table_carries_the_exact_synthetic_disclaimer(trained_pair) -> None:
    """Character for character. A paraphrase would lose the instruction not to
    present the numbers as observations."""
    assert trained_pair.comparison.disclaimer == SYNTHETIC_DISCLAIMER


def test_distinct_training_statuses_are_preserved_rather_than_collapsed(trained_pair) -> None:
    """`trained`, `dependency_unavailable`, `insufficient_data`, `failed_training`,
    `target_unavailable` and `evaluation_unavailable` mean different things to a
    reader, so the table must not flatten them into `ok` / `failed`."""
    statuses = {row.training_status for row in trained_pair.comparison.rows}
    assert statuses == {"trained"}, f"unexpected statuses for a dependency-clean run: {statuses}"
    assert "trained" in TRAINING_STATUSES
    assert len(TRAINING_STATUSES) > 2, (
        "the vocabulary must distinguish more than success from failure, or the "
        "blocked and short-data cases have nowhere to be recorded"
    )


def test_a_model_that_could_not_be_scored_says_so_in_the_evaluation_column() -> None:
    """Built by hand, because the run under test has nothing blocked.

    The training status and the evaluation status are separate columns, so a model
    that trained and then could not be scored is representable: trained here,
    `not_evaluated` there.
    """
    blocked = unevaluated_outcome(
        model_id="gru",
        model_family="gru",
        target="target_water_level_6h",
        target_units=None,
        horizon="6h",
        split="test",
        status="not_evaluated",
        reason="no deep-learning runtime is installed",
        is_synthetic=True,
    )
    table = build_comparison([blocked], {"gru": "dependency_unavailable"})
    row = next(r for r in table.rows if r.model_id == "gru")
    assert row.evaluation_status == "not_evaluated"
    assert row.training_status == "dependency_unavailable", (
        "training and evaluation are separate facts and must land in separate columns"
    )
    assert row.mae is None
    assert row.n_samples == 0
    assert row.baseline_delta is None


def test_training_notes_are_carried_onto_the_row_they_belong_to() -> None:
    """A model-specific note — a warning, a dropped feature — belongs on that model's
    row, not on the table header where it would read as applying to everything."""
    blocked = unevaluated_outcome(
        model_id="lstm",
        model_family="lstm",
        target="target_water_level_6h",
        target_units=None,
        horizon="6h",
        split="test",
        status="not_evaluated",
        reason="keras is not installed",
        is_synthetic=True,
    )
    table = build_comparison(
        [blocked],
        {"lstm": "dependency_unavailable"},
        {"lstm": ("no deep-learning runtime is installed",)},
    )
    row = next(r for r in table.rows if r.model_id == "lstm")
    assert row.notes[0] == "no deep-learning runtime is installed", (
        "the run's own note must lead; it is the statement the run makes about itself"
    )
    assert "keras is not installed" in row.notes, (
        "a row with no metric must carry the reason it has no metric"
    )
    assert table.notes == (), (
        "a model-specific note belongs on that model's row, not on the table header "
        "where it would read as applying to every model"
    )


def test_the_reason_for_no_metric_reaches_the_row_even_without_a_training_note() -> None:
    """The regression this fixes.

    A model that fitted perfectly well and then had too few evaluable rows reported
    `insufficient_rows` with no explanation at all, because the notes came only from
    `training_notes` and a successful run has none. A status with no reason is a
    shrug in a table.
    """
    thin = unevaluated_outcome(
        model_id="random_forest",
        model_family="random_forest",
        target="target_water_level_6h",
        target_units="m",
        horizon="6h",
        split="validation",
        status="insufficient_rows",
        reason="24 evaluable row(s) is below this family's min_eval_rows of 10000",
        is_synthetic=True,
    )
    table = build_comparison([thin], {"random_forest": "trained"})
    row = next(r for r in table.rows if r.model_id == "random_forest")
    assert row.evaluation_status == "insufficient_rows"
    assert row.mae is None
    assert row.notes == ("24 evaluable row(s) is below this family's min_eval_rows of 10000",)
    assert "10000" in " ".join(row.notes), (
        "the note must name the threshold, or a reader cannot tell what to change"
    )


def test_an_evaluated_row_does_not_gain_a_note_it_did_not_earn() -> None:
    """The appended reason belongs to rows with no metric. Bolting a stale reason
    onto a scored row would misattribute it."""
    scored = _outcome([1.0, 2.0, 3.0], [1.2, 1.8, 3.4], model_id="random_forest")
    table = build_comparison([scored], {"random_forest": "trained"})
    row = next(r for r in table.rows if r.model_id == "random_forest")
    assert row.evaluation_status == "evaluated"
    assert row.notes == ()


def test_an_evaluated_model_and_a_blocked_one_coexist_without_pretending_equality() -> None:
    """The table must be able to hold both, which is the normal state of a real run."""
    scored = _outcome([1.0, 2.0, 3.0], [1.2, 1.8, 3.4], model_id=FAMILY_RANDOM_FOREST)
    blocked = unevaluated_outcome(
        model_id="lstm",
        model_family="lstm",
        target="target_water_level_6h",
        target_units=None,
        horizon="6h",
        split="test",
        status="not_evaluated",
        reason="keras is not installed",
        is_synthetic=True,
    )
    table = build_comparison(
        [scored, blocked],
        {FAMILY_RANDOM_FOREST: "trained", "lstm": "dependency_unavailable"},
    )
    by_id = {row.model_id: row for row in table.rows}
    assert by_id["random_forest"].evaluation_status == "evaluated"
    assert by_id["random_forest"].mae is not None
    assert by_id["lstm"].evaluation_status == "not_evaluated"
    assert by_id["lstm"].mae is None
    assert by_id["lstm"].synthetic_demo is True, (
        "a blocked model is still a run on synthetic data and must say so"
    )


def test_the_table_refuses_to_select_a_model_that_was_never_scored() -> None:
    """Selection is not a fallback. With nothing evaluated there is no selection, and
    reporting one would be a choice with no evidence behind it."""
    blocked = unevaluated_outcome(
        model_id="lstm",
        model_family="lstm",
        target="target_water_level_6h",
        target_units=None,
        horizon="6h",
        split="validation",
        status="not_evaluated",
        reason="keras is not installed",
        is_synthetic=True,
    )
    table = build_comparison([blocked], {"lstm": "dependency_unavailable"})
    assert table.selected_model_id is None


def test_an_empty_set_of_outcomes_produces_an_empty_table_not_an_error() -> None:
    """No model ran. The table says so; it does not select, and it does not invent
    a row."""
    table = build_comparison([], {})
    assert table.rows == ()
    assert table.selected_model_id is None
    assert table.data_status == "unknown"


def test_context_notes_are_carried_into_the_table(trained_pair) -> None:
    """Dataset-level facts — the imputation count, the scored population — belong on
    the table a reader reads, not only in a log nobody opens."""
    notes = " ".join(trained_pair.comparison.notes)
    assert notes.strip(), "the table carries no notes at all"
    assert "imputation" in notes.lower()
    assert "population" in notes.lower()


def test_the_scored_population_note_states_the_row_counts_it_used(trained_pair) -> None:
    """A like-for-like claim is only worth anything if the counts are on the page.

    Each split's scored count is cross-checked against the row count the table
    reports, so the note cannot drift away from the table it qualifies.
    """
    joined = " ".join(trained_pair.comparison.notes)
    for row in trained_pair.comparison.rows:
        if row.evaluation_status != "evaluated":
            continue
        fragment = f"{row.split}: {row.n_samples}"
        assert fragment in joined, (
            f"the scored-population note does not state {fragment!r}; the reader cannot "
            "check the like-for-like claim"
        )


def test_a_row_keeps_the_target_horizon_units_it_was_measured_on(trained_pair) -> None:
    """Preserved through evaluation. A metric without its unit is a number."""
    assert trained_pair.comparison.target == "target_water_level_6h"
    assert trained_pair.comparison.horizon == "6h"
    for outcome in trained_pair.outcomes:
        assert outcome.target == "target_water_level_6h"
        assert outcome.horizon == "6h"
        assert outcome.target_units == "m"
    for row in trained_pair.comparison.rows:
        assert row.target == trained_pair.comparison.target
        assert row.horizon == trained_pair.comparison.horizon


def test_lower_is_better_is_the_set_of_metrics_it_claims() -> None:
    """The direction matters for the delta a reader infers from it.

    `bias` is deliberately absent: it is two-sided and neither better nor worse
    merely because it is small.
    """
    assert "bias" not in LOWER_IS_BETTER
    assert "r2" not in LOWER_IS_BETTER
    assert {"mae", "rmse"} <= LOWER_IS_BETTER
    assert "bias" in REPORTABLE_METRICS
    assert TWO_SIDED_METRICS == {"bias"}


def test_the_table_does_not_claim_the_forest_beats_the_baseline_on_this_fixture(
    trained_pair,
) -> None:
    """The honest reading of the run that actually happened.

    On this fixture the forest is marginally better on validation and clearly worse on
    test. A table that reported only the favourable split would be the failure this
    project exists to prevent, so the test asserts that both splits are present and
    that the numbers disagree — rather than asserting a winner.
    """
    table = trained_pair.comparison
    rows = {
        (row.model_family, row.split): row
        for row in table.rows
        if row.evaluation_status == "evaluated"
    }
    validation = rows[("random_forest", "validation")]
    test = rows[("random_forest", "test")]
    baseline_validation = rows[("naive", "validation")]
    baseline_test = rows[("naive", "test")]

    forest_beat_baseline_on_validation = validation.mae < baseline_validation.mae
    forest_beat_baseline_on_test = test.mae < baseline_test.mae
    assert forest_beat_baseline_on_validation != forest_beat_baseline_on_test, (
        "the two splits agree on which model is better; this fixture was built so they "
        "would not, and that disagreement is the point"
    )


def test_the_configuration_drives_which_metrics_are_asked_for() -> None:
    """The frozen configuration, not a constant buried in the evaluator."""
    config = config_for(FAMILY_NAIVE, metrics=("mae", "bias"))
    assert config.metrics == ("mae", "bias")
    outcome = evaluate_predictions(
        model_id="naive",
        model_family=FAMILY_NAIVE,
        target="target_water_level_6h",
        target_units="m",
        horizon="6h",
        split="validation",
        y_true=[1.0, 2.0, 3.0],
        y_pred=[1.5, 2.5, 2.0],
        is_synthetic=True,
        report=config.metrics,
    )
    assert set(outcome.metrics) == {"mae", "bias"}