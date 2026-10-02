# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Tests for `app.engines.hydro.domains` — the Phase 1 record schemas.

**Every value in this file is SYNTHETIC/DEMO test data.** The station and area
references are deliberately labelled `SYNTHETIC-*` so that no assertion in this
module can be mistaken for a reference to a real gauge, a real reach, or a real
flood event. There is no verified hydrological observation data in this
repository, and nothing here pretends otherwise.

What these tests protect
------------------------
1. A record cannot be constructed without the facts that make it interpretable
   (an instant with an explicit zone, a location, a unit, a provenance class).
2. `dataset_type` really does drive the disclaimer, in both directions: a
   synthetic record always carries the warning, a real record never does.
3. The forecast contract's vocabulary is re-used rather than re-declared.
4. Nothing invents an identifier, a coordinate, a station or a threshold.
"""

from __future__ import annotations

import json

import pytest

from app.engines.hydro import contract
from app.engines.hydro.domains import (
    CANONICAL_QUANTITY,
    DATA_DOMAINS,
    DOMAIN_DISCHARGE,
    DOMAIN_FLOOD_EVENT,
    DOMAIN_INFLOW,
    DOMAIN_RAINFALL,
    DOMAIN_RISK_SCORE,
    DOMAIN_SPECS,
    DOMAIN_WATER_LEVEL,
    DOMAIN_WEATHER,
    MEASUREMENT_DOMAINS,
    NOT_AVAILABLE,
    QUALITY_OK,
    QUALITY_UNKNOWN,
    ColumnBinding,
    FloodEvent,
    Measurement,
    Observation,
    RiskScoreRecord,
    SchemaError,
    describe_domains,
    domain_catalog,
    domain_spec,
    observations_from_row,
    parse_instant,
    to_instant_iso,
    unit_is_known,
    unknown_columns,
)
from app.engines.hydro.provenance import (
    DATASET_TYPE_REAL,
    DATASET_TYPE_SYNTHETIC,
    DATASET_TYPE_UNKNOWN,
    SYNTHETIC_DATA_DISCLAIMER,
)

# SYNTHETIC/DEMO identifiers. Not a station, not a gauge, not a real reach.
SYNTHETIC_STATION = "SYNTHETIC-STATION-0001"
SYNTHETIC_AREA = "SYNTHETIC-AREA-0001"
SYNTHETIC_SOURCE = "synthetic://unit-test/generator"
SYNTHETIC_INSTANT = "2024-01-01T00:00:00Z"


# --------------------------------------------------------------------------- #
# Measurement
# --------------------------------------------------------------------------- #


def _rainfall(value: float = 1.25, unit: str = "mm/h") -> Measurement:
    return Measurement(quantity="rainfall", value=value, unit=unit)


def _level(value: float = 2.5, unit: str = "m") -> Measurement:
    return Measurement(quantity="water_level", value=value, unit=unit)


# --------------------------------------------------------------------------- #
# Timestamps
# --------------------------------------------------------------------------- #


def test_an_instant_must_carry_an_explicit_offset():
    parse_instant("2024-01-01T00:00:00Z")
    parse_instant("2024-01-01T05:30:00+05:30")


def test_a_naive_timestamp_is_refused_rather_than_assumed_utc():
    """The whole point: guessing the zone silently shifts the series."""
    with pytest.raises(SchemaError, match="no UTC offset"):
        parse_instant("2024-01-01T00:00:00")


def test_an_unparseable_timestamp_is_refused():
    with pytest.raises(SchemaError, match="not a parseable ISO-8601"):
        parse_instant("first of January")


def test_a_blank_timestamp_is_refused():
    with pytest.raises(SchemaError, match="non-empty ISO-8601"):
        parse_instant("   ")


def test_instant_rendering_normalises_to_utc():
    from datetime import datetime, timezone

    rendered = to_instant_iso(datetime(2024, 1, 1, 5, 30, tzinfo=timezone.utc))
    assert rendered == "2024-01-01T05:30:00Z"


# --------------------------------------------------------------------------- #
# Observation — creation, per domain
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("domain", MEASUREMENT_DOMAINS)
def test_every_measurement_domain_can_hold_a_record(domain):
    quantity = CANONICAL_QUANTITY.get(domain, "temperature")
    record = Observation(
        domain=domain,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(Measurement(quantity=quantity, value=1.0, unit="mm/h"),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
        source_reference=SYNTHETIC_SOURCE,
    )
    assert record.domain == domain
    assert record.value_for(quantity) == 1.0
    assert record.disclaimer == SYNTHETIC_DATA_DISCLAIMER


def test_a_weather_record_carries_several_quantities_at_one_instant():
    """Weather is multi-quantity: a source may report temperature and humidity."""
    record = Observation(
        domain=DOMAIN_WEATHER,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(
            Measurement(quantity="temperature", value=27.5, unit="degC"),
            Measurement(quantity="humidity", value=80.0, unit="%"),
        ),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert record.value_for("temperature") == 27.5
    assert record.value_for("humidity") == 80.0
    assert record.value_for("pressure") is None


def test_a_single_quantity_domain_rejects_a_foreign_quantity():
    """A `discharge` value filed as a water level is a unit error, not a detail."""
    with pytest.raises(SchemaError, match="accepts only the 'water_level' quantity"):
        Observation(
            domain=DOMAIN_WATER_LEVEL,
            location_reference=SYNTHETIC_STATION,
            observed_at=SYNTHETIC_INSTANT,
            measurements=(_rainfall(),),
        )


def test_inflow_is_a_distinct_domain_from_discharge():
    """Inflow forecasting is a project requirement; a discharge gauge is not it."""
    assert DOMAIN_INFLOW in DATA_DOMAINS
    assert DOMAIN_DISCHARGE in DATA_DOMAINS
    inflow = Observation(
        domain=DOMAIN_INFLOW,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(Measurement(quantity="inflow", value=42.0, unit="m3/s"),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    discharge = Observation(
        domain=DOMAIN_DISCHARGE,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(Measurement(quantity="discharge", value=42.0, unit="m3/s"),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert inflow.domain != discharge.domain


def test_measurement_window_is_carried_so_accumulation_is_possible_later():
    """Phase 1 records the window; it does not accumulate. Phase 3 does that."""
    record = Observation(
        domain=DOMAIN_RAINFALL,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(_rainfall(),),
        measurement_window="1h",
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert record.measurement_window == "1h"


# --------------------------------------------------------------------------- #
# Observation — required fields
# --------------------------------------------------------------------------- #


def test_an_observation_requires_a_location_reference():
    with pytest.raises(SchemaError, match="location_reference is required"):
        Observation(
            domain=DOMAIN_WATER_LEVEL,
            location_reference="   ",
            observed_at=SYNTHETIC_INSTANT,
            measurements=(_level(),),
        )


def test_an_observation_requires_at_least_one_measurement():
    with pytest.raises(SchemaError, match="at least one measurement"):
        Observation(
            domain=DOMAIN_WATER_LEVEL,
            location_reference=SYNTHETIC_STATION,
            observed_at=SYNTHETIC_INSTANT,
            measurements=(),
        )


def test_an_observation_requires_a_unit_on_every_measurement():
    with pytest.raises(SchemaError, match="must declare a unit"):
        Measurement(quantity="rainfall", value=1.0, unit="  ")


def test_an_observation_requires_a_quantity():
    with pytest.raises(SchemaError, match="quantity must be a non-empty string"):
        Measurement(quantity="", value=1.0, unit="mm")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_measurement_value_must_be_finite(bad):
    with pytest.raises(SchemaError, match="must be finite"):
        Measurement(quantity="water_level", value=bad, unit="m")


def test_a_boolean_is_not_a_measurement():
    """`True` would otherwise coerce to 1.0 and look like a plausible reading."""
    with pytest.raises(SchemaError, match="must be a real number"):
        Measurement(quantity="water_level", value=True, unit="m")


def test_two_values_for_one_quantity_at_one_instant_are_ambiguous():
    with pytest.raises(SchemaError, match="duplicate quantity"):
        Observation(
            domain=DOMAIN_WATER_LEVEL,
            location_reference=SYNTHETIC_STATION,
            observed_at=SYNTHETIC_INSTANT,
            measurements=(_level(1.0), _level(2.0)),
        )


def test_an_unknown_domain_is_refused():
    with pytest.raises(SchemaError, match="unknown domain"):
        Observation(
            domain="soil_moisture",
            location_reference=SYNTHETIC_STATION,
            observed_at=SYNTHETIC_INSTANT,
            measurements=(_level(),),
        )


def test_a_non_measurement_domain_cannot_borrow_the_observation_record():
    """A flood event is not a measurement; forcing it through would hide that."""
    with pytest.raises(SchemaError, match="does not carry measurements"):
        Observation(
            domain=DOMAIN_FLOOD_EVENT,
            location_reference=SYNTHETIC_AREA,
            observed_at=SYNTHETIC_INSTANT,
            measurements=(_level(),),
        )


# --------------------------------------------------------------------------- #
# Provenance classification
# --------------------------------------------------------------------------- #


def test_a_synthetic_record_carries_the_mandatory_disclaimer():
    record = Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(_level(),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert record.is_synthetic is True
    assert record.disclaimer == SYNTHETIC_DATA_DISCLAIMER


def test_an_unclassified_record_is_unknown_and_carries_its_own_warning():
    record = Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(_level(),),
    )
    assert record.dataset_type == DATASET_TYPE_UNKNOWN
    assert record.disclaimer is not None
    assert record.disclaimer != SYNTHETIC_DATA_DISCLAIMER


def test_a_real_record_carries_no_synthetic_disclaimer():
    """Labelling genuine data as fake is its own dishonesty."""
    record = Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference="STATION-REFERENCE-SUPPLIED-BY-DATASET-OWNER",
        observed_at=SYNTHETIC_INSTANT,
        measurements=(Measurement(quantity="water_level", value=2.5, unit="m"),),
        dataset_type=DATASET_TYPE_REAL,
    )
    assert record.disclaimer is None
    assert record.may_be_presented_as_observation_data is True


def test_a_dataset_type_outside_the_vocabulary_is_refused():
    with pytest.raises(SchemaError, match="dataset_type must be one of"):
        Observation(
            domain=DOMAIN_WATER_LEVEL,
            location_reference=SYNTHETIC_STATION,
            observed_at=SYNTHETIC_INSTANT,
            measurements=(_level(),),
            dataset_type="probably_real",
        )


def test_the_disclaimer_text_is_the_one_provenance_defines():
    """One sentence, one source. A second copy would eventually disagree."""
    from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER as canonical

    record = Observation(
        domain=DOMAIN_RAINFALL,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(_rainfall(),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert record.disclaimer == canonical
    assert record.disclaimer == SYNTHETIC_DATA_DISCLAIMER


@pytest.mark.parametrize("dataset_type", [DATASET_TYPE_SYNTHETIC, DATASET_TYPE_UNKNOWN])
def test_non_real_records_are_never_presentable_as_observations(dataset_type):
    record = Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(_level(),),
        dataset_type=dataset_type,
    )
    assert record.may_be_presented_as_observation_data is False


# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #


def test_an_unrecognised_unit_is_kept_verbatim_and_never_converted():
    """No authority in this repository over which units a foreign source uses."""
    record = Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(Measurement(quantity="water_level", value=7.5, unit="ft"),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert record.unit_for("water_level") == "ft"
    assert unit_is_known("ft") is True
    assert unit_is_known("bananas") is False


def test_the_deliberately_worded_demo_inflow_unit_is_accepted():
    """The synthetic pipeline declares inflow's unit as UNDETERMINED on purpose."""
    demo_unit = (
        "UNDETERMINED (demo — no unit assigned; a real dataset's inflow unit must be "
        "supplied by the dataset owner, typically m3/s, along with the rating curve "
        "used to derive it)"
    )
    record = Observation(
        domain=DOMAIN_INFLOW,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(Measurement(quantity="inflow", value=42.0, unit=demo_unit),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert record.unit_for("inflow") == demo_unit
    assert unit_is_known(demo_unit) is False


# --------------------------------------------------------------------------- #
# Quality status
# --------------------------------------------------------------------------- #


def test_a_fresh_record_has_not_been_assessed_yet():
    record = Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(_level(),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert record.quality_status == QUALITY_UNKNOWN


def test_quality_status_can_be_recorded_without_mutating_the_original():
    record = Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(_level(),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assessed = record.with_quality_status(QUALITY_OK)
    assert assessed.quality_status == QUALITY_OK
    assert record.quality_status == QUALITY_UNKNOWN
    assert assessed.disclaimer == record.disclaimer


def test_an_out_of_vocabulary_quality_status_is_refused():
    with pytest.raises(SchemaError, match="quality_status must be one of"):
        Observation(
            domain=DOMAIN_WATER_LEVEL,
            location_reference=SYNTHETIC_STATION,
            observed_at=SYNTHETIC_INSTANT,
            measurements=(_level(),),
            quality_status="looks-fine-to-me",
        )


# --------------------------------------------------------------------------- #
# Forecast compatibility
# --------------------------------------------------------------------------- #


def test_an_observation_can_supply_the_contract_identifying_fields():
    record = Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(Measurement(quantity="water_level", value=2.5, unit="m"),),
        provenance_reference="provenance://unit-test/record",
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    inputs = record.forecast_inputs()
    assert inputs["station_reference"] == SYNTHETIC_STATION
    assert inputs["target"] == "water_level"
    assert inputs["target_units"] == "m"
    assert record.missing_forecast_inputs() == ()


def test_forecast_input_names_are_the_contracts_own_field_names():
    """Phase 5 must not invent a differently-spelled field.

    Asserted as a subset relation against `ForecastOutput`'s real dataclass
    fields, so adding a differently-named key to `forecast_inputs()` fails here
    rather than at the first consumer.
    """
    record = Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(_level(),),
        provenance_reference="provenance://unit-test/record",
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    contract_fields = set(contract.ForecastOutput.__dataclass_fields__)
    assert set(record.forecast_inputs()) <= contract_fields
    assert {
        "station_reference",
        "target",
        "target_units",
        "provenance_reference",
    } <= contract_fields
    assert set(record.missing_forecast_inputs()) == set()


def test_dataset_type_travels_beside_the_forecast_not_inside_it():
    """`ForecastOutput` has no `dataset_type` field; pretending otherwise would
    send a reader looking for it in a payload that does not contain it."""
    record = Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(_level(),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert "dataset_type" not in contract.ForecastOutput.__dataclass_fields__
    assert "dataset_type" not in record.forecast_inputs()
    assert record.forecast_provenance_inputs()["dataset_type"] == DATASET_TYPE_SYNTHETIC
    assert record.forecast_provenance_inputs()["disclaimer"] == SYNTHETIC_DATA_DISCLAIMER


def test_a_record_with_no_provenance_reference_reports_it_as_missing():
    record = Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(_level(),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert "provenance_reference" not in record.forecast_inputs()


def test_an_observation_can_drive_the_existing_forecast_contract_unchanged():
    """Compatibility test: build the real `ForecastOutput` from record facts.

    Asserts the Phase 1 schema feeds the existing contract without renaming or
    removing any of its fields.
    """
    record = Observation(
        domain=DOMAIN_INFLOW,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(Measurement(quantity="inflow", value=42.0, unit="m3/s"),),
        provenance_reference="provenance://unit-test/record",
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    inputs = record.forecast_inputs()
    forecast = contract.ForecastOutput(
        forecast_id="SYNTHETIC-FORECAST-0001",
        forecast_timestamp=SYNTHETIC_INSTANT,
        forecast_horizon="6h",
        model_id="SYNTHETIC-MODEL-0001",
        model_version="0.0.0-synthetic",
        station_reference=inputs["station_reference"],
        target=inputs["target"],
        target_units=inputs["target_units"],
        provenance_reference=inputs["provenance_reference"],
    )
    payload = forecast.to_dict()
    # Every field the integration contract relies on is still present.
    for name in (
        "forecast_id",
        "forecast_timestamp",
        "forecast_horizon",
        "station_reference",
        "target",
        "target_units",
        "predicted_value",
        "predicted_inflow",
        "flood_probability",
        "risk_level",
        "threshold",
        "threshold_policy",
        "residual_sigma",
        "provenance_reference",
        "contract_version",
        "status",
    ):
        assert name in payload, f"the forecast contract lost {name!r}"
    assert payload["contract_version"] == contract.FORECAST_CONTRACT_VERSION
    assert payload["target"] == "inflow"


# --------------------------------------------------------------------------- #
# Flood events
# --------------------------------------------------------------------------- #


def test_a_flood_event_record_can_be_built_and_carries_its_provenance():
    event = FloodEvent(
        event_reference="SYNTHETIC-EVENT-0001",
        area_reference=SYNTHETIC_AREA,
        started_at="2024-01-01T00:00:00Z",
        ended_at="2024-01-02T06:00:00Z",
        severity="DEMO-severity-label-not-a-standard-scale",
        severity_source="synthetic://unit-test/generator",
        status="closed",
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert event.is_ongoing is False
    assert event.disclaimer == SYNTHETIC_DATA_DISCLAIMER
    assert event.area_reference == SYNTHETIC_AREA


def test_an_event_with_no_recorded_end_is_ongoing_but_says_nothing_stronger():
    """`is_ongoing` means "no end recorded", which is not "still flooding"."""
    event = FloodEvent(
        event_reference="SYNTHETIC-EVENT-0002",
        area_reference=SYNTHETIC_AREA,
        started_at="2024-01-01T00:00:00Z",
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert event.is_ongoing is True
    assert event.ended_at is None
    assert event.severity is None
    assert event.status == "unknown"


def test_an_event_that_ends_before_it_starts_is_refused():
    with pytest.raises(SchemaError, match="precedes started_at"):
        FloodEvent(
            event_reference="SYNTHETIC-EVENT-0003",
            area_reference=SYNTHETIC_AREA,
            started_at="2024-01-02T00:00:00Z",
            ended_at="2024-01-01T00:00:00Z",
        )


def test_an_event_requires_an_event_reference_and_an_area():
    with pytest.raises(SchemaError, match="event_reference is required"):
        FloodEvent(event_reference="", area_reference=SYNTHETIC_AREA, started_at=SYNTHETIC_INSTANT)
    with pytest.raises(SchemaError, match="area_reference is required"):
        FloodEvent(event_reference="SYNTHETIC-EVENT-0004", area_reference="  ", started_at=SYNTHETIC_INSTANT)


def test_event_severity_is_free_text_because_no_scale_has_been_approved():
    """No severity vocabulary is imposed: an invented one would look official."""
    for label in ("catastrophic", "level-3", "SEV-2", "未知"):
        event = FloodEvent(
            event_reference="SYNTHETIC-EVENT-0005",
            area_reference=SYNTHETIC_AREA,
            started_at=SYNTHETIC_INSTANT,
            severity=label,
            dataset_type=DATASET_TYPE_SYNTHETIC,
        )
        assert event.severity == label


def test_the_repository_declares_that_it_holds_no_flood_events():
    spec = domain_spec(DOMAIN_FLOOD_EVENT)
    assert spec.present_in_repository is False
    assert NOT_AVAILABLE in spec.availability_note


# --------------------------------------------------------------------------- #
# Risk records
# --------------------------------------------------------------------------- #


def test_a_risk_record_needs_nothing_beyond_an_area():
    """The pending, unassessed state is representable and is not a zero risk."""
    record = RiskScoreRecord(area_reference=SYNTHETIC_AREA)
    assert record.is_available is False
    assert record.risk_score is None
    assert record.risk_level is None
    assert record.status == "pending"
    assert "risk_score" in record.missing_fields()


def test_a_risk_record_reports_its_own_gaps():
    record = RiskScoreRecord(area_reference=SYNTHETIC_AREA, risk_score=0.4)
    missing = record.missing_fields()
    assert "risk_level" in missing
    assert "forecast_reference" in missing
    assert "provenance_reference" in missing
    assert "area_reference" not in missing


def test_risk_level_and_priority_come_from_the_existing_contract_vocabulary():
    for level in contract.SUPPORTED_RISK_LEVELS:
        record = RiskScoreRecord(
            area_reference=SYNTHETIC_AREA,
            risk_score=0.5,
            risk_level=level,
            dataset_type=DATASET_TYPE_SYNTHETIC,
        )
        assert record.priority == contract.priority_for_risk_level(level)
        assert record.priority in contract.SUPPORTED_PRIORITIES


def test_the_modules_vocabularies_cannot_drift_from_the_contract():
    """A test, because two lists of the same four words will drift eventually."""
    record = RiskScoreRecord(
        area_reference=SYNTHETIC_AREA,
        risk_score=0.5,
        risk_level="HIGH",
    )
    with pytest.raises(SchemaError, match="is not one of"):
        RiskScoreRecord(area_reference=SYNTHETIC_AREA, risk_level="SEVERE")
    assert record.priority == "high"
    assert contract.SUPPORTED_RISK_LEVELS == ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def test_a_risk_score_outside_zero_to_one_is_a_scale_error():
    """The optimizer's objective reads a [0, 1] term; 1.7 is not 'high risk'."""
    with pytest.raises(SchemaError, match=r"must lie in \[0, 1\]"):
        RiskScoreRecord(area_reference=SYNTHETIC_AREA, risk_score=1.7)


def test_an_approved_threshold_requires_evidence():
    with pytest.raises(SchemaError, match="requires both a threshold and a threshold_source"):
        RiskScoreRecord(
            area_reference=SYNTHETIC_AREA,
            threshold_policy="approved",
            threshold=5.0,
        )


def test_a_pending_threshold_needs_no_citation():
    record = RiskScoreRecord(
        area_reference=SYNTHETIC_AREA,
        risk_score=0.2,
        threshold_policy="pending",
    )
    assert record.threshold is None
    assert record.threshold_policy == "pending"


def test_a_risk_record_rejects_an_unknown_payload_key():
    with pytest.raises(SchemaError, match="unknown key"):
        RiskScoreRecord.from_dict({"area_reference": SYNTHETIC_AREA, "population_at_risk": 12000})


def test_no_exposure_values_are_modelled_on_a_risk_record():
    """No population, asset or elevation field exists — and none is invented."""
    fields = set(RiskScoreRecord.__dataclass_fields__)
    for forbidden in ("population", "assets", "elevation", "exposure", "coordinates", "lat", "lon"):
        assert not any(forbidden in name for name in fields)


# --------------------------------------------------------------------------- #
# Serialisation round-trips
# --------------------------------------------------------------------------- #


def test_an_observation_round_trips_through_dict_and_json():
    record = Observation(
        domain=DOMAIN_WEATHER,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(
            Measurement(quantity="temperature", value=27.5, unit="degC"),
            Measurement(quantity="humidity", value=80.0, unit="%"),
        ),
        measurement_window="1h",
        source_reference=SYNTHETIC_SOURCE,
        provenance_reference="provenance://unit-test/record",
        dataset_reference="synthetic://unit-test/dataset",
        dataset_type=DATASET_TYPE_SYNTHETIC,
        quality_status=QUALITY_OK,
        notes="SYNTHETIC/DEMO test record",
    )
    payload = record.to_dict()
    restored = Observation.from_dict(json.loads(json.dumps(payload)))
    assert restored == record


def test_a_flood_event_round_trips_through_dict_and_json():
    event = FloodEvent(
        event_reference="SYNTHETIC-EVENT-0001",
        area_reference=SYNTHETIC_AREA,
        started_at="2024-01-01T00:00:00Z",
        ended_at="2024-01-02T06:00:00Z",
        severity="DEMO-label",
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    restored = FloodEvent.from_dict(json.loads(json.dumps(event.to_dict())))
    assert restored == event


def test_a_risk_record_round_trips_through_dict_and_json():
    record = RiskScoreRecord(
        area_reference=SYNTHETIC_AREA,
        risk_score=0.73,
        risk_level="HIGH",
        forecast_reference="SYNTHETIC-FORECAST-0001",
        assessed_at=SYNTHETIC_INSTANT,
        status="recorded",
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    restored = RiskScoreRecord.from_dict(json.loads(json.dumps(record.to_dict())))
    assert restored == record


def test_round_trip_preserves_the_disclaimer_for_non_real_data():
    record = Observation(
        domain=DOMAIN_RAINFALL,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(_rainfall(),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    restored = Observation.from_dict(record.to_dict())
    assert restored.disclaimer == SYNTHETIC_DATA_DISCLAIMER
    assert restored.is_synthetic is True


def test_an_unknown_key_on_a_record_payload_is_not_silently_dropped():
    """`from_dict` on Observation is lenient by design, so the strict check is
    that the value still round-trips through `to_dict` unchanged."""
    record = Observation(
        domain=DOMAIN_WATER_LEVEL,
        location_reference=SYNTHETIC_STATION,
        observed_at=SYNTHETIC_INSTANT,
        measurements=(_level(),),
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    payload = record.to_dict()
    assert set(payload) == {
        "domain",
        "location_reference",
        "observed_at",
        "measurements",
        "measurement_window",
        "source_reference",
        "provenance_reference",
        "dataset_reference",
        "dataset_type",
        "quality_status",
        "disclaimer",
        "notes",
    }


# --------------------------------------------------------------------------- #
# Column bindings and row splitting
# --------------------------------------------------------------------------- #


def test_a_wide_row_becomes_one_record_per_domain():
    """Level and rainfall at one instant are two records: different units."""
    bindings = [
        ColumnBinding(column="water_level", domain=DOMAIN_WATER_LEVEL, quantity="water_level", unit="m"),
        ColumnBinding(column="rainfall_mm", domain=DOMAIN_RAINFALL, quantity="rainfall", unit="mm/h"),
        ColumnBinding(column="inflow", domain=DOMAIN_INFLOW, quantity="inflow", unit="m3/s"),
    ]
    records = observations_from_row(
        {
            "timestamp": SYNTHETIC_INSTANT,
            "water_level": 2.5,
            "rainfall_mm": 1.25,
            "inflow": 42.0,
            "temperature": 27.5,
        },
        bindings,
        location_reference=SYNTHETIC_STATION,
        dataset_type=DATASET_TYPE_SYNTHETIC,
        measurement_window="1h",
    )
    assert {record.domain for record in records} == {
        DOMAIN_WATER_LEVEL,
        DOMAIN_RAINFALL,
        DOMAIN_INFLOW,
    }
    level = next(r for r in records if r.domain == DOMAIN_WATER_LEVEL)
    assert level.value_for("water_level") == 2.5
    assert level.unit_for("water_level") == "m"


def test_unbound_columns_are_reported_rather_than_ignored():
    bindings = [
        ColumnBinding(column="water_level", domain=DOMAIN_WATER_LEVEL, quantity="water_level", unit="m")
    ]
    row = {"timestamp": SYNTHETIC_INSTANT, "water_level": 2.5, "soil_moisture": 0.3}
    assert unknown_columns(row, bindings) == ("soil_moisture",)


def test_a_bound_column_absent_from_the_row_produces_no_record():
    """An absent column is not a zero reading."""
    bindings = [
        ColumnBinding(column="water_level", domain=DOMAIN_WATER_LEVEL, quantity="water_level", unit="m"),
        ColumnBinding(column="inflow", domain=DOMAIN_INFLOW, quantity="inflow", unit="m3/s"),
    ]
    records = observations_from_row(
        {"timestamp": SYNTHETIC_INSTANT, "water_level": 2.5},
        bindings,
        location_reference=SYNTHETIC_STATION,
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    assert [record.domain for record in records] == [DOMAIN_WATER_LEVEL]


def test_a_null_cell_produces_no_measurement_rather_than_a_zero():
    bindings = [
        ColumnBinding(column="water_level", domain=DOMAIN_WATER_LEVEL, quantity="water_level", unit="m")
    ]
    assert (
        observations_from_row(
            {"timestamp": SYNTHETIC_INSTANT, "water_level": None},
            bindings,
            location_reference=SYNTHETIC_STATION,
        )
        == []
    )


def test_a_non_numeric_cell_is_refused_not_coerced():
    binding = ColumnBinding(
        column="water_level", domain=DOMAIN_WATER_LEVEL, quantity="water_level", unit="m"
    )
    with pytest.raises(SchemaError, match="not a number"):
        binding.to_measurement("n/a")


def test_a_binding_must_name_a_registered_domain():
    with pytest.raises(SchemaError, match="unknown domain"):
        ColumnBinding(column="x", domain="soil_moisture", quantity="soil_moisture", unit="frac")


def test_a_binding_declares_its_unit_rather_than_inferring_it():
    """`water_level` says nothing about metres versus feet."""
    metres = ColumnBinding(
        column="level", domain=DOMAIN_WATER_LEVEL, quantity="water_level", unit="m"
    )
    feet = ColumnBinding(
        column="level", domain=DOMAIN_WATER_LEVEL, quantity="water_level", unit="ft"
    )
    assert metres.to_measurement(1.0).to_dict() != feet.to_measurement(1.0).to_dict()


# --------------------------------------------------------------------------- #
# Domain registry
# --------------------------------------------------------------------------- #


def test_every_domain_is_registered_and_documented():
    assert {spec.name for spec in DOMAIN_SPECS} == set(DATA_DOMAINS)
    catalog = domain_catalog()
    assert len(catalog) == len(DOMAIN_SPECS)
    for entry in catalog:
        assert entry["availability_note"], f"{entry['name']} has no availability note"
        assert entry["record_type"] in ("Observation", "FloodEvent", "RiskScoreRecord")


def test_the_forecast_domain_is_not_redeclared_here():
    """A second forecast record would be a competing contract."""
    assert "forecast" not in DATA_DOMAINS


def test_an_unregistered_domain_lookup_raises_rather_than_defaulting():
    with pytest.raises(SchemaError, match="unknown domain"):
        domain_spec("groundwater")


def test_the_domain_table_states_what_is_absent():
    """The repository's own inventory is part of the deliverable."""
    text = describe_domains()
    assert "rainfall" in text
    assert NOT_AVAILABLE in text
    for domain in (DOMAIN_WEATHER, DOMAIN_DISCHARGE, DOMAIN_FLOOD_EVENT):
        assert domain in text


def test_domains_this_repository_actually_holds_are_labelled_synthetic():
    """`present_in_repository` never means 'real'."""
    for spec in DOMAIN_SPECS:
        if spec.present_in_repository:
            assert "synthetic" in spec.availability_note.lower() or "DEMO" in spec.availability_note