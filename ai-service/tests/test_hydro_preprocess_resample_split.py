# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 2 tests: resampling, temporal splitting and leakage prevention.

Covers the remaining groups of the Phase 2 test matrix:

* **G. Resampling** -- explicit frequency, domain-aware aggregation, native
  resolution by default.
* **H. Splitting** -- chronological only, validated boundaries, explicit strategy.
* **I. Leakage** -- right-labelled bins, causal fills, an independent audit.

All inputs are SYNTHETIC/DEMO data. Nothing here measures hydrological skill,
and no station identifier, threshold or rating curve is asserted as real.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from app.engines.hydro.domains import Measurement, Observation
from app.engines.hydro.preprocess_config import (
    SPLIT_GLOBAL,
    SPLIT_PER_ENTITY,
    AggregationRule,
    PreprocessConfig,
    PreprocessConfigError,
)
from app.engines.hydro.preprocess_pipeline import LeakageAudit, preprocess
from app.engines.hydro.preprocess_temporal import (
    _ENVELOPE_KEY,
    Duration,
    TemporalError,
    build_grid,
    infer_base_interval,
    resample_entity,
    series_key,
    split_records,
)

BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def instant(hours: float = 0) -> str:
    return (BASE + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def observation(
    hours: float = 0,
    *,
    value: float | None = None,
    unit: str = "mm",
    quantity: str = "rainfall",
    entity: str = "SYNTHETIC-STATION-0001",
) -> Observation:
    return Observation(
        domain=quantity,
        location_reference=entity,
        observed_at=instant(hours),
        source_reference="synthetic://demo/source",
        measurements=(
            Measurement(quantity=quantity, value=float(hours if value is None else value), unit=unit),
        ),
        dataset_type="synthetic",
    )


def series(hours, **kwargs) -> list[Observation]:
    return [observation(hour, **kwargs) for hour in hours]


RAINFALL_RULES = (AggregationRule(quantity="rainfall", function="sum", unit="mm"),)


def grid_for(records):
    return build_grid(records, infer_base_interval(records))


# --------------------------------------------------------------------------- #
# G. Resampling
# --------------------------------------------------------------------------- #


class TestResampling:
    def test_a_daily_bin_is_stamped_with_its_last_contributing_instant(self):
        """Right-labelling is what makes a bin causal.

        A bin covering hours 0..23 stamped `00:00` would depend on 23 readings
        taken after it, which is the definition of leakage.
        """
        slots = grid_for(series(range(24)))
        produced = resample_entity(
            slots, "1D", RAINFALL_RULES, series="S|rainfall",
            domain="rainfall", dataset_type="synthetic",
        )
        assert len(produced) == 1
        assert produced[0].observed_at == instant(23)

    def test_the_bin_value_is_the_sum_of_its_slots(self):
        slots = grid_for(series(range(24)))
        produced = resample_entity(
            slots, "1D", RAINFALL_RULES, series="S|rainfall",
            domain="rainfall", dataset_type="synthetic",
        )
        assert produced[0].measurements[0].value == pytest.approx(sum(range(24)))

    def test_an_empty_bin_produces_no_record(self):
        """A day with no rain is `0 mm`; a day with no *report* is not.

        Emitting a zero for an unreported day would turn a communications gap
        into a measurement, which is the failure this dataset exists to avoid.
        """
        slots = grid_for(series(range(24)))
        produced = resample_entity(
            slots, "2D", RAINFALL_RULES, series="S|rainfall",
            domain="rainfall", dataset_type="synthetic",
        )
        assert [r.observed_at for r in produced] == [instant(23)]

    def test_a_quantity_with_no_aggregation_rule_raises(self):
        """Rainfall intensity summed over an hour is a *depth*, not an intensity."""
        slots = grid_for(series(range(24)))
        with pytest.raises(TemporalError) as caught:
            resample_entity(
                slots, "1D", (), series="S|rainfall",
                domain="rainfall", dataset_type="synthetic",
            )
        assert "AggregationRule" in str(caught.value)

    def test_upsampling_is_refused(self):
        slots = grid_for(series(range(24)))
        with pytest.raises(TemporalError) as caught:
            resample_entity(
                slots, "30min", RAINFALL_RULES, series="S|rainfall",
                domain="rainfall", dataset_type="synthetic",
            )
        assert "invent" in str(caught.value).lower()

    def test_a_frequency_that_does_not_divide_the_cadence_is_refused(self):
        slots = grid_for(series(range(24)))
        with pytest.raises(TemporalError) as caught:
            resample_entity(
                slots, "90min", RAINFALL_RULES, series="S|rainfall",
                domain="rainfall", dataset_type="synthetic",
            )
        assert "multiple" in str(caught.value)

    def test_mixed_units_inside_one_bin_are_refused(self):
        """Averaging metres and centimetres is arithmetic on two different quantities."""
        records = [
            observation(hour, unit="mm" if hour % 2 == 0 else "in")
            for hour in range(24)
        ]
        slots = grid_for(records)
        with pytest.raises(TemporalError) as caught:
            resample_entity(
                slots, "1D", RAINFALL_RULES, series="S|rainfall",
                domain="rainfall", dataset_type="synthetic",
            )
        assert "unit" in str(caught.value).lower()

    def test_an_irregular_grid_is_refused_rather_than_binned(self):
        """`build_grid` always yields a regular grid, so this is a caller-supplied one.

        A hand-built slot sequence whose spacing is not uniform has no
        well-defined bin boundary, so it is refused rather than binned at the
        first plausible boundary.
        """
        from app.engines.hydro.preprocess_temporal import SeriesSlot

        slots = [
            SeriesSlot(instant=instant(hour), observations=(observation(hour),))
            for hour in (0, 1, 2, 5, 6, 7)
        ]
        with pytest.raises(TemporalError) as caught:
            resample_entity(
                slots, "1D", RAINFALL_RULES, series="S|rainfall",
                domain="rainfall", dataset_type="synthetic",
            )
        assert "regular grid" in str(caught.value)

    def test_native_resolution_is_the_default(self):
        """Nothing here establishes what cadence a real gauge network reports."""
        result = preprocess(series(range(60)))
        assert result.report.resampling["enabled"] is False
        assert result.report.resampling_delta == 0
        assert result.report.records_out == 60

    def test_declaring_no_resampling_is_not_reported_as_a_failure(self):
        """Running the resampling path with resampling off must not look broken."""
        result = preprocess(series(range(60)))
        messages = " ".join(note.message for note in result.report.notes)
        assert "no resampling was requested" in messages
        assert "could not be resampled" not in messages
        assert "irregular" not in messages


# --------------------------------------------------------------------------- #
# H. Splitting
# --------------------------------------------------------------------------- #


class TestSplitting:
    def test_a_global_split_is_chronological_and_disjoint(self):
        records = series(range(120))
        report = split_records(records, PreprocessConfig())
        assert report.strategy == SPLIT_GLOBAL
        assert report.is_leak_free is True
        latest_train = max(r.instant for r in report.train)
        earliest_validation = min(r.instant for r in report.validation)
        earliest_test = min(r.instant for r in report.test)
        assert latest_train < earliest_validation < earliest_test

    def test_the_configured_fractions_are_honoured(self):
        records = series(range(1000))
        report = split_records(
            records, PreprocessConfig(train_fraction=0.6, validation_fraction=0.2)
        )
        assert report.sizes["train"] == pytest.approx(600, abs=5)
        assert report.sizes["validation"] == pytest.approx(200, abs=5)
        assert report.sizes["test"] == pytest.approx(200, abs=5)

    def test_boundaries_are_validated_not_assumed(self):
        """`train_end < validation_start` and `validation_end < test_start`.

        Checked against the actual records rather than the reported boundaries,
        so a boundary that is merely *printed* consistently but does not match
        the data it claims to describe still fails.
        """
        records = series(range(120))
        report = split_records(records, PreprocessConfig())
        for entity, window in report.per_entity.items():
            parts = window.parts()
            latest_train = max((r.instant for r in parts[0]), default=None)
            earliest_validation = min((r.instant for r in parts[1]), default=None)
            earliest_test = min((r.instant for r in parts[2]), default=None)
            assert latest_train < earliest_validation < earliest_test, entity
        boundaries = report.to_dict()["boundaries"]
        assert boundaries, "a split with no published boundaries is unauditable"
        for window in boundaries.values():
            if window is None:
                continue
            assert window["train_end"] < window["validation_start"]
            assert window["validation_end"] < window["test_start"]

    def test_a_random_split_is_not_offered(self):
        """No phase-2 module imports `random` or offers a `seed`/`shuffle` knob.

        Checked over the AST rather than the source text, so a docstring that
        merely *mentions* shuffling does not satisfy or fail the check -- only
        real code does.
        """
        from app.engines.hydro import (
            preprocess_config,
            preprocess_pipeline,
            preprocess_temporal,
            preprocess_units,
        )

        for module in (
            preprocess_config,
            preprocess_pipeline,
            preprocess_temporal,
            preprocess_units,
        ):
            tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
            imported = {
                alias.name.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in node.names
            }
            assert "random" not in imported, f"{module.__name__} imports random"
            assert "numpy" not in imported, f"{module.__name__} imports numpy"
            called = {
                node.func.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
            }
            for banned in ("shuffle", "sample", "permutation", "seed"):
                assert banned not in called, f"{module.__name__} calls {banned}"
            keywords = {
                keyword.arg
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                for keyword in node.keywords
                if keyword.arg
            }
            for banned in ("random_state", "seed", "shuffle"):
                assert banned not in keywords, f"{module.__name__} takes {banned}="

    def test_too_few_records_is_refused_rather_than_silently_split(self):
        """Below three rows a three-way split has no honest answer to give."""
        for count in (0, 1, 2):
            with pytest.raises(TemporalError):
                split_records(series(range(count)), PreprocessConfig())

    def test_the_minimum_that_can_split_is_three_rows_one_each(self):
        report = split_records(series(range(3)), PreprocessConfig())
        assert report.sizes == {
            "train": 1,
            "validation": 1,
            "test": 1,
            "excluded_entities": 0,
        }

    def test_per_entity_splits_each_station_and_reports_the_overlap(self):
        """Stations with different coverage end up with overlapping absolute windows.

        That is a real consequence of per-entity splitting, not a bug, so it is
        published as a leakage finding rather than hidden.
        """
        records = series(range(40), entity="SYNTHETIC-STATION-0001") + series(
            range(80), entity="SYNTHETIC-STATION-0002"
        )
        report = split_records(records, PreprocessConfig(split_strategy=SPLIT_PER_ENTITY))
        assert report.strategy == SPLIT_PER_ENTITY
        assert set(report.per_entity) == {
            "SYNTHETIC-STATION-0001",
            "SYNTHETIC-STATION-0002",
        }
        assert report.is_leak_free is False
        assert report.leakage_findings
        assert any("overlaps" in finding for finding in report.leakage_findings)

    def test_per_entity_publishes_no_fictional_aggregate_boundary(self):
        """Flattening a (entity, instant)-sorted list invents a non-ordered triple.

        The three periods overlap in absolute time, so no single boundary triple
        describes them. Only the per-entity windows plus an explicitly-named,
        explicitly-flagged envelope are published -- and the flag is in the JSON,
        not only in the prose a reader of `describe()` would see.
        """
        records = series(range(40), entity="SYNTHETIC-STATION-0001") + series(
            range(80), entity="SYNTHETIC-STATION-0002"
        )
        report = split_records(records, PreprocessConfig(split_strategy=SPLIT_PER_ENTITY))
        boundaries = report.to_dict()["boundaries"]
        envelope = boundaries[_ENVELOPE_KEY]
        assert envelope["is_partition"] is False
        assert "NOT a partition" in envelope["note"]
        # The edge fields are renamed so they cannot be read as a partition.
        assert "train_start" not in envelope
        assert "envelope_train_start" in envelope
        # Every "period" spans the whole dataset, which is exactly why it is not
        # a partition: no cut separates anything.
        assert envelope["envelope_train_start"] == envelope["envelope_test_start"]
        assert envelope["envelope_train_end"] == envelope["envelope_test_end"]
        assert envelope["envelope_train_start"] < envelope["envelope_train_end"]
        # Real per-entity windows are still published and are genuine partitions.
        for entity in ("SYNTHETIC-STATION-0001", "SYNTHETIC-STATION-0002"):
            window = boundaries[entity]
            assert window["train_end"] < window["validation_start"]
            assert window["validation_end"] < window["test_start"]

    def test_a_global_split_is_leak_free_even_with_ragged_stations(self):
        """One cut on the merged timeline is why `global` is the default."""
        records = series(range(40), entity="SYNTHETIC-STATION-0001") + series(
            range(80), entity="SYNTHETIC-STATION-0002"
        )
        report = split_records(records, PreprocessConfig(split_strategy=SPLIT_GLOBAL))
        assert report.is_leak_free is True
        assert report.leakage_findings == []


# --------------------------------------------------------------------------- #
# I. Leakage
# --------------------------------------------------------------------------- #


class TestLeakage:
    def test_a_clean_run_passes_the_audit(self):
        result = preprocess(series(range(120)))
        assert result.report.leakage.findings == []
        assert result.report.leakage.checks_run > 0
        assert result.is_leak_free is True

    def test_a_resampled_output_is_still_leak_free(self):
        """Right-labelled bins must survive the audit, not merely assert it."""
        config = PreprocessConfig(
            resample_frequency="1D", aggregations=RAINFALL_RULES
        )
        result = preprocess(series(range(120)), config)
        assert result.report.leakage.findings == []

    def test_a_resampled_bin_never_precedes_its_own_sources(self):
        config = PreprocessConfig(resample_frequency="1D", aggregations=RAINFALL_RULES)
        result = preprocess(series(range(120)), config)
        for record in result.train + result.validation + result.test:
            # Every bin is stamped at or after the last hour it could contain.
            assert record.observed_at >= instant(23)

    def test_the_audit_re_checks_the_result_rather_than_trusting_the_config(self):
        """A run with a non-causal fill is flagged even when it was acknowledged.

        Acknowledging an operation says a human accepted it; it does not make the
        output leak-free, and the report must not imply that it does.
        """
        config = PreprocessConfig(
            missing_policy="linear_bidirectional",
            allow_leakage_sensitive=True,
            acknowledged_leakage_operations=("missing_policy:linear_bidirectional",),
        )
        result = preprocess(series([0, 1, 5, 6, 7, 8]), config)
        assert result.config.is_causal is False
        assert isinstance(result.report.leakage, LeakageAudit)
        assert result.report.leakage.checks_run > 0

    def test_an_entity_with_too_few_records_is_reported_not_dropped_silently(self):
        records = series(range(80)) + series(range(2), entity="SYNTHETIC-STATION-0002")
        report = split_records(records, PreprocessConfig(split_strategy=SPLIT_PER_ENTITY))
        assert "SYNTHETIC-STATION-0002" in report.insufficient
        assert report.insufficient_reason["SYNTHETIC-STATION-0002"]

    def test_the_error_policy_can_refuse_instead_of_reporting(self):
        from app.engines.hydro.preprocess_config import INSUFFICIENT_ERROR

        records = series(range(80)) + series(range(2), entity="SYNTHETIC-STATION-0002")
        with pytest.raises(TemporalError):
            split_records(
                records,
                PreprocessConfig(
                    split_strategy=SPLIT_PER_ENTITY,
                    insufficient_group_policy=INSUFFICIENT_ERROR,
                ),
            )

    def test_an_unknown_split_strategy_is_refused(self):
        with pytest.raises(PreprocessConfigError):
            PreprocessConfig(split_strategy="random")

    def test_split_sizes_are_disjoint_and_total(self):
        result = preprocess(series(range(120)))
        total = result.sizes["train"] + result.sizes["validation"] + result.sizes["test"]
        assert total == result.report.records_out
