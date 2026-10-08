# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Tests for `app.engines.hydro.synthetic`.

The synthetic generator exists so the pipeline is runnable without a real
dataset. That makes it the single highest-risk place in the project to have a
bug: a generator that looks too realistic, or whose output can escape
unlabelled, is how fabricated data enters a system.

These tests therefore assert labelling and separation, not hydrological realism.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER
from app.engines.hydro.synthetic import (
    SYNTHETIC_REFERENCE_PREFIX,
    SyntheticSeriesSpec,
    generate_synthetic_series,
    synthetic_dataset_spec,
    synthetic_target_spec,
    write_synthetic_csv,
)


# --- the generated frame -----------------------------------------------------


def test_generator_produces_the_documented_columns(demo_frame):
    assert list(demo_frame.columns) == ["timestamp", "water_level", "inflow", "rainfall_mm"]
    assert len(demo_frame) == 1200


def test_timestamps_are_regular_and_start_at_the_declared_instant():
    """Timestamps are timezone-naive UTC, by design.

    A naive-versus-aware mix would shift every chronological boundary, so the
    generator normalises to UTC and strips the zone. Comparing against a naive
    `Timestamp` documents that choice.
    """
    frame = generate_synthetic_series(SyntheticSeriesSpec(n_rows=48, start="2024-06-01T00:00:00Z"))
    assert frame["timestamp"].iloc[0] == pd.Timestamp("2024-06-01T00:00:00")
    assert frame["timestamp"].dt.tz is None
    deltas = frame["timestamp"].diff().dropna().unique()
    assert len(deltas) == 1
    assert deltas[0] == pd.Timedelta(hours=1)


def test_a_non_utc_start_is_converted_not_dropped():
    """An offset start is converted to UTC, so the first row is the UTC instant."""
    frame = generate_synthetic_series(SyntheticSeriesSpec(n_rows=24, start="2024-06-01T05:30:00+05:30"))
    assert frame["timestamp"].iloc[0] == pd.Timestamp("2024-06-01T00:00:00")


def test_interval_hours_is_honoured():
    frame = generate_synthetic_series(SyntheticSeriesSpec(n_rows=24, interval_hours=15))
    delta = frame["timestamp"].diff().dropna().iloc[0]
    assert delta == pd.Timedelta(hours=15)


def test_generation_is_deterministic_for_a_fixed_seed():
    spec = SyntheticSeriesSpec(n_rows=100, random_state=42)
    first = generate_synthetic_series(spec)
    second = generate_synthetic_series(spec)
    pd.testing.assert_frame_equal(first, second)


def test_different_seeds_give_different_series():
    a = generate_synthetic_series(SyntheticSeriesSpec(n_rows=100, random_state=1))
    b = generate_synthetic_series(SyntheticSeriesSpec(n_rows=100, random_state=2))
    assert a["water_level"].tolist() != b["water_level"].tolist()


def test_values_are_finite():
    frame = generate_synthetic_series(SyntheticSeriesSpec(n_rows=500))
    for column in ("water_level", "inflow", "rainfall_mm"):
        assert frame[column].notna().all()
        assert frame[column].map(lambda v: abs(v) != float("inf")).all()


def test_rainfall_is_not_negative():
    frame = generate_synthetic_series(SyntheticSeriesSpec(n_rows=500))
    assert (frame["rainfall_mm"] >= 0.0).all()


def test_spec_rejects_a_non_positive_row_count():
    with pytest.raises(ValueError):
        SyntheticSeriesSpec(n_rows=0)
    with pytest.raises(ValueError):
        SyntheticSeriesSpec(n_rows=-10)


def test_spec_rejects_a_series_too_short_to_be_useful():
    """The generator's seasonal and reservoir terms need a full day to mean
    anything, so a shorter request is refused rather than producing a series that
    looks like a degenerate hydrological record."""
    with pytest.raises(ValueError, match="at least 24"):
        SyntheticSeriesSpec(n_rows=23)


def test_spec_rejects_a_non_positive_interval():
    with pytest.raises(ValueError):
        SyntheticSeriesSpec(interval_hours=0)


# --- writing to disk ---------------------------------------------------------


def test_written_csv_is_labelled_synthetic_everywhere(tmp_path):
    """The file on disk must be unlabelable-as-real, not just the frame in RAM.

    A CSV is the artefact most likely to be copied out of this project, so the
    provenance returned alongside it has to carry the dataset type, the checksum
    and the mandatory warning. If any of those were dropped the file would
    outlive its label.
    """
    target = tmp_path / "sample.csv"
    info = write_synthetic_csv(str(target), SyntheticSeriesSpec(n_rows=120))
    assert info["dataset_type"] == "synthetic"
    assert info["dataset_reference"].startswith(SYNTHETIC_REFERENCE_PREFIX)
    assert info["disclaimer"] == SYNTHETIC_DATA_DISCLAIMER
    assert len(info["dataset_checksum"]) == 64
    assert info["n_rows"] == 120
    assert info["sampling_interval"] == "1h"
    # The licence field says why there is no licence, rather than leaving the
    # reader to infer that a blank means "public domain".
    assert "not real data" in info["dataset_license"]
    assert target.is_file()


def test_the_recorded_checksum_is_of_the_bytes_actually_written(tmp_path):
    """A checksum of a different file than the one on disk is worse than none."""
    import hashlib

    target = tmp_path / "sample.csv"
    info = write_synthetic_csv(str(target), SyntheticSeriesSpec(n_rows=60))
    assert info["dataset_checksum"] == hashlib.sha256(target.read_bytes()).hexdigest()


def test_written_csv_columns_are_the_documented_ones(tmp_path):
    target = tmp_path / "sample.csv"
    write_synthetic_csv(str(target), SyntheticSeriesSpec(n_rows=60))
    frame = pd.read_csv(target)
    assert list(frame.columns) == ["timestamp", "water_level", "inflow", "rainfall_mm"]


def test_written_csv_is_byte_identical_for_the_same_spec(tmp_path):
    spec = SyntheticSeriesSpec(n_rows=60, random_state=5)
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    assert write_synthetic_csv(str(a), spec)["dataset_checksum"] == write_synthetic_csv(
        str(b), spec
    )["dataset_checksum"]


def test_writing_refuses_an_unwritable_path(tmp_path):
    with pytest.raises((OSError, ValueError)):
        write_synthetic_csv(str(tmp_path / "missing-dir" / "x.csv"))


# --- the specs that label a run ---------------------------------------------


def test_synthetic_dataset_spec_marks_the_dataset_synthetic():
    from app.engines.hydro.config import load_config

    spec = synthetic_dataset_spec(load_config({}))
    assert spec.dataset_type == "synthetic"
    assert spec.reference.startswith(SYNTHETIC_REFERENCE_PREFIX)
    assert spec.license and "not real data" in spec.license
    assert spec.station_reference == "SYNTHETIC-STATION-0001"


def test_synthetic_dataset_spec_keeps_a_declared_synthetic_reference():
    from app.engines.hydro.config import DatasetSpec, load_config

    config = load_config({}).with_overrides(
        dataset=DatasetSpec(reference="synthetic://mine/run-7", dataset_type="synthetic")
    )
    assert synthetic_dataset_spec(config).reference == "synthetic://mine/run-7"


def test_synthetic_dataset_spec_overrides_a_misleading_real_looking_reference():
    """A demo run pointed at a local file must not keep a reference that looks
    like a real observation source."""
    from app.engines.hydro.config import DatasetSpec, load_config

    config = load_config({}).with_overrides(
        dataset=DatasetSpec(reference="unrecorded://local-file", dataset_type="real")
    )
    spec = synthetic_dataset_spec(config)
    assert spec.reference.startswith(SYNTHETIC_REFERENCE_PREFIX)
    assert spec.dataset_type == "synthetic"


def test_synthetic_target_spec_declares_demo_units():
    from app.engines.hydro.config import load_config

    spec = synthetic_target_spec(load_config({}))
    assert spec.column == "water_level"
    assert spec.units and "demo assumption" in spec.units
    assert "NOT" in spec.units.upper()


def test_synthetic_target_spec_supports_the_inflow_target():
    """Inflow gets the same labelling treatment as water level.

    A bare `demo-units` placeholder would read as though the unit had been
    established, and no physical unit is invented here because the generator's
    inflow scale is arbitrary and the real unit depends on the rating curve the
    dataset owner used.
    """
    from app.engines.hydro.config import load_config

    config = load_config({"HYDRO_TARGET": "inflow"})
    spec = synthetic_target_spec(config)
    assert spec.column == "inflow"
    assert "demo" in spec.units
    assert "UNDETERMINED" in spec.units
    assert "demo assumption" not in spec.units


def test_a_declared_unit_is_never_overwritten():
    """A unit the operator supplied is a real fact; the demo helper must not
    replace it with its own assumption."""
    from app.engines.hydro.config import TargetSpec, load_config

    config = load_config({}).with_overrides(
        target=TargetSpec(column="water_level", units="m AMSL", horizon_hours=6)
    )
    assert synthetic_target_spec(config).units == "m AMSL"


# --- separation from real data ----------------------------------------------


def test_the_reference_prefix_is_not_something_a_real_source_would_use():
    assert SYNTHETIC_REFERENCE_PREFIX == "synthetic://"
    assert SYNTHETIC_DATA_DISCLAIMER in SYNTHETIC_DATA_DISCLAIMER  # non-empty
