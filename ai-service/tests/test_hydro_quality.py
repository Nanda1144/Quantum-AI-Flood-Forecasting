# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Tests for `app.engines.hydro.quality` — Phase 1 structural validation.

**All payloads here are SYNTHETIC/DEMO test data**, deliberately so: they
include malformed, missing and conflicting records on purpose, because testing a
validator means feeding it bad input. No payload in this file describes a real
gauge, and none of the conflicting pairs below are real observations that
disagree.

What these tests protect
------------------------
1. A validator **reports**; it never repairs, fills, collapses or resolves.
2. Every problem in a payload is reported in one pass, not just the first.
3. A duplicate is reported and a conflict is an error — and neither is silently
   decided.
4. Provenance warnings travel with the report.
"""

from __future__ import annotations

import json
import sys

import pytest

from app.engines.hydro.domains import (
    DOMAIN_DISCHARGE,
    DOMAIN_FLOOD_EVENT,
    DOMAIN_INFLOW,
    DOMAIN_RAINFALL,
    DOMAIN_WATER_LEVEL,
    QUALITY_MISSING,
    QUALITY_OK,
    QUALITY_REJECTED,
    QUALITY_SUSPECT,
    QUALITY_UNKNOWN,
    ColumnBinding,
    FloodEvent,
    Measurement,
    Observation,
    RiskScoreRecord,
)
from app.engines.hydro.provenance import (
    DATASET_TYPE_REAL,
    DATASET_TYPE_SYNTHETIC,
    SYNTHETIC_DATA_DISCLAIMER,
)
from app.engines.hydro.quality import (
    CODE_ABSENT_COLUMN,
    CODE_CONFLICTING_VALUES,
    CODE_DOMAIN_QUANTITY_MISMATCH,
    CODE_DUPLICATE_RECORD,
    CODE_INVALID_TIMESTAMP,
    CODE_MISSING_DISCLAIMER,
    CODE_MISSING_LOCATION,
    CODE_MISSING_MEASUREMENT,
    CODE_MISSING_SOURCE,
    CODE_MISSING_TIMESTAMP,
    CODE_MISSING_UNIT,
    CODE_NEGATIVE_FLOW,
    CODE_NEGATIVE_RAINFALL,
    CODE_NON_FINITE_VALUE,
    CODE_NON_NUMERIC_VALUE,
    CODE_RATE_WITHOUT_WINDOW,
    CODE_UNKNOWN_DOMAIN,
    CODE_UNKNOWN_UNIT,
    CODE_UNMAPPED_COLUMN,
    NON_BLOCKING_CODES,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    IngestReport,
    QualityIssue,
    ValidationReport,
    check_flood_events,
    check_observation_collection,
    check_risk_records,
    ingest_observations,
    summarise,
    validate_observation,
    validate_observation_payload,
)

# SYNTHETIC/DEMO identifiers — not a station, not a reach, not a real event.
STATION = "SYNTHETIC-STATION-0001"
AREA = "SYNTHETIC-AREA-0001"
INSTANT = "2024-01-01T00:00:00Z"
SYNTHETIC_NOTE = "synthetic/demo fixture — not real hydrological observation data"


def _payload(**overrides):
    """A structurally valid SYNTHETIC observation payload to mutate per test."""
    payload = {
        "domain": DOMAIN_WATER_LEVEL,
        "location_reference": STATION,
        "observed_at": INSTANT,
        "measurements": [{"quantity": "water_level", "value": 2.5, "unit": "m"}],
        "source_reference": "synthetic://unit-test/generator",
        "dataset_type": DATASET_TYPE_SYNTHETIC,
        "disclaimer": SYNTHETIC_DATA_DISCLAIMER,
    }
    payload.update(overrides)
    return payload


def _observation(value: float = 2.5, *, instant: str = INSTANT, station: str = STATION) -> Observation:
    return Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference=station,
        observed_at=instant,
        measurements=(Measurement(quantity="water_level", value=value, unit="m"),),
        source_reference="synthetic://unit-test/generator",
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )


# --------------------------------------------------------------------------- #
# Report mechanics
# --------------------------------------------------------------------------- #


def test_a_clean_report_is_ok():
    report = validate_observation_payload(_payload())
    assert report.ok is True
    assert report.errors == ()
    assert report.quality_status == QUALITY_OK


def test_an_empty_report_is_unknown_not_ok():
    """Nothing was inspected, so nothing may be certified."""
    report = ValidationReport()
    assert report.quality_status == QUALITY_UNKNOWN
    assert report.ok is True  # no error, but also no assessment


def test_one_error_rejects_the_record():
    report = validate_observation_payload(_payload(location_reference=""))
    assert report.quality_status == QUALITY_REJECTED
    assert report.has_rejection is True


def test_a_warning_alone_leaves_the_record_usable_but_suspect():
    report = validate_observation_payload(_payload(source_reference=None))
    assert report.ok is True
    assert report.quality_status == QUALITY_SUSPECT
    assert report.has(CODE_MISSING_SOURCE)


def test_an_issue_needs_a_severity_from_the_vocabulary():
    with pytest.raises(ValueError, match="severity must be"):
        QualityIssue(code="x", message="y", severity="catastrophe")


# --------------------------------------------------------------------------- #
# Required fields
# --------------------------------------------------------------------------- #


def test_a_missing_timestamp_is_reported():
    payload = _payload()
    del payload["observed_at"]
    assert validate_observation_payload(payload).has(CODE_MISSING_TIMESTAMP)


def test_an_unparseable_timestamp_is_reported():
    report = validate_observation_payload(_payload(observed_at="whenever"))
    assert report.has(CODE_INVALID_TIMESTAMP)


def test_a_missing_location_is_an_error():
    report = validate_observation_payload(_payload(location_reference=None))
    assert report.has(CODE_MISSING_LOCATION)
    assert report.ok is False


def test_an_empty_measurement_set_is_a_gap_not_a_reading():
    report = validate_observation_payload(_payload(measurements=[]))
    assert report.has(CODE_MISSING_MEASUREMENT)
    assert report.ok is False


def test_a_measurement_with_no_unit_is_an_error():
    report = validate_observation_payload(
        _payload(measurements=[{"quantity": "water_level", "value": 2.5, "unit": "  "}])
    )
    assert report.has(CODE_MISSING_UNIT)


def test_a_null_measurement_value_is_an_error():
    report = validate_observation_payload(
        _payload(measurements=[{"quantity": "water_level", "value": None, "unit": "m"}])
    )
    assert report.has(CODE_MISSING_MEASUREMENT)


# --------------------------------------------------------------------------- #
# Numeric findings
# --------------------------------------------------------------------------- #


def test_a_non_numeric_value_is_reported_not_coerced():
    report = validate_observation_payload(
        _payload(measurements=[{"quantity": "water_level", "value": "n/a", "unit": "m"}])
    )
    assert report.has(CODE_NON_NUMERIC_VALUE)


def test_a_nan_value_is_reported():
    """Some exports write NaN, or the literal string "nan", as a missing sentinel."""
    for bad in (float("nan"), "nan", "inf"):
        report = validate_observation_payload(
            _payload(measurements=[{"quantity": "water_level", "value": bad, "unit": "m"}])
        )
        assert report.has(CODE_NON_FINITE_VALUE), bad


def test_a_negative_rainfall_is_an_error():
    """-999 is a missing-value sentinel, not a precipitation depth."""
    report = validate_observation_payload(
        _payload(
            domain=DOMAIN_RAINFALL,
            measurements=[{"quantity": "rainfall", "value": -999.0, "unit": "mm"}],
        )
    )
    assert report.has(CODE_NEGATIVE_RAINFALL)
    assert report.ok is False


def test_a_negative_inflow_is_an_error():
    report = validate_observation_payload(
        _payload(
            domain=DOMAIN_INFLOW,
            measurements=[{"quantity": "inflow", "value": -1.0, "unit": "m3/s"}],
        )
    )
    assert report.has(CODE_NEGATIVE_FLOW)


def test_a_negative_discharge_is_an_error():
    report = validate_observation_payload(
        _payload(
            domain=DOMAIN_DISCHARGE,
            measurements=[{"quantity": "discharge", "value": -0.5, "unit": "m3/s"}],
        )
    )
    assert report.has(CODE_NEGATIVE_FLOW)


def test_a_negative_water_level_is_not_judged():
    """Stage is relative to an unknown datum, so its sign carries no information
    this repository has. A range policy beyond that is Phase 2's business."""
    report = validate_observation_payload(
        _payload(measurements=[{"quantity": "water_level", "value": -1.2, "unit": "m"}])
    )
    assert report.ok is True


def test_a_quantity_mismatched_with_its_domain_is_an_error():
    report = validate_observation_payload(
        _payload(
            domain=DOMAIN_WATER_LEVEL,
            measurements=[{"quantity": "rainfall", "value": 1.0, "unit": "mm"}],
        )
    )
    assert report.has(CODE_DOMAIN_QUANTITY_MISMATCH)


def test_an_unknown_domain_is_an_error():
    assert validate_observation_payload(_payload(domain="groundwater")).has(CODE_UNKNOWN_DOMAIN)


def test_a_non_measurement_domain_is_rejected_as_an_observation():
    report = validate_observation_payload(_payload(domain=DOMAIN_FLOOD_EVENT))
    assert report.has(CODE_UNKNOWN_DOMAIN)


# --------------------------------------------------------------------------- #
# Units — advisory, never a rejection
# --------------------------------------------------------------------------- #


def test_an_unrecognised_unit_is_a_warning_not_an_error():
    report = validate_observation_payload(
        _payload(measurements=[{"quantity": "water_level", "value": 2.5, "unit": "bananas"}])
    )
    assert report.ok is True
    assert report.has(CODE_UNKNOWN_UNIT)
    issue = next(i for i in report.issues if i.code == CODE_UNKNOWN_UNIT)
    assert issue.severity == SEVERITY_WARNING


def test_a_rate_without_a_window_is_a_warning():
    """Accumulation needs a declared window. Phase 1 does not accumulate."""
    report = validate_observation_payload(
        _payload(
            domain=DOMAIN_RAINFALL,
            measurements=[{"quantity": "rainfall", "value": 1.0, "unit": "mm/h"}],
        )
    )
    assert report.has(CODE_RATE_WITHOUT_WINDOW)
    assert report.ok is True


def test_a_rate_with_a_window_produces_no_warning():
    report = validate_observation_payload(
        _payload(
            domain=DOMAIN_RAINFALL,
            measurements=[{"quantity": "rainfall", "value": 1.0, "unit": "mm/h"}],
            measurement_window="1h",
        )
    )
    assert not report.has(CODE_RATE_WITHOUT_WINDOW)


# --------------------------------------------------------------------------- #
# Provenance findings
# --------------------------------------------------------------------------- #


def test_non_real_data_without_a_disclaimer_is_an_error():
    report = validate_observation_payload(_payload(disclaimer=None))
    assert report.has(CODE_MISSING_DISCLAIMER)
    assert report.ok is False


def test_unknown_provenance_without_a_disclaimer_is_an_error():
    report = validate_observation_payload(_payload(dataset_type="unknown", disclaimer=None))
    assert report.has(CODE_MISSING_DISCLAIMER)


def test_real_data_needs_no_disclaimer():
    report = validate_observation_payload(
        _payload(dataset_type=DATASET_TYPE_REAL, disclaimer=None, location_reference="STATION-AS-SUPPLIED")
    )
    assert report.ok is True


def test_a_dataset_type_outside_the_vocabulary_is_an_error():
    report = validate_observation_payload(_payload(dataset_type="probably_real"))
    assert report.ok is False


def test_a_missing_source_reference_is_a_warning():
    report = validate_observation_payload(_payload(source_reference=None))
    assert report.has(CODE_MISSING_SOURCE)
    assert report.ok is True


# --------------------------------------------------------------------------- #
# One pass reports everything
# --------------------------------------------------------------------------- #


def test_every_problem_in_a_payload_is_reported_not_just_the_first():
    """A batch ingest must learn about all of its bad rows, not die on row one."""
    report = validate_observation_payload(
        {
            "domain": DOMAIN_WATER_LEVEL,
            "location_reference": "",
            "observed_at": "not-a-time",
            "measurements": [{"quantity": "water_level", "value": "n/a", "unit": ""}],
        }
    )
    codes = set(report.codes())
    assert {
        CODE_INVALID_TIMESTAMP,
        CODE_MISSING_LOCATION,
        CODE_NON_NUMERIC_VALUE,
        CODE_MISSING_UNIT,
    } <= codes


def test_a_payload_that_is_not_a_mapping_is_reported_not_raised():
    for bad in (None, [], "a string", 7):
        report = validate_observation_payload(bad)
        assert report.ok is False
        assert report.has(CODE_MISSING_MEASUREMENT)


# --------------------------------------------------------------------------- #
# Column bindings
# --------------------------------------------------------------------------- #


BINDINGS = [
    ColumnBinding(column="water_level", domain=DOMAIN_WATER_LEVEL, quantity="water_level", unit="m"),
    ColumnBinding(column="inflow", domain=DOMAIN_INFLOW, quantity="inflow", unit="m3/s"),
]


def test_a_bound_column_absent_from_the_payload_is_a_warning():
    report = validate_observation_payload(_payload(), bindings=BINDINGS)
    assert report.has(CODE_ABSENT_COLUMN)
    assert report.ok is True


def test_an_unmapped_column_is_a_warning():
    payload = _payload()
    payload["soil_moisture"] = 0.3
    report = validate_observation_payload(payload, bindings=BINDINGS)
    assert report.has(CODE_UNMAPPED_COLUMN)
    assert report.ok is True


def test_no_binding_findings_appear_without_bindings():
    report = validate_observation_payload(_payload())
    assert not report.has(CODE_ABSENT_COLUMN)
    assert not report.has(CODE_UNMAPPED_COLUMN)


# --------------------------------------------------------------------------- #
# Record validation
# --------------------------------------------------------------------------- #


def test_a_constructed_record_validates_clean():
    record = Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference=STATION,
        observed_at=INSTANT,
        measurements=(Measurement(quantity="water_level", value=2.5, unit="m"),),
        source_reference="synthetic://unit-test/generator",
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    report = validate_observation(record)
    assert report.ok is True
    assert report.issues == ()


def test_a_record_with_no_source_is_suspect_not_rejected():
    record = Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference=STATION,
        observed_at=INSTANT,
        measurements=(Measurement(quantity="water_level", value=2.5, unit="m"),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    report = validate_observation(record)
    assert report.ok is True
    assert report.quality_status == QUALITY_SUSPECT


def test_a_record_claiming_a_domain_absent_from_the_repository_is_flagged():
    """A `real` discharge record may arrive later, but this repository has never
    held one, and that is worth saying on the record itself."""
    record = Observation(
        domain=DOMAIN_DISCHARGE,
        location_reference="STATION-AS-SUPPLIED-BY-DATASET-OWNER",
        observed_at=INSTANT,
        measurements=(Measurement(quantity="discharge", value=12.0, unit="m3/s"),),
        source_reference="synthetic://unit-test/generator",
        dataset_type=DATASET_TYPE_REAL,
    )
    report = validate_observation(record)
    assert report.ok is True
    assert any(DOMAIN_DISCHARGE in issue.message for issue in report.issues)


# --------------------------------------------------------------------------- #
# Duplicates and conflicts
# --------------------------------------------------------------------------- #


def test_a_collection_with_unique_keys_is_clean():
    records = [
        _observation(2.5, instant="2024-01-01T00:00:00Z"),
        _observation(2.6, instant="2024-01-01T01:00:00Z"),
    ]
    report = check_observation_collection(records)
    assert report.ok is True
    assert report.checked == 2


def test_an_identical_duplicate_is_reported_and_not_collapsed():
    records = [_observation(2.5), _observation(2.5)]
    report = check_observation_collection(records)
    assert report.has_duplicates is True
    assert report.ok is False
    # Reported, not resolved: the dataset owner decides which row survives.
    assert len(records) == 2
    assert report.has(CODE_DUPLICATE_RECORD)


def test_two_different_values_at_one_instant_is_a_conflict():
    """A source disagreeing with itself. Either reading may be the wrong one."""
    records = [_observation(2.5), _observation(3.9)]
    report = check_observation_collection(records)
    assert report.has_conflicts is True
    assert report.has_conflicts and not report.has_duplicates
    assert report.has(CODE_CONFLICTING_VALUES)


def test_the_same_instant_at_different_stations_is_not_a_duplicate():
    records = [
        _observation(2.5, station="SYNTHETIC-STATION-0001"),
        _observation(2.5, station="SYNTHETIC-STATION-0002"),
    ]
    assert check_observation_collection(records).ok is True


def test_the_same_station_instant_in_two_domains_is_not_a_duplicate():
    level = _observation(2.5)
    discharge = Observation(
        domain=DOMAIN_DISCHARGE,
        location_reference=STATION,
        observed_at=INSTANT,
        measurements=(Measurement(quantity="discharge", value=12.0, unit="m3/s"),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert check_observation_collection([level, discharge]).ok is True


def test_a_conflict_report_serialises_for_the_quality_record():
    report = check_observation_collection([_observation(2.5), _observation(3.9)])
    payload = json.loads(json.dumps(report.to_dict()))
    assert payload["has_conflicts"] is True
    assert payload["conflicting_keys"]


def test_flood_event_duplicates_and_conflicts():
    event = FloodEvent(
        event_reference="SYNTHETIC-EVENT-0001",
        area_reference=AREA,
        started_at=INSTANT,
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    same = FloodEvent(
        event_reference="SYNTHETIC-EVENT-0001",
        area_reference=AREA,
        started_at=INSTANT,
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    different = FloodEvent(
        event_reference="SYNTHETIC-EVENT-0001",
        area_reference="SYNTHETIC-AREA-0002",
        started_at=INSTANT,
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert check_flood_events([event, same]).has_duplicates is True
    assert check_flood_events([event, different]).has_conflicts is True
    assert check_flood_events([event]).ok is True


def test_risk_records_keyed_by_area_and_instant():
    first = RiskScoreRecord(
        area_reference=AREA,
        risk_score=0.4,
        assessed_at=INSTANT,
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    same = RiskScoreRecord(
        area_reference=AREA,
        risk_score=0.4,
        assessed_at=INSTANT,
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    different = RiskScoreRecord(
        area_reference=AREA,
        risk_score=0.9,
        assessed_at=INSTANT,
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    later = RiskScoreRecord(
        area_reference=AREA,
        risk_score=0.9,
        assessed_at="2024-01-01T06:00:00Z",
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    # Re-assessing an area at a later instant is legitimate: that is a new forecast.
    assert check_risk_records([first, later]).ok is True
    assert check_risk_records([first, same]).has_duplicates is True
    assert check_risk_records([first, different]).has_conflicts is True


# --------------------------------------------------------------------------- #
# Batch ingest
# --------------------------------------------------------------------------- #


def test_a_batch_keeps_the_good_rows_and_reports_the_bad_ones():
    """Bad rows are recorded with their index, never silently dropped."""
    payloads = [
        _payload(),
        _payload(observed_at="not-a-time"),
        _payload(location_reference=""),
        _payload(measurements=[{"quantity": "water_level", "value": 2.7, "unit": "m"}]),
    ]
    outcome = ingest_observations(payloads)
    assert outcome.accepted_count == 2
    assert len(outcome.failures) == 2
    assert [index for index, _ in outcome.failures] == [1, 2]
    assert len(outcome.reports) == 4


def test_ingest_never_raises_for_bad_input():
    """Raising would abandon the findings for every row after the failure."""
    outcome = ingest_observations([None, "nonsense", 42, _payload()])
    assert outcome.accepted_count == 1
    assert len(outcome.failures) == 3


def test_ingest_reports_conflicts_across_the_batch():
    payloads = [_payload(), _payload(measurements=[{"quantity": "water_level", "value": 9.9, "unit": "m"}])]
    outcome = ingest_observations(payloads)
    assert outcome.accepted_count == 2
    assert outcome.conflicts is not None
    assert outcome.conflicts.has_conflicts is True
    # Both rows are surfaced as conflicted rather than one being chosen.
    assert len(outcome.rejected()) == 2


def test_ingest_accepts_a_custom_builder_for_other_record_types():
    outcome = ingest_observations(
        [_payload()],
        build=lambda payload: FloodEvent(
            event_reference=payload["location_reference"],
            area_reference=AREA,
            started_at=payload["observed_at"],
            dataset_type=DATASET_TYPE_SYNTHETIC,
        ),
    )
    assert outcome.accepted_count == 1
    assert isinstance(outcome.records[0], FloodEvent)


def test_ingest_output_serialises_for_storage():
    outcome = ingest_observations([_payload(), _payload(observed_at="nope")])
    payload = json.loads(json.dumps(outcome.to_dict()))
    assert payload["accepted_count"] == 1
    assert payload["failure_count"] == 1
    assert payload["failures"][0]["index"] == 1


# --------------------------------------------------------------------------- #
# Batch summary — the counters a quality record stores
# --------------------------------------------------------------------------- #


def test_the_summary_counts_every_record_including_the_clean_ones():
    outcome = ingest_observations(
        [
            _payload(),
            _payload(source_reference=None),
            _payload(observed_at="nope"),
            _payload(location_reference=""),
        ]
    )
    totals = summarise(outcome.reports)
    assert totals["records_checked"] == 4
    assert totals["records_rejected"] == 2
    assert totals["records_clean"] + totals["records_suspect"] + totals["records_rejected"] == 4
    assert totals["issue_counts"]


def test_the_summary_of_a_clean_batch_is_ok():
    totals = summarise([validate_observation_payload(_payload()) for _ in range(3)])
    assert totals["records_checked"] == 3
    assert totals["records_rejected"] == 0
    assert totals["quality_status"] == QUALITY_OK


def test_an_empty_batch_is_reported_as_zero_not_as_a_pass():
    totals = summarise([])
    assert totals["records_checked"] == 0
    assert totals["quality_status"] == QUALITY_OK
    assert totals["issue_counts"] == {}


def test_a_rejected_batch_is_marked_rejected_in_the_summary():
    totals = summarise([validate_observation_payload(_payload(location_reference=""))])
    assert totals["quality_status"] == QUALITY_REJECTED


# --------------------------------------------------------------------------- #
# Scope: validation must not preprocess
# --------------------------------------------------------------------------- #


def test_the_validator_exposes_no_resampling_filling_or_scaling():
    """Phase 2 owns those. Their presence here would blur the phase boundary."""
    forbidden = ("fillna", "ffill", "bfill", "resample", "interpolate", "scaler", "StandardScaler")
    import app.engines.hydro.quality as quality

    exported = dir(quality)
    for name in forbidden:
        assert not any(name in symbol for symbol in exported), name


def test_the_validator_does_not_import_the_frame_preprocessing_pipeline():
    """Keeps the Phase 1 / Phase 2 boundary enforced by the import graph.

    `preprocessing.py` answers "is this frame usable for training?". Importing it
    here would mean the structural validator had acquired opinions about resampling
    and missing-value policy, which are Phase 2's decisions.
    """
    import app.engines.hydro.quality as quality

    module_names = {value for value in vars(quality).values() if isinstance(value, type(sys))}
    assert not any(module.__name__.endswith("preprocessing") for module in module_names)
    assert "preprocessing" not in {
        name for name in dir(quality) if name == "preprocessing"
    }
    assert not any(name.startswith("Preprocessing") for name in dir(quality))


def test_quality_missing_is_a_status_a_supplier_may_declare():
    """Distinct from a null value: a declared absence, not an absent fact."""
    from app.engines.hydro.domains import QUALITY_STATUSES

    assert QUALITY_MISSING in QUALITY_STATUSES
    record = _observation().with_quality_status(QUALITY_MISSING)
    assert record.quality_status == QUALITY_MISSING


def test_the_ingest_report_type_is_exported_and_typed():
    outcome = IngestReport(subject="synthetic-batch")
    assert outcome.subject == "synthetic-batch"
    assert outcome.accepted_count == 0
    assert outcome.conflicts is None
    assert outcome.rejected() == ()
    payload = outcome.to_dict()
    assert payload["subject"] == "synthetic-batch"
    assert payload["accepted_count"] == 0
    assert payload["conflicts"] is None


def test_the_non_blocking_codes_are_exactly_the_advisory_findings():
    """A caller that wants "usable but unverified" filters on this set.

    If a code that rejects a record were ever listed here, that record would be
    admitted downstream — so the set is asserted rather than assumed.
    """
    assert NON_BLOCKING_CODES == {
        CODE_UNKNOWN_UNIT,
        CODE_RATE_WITHOUT_WINDOW,
        CODE_ABSENT_COLUMN,
        CODE_UNMAPPED_COLUMN,
        CODE_MISSING_SOURCE,
    }
    # Nothing in the advisory set may be an error anywhere in this module.
    for report in (
        validate_observation_payload(_payload(source_reference=None, measurements=[
            {"quantity": "water_level", "value": 2.5, "unit": "bananas"}
        ])),
    ):
        assert report.errors == ()