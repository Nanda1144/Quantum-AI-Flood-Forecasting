# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 2 tests: the end-to-end pipeline, its report and its guarantees.

Covers the closing groups of the Phase 2 test matrix:

* **J. End to end** -- every stage together, on the committed sample and on
  hand-built fixtures.
* **K. Guarantees** -- determinism, machine-readability, row reconciliation,
  synthetic-data safety, configuration coherence.

All inputs are SYNTHETIC/DEMO data. Nothing here measures hydrological skill.
"""

from __future__ import annotations

import csv
import json
import pathlib
import random
from datetime import datetime, timedelta, timezone

import pytest

from app.engines.hydro.datasets import synthetic_sample_descriptor
from app.engines.hydro.domains import Measurement, Observation
from app.engines.hydro.preprocess_config import (
    CONFLICT_KEEP_FIRST,
    DUPLICATE_KEEP_FIRST,
    MISSING_FORWARD_FILL,
    SPLIT_PER_ENTITY,
    AggregationRule,
    PreprocessConfig,
    PreprocessConfigError,
    conservative_config,
    strict_config,
)
from app.engines.hydro.preprocess_pipeline import (
    ALL_CODES,
    CODE_ORDERED,
    CODE_PREFIX,
    CODE_RESAMPLED,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    PreprocessError,
    preprocess,
)
from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER

BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)

#: The committed sample carries no station column, so the entity reference comes
#: from configuration. It is a demo label, not a real gauge identifier, and no
#: test in this repository treats it as one.
DEMO_ENTITY = "SYNTHETIC-STATION-0001"

SAMPLE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "app"
    / "engines"
    / "hydro"
    / "data"
    / "synthetic_hydrology_sample.csv"
)

#: The three columns of the committed sample, as (quantity, domain, column, unit).
SAMPLE_COLUMNS = (
    ("water_level", "water_level", "water_level", "m"),
    ("inflow", "inflow", "inflow", "UNDETERMINED (DEMO - no unit assigned)"),
    ("rainfall", "rainfall", "rainfall_mm", "mm"),
)


def instant(hours: float = 0) -> str:
    return (BASE + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def observation(
    hours: float = 0,
    *,
    value: float = 1.0,
    unit: str = "mm",
    quantity: str = "rainfall",
    entity: str = DEMO_ENTITY,
) -> Observation:
    return Observation(
        domain=quantity,
        location_reference=entity,
        observed_at=instant(hours),
        source_reference="synthetic://demo/source",
        measurements=(Measurement(quantity=quantity, value=value, unit=unit),),
        dataset_type="synthetic",
    )


def series(hours, **kwargs) -> list[Observation]:
    return [observation(hour, **kwargs) for hour in hours]


def sample_records() -> list[Observation]:
    """The committed CSV as records, one per domain per row.

    Phase 1 enforces a 1:1 domain/quantity mapping, so a row carrying three
    quantities becomes three `Observation`s rather than one wide record.
    """
    descriptor = synthetic_sample_descriptor()
    records: list[Observation] = []
    with SAMPLE_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            # The file stores `2023-01-01 00:00:00`; the records need an explicit
            # UTC offset, which Phase 1 refuses to infer.
            stamp = row["timestamp"].replace(" ", "T") + "Z"
            for quantity, domain, column, unit in SAMPLE_COLUMNS:
                records.append(
                    Observation(
                        domain=domain,
                        location_reference=DEMO_ENTITY,
                        observed_at=stamp,
                        source_reference=descriptor.reference,
                        measurements=(
                            Measurement(
                                quantity=quantity,
                                value=float(row[column]),
                                unit=unit,
                            ),
                        ),
                        dataset_type="synthetic",
                    )
                )
    return records


# --------------------------------------------------------------------------- #
# J. End to end
# --------------------------------------------------------------------------- #


class TestEndToEnd:
    def test_the_committed_sample_runs_through_every_stage(self):
        records = sample_records()
        result = preprocess(records, dataset=synthetic_sample_descriptor())
        assert len(records) == 6480  # 2160 hourly rows x 3 quantities
        assert result.report.records_in == 6480
        assert result.report.records_out == 6480
        assert result.report.completed is True
        assert result.report.rows_reconciled is True
        assert result.report.leakage.findings == []
        assert result.is_leak_free is True

    def test_three_series_are_identified_at_one_station(self):
        """Phase 1 makes domain and quantity 1:1, so one station is three series."""
        result = preprocess(sample_records(), dataset=synthetic_sample_descriptor())
        assert set(result.report.intervals) == {
            f"{DEMO_ENTITY}|water_level",
            f"{DEMO_ENTITY}|inflow",
            f"{DEMO_ENTITY}|rainfall",
        }
        assert result.report.missing.series_processed == 3

    def test_the_samples_hourly_cadence_is_inferred_and_published(self):
        result = preprocess(sample_records(), dataset=synthetic_sample_descriptor())
        for detail in result.report.intervals.values():
            assert "1h" in detail
            assert "regularity 100%" in detail
            assert "inferred" in detail

    def test_an_undetermined_unit_is_carried_not_guessed(self):
        """The committed `inflow` column is deliberately unit-less."""
        result = preprocess(sample_records(), dataset=synthetic_sample_descriptor())
        assert result.report.units.undetermined == 2160
        assert "inflow" in result.report.units.undetermined_quantities
        assert any(
            note.code == "PREPROCESS_UNDETERMINED_UNIT" for note in result.report.notes
        )

    def test_phase_one_quality_findings_are_carried_not_duplicated(self):
        """Phase 1 remains the one validation framework; its output is embedded."""
        result = preprocess(sample_records(), dataset=synthetic_sample_descriptor())
        assert result.report.phase1_quality, "Phase 1 findings must be published"
        payload = json.dumps(result.report.phase1_quality)
        assert "unknown_unit" in payload

    def test_the_sample_has_no_gaps_to_report(self):
        result = preprocess(sample_records(), dataset=synthetic_sample_descriptor())
        assert result.report.missing.missing_before == 0
        assert result.report.missing.imputed == 0

    def test_a_split_covers_the_sample_chronologically(self):
        result = preprocess(sample_records(), dataset=synthetic_sample_descriptor())
        assert result.sizes["train"] == 4536
        assert result.sizes["validation"] == 972
        assert result.sizes["test"] == 972
        latest_train = max(r.instant for r in result.train)
        earliest_validation = min(r.instant for r in result.validation)
        earliest_test = min(r.instant for r in result.test)
        assert latest_train < earliest_validation < earliest_test

    def test_an_empty_batch_is_refused_rather_than_reported_clean(self):
        with pytest.raises(PreprocessError) as caught:
            preprocess([])
        assert "no records" in str(caught.value)

    def test_duplicates_units_resampling_and_fills_compose(self):
        records = series(range(72)) + [observation(3, value=3.0)]
        config = PreprocessConfig(
            duplicate_policy=DUPLICATE_KEEP_FIRST,
            conflict_policy=CONFLICT_KEEP_FIRST,
            conflict_policy_source="synthetic://demo/ticket",
            target_units={"rainfall": "mm"},
            resample_frequency="1D",
            aggregations=(AggregationRule(quantity="rainfall", function="sum", unit="mm"),),
            missing_policy=MISSING_FORWARD_FILL,
        )
        result = preprocess(records, config)
        assert result.report.records_in == 73
        assert result.report.records_discarded == 1
        assert result.report.resampling_delta == -69
        assert result.report.rows_reconciled is True
        assert result.report.completed is True

    def test_a_declared_target_unit_converts_and_records_the_original(self):
        records = [
            observation(hour, value=1.0, unit="in" if hour % 2 else "mm")
            for hour in range(60)
        ]
        result = preprocess(records, PreprocessConfig(target_units={"rainfall": "mm"}))
        assert result.report.units.converted == 30
        converted = next(
            r for r in result.train if r.observed_at == instant(1)
        )
        assert converted.measurements[0].value == pytest.approx(25.4)
        assert converted.measurements[0].unit == "mm"
        assert "in -> mm" in converted.notes
        untouched = next(r for r in result.train if r.observed_at == instant(0))
        assert untouched.measurements[0].value == 1.0
        assert untouched.notes == ""

    def test_per_entity_splitting_surfaces_its_own_leakage(self):
        records = series(range(40), entity="SYNTHETIC-STATION-0001") + series(
            range(80), entity="SYNTHETIC-STATION-0002"
        )
        result = preprocess(records, PreprocessConfig(split_strategy=SPLIT_PER_ENTITY))
        assert result.is_leak_free is False
        assert result.report.completed is False


# --------------------------------------------------------------------------- #
# K. Guarantees
# --------------------------------------------------------------------------- #


class TestReportContract:
    def test_the_report_is_json_serialisable(self):
        result = preprocess(sample_records()[:300], dataset=synthetic_sample_descriptor())
        payload = result.report.to_dict()
        text = json.dumps(payload, sort_keys=True)
        assert json.loads(text) == payload

    def test_the_described_report_names_every_stage(self):
        result = preprocess(series(range(120)))
        text = result.report.describe()
        for section in (
            "PREPROCESSING",
            "TIMESTAMPS",
            "UNITS",
            "DUPLICATES",
            "MISSING",
            "SPLIT",
            "LEAKAGE AUDIT",
            "DISCLAIMER",
        ):
            assert section in text, section

    def test_every_note_code_is_namespaced_and_stable(self):
        """A code outside `ALL_CODES` is a bug in phase 2, not untrusted data."""
        result = preprocess(sample_records()[:600], dataset=synthetic_sample_descriptor())
        codes = {note.code for note in result.report.notes}
        assert codes <= ALL_CODES, codes - ALL_CODES
        for code in ALL_CODES:
            assert code.startswith(CODE_PREFIX), code

    def test_severities_are_exposed_as_separate_lists(self):
        """Lower-case, matching the Phase 1 `quality` vocabulary phase 2 reuses."""
        result = preprocess(sample_records()[:600], dataset=synthetic_sample_descriptor())
        report = result.report
        assert report.notes, "a run with no findings would make this vacuous"
        assert all(n.severity == SEVERITY_WARNING for n in report.warnings)
        assert all(n.severity == SEVERITY_ERROR for n in report.errors)
        assert all(n.severity == SEVERITY_INFO for n in report.infos)
        assert not report.errors, [n.code for n in report.errors]
        assert report.warnings and report.infos
        assert sum(len(p) for p in (report.errors, report.warnings, report.infos)) == len(
            report.notes
        )

    def test_a_clean_run_still_reports_what_it_did(self):
        """Silence is not the same as clean: each stage says what it found."""
        result = preprocess(series(range(120)))
        codes = {note.code for note in result.report.notes}
        assert CODE_ORDERED in codes
        assert CODE_RESAMPLED in codes  # records that resampling was deliberately off

    def test_the_row_count_reconciles_for_every_gap_policy(self):
        from app.engines.hydro.preprocess_config import (
            MISSING_DROP,
            MISSING_LINEAR_CAUSAL,
            MISSING_RETAIN,
        )

        gapped = series([0, 1, 4, 5, 6, 7, 8, 9])
        for policy in (MISSING_RETAIN, MISSING_DROP, MISSING_FORWARD_FILL, MISSING_LINEAR_CAUSAL):
            result = preprocess(gapped, PreprocessConfig(missing_policy=policy))
            assert result.report.rows_reconciled is True, policy

    def test_resampling_is_not_reported_as_a_removal(self):
        """72 hourly rows into 3 daily bins discards no reading."""
        config = PreprocessConfig(
            resample_frequency="1D",
            aggregations=(AggregationRule(quantity="rainfall", function="sum", unit="mm"),),
        )
        result = preprocess(series(range(72)), config)
        assert result.report.records_in == 72
        assert result.report.records_out == 3
        assert result.report.records_discarded == 0
        assert result.report.resampling_delta == -69
        payload = result.report.to_dict()["counts"]
        assert payload["records_discarded"] == 0
        assert payload["rows_reconciled"] is True

    def test_the_report_is_a_pure_function_of_its_input(self):
        records = series(range(60)) + series(range(60), entity="SYNTHETIC-STATION-0002")
        first = preprocess(records).report.to_dict()
        shuffled = records[:]
        random.Random(29).shuffle(shuffled)
        second = preprocess(shuffled).report.to_dict()
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def test_the_output_records_are_a_pure_function_of_the_input(self):
        records = series(range(60)) + series(range(60), entity="SYNTHETIC-STATION-0002")
        first = preprocess(records)
        shuffled = records[:]
        random.Random(29).shuffle(shuffled)
        second = preprocess(shuffled)
        for attribute in ("train", "validation", "test"):
            left = getattr(first, attribute)
            right = getattr(second, attribute)
            assert [r.observed_at + r.location_reference for r in left] == [
                r.observed_at + r.location_reference for r in right
            ]
            assert [r.measurements for r in left] == [r.measurements for r in right]

    def test_a_series_survives_shuffling_unscathed(self):
        records = sample_records()
        first = preprocess(records)
        shuffled = records[:]
        random.Random(7).shuffle(shuffled)
        second = preprocess(shuffled)
        assert first.report.to_dict() == second.report.to_dict()


class TestSyntheticDataSafety:
    def test_the_synthetic_disclaimer_is_carried_verbatim(self):
        result = preprocess(series(range(60)), dataset=synthetic_sample_descriptor())
        assert SYNTHETIC_DATA_DISCLAIMER in result.report.disclaimer
        assert result.report.is_synthetic is True

    def test_the_disclaimer_appears_in_the_described_report(self):
        result = preprocess(series(range(60)), dataset=synthetic_sample_descriptor())
        assert SYNTHETIC_DATA_DISCLAIMER in result.report.describe()

    def test_records_keep_their_own_disclaimer(self):
        """The disclaimer rides on every record, not only on the report.

        `notes` is where phase 2 writes what it *did* to a record; the disclaimer
        is a separate field precisely so that appending a provenance note can
        never displace it.
        """
        record = series(range(1))[0]
        assert record.disclaimer == SYNTHETIC_DATA_DISCLAIMER
        assert SYNTHETIC_DATA_DISCLAIMER not in record.notes  # nor overwritten by it

    def test_the_disclaimer_survives_every_stage_that_rewrites_a_record(self):
        """Conversion, canonicalisation and deduplication all rebuild records."""
        records = [
            observation(hour, value=1.0, unit="in" if hour % 2 else "mm")
            for hour in range(60)
        ]
        config = PreprocessConfig(
            target_units={"rainfall": "mm"},
            duplicate_policy=DUPLICATE_KEEP_FIRST,
            conflict_policy=CONFLICT_KEEP_FIRST,
            conflict_policy_source="synthetic://demo/ticket",
            resample_frequency="6h",
            aggregations=(AggregationRule(quantity="rainfall", function="sum", unit="mm"),),
        )
        result = preprocess(records, config)
        for record in result.train + result.validation + result.test:
            assert record.disclaimer == SYNTHETIC_DATA_DISCLAIMER

    def test_an_unknown_dataset_is_treated_as_unverified_not_as_real(self):
        result = preprocess(series(range(60)))
        assert result.report.is_synthetic is False
        assert "UNVERIFIED" in result.report.disclaimer.upper()

    def test_no_station_identifier_is_invented(self):
        """The committed sample has no station column, so none is asserted."""
        descriptor = synthetic_sample_descriptor()
        assert descriptor.station_reference is None

    def test_phase_two_writes_no_hydrological_threshold(self):
        """A hard-coded flood threshold would be a fabricated domain fact."""
        import ast

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
            source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
            for token in ("flood_threshold", "danger_level", "FLOOD_", "alert_level"):
                assert token not in source, f"{module.__name__} mentions {token}"
            ast.parse(source)


class TestConfigCoherence:
    def test_the_default_config_is_conservative_and_causal(self):
        config = PreprocessConfig()
        assert config.missing_policy == "retain"
        assert config.conflict_policy == "error"
        assert config.duplicate_policy == "report"
        assert config.timezone_policy == "require_explicit"
        assert config.unit_policy == "preserve_undetermined"
        assert config.split_strategy == "global"
        assert config.resample_frequency is None
        assert config.imputes_missing is False
        assert config.is_causal is True

    def test_strict_mode_refuses_every_operation_that_changes_the_data(self):
        with pytest.raises(PreprocessConfigError):
            PreprocessConfig(strictness="strict", duplicate_policy=DUPLICATE_KEEP_FIRST)
        with pytest.raises(PreprocessConfigError):
            PreprocessConfig(strictness="strict", missing_policy=MISSING_FORWARD_FILL)
        with pytest.raises(PreprocessConfigError):
            PreprocessConfig(strictness="strict", unit_policy="preserve_undetermined")
        with pytest.raises(PreprocessConfigError):
            PreprocessConfig(strictness="strict", timezone_policy="assume_utc")

    def test_the_shipped_presets_are_self_consistent(self):
        for preset in (conservative_config(), strict_config()):
            assert preset.is_causal is True
            assert preset.imputes_missing is False
            json.dumps(preset.to_dict())  # machine-readable

    def test_a_config_is_machine_readable(self):
        payload = PreprocessConfig().to_dict()
        assert json.loads(json.dumps(payload)) == payload
        assert payload["is_causal"] is True
        assert payload["conflict_policy"] == "error"

    def test_train_and_validation_fractions_must_be_a_partition(self):
        with pytest.raises(PreprocessConfigError):
            PreprocessConfig(train_fraction=0.9, validation_fraction=0.9)

    def test_a_negative_fraction_is_refused(self):
        with pytest.raises(PreprocessConfigError):
            PreprocessConfig(train_fraction=-0.1)

    def test_phase_two_does_not_do_feature_engineering(self):
        """Phase 3 owns lags, rolling windows and accumulation; phase 2 must not."""
        import ast

        from app.engines.hydro import preprocess_pipeline, preprocess_temporal

        for module in (preprocess_pipeline, preprocess_temporal):
            tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
            names = {
                node.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Name)
            } | {
                node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
            }
            for banned in (
                "rolling_mean",
                "lag_",
                "cumulative_rainfall",
                "accumulate_rain",
                "build_features",
                "make_features",
                "FeatureBuilder",
            ):
                assert not any(banned in name for name in names), (
                    f"{module.__name__} references {banned}"
                )
