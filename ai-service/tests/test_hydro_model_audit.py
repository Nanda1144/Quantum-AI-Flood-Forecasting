# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 4 — the leakage audit, and the mutation tests that prove it can fail.

An audit that only ever runs on clean data is a report, not a check. Half of this
file therefore does something deliberate and wrong to a fixture and asserts that the
named check catches it: a feature reading from after its own origin, a target whose
reading lands before the origin instead of after, a horizon nudged by an hour, a
target column renamed into the feature list, a scaler whose fitted mean is not the
training mean, a split matrix filed under a label it does not carry, a sequence
window that reaches one step past its origin, a window one row longer than the
declared lookback, and a window that held two stations' rows.

Three of those mutations were found to *pass* while this file was being written,
and the check was changed rather than the test. That is the point of writing the
mutation tests: a check that cannot fail is not documenting a guarantee, and the
failures recorded here are the reason to prefer them over asserting on clean data.

Every value here is synthetic/demo data. No test asserts a hydrological result.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import numpy as np
import pytest

from hydro_phase4_fixtures import (
    SEQUENCE_LOOKBACK,
    STATION_A,
    STATION_B,
    assemble,
    build_feature_result,
    build_sequence_result,
    feature_result,
    sequence_dataset,
)

from app.engines.hydro.feature_pipeline import SPLIT_TEST, SPLIT_TRAIN, SPLIT_VALIDATION
from app.engines.hydro.model_audit import (
    AUDIT_CHECKS,
    CHECK_FEATURE_TARGET_DISJOINT,
    CHECK_FEATURES_AT_OR_BEFORE,
    CHECK_HORIZON_EXACT,
    CHECK_SEQUENCE_CAUSAL,
    CHECK_SPLIT_LABELS_INSIDE,
    CHECK_SPLIT_ORDERED,
    CHECK_TARGET_AFTER_ORIGIN,
    CHECK_TRAIN_FITTED_STATS,
    EXPECTED_SPLIT_ORDER,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIPPED,
    LeakageAudit,
    LeakageFinding,
    audit_leakage,
)
from app.engines.hydro.model_config import FAMILY_LSTM, FAMILY_NAIVE, FAMILY_RANDOM_FOREST

pytest_plugins: list[str] = []

#: The eight checks Phase 4 is required to run, spelled out rather than read back from
#: the module. If the declaration changes, this is the assertion that notices.
EXPECTED_CHECKS = (
    "features_read_at_or_before_origin",
    "target_instant_strictly_after_origin",
    "target_horizon_alignment_exact",
    "feature_columns_disjoint_from_targets",
    "split_origins_chronologically_ordered",
    "split_labels_do_not_cross_boundaries",
    "scaler_and_imputer_fitted_on_train_only",
    "sequence_windows_causal_and_entity_scoped",
)

HORIZON_SECONDS = 21600


def _status(dataset, check, sequences=None) -> str:
    return next(
        f.status for f in audit_leakage(dataset, sequences=sequences).findings
        if f.check == check
    )


def _finding(dataset, check, sequences=None) -> LeakageFinding:
    return next(
        f for f in audit_leakage(dataset, sequences=sequences).findings if f.check == check
    )


def _matrix_dataset(**changes):
    """The short fixture assembled under a forest configuration."""
    return assemble(build_feature_result().dataset, FAMILY_RANDOM_FOREST, **changes)


def _with_split(dataset, split_name, **changes):
    """A copy of `dataset` with one split matrix replaced."""
    part = dataset.splits[split_name]
    return dataclasses.replace(
        dataset, splits={**dataset.splits, split_name: dataclasses.replace(part, **changes)}
    )


def _one_hour_later(instant: dt.datetime) -> dt.datetime:
    return instant + dt.timedelta(hours=1)


def _scaled_dataset():
    """The short fixture with a fitted scaler and imputer, which one check needs."""
    return _matrix_dataset(scaler_policy="standard")


def _sequence_dataset(lookback: int = SEQUENCE_LOOKBACK):
    return assemble(
        build_sequence_result(),
        FAMILY_LSTM,
        lookback=lookback,
        scaler_policy="standard",
    )


def _blocks(dataset, lookback: int = SEQUENCE_LOOKBACK):
    """The window sets a real run hands the audit for every split."""
    from hydro_phase4_fixtures import config_for
    from app.engines.hydro.model_training import _sequence_blocks

    config = config_for(
        FAMILY_LSTM, lookback=lookback, scaler_policy="standard"
    )
    return _sequence_blocks(
        dataset, config, (SPLIT_TRAIN, SPLIT_VALIDATION, SPLIT_TEST)
    )


# --------------------------------------------------------------------------- #
# The audit declares and runs the eight required checks
# --------------------------------------------------------------------------- #


def test_the_audit_declares_the_eight_required_checks() -> None:
    """Spelled out here rather than read from the module.

    A test that asserts the module equals itself proves nothing; this one breaks the
    moment a check is renamed, dropped or quietly added.
    """
    assert AUDIT_CHECKS == EXPECTED_CHECKS, (
        "the declared check list changed; the requirement names eight specific checks "
        "and a reader needs to see the same eight"
    )
    assert len(AUDIT_CHECKS) == 8


def test_every_declared_check_runs_and_explains_itself() -> None:
    """A check that passes or fails with no `detail` is unfalsifiable to a reader."""
    audit = audit_leakage(_matrix_dataset())
    assert tuple(audit.names) == EXPECTED_CHECKS
    for finding in audit.findings:
        assert finding.status in (STATUS_PASS, STATUS_FAIL, STATUS_SKIPPED)
        assert finding.detail, f"{finding.check} reported a status with no explanation"


def test_a_clean_dataset_fails_nothing() -> None:
    """Nothing failed - and `ok` is still false, because one check could not run.

    `ok` is deliberately strict: it is true only when every check both ran and passed.
    A gate that reads `ok` therefore cannot be satisfied by a check that skipped
    itself, which is the only way a skip could be mistaken for a pass.
    """
    audit = audit_leakage(_matrix_dataset())
    assert audit.failed() == (), f"a clean fixture failed: {audit.failed()}"
    assert audit.ok is False, "the sequence check skipped, so `ok` cannot be true"
    for finding in audit.findings:
        assert finding.status in (STATUS_PASS, STATUS_SKIPPED)
        assert finding.offending_rows == 0


def test_a_clean_fully_checked_run_is_a_pass() -> None:
    """The verdict a run with sequence families configured reports."""
    dataset = _sequence_dataset()
    audit = audit_leakage(dataset, sequences=_blocks(dataset))
    assert audit.verdict == "PASS", audit.describe()
    assert audit.ok is True
    assert audit.failed() == ()
    assert audit.skipped_checks() == ()


def test_the_sequence_check_is_skipped_rather_than_passed_when_no_windows_exist() -> None:
    """A check that cannot run must not report a pass.

    Calling an unrun check `pass` is how a reader comes to believe a property was
    verified. `ok` stays true so a caller who only needs "nothing failed" is not
    blocked, and `skipped_checks()` is how the difference is found.
    """
    audit = audit_leakage(_matrix_dataset())
    finding = next(f for f in audit.findings if f.check == CHECK_SEQUENCE_CAUSAL)
    assert finding.status == STATUS_SKIPPED
    assert finding.ok is True, "`ok` covers skip so one unrunnable check is not a blocker"
    assert CHECK_SEQUENCE_CAUSAL in audit.skipped_checks()
    assert CHECK_SEQUENCE_CAUSAL not in audit.passed_checks


def test_an_audit_that_skipped_a_check_is_partial_not_a_clean_pass() -> None:
    """`PARTIAL` says "nothing failed, but not everything ran".

    That is the truth about a non-sequence family, and it is not the same statement
    as `PASS`.
    """
    audit = audit_leakage(_matrix_dataset())
    assert audit.verdict == "PARTIAL"
    assert audit.ok is False, "`ok` requires a pass from every check, not merely no failure"
    assert set(audit.passed_checks) < set(audit.names)


def test_the_audit_reaches_the_sequence_path_even_when_no_deep_learning_runtime_exists() -> None:
    """Auditing the sequence path only when TensorFlow happens to be installed would
    make the most safety-critical check the one that runs least often.

    Every sequence family in this environment is dependency-blocked, and the windows
    are still auditable: window construction needs NumPy and the Phase 3 cadence, not
    a deep-learning runtime.
    """
    dataset = _sequence_dataset()
    audit = audit_leakage(dataset, sequences=_blocks(dataset))
    finding = next(f for f in audit.findings if f.check == CHECK_SEQUENCE_CAUSAL)
    assert finding.status == STATUS_PASS, finding.detail
    assert audit.verdict == "PASS"


# --------------------------------------------------------------------------- #
# Mutation 1: a feature reading from after its own origin
# --------------------------------------------------------------------------- #


def test_a_feature_reading_from_after_the_origin_is_caught() -> None:
    """The most important check in the file.

    A feature computed from a reading that has not happened yet at the prediction
    instant is the failure mode this project exists to avoid. Lag features sit hours
    in the past, so the mutation moves a reading to exactly one hour *after* the
    origin: a shift of one hour is not enough to leak here, and a test that used one
    would pass on a leaking implementation.
    """
    dataset = _matrix_dataset()
    part = dataset.splits[SPLIT_TRAIN]
    poisoned = list(part.source_instants)
    poisoned[0] = (_one_hour_later(part.origin_instants[0]), *poisoned[0][1:])

    tampered = _with_split(dataset, SPLIT_TRAIN, source_instants=tuple(poisoned))
    finding = _finding(tampered, CHECK_FEATURES_AT_OR_BEFORE)
    assert finding.status == STATUS_FAIL
    assert finding.offending_rows == 1
    assert f"{SPLIT_TRAIN}[0]" in finding.detail, (
        f"the finding does not say which row: {finding.detail!r}"
    )
    assert audit_leakage(tampered).verdict == "FAIL"


def test_a_feature_reading_later_in_the_window_is_also_caught() -> None:
    """Not only the final column.

    Any reading past the origin leaks, wherever it sits in the list - so the mutation
    moves a *leading* reading, which is hours in the past, all the way past the
    origin.
    """
    dataset = _matrix_dataset()
    part = dataset.splits[SPLIT_TRAIN]
    row = list(part.source_instants[3])
    row[0] = _one_hour_later(part.origin_instants[3])
    poisoned = list(part.source_instants)
    poisoned[3] = tuple(row)

    tampered = _with_split(dataset, SPLIT_TRAIN, source_instants=tuple(poisoned))
    finding = _finding(tampered, CHECK_FEATURES_AT_OR_BEFORE)
    assert finding.status == STATUS_FAIL
    assert f"{SPLIT_TRAIN}[3]" in finding.detail


def test_a_reading_exactly_at_the_origin_is_allowed() -> None:
    """The guarantee is "at or before", not "strictly before".

    `water_level_lag_0h` is a legitimate feature: the level at the prediction instant
    is known then. A check that rejected it would push an author to delete a valid
    feature rather than fix the real bug.
    """
    dataset = _matrix_dataset()
    part = dataset.splits[SPLIT_TRAIN]
    poisoned = list(part.source_instants)
    poisoned[0] = (part.origin_instants[0], *poisoned[0][1:])
    tampered = _with_split(dataset, SPLIT_TRAIN, source_instants=tuple(poisoned))
    assert _status(tampered, CHECK_FEATURES_AT_OR_BEFORE) == STATUS_PASS


def test_the_offending_row_is_reported_with_its_split() -> None:
    """Row indices are per split.

    Row 3 of the training split and row 3 of the test split are different rows, so a
    bare `3` leaves a reader unable to tell which one to go and look at - which is the
    only reason the index is printed at all.
    """
    dataset = _matrix_dataset()
    part = dataset.splits[SPLIT_VALIDATION]
    poisoned = list(part.source_instants)
    poisoned[2] = (_one_hour_later(part.origin_instants[2]), *poisoned[2][1:])
    tampered = _with_split(dataset, SPLIT_VALIDATION, source_instants=tuple(poisoned))
    detail = _finding(tampered, CHECK_FEATURES_AT_OR_BEFORE).detail
    assert f"{SPLIT_VALIDATION}[2]" in detail
    assert f"{SPLIT_TRAIN}[2]" not in detail


# --------------------------------------------------------------------------- #
# Mutation 2: a target that is not in the future of its origin
# --------------------------------------------------------------------------- #


def test_a_target_reading_at_the_origin_instead_of_after_it_is_caught() -> None:
    """Training on a contemporaneous target produces a very accurate model and a
    worthless forecast."""
    dataset = _matrix_dataset()
    part = dataset.splits[SPLIT_TRAIN]
    tampered = _with_split(
        dataset, SPLIT_TRAIN, target_instants=tuple(part.origin_instants)
    )
    finding = _finding(tampered, CHECK_TARGET_AFTER_ORIGIN)
    assert finding.status == STATUS_FAIL
    assert finding.offending_rows > 0
    assert audit_leakage(tampered).verdict == "FAIL"


def test_a_target_reading_before_the_origin_is_caught() -> None:
    dataset = _matrix_dataset()
    part = dataset.splits[SPLIT_TRAIN]
    poisoned = [
        origin - dt.timedelta(hours=HORIZON_SECONDS // 3600 + 1) for origin in part.origin_instants
    ]
    tampered = _with_split(dataset, SPLIT_TRAIN, target_instants=tuple(poisoned))
    assert _status(tampered, CHECK_TARGET_AFTER_ORIGIN) == STATUS_FAIL


def test_a_target_a_second_after_the_origin_passes_the_after_origin_check() -> None:
    """Each check answers one question, and this is where the boundary sits.

    A target one second after the origin *is* after the origin, so
    `target_instant_strictly_after_origin` is right to accept it. It is not the right
    horizon though, and `target_horizon_alignment_exact` is the check that says so.
    Keeping the two apart matters: collapsing them would mean the horizon was never
    verified on its own, and the horizon is what the model id and the registry name.
    """
    dataset = _matrix_dataset()
    part = dataset.splits[SPLIT_TRAIN]
    poisoned = [
        origin + dt.timedelta(seconds=1) for origin in part.origin_instants
    ]
    tampered = _with_split(dataset, SPLIT_TRAIN, target_instants=tuple(poisoned))
    assert _status(tampered, CHECK_TARGET_AFTER_ORIGIN) == STATUS_PASS
    assert _status(tampered, CHECK_HORIZON_EXACT) == STATUS_FAIL, (
        "a one-second misalignment must be caught by the horizon check"
    )


# --------------------------------------------------------------------------- #
# Mutation 3: the horizon is not the horizon that was declared
# --------------------------------------------------------------------------- #


def test_a_target_one_hour_short_of_the_declared_horizon_is_caught() -> None:
    """`features at t -> target at t + H`, exactly.

    A target at `t + H - 1h` is a different experiment wearing this one's name: the
    horizon in the model id, the registry and the artifact manifest would all be
    wrong by an hour while every other check still passed.
    """
    dataset = _matrix_dataset()
    part = dataset.splits[SPLIT_TRAIN]
    poisoned = [
        instant - dt.timedelta(hours=1) if instant is not None else None
        for instant in part.target_instants
    ]
    tampered = _with_split(dataset, SPLIT_TRAIN, target_instants=tuple(poisoned))
    finding = _finding(tampered, CHECK_HORIZON_EXACT)
    assert finding.status == STATUS_FAIL
    assert finding.offending_rows > 0
    assert audit_leakage(tampered).verdict == "FAIL"


def test_a_target_one_hour_past_the_declared_horizon_is_also_caught() -> None:
    """A horizon that is too long is as wrong as one that is too short."""
    dataset = _matrix_dataset()
    part = dataset.splits[SPLIT_TRAIN]
    poisoned = [
        _one_hour_later(instant) if instant is not None else None
        for instant in part.target_instants
    ]
    tampered = _with_split(dataset, SPLIT_TRAIN, target_instants=tuple(poisoned))
    assert _status(tampered, CHECK_HORIZON_EXACT) == STATUS_FAIL


def test_the_horizon_check_names_the_interval_it_checked() -> None:
    """A passing horizon check that does not say which interval passed is a claim
    with no content."""
    finding = _finding(_matrix_dataset(), CHECK_HORIZON_EXACT)
    assert finding.status == STATUS_PASS
    assert str(HORIZON_SECONDS) in finding.detail


def test_the_failing_horizon_detail_reports_what_it_actually_observed() -> None:
    """The observed deltas are what a reader needs in order to work out what went
    wrong, rather than only being told that something did."""
    dataset = _matrix_dataset()
    part = dataset.splits[SPLIT_TRAIN]
    poisoned = [
        instant - dt.timedelta(hours=1) if instant is not None else None
        for instant in part.target_instants
    ]
    tampered = _with_split(dataset, SPLIT_TRAIN, target_instants=tuple(poisoned))
    detail = _finding(tampered, CHECK_HORIZON_EXACT).detail
    assert "observed deltas" in detail
    assert str(HORIZON_SECONDS - 3600) in detail


# --------------------------------------------------------------------------- #
# Mutation 4: a target column promoted into the feature list
# --------------------------------------------------------------------------- #


def test_a_target_column_present_in_the_feature_list_is_caught() -> None:
    """The two sets must be disjoint.

    A target in the feature list is the target read at its own instant and fed back
    in as an input: the definition of a leak, and invisible to every timestamp check.
    The mutation renames an existing column rather than appending a new one, so the
    matrices and the name list stay consistent - which is the shape a real
    misconfiguration would take.
    """
    dataset = _matrix_dataset()
    target = dataset.binding.column
    assert target not in dataset.feature_names, (
        "this fixture must not already contain the target in its features"
    )
    poisoned = (target, *dataset.feature_names[1:])
    tampered = dataclasses.replace(
        dataset,
        feature_names=poisoned,
        splits={
            name: dataclasses.replace(matrix, feature_names=poisoned)
            for name, matrix in dataset.splits.items()
        },
    )
    finding = _finding(tampered, CHECK_FEATURE_TARGET_DISJOINT)
    assert finding.status == STATUS_FAIL
    assert target in finding.detail
    assert audit_leakage(tampered).verdict == "FAIL"


def test_a_disjointness_failure_names_every_offending_column() -> None:
    """Not just the first. A single-named offender in a list of several is a partial
    fix reported as a fix.

    The mutation renames two existing columns rather than appending, so the matrices
    and the name list stay the same width.
    """
    dataset = _matrix_dataset()
    targets = (dataset.binding.column, "target_rain_24h")
    poisoned = (*targets, *dataset.feature_names[2:])
    assert len(poisoned) == len(dataset.feature_names)
    tampered = dataclasses.replace(
        dataset,
        feature_names=poisoned,
        splits={
            name: dataclasses.replace(matrix, feature_names=poisoned)
            for name, matrix in dataset.splits.items()
        },
    )
    detail = _finding(tampered, CHECK_FEATURE_TARGET_DISJOINT).detail
    for target in targets:
        assert target in detail, f"{target} was not named: {detail!r}"


def test_a_second_column_carrying_the_reserved_target_prefix_is_also_caught() -> None:
    """The prefix, not just the bound column name.

    `target_rain_24h` is not the bound target, and it is still a target that must
    never be an input. The check refuses the prefix as well as the name, and this is
    what keeps that refusal from quietly narrowing to one column.
    """
    dataset = _matrix_dataset()
    poisoned = ("target_rain_24h", *dataset.feature_names[1:])
    assert len(poisoned) == len(dataset.feature_names)
    tampered = dataclasses.replace(
        dataset,
        feature_names=poisoned,
        splits={
            name: dataclasses.replace(matrix, feature_names=poisoned)
            for name, matrix in dataset.splits.items()
        },
    )
    assert _status(tampered, CHECK_FEATURE_TARGET_DISJOINT) == STATUS_FAIL


def test_the_disjointness_detail_lists_the_targets_it_compared_against() -> None:
    """A passing disjointness check states what it compared, so a reader can tell an
    empty feature list from a genuinely disjoint one."""
    finding = _finding(_matrix_dataset(), CHECK_FEATURE_TARGET_DISJOINT)
    assert finding.status == STATUS_PASS
    assert "target_water_level_6h" in finding.detail


# --------------------------------------------------------------------------- #
# Mutation 5: splits that do not run forward in time
# --------------------------------------------------------------------------- #


def test_splits_whose_boundaries_overlap_are_caught() -> None:
    """`train_end == validation_start` means one instant of the series is in two
    splits.

    A row in both the training set and the evaluation set scores the model on the
    data it was fitted from, and every metric on it becomes a training metric.
    """
    dataset = _matrix_dataset()
    bounds = dataset.bounds
    tampered = dataclasses.replace(
        dataset, bounds=dataclasses.replace(bounds, validation_start=bounds.train_end)
    )
    finding = _finding(tampered, CHECK_SPLIT_ORDERED)
    assert finding.status == STATUS_FAIL
    assert audit_leakage(tampered).verdict == "FAIL"


def test_splits_whose_boundaries_run_backwards_are_caught() -> None:
    dataset = _matrix_dataset()
    bounds = dataset.bounds
    tampered = dataclasses.replace(
        dataset, bounds=dataclasses.replace(bounds, test_start=bounds.train_start)
    )
    assert _status(tampered, CHECK_SPLIT_ORDERED) == STATUS_FAIL


def test_the_ordered_check_states_the_row_count_of_each_split() -> None:
    """Train, validation and test, by name and by count.

    A passing check that says only "chronological" leaves a reader unable to confirm
    which rows the figure covers.
    """
    finding = _finding(_matrix_dataset(), CHECK_SPLIT_ORDERED)
    assert finding.status == STATUS_PASS
    for split in EXPECTED_SPLIT_ORDER:
        assert split in finding.detail
    assert str(_matrix_dataset().splits[SPLIT_TRAIN].rows) in finding.detail


def test_the_expected_split_order_is_the_one_the_audit_declares() -> None:
    assert EXPECTED_SPLIT_ORDER == (SPLIT_TRAIN, SPLIT_VALIDATION, SPLIT_TEST)


# --------------------------------------------------------------------------- #
# Mutation 6: a split matrix filed under a label it does not carry
# --------------------------------------------------------------------------- #


def test_a_split_matrix_filed_under_the_wrong_label_is_caught() -> None:
    """A matrix stored under `test` while calling itself `train`.

    Every count keyed on the split name would then describe the wrong rows, and the
    comparison table would score one population and label it as another. Nothing
    else in the audit can see it: the timestamps are all individually correct.
    """
    dataset = _matrix_dataset()
    tampered = _with_split(dataset, SPLIT_TRAIN, split=SPLIT_TEST)
    finding = _finding(tampered, CHECK_SPLIT_LABELS_INSIDE)
    assert finding.status == STATUS_FAIL
    assert SPLIT_TRAIN in finding.detail
    assert SPLIT_TEST in finding.detail
    assert audit_leakage(tampered).verdict == "FAIL"


def test_a_target_outside_its_own_splits_origin_range_is_caught() -> None:
    """The original purpose of the check: a target that belongs to a later period.

    The last hours of every split have no supervised target - their reading lands
    past the end of the series - so the mutation takes a *supervised* row and moves
    its target past the split's own last origin.
    """
    dataset = _matrix_dataset()
    part = dataset.splits[SPLIT_TRAIN]
    high = max(part.origin_instants)
    supervised = [
        index
        for index, (instant, value) in enumerate(
            zip(part.target_instants, part.target)
        )
        if instant is not None and np.isfinite(value)
    ]
    assert supervised, "this fixture has no supervised training row to move"
    poisoned = list(part.target_instants)
    poisoned[supervised[-1]] = high + dt.timedelta(hours=1)

    tampered = _with_split(dataset, SPLIT_TRAIN, target_instants=tuple(poisoned))
    finding = _finding(tampered, CHECK_SPLIT_LABELS_INSIDE)
    assert finding.status == STATUS_FAIL
    assert f"{SPLIT_TRAIN}[{supervised[-1]}]" in finding.detail


def test_a_clean_run_reports_no_mislabelled_matrix() -> None:
    for split in EXPECTED_SPLIT_ORDER:
        dataset = _matrix_dataset()
        assert dataset.splits[split].split == split
    assert _status(_matrix_dataset(), CHECK_SPLIT_LABELS_INSIDE) == STATUS_PASS


# --------------------------------------------------------------------------- #
# Mutation 7: a scaler or imputer fitted on more than the training split
# --------------------------------------------------------------------------- #


def test_a_scaler_whose_mean_is_not_the_training_mean_is_caught() -> None:
    """The check recomputes the fitted statistics from the training rows alone.

    That is the only way to catch a leak here: the stored state looks identical
    whether it was fitted on 168 rows or 264, so nothing about the value itself
    reveals the difference. Reading `fitted_on == "train"` would only prove that a
    label says so.
    """
    dataset = _scaled_dataset()
    state = dataset.scaler_state
    assert state, "the fixture must have a fitted scaler for this check to mean anything"
    assert state["fitted_on"] == SPLIT_TRAIN

    poisoned = dict(state["mean"])
    column = next(iter(poisoned))
    poisoned[column] = poisoned[column] + 1.0

    tampered = dataclasses.replace(dataset, scaler_state={**state, "mean": poisoned})
    finding = _finding(tampered, CHECK_TRAIN_FITTED_STATS)
    assert finding.status == STATUS_FAIL
    assert audit_leakage(tampered).verdict == "FAIL"


def test_a_scaler_whose_scale_is_wrong_is_caught() -> None:
    """Mean and scale are both fitted; a leak in either has to be found."""
    dataset = _scaled_dataset()
    state = dataset.scaler_state
    poisoned = dict(state["scale"])
    column = next(iter(poisoned))
    poisoned[column] = poisoned[column] * 3.0

    tampered = dataclasses.replace(dataset, scaler_state={**state, "scale": poisoned})
    assert _status(tampered, CHECK_TRAIN_FITTED_STATS) == STATUS_FAIL


def test_an_imputer_median_taken_from_a_non_training_split_is_caught() -> None:
    """The imputer is the other fitted statistic, and the easier one to get wrong: a
    median is easy to compute over everything by accident."""
    dataset = _scaled_dataset()
    state = dataset.imputer_state
    assert state, "the fixture must have a fitted imputer for this check to mean anything"
    assert state["kind"] == "median"

    poisoned = dict(state["values"])
    column = next(iter(poisoned))
    poisoned[column] = poisoned[column] + 1000.0

    tampered = dataclasses.replace(dataset, imputer_state={**state, "values": poisoned})
    assert _status(tampered, CHECK_TRAIN_FITTED_STATS) == STATUS_FAIL


def test_a_scaler_that_declares_it_saw_more_than_train_is_caught() -> None:
    """The label is checked as well as the values.

    A state that says `fitted_on: 'all'` while holding the training mean would pass a
    values-only check, and the label is the field a reader would trust.
    """
    dataset = _scaled_dataset()
    state = dataset.scaler_state
    tampered = dataclasses.replace(
        dataset,
        scaler_state={
            **state,
            "fitted_on": "all",
            "fitted_rows": sum(matrix.rows for matrix in dataset.splits.values()),
        },
    )
    assert _status(tampered, CHECK_TRAIN_FITTED_STATS) == STATUS_FAIL


def test_the_fitted_statistics_check_says_how_it_passed() -> None:
    """The passing detail has to explain that the statistics were *recomputed*, or
    "pass" is unfalsifiable to a reader."""
    dataset = _scaled_dataset()
    finding = _finding(dataset, CHECK_TRAIN_FITTED_STATS)
    assert finding.status == STATUS_PASS
    assert "reproduce" in finding.detail
    assert str(dataset.splits[SPLIT_TRAIN].rows) in finding.detail


def test_the_fitted_statistics_check_is_skipped_when_nothing_was_fitted() -> None:
    """With no scaler and no imputer there is nothing to verify, and saying
    `skipped` beats implying a guarantee that was never exercised."""
    dataset = _matrix_dataset(scaler_policy="none", impute_policy="none")
    assert dataset.scaler_state is None
    assert dataset.imputer_state is None
    finding = _finding(dataset, CHECK_TRAIN_FITTED_STATS)
    assert finding.status == STATUS_SKIPPED, (
        f"expected a skip with nothing fitted, got {finding.status}: {finding.detail}"
    )
    assert audit_leakage(dataset).ok is False


def test_the_fitted_statistics_check_runs_for_every_scaling_policy() -> None:
    """Whatever the policy, either there are statistics to verify or there are
    none - and the check says which."""
    for policy in ("none", "standard"):
        dataset = _matrix_dataset(scaler_policy=policy)
        finding = _finding(dataset, CHECK_TRAIN_FITTED_STATS)
        assert finding.status in (STATUS_PASS, STATUS_SKIPPED), (
            f"{policy}: {finding.status} - {finding.detail}"
        )
    assert _status(_matrix_dataset(scaler_policy="standard"), CHECK_TRAIN_FITTED_STATS) == (
        STATUS_PASS
    )


# --------------------------------------------------------------------------- #
# Mutation 8: sequence windows that are not causal, or that span two stations
# --------------------------------------------------------------------------- #


def _audit_with_sequences():
    dataset = _sequence_dataset()
    blocks = _blocks(dataset)
    return audit_leakage(dataset, sequences=blocks), dataset, blocks


def test_a_clean_sequence_run_passes_the_causality_check() -> None:
    audit, _, _ = _audit_with_sequences()
    finding = next(f for f in audit.findings if f.check == CHECK_SEQUENCE_CAUSAL)
    assert finding.status == STATUS_PASS, finding.detail


def test_a_window_that_reaches_one_step_past_its_origin_is_caught() -> None:
    """A window ending after its own origin hands the model the answer.

    `window_instants` is the window's own record of what it read; moving the final
    reading one hour forward is exactly the leak, stated in the data the audit reads
    rather than in the code that produced it.
    """
    audit, dataset, blocks = _audit_with_sequences()
    train = blocks[SPLIT_TRAIN]
    poisoned = list(train.window_instants)
    poisoned[0] = poisoned[0][:-1] + (_one_hour_later(poisoned[0][-1]),)

    tampered = audit_leakage(
        dataset,
        sequences={**blocks, SPLIT_TRAIN: dataclasses.replace(train, window_instants=tuple(poisoned))},
    )
    finding = next(f for f in tampered.findings if f.check == CHECK_SEQUENCE_CAUSAL)
    assert finding.status == STATUS_FAIL
    assert tampered.verdict == "FAIL"
    assert f"{SPLIT_TRAIN} window 0" in finding.detail


def test_a_window_one_row_longer_than_the_declared_lookback_is_caught() -> None:
    """`L` is part of the contract.

    A window of `L + 1` reaches one reading further back, which on a lookback chosen
    for a reason is a different experiment - and the model was built for `L` inputs.
    """
    audit, dataset, blocks = _audit_with_sequences()
    train = blocks[SPLIT_TRAIN]
    poisoned = list(train.window_instants)
    poisoned[0] = (
        poisoned[0][0] - dt.timedelta(hours=1),
        *poisoned[0],
    )

    tampered = audit_leakage(
        dataset,
        sequences={**blocks, SPLIT_TRAIN: dataclasses.replace(train, window_instants=tuple(poisoned))},
    )
    finding = next(f for f in tampered.findings if f.check == CHECK_SEQUENCE_CAUSAL)
    assert finding.status == STATUS_FAIL
    assert str(train.lookback) in finding.detail


def test_a_window_whose_rows_are_further_apart_than_the_step_is_caught() -> None:
    """A gap in the series.

    `window_instants` reports how far the window actually reaches. If a gap widened it
    while `lookback` stayed the same, the model receives a history shorter in time
    than the one it was built and configured for.
    """
    audit, dataset, blocks = _audit_with_sequences()
    train = blocks[SPLIT_TRAIN]
    poisoned = list(train.window_instants)
    poisoned[0] = (
        poisoned[0][0] - dt.timedelta(hours=1),
        *poisoned[0][1:],
    )

    tampered = audit_leakage(
        dataset,
        sequences={
            **blocks,
            SPLIT_TRAIN: dataclasses.replace(
                train, window_instants=tuple(poisoned), lookback=train.lookback + 1
            ),
        },
    )
    finding = next(f for f in tampered.findings if f.check == CHECK_SEQUENCE_CAUSAL)
    assert finding.status == STATUS_FAIL


def test_a_window_holding_two_stations_rows_is_caught() -> None:
    """`[t - L + 1 … t]` for one station.

    `window_entity_sets` records the entities of the rows each window was assembled
    from, as the builder found them. A window containing another station's reading is
    a different catchment's history, and no timestamp check can see it.
    """
    audit, dataset, blocks = _audit_with_sequences()
    train = blocks[SPLIT_TRAIN]
    assert {frozenset(entities) for entities in train.window_entity_sets} == {
        frozenset({STATION_A}),
        frozenset({STATION_B}),
    }, "the fixture must produce windows for both stations for this to be a test"

    poisoned = list(train.window_entity_sets)
    poisoned[0] = (STATION_A, STATION_B)

    tampered = audit_leakage(
        dataset,
        sequences={
            **blocks,
            SPLIT_TRAIN: dataclasses.replace(train, window_entity_sets=tuple(poisoned)),
        },
    )
    finding = next(f for f in tampered.findings if f.check == CHECK_SEQUENCE_CAUSAL)
    assert finding.status == STATUS_FAIL, (
        "a window spanning two stations was accepted; the entity-scoping half of the "
        "causality check is not working"
    )
    assert STATION_A in finding.detail and STATION_B in finding.detail


def test_a_window_labelled_with_one_station_but_built_from_another_is_caught() -> None:
    """The recorded label has to agree with the rows.

    A mismatch means the per-window entity recorded for attribution is not the one the
    values came from, so every downstream statement about which station a forecast is
    for would be wrong.
    """
    audit, dataset, blocks = _audit_with_sequences()
    train = blocks[SPLIT_TRAIN]
    poisoned = list(train.window_entities)
    poisoned[0] = STATION_B if poisoned[0] == STATION_A else STATION_A

    tampered = audit_leakage(
        dataset,
        sequences={
            **blocks,
            SPLIT_TRAIN: dataclasses.replace(train, window_entities=tuple(poisoned)),
        },
    )
    finding = next(f for f in tampered.findings if f.check == CHECK_SEQUENCE_CAUSAL)
    assert finding.status == STATUS_FAIL
    assert "assembled from" in finding.detail


def test_the_causality_check_reports_fail_when_the_step_was_never_established() -> None:
    """`step_seconds is None` means a window's length in time is unknown, so the
    lookback cannot be shown to be causal.

    Skipping here would be the wrong answer: an unestablished step is a missing fact,
    not an absent risk.
    """
    audit, dataset, blocks = _audit_with_sequences()
    train = blocks[SPLIT_TRAIN]
    tampered = audit_leakage(
        dataset,
        sequences={**blocks, SPLIT_TRAIN: dataclasses.replace(train, step_seconds=None)},
    )
    finding = next(f for f in tampered.findings if f.check == CHECK_SEQUENCE_CAUSAL)
    assert finding.status == STATUS_FAIL
    assert "sampling step" in finding.detail


def test_the_causality_check_names_the_step_it_used() -> None:
    """A passing check that does not say what it verified is a claim with no content."""
    audit, _, blocks = _audit_with_sequences()
    finding = next(f for f in audit.findings if f.check == CHECK_SEQUENCE_CAUSAL)
    step = blocks[SPLIT_TRAIN].step_seconds
    assert finding.status == STATUS_PASS
    assert f"{step:.0f}s" in finding.detail


def test_every_row_of_every_split_is_accounted_for_by_the_window_set() -> None:
    """`samples + insufficient_history + missing_target + restricted == rows`.

    Rows must be accounted for. A window set that silently dropped rows it cannot
    explain would make every per-window number describe a population nobody chose,
    and the reader comparing `samples = 458` with `rows = 480` would have no way to
    learn what happened to the other 22.
    """
    dataset = _sequence_dataset()
    for split, block in _blocks(dataset).items():
        matrix = dataset.splits[split]
        assert block.accounted_for() == matrix.rows, (
            f"{split}: {block.samples} window(s) + {block.skipped_insufficient_history} "
            f"without history + {block.skipped_missing_target} without a target + "
            f"{block.restricted_rows} restricted = {block.accounted_for()}, but the matrix "
            f"holds {matrix.rows} row(s)"
        )
        assert block.restricted_rows > 0, (
            f"{split}: the fixture was expected to restrict some rows, so that this "
            "identity is being checked against a real restricted count"
        )


def test_the_rows_restricted_away_are_named_rather_than_vanishing() -> None:
    """The validation and test splits' first hours have no persistence baseline
    inside their own split, and are restricted out so a sequence family is scored on
    the same rows as the baseline it is compared against.

    That restriction has to be visible. Hidden, it would make a sequence family look
    like it was scored on more rows than it was.
    """
    dataset = _sequence_dataset()
    blocks = _blocks(dataset)
    for split in (SPLIT_VALIDATION, SPLIT_TEST):
        assert blocks[split].restricted_rows > 0
        assert blocks[split].restricted_rows == blocks[SPLIT_TRAIN].restricted_rows * 2, (
            f"{split}: the two evaluation splits are the same size, so their restricted "
            "counts should match each other"
        )


def test_no_window_reaches_across_a_split_boundary() -> None:
    """Windows are built per split, so a validation window cannot draw on training
    rows. The instants prove it."""
    dataset = _sequence_dataset()
    blocks = _blocks(dataset)
    for split, block in blocks.items():
        own = set(dataset.splits[split].origin_instants)
        for window in block.window_instants:
            assert set(window) <= own, (
                f"{split}: a window reads an instant that is not a row of its own split"
            )


# --------------------------------------------------------------------------- #
# The audit's own reporting
# --------------------------------------------------------------------------- #


def test_verdict_is_fail_when_anything_failed() -> None:
    dataset = _matrix_dataset()
    part = dataset.splits[SPLIT_TRAIN]
    tampered = _with_split(
        dataset, SPLIT_TRAIN, target_instants=tuple(part.origin_instants)
    )
    audit = audit_leakage(tampered)
    assert audit.verdict == "FAIL"
    assert audit.ok is False, "`ok` is strict: a partial pass is not an ok"
    failed = {finding.check for finding in audit.failed()}
    assert CHECK_TARGET_AFTER_ORIGIN in failed, (
        f"the target check should have failed; what failed was {failed}"
    )


def test_verdict_is_partial_when_something_was_skipped() -> None:
    assert audit_leakage(_matrix_dataset()).verdict == "PARTIAL"


def test_verdict_is_pass_when_everything_ran_and_nothing_failed() -> None:
    audit, _, _ = _audit_with_sequences()
    assert audit.verdict == "PASS"
    assert audit.ok is True
    assert audit.failed() == ()


def test_a_failure_outranks_a_skip_in_the_verdict() -> None:
    """A failure and a skip together must still read as `FAIL`.

    Reporting `PARTIAL` when something actually leaked would let a caller checking only
    the verdict miss the leak - and the verdict is the field a gate is most likely to
    read.
    """
    dataset = _matrix_dataset()
    part = dataset.splits[SPLIT_TRAIN]
    tampered = _with_split(
        dataset, SPLIT_TRAIN, target_instants=tuple(part.origin_instants)
    )
    audit = audit_leakage(tampered)
    assert audit.verdict == "FAIL"
    assert CHECK_SEQUENCE_CAUSAL in audit.skipped_checks()


def test_describe_is_human_readable_and_labels_every_check() -> None:
    audit = audit_leakage(_matrix_dataset())
    text = audit.describe()
    assert "Phase 4 leakage audit" in text
    for finding in audit.findings:
        assert finding.check in text
    assert text.count("[") >= len(audit.findings), "every finding needs a visible marker"


def test_to_dict_is_serialisable_and_carries_every_field() -> None:
    import json

    payload = audit_leakage(_matrix_dataset()).to_dict()
    json.dumps(payload)
    assert sorted(payload) == [
        "checks",
        "failed",
        "findings",
        "ok",
        "passed",
        "skipped",
        "verdict",
    ]
    assert len(payload["findings"]) == 8
    for entry in payload["findings"]:
        assert sorted(entry) == ["check", "detail", "offending_rows", "status"]
        json.dumps(entry)


def test_an_empty_audit_claims_nothing_was_verified() -> None:
    """Constructed by hand, because a real audit always finds eight checks.

    `LeakageAudit()` with no findings must not read as though a property was
    established - and it must not read as `FAIL` either. Nothing failed here; what
    happened is that nothing ran. `PARTIAL` is the honest word, because it says
    exactly that.
    """
    empty = LeakageAudit()
    assert empty.findings == ()
    assert empty.names == ()
    assert empty.ok is False, (
        "an audit that ran nothing must not report that something is verified"
    )
    assert empty.failed() == (), "nothing ran, so nothing failed either"
    assert empty.passed_checks == ()
    assert empty.to_dict()["findings"] == []
    assert empty.to_dict()["verdict"] == "PARTIAL"
    assert "PARTIAL" in empty.describe()


def test_a_finding_can_be_built_by_hand_for_a_report_row() -> None:
    """Reports are assembled from these; constructing one must not require a dataset."""
    finding = LeakageFinding(
        check=CHECK_TARGET_AFTER_ORIGIN,
        status=STATUS_FAIL,
        detail="12 row(s)",
        offending_rows=12,
    )
    assert finding.ok is False
    assert finding.to_dict() == {
        "check": CHECK_TARGET_AFTER_ORIGIN,
        "status": STATUS_FAIL,
        "detail": "12 row(s)",
        "offending_rows": 12,
    }
    assert "12 row(s)" in LeakageAudit(findings=(finding,)).describe()


def test_a_skipped_finding_is_never_reported_as_a_pass() -> None:
    """`ok` is the loose gate; `passed_checks` is the strict one.

    Both exist so a caller can choose, and the choice has to be visible.
    """
    finding = LeakageFinding(
        check=CHECK_SEQUENCE_CAUSAL, status=STATUS_SKIPPED, detail="no windows configured"
    )
    audit = LeakageAudit(findings=(finding,))
    assert finding.ok is True
    assert CHECK_SEQUENCE_CAUSAL not in audit.passed_checks
    assert CHECK_SEQUENCE_CAUSAL in audit.skipped_checks()
    assert audit.verdict == "PARTIAL"


# --------------------------------------------------------------------------- #
# The audit over more than one shape of data
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "family, changes",
    [
        (FAMILY_NAIVE, {"impute_policy": "none"}),
        (FAMILY_RANDOM_FOREST, {"scaler_policy": "standard"}),
        (FAMILY_RANDOM_FOREST, {"scaler_policy": "none", "impute_policy": "median"}),
        (FAMILY_RANDOM_FOREST, {"scaler_policy": "none", "impute_policy": "none"}),
    ],
    ids=["naive", "standard", "median", "nothing-fitted"],
)
def test_the_audit_does_not_depend_on_which_family_or_policy_is_configured(
    family, changes
) -> None:
    """Scaling and imputation policy change the fitted statistics; family choice does
    not change the timestamps.

    A check that only ever saw one configuration would be a check tuned to that
    configuration.
    """
    audit = audit_leakage(_matrix_dataset_family(family, **changes))
    assert audit.failed() == (), f"{family} {changes}: {audit.failed()}"


def _matrix_dataset_family(family, **changes):
    return assemble(build_feature_result().dataset, family, **changes)


def test_both_fixtures_audit_clean() -> None:
    """A short series and a long one, two configurations, neither leaking.

    A check that had only ever seen one fixture would be a check tuned to that
    fixture.
    """
    short = audit_leakage(assemble(build_feature_result().dataset, FAMILY_NAIVE))
    assert short.failed() == ()

    longer = _sequence_dataset()
    blocks = _blocks(longer)
    sequence_audit = audit_leakage(longer, sequences=blocks)
    assert sequence_audit.failed() == ()
    assert _status(longer, CHECK_SEQUENCE_CAUSAL, sequences=blocks) == STATUS_PASS


def test_the_audit_is_stable_across_repeated_runs_on_identical_data() -> None:
    """An audit that changed its mind between runs on the same data could not be used
    as a gate."""
    dataset = _matrix_dataset()
    assert audit_leakage(dataset).to_dict() == audit_leakage(dataset).to_dict()


def test_the_phase_3_and_phase_4_audits_both_pass_on_the_same_rows(feature_result) -> None:
    """Phase 4 audits the matrices it assembles; Phase 3 audited the rows they came
    from.

    Both verdicts have to be readable together, because a Phase 4 check that passed
    over rows Phase 3 rejected would be auditing the wrong thing. One name -
    `features_read_at_or_before_origin` - appears in both, on purpose: the property is
    the same one at two different stages, and having it checked once in Phase 3 and
    again in Phase 4 is the point of re-checking it.
    """
    phase_three = feature_result.report.leakage
    assert phase_three.ok is True, phase_three.describe()
    assert len(phase_three.names) == 8

    shared = set(phase_three.names) & set(EXPECTED_CHECKS)
    assert shared == {"features_read_at_or_before_origin"}, (
        f"the two audits share {shared}; a name reused for a different meaning would let "
        "a reader assume one audit covers both"
    )

    phase_four = audit_leakage(_matrix_dataset())
    assert phase_four.failed() == ()
    shared_finding = next(f for f in phase_four.findings if f.check in shared)
    # Phase 3 records are `(name, ok, detail)` tuples, one per check.
    phase_three_shared = next(
        record for record in phase_three.records if record[0] in shared
    )
    assert shared_finding.status == STATUS_PASS
    assert phase_three_shared[1] is True
    assert "origin" in shared_finding.detail
    assert "origin" in phase_three_shared[2]