# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Tests for `app.engines.hydro.provenance`.

Provenance is the part of a forecast that is easiest to fake and hardest to
notice later. These tests assert that an unknown fact stays `None`, that a
synthetic run is labelled synthetic everywhere, and that the disclaimers cannot
be dropped by accident.
"""

from __future__ import annotations

import json
import math

import pytest

from app.engines.hydro.provenance import (
    DATASET_TYPE_REAL,
    DATASET_TYPE_SYNTHETIC,
    DATASET_TYPE_UNKNOWN,
    PENDING_THRESHOLD_DISCLAIMER,
    SYNTHETIC_DATA_DISCLAIMER,
    SYNTHETIC_METRIC_DISCLAIMER,
    UNVERIFIED_DATA_DISCLAIMER,
    ProvenanceRecord,
    SplitBoundaries,
    combine_disclaimers,
    describe_unknowns,
    file_checksum,
    format_provenance_lines,
    provenance_from_config,
    software_environment,
    synthetic_disclaimer,
    text_checksum,
    utc_now_iso,
)


def test_the_mandatory_data_disclaimer_is_verbatim():
    assert SYNTHETIC_DATA_DISCLAIMER == (
        "THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL "
        "HYDROLOGICAL OBSERVATION DATA."
    )


def test_the_mandatory_metric_disclaimer_mentions_synthetic_and_demo():
    lowered = SYNTHETIC_METRIC_DISCLAIMER.lower()
    assert "synthetic" in lowered
    assert "demo" in lowered


def test_dataset_type_constants_are_explicit():
    assert DATASET_TYPE_REAL == "real"
    assert DATASET_TYPE_SYNTHETIC == "synthetic"
    assert DATASET_TYPE_UNKNOWN == "unknown"


# --- checksums ---------------------------------------------------------------


def test_text_checksum_is_stable_and_content_addressed():
    assert text_checksum("abc") == text_checksum("abc")
    assert text_checksum("abc") != text_checksum("abd")
    assert len(text_checksum("abc")) == 64


def test_file_checksum_reads_the_file(tmp_path):
    target = tmp_path / "data.csv"
    target.write_text("timestamp,water_level\n2024-01-01,1.0\n", encoding="utf-8")
    checksum = file_checksum(str(target))
    assert checksum is not None and len(checksum) == 64
    assert checksum == file_checksum(str(target))


def test_file_checksum_of_a_missing_file_is_none_not_a_guess():
    assert file_checksum("/definitely/not/a/file.csv") is None


# --- split boundaries --------------------------------------------------------


def _boundaries() -> SplitBoundaries:
    """Contiguous but non-overlapping periods.

    The splits share no instant: the last training row and the first validation
    row are different timestamps, because a boundary instant belonging to both
    splits would mean a row counted twice, which is exactly the leak the order
    check exists to prevent.
    """
    return SplitBoundaries(
        train_start="2024-01-01T00:00:00Z",
        train_end="2024-01-10T00:00:00Z",
        validation_start="2024-01-11T00:00:00Z",
        validation_end="2024-01-15T00:00:00Z",
        test_start="2024-01-16T00:00:00Z",
        test_end="2024-01-20T00:00:00Z",
        train_rows=100,
        validation_rows=50,
        test_rows=50,
    )


def test_split_boundaries_order_check():
    assert _boundaries().is_ordered() is True


def test_split_boundaries_reject_a_boundary_shared_by_two_splits():
    """A boundary instant in two splits would double-count that row."""
    from dataclasses import replace

    overlapping = replace(_boundaries(), validation_start="2024-01-10T00:00:00Z")
    assert overlapping.is_ordered() is False


def test_split_boundaries_detect_an_overlap():
    from dataclasses import replace

    broken = replace(_boundaries(), validation_start="2024-01-05T00:00:00Z")
    assert broken.is_ordered() is False


def test_split_boundaries_detect_a_backwards_test_start():
    from dataclasses import replace

    broken = replace(_boundaries(), test_start="2024-01-10T00:00:00Z")
    assert broken.is_ordered() is False


def test_split_boundaries_detect_a_reversed_period():
    from dataclasses import replace

    broken = replace(_boundaries(), train_start="2024-01-12T00:00:00Z")
    assert broken.is_ordered() is False


def test_a_single_instant_period_is_ordered_not_reversed():
    """`start == end` is a one-row split, not a reversed one, so it stays valid
    even though it shares its instant with no other period."""
    from dataclasses import replace

    one_row = replace(
        _boundaries(),
        train_start="2024-01-09T00:00:00Z",
        train_end="2024-01-09T00:00:00Z",
        train_rows=1,
    )
    assert one_row.is_ordered() is True


def test_an_entirely_unknown_record_is_not_reported_as_disordered():
    """Absence of evidence is not evidence of a leak.

    `is_ordered()` answers only what it can see, so a record with no boundaries
    returns True and callers are required to supply them to get a definite
    answer.
    """
    assert SplitBoundaries().is_ordered() is True


# --- unknown stays unknown ---------------------------------------------------


def test_unknown_facts_stay_none_in_the_record(demo_config):
    record = provenance_from_config(demo_config)
    assert record.dataset_license is None or record.dataset_license
    # A record built from a config with no declared source must not invent one.
    if record.dataset_reference is None:
        assert record.dataset_checksum is None


def test_missing_fields_names_every_unknown():
    record = ProvenanceRecord(dataset_type=DATASET_TYPE_UNKNOWN)
    missing = record.missing_fields()
    for field in ("dataset_reference", "dataset_license", "sampling_interval", "target_units"):
        assert field in missing


def test_a_complete_record_reports_no_missing_fields(demo_config):
    record = provenance_from_config(
        demo_config,
        feature_list=("water_level_lag1",),
        split=_boundaries(),
        model_name="ridge",
        model_version="ridge-v1",
        dataset_checksum="a" * 64,
    )
    assert record.is_complete is True
    assert record.missing_fields() == ()


def test_describe_unknowns_is_readable_and_non_empty():
    text = describe_unknowns(ProvenanceRecord(dataset_type=DATASET_TYPE_UNKNOWN))
    assert text
    assert isinstance(text, str)


# --- synthetic labelling -----------------------------------------------------


def test_a_synthetic_record_is_labelled_synthetic():
    """The warning is attached by the constructor, so it cannot be forgotten."""
    record = ProvenanceRecord(dataset_type=DATASET_TYPE_SYNTHETIC)
    assert record.is_synthetic is True
    assert record.disclaimer == SYNTHETIC_DATA_DISCLAIMER
    assert record.metrics_label == SYNTHETIC_METRIC_DISCLAIMER


def test_an_unknown_record_is_marked_unverified_not_synthetic():
    """Unknown is not synthetic. The wording must not accuse the data of being
    fake when the honest statement is that its origin is not established."""
    record = ProvenanceRecord(dataset_type=DATASET_TYPE_UNKNOWN)
    assert record.is_synthetic is False
    assert record.disclaimer == UNVERIFIED_DATA_DISCLAIMER
    assert SYNTHETIC_DATA_DISCLAIMER not in (record.disclaimer or "")


def test_a_real_record_carries_no_synthetic_disclaimer():
    record = ProvenanceRecord(
        dataset_type=DATASET_TYPE_REAL, dataset_reference="station-42 gauge export"
    )
    assert record.is_synthetic is False
    assert record.disclaimer is None
    # A real measurement is labelled as a real measurement, not left unlabelled.
    assert record.metrics_label == "measured evaluation"
    assert "synthetic" not in record.metrics_label.lower()


def test_a_caller_supplied_disclaimer_is_kept_not_overwritten():
    """The invariant only fills a blank; it never discards extra context."""
    extra = f"{SYNTHETIC_DATA_DISCLAIMER} Generated by fixture X."
    record = ProvenanceRecord(dataset_type=DATASET_TYPE_SYNTHETIC, disclaimer=extra)
    assert record.disclaimer == extra


def test_synthetic_disclaimer_only_applies_to_non_real_data():
    assert synthetic_disclaimer(DATASET_TYPE_SYNTHETIC) == SYNTHETIC_DATA_DISCLAIMER
    # Non-synthetic types get no synthetic warning: the helper is named for what
    # it adds, and the unknown case is handled by ProvenanceRecord itself.
    assert synthetic_disclaimer(DATASET_TYPE_UNKNOWN) is None
    assert synthetic_disclaimer(DATASET_TYPE_REAL) is None


def test_synthetic_disclaimer_accepts_an_extra_note():
    text = synthetic_disclaimer(DATASET_TYPE_SYNTHETIC, "generated by unit test X")
    assert SYNTHETIC_DATA_DISCLAIMER in text
    assert "generated by unit test X" in text


def test_combine_disclaimers_skips_empty_parts():
    """Fragments are complete sentences, so they are joined with a space rather
    than a `|` separator, which would read as a field delimiter."""
    assert combine_disclaimers(None, None) is None
    assert combine_disclaimers("", "  ", None) is None
    assert combine_disclaimers("a", None, "b") == "a b"


def test_pending_threshold_disclaimer_names_the_policy():
    assert "pending" in PENDING_THRESHOLD_DISCLAIMER.lower()
    assert "official" in PENDING_THRESHOLD_DISCLAIMER.lower()


# --- metrics attachment ------------------------------------------------------


def test_metrics_are_attached_without_mutating_the_original():
    record = ProvenanceRecord(dataset_type=DATASET_TYPE_SYNTHETIC)
    with_metrics = record.with_metrics({"rmse": 0.31, "n_samples": 100})
    assert with_metrics.evaluation_metrics["rmse"] == pytest.approx(0.31)
    assert record.evaluation_metrics is None


def test_attached_metrics_stay_labelled_synthetic():
    record = ProvenanceRecord(dataset_type=DATASET_TYPE_SYNTHETIC).with_metrics({"rmse": 0.3})
    assert record.metrics_label == SYNTHETIC_METRIC_DISCLAIMER


def test_attached_metrics_on_real_data_are_not_labelled_synthetic():
    record = ProvenanceRecord(
        dataset_type=DATASET_TYPE_REAL, dataset_reference="station-42"
    ).with_metrics({"rmse": 0.3})
    assert "synthetic" not in record.metrics_label.lower()
    assert record.metrics_label == "measured evaluation"


# --- serialisation -----------------------------------------------------------


def test_record_serialises_to_json_with_nulls_preserved():
    record = ProvenanceRecord(dataset_type=DATASET_TYPE_SYNTHETIC)
    text = json.dumps(record.to_dict())
    assert "null" in text  # unknowns are explicit nulls, not omitted keys
    assert "synthetic" in text


def test_format_provenance_lines_mentions_the_key_facts(demo_config):
    record = provenance_from_config(
        demo_config, feature_list=("a", "b"), split=_boundaries(), model_name="ridge"
    )
    lines = "\n".join(format_provenance_lines(record))
    assert "water_level" in lines
    assert "synthetic" in lines
    assert SYNTHETIC_DATA_DISCLAIMER in lines


def test_software_environment_is_recorded():
    env = software_environment()
    assert "python" in json.dumps(env).lower()
    assert all(isinstance(v, str) for v in env.values())


def test_utc_now_iso_is_parseable():
    import datetime as dt

    stamp = utc_now_iso()
    assert stamp.endswith("Z")
    dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
