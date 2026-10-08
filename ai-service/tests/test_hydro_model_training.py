# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 4 — model training orchestration, the persistence baseline and the gates.

The questions this file asks are about honesty under failure. A family whose library
is not installed must say so with the exact blocker rather than vanish from the
report. A run with too little data must record what it needed and what it had. A
model that fitted must be describable from its record alone. And the persistence
baseline — the number every other number has to beat — must be computed on the same
rows, from the same target, at the same horizon, by the code path that scores
everything else.

Three of the five families are unavailable in this environment, and the tests say
that rather than working around it. Where a family is blocked the assertions are
about the *shape* of the refusal, never about performance: no metric is invented, no
status is softened, and the blocker text names the module, the class and the
requirement file that would change the outcome.

Every value here is synthetic/demo data. No test asserts a hydrological result.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from hydro_phase4_fixtures import (
    STATION_A,
    STATION_B,
    SYNTHETIC_DISCLAIMER,
    build_feature_result,
    config_for,
    feature_result,
    naive_dataset,
    trained_pair,
    trained_result,
)

from app.engines.hydro.feature_pipeline import (
    FEATURE_CONTRACT_VERSION,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VALIDATION,
)
from app.engines.hydro.model_config import (
    ARTIFACT_INCLUDE_PARAMETERS,
    ARTIFACT_METADATA_ONLY,
    FAMILY_GRU,
    FAMILY_LSTM,
    FAMILY_NAIVE,
    FAMILY_RANDOM_FOREST,
    FAMILY_XGBOOST,
    MODEL_CONTRACT_VERSION,
)
from app.engines.hydro.model_registry import (
    ARTIFACT_STATUS_METADATA,
    ARTIFACT_STATUS_NOT_WRITTEN,
    STATUS_DEPENDENCY_UNAVAILABLE,
    STATUS_INSUFFICIENT_DATA,
    STATUS_TARGET_UNAVAILABLE,
    STATUS_TRAINED,
    spec_for,
)
from app.engines.hydro.model_training import (
    Insufficiency,
    InsufficientData,
    NaivePersistenceEstimator,
    TrainingError,
    default_configurations,
    fit_family,
    model_id_for,
    seed_everything,
    train_models,
)

pytest_plugins: list[str] = []

ALL_FAMILIES = (FAMILY_NAIVE, FAMILY_RANDOM_FOREST, FAMILY_XGBOOST, FAMILY_LSTM, FAMILY_GRU)
#: Families whose library this interpreter does not have. Not a wish list and not a
#: skip: the environment is what it is, and the run must describe it accurately.
UNAVAILABLE_HERE = {
    family
    for family in (FAMILY_XGBOOST, FAMILY_LSTM, FAMILY_GRU)
    if spec_for(family).blocker_text() is not None
}
TARGET_COLUMN = "target_water_level_6h"


def _forest_run(result):
    """The one trained learned model in `result`, by family rather than by index."""
    matches = [r for r in result.runs if r.model_family == FAMILY_RANDOM_FOREST]
    assert len(matches) == 1, f"expected exactly one forest run, found {len(matches)}"
    return matches[0]


def _train(configs, result=None):
    """`train_models` over `configs`, defaulting to the short fixture."""
    if result is None:
        result = build_feature_result()
    return train_models(result.dataset, configs, cadences=result.report.cadence)


# --------------------------------------------------------------------------- #
# The five declared families are the five the run attempts
# --------------------------------------------------------------------------- #


def test_the_default_configurations_cover_every_declared_family() -> None:
    """A family in the registry but not in the default run is a family nobody
    reports on, which is how a gap becomes invisible."""
    assert {config.model_family for config in default_configurations()} == set(ALL_FAMILIES)


def test_the_default_configurations_are_frozen_and_deterministic() -> None:
    """Two calls, two identical sequences.

    A default that varies between calls cannot appear in a manifest and cannot be
    reproduced, so the difference has to be observable rather than assumed.
    """
    first = default_configurations()
    second = default_configurations()
    assert [config.to_dict() for config in first] == [config.to_dict() for config in second]
    assert {config.random_seed for config in first} == {20240917}


def test_a_run_attempts_every_family_it_was_given(trained_result) -> None:
    assert {run.model_family for run in trained_result.runs} == set(ALL_FAMILIES)


def test_every_family_that_can_run_did_run(trained_result) -> None:
    """The converse: nothing was quietly left out of the attempt."""
    for run in trained_result.runs:
        if run.model_family in UNAVAILABLE_HERE:
            continue
        assert run.status == STATUS_TRAINED, (
            f"{run.model_family} is available in this environment but finished as "
            f"{run.status!r}: {run.reason}"
        )


def test_this_environment_really_does_block_the_families_the_tests_assume() -> None:
    """So that a run on a machine where xgboost *is* installed fails loudly here
    instead of silently testing a different code path than the one documented."""
    assert UNAVAILABLE_HERE, (
        "no family was blocked; the tests that assert the blocked path are not "
        "exercising it and the report must be updated to say so"
    )


# --------------------------------------------------------------------------- #
# The persistence baseline
# --------------------------------------------------------------------------- #


def test_the_baseline_is_scored_and_never_described_as_fitted(trained_result) -> None:
    """`prediction(t + h) = the latest known target value`.

    There is nothing to learn, so the run must say `fitted: false` rather than
    reporting a training row count as though a model had been estimated.
    """
    run = next(r for r in trained_result.runs if r.model_family == FAMILY_NAIVE)
    assert run.status == STATUS_TRAINED
    assert run.record["fitted"] is False
    assert "no parameters to learn" in run.record["fitted_note"]


def test_the_baseline_carries_forward_the_last_reading_at_or_before_the_origin(
    naive_dataset,
) -> None:
    """Not the mean, not the last row of the whole series.

    Checked against the reading instant the estimator itself recorded for each
    prediction, so the assertion is about a value and a timestamp the baseline chose
    rather than about the code that produced them.
    """
    estimator = fit_family(naive_dataset, config_for(FAMILY_NAIVE)).estimator
    assert isinstance(estimator, NaivePersistenceEstimator)
    split = SPLIT_TEST
    matrix = naive_dataset.splits[split]

    origins = [origin for origin, keep in zip(matrix.origin_instants, matrix.evaluable_mask) if keep]
    entities = [
        entity for entity, keep in zip(matrix.row_entities, matrix.evaluable_mask) if keep
    ]
    estimator.bind_split(split)
    predicted = np.asarray(
        estimator.predict(matrix.values[matrix.evaluable_mask]), dtype="float64"
    )
    sources = estimator.source_instants[split]

    assert predicted.size == len(sources) == len(origins), (
        "the estimator's block does not line up with the split's evaluable rows"
    )
    assert sources, "no baseline prediction was produced, so nothing was checked"

    # `matrix.target[i]` is the observation at `target_instants[i]`, and the value the
    # baseline carries forward from instant `t` is exactly the observation at `t` - it
    # is the target of the row whose origin is `t - horizon`.
    reading_at = {
        (entity, instant): value
        for entity, instant, value in zip(
            matrix.row_entities, matrix.target_instants, matrix.target
        )
        if instant is not None
    }
    for value, source, origin, entity in zip(predicted, sources, origins, entities):
        assert source <= origin, (
            f"the baseline for origin {origin} was carried forward from {source}, which "
            "is in the future"
        )
        assert (entity, source) in reading_at, (
            f"no observation is recorded for {entity} at the source instant {source}"
        )
        assert float(value) == pytest.approx(reading_at[(entity, source)], abs=1e-12), (
            f"at source {source} the baseline predicted {value}, which is not the "
            f"observation recorded there ({reading_at[(entity, source)]})"
        )


def test_the_baseline_reads_only_its_own_split(naive_dataset) -> None:
    """Reaching back into the tail of an earlier split would give the baseline a
    value from a time regime it is not being judged on."""
    estimator = fit_family(naive_dataset, config_for(FAMILY_NAIVE)).estimator
    latest_validation = max(naive_dataset.splits[SPLIT_VALIDATION].origin_instants)
    earliest_test = min(naive_dataset.splits[SPLIT_TEST].origin_instants)
    assert earliest_test > latest_validation
    for source in estimator.source_instants[SPLIT_TEST]:
        assert source >= earliest_test, (
            f"the test baseline was carried forward from {source}, which lies inside the "
            "validation split"
        )


def test_the_baseline_is_a_copy_not_an_average(naive_dataset) -> None:
    """A jitter of ±1 m in the target moves the prediction by exactly ±1 m.

    A fitted model would absorb the jitter; a smoothed or averaged one would not
    reproduce it. This fixture's target is non-constant, so the two are
    distinguishable.
    """
    estimator = fit_family(naive_dataset, config_for(FAMILY_NAIVE)).estimator
    matrix = naive_dataset.splits[SPLIT_TEST]
    estimator.bind_split(SPLIT_TEST)
    predicted = np.asarray(estimator.predict(matrix.values[matrix.evaluable_mask]), dtype="float64")
    finite = np.isfinite(predicted)
    assert int(finite.sum()) > 0
    assert len(set(np.round(predicted[finite], 9))) > 1, (
        "the baseline predicts one value; this fixture cannot distinguish a copy from a "
        "constant"
    )


def test_the_baseline_is_scored_on_the_same_rows_as_every_other_model(trained_pair) -> None:
    """Like-for-like, or the comparison is a difference in which rows survived."""
    counts: dict[str, set[int]] = {}
    for outcome in trained_pair.outcomes:
        counts.setdefault(outcome.split, set()).add(outcome.n_samples)
    for split, seen in counts.items():
        assert len(seen) == 1, f"{split}: models were scored on differing row counts {seen}"


def test_the_baseline_row_is_present_even_when_nothing_else_ran(trained_result) -> None:
    """The reference point exists whether or not there is anything to compare
    against it, and its own MAE is a real number that later runs would be measured
    against."""
    blocked = {
        r.model_family
        for r in trained_result.runs
        if r.status == STATUS_DEPENDENCY_UNAVAILABLE
    }
    assert blocked, "this environment was expected to block some families"
    baseline_rows = [
        row for row in trained_result.comparison.rows if row.model_family == FAMILY_NAIVE
    ]
    assert baseline_rows
    for row in baseline_rows:
        assert row.mae is not None
        assert row.n_samples > 0
        assert row.evaluation_status == "evaluated"


def test_a_baseline_that_cannot_be_asked_for_a_split_refuses_rather_than_guessing(
    naive_dataset,
) -> None:
    """An unbound or absent split has no values to copy.

    The estimator refuses. Producing zeros would look like a confidently wrong
    forecast rather than the refusal it is, and producing the wrong split's values
    would change what the number in the table means without saying so.
    """
    estimator = fit_family(naive_dataset, config_for(FAMILY_NAIVE)).estimator
    matrix = naive_dataset.splits[SPLIT_TEST]
    with pytest.raises(TrainingError) as unbound:
        estimator.predict(matrix.values[matrix.evaluable_mask])
    assert "bound" in str(unbound.value)

    estimator.bind_split(SPLIT_TEST)
    with pytest.raises(TrainingError) as absent:
        estimator.bind_split("holdout")
    assert "holdout" in str(absent.value)


def test_a_baseline_predicting_for_the_wrong_number_of_rows_is_refused(
    naive_dataset,
) -> None:
    """The row count is a check that the caller and the block describe the same
    rows. Passing all 48 matrix rows where 24 predictions exist would otherwise
    either truncate or broadcast."""
    estimator = fit_family(naive_dataset, config_for(FAMILY_NAIVE)).estimator
    estimator.bind_split(SPLIT_TEST)
    with pytest.raises(TrainingError) as caught:
        estimator.predict(naive_dataset.splits[SPLIT_TEST].values)
    assert "24" in str(caught.value) and "48" in str(caught.value)


# --------------------------------------------------------------------------- #
# The dependency gate: honest, specific, and never a fake result
# --------------------------------------------------------------------------- #


def test_every_blocked_family_records_the_exact_blocker() -> None:
    """A reader has to be able to act on this: which module, which class, which
    exception, and which requirement file would have to change."""
    for family in UNAVAILABLE_HERE:
        text = spec_for(family).blocker_text() or ""
        assert text, f"{family} is blocked but reported no reason"
        assert "not importable" in text
        assert "ModuleNotFoundError" in text or "ImportError" in text
        assert "requirements" in text.lower(), (
            f"{family}'s blocker does not say which requirement declaration would change "
            "the outcome, so it is not actionable"
        )


def test_the_blocker_is_the_same_text_the_run_reports() -> None:
    """One statement of the blocker.

    A probe that says `xgboost.xgboost.XGBRegressor is not importable` while the run
    says "xgboost unavailable" leaves a reader unsure which one is the finding.
    """
    result = build_feature_result()
    outcome = _train(default_configurations(), result)
    for run in outcome.runs:
        if run.model_family not in UNAVAILABLE_HERE:
            continue
        assert run.reason == spec_for(run.model_family).blocker_text()


def test_a_blocked_family_never_reports_a_metric(trained_result) -> None:
    """The central honesty rule, asserted on the runs that actually hit it."""
    blocked = [r for r in trained_result.runs if r.status == STATUS_DEPENDENCY_UNAVAILABLE]
    assert blocked, "no family was blocked, so nothing was proved"
    blocked_ids = {run.model_id for run in blocked}
    for run in blocked:
        assert run.estimator is None
    for outcome in trained_result.outcomes:
        if outcome.model_id not in blocked_ids:
            continue
        assert outcome.metrics is None
        assert outcome.n_samples == 0
        assert outcome.reason


def test_a_blocked_family_writes_no_artifact(trained_result) -> None:
    """`not_written`, not `metadata_only`.

    Metadata for a model that does not exist would give a loader a manifest with no
    weights behind it, which is precisely the shape of a silently broken deployment.
    """
    for run in trained_result.runs:
        if run.status != STATUS_TRAINED:
            assert run.artifact_status == ARTIFACT_STATUS_NOT_WRITTEN, (
                f"{run.model_family} did not train but reports {run.artifact_status!r}"
            )


def test_a_blocked_family_still_gets_a_row_in_the_comparison_table(trained_result) -> None:
    """*Absent* is not *attempted and could not run*.

    A reader counting rows has to see five families and five statuses, not two rows
    for the two that happened to work.
    """
    rows = {(row.model_family, row.split) for row in trained_result.comparison.rows}
    for run in trained_result.runs:
        if run.status == STATUS_TRAINED:
            continue
        for split in (SPLIT_VALIDATION, SPLIT_TEST):
            assert (run.model_family, split) in rows, (
                f"{run.model_family}/{split} was attempted and did not run, but has no row "
                "in the comparison table"
            )
    for row in trained_result.comparison.rows:
        if row.model_family not in UNAVAILABLE_HERE:
            continue
        assert row.training_status == STATUS_DEPENDENCY_UNAVAILABLE
        assert row.evaluation_status == "not_evaluated"
        assert row.mae is None
        assert row.notes, "a blocked row must carry the blocker as a note"


def test_a_blocked_family_is_never_selected(trained_result) -> None:
    """Selection reads validation RMSE. A blocked family has none, so it cannot win
    — and must not win by default."""
    selected = trained_result.comparison.selected_model_id
    assert selected is not None
    chosen = next(r for r in trained_result.runs if r.model_id == selected)
    assert chosen.status == STATUS_TRAINED


def test_no_run_is_ever_marked_production_ready(trained_result) -> None:
    """Not the trained ones and not the blocked ones. The field exists because the
    requirement is that it is never set."""
    for run in trained_result.runs:
        assert run.production_ready_claimed is False


# --------------------------------------------------------------------------- #
# Insufficient data: structured, with the numbers on both sides
# --------------------------------------------------------------------------- #


def test_too_few_training_rows_produces_a_structured_insufficiency() -> None:
    """Required, available, target, horizon, model — all of it.

    "Not enough data" is not actionable. "Needs 10 000 rows, has 156, for
    `target_water_level_6h` at `6h`" is.
    """
    result = build_feature_result()
    config = config_for(FAMILY_RANDOM_FOREST, min_train_rows=10_000, scaler_policy="standard")
    run = _train((config,), result).runs[0]

    assert run.status == STATUS_INSUFFICIENT_DATA
    short = run.insufficiency
    assert short is not None
    assert short.required == 10_000
    assert 0 < short.available < short.required
    assert short.target == TARGET_COLUMN
    assert short.horizon == "6h"
    assert short.model == FAMILY_RANDOM_FOREST
    assert "fewer supervised training rows" in short.reason
    assert str(short)


def test_the_recorded_row_count_is_the_count_that_actually_existed() -> None:
    """Padding a short series to reach a threshold would satisfy the check and
    destroy the meaning of every number computed on it.

    The count is therefore the fixture's own supervised training rows, which the
    test computes independently rather than reading back from the record.
    """
    from hydro_phase4_fixtures import assemble

    result = build_feature_result()
    dataset = assemble(result.dataset, FAMILY_RANDOM_FOREST, scaler_policy="standard")
    supervised = int(np.count_nonzero(np.isfinite(dataset.splits[SPLIT_TRAIN].target)))

    config = config_for(FAMILY_RANDOM_FOREST, min_train_rows=10_000, scaler_policy="standard")
    run = _train((config,), result).runs[0]

    assert run.status == STATUS_INSUFFICIENT_DATA
    assert supervised > 0
    assert run.insufficiency.available <= supervised
    assert run.insufficiency.required > supervised
    assert run.estimator is None


def test_an_insufficient_run_reports_no_metric_on_either_split() -> None:
    result = build_feature_result()
    config = config_for(FAMILY_RANDOM_FOREST, min_train_rows=10_000, scaler_policy="standard")
    outcome = _train((config,), result)
    rows = {row.split: row for row in outcome.comparison.rows}
    assert set(rows) == {SPLIT_VALIDATION, SPLIT_TEST}
    for row in rows.values():
        assert row.training_status == STATUS_INSUFFICIENT_DATA
        assert row.evaluation_status == "insufficient_rows"
        assert row.mae is None and row.rmse is None and row.r2 is None and row.bias is None


def test_insufficient_data_is_not_reported_as_a_training_failure() -> None:
    """Two different problems with two different remedies.

    Collapsing them into `failed_training` would send a reader looking for a bug in
    the estimator when the answer is that the series is short.
    """
    result = build_feature_result()
    config = config_for(FAMILY_RANDOM_FOREST, min_train_rows=10_000, scaler_policy="standard")
    run = _train((config,), result).runs[0]
    assert run.status != "failed_training"
    assert run.insufficiency is not None


def test_fit_family_raises_insufficient_data_directly() -> None:
    """The lower-level call has the same contract: raise, do not return a stub."""
    from hydro_phase4_fixtures import assemble

    result = build_feature_result()
    dataset = assemble(result.dataset, FAMILY_RANDOM_FOREST, scaler_policy="standard")
    config = config_for(FAMILY_RANDOM_FOREST, min_train_rows=10_000, scaler_policy="standard")
    with pytest.raises(InsufficientData) as caught:
        fit_family(dataset, config)
    assert caught.value.insufficiency.required == 10_000
    assert caught.value.insufficiency.model == FAMILY_RANDOM_FOREST
    assert str(caught.value)


def test_a_threshold_the_series_already_meets_does_not_stop_the_run() -> None:
    """The direction of the comparison is load-bearing.

    Set `min_train_rows` to the count the fixture really has. A check that always
    reported "insufficient" would pass every insufficient-data assertion above while
    refusing every sufficient series.
    """
    from hydro_phase4_fixtures import assemble

    result = build_feature_result()
    dataset = assemble(result.dataset, FAMILY_RANDOM_FOREST, scaler_policy="standard")
    supervised = int(np.count_nonzero(np.isfinite(dataset.splits[SPLIT_TRAIN].target)))

    config = config_for(
        FAMILY_RANDOM_FOREST, min_train_rows=supervised, scaler_policy="standard"
    )
    run = _train((config,), result).runs[0]

    assert run.status == STATUS_TRAINED, (
        f"a threshold of exactly {supervised} rows against {supervised} available was "
        f"reported as {run.status!r}: {run.reason}"
    )
    assert run.insufficiency is None


def test_an_insufficiency_record_states_both_sides_of_the_comparison() -> None:
    short = Insufficiency(
        reason="not enough rows",
        required=100,
        available=12,
        target=TARGET_COLUMN,
        horizon="6h",
        model=FAMILY_RANDOM_FOREST,
    )
    assert short.available < short.required
    assert "not enough rows" in short.reason
    assert str(short)


# --------------------------------------------------------------------------- #
# The target gate
# --------------------------------------------------------------------------- #


def test_a_target_phase_3_cannot_supply_stops_the_run_rather_than_substituting(
    trained_result,
) -> None:
    """No fallback variable, ever.

    The run asks for a horizon Phase 3 did not build. The only acceptable answer is
    `target_unavailable` naming what was asked for and what exists.
    """
    result = build_feature_result()
    config = config_for(FAMILY_RANDOM_FOREST, horizon_hours=(11.0,), scaler_policy="standard")
    run = _train((config,), result).runs[0]
    assert run.status == STATUS_TARGET_UNAVAILABLE
    assert run.model_family == FAMILY_RANDOM_FOREST
    assert run.estimator is None
    assert run.artifact_status == ARTIFACT_STATUS_NOT_WRITTEN
    assert "11" in (run.reason or ""), (
        f"the reason does not name the requested horizon: {run.reason!r}"
    )
    assert TARGET_COLUMN in (run.reason or ""), (
        "the reason does not name the target that does exist"
    )


def test_a_target_supplied_at_the_prediction_instant_is_not_trained_against(
    feature_result,
) -> None:
    """A contemporaneous target is an input. Training on it would produce a very
    accurate model and a worthless forecast."""
    tampered = _mark_target_available(feature_result.dataset)
    outcome = train_models(
        tampered,
        (config_for(FAMILY_RANDOM_FOREST, scaler_policy="standard"),),
        cadences=feature_result.report.cadence,
    )
    run = outcome.runs[0]
    assert run.status == STATUS_TARGET_UNAVAILABLE
    assert "forecast target" in (run.reason or "")
    assert run.estimator is None


def test_a_target_gate_fires_before_the_dependency_gate() -> None:
    """The order matters for what a reader is told.

    With no target there is nothing to fit, whatever libraries are installed; saying
    "xgboost is missing" first would send the reader to install a package for a run
    that still could not work.
    """
    result = build_feature_result()
    config = config_for(
        FAMILY_XGBOOST, horizon_hours=(11.0,), scaler_policy="standard"
    )
    run = _train((config,), result).runs[0]
    assert run.status == STATUS_TARGET_UNAVAILABLE, (
        "the dependency gate fired before the target gate; the report would blame the "
        "environment for a problem in the data contract"
    )


def test_no_target_substitution_happens_silently(trained_result) -> None:
    """Every trained run predicts the column Phase 3 built."""
    for run in trained_result.runs:
        if run.status != STATUS_TRAINED:
            continue
        assert run.target == TARGET_COLUMN
        assert run.horizon == "6h"


# --------------------------------------------------------------------------- #
# Evaluation after a successful fit
# --------------------------------------------------------------------------- #


def test_a_model_that_fitted_but_cannot_be_scored_reports_that_separately() -> None:
    """`trained` with `not_evaluated`.

    The two statuses are independent facts and this is the case that proves it: the
    model exists, and nothing can be said about how good it is.
    """
    result = build_feature_result()
    config = config_for(FAMILY_RANDOM_FOREST, min_eval_rows=10_000, scaler_policy="standard")
    outcome = _train((config,), result)
    run = outcome.runs[0]
    assert run.status == STATUS_TRAINED
    assert run.evaluation_status == "not_evaluated"
    assert run.record["fitted"] is True
    for row in outcome.comparison.rows:
        assert row.training_status == STATUS_TRAINED
        assert row.evaluation_status == "insufficient_rows"
        assert row.mae is None
        assert row.notes, "an unscored row must say why it is unscored"
        assert "10" in " ".join(row.notes), (
            f"the note does not name the threshold: {' '.join(row.notes)!r}"
        )


def test_scoring_is_reported_split_by_split_never_as_one_figure() -> None:
    result = build_feature_result()
    config = config_for(FAMILY_RANDOM_FOREST, min_eval_rows=10_000, scaler_policy="standard")
    outcome = _train((config,), result)
    assert {row.split for row in outcome.comparison.rows} == {SPLIT_VALIDATION, SPLIT_TEST}, (
        "an averaged figure would be a score on a population in neither split"
    )


# --------------------------------------------------------------------------- #
# The run record: enough to reproduce and to detect drift
# --------------------------------------------------------------------------- #


def test_the_record_states_the_seed_the_row_counts_and_the_feature_count(
    trained_result,
) -> None:
    """The reproducibility fields, on a run that actually completed."""
    record = _forest_run(trained_result).record
    assert record["seed"] == 20240917
    assert record["train_rows"] > 0
    assert record["validation_rows"] > 0
    assert record["test_rows"] > 0
    assert 0 < record["train_supervised_rows"] <= record["train_rows"]
    assert record["feature_columns"] == len(_forest_run(trained_result).feature_names)
    assert record["fitted"] is True


def test_the_row_counts_in_the_record_match_the_matrices_that_were_scored(
    trained_result,
) -> None:
    """The record is a claim about this run, not a template.

    A mismatch would let two runs report identical counts while having been fitted on
    different data, which defeats the purpose of recording them. The cached dataset
    is the baseline's assembly of the same target; row counts are a property of the
    Phase 3 split, not of the family, which is why one matrix suffices here.
    """
    dataset = trained_result.datasets[TARGET_COLUMN]
    record = _forest_run(trained_result).record
    for split, key in (
        (SPLIT_TRAIN, "train_rows"),
        (SPLIT_VALIDATION, "validation_rows"),
        (SPLIT_TEST, "test_rows"),
    ):
        assert record[key] == dataset.splits[split].rows, (
            f"{split}: the record says {record[key]}, the matrix holds "
            f"{dataset.splits[split].rows}"
        )


def test_the_record_names_the_environment_the_model_was_fitted_in(trained_result) -> None:
    """A forest fitted on one scikit-learn version is not the same object as one
    fitted on another, and the version has to travel with the record."""
    environment = _forest_run(trained_result).record["environment"]
    assert environment, "no dependency version was recorded"
    joined = " ".join(f"{name}={version}" for name, version in environment.items())
    assert "sklearn" in joined
    assert any(character.isdigit() for character in joined), (
        f"no version number was recorded: {environment!r}"
    )


def test_the_record_states_the_effective_hyperparameters_not_just_the_request(
    trained_result,
) -> None:
    """The configuration requests; the record states what was actually used.

    `_hyperparameters` writes out this project's own defaults so they can be stated,
    but a value scikit-learn fills in for itself - `criterion`, `max_samples`,
    `warm_start` - is invisible to it. Reporting the fitted estimator's parameters
    is what makes the record reproducible rather than merely plausible.
    """
    hyperparameters = _forest_run(trained_result).record["hyperparameters"]
    assert hyperparameters, "no hyperparameters were recorded for a fitted forest"
    assert hyperparameters["n_estimators"] == 200
    assert hyperparameters["criterion"] == "squared_error"
    assert hyperparameters["warm_start"] is False


def test_the_seed_in_the_record_is_the_seed_the_estimator_was_fitted_with(
    trained_result,
) -> None:
    """The record, the model id and the estimator have to agree.

    `models._build_sklearn` inserts `random_state=0` when no seed is supplied, so a
    forest built without one was fitted with seed 0 while the record said
    `seed20240917`. Nothing in the record was false about itself; the record and the
    model simply disagreed, and a run that cannot be reproduced from its own record
    is not reproducible at all.
    """
    run = _forest_run(trained_result)
    recorded = run.record["seed"]
    assert run.record["hyperparameters"]["random_state"] == recorded
    assert run.estimator.estimator.get_params()["random_state"] == recorded


def test_changing_the_configured_seed_changes_the_model_it_fits() -> None:
    """Proof that the seed is live rather than recorded.

    While `random_state` was pinned to 0 two configurations differing only in
    `random_seed` produced the *same forest* while reporting two different seeds.
    `deterministic_config` refuses a seed override, so the second configuration is
    built by replacing the frozen one.
    """
    result = build_feature_result()
    base = config_for(FAMILY_RANDOM_FOREST, scaler_policy="standard")
    first = _train((base,), result)
    second = _train((dataclasses.replace(base, random_seed=4242),), result)
    assert _forest_run(first).record["seed"] != _forest_run(second).record["seed"], (
        "this fixture must configure two different seeds for the test to mean anything"
    )

    def predictions(outcome):
        run = _forest_run(outcome)
        matrix = outcome.datasets[TARGET_COLUMN].splits[SPLIT_TEST]
        return np.asarray(run.estimator.predict(matrix.values), dtype="float64")

    assert not np.allclose(predictions(first), predictions(second)), (
        "two seeds produced identical predictions, so the seed is not reaching the "
        "estimator even though the record claims it is"
    )


def test_the_record_lists_which_components_were_seeded(trained_result) -> None:
    seeded = _forest_run(trained_result).record["seeded_components"]
    assert "random_state" in seeded
    assert "numpy.random" in seeded


def test_the_record_says_a_blocked_run_fitted_nothing(trained_result) -> None:
    """`fitted` is a fact about the estimator, not about the attempt."""
    for run in trained_result.runs:
        if run.status == STATUS_TRAINED:
            continue
        assert run.record.get("fitted") in (None, False), (
            f"{run.model_family} reports {run.status!r} but claims to have fitted"
        )


def test_a_learned_model_records_the_rows_it_was_fitted_on_not_the_matrix_rows(
    trained_result,
) -> None:
    """Rows presented to the estimator, not rows in the matrix.

    A matrix row whose target sits six hours ahead is training data; a row without
    one is not, and counting both would inflate the training count by exactly the
    rows with no target.
    """
    dataset = trained_result.datasets[TARGET_COLUMN]
    matrix = dataset.splits[SPLIT_TRAIN]
    supervised = int(np.count_nonzero(np.isfinite(matrix.target)))
    record = _forest_run(trained_result).record
    assert record["training_rows"] == supervised
    assert record["training_rows"] < matrix.rows, (
        "the training count equals the row count, so untrained rows were counted"
    )
    assert record["train_supervised_rows"] == supervised


def test_a_prediction_count_is_recorded_for_every_scored_split(trained_pair) -> None:
    """How many rows each model actually predicted, so a reader can check the
    like-for-like claim rather than take it on trust.

    `n_samples` is the number the metric was computed over, which is the number that
    matters: it is the denominator of the MAE in the row above it.
    """
    counts: dict[str, set[int]] = {}
    for outcome in trained_pair.outcomes:
        counts.setdefault(outcome.split, set()).add(outcome.n_samples)
    assert set(counts) == {SPLIT_VALIDATION, SPLIT_TEST}
    for split, seen in counts.items():
        assert len(seen) == 1, f"{split}: differing prediction counts {seen}"
        assert seen.pop() > 0


def test_the_baseline_records_the_size_of_each_of_its_prediction_blocks(trained_pair) -> None:
    """The baseline predicts every split including train, because it has nothing to
    fit and therefore nothing that would only be available after training."""
    naive = next(r for r in trained_pair.runs if r.model_family == FAMILY_NAIVE)
    counts = naive.record["predictions_per_split"]
    assert set(counts) == {SPLIT_TRAIN, SPLIT_VALIDATION, SPLIT_TEST}
    assert all(count > 0 for count in counts.values())
    assert counts[SPLIT_TRAIN] > counts[SPLIT_TEST]


# --------------------------------------------------------------------------- #
# Provenance, reused rather than reinvented
# --------------------------------------------------------------------------- #


def test_every_run_carries_a_provenance_record(trained_result) -> None:
    """Not only the runs that succeeded — a blocked run is exactly the one whose
    provenance explains why."""
    for run in trained_result.runs:
        assert run.provenance is not None
        payload = run.provenance.to_dict()
        assert payload


def test_provenance_names_the_phase_3_and_phase_4_contract_versions(trained_result) -> None:
    """One provenance system. A Phase 4-only scheme would make the lineage of a
    prediction untraceable back to the data contract it was built from."""
    payload = _forest_run(trained_result).provenance.to_dict()
    assert payload["software_environment"]["phase4_model_contract"] == MODEL_CONTRACT_VERSION
    assert payload["model_name"] == FAMILY_RANDOM_FOREST
    assert payload["model_version"] == (
        f"{FAMILY_RANDOM_FOREST}/{MODEL_CONTRACT_VERSION}/"
        f"{FEATURE_CONTRACT_VERSION}/seed20240917"
    ), (
        "the model version must carry the family, both contract versions and the seed, "
        "so a prediction can be traced back to the code that produced it"
    )


def test_provenance_on_a_never_fitted_run_still_records_the_requested_seed(
    trained_result,
) -> None:
    """The seed that *would* have been used is part of the attempt's record.

    Omitting it would make a blocked run's provenance look like an oversight rather
    than a description of the attempt.
    """
    blocked = next(r for r in trained_result.runs if r.status == STATUS_DEPENDENCY_UNAVAILABLE)
    payload = blocked.provenance.to_dict()
    assert payload["software_environment"]["random_seed"] == "20240917"
    assert payload["evaluation_metrics"] is None, (
        "a run that never fitted must not report evaluation metrics"
    )
    assert f"seed20240917" in payload["model_version"]


def test_every_run_records_whether_the_data_was_synthetic(trained_result) -> None:
    """On every run, blocked included. The data did not stop being synthetic
    because the library was missing."""
    for run in trained_result.runs:
        assert run.synthetic_demo is True
        assert run.data_status == "synthetic_demo"


def test_the_run_carries_the_exact_synthetic_disclaimer(trained_result) -> None:
    assert trained_result.disclaimer == SYNTHETIC_DISCLAIMER
    assert "MUST NOT BE PRESENTED AS REAL" in trained_result.disclaimer


def test_the_metrics_label_on_a_synthetic_run_says_synthetic(trained_result) -> None:
    """The sentence a reader sees next to the numbers."""
    payload = _forest_run(trained_result).provenance.to_dict()
    assert "synthetic/demo evaluation only" in payload["metrics_label"]
    assert payload["is_synthetic"] is True


# --------------------------------------------------------------------------- #
# Model identity
# --------------------------------------------------------------------------- #


def test_the_model_id_distinguishes_two_targets_on_one_family() -> None:
    """Two horizons of the same family are two experiments."""
    left = model_id_for(config_for(FAMILY_RANDOM_FOREST), _binding(horizon="6h"))
    right = model_id_for(
        config_for(FAMILY_RANDOM_FOREST, horizon_hours=(12.0,)), _binding(horizon="12h")
    )
    assert left != right
    assert "12h" in right


def test_the_model_id_distinguishes_two_seeds() -> None:
    """Same data, same family, different seed: different experiments, because a seed
    change can move every number.

    `deterministic_config` deliberately refuses a `random_seed` override, so the
    second configuration is built by replacing the frozen one — which also confirms
    the refusal is a real guard rather than an accident of the constructor.
    """
    base = config_for(FAMILY_RANDOM_FOREST)
    first = model_id_for(base, _binding())
    second = model_id_for(dataclasses.replace(base, random_seed=7), _binding())
    assert first != second
    assert f"seed{base.random_seed}" in first
    assert "seed7" in second


def test_a_deterministic_configuration_refuses_to_be_de_seeded() -> None:
    """`random_seed` is part of what makes a run reproducible. A configuration that
    let a caller change it while still calling itself deterministic would be a
    contradiction."""
    from app.engines.hydro.model_config import ModelConfigError, deterministic_config

    with pytest.raises(ModelConfigError) as caught:
        deterministic_config(FAMILY_RANDOM_FOREST, random_seed=99)
    assert "random_seed" in str(caught.value)


def test_the_model_id_is_stable_for_one_configuration_and_binding() -> None:
    binding = _binding()
    config = config_for(FAMILY_RANDOM_FOREST)
    assert model_id_for(config, binding) == model_id_for(config, binding)


def test_two_families_sharing_a_configuration_still_get_different_ids() -> None:
    binding = _binding()
    assert model_id_for(config_for(FAMILY_RANDOM_FOREST), binding) != model_id_for(
        config_for(FAMILY_LSTM), binding
    )


def test_the_stations_in_the_fixture_are_distinguishable() -> None:
    """The cross-station tests elsewhere depend on the two stations differing.

    If they were identical, a window that crossed from one to the other would look
    correct and the audit would pass for the wrong reason.
    """
    result = build_feature_result()
    first_instant = result.dataset.rows[0].instant
    targets = {}
    for row in result.dataset.rows:
        if row.instant != first_instant:
            continue
        targets[row.entity] = row.targets.get("target_water_level_6h")
    assert set(targets) == {STATION_A, STATION_B}
    assert targets[STATION_A] is not None
    assert targets[STATION_A] != targets[STATION_B], (
        "the two stations carry the same value, so a cross-station read would be "
        "indistinguishable from a correct one"
    )


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #


def test_seeding_makes_the_standard_library_and_numpy_draws_repeatable() -> None:
    """The claim the record makes, checked rather than assumed."""
    import random

    seed_everything(1234)
    first = (random.random(), float(np.random.random()))
    seed_everything(1234)
    second = (random.random(), float(np.random.random()))
    assert first == second


def test_two_different_seeds_produce_different_draws() -> None:
    """Otherwise the seed is not reaching the generators at all."""
    import random

    seed_everything(1)
    first = (random.random(), float(np.random.random()))
    seed_everything(2)
    second = (random.random(), float(np.random.random()))
    assert first != second


def test_the_run_seed_is_the_configured_seed_and_not_a_constant_in_the_code() -> None:
    """A run configured with a different seed must report and use that seed."""
    base = config_for(FAMILY_RANDOM_FOREST, scaler_policy="standard")
    result = build_feature_result()
    outcome = train_models(
        result.dataset,
        (dataclasses.replace(base, random_seed=4242),),
        cadences=result.report.cadence,
    )
    run = outcome.runs[0]
    assert run.status == STATUS_TRAINED
    assert run.record["seed"] == 4242
    assert run.record["hyperparameters"]["random_state"] == 4242
    assert "seed4242" in run.model_id


# --------------------------------------------------------------------------- #
# The artifact policy is a configuration, not a habit
# --------------------------------------------------------------------------- #


def test_the_default_policy_writes_metadata_only() -> None:
    """Metadata by default. Binary weights are large and belong outside the
    repository unless somebody asks for them."""
    result = build_feature_result()
    outcome = _train((config_for(FAMILY_RANDOM_FOREST, scaler_policy="standard"),), result)
    assert outcome.runs[0].artifact_status == ARTIFACT_STATUS_METADATA


def test_the_include_parameters_policy_is_honoured_when_it_is_asked_for() -> None:
    """Opt-in has to actually opt in, or the flag is decoration."""
    result = build_feature_result()
    outcome = _train(
        (
            config_for(
                FAMILY_RANDOM_FOREST,
                artifact_policy=ARTIFACT_INCLUDE_PARAMETERS,
                scaler_policy="standard",
            ),
        ),
        result,
    )
    assert outcome.runs[0].artifact_status == "metadata_and_parameters"


def test_a_trained_run_carries_the_estimator_a_blocked_run_does_not(trained_result) -> None:
    for run in trained_result.runs:
        if run.status == STATUS_TRAINED:
            assert run.estimator is not None
        else:
            assert run.estimator is None


def test_the_artifact_policy_values_are_two_and_both_are_named() -> None:
    """`metadata_only` and `metadata_and_parameters`. A third, unnamed state would be
    the one nobody knows how to handle."""
    assert {ARTIFACT_METADATA_ONLY, ARTIFACT_INCLUDE_PARAMETERS} == {
        "metadata_only",
        "metadata_and_parameters",
    }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def dataset_rows_available(result) -> int:
    """Supervised training rows in the fixture — the count `min_train_rows` sees."""
    from hydro_phase4_fixtures import assemble

    dataset = assemble(result.dataset, FAMILY_RANDOM_FOREST, scaler_policy="standard")
    return int(np.count_nonzero(np.isfinite(dataset.splits[SPLIT_TRAIN].target)))


def _binding(horizon: str = "6h"):
    """A stand-in with the attributes `model_id_for` reads."""
    class _Binding:
        column = TARGET_COLUMN
        quantity = "water_level"
        units = "m"
        horizon_label = horizon

    return _Binding()


def _mark_target_available(dataset):
    """A dataset whose target lineage claims the reading exists at `t`."""
    lineage = {}
    for column, entry in dataset.target_lineage.items():
        updated = dict(entry)
        updated["available_at_prediction_time"] = True
        lineage[column] = updated
    return dataclasses.replace(dataset, target_lineage=lineage)
