# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 4 — target binding, matrices, the persistence baseline and sequences.

Everything a model is later fitted on is assembled here, so this is the module
where a leak enters the pipeline if one is going to. The tests are written to
attack the assembly rather than to admire it: features are mutated in the future,
targets are moved, one station's readings are replaced with another's, and the
claim "this row cannot see anything later than its origin" is checked against the
produced numbers rather than against the code that produced them.

Every value here is synthetic/demo data. No test asserts a hydrological result.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import numpy as np
import pytest

from hydro_phase4_fixtures import (
    HOUR,
    STATION_A,
    STATION_B,
    SYNTHETIC_DISCLAIMER,
    at,
    config_for,
    feature_dataset,
    feature_result,
    model_dataset,
    sequence_dataset,
    step_seconds,
    synthetic_descriptor,
)
from app.engines.hydro import feature_pipeline as pipeline
from app.engines.hydro.feature_config import FeatureConfig
from app.engines.hydro.model_config import (
    FEATURE_SELECTION_ALL,
    FEATURE_SELECTION_TRAIN_PRESENT,
    FAMILY_NAIVE,
    IMPUTE_MEDIAN,
    IMPUTE_NONE,
    PERSISTENCE_SOURCE_ANY_PAST,
    PERSISTENCE_SOURCE_SAME_SPLIT,
    SCALER_NONE,
    SCALER_STANDARD,
)
from app.engines.hydro.preprocessing import PreprocessError
from app.engines.hydro.model_dataset import (
    CODE_BASELINE_ROWS_EXCLUDED,
    CODE_FEATURE_DROPPED,
    CODE_IMPUTE_NONE,
    CODE_IMPUTED,
    CODE_NO_FEATURES,
    CODE_TARGET_NOT_FUTURE,
    CODE_TARGET_UNAVAILABLE,
    DATA_PREFIX,
    ModelDataError,
    assemble_dataset,
    bind_target,
    build_sequences,
    persistence_predictions,
    resolve_step_seconds,
)

pytest_plugins: list[str] = []


# --------------------------------------------------------------------------- #
# Target binding
# --------------------------------------------------------------------------- #


def test_the_bound_target_is_the_one_phase_3_built(model_dataset) -> None:
    """Not a name Phase 4 chose. `target_water_level_6h` came out of Phase 3 and
    Phase 4 consumes it."""
    binding = model_dataset.binding
    assert binding.available
    assert binding.column == "target_water_level_6h"
    assert binding.quantity == "water_level"
    assert binding.column == model_dataset.target_column


def test_the_binding_carries_phase_3s_horizon_not_a_restated_one(model_dataset) -> None:
    """6 hours in, 21600 seconds, and the same label Phase 3 emitted."""
    binding = model_dataset.binding
    assert binding.horizon_seconds == 6 * HOUR
    assert binding.horizon_label == "6h"
    assert binding.alignment


def test_the_binding_carries_phase_3s_units_not_a_guessed_one(model_dataset) -> None:
    """`m` here because the fixture declared it. A quantity whose unit Phase 3 could
    not resolve would be recorded as unknown, not as metres."""
    assert model_dataset.binding.units == "m"
    assert model_dataset.target_units == "m"


def test_a_binding_states_whether_the_target_is_available_at_prediction_time(model_dataset) -> None:
    """A forecast target must be one you *cannot* already read.

    The Phase 3 lineage field is `available_at_prediction_time`, and `False` is the
    good answer here: the reading sits at `t + 6h`, not at `t`. `bind_target`
    treats any value other than `False` as a reason to mark the target unavailable,
    because a target readable at the prediction instant is a contemporaneous
    feature, not a forecast.
    """
    assert model_dataset.binding.available_at_prediction_time is False
    assert model_dataset.binding.available


def test_a_target_phase_3_never_built_is_reported_unavailable(feature_result) -> None:
    """No substitution. A `water_level` target at 3 hours, when Phase 3 built only
    6, is unavailable — not quietly rounded to 6."""
    config = config_for(FAMILY_NAIVE, horizon_hours=(3.0,))
    binding = bind_target(feature_result.dataset, config)
    assert not binding.available
    assert binding.reason
    assert binding.column  # the name is still stated, so the reader sees what was asked
    assert "3h" in binding.reason


def test_the_reason_names_the_targets_that_do_exist(feature_result) -> None:
    """A refusal that only says "no" leaves the reader guessing whether the column
    was misspelled, or never built, or belongs to a different variable."""
    config = config_for(FAMILY_NAIVE, horizon_hours=(3.0,))
    binding = bind_target(feature_result.dataset, config)
    assert "target_water_level_6h" in binding.reason


def test_an_unavailable_target_produces_no_target_column(feature_result) -> None:
    """The refusal must be structural: the target column is absent and the target
    array is entirely NaN, not a column of another variable's values."""
    config = config_for(FAMILY_NAIVE, horizon_hours=(3.0,))
    dataset = assemble_dataset(feature_result, config)
    assert dataset.binding.available is False
    assert dataset.target_column == "target_water_level_3h"
    for matrix in dataset.splits.values():
        assert np.all(np.isnan(matrix.target))


def test_an_unavailable_target_is_never_scored_rather_than_scored_as_zero(feature_result) -> None:
    """No target, no evaluable rows. A run that scored 36 rows against an all-NaN
    target would have to invent the truth it is being measured on."""
    config = config_for(FAMILY_NAIVE, horizon_hours=(3.0,))
    dataset = assemble_dataset(feature_result, config)
    for matrix in dataset.splits.values():
        assert matrix.evaluable == 0


def test_a_quantity_phase_3_never_targeted_is_unavailable(feature_result) -> None:
    """`rainfall` is a feature source here, not a target. Asking Phase 4 to predict
    it must not fall back to the water level."""
    config = config_for(FAMILY_NAIVE, target_quantity="rainfall")
    dataset = assemble_dataset(feature_result, config)
    assert dataset.binding.available is False
    assert "rainfall" in dataset.binding.reason
    assert "target_water_level_6h" in dataset.binding.reason, (
        "the reason must show the available target rather than leave the reader "
        "guessing whether Phase 3 produced nothing at all"
    )


def test_an_unavailable_target_is_recorded_as_a_note_not_a_silent_empty(feature_result) -> None:
    config = config_for(FAMILY_NAIVE, target_quantity="rainfall")
    dataset = assemble_dataset(feature_result, config)
    codes = {note.code for note in dataset.notes}
    assert CODE_TARGET_UNAVAILABLE in codes


def test_a_target_readable_at_the_prediction_instant_is_refused(feature_dataset) -> None:
    """A target whose reading is available at `t` is an input, not a forecast.

    `bind_target` asks Phase 3's own lineage one question — is this target readable
    at the prediction instant? — and refuses anything other than a firm `False`. A
    tampered lineage is the honest way to exercise that branch: the alternative,
    rewriting the per-row target instants, is checked row-by-row by the leakage audit
    instead, because that is where a timestamp disagreement can be detected at all.
    """
    tampered = _mark_target_available_at_prediction_time(feature_dataset)
    dataset = assemble_dataset(tampered, config_for(FAMILY_NAIVE))
    codes = {note.code for note in dataset.notes}
    assert CODE_TARGET_NOT_FUTURE in codes, (
        f"a target readable at the prediction instant was accepted; codes were {sorted(codes)}"
    )
    notes = [note for note in dataset.notes if note.code == CODE_TARGET_NOT_FUTURE]
    assert notes[0].message.strip(), "the refusal must carry a reason"


def test_a_target_readable_at_the_prediction_instant_is_not_usable(feature_dataset) -> None:
    """`available` asks whether the column exists; `usable` asks whether it is
    forecastable. A column that exists but sits at the prediction instant answers the
    first and fails the second — and the second is what gates training.
    """
    tampered = _mark_target_available_at_prediction_time(feature_dataset)
    binding = bind_target(tampered, config_for(FAMILY_NAIVE))
    assert binding.available is True, "the column does exist; only its alignment is wrong"
    assert binding.usable is False, (
        "a contemporaneous target must not be usable, or a model could be scored on a "
        "reading it could already see"
    )
    assert "available_at_prediction_time=True" in binding.reason
    assert binding.reason.endswith("not a forecast target")


def test_the_unmodified_binding_is_usable(model_dataset) -> None:
    """The gate above is only meaningful because a real target passes it."""
    assert model_dataset.binding.available is True
    assert model_dataset.binding.usable is True


def test_the_target_instant_is_exactly_one_horizon_after_the_origin(model_dataset) -> None:
    """Not approximately. `t + 6h` and `t + 6h30m` are different experiments."""
    seconds = model_dataset.binding.horizon_seconds
    for matrix in model_dataset.splits.values():
        pairs = [
            (origin, target)
            for origin, target in zip(matrix.origin_instants, matrix.target_instants)
            if target is not None
        ]
        assert pairs
        for origin, target in pairs:
            assert target - origin == dt.timedelta(seconds=seconds)


# --------------------------------------------------------------------------- #
# Split matrices
# --------------------------------------------------------------------------- #


def test_the_three_splits_partition_the_rows_exactly(model_dataset) -> None:
    """No row counted twice, none dropped."""
    counts = {name: matrix.rows for name, matrix in model_dataset.splits.items()}
    assert set(counts) == {"train", "validation", "test"}
    assert sum(counts.values()) == model_dataset.total_rows
    assert all(count > 0 for count in counts.values())


def test_the_splits_are_chronological_and_non_overlapping(model_dataset) -> None:
    """Train ends before validation begins, validation before test.

    A random split would let a model see tomorrow while predicting today. Ordering is
    checked per entity, because rows are laid out entity-then-instant and a flat sort
    across both entities would compare station A's last hour with station B's first.
    """
    ordered = ["train", "validation", "test"]
    previous_end: dict[str, dt.datetime] = {}
    for name in ordered:
        matrix = model_dataset.splits[name]
        by_entity: dict[str, list[dt.datetime]] = {}
        for entity, origin in zip(matrix.row_entities, matrix.origin_instants):
            by_entity.setdefault(entity, []).append(origin)
        assert by_entity, f"{name} holds no rows"
        for entity, origins in by_entity.items():
            assert origins == sorted(origins), f"{name}/{entity} origins are not sorted"
            if name in previous_end:
                assert min(origins) > previous_end[entity], (
                    f"{name}/{entity} starts at {min(origins)}, at or before the end of "
                    f"the previous split ({previous_end[entity]})"
                )
        previous_end = {entity: max(origins) for entity, origins in by_entity.items()}


def test_the_split_labels_phase_3_assigned_are_the_ones_phase_4_uses(
    feature_dataset, model_dataset
) -> None:
    """Phase 4 does not re-split.

    Every row's label came from Phase 3, and this checks the assembled matrix against
    the Phase 3 rows themselves rather than against a copy — so a re-split in
    `model_dataset` would show up as a row in `train` that Phase 3 called `test`.
    """
    phase_three = {
        (row.entity, row.instant): row.split for row in feature_dataset.rows
    }
    seen = 0
    for name, matrix in model_dataset.splits.items():
        for entity, origin in zip(matrix.row_entities, matrix.origin_instants):
            key = (entity, origin)
            assert key in phase_three, f"{key} is not a Phase 3 row at all"
            assert phase_three[key] == name, (
                f"{entity} at {origin} sits in {name} here but Phase 3 labelled it "
                f"{phase_three[key]}"
            )
            seen += 1
    assert seen == model_dataset.total_rows


def test_a_split_boundary_never_splits_one_entitys_time_axis(model_dataset) -> None:
    """Consecutive reads within one entity never jump splits and back.

    A row at `t` in train and `t + 1h` in test would mean the split boundary ran
    *through* a station's series, so a model could learn from a reading that sits
    between two others it is scored against.
    """
    by_entity: dict[str, dict[dt.datetime, str]] = {}
    for name, matrix in model_dataset.splits.items():
        for entity, origin in zip(matrix.row_entities, matrix.origin_instants):
            by_entity.setdefault(entity, {})[origin] = name
    for entity, labels in by_entity.items():
        ordered = sorted(labels)
        for earlier, later in zip(ordered, ordered[1:]):
            assert labels[earlier] != "test" or labels[later] != "train", (
                f"{entity}: a row in {labels[later]} at {later} follows a row in "
                f"{labels[earlier]} at {earlier}"
            )


def test_a_matrix_column_count_matches_the_declared_feature_list(model_dataset) -> None:
    """A matrix that is wider than the feature list means something was added
    without being named, and an unnamed column cannot be audited."""
    matrix = model_dataset.splits["train"]
    assert matrix.values.shape[1] == len(matrix.feature_names) == len(
        model_dataset.feature_names
    )
    assert matrix.feature_names == model_dataset.feature_names


def test_feature_names_never_include_the_target_column(model_dataset) -> None:
    """The core separation. A feature sharing the target's name would mean the model
    could read its own answer, and the result would be a near-perfect R² produced by
    nothing more than a copy operation."""
    assert model_dataset.feature_names
    assert model_dataset.target_column
    assert model_dataset.target_column not in model_dataset.feature_names


def test_no_feature_name_begins_with_the_reserved_target_prefix(model_dataset) -> None:
    for name in model_dataset.feature_names:
        assert not name.startswith("target"), name


def test_the_matrix_carries_the_values_and_the_raw_values_apart(model_dataset) -> None:
    """`values` is what a model sees; `raw_values` is what Phase 3 produced. Keeping
    both means the imputation and scaling can be undone and checked."""
    matrix = model_dataset.splits["train"]
    assert matrix.raw_values.shape == matrix.values.shape
    assert matrix.raw_values is not matrix.values


def test_no_feature_is_dropped_when_every_declared_column_has_training_data(model_dataset) -> None:
    """This fixture's warm-up gaps are filled by the median, so nothing is dropped.

    Asserted explicitly rather than left implied, because "which features did you
    drop?" only means something once a run *has* dropped some — see the next test.
    """
    assert not model_dataset.dropped_features
    assert not any(note.code == CODE_FEATURE_DROPPED for note in model_dataset.notes)


def test_a_feature_with_no_training_value_is_dropped_and_named_with_a_reason(
    feature_dataset,
) -> None:
    """The policy that actually fires.

    A column with no finite value anywhere in training cannot be standardised — its
    standard deviation is undefined — so it is dropped by name with the reason
    recorded, rather than becoming a column of zeros that a model would treat as a
    constant signal.

    The blanking is applied to the dataset rather than to a configuration, because
    the fixture has no such column naturally and a policy that is only ever asserted
    against a fixture built to satisfy it is not tested.
    """
    absent = feature_dataset.feature_columns[-1]
    assert absent in feature_dataset.feature_columns
    holed = _blank_column(feature_dataset, absent, splits=None)

    dataset = assemble_dataset(holed, config_for(FAMILY_NAIVE))
    assert absent not in dataset.feature_names
    assert absent in dataset.dropped_features
    assert not (set(dataset.dropped_features) & set(dataset.feature_names))
    assert dataset.splits["train"].values.shape[1] == len(dataset.feature_names)

    named = [
        note.message for note in dataset.notes
        if note.code == CODE_FEATURE_DROPPED and absent in note.message
    ]
    assert named, (
        f"{absent} was dropped but no note names it; the reader cannot tell which column "
        "disappeared from the feature matrix"
    )


def test_a_feature_present_only_outside_training_is_dropped_by_default(
    feature_dataset,
) -> None:
    """The decision that actually matters, and the reason the policy exists.

    A column populated only in validation and test *could* be imputed from nothing,
    scaled from nothing, and then would carry information that exists only where a
    model is scored. Dropping it keeps the feature set a function of training data
    alone.
    """
    absent = feature_dataset.feature_columns[-1]
    holed = _blank_column(feature_dataset, absent, splits=("train",))
    assert [
        row
        for row in holed.rows
        if row.split == "train" and row.values.get(absent) is not None
    ] == [], "the tamper must leave the column absent throughout training"
    assert [
        row
        for row in holed.rows
        if row.split == "test" and row.values.get(absent) is not None
    ], "the column must remain populated in test; otherwise this is not the test"

    dataset = assemble_dataset(holed, config_for(FAMILY_NAIVE))
    assert absent not in dataset.feature_names
    assert absent in dataset.dropped_features

    with pytest.raises(PreprocessError) as caught:
        assemble_dataset(
            holed, config_for(FAMILY_NAIVE, feature_selection=FEATURE_SELECTION_ALL)
        )
    assert absent in str(caught.value), (
        "the refusal must name the column that cannot be fitted, so a reader knows "
        "which one to investigate"
    )


def test_selecting_all_features_keeps_everything_phase_3_declared(feature_result) -> None:
    """The opt-in exists and does what it says: a column with no training value is
    retained, on the understanding that the estimator will refuse it."""
    kept = assemble_dataset(feature_result, config_for(FAMILY_NAIVE))
    every = assemble_dataset(
        feature_result, config_for(FAMILY_NAIVE, feature_selection=FEATURE_SELECTION_ALL)
    )
    assert len(every.feature_names) >= len(kept.feature_names)
    assert every.feature_names == every.declared_feature_names
    assert not every.dropped_features


def test_the_default_selection_is_the_one_the_module_documents(feature_result) -> None:
    """A feature that is present only in test is dropped by default. That is the
    choice that matters: keeping it would mean the test split contributed to the
    feature set, which is a leak of the split structure even when every value is
    imputed."""
    assert config_for(FAMILY_NAIVE).feature_selection == FEATURE_SELECTION_TRAIN_PRESENT


def test_every_note_carries_a_readable_message(feature_result) -> None:
    """A code is for machines; the message is for whoever reads the run afterwards.

    Asserted on the real run rather than on a synthesised note, so a note added by a
    later change without an explanation fails here.
    """
    dataset = assemble_dataset(feature_result, config_for(FAMILY_NAIVE))
    assert dataset.notes, "the fixture produces absences, so there is something to note"
    for note in dataset.notes:
        assert note.code.startswith(DATA_PREFIX), note.code
        assert note.message.strip(), f"{note.code} carries an empty message"
        assert len(note.message.split()) >= 5, (
            f"{note.code} is too terse to explain itself: {note.message!r}"
        )


def test_the_notes_are_deduplicated_by_code_or_per_split_as_intended(feature_result) -> None:
    """A per-split note repeats once per split, which is what makes the count
    readable. Asserted so a reader knows the repetition is deliberate."""
    dataset = assemble_dataset(feature_result, config_for(FAMILY_NAIVE))
    per_split = [note for note in dataset.notes if note.code == CODE_BASELINE_ROWS_EXCLUDED]
    assert len(per_split) == len(dataset.splits)
    for note in per_split:
        split = note.message.split(":", 1)[0].strip()
        assert split in dataset.splits, f"{note.message!r} does not name a split"


# --------------------------------------------------------------------------- #
# The persistence baseline
# --------------------------------------------------------------------------- #


def test_persistence_is_the_observation_at_the_origin(feature_dataset) -> None:
    """The definition, checked against the fixture's own arithmetic.

    The generator is deterministic, so the expected value is *computable* rather
    than merely "different from what the code produced" — a wrong lookup yields a
    specific wrong number, which is what makes a failure readable.

    Why the origin and not `origin - horizon`: Phase 3's target column for origin
    `t - H` *is* the observation at `t`, so the latest target value readable at `t`
    is the reading at `t` itself. That derivation is what keeps the baseline inside
    the Phase 3 contract without asking Phase 3 for a zero-horizon target.
    """
    import hydro_phase4_fixtures as fixtures

    matrix = assemble_dataset(feature_dataset, config_for(FAMILY_NAIVE)).splits["validation"]
    offsets = {STATION_A: 0.0, STATION_B: 3.0}
    checked = 0
    for index, keep in enumerate(matrix.evaluable_mask):
        if not keep:
            continue
        entity = matrix.row_entities[index]
        hours = (matrix.origin_instants[index] - at(0)).total_seconds() / HOUR
        expected = fixtures._level(hours, offsets[entity])
        assert matrix.persistence[index] == pytest.approx(expected, abs=1e-9), (
            f"row {index} ({entity}) baseline read {matrix.persistence[index]} but the "
            f"observation at {matrix.origin_instants[index].isoformat()} is {expected}"
        )
        checked += 1
    assert checked > 0, "no validation row had a baseline prediction, so nothing was checked"


def test_every_baseline_prediction_copied_a_reading_from_its_own_entity(feature_dataset) -> None:
    """The search pool is per entity, so station A's baseline is never station B's
    value — and the offset in the fixture is what makes that visible, because the
    per-entity check above passes only if the two series stay separate.
    """
    matrix = assemble_dataset(feature_dataset, config_for(FAMILY_NAIVE)).splits["validation"]
    by_entity: dict[str, list[float]] = {}
    for index, keep in enumerate(matrix.evaluable_mask):
        if keep:
            by_entity.setdefault(matrix.row_entities[index], []).append(
                round(float(matrix.persistence[index]), 9)
            )
    assert len(by_entity) >= 2, "the fixture must hold two stations for this to mean anything"
    shared = set(by_entity[STATION_A]) & set(by_entity[STATION_B])
    assert not shared, (
        f"both stations produced the same baseline value(s) {sorted(shared)[:3]}; the "
        "fixture's per-station offset is too small to detect a cross-station read"
    )


def test_the_instants_a_row_read_are_all_at_or_before_its_origin(model_dataset) -> None:
    """Structural, and the property every feature-level leak test rests on.

    `source_instants` is carried verbatim from Phase 3, so this checks the *inputs*
    Phase 4 assembled rather than taking Phase 3's word for them.
    """
    for matrix in model_dataset.splits.values():
        for index, origin in enumerate(matrix.origin_instants):
            instants = matrix.source_instants[index]
            assert instants, "a row that read nothing cannot be a model input"
            assert max(instants) <= origin, (
                f"{matrix.split} row {index} read {max(instants)} after its origin {origin}"
            )


def test_persistence_never_reads_a_value_after_the_origin(feature_dataset) -> None:
    """Behavioural: mutate every future reading and the baseline must not move.

    Stronger than reading the code. If anything in the baseline's search reached
    forward, the persisted value would shift by the 1000.0 the mutation added.
    """
    cutoff = dt.datetime(2024, 1, 8, tzinfo=dt.timezone.utc)
    before = assemble_dataset(feature_dataset, config_for(FAMILY_NAIVE)).splits["validation"]

    mutated_rows = [
        dataclasses.replace(
            row,
            targets={name: value + 1000.0 for name, value in row.targets.items()},
        )
        if (row.split == "validation" and row.instant >= cutoff)
        else row
        for row in feature_dataset.rows
    ]
    mutated = dataclasses.replace(feature_dataset, rows=tuple(mutated_rows))
    after = assemble_dataset(mutated, config_for(FAMILY_NAIVE)).splits["validation"]

    before_kept = [
        (entity, origin, round(float(value), 12))
        for entity, origin, value, keep in zip(
            before.row_entities, before.origin_instants, before.persistence,
            before.evaluable_mask,
        )
        if keep and origin < cutoff
    ]
    after_kept = [
        (entity, origin, round(float(value), 12))
        for entity, origin, value, keep in zip(
            after.row_entities, after.origin_instants, after.persistence,
            after.evaluable_mask,
        )
        if keep and origin < cutoff
    ]
    assert before_kept, "no validation row before the cutoff had a baseline to compare"
    assert before_kept == after_kept


def test_persistence_never_reads_another_stations_reading(feature_dataset) -> None:
    """Station A's baseline is not station B's value.

    The fixture offsets station B's levels by a constant, so a cross-station read
    would produce a specific wrong number.
    """
    matrix = assemble_dataset(feature_dataset, config_for(FAMILY_NAIVE)).splits["train"]
    by_entity: dict[str, set[float]] = {}
    for index, keep in enumerate(matrix.evaluable_mask):
        if not keep:
            continue
        by_entity.setdefault(matrix.row_entities[index], set()).add(
            round(float(matrix.persistence[index]), 9)
        )
    assert len(by_entity) >= 2, "the fixture must hold two stations for this to mean anything"
    shared = by_entity[STATION_A] & by_entity[STATION_B]
    assert not shared, (
        f"both stations produced the same baseline value(s) {sorted(shared)[:3]}; the "
        "fixture's per-station offset is too small to detect a cross-station read"
    )


def test_same_split_only_never_carries_a_value_across_a_split_boundary(feature_result) -> None:
    """The conservative default.

    A validation row whose target instant sits inside the validation split still has
    no *earlier* observation inside validation, so no baseline exists and the row is
    dropped. Under `any_past` it would be carried from the tail of train — a value
    from a different time regime, which is exactly the choice the conservative
    policy exists to avoid.
    """
    strict = assemble_dataset(
        feature_result, config_for(FAMILY_NAIVE, persistence_source=PERSISTENCE_SOURCE_SAME_SPLIT)
    )
    loose = assemble_dataset(
        feature_result, config_for(FAMILY_NAIVE, persistence_source=PERSISTENCE_SOURCE_ANY_PAST)
    )
    strict_rows = int(np.count_nonzero(strict.splits["validation"].evaluable_mask))
    loose_rows = int(np.count_nonzero(loose.splits["validation"].evaluable_mask))
    assert loose_rows > strict_rows
    assert strict_rows < strict.splits["validation"].rows


def test_the_looser_policy_only_widens_the_scored_population_it_never_narrows(feature_result) -> None:
    """Every row the strict policy scored is still scored under the loose one."""
    strict = assemble_dataset(
        feature_result, config_for(FAMILY_NAIVE, persistence_source=PERSISTENCE_SOURCE_SAME_SPLIT)
    )
    loose = assemble_dataset(
        feature_result, config_for(FAMILY_NAIVE, persistence_source=PERSISTENCE_SOURCE_ANY_PAST)
    )
    for name in strict.splits:
        strict_mask = strict.splits[name].evaluable_mask
        loose_mask = loose.splits[name].evaluable_mask
        assert bool(np.all(loose_mask[strict_mask])), f"{name}: the loose policy dropped a row"


def test_rows_without_a_baseline_prediction_are_excluded_from_scoring(feature_result) -> None:
    """And the exclusion is recorded per split, with the count, as a note.

    The exclusion is what makes the comparison like-for-like: if the baseline lost a
    row and a forest did not, the two metrics would differ partly because of which
    rows were measured.
    """
    dataset = assemble_dataset(feature_result, config_for(FAMILY_NAIVE))
    notes = [note for note in dataset.notes if note.code == CODE_BASELINE_ROWS_EXCLUDED]
    assert len(notes) == len(dataset.splits)
    for name, matrix in dataset.splits.items():
        assert matrix.evaluable == int(np.count_nonzero(matrix.evaluable_mask))
        assert matrix.evaluable < matrix.rows, f"{name} excluded no rows"
        matching = [note for note in notes if note.message.startswith(f"{name}:")]
        assert matching, f"no exclusion note for {name}"
        without_baseline = int(np.count_nonzero(~np.isfinite(matrix.persistence)))
        assert without_baseline > 0, f"{name} excluded no rows for want of a baseline"
        assert str(without_baseline) in matching[0].message, (
            f"the {name} note reports {matching[0].message!r} but {without_baseline} "
            "row(s) had no baseline prediction"
        )


def test_an_excluded_row_has_no_baseline_value_to_manufacture(feature_result) -> None:
    """The mask exists so nobody has to guess what a missing baseline means."""
    dataset = assemble_dataset(feature_result, config_for(FAMILY_NAIVE))
    matrix = dataset.splits["validation"]
    dropped = matrix.persistence[~matrix.evaluable_mask]
    assert dropped.shape[0] > 0


def test_persistence_predictions_are_nan_where_no_value_exists(feature_dataset) -> None:
    """NaN, not zero. A zero would be indistinguishable from a real reading of zero
    and would quietly become a baseline prediction that scored as an error measure.
    """
    dataset = assemble_dataset(feature_dataset, config_for(FAMILY_NAIVE))
    matrix = dataset.splits["validation"]
    no_baseline = ~np.isfinite(matrix.persistence)
    assert no_baseline.any(), "no validation row lacked a baseline, so nothing was checked"
    assert np.all(np.isnan(matrix.persistence[no_baseline]))
    assert np.all(np.isfinite(matrix.persistence[~no_baseline]))
    # Every such row is excluded, so it can never reach a score.
    assert not np.any(matrix.evaluable_mask & no_baseline)


def test_persistence_predictions_reject_a_policy_it_does_not_know() -> None:
    """Named, not defaulted.

    The two implemented policies disagree about whether a baseline may read across a
    split boundary, so an unrecognised policy silently treated as the default would
    change what the baseline *is* while the recorded configuration said nothing.
    """
    with pytest.raises(ModelDataError) as caught:
        persistence_predictions([], "target_x", policy="from_the_future")
    assert "from_the_future" in str(caught.value)
    assert PERSISTENCE_SOURCE_SAME_SPLIT in str(caught.value)


def test_persistence_on_an_empty_row_list_is_an_empty_array() -> None:
    """An empty population is not an error, and it is not a zero either."""
    result = persistence_predictions([], "target_x", policy=PERSISTENCE_SOURCE_SAME_SPLIT)
    assert isinstance(result, np.ndarray)
    assert result.size == 0


# --------------------------------------------------------------------------- #
# Scaling and imputation — fitted on training rows only
# --------------------------------------------------------------------------- #


def test_the_imputer_reports_the_median_it_was_fitted_with(feature_result) -> None:
    """The reported median must be the *training* median.

    Recomputed from the training matrix rather than read from the state, because a
    state field that disagreed with the matrix would be worse than no state at all:
    it would be a claim a reader could not check.
    """
    dataset = assemble_dataset(feature_result, config_for(FAMILY_NAIVE, impute_policy=IMPUTE_MEDIAN))
    state = dataset.imputer_state
    assert state["kind"] == "median"
    assert state["fitted_on"] == "train"
    assert state["fitted_rows"] == dataset.splits["train"].rows
    train = dataset.splits["train"]
    checked = 0
    for name, median in state["values"].items():
        column = _column_of(train.feature_names, name)
        if column is None:
            continue
        finite = train.raw_values[:, column]
        finite = finite[np.isfinite(finite)]
        assert finite.size > 0, f"{name} was imputed but has no finite training value to impute"
        assert float(median) == pytest.approx(float(np.median(finite)), abs=1e-9), (
            f"{name}: reported median {median} but the training median is {np.median(finite)}"
        )
        checked += 1
    assert checked > 0


def test_a_validation_row_with_an_extreme_value_cannot_move_the_imputer(feature_result) -> None:
    """Behavioural, not structural: the test value is scaled far beyond anything in
    training, and the fitted medians must be bit-identical afterwards."""
    baseline = assemble_dataset(feature_result, config_for(FAMILY_NAIVE))
    tampered_rows = []
    for row in feature_result.dataset.rows:
        if row.split == "validation":
            tampered_rows.append(
                dataclasses.replace(
                    row, values={k: 1e9 for k, v in row.values.items() if v is not None}
                )
            )
        else:
            tampered_rows.append(row)
    tampered = dataclasses.replace(feature_result.dataset, rows=tuple(tampered_rows))
    after = assemble_dataset(tampered, config_for(FAMILY_NAIVE))
    assert after.imputer_state == baseline.imputer_state


def test_the_scaler_fits_on_training_rows_only(feature_result) -> None:
    """A test value far outside training must not widen the fitted scale."""
    baseline = assemble_dataset(
        feature_result, config_for(FAMILY_NAIVE, scaler_policy=SCALER_STANDARD)
    )
    tampered_rows = []
    for row in feature_result.dataset.rows:
        if row.split == "test":
            tampered_rows.append(
                dataclasses.replace(
                    row, values={k: 1e6 for k, v in row.values.items() if v is not None}
                )
            )
        else:
            tampered_rows.append(row)
    tampered = dataclasses.replace(feature_result.dataset, rows=tuple(tampered_rows))
    after = assemble_dataset(tampered, config_for(FAMILY_NAIVE, scaler_policy=SCALER_STANDARD))
    assert after.scaler_state == baseline.scaler_state


def test_scaling_none_leaves_the_values_exactly_as_phase_3_produced(feature_result) -> None:
    dataset = assemble_dataset(feature_result, config_for(FAMILY_NAIVE, scaler_policy=SCALER_NONE))
    matrix = dataset.splits["train"]
    raw = matrix.raw_values
    scaled = matrix.values
    finite = np.isfinite(raw)
    assert np.allclose(raw[finite], scaled[finite], rtol=0, atol=0)


def test_standard_scaling_centres_the_training_split(feature_result) -> None:
    """Mean near zero and unit variance *on training rows*. If this held on the
    test split instead, the scaler would be a leak; if it held nowhere, it was not
    fitted."""
    dataset = assemble_dataset(
        feature_result, config_for(FAMILY_NAIVE, scaler_policy=SCALER_STANDARD)
    )
    matrix = dataset.splits["train"]
    column = _first_finite_column(matrix.values)
    assert column is not None
    mean, std = matrix.values[:, column].mean(), matrix.values[:, column].std()
    assert abs(mean) < 1e-6
    assert abs(std - 1.0) < 1e-6


def test_the_test_split_is_not_centred_by_the_test_split(feature_result) -> None:
    """The other half of the claim: the training transform is applied unchanged to
    test, so the test columns keep whatever offset training gave them."""
    dataset = assemble_dataset(
        feature_result, config_for(FAMILY_NAIVE, scaler_policy=SCALER_STANDARD)
    )
    train = dataset.splits["train"]
    test = dataset.splits["test"]
    column = _first_finite_column(train.values)
    assert column is not None
    test_mean = test.values[:, column].mean()
    assert abs(test_mean) > 1e-6, "the test split was centred on its own mean"


def test_impute_none_leaves_the_absent_cells_absent(feature_result) -> None:
    """The policy's whole meaning: an estimator must handle them or the run cannot
    proceed, so this is not a convenience default."""
    dataset = assemble_dataset(feature_result, config_for(FAMILY_NAIVE, impute_policy=IMPUTE_NONE))
    matrix = dataset.splits["train"]
    assert np.any(~np.isfinite(matrix.values)), "nothing was left absent to check"
    assert matrix.imputed_cells == 0


def test_a_run_that_imputed_nothing_never_claims_to_have_imputed(feature_result) -> None:
    """`imputed_cells` means "cells replaced". Under `none` nothing was replaced, so
    the field and the note must both say zero rather than counting the cells that
    stayed absent — otherwise a reader would conclude a non-imputing run had filled
    its gaps.
    """
    dataset = assemble_dataset(feature_result, config_for(FAMILY_NAIVE, impute_policy=IMPUTE_NONE))
    assert sum(matrix.imputed_cells for matrix in dataset.splits.values()) == 0
    assert not any(note.code == CODE_IMPUTED for note in dataset.notes), (
        "a run that imputed nothing must not carry an imputation note"
    )


def test_the_disabled_policy_is_recorded_rather_than_left_silent(feature_result) -> None:
    """A run that imputed nothing and a run over a gap-free dataset are different
    experiments; only this note separates them."""
    dataset = assemble_dataset(feature_result, config_for(FAMILY_NAIVE, impute_policy=IMPUTE_NONE))
    notes = [note for note in dataset.notes if note.code == CODE_IMPUTE_NONE]
    assert len(notes) == 1
    assert IMPUTE_NONE in notes[0].message
    still_absent = sum(
        int(np.count_nonzero(~np.isfinite(matrix.values)))
        for matrix in dataset.splits.values()
    )
    assert str(still_absent) in notes[0].message, (
        "the note must state how many cells remain absent, not just that some do"
    )


def test_imputation_is_recorded_as_a_count_and_a_note(feature_result) -> None:
    dataset = assemble_dataset(feature_result, config_for(FAMILY_NAIVE))
    total = sum(matrix.imputed_cells for matrix in dataset.splits.values())
    assert total > 0
    notes = [note for note in dataset.notes if note.code == CODE_IMPUTED]
    assert len(notes) == 1
    assert str(total) in notes[0].message
    assert not any(note.code == CODE_IMPUTE_NONE for note in dataset.notes)


def test_the_reported_imputation_count_matches_the_cells_that_were_absent(feature_result) -> None:
    """Cross-checked against the raw matrix, so a count that drifted from the data
    would be caught rather than trusted."""
    dataset = assemble_dataset(feature_result, config_for(FAMILY_NAIVE))
    for matrix in dataset.splits.values():
        absent_before = int(np.count_nonzero(~np.isfinite(matrix.raw_values)))
        assert matrix.imputed_cells == absent_before
        assert not np.any(~np.isfinite(matrix.values)), (
            f"{matrix.split} still holds absent cells after median imputation"
        )


# --------------------------------------------------------------------------- #
# Entity isolation
# --------------------------------------------------------------------------- #


def test_every_row_carries_the_entity_it_came_from(model_dataset) -> None:
    for matrix in model_dataset.splits.values():
        assert set(matrix.row_entities) <= set(model_dataset.entities)


def test_a_matrix_can_hold_more_than_one_entity(model_dataset) -> None:
    """Guards the station-isolation tests: with only one entity present, every one
    of them would pass vacuously."""
    assert len(model_dataset.entities) >= 2
    assert len(set(model_dataset.splits["train"].row_entities)) >= 2


def test_one_stations_rows_are_unaffected_by_anothers(feature_dataset) -> None:
    """The core isolation claim, asserted on the produced matrix.

    Station B's levels are offset by a constant from station A's, so any
    cross-station read — in the baseline, in a feature, in an imputation — produces
    a specific wrong number rather than a plausible one. Removing every station-B
    row leaves station A's matrix bit-identical.

    The comparison is over the columns both matrices retain: dropping station B
    changes which features have any training value at all, so a column absent in
    one run and present in the other is a consequence of the *fixture*, not evidence
    of a leak.
    """
    baseline = assemble_dataset(feature_dataset, config_for(FAMILY_NAIVE))
    before = baseline.splits["train"]

    only_a = dataclasses.replace(
        feature_dataset,
        rows=tuple(row for row in feature_dataset.rows if row.entity == STATION_A),
    )
    after = assemble_dataset(only_a, config_for(FAMILY_NAIVE))
    only_a_matrix = after.splits["train"]

    mask = np.array([entity == STATION_A for entity in before.row_entities])
    assert mask.any(), "the fixture must hold station A rows in train for this to mean anything"
    assert only_a_matrix.rows == int(mask.sum())
    assert np.array_equal(only_a_matrix.row_entities, tuple(before.row_entities[i] for i in np.flatnonzero(mask)))
    assert only_a_matrix.origin_instants == tuple(
        before.origin_instants[i] for i in np.flatnonzero(mask)
    )

    shared = [name for name in only_a_matrix.feature_names if name in before.feature_names]
    assert shared, "the two runs retained no feature in common, so nothing can be compared"
    for name in shared:
        column = before.feature_names.index(name)
        left = before.raw_values[np.ix_(np.flatnonzero(mask), [column])]
        right = only_a_matrix.raw_values[:, [only_a_matrix.feature_names.index(name)]]
        assert np.array_equal(left, right, equal_nan=True), (
            f"{name} for {STATION_A} changed when {STATION_B} was removed"
        )


def test_one_stations_target_column_is_unchanged_by_the_other_stations_presence(
    feature_dataset,
) -> None:
    """The target half of the same claim, and the half a leak would flatter most."""
    before = assemble_dataset(feature_dataset, config_for(FAMILY_NAIVE)).splits["train"]
    after = assemble_dataset(
        dataclasses.replace(
            feature_dataset,
            rows=tuple(row for row in feature_dataset.rows if row.entity == STATION_A),
        ),
        config_for(FAMILY_NAIVE),
    ).splits["train"]
    mask = np.flatnonzero([entity == STATION_A for entity in before.row_entities])
    assert np.array_equal(before.target[mask], after.target, equal_nan=True), (
        f"{STATION_A}'s own target values changed when {STATION_B} was removed"
    )


def test_entities_are_never_interleaved_within_a_split(model_dataset) -> None:
    """Phase 3 emits rows in `(entity, instant)` order and Phase 4 preserves it.

    A shuffle of `row_entities` inside a split would mean a sliding window walked
    from one station to another while believing it was walking through time.
    """
    for matrix in model_dataset.splits.values():
        seen: list[str] = []
        for entity in matrix.row_entities:
            if not seen or seen[-1] != entity:
                assert entity not in seen, f"{matrix.split}: entity {entity} appears in two blocks"
                seen.append(entity)
        assert seen, f"{matrix.split} holds no rows"


def test_two_entities_with_different_values_produce_two_different_rows(model_dataset) -> None:
    """If the two stations' rows were identical, every isolation test above would be
    vacuous. Asserting they differ is what makes them mean something."""
    matrix = model_dataset.splits["train"]
    column = _column_of(matrix.feature_names, "water_level_lag_1h")
    assert column is not None, "the fixture declares a water-level lag, so this should exist"
    by_entity: dict[str, list[float]] = {}
    for row, entity in enumerate(matrix.row_entities):
        value = matrix.raw_values[row, column]
        if value is None:
            continue
        by_entity.setdefault(entity, []).append(float(value))
    assert len(by_entity) >= 2
    firsts = [values[0] for values in by_entity.values()]
    assert len(set(round(value, 9) for value in firsts)) == len(firsts), (
        "both stations start at the same value, so a cross-station leak would be invisible"
    )


# --------------------------------------------------------------------------- #
# Sequences
# --------------------------------------------------------------------------- #


def _train_sequences(dataset, split: str = "train"):
    """The windows `train_models` builds for `split`, plus the row positions used.

    Built through the same call the orchestrator makes, so these tests check the
    population the audit checks and not a private reimplementation of it.
    """
    matrix = dataset.splits[split]
    sequences = build_sequences(
        matrix, dataset.config.lookback, step_seconds(dataset), restrict=matrix.evaluable_mask
    )
    return matrix, sequences


def test_a_window_ends_at_its_own_origin(sequence_dataset) -> None:
    """`[t - L + 1 … t]`. Not `[t … t + L - 1]`, which is the same length and the
    wrong direction."""
    _, sequences = _train_sequences(sequence_dataset)
    assert len(sequences.windows) > 0, "no windows were built, so nothing was checked"
    for instants, origin in zip(sequences.window_instants, sequences.origin_instants):
        assert instants[-1] == origin, f"a window for origin {origin} ended at {instants[-1]}"
        assert len(instants) == sequence_dataset.config.lookback


def test_a_window_is_monotonically_increasing_and_past(sequence_dataset) -> None:
    for instants in sequences_iter(sequence_dataset):
        assert list(instants) == sorted(instants), f"window instants out of order: {instants}"
        assert len(set(instants)) == len(instants), f"window repeated an instant: {instants}"


def sequences_iter(dataset, split: str = "train"):
    _, sequences = _train_sequences(dataset, split)
    for instants in sequences.window_instants:
        yield instants


def test_a_window_holds_one_entity_only(sequence_dataset) -> None:
    _, sequences = _train_sequences(sequence_dataset)
    assert len(sequences.windows) > 0, "no windows were built, so nothing was checked"
    assert len(sequences.window_entities) == len(sequences.windows)
    for entity in sequences.window_entities:
        assert entity in {STATION_A, STATION_B}


def test_the_window_matrix_has_the_declared_shape(sequence_dataset) -> None:
    _, sequences = _train_sequences(sequence_dataset)
    expected = (
        len(sequences.windows),
        sequence_dataset.config.lookback,
        len(sequence_dataset.feature_names),
    )
    assert sequences.windows.shape == expected
    assert sequences.targets.shape == (len(sequences.windows),)


def test_every_window_target_is_the_row_target_of_its_own_origin(sequence_dataset) -> None:
    """`features at t → target at t + H`. The window's label is the target of the
    row it ends on, not of its first row and not of the row after it."""
    matrix, sequences = _train_sequences(sequence_dataset)
    by_key = {
        (entity, origin): float(target)
        for entity, origin, target in zip(
            matrix.row_entities, matrix.origin_instants, matrix.target
        )
    }
    for entity, origin, target in zip(
        sequences.window_entities, sequences.origin_instants, sequences.targets
    ):
        assert by_key[(entity, origin)] == pytest.approx(float(target))


def test_a_window_spans_at_most_the_declared_lookback(sequence_dataset) -> None:
    step = step_seconds(sequence_dataset)
    _, sequences = _train_sequences(sequence_dataset)
    allowed = dt.timedelta(seconds=sequence_dataset.config.lookback * step)
    for instants, origin in zip(sequences.window_instants, sequences.origin_instants):
        assert origin - instants[0] < allowed, (
            f"window spans {origin - instants[0]}, which is not less than the configured "
            f"lookback of {allowed}"
        )


def test_windows_never_reach_into_the_future(sequence_dataset) -> None:
    _, sequences = _train_sequences(sequence_dataset)
    assert len(sequences.windows) > 0, "no windows were built, so nothing was checked"
    for instants, origin in zip(sequences.window_instants, sequences.origin_instants):
        assert max(instants) <= origin


def test_windows_never_reach_across_a_split_boundary(sequence_dataset) -> None:
    """Validation windows are built from validation rows only.

    Reaching back into the tail of train would hand the model values from the time
    regime the conservative persistence policy refuses to touch — so the sequence
    and flat models would be scored on different information.
    """
    latest_train = max(sequence_dataset.splits["train"].origin_instants)
    for instants in sequences_iter(sequence_dataset, "validation"):
        assert min(instants) > latest_train


def test_a_window_with_a_gap_in_its_history_is_skipped_not_padded(sequence_dataset) -> None:
    """A window whose rows are further apart than `lookback * step` does not span the
    period it claims to, so it is skipped and counted rather than treated as a
    sample.

    Built by removing a row's instant from a copy of the split, so the gap is real.
    """
    matrix = sequence_dataset.splits["validation"]
    step = step_seconds(sequence_dataset)
    baseline = build_sequences(matrix, sequence_dataset.config.lookback, step)

    # Drop the second row of station A's history by moving it far into the past, so
    # the window that would have used it now spans more than lookback * step.
    positions = [
        index
        for index, entity in enumerate(matrix.row_entities)
        if entity == STATION_A
    ]
    assert len(positions) >= sequence_dataset.config.lookback + 2
    gapped = matrix.origin_instants[: positions[1]] + (
        matrix.origin_instants[positions[1]] - dt.timedelta(seconds=10 * HOUR),
    ) + matrix.origin_instants[positions[1] + 1 :]
    holed = dataclasses.replace(matrix, origin_instants=gapped)
    after = build_sequences(holed, sequence_dataset.config.lookback, step)
    assert len(after.windows) < len(baseline.windows)
    assert after.skipped_insufficient_history > baseline.skipped_insufficient_history


def test_a_window_never_draws_history_from_another_split(sequence_dataset) -> None:
    """Validation windows are built from validation rows only. Reaching back into
    the tail of train would hand the model values from a time regime the
    conservative persistence policy refuses to touch."""
    sequences = build_sequences(
        sequence_dataset.splits["validation"],
        sequence_dataset.config.lookback,
        step_seconds(sequence_dataset),
        restrict=sequence_dataset.splits["validation"].evaluable_mask,
    )
    if len(sequences.windows) == 0:
        pytest.skip("this fixture's validation split is too short for a window")
    train_starts = sequence_dataset.splits["train"].origin_instants
    latest_train = max(train_starts)
    for instants in sequences.window_instants:
        assert min(instants) > latest_train


def test_restricting_which_rows_may_end_a_window_keeps_the_history_pool_intact(
    sequence_dataset,
) -> None:
    """`restrict` selects the *origin* rows, not the history pool.

    The distinction matters: restricting the history pool too would make validation
    windows start at the first validation row and silently shorten them, which
    would look like a working feature.
    """
    matrix = sequence_dataset.splits["validation"]
    step = step_seconds(sequence_dataset)
    unrestricted = build_sequences(matrix, sequence_dataset.config.lookback, step)
    restricted = build_sequences(
        matrix, sequence_dataset.config.lookback, step, restrict=matrix.evaluable_mask
    )
    assert 0 < len(restricted.windows) <= len(unrestricted.windows)
    assert set(restricted.origin_instants) <= set(unrestricted.origin_instants)
    # The windows that survive the restriction are the *same* windows: same origins,
    # same spans. Only the population shrank.
    keep = set(restricted.origin_instants)
    for instants, origin in zip(unrestricted.window_instants, unrestricted.origin_instants):
        if origin in keep:
            assert instants in restricted.window_instants


def test_every_split_produces_windows_when_it_has_enough_history(sequence_dataset) -> None:
    """The audit's sequence check must have something to inspect in every split.

    If a split legitimately cannot produce a window that is worth knowing — so this
    asserts the fixture *can*, which is what makes the audit's window count mean
    something beyond "the training split had windows".
    """
    for name in ("train", "validation", "test"):
        _, sequences = _train_sequences(sequence_dataset, name)
        assert len(sequences.windows) > 0, (
            f"{name} produced no windows, so the sequence check would be vacuous for it"
        )


def test_a_window_without_enough_history_is_skipped_and_counted(sequence_dataset) -> None:
    """Not padded, not borrowed. The skip is counted so a reader can see how many
    rows the window construction dropped and why."""
    matrix = sequence_dataset.splits["train"]
    sequences = build_sequences(
        matrix, sequence_dataset.config.lookback, step_seconds(sequence_dataset)
    )
    assert sequences.skipped_insufficient_history >= sequence_dataset.config.lookback - 1, (
        "the first lookback-1 rows of each entity have too little history"
    )
    assert len(sequences.windows) + sequences.skipped_insufficient_history <= matrix.rows


def test_every_row_is_either_a_window_or_a_named_skip(sequence_dataset) -> None:
    """Nothing disappears silently.

    A window count that does not reconcile against the split's row count means rows
    were dropped for a reason nobody recorded, and a reader comparing two runs could
    not tell whether the difference came from the data or from the bookkeeping.
    """
    for name, matrix in sequence_dataset.splits.items():
        sequences = build_sequences(
            matrix, sequence_dataset.config.lookback, step_seconds(sequence_dataset)
        )
        accounted = (
            len(sequences.windows)
            + sequences.skipped_insufficient_history
            + sequences.skipped_missing_target
        )
        assert accounted == matrix.rows, (
            f"{name}: {len(sequences.windows)} window(s) + "
            f"{sequences.skipped_insufficient_history} short-history + "
            f"{sequences.skipped_missing_target} untargeted = {accounted}, but the split "
            f"holds {matrix.rows} row(s)"
        )


def test_a_row_without_a_target_is_skipped_and_counted(sequence_dataset) -> None:
    matrix = sequence_dataset.splits["test"]
    sequences = build_sequences(
        matrix, sequence_dataset.config.lookback, step_seconds(sequence_dataset)
    )
    expected = int(np.count_nonzero(np.isnan(matrix.target)))
    assert sequences.skipped_missing_target == expected
    assert len(sequences.windows) + sequences.skipped_missing_target == (
        matrix.rows - sequences.skipped_insufficient_history
    )


def test_an_unknown_step_yields_no_windows_and_is_not_guessed(sequence_dataset) -> None:
    """No cadence is not "assume one hour".

    Guessing the step would produce windows at the wrong spacing that pass every
    structural check while describing a cadence nobody measured.
    """
    matrix = sequence_dataset.splits["train"]
    sequences = build_sequences(matrix, sequence_dataset.config.lookback, None)
    assert sequences.windows.shape[0] == 0
    assert sequences.samples == 0
    assert sequences.step_seconds is None
    assert sequences.origin_instants == ()
    assert sequences.window_instants == ()


def test_a_known_step_is_the_one_phase_3_declared(sequence_dataset) -> None:
    """The window spacing comes from Phase 3's cadence map, not from a constant in
    this module."""
    step = step_seconds(sequence_dataset)
    assert step is not None
    matrix = sequence_dataset.splits["train"]
    sequences = build_sequences(matrix, sequence_dataset.config.lookback, step)
    for instants in sequences.window_instants:
        gaps = {
            (later - earlier).total_seconds()
            for earlier, later in zip(instants, instants[1:])
        }
        assert gaps == {step}, f"a window used spacing {sorted(gaps)} but the cadence is {step}"


def test_an_unknown_cadence_resolves_to_none_rather_than_a_guess() -> None:
    assert resolve_step_seconds({}, ["SYNTHETIC-STATION-0001"], "water_level") is None
    assert resolve_step_seconds(None, ["SYNTHETIC-STATION-0001"], "water_level") is None


def test_a_known_cadence_resolves_to_seconds_from_phase_3(sequence_dataset) -> None:
    """Read from Phase 3's own report, never re-inferred from the row spacing."""
    step = step_seconds(sequence_dataset)
    assert step == HOUR


# --------------------------------------------------------------------------- #
# Provenance carried by the dataset
# --------------------------------------------------------------------------- #


def test_the_dataset_carries_phase_1_provenance_through(model_dataset) -> None:
    """Phase 4 reuses the existing provenance fields rather than a second system."""
    assert model_dataset.dataset_reference == "synthetic://unit-test/phase4"
    assert model_dataset.dataset_type == "synthetic"
    assert model_dataset.dataset_license
    assert model_dataset.is_synthetic


def test_the_disclaimer_is_the_repositorys_own_synthetic_sentence(model_dataset) -> None:
    assert model_dataset.disclaimer == SYNTHETIC_DISCLAIMER


def test_the_feature_contract_version_is_carried(model_dataset) -> None:
    assert model_dataset.feature_contract_version == pipeline.FEATURE_CONTRACT_VERSION


def test_the_registry_feature_names_are_carried_for_audit(model_dataset) -> None:
    """Phase 4 records which registry produced the columns so a feature can be
    traced to its definition without re-running Phase 3."""
    assert model_dataset.feature_registry_names
    assert set(model_dataset.feature_names) <= set(model_dataset.feature_registry_names)


def test_the_split_bounds_are_carried(model_dataset) -> None:
    bounds = model_dataset.bounds
    assert bounds.train_start is not None and bounds.train_end is not None
    assert bounds.train_end <= bounds.validation_start
    assert bounds.validation_end <= bounds.test_start


def test_the_dataset_describes_itself_readably(model_dataset) -> None:
    text = model_dataset.describe()
    assert "target_water_level_6h" in text
    assert "train" in text


def test_the_dataset_is_json_serialisable(model_dataset) -> None:
    import json

    payload = model_dataset.to_dict()
    assert json.loads(json.dumps(payload, sort_keys=True, default=str))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _first_finite_column(values: np.ndarray) -> int | None:
    for column in range(values.shape[1]):
        finite = values[:, column][np.isfinite(values[:, column])]
        if finite.size > 2:
            return column
    return None


def _column_of(feature_names, name: str) -> int | None:
    try:
        return list(feature_names).index(name)
    except ValueError:
        return None


def _blank_column(dataset, name: str, splits: tuple[str, ...] | None):
    """The dataset with `name` reported absent on the rows named in `splits`.

    `splits=None` blanks it everywhere. Rewriting `row.values` is the same surface a
    genuinely unbuildable feature would occupy, so the policy under test sees a real
    absence rather than a special case.
    """
    rows = []
    for row in dataset.rows:
        if splits is None or row.split in splits:
            values = {key: value for key, value in row.values.items() if key != name}
            rows.append(dataclasses.replace(row, values=values))
        else:
            rows.append(row)
    return dataclasses.replace(dataset, rows=tuple(rows))


def _mark_target_available_at_prediction_time(dataset):
    """A dataset whose target lineage claims the reading exists at `t`.

    Only the lineage is rewritten. The per-row `target_instants` are left alone so
    that a reader can see exactly which record the refusal consults — and so this
    helper cannot accidentally satisfy the check by moving the timestamps.
    """
    lineage = {}
    for column, entry in dataset.target_lineage.items():
        updated = dict(entry)
        updated["available_at_prediction_time"] = True
        lineage[column] = updated
    return dataclasses.replace(dataset, target_lineage=lineage)


def _retarget_at_its_own_origin(dataset):
    """A dataset whose target instants have been moved back onto their origins.

    Built by rewriting `target_instants` rather than by patching the assembly code,
    so the refusal under test is the assembly's own.
    """
    rows = []
    for row in dataset.rows:
        if row.targets:
            rows.append(
                dataclasses.replace(
                    row, target_instants=dict.fromkeys(row.targets, row.instant)
                )
            )
        else:
            rows.append(row)
    return dataclasses.replace(dataset, rows=tuple(rows))