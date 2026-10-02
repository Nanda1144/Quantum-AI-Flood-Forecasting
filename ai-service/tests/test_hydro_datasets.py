# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Tests for `app.engines.hydro.datasets` — Phase 1 dataset metadata.

What these tests protect
------------------------
1. The empty catalog is the honest default and says so in words.
2. The one descriptor the repository can build describes the *committed* file —
   its checksum, row count and columns are read from bytes on disk, not from prose.
3. No descriptor claims to be presentable as real observation data.
4. Nothing is invented: no organisation, no licence, no station, no domain the
   file does not contain.

The catalogue under test is the committed SYNTHETIC/DEMO sample. Nothing here
describes a real gauge, a real organisation or a real licence.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from app.engines.hydro.config import DatasetSpec
from app.engines.hydro.datasets import (
    COVERAGE_ABSENT,
    COVERAGE_AVAILABLE,
    COVERAGE_STATUSES,
    COVERAGE_UNKNOWN,
    EMPTY_CATALOG,
    NO_VERIFIED_DATASETS,
    SCHEMA_VERSION,
    SYNTHETIC_SAMPLE_COLUMNS,
    SYNTHETIC_SAMPLE_PATH,
    DatasetCatalog,
    DatasetDescriptor,
    DomainCoverage,
    catalog_from_config,
    committed_sample_catalog,
    coverage_matrix,
    synthetic_sample_descriptor,
    unknown_coverage,
)
from app.engines.hydro.domains import (
    DATA_DOMAINS,
    DOMAIN_DISCHARGE,
    DOMAIN_FLOOD_EVENT,
    DOMAIN_INFLOW,
    DOMAIN_RAINFALL,
    DOMAIN_RISK_SCORE,
    DOMAIN_WATER_LEVEL,
    DOMAIN_WEATHER,
    NOT_AVAILABLE,
)
from app.engines.hydro.provenance import (
    DATASET_TYPE_REAL,
    DATASET_TYPE_SYNTHETIC,
    SYNTHETIC_DATA_DISCLAIMER,
    ProvenanceRecord,
)

#: The committed file's digest, recorded when it was generated. Asserting it
#: means the descriptor cannot quietly describe a *different* sample file.
EXPECTED_CHECKSUM = "56f4b7c5b4122b5d9b61db256f8d7afcb7e03d4a1cf9e942c013818386e29ac6"

#: Number of rows in the committed sample (header excluded).
EXPECTED_ROWS = 2160


# --------------------------------------------------------------------------- #
# The empty catalog is the honest default
# --------------------------------------------------------------------------- #


def test_the_default_catalog_is_empty():
    assert EMPTY_CATALOG.datasets == ()
    assert EMPTY_CATALOG.real_datasets() == ()
    assert EMPTY_CATALOG.non_real_datasets() == ()
    assert EMPTY_CATALOG.domains_available_anywhere() == ()


def test_an_empty_catalog_says_it_is_empty_rather_than_looking_well_stocked():
    """A registry that silently contains nothing reads the same as one nobody checked."""
    description = EMPTY_CATALOG.describe()
    assert "empty" in description.lower()
    assert NO_VERIFIED_DATASETS in description
    assert NOT_AVAILABLE in description


def test_no_dataset_is_presentable_as_observation_data_by_default():
    for descriptor in committed_sample_catalog().datasets:
        assert descriptor.may_be_presented_as_observation_data is False


def test_the_catalog_serialises_with_the_schema_version():
    payload = json.loads(json.dumps(committed_sample_catalog().to_dict()))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["dataset_count"] == 1
    assert payload["real_dataset_count"] == 0


# --------------------------------------------------------------------------- #
# The committed synthetic sample
# --------------------------------------------------------------------------- #


def test_the_sample_file_is_committed_where_the_module_says_it_is():
    assert os.path.exists(SYNTHETIC_SAMPLE_PATH)
    assert SYNTHETIC_SAMPLE_PATH.endswith(
        os.path.join("data", "synthetic_hydrology_sample.csv")
    )


def test_the_descriptor_checksum_matches_the_bytes_on_disk():
    """Read the file directly, so a regenerated or edited sample cannot slip past."""
    descriptor = synthetic_sample_descriptor()
    with open(SYNTHETIC_SAMPLE_PATH, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    assert descriptor.checksum == digest


def test_the_recorded_checksum_is_the_one_the_generator_produced():
    """Pins the artefact itself, so a silent data swap becomes a test failure."""
    descriptor = synthetic_sample_descriptor()
    assert descriptor.checksum == EXPECTED_CHECKSUM


def test_the_record_count_is_read_from_the_file_not_asserted():
    descriptor = synthetic_sample_descriptor()
    with open(SYNTHETIC_SAMPLE_PATH, newline="", encoding="utf-8") as handle:
        lines = handle.read().strip().splitlines()
    assert len(lines) - 1 == EXPECTED_ROWS  # header excluded
    assert descriptor.coverage_for(DOMAIN_WATER_LEVEL).record_count == EXPECTED_ROWS


def test_the_declared_columns_are_the_ones_the_file_actually_has():
    """An unmapped column is an undeclared observation; the descriptor must say so."""
    with open(SYNTHETIC_SAMPLE_PATH, newline="", encoding="utf-8") as handle:
        header = handle.readline().strip().split(",")
    assert header == list(SYNTHETIC_SAMPLE_COLUMNS)
    assert "NOTE: columns not declared" not in synthetic_sample_descriptor().notes


def test_the_sample_is_synthetic_and_carries_the_mandatory_warning():
    descriptor = synthetic_sample_descriptor()
    assert descriptor.dataset_type == DATASET_TYPE_SYNTHETIC
    assert descriptor.is_synthetic is True
    assert descriptor.disclaimer == SYNTHETIC_DATA_DISCLAIMER
    assert SYNTHETIC_DATA_DISCLAIMER in descriptor.describe()


def test_the_descriptor_declares_no_station():
    """The file has no station column.

    `SYNTHETIC-STATION-0001` is a demo value in the configuration, not a property
    of the data. Promoting it here would invent a gauge network.
    """
    assert "station" not in SYNTHETIC_SAMPLE_COLUMNS
    assert synthetic_sample_descriptor().station_reference is None
    assert "station_reference" in synthetic_sample_descriptor().missing_fields()


def test_the_descriptor_declares_no_source_organisation():
    """Nobody has supplied an organisation, so no organisation is named."""
    assert synthetic_sample_descriptor().source_organisation is None
    assert "source_organisation" in synthetic_sample_descriptor().missing_fields()


def test_the_descriptor_does_not_invent_a_licence():
    """The licence says exactly that there is none, because the data is not real."""
    descriptor = synthetic_sample_descriptor()
    assert descriptor.license is not None
    assert "none" in descriptor.license.lower()
    assert "license" not in descriptor.missing_fields()


def test_the_inflow_unit_is_recorded_as_undetermined_not_guessed():
    """`m3/s` would be a plausible-looking guess for an inflow column. Not made."""
    inflow = synthetic_sample_descriptor().coverage_for(DOMAIN_INFLOW)
    assert "UNDETERMINED" in (inflow.units or "")


def test_the_water_level_datum_is_recorded_as_fictional():
    descriptor = synthetic_sample_descriptor()
    level = descriptor.coverage_for(DOMAIN_WATER_LEVEL)
    assert "fictional" in (level.units or "").lower()


# --------------------------------------------------------------------------- #
# Coverage — the point of the module
# --------------------------------------------------------------------------- #


def test_the_sample_covers_exactly_three_domains():
    assert set(synthetic_sample_descriptor().available_domains()) == {
        DOMAIN_WATER_LEVEL,
        DOMAIN_INFLOW,
        DOMAIN_RAINFALL,
    }


def test_the_domains_the_sample_lacks_are_declared_absent_not_unknown():
    """`absent` is a fact; `unknown` is an absence of information. They differ."""
    descriptor = synthetic_sample_descriptor()
    assert set(descriptor.absent_domains()) == {
        DOMAIN_WEATHER,
        DOMAIN_DISCHARGE,
        DOMAIN_FLOOD_EVENT,
        DOMAIN_RISK_SCORE,
    }
    assert descriptor.unknown_domains() == ()


def test_coverage_defaults_to_unknown_for_every_domain():
    """A dataset is not assumed to carry anything; the supplier states what it does."""
    entries = unknown_coverage()
    assert len(entries) == len(DATA_DOMAINS)
    assert all(entry.status == COVERAGE_UNKNOWN for entry in entries)
    assert all(entry.is_available is False for entry in entries)


def test_coverage_of_an_unstated_domain_is_unknown_rather_than_absent():
    descriptor = DatasetDescriptor()
    coverage = descriptor.coverage_for(DOMAIN_DISCHARGE)
    assert coverage.status == COVERAGE_UNKNOWN
    assert coverage.is_asserted is False


def test_every_coverage_status_is_from_the_vocabulary():
    with pytest.raises(ValueError, match="coverage status must be"):
        DomainCoverage(domain=DOMAIN_RAINFALL, status="probably there")


def test_a_coverage_status_must_be_a_registered_domain():
    with pytest.raises(ValueError):
        DomainCoverage(domain="groundwater")


def test_a_negative_record_count_is_refused():
    with pytest.raises(ValueError, match="record_count must be"):
        DomainCoverage(domain=DOMAIN_RAINFALL, record_count=-1)


def test_coverage_matrix_lists_every_domain_exactly_once():
    rows = coverage_matrix()
    assert [row["domain"] for row in rows] == list(DATA_DOMAINS)


def test_the_coverage_matrix_names_the_sample_column_as_the_source():
    """The grid answers "which dataset supplies which domain?", so it is keyed by reference."""
    rows = coverage_matrix(committed_sample_catalog())
    assert all("synthetic://hydrology/committed-sample" in row for row in rows)
    row = next(row for row in rows if row["domain"] == DOMAIN_WATER_LEVEL)
    assert row["synthetic://hydrology/committed-sample"] == COVERAGE_AVAILABLE
    row = next(row for row in rows if row["domain"] == DOMAIN_DISCHARGE)
    assert row["synthetic://hydrology/committed-sample"] == COVERAGE_ABSENT


def test_the_catalog_reports_which_domains_are_available_anywhere():
    catalog = committed_sample_catalog()
    assert set(catalog.domains_available_anywhere()) == {
        DOMAIN_WATER_LEVEL,
        DOMAIN_INFLOW,
        DOMAIN_RAINFALL,
    }
    assert catalog.by_reference("synthetic://hydrology/committed-sample") is not None
    assert catalog.by_reference("synthetic://nope") is None


def test_the_catalog_is_a_value_not_a_mutable_registry():
    catalog = committed_sample_catalog()
    extended = catalog.add(DatasetDescriptor(reference="synthetic://another-demo"))
    assert len(catalog.datasets) == 1
    assert len(extended.datasets) == 2


def test_duplicate_coverage_entries_are_refused():
    with pytest.raises(ValueError, match="duplicate domain coverage"):
        DatasetDescriptor(
            domains=(
                DomainCoverage(domain=DOMAIN_RAINFALL),
                DomainCoverage(domain=DOMAIN_RAINFALL),
            )
        )


def test_with_coverage_replaces_rather_than_appends():
    descriptor = DatasetDescriptor().with_coverage(
        DomainCoverage(domain=DOMAIN_DISCHARGE, status=COVERAGE_AVAILABLE, record_count=10)
    )
    assert len(descriptor.domains) == len(DATA_DOMAINS)
    assert descriptor.coverage_for(DOMAIN_DISCHARGE).status == COVERAGE_AVAILABLE
    assert descriptor.available_domains() == (DOMAIN_DISCHARGE,)


# --------------------------------------------------------------------------- #
# Honesty invariants
# --------------------------------------------------------------------------- #


def test_a_non_real_descriptor_always_carries_a_warning():
    """The one failure this module exists to make impossible."""
    synthetic = DatasetDescriptor(dataset_type=DATASET_TYPE_SYNTHETIC)
    assert synthetic.disclaimer == SYNTHETIC_DATA_DISCLAIMER
    unknown = DatasetDescriptor()
    assert unknown.dataset_type == "unknown"
    assert unknown.disclaimer is not None


def test_a_real_descriptor_must_not_carry_a_warning():
    """Real data may not be labelled synthetic, and the DB constraint requires NULL."""
    real = DatasetDescriptor(dataset_type=DATASET_TYPE_REAL)
    assert real.disclaimer is None
    assert real.may_be_presented_as_observation_data is True


def test_a_dataset_type_outside_the_vocabulary_is_refused():
    with pytest.raises(ValueError, match="dataset_type must be"):
        DatasetDescriptor(dataset_type="probably_real")


def test_a_blank_reference_becomes_none_not_an_empty_string():
    assert DatasetDescriptor(reference="   ").reference is None


def test_the_audit_rows_cover_every_non_presentable_dataset():
    rows = committed_sample_catalog().audit_rows()
    assert len(rows) == 1
    assert rows[0]["dataset_type"] == DATASET_TYPE_SYNTHETIC
    assert rows[0]["disclaimer"] == SYNTHETIC_DATA_DISCLAIMER
    assert "station_reference" in rows[0]["missing_fields"]


def test_the_descriptor_description_names_what_is_unknown():
    description = synthetic_sample_descriptor().describe()
    assert "UNKNOWN FIELDS" in description
    assert "station" in description


def test_the_coverage_status_vocabulary_is_exactly_three_values():
    assert COVERAGE_STATUSES == (COVERAGE_AVAILABLE, COVERAGE_ABSENT, COVERAGE_UNKNOWN)


# --------------------------------------------------------------------------- #
# Reuse, not duplication
# --------------------------------------------------------------------------- #


def test_the_provenance_record_remains_the_authority_for_dataset_facts():
    """A descriptor cannot claim a different checksum or licence than the model."""
    record = ProvenanceRecord(
        dataset_reference="synthetic://from-provenance",
        dataset_type=DATASET_TYPE_SYNTHETIC,
        dataset_checksum="f" * 64,
        dataset_license="none",
        station_reference="SYNTHETIC-STATION-0001",
    )
    descriptor = DatasetDescriptor().with_provenance(record)
    assert descriptor.reference == "synthetic://from-provenance"
    assert descriptor.checksum == "f" * 64
    assert descriptor.station_reference == "SYNTHETIC-STATION-0001"
    assert descriptor.disclaimer == record.disclaimer


def test_a_descriptor_built_from_config_leaves_coverage_unstated():
    """The configuration names a dataset; it does not describe the file's contents."""
    spec = DatasetSpec(
        path="data/synthetic_hydrology_sample.csv",
        timestamp_column="timestamp",
        station_reference="SYNTHETIC-STATION-0001",
        sampling_interval="1h",
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    descriptor = catalog_from_config(type("C", (), {"dataset": spec})())
    assert descriptor.dataset_type == DATASET_TYPE_SYNTHETIC
    assert descriptor.station_reference == "SYNTHETIC-STATION-0001"
    assert descriptor.available_domains() == ()
    assert set(descriptor.unknown_domains()) == set(DATA_DOMAINS)


def test_a_descriptor_from_config_is_still_not_presentable_as_real():
    spec = DatasetSpec(
        path="data/synthetic_hydrology_sample.csv",
        timestamp_column="timestamp",
        station_reference="SYNTHETIC-STATION-0001",
        sampling_interval="1h",
        dataset_type=DATASET_TYPE_SYNTHETIC,
    )
    descriptor = catalog_from_config(type("C", (), {"dataset": spec})())
    assert descriptor.may_be_presented_as_observation_data is False
    assert descriptor.disclaimer == SYNTHETIC_DATA_DISCLAIMER


def test_a_second_synthetic_dataset_is_not_invented():
    """One sample, one descriptor. A growing demo corpus is how fake data gets cited."""
    catalog = committed_sample_catalog()
    references = [descriptor.reference for descriptor in catalog.datasets]
    assert references == ["synthetic://hydrology/committed-sample"]
    assert len(references) == len(set(references))


def test_the_catalog_is_json_serialisable():
    payload = json.loads(json.dumps(committed_sample_catalog().to_dict()))
    assert payload["datasets"][0]["schema_version"] == SCHEMA_VERSION
    assert payload["datasets"][0]["may_be_presented_as_observation_data"] is False


def test_dataset_catalog_type_is_exported():
    assert DatasetCatalog().to_dict()["dataset_count"] == 0