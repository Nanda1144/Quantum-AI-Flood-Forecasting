# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 2 tests: timestamps, ordering and unit normalisation.

Covers the first three groups of the Phase 2 test matrix:

* **A. Timestamps** -- normalisation, timezone policy, refusal to guess.
* **B. Ordering** -- determinism, total order, entity/series identity.
* **C. Units** -- exact conversion only, no guessing, provenance preserved.

All inputs are SYNTHETIC/DEMO data. Nothing here measures hydrological skill,
and no station identifier, threshold or rating curve is asserted as real.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from app.engines.hydro.domains import Measurement, Observation, SchemaError
from app.engines.hydro.preprocess_config import (
    TIMEZONE_ASSUME_UTC,
    TIMEZONE_REQUIRE_EXPLICIT,
    TIMEZONE_SOURCE_DECLARED,
    PreprocessConfig,
    PreprocessConfigError,
)
from app.engines.hydro.preprocess_pipeline import preprocess
from app.engines.hydro.preprocess_temporal import (
    TemporalError,
    TimestampNormalizationReport,
    canonical_record,
    entity_key,
    normalize_timestamp,
    parse_frequency,
    series_key,
    sort_records,
)
from app.engines.hydro.preprocess_units import (
    UNIT_PRESERVE_UNDETERMINED,
    UNIT_REQUIRE_KNOWN,
    UnitError,
    convert_value,
    dimension_of,
    is_convertible,
    normalize_unit,
)

BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def instant(hours: float = 0) -> str:
    """A canonical UTC ISO-8601 instant `hours` after 2024-01-01T00:00:00Z."""
    return (BASE + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def observation(
    hours: float = 0,
    *,
    value: float = 1.0,
    unit: str = "mm",
    quantity: str = "rainfall",
    domain: str | None = None,
    entity: str = "SYNTHETIC-STATION-0001",
    source: str | None = "synthetic://demo/source",
    timestamp: str | None = None,
) -> Observation:
    return Observation(
        domain=domain or quantity,
        location_reference=entity,
        observed_at=timestamp or instant(hours),
        source_reference=source,
        measurements=(Measurement(quantity=quantity, value=value, unit=unit),),
        dataset_type="synthetic",
    )


# --------------------------------------------------------------------------- #
# A. Timestamps
# --------------------------------------------------------------------------- #


class TestTimestampPolicies:
    def test_explicit_offset_is_converted_to_utc(self):
        result = normalize_timestamp("2024-01-01T05:30:00+05:30", PreprocessConfig())
        assert result.normalized == "2024-01-01T00:00:00Z"
        assert result.timezone_source == "explicit"
        assert result.assumed is False

    def test_naive_timestamp_is_refused_by_default(self):
        with pytest.raises(TemporalError) as caught:
            normalize_timestamp("2024-01-01 00:00:00", PreprocessConfig())
        assert "no UTC offset" in str(caught.value)

    def test_declared_source_zone_is_applied_not_guessed(self):
        config = PreprocessConfig(
            timezone_policy=TIMEZONE_SOURCE_DECLARED, source_timezone="+05:30"
        )
        result = normalize_timestamp("2024-01-01 00:00:00", config)
        assert result.normalized == "2023-12-31T18:30:00Z"
        assert result.timezone_source == "declared:+05:30"

    def test_assume_utc_is_flagged_as_assumed(self):
        config = PreprocessConfig(timezone_policy=TIMEZONE_ASSUME_UTC)
        result = normalize_timestamp("2024-01-01 00:00:00", config)
        assert result.normalized == "2024-01-01T00:00:00Z"
        assert result.assumed is True
        assert result.timezone_source != "explicit"

    def test_source_declared_requires_a_source_timezone(self):
        with pytest.raises(PreprocessConfigError):
            PreprocessConfig(timezone_policy=TIMEZONE_SOURCE_DECLARED)

    @pytest.mark.parametrize(
        "offset",
        ["Asia/Kolkata", "+5:30", "abc", "+99:00", ""],
    )
    def test_unusable_source_zone_is_refused(self, offset):
        with pytest.raises((PreprocessConfigError, TemporalError)):
            normalize_timestamp(
                "2024-01-01 00:00:00",
                PreprocessConfig(
                    timezone_policy=TIMEZONE_SOURCE_DECLARED, source_timezone=offset
                ),
            )

    @pytest.mark.parametrize(
        ("offset", "expected"),
        [
            ("+05:30", "2023-12-31T18:30:00Z"),
            ("-08:00", "2024-01-01T08:00:00Z"),
            ("+00:00", "2024-01-01T00:00:00Z"),
            ("+0530", "2023-12-31T18:30:00Z"),
            ("+05", "2023-12-31T19:00:00Z"),
            ("-0330", "2024-01-01T03:30:00Z"),
        ],
    )
    def test_offset_parsing_is_length_correct(self, offset, expected):
        """A 2-, 4- or 6-digit offset decodes by length, not by one fixed formula.

        Reading `+05:30` as five *minutes* thirty seconds shifts a whole series
        by five and a half hours while leaving every downstream boundary
        self-consistent, which is why this is pinned per length.
        """
        result = normalize_timestamp(
            "2024-01-01 00:00:00",
            PreprocessConfig(
                timezone_policy=TIMEZONE_SOURCE_DECLARED, source_timezone=offset
            ),
        )
        assert result.normalized == expected

    def test_observation_itself_refuses_a_naive_timestamp(self):
        """Phase 1 enforces this upstream, so Phase 2's tz policy is the second line."""
        with pytest.raises(SchemaError):
            observation(timestamp="2024-01-01 00:00:00")

    def test_canonical_record_rewrites_offset_and_keeps_the_original(self):
        record = Observation(
            domain="rainfall",
            location_reference="SYNTHETIC-STATION-0001",
            observed_at="2024-01-01T05:30:00+05:30",
            source_reference="synthetic://demo/source",
            measurements=(Measurement(quantity="rainfall", value=1.0, unit="mm"),),
            dataset_type="synthetic",
        )
        rewritten = canonical_record(record)
        assert rewritten.observed_at == "2024-01-01T00:00:00Z"
        assert "2024-01-01T05:30:00+05:30" in rewritten.notes
        assert "timestamp normalisation" in rewritten.notes

    def test_canonical_record_is_a_no_op_when_already_canonical(self):
        record = observation()
        assert canonical_record(record) is record

    def test_two_spellings_of_one_instant_are_ordered_identically(self):
        """Phase 1 stores the source's own offset, so string comparison is unsound.

        `05:30+05:30` and `00:00Z` are the same instant. Sorting the raw strings
        would place them apart and split a station's series at a boundary that
        does not exist.
        """
        early = Observation(
            domain="rainfall",
            location_reference="SYNTHETIC-STATION-0001",
            observed_at="2024-01-01T00:00:00Z",
            source_reference="synthetic://demo/source",
            measurements=(Measurement(quantity="rainfall", value=1.0, unit="mm"),),
            dataset_type="synthetic",
        )
        late = Observation(
            domain="rainfall",
            location_reference="SYNTHETIC-STATION-0001",
            observed_at="2024-01-01T05:30:00+05:30",
            source_reference="synthetic://demo/source",
            measurements=(Measurement(quantity="rainfall", value=2.0, unit="mm"),),
            dataset_type="synthetic",
        )
        assert early.instant == late.instant
        # The total order places them by instant, so both land on the same
        # boundary, and the tiebreak -- not the string -- decides between them.
        forward, _ = sort_records([early, late])
        backward, _ = sort_records([late, early])
        assert [record.instant for record in forward] == [
            record.instant for record in backward
        ]
        assert [record.observed_at for record in forward] == [
            record.observed_at for record in backward
        ]


class TestFrequencyParsing:
    @pytest.mark.parametrize(
        ("text", "seconds"),
        [
            ("1h", 3600.0),
            ("1H", 3600.0),
            ("30min", 1800.0),
            ("1D", 86400.0),
            ("1w", 604800.0),
            ("90s", 90.0),
            ("1day", 86400.0),
            ("2 hours", 7200.0),
            ("15M", 900.0),
        ],
    )
    def test_accepted_spellings(self, text, seconds):
        assert parse_frequency(text).seconds == seconds

    @pytest.mark.parametrize(
        "text", ["1month", "h", "1", "0h", "-1h", "", "1x", "1 y"]
    )
    def test_refused_spellings(self, text):
        with pytest.raises(TemporalError):
            parse_frequency(text)

    def test_a_calendar_frequency_is_refused_with_a_reason(self):
        with pytest.raises(TemporalError) as caught:
            parse_frequency("1month")
        assert "no fixed length" in str(caught.value)


# --------------------------------------------------------------------------- #
# B. Ordering and identity
# --------------------------------------------------------------------------- #


class TestOrdering:
    def test_records_are_grouped_by_entity_then_ordered_by_instant(self):
        records = [
            observation(0, entity="SYNTHETIC-STATION-0002"),
            observation(1, entity="SYNTHETIC-STATION-0001"),
            observation(0, entity="SYNTHETIC-STATION-0001"),
        ]
        ordered, summary = sort_records(records)
        assert [(entity_key(r), r.observed_at) for r in ordered] == [
            ("SYNTHETIC-STATION-0001", instant(0)),
            ("SYNTHETIC-STATION-0001", instant(1)),
            ("SYNTHETIC-STATION-0002", instant(0)),
        ]
        assert summary["entities"] == 2

    def test_ordering_is_independent_of_input_order(self):
        records = [observation(hour, entity="B") for hour in range(5)]
        records += [observation(hour, entity="A") for hour in range(5)]
        shuffled = records[:]
        random.Random(17).shuffle(shuffled)
        first, _ = sort_records(records)
        second, _ = sort_records(shuffled)
        assert [r.observed_at + entity_key(r) for r in first] == [
            r.observed_at + entity_key(r) for r in second
        ]

    def test_records_sharing_an_instant_and_source_still_order_totally(self):
        """A stable sort alone would leave these in whatever order they arrived.

        Two readings of one instant from one source compare equal on
        (instant, domain, source, provenance), so keying only on those would make
        the output depend on the caller's row order. The tiebreak continues
        through `observed_at` and the measurements.
        """
        first = observation(0, value=1.0)
        second = observation(0, value=2.0)
        forward, _ = sort_records([first, second])
        backward, _ = sort_records([second, first])
        assert [r.measurements[0].value for r in forward] == [
            r.measurements[0].value for r in backward
        ]

    def test_ordering_summary_is_identical_for_shuffled_input(self):
        records = [observation(hour) for hour in range(8)]
        shuffled = records[:]
        random.Random(3).shuffle(shuffled)
        assert sort_records(records)[1] == sort_records(shuffled)[1]

    def test_series_key_separates_domains_at_one_station(self):
        """Phase 1 makes domain and quantity 1:1, so a station is several series.

        Grouping by station alone gives consecutive deltas of `0s, 3600s, 0s`,
        which admits no sampling interval and no grid -- and the missing-value
        stage then silently does nothing.
        """
        rainfall = observation(0, quantity="rainfall")
        water_level = observation(0, quantity="water_level", unit="m")
        inflow = observation(0, quantity="inflow", unit="m3/s")
        assert entity_key(rainfall) == entity_key(water_level) == entity_key(inflow)
        series = {series_key(record) for record in (rainfall, water_level, inflow)}
        assert series == {
            "SYNTHETIC-STATION-0001|rainfall",
            "SYNTHETIC-STATION-0001|water_level",
            "SYNTHETIC-STATION-0001|inflow",
        }


# --------------------------------------------------------------------------- #
# C. Units
# --------------------------------------------------------------------------- #


class TestNormalizationAccounting:
    """The counters a reader checks first have to mean what the labels say."""

    def test_rewritten_and_already_canonical_partition_the_considered_records(self):
        """`considered == rewritten + already_canonical`, for both outcomes.

        A reader comparing these three numbers is checking whether the stage did
        anything. If `rewritten` counted every record it saw, the ratio would
        always be 1.0 and would say nothing at all.
        """
        canonical = preprocess([observation(hour) for hour in range(12)])
        offset = preprocess(
            [
                Observation(
                    domain="rainfall",
                    location_reference="SYNTHETIC-STATION-0001",
                    observed_at=(BASE + timedelta(hours=hour))
                    .replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
                    .isoformat(),
                    source_reference="synthetic://demo/source",
                    measurements=(Measurement(quantity="rainfall", value=1.0, unit="mm"),),
                    dataset_type="synthetic",
                )
                for hour in range(12)
            ]
        )
        for report in (canonical.report.timestamps, offset.report.timestamps):
            assert report.normalized + report.already_canonical == report.considered

    def test_a_batch_already_in_utc_reports_nothing_rewritten(self):
        report = preprocess([observation(hour) for hour in range(12)]).report.timestamps
        assert report.considered == 12
        assert report.normalized == 0
        assert report.already_canonical == 12
        assert report.examples == []

    def test_a_batch_in_another_fixed_offset_is_rewritten_and_shown(self):
        records = [
            Observation(
                domain="rainfall",
                location_reference="SYNTHETIC-STATION-0001",
                observed_at=(BASE + timedelta(hours=hour, minutes=30))
                .replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
                .isoformat(),
                source_reference="synthetic://demo/source",
                measurements=(Measurement(quantity="rainfall", value=1.0, unit="mm"),),
                dataset_type="synthetic",
            )
            for hour in range(12)
        ]
        report = preprocess(records).report.timestamps
        assert report.normalized == 12
        assert report.already_canonical == 0
        assert len(report.examples) == TimestampNormalizationReport.EXAMPLE_LIMIT
        for item in report.examples:
            assert item["original_timestamp"].endswith("+05:30")
            assert item["normalized_timestamp"].endswith("Z")
            assert item["timezone_source"] == "explicit"

    def test_examples_are_ordered_by_content_not_by_input_order(self):
        """Two runs over the same data in opposite orders report the same five.

        A report an auditor diffs across runs has to be a function of the data.
        The limit is still applied while streaming, so this orders the sample
        rather than choosing a different one.
        """
        records = [
            Observation(
                domain="rainfall",
                location_reference="SYNTHETIC-STATION-0001",
                observed_at=(BASE + timedelta(hours=hour, minutes=30))
                .replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
                .isoformat(),
                source_reference="synthetic://demo/source",
                measurements=(Measurement(quantity="rainfall", value=1.0, unit="mm"),),
                dataset_type="synthetic",
            )
            for hour in range(12)
        ]
        shuffled = records[:]
        random.Random(5).shuffle(shuffled)
        first = preprocess(records).report.timestamps.to_dict()
        second = preprocess(shuffled).report.timestamps.to_dict()
        assert first == second


class TestUnitConversion:
    @pytest.mark.parametrize(
        ("value", "unit", "target", "expected", "expected_offset"),
        [
            # Pure scale factors: a zero offset.
            (1.0, "in", "mm", 25.4, 0.0),
            (1.0, "mm", "in", pytest.approx(1 / 25.4), 0.0),
            (100.0, "cusecs", "m3/s", pytest.approx(100.0), 0.0),
            # Affine conversions: a non-zero offset, because 32 degrees Fahrenheit
            # is the same point as 0 Celsius, not a scaled version of it.
            (212.0, "degF", "degC", pytest.approx(100.0), pytest.approx(-17.77777777777778)),
            (0.0, "degC", "degF", pytest.approx(32.0), pytest.approx(32.0)),
        ],
    )
    def test_exact_documented_conversions(self, value, unit, target, expected, expected_offset):
        converted, factor, offset = convert_value(value, unit, target)
        assert converted == pytest.approx(expected, rel=1e-9, abs=1e-12)
        assert factor != 0.0
        assert offset == pytest.approx(expected_offset, rel=1e-9, abs=1e-12)

    def test_conversion_results_are_not_rounded(self):
        """Documented rather than fixed.

        1 mm/h in m/s is 2.777...e-07 and no decimal length makes it exact.
        Rounding would put a small, invisible bias into every derived series, so
        the factor is kept at full precision and callers compare with a
        tolerance.
        """
        converted, _, _ = convert_value(1.0, "mm/h", "m/s")
        assert converted == pytest.approx(2.7777777777777777e-07, rel=1e-15)

    @pytest.mark.parametrize(
        ("unit", "target"),
        [
            ("mm/h", "mm"),  # a rate is not an amount; needs a window, i.e. aggregation
            ("m3/s", "mm"),  # different physical dimensions entirely
            ("m", "degC"),
        ],
    )
    def test_unsupported_conversions_raise_rather_than_guess(self, unit, target):
        with pytest.raises(UnitError):
            convert_value(1.0, unit, target)

    @pytest.mark.parametrize("unit", ["C", "F"])
    def test_bare_temperature_symbols_are_refused_as_ambiguous(self, unit):
        """`C` could be Celsius or coulomb; guessing either would be fabrication."""
        with pytest.raises(UnitError) as caught:
            convert_value(1.0, unit, "degC")
        assert "ambiguous" in str(caught.value).lower()

    def test_unknown_unit_reports_undetermined_and_keeps_the_value(self):
        result = normalize_unit(1.0, "furlongs", target_unit="mm", quantity="rainfall")
        assert result.value == 1.0
        assert "UNDETERMINED" in result.normalized_unit
        assert result.converted is False

    def test_no_target_means_no_conversion(self):
        """A target must be declared; choosing one would be a domain decision."""
        result = normalize_unit(1.0, "in", target_unit=None, quantity="rainfall")
        assert result.normalized_unit == "in"
        assert result.converted is False

    def test_conversion_preserves_the_original_unit(self):
        result = normalize_unit(1.0, "in", target_unit="mm", quantity="rainfall")
        assert result.original_unit == "in"
        assert result.normalized_unit == "mm"
        assert result.original_value == 1.0
        assert result.value == pytest.approx(25.4)
        assert result.converted is True
        assert result.factor == pytest.approx(25.4)

    def test_dimensions_are_queryable(self):
        """`mm` and `m` are both lengths; the module is right and a reader may not be."""
        assert dimension_of("mm") == dimension_of("m") == dimension_of("in")
        assert dimension_of("mm") != dimension_of("m3/s")
        assert dimension_of("furlongs") is None

    def test_convertibility_is_queryable_for_one_unit(self):
        assert is_convertible("mm") is True
        assert is_convertible("mm/h") is True
        assert is_convertible("furlongs") is False
        assert is_convertible("C") is False  # ambiguous, not merely unknown

    def test_unit_lookup_is_case_insensitive_but_displayed_as_declared(self):
        lower = normalize_unit(1.0, "mm", target_unit="in", quantity="rainfall")
        upper = normalize_unit(1.0, "MM", target_unit="IN", quantity="rainfall")
        assert lower.value == pytest.approx(upper.value)
        assert upper.original_unit == "MM"
        assert upper.normalized_unit == "IN"

    def test_water_level_conversion_carries_a_datum_warning(self):
        """Metres to feet moves a level relative to a datum that did not travel with it."""
        result = normalize_unit(1.0, "m", target_unit="ft", quantity="water_level")
        assert result.converted is True
        assert "datum" in result.note.lower()

    def test_datum_warning_is_scoped_to_water_level(self):
        """Rainfall has no datum, so the caveat must not fire on it."""
        result = normalize_unit(1.0, "in", target_unit="mm", quantity="rainfall")
        assert "datum" not in result.note.lower()

    def test_require_known_policy_refuses_an_unknown_unit(self):
        with pytest.raises(UnitError) as caught:
            normalize_unit(
                1.0,
                "furlongs",
                target_unit="mm",
                quantity="rainfall",
                policy=UNIT_REQUIRE_KNOWN,
            )
        assert "require_known" in str(caught.value)

    def test_preserve_undetermined_is_the_default_policy(self):
        """The committed sample's `inflow` column is deliberately unit-less."""
        result = normalize_unit(84.224, "UNDETERMINED (DEMO - no unit assigned)")
        assert result.value == 84.224
        assert "UNDETERMINED" in result.normalized_unit
        assert result.converted is False

    def test_non_finite_values_are_refused(self):
        for bad in (float("nan"), float("inf")):
            with pytest.raises(UnitError):
                normalize_unit(bad, "mm")

    def test_a_non_numeric_value_is_refused(self):
        with pytest.raises(UnitError):
            normalize_unit("lots", "mm")