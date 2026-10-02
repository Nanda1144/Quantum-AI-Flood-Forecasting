# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 2 tests: duplicates, conflicts and missing values.

Covers the middle groups of the Phase 2 test matrix:

* **D. Duplicates** -- identity, exact vs conflicting, no silent averaging.
* **E. Conflicts** -- refused by default, explicit policy plus citation.
* **F. Missing values** -- retain by default, opt-in fills, honest provenance.

All inputs are SYNTHETIC/DEMO data. Nothing here measures hydrological skill.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.engines.hydro.domains import QUALITY_MISSING, Measurement, Observation
from app.engines.hydro.preprocess_config import (
    CONFLICT_ERROR,
    CONFLICT_KEEP_FIRST,
    CONFLICT_KEEP_LAST,
    CONFLICT_POLICIES_THAT_FABRICATE,
    DUPLICATE_ERROR,
    DUPLICATE_KEEP_FIRST,
    DUPLICATE_KEEP_LAST,
    DUPLICATE_REPORT,
    MISSING_BACKWARD_FILL,
    MISSING_DROP,
    MISSING_FORWARD_FILL,
    MISSING_LINEAR_BIDIRECTIONAL,
    MISSING_LINEAR_CAUSAL,
    MISSING_REJECT,
    MISSING_RETAIN,
    PreprocessConfig,
    PreprocessConfigError,
)
from app.engines.hydro.preprocess_pipeline import (
    PreprocessError,
    resolve_duplicates_and_conflicts,
    slot_identity,
)
from app.engines.hydro.preprocess_temporal import (
    Duration,
    TemporalError,
    apply_missing_policy,
    build_grid,
    infer_base_interval,
    interval_regularity,
)

BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)
SOURCE_A = "synthetic://demo/source-a"
SOURCE_B = "synthetic://demo/source-b"

#: A config that tolerates a conflict by name. Nothing may resolve a conflict
#: without one, so tests that are not *about* the refusal need it.
CITED_CONFLICT = PreprocessConfig(
    conflict_policy=CONFLICT_KEEP_FIRST,
    conflict_policy_source="synthetic://demo/ticket",
)


def instant(hours: float = 0) -> str:
    return (BASE + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def observation(
    hours: float = 0,
    *,
    value: float = 1.0,
    unit: str = "mm",
    quantity: str = "rainfall",
    entity: str = "SYNTHETIC-STATION-0001",
    source: str = SOURCE_A,
) -> Observation:
    return Observation(
        domain=quantity,
        location_reference=entity,
        observed_at=instant(hours),
        source_reference=source,
        measurements=(Measurement(quantity=quantity, value=value, unit=unit),),
        dataset_type="synthetic",
    )


def series(hours, **kwargs) -> list[Observation]:
    return [observation(hour, **kwargs) for hour in hours]


def repeated(record: Observation) -> Observation:
    """A *distinct* record carrying the same reading as `record`.

    Built rather than reused, because appending the same object twice would test
    reference identity instead of value duplication.
    """
    return Observation(
        domain=record.domain,
        location_reference=record.location_reference,
        observed_at=record.observed_at,
        source_reference=record.source_reference,
        measurements=record.measurements,
        dataset_type=record.dataset_type,
    )


# --------------------------------------------------------------------------- #
# D. Duplicates
# --------------------------------------------------------------------------- #


class TestDuplicateDetection:
    def test_identical_rows_are_an_exact_duplicate(self):
        records = series(range(20))
        duplicates = records + [repeated(records[3])]
        survivors, report = resolve_duplicates_and_conflicts(
            duplicates, PreprocessConfig()
        )
        assert report.duplicate_slot_groups == 1
        assert report.removed == 0  # the default reports rather than removing

    def test_a_repeated_reading_is_counted_once_even_though_it_compares_equal(self):
        """`Observation` is a frozen dataclass, so two identical rows compare equal.

        Counting affected records in a `set` of records would report 1 where two
        distinct rows exist. The count is by identity.
        """
        records = series(range(20))
        survivors, report = resolve_duplicates_and_conflicts(
            records + [repeated(records[3])], PreprocessConfig()
        )
        assert report.duplicate_slot_groups == 1
        assert report.duplicate_records == 2

    def test_a_differing_value_at_the_same_instant_is_a_conflict_not_a_duplicate(self):
        records = series(range(20))
        with pytest.raises(PreprocessError):
            resolve_duplicates_and_conflicts(
                records + [observation(3, value=99.0)], PreprocessConfig()
            )
        _, report = resolve_duplicates_and_conflicts(
            records + [observation(3, value=99.0)], CITED_CONFLICT
        )
        assert report.duplicate_slot_groups == 0
        assert report.conflicting_slot_groups == 1

    def test_two_sources_reporting_one_gauge_are_neither_duplicate_nor_conflict(self):
        """Identity includes the source, so a merge is surfaced, not silently done."""
        records = series(range(20), source=SOURCE_A)
        other = series(range(20), value=5.0, source=SOURCE_B)
        survivors, report = resolve_duplicates_and_conflicts(
            records + other, PreprocessConfig()
        )
        assert report.duplicate_slot_groups == 0
        assert report.conflicting_slot_groups == 0
        assert len(survivors) == 40

    def test_a_cross_source_merge_decision_is_published_as_an_advisory(self):
        """Phase 1's check ignores the source, so it sees the merge Phase 2 declines."""
        records = series(range(20), source=SOURCE_A)
        other = series(range(20), value=5.0, source=SOURCE_B)
        _, report = resolve_duplicates_and_conflicts(records + other, PreprocessConfig())
        assert report.cross_source is not None
        assert len(report.cross_source.conflicting_keys) > 0

    def test_slot_identity_distinguishes_quantity_source_and_instant(self):
        base = observation(0)
        assert slot_identity(base, "rainfall") == slot_identity(observation(0), "rainfall")
        assert slot_identity(base, "rainfall") != slot_identity(
            observation(0, source=SOURCE_B), "rainfall"
        )
        assert slot_identity(base, "rainfall") != slot_identity(observation(1), "rainfall")
        assert slot_identity(base, "rainfall") != slot_identity(base, "water_level")

    @pytest.mark.parametrize(
        ("policy", "removed", "surviving"),
        [
            (DUPLICATE_REPORT, 0, 21),
            (DUPLICATE_KEEP_FIRST, 1, 20),
            (DUPLICATE_KEEP_LAST, 1, 20),
        ],
    )
    def test_duplicate_policies(self, policy, removed, surviving):
        records = series(range(20))
        survivors, report = resolve_duplicates_and_conflicts(
            records + [repeated(records[3])], PreprocessConfig(duplicate_policy=policy)
        )
        assert report.removed == removed
        assert len(survivors) == surviving

    def test_duplicate_error_policy_refuses_rather_than_choosing(self):
        records = series(range(20))
        with pytest.raises(PreprocessError) as caught:
            resolve_duplicates_and_conflicts(
                records + [repeated(records[3])],
                PreprocessConfig(duplicate_policy=DUPLICATE_ERROR),
            )
        assert "duplicate" in str(caught.value).lower()

    def test_keep_first_and_keep_last_differ_in_which_row_survives(self):
        base = series(range(20), value=5.0)
        records = base + [observation(5, value=42.0)]
        for policy, expected in ((DUPLICATE_KEEP_FIRST, 5.0), (DUPLICATE_KEEP_LAST, 42.0)):
            config = PreprocessConfig(
                duplicate_policy=policy,
                conflict_policy=CONFLICT_KEEP_FIRST if policy == DUPLICATE_KEEP_FIRST else CONFLICT_KEEP_LAST,
                conflict_policy_source="synthetic://demo/ticket",
            )
            survivors, _ = resolve_duplicates_and_conflicts(records, config)
            values = [
                r.measurements[0].value
                for r in survivors
                if r.instant == observation(5).instant
            ]
            assert values == [expected]


# --------------------------------------------------------------------------- #
# E. Conflicts
# --------------------------------------------------------------------------- #


class TestConflictHandling:
    def test_conflict_is_refused_by_default(self):
        records = series(range(20)) + [observation(3, value=99.0)]
        with pytest.raises(PreprocessError) as caught:
            resolve_duplicates_and_conflicts(records, PreprocessConfig())
        message = str(caught.value)
        assert "conflict_policy" in message
        assert "2024-01-01T03:00:00Z" in message  # names the instant at fault
        assert "= 1.0 mm" in message  # and the reading it is contradicting

    def test_resolving_a_conflict_requires_a_citation(self):
        """Choosing between two readings of one instant is a human decision."""
        with pytest.raises(PreprocessConfigError) as caught:
            PreprocessConfig(conflict_policy=CONFLICT_KEEP_FIRST)
        assert "conflict_policy_source" in str(caught.value)

    @pytest.mark.parametrize("policy", [CONFLICT_KEEP_FIRST, CONFLICT_KEEP_LAST])
    def test_a_cited_conflict_policy_resolves_and_records_the_citation(self, policy):
        records = series(range(20)) + [observation(3, value=99.0)]
        config = PreprocessConfig(
            conflict_policy=policy, conflict_policy_source="synthetic://demo/ticket-42"
        )
        survivors, report = resolve_duplicates_and_conflicts(records, config)
        assert report.conflicting_slot_groups == 1
        assert report.removed == 1
        assert len(survivors) == 20
        assert any(
            "synthetic://demo/ticket-42" in note.message for note in report.notes
        ), "the citation must appear in the report, not only in the config"

    def test_no_conflict_policy_averages_the_readings(self):
        """Averaging two disagreeing gauges invents a third reading nobody made."""
        assert CONFLICT_POLICIES_THAT_FABRICATE == ()

    @pytest.mark.parametrize(
        ("policy", "expected"), [(CONFLICT_KEEP_FIRST, 1.0), (CONFLICT_KEEP_LAST, 99.0)]
    )
    def test_a_resolved_conflict_keeps_one_reading_and_not_a_middle_one(
        self, policy, expected
    ):
        records = series(range(20)) + [observation(3, value=99.0)]
        config = PreprocessConfig(
            conflict_policy=policy, conflict_policy_source="synthetic://demo/ticket"
        )
        survivors, _ = resolve_duplicates_and_conflicts(records, config)
        values = [
            r.measurements[0].value
            for r in survivors
            if r.instant == observation(3).instant
        ]
        assert values == [expected]
        assert 50.0 not in values  # the mean of the two is the fabricated option

    def test_conflicts_are_resolved_before_duplicates_are_counted(self):
        """A conflicting pair is a conflict; collapsing it silently is not dedup."""
        records = series(range(20)) + [observation(3, value=99.0)]
        _, report = resolve_duplicates_and_conflicts(records, CITED_CONFLICT)
        assert report.duplicate_slot_groups == 0
        assert report.conflicting_slot_groups == 1


# --------------------------------------------------------------------------- #
# F. Missing values
# --------------------------------------------------------------------------- #


class TestIntervalInference:
    def test_a_regular_series_infers_its_cadence(self):
        records = series(range(60))
        assert infer_base_interval(records).seconds == 3600.0
        assert interval_regularity(records, infer_base_interval(records)) == 1.0

    def test_a_series_with_one_gap_still_infers_its_cadence(self):
        """The modal-gap rule called this irregular and disabled gap handling.

        Dropout is the normal condition for a real gauge, so the stage that exists
        to report it must run on exactly the data that needs it.
        """
        records = series([0, 1, 4, 5, 6, 7, 8, 9])
        interval = infer_base_interval(records)
        assert interval is not None
        assert interval.seconds == 3600.0
        assert interval_regularity(records, interval) == pytest.approx(6 / 7)

    def test_a_single_record_infers_nothing(self):
        assert infer_base_interval(series(range(1))) is None

    def test_the_grid_makes_the_gap_visible(self):
        records = series([0, 1, 4, 5])
        slots = build_grid(records, infer_base_interval(records))
        assert [slot.is_gap for slot in slots] == [
            False,
            False,
            True,
            True,
            False,
            False,
        ]

    def test_build_grid_refuses_an_absurd_interval_rather_than_allocating(self):
        """A caller-supplied interval must not be able to allocate without limit.

        The bound is monkeypatched down so the test exercises the real guard
        quickly; running it against the production five-million-slot limit would
        mean five million loop iterations to prove a counter works.
        """
        from app.engines.hydro import preprocess_temporal

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(preprocess_temporal, "MAX_GRID_SLOTS", 10)
        try:
            records = series(range(50))
            with pytest.raises(TemporalError) as caught:
                build_grid(records, Duration(1.0))
        finally:
            monkeypatch.undo()
        assert "MAX_GRID_SLOTS" in str(caught.value)

    def test_the_grid_bound_is_a_finite_positive_number(self):
        from app.engines.hydro.preprocess_temporal import (
            MAX_GRID_EXPANSION,
            MAX_GRID_SLOTS,
            MIN_GRID_SLOTS,
        )

        assert 0 < MAX_GRID_SLOTS
        assert 0 < MIN_GRID_SLOTS <= MAX_GRID_SLOTS
        assert 0 < MAX_GRID_EXPANSION


class TestMissingPolicies:
    def grid(self, hours=(0, 1, 4, 5, 6, 7, 8, 9)):
        records = series(hours)
        return build_grid(records, infer_base_interval(records))

    def run(self, policy, hours=(0, 1, 4, 5, 6, 7, 8, 9), **kwargs):
        slots = self.grid(hours)
        config = PreprocessConfig(missing_policy=policy, **kwargs)
        return slots, apply_missing_policy(slots, config, quantities=("rainfall",))

    def test_retain_is_the_default_and_invents_nothing(self):
        slots, (filled, report) = self.run(MISSING_RETAIN)
        assert report.imputed == 0
        assert report.missing_before == 2
        assert report.missing_after == 2
        assert len(filled) == len(slots)

    def test_drop_removes_the_empty_slots(self):
        _, (filled, report) = self.run(MISSING_DROP)
        assert report.missing_after == 0
        assert report.imputed == 0
        assert all(not slot.is_gap for slot in filled)

    def test_forward_fill_is_opt_in_and_marks_what_it_invented(self):
        _, (filled, report) = self.run(MISSING_FORWARD_FILL)
        assert report.imputed == 2
        assert report.missing_after == 0
        for slot in filled:
            if slot.instant in (instant(2), instant(3)):
                assert all(
                    record.quality_status == QUALITY_MISSING
                    for record in slot.observations
                )

    def test_a_filled_value_names_the_instant_it_was_carried_from(self):
        _, (filled, _) = self.run(MISSING_FORWARD_FILL)
        notes = " ".join(
            record.notes
            for slot in filled
            for record in slot.observations
            if record.quality_status == QUALITY_MISSING
        )
        assert notes.strip(), "a filled row must record where the value came from"
        assert "no source record exists" in notes
        assert instant(1) in notes  # the donor instant, carried forward

    def test_the_input_grid_is_not_mutated(self):
        slots, (filled, _) = self.run(MISSING_FORWARD_FILL)
        assert sum(slot.is_gap for slot in slots) == 2, "the caller's grid changed"
        assert sum(slot.is_gap for slot in filled) == 0

    def test_reject_policy_refuses_the_batch(self):
        with pytest.raises(TemporalError) as caught:
            self.run(MISSING_REJECT)
        assert "gap" in str(caught.value).lower()

    def test_max_fill_gap_bounds_how_far_a_fill_may_reach(self):
        """Carrying a value across three missing hours is a different claim than one."""
        slots = self.grid((0, 1, 20, 21, 22))
        filled, report = apply_missing_policy(
            slots,
            PreprocessConfig(missing_policy=MISSING_FORWARD_FILL, max_fill_gap=2),
            quantities=("rainfall",),
        )
        assert report.beyond_max_gap > 0

    def test_a_leading_gap_is_never_filled(self):
        """There is no earlier value to carry, so nothing is invented.

        `build_grid` starts at the first observation, so a leading gap only exists
        when a caller supplies a grid that begins earlier -- which is exactly the
        case that must be left alone.
        """
        slots = self.grid((0, 1, 2, 3))
        padded = [replace(slots[0], observations=())] + slots
        filled, report = apply_missing_policy(
            padded, PreprocessConfig(missing_policy=MISSING_FORWARD_FILL),
            quantities=("rainfall",),
        )
        assert report.leading_gap == 1
        assert filled[0].is_gap, "a leading gap must survive a forward fill"

    def test_no_ordinary_grid_has_a_leading_gap(self):
        """Guards the previous test: the counter must not fire spuriously."""
        _, (_, report) = self.run(MISSING_FORWARD_FILL)
        assert report.leading_gap == 0

    @pytest.mark.parametrize("policy", [MISSING_FORWARD_FILL, MISSING_LINEAR_CAUSAL])
    def test_causal_policies_fill_a_short_interior_gap(self, policy):
        _, (filled, report) = self.run(policy)
        assert report.imputed == 2
        assert report.leakage_sensitive is False

    @pytest.mark.parametrize(
        "policy", [MISSING_BACKWARD_FILL, MISSING_LINEAR_BIDIRECTIONAL]
    )
    def test_backward_looking_policies_are_declared_leakage_sensitive(self, policy):
        """They read a later instant, so a model could learn from its own future."""
        config = PreprocessConfig(
            missing_policy=policy,
            allow_leakage_sensitive=True,
            acknowledged_leakage_operations=(f"missing_policy:{policy}",),
        )
        assert config.is_causal is False
        assert f"missing_policy:{policy}" in config.leakage_sensitive_operations

    @pytest.mark.parametrize(
        "policy", [MISSING_BACKWARD_FILL, MISSING_LINEAR_BIDIRECTIONAL]
    )
    def test_a_backward_looking_fill_needs_both_the_flag_and_the_name(self, policy):
        with pytest.raises(PreprocessConfigError) as caught:
            PreprocessConfig(missing_policy=policy)
        assert "allow_leakage_sensitive" in str(caught.value)
        with pytest.raises(PreprocessConfigError):
            PreprocessConfig(
                missing_policy=policy, allow_leakage_sensitive=True
            )

    def test_the_leakage_refusal_names_the_causal_alternatives(self):
        with pytest.raises(PreprocessConfigError) as caught:
            PreprocessConfig(missing_policy=MISSING_LINEAR_BIDIRECTIONAL)
        message = str(caught.value)
        assert "not causal" in message
        assert MISSING_FORWARD_FILL in message
        assert MISSING_LINEAR_CAUSAL in message

    def test_the_config_reports_whether_it_is_causal(self):
        assert PreprocessConfig().is_causal is True
        assert PreprocessConfig(missing_policy=MISSING_FORWARD_FILL).is_causal is True
        assert PreprocessConfig(missing_policy=MISSING_RETAIN).is_causal is True
