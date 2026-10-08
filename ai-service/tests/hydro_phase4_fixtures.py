# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Shared fixtures for the Phase 4 model-development tests.

Not a test module — a helper. Seven focused test files need the same small,
deterministic, unmistakably-synthetic dataset, and each of them rebuilding it
would mean seven subtly different fixtures, so a leak test could pass against one
dataset and fail against another for no reason anyone could find.

**Every value produced here is synthetic/demo data.** The series is a deterministic
ramp and a deterministic square wave, not a gauge record. `SYNTHETIC_DISCLAIMER` is
carried onto every dataset built here so it travels into provenance, manifests and
handoff results, and no test asserts a hydrological result — only that the pipeline
reports honestly about the numbers it computed.

The data is shaped, not tuned. A ramp plus a wave makes a wrong window, a wrong
horizon or a crossed split produce a *specific wrong number* that a human can read,
which is the point: a test that only says "assert something changed" passes for the
wrong reasons.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

import pytest

from app.engines.hydro.datasets import (
    DATASET_TYPE_SYNTHETIC,
    SYNTHETIC_DATA_DISCLAIMER,
    DatasetDescriptor,
)
from app.engines.hydro.domains import Measurement, Observation
from app.engines.hydro.feature_config import FeatureConfig
from app.engines.hydro.feature_pipeline import build_features
from app.engines.hydro.model_config import ModelConfig, deterministic_config
from app.engines.hydro.model_dataset import ModelDataset, assemble_dataset
from app.engines.hydro.model_training import default_configurations, train_models

UTC = dt.timezone.utc
EPOCH = dt.datetime(2024, 1, 1, tzinfo=UTC)
HOUR = 3600.0

#: The exact sentence Phase 1–4 use for synthetic data, kept in one place so a test
#: cannot quietly assert a *different* disclaimer than the pipeline emits.
SYNTHETIC_DISCLAIMER = (
    "THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL "
    "HYDROLOGICAL OBSERVATION DATA."
)

#: Two synthetic stations. Station isolation is asserted throughout Phase 4, so a
#: single-station fixture would make that class of test vacuous.
STATION_A = "SYNTHETIC-STATION-0001"
STATION_B = "SYNTHETIC-STATION-0002"

#: The three quantities Phase 3 builds features from. `inflow` carries an
#: explicitly-undetermined unit so unit handling is exercised rather than assumed.
QUANTITIES: tuple[tuple[str, str, str], ...] = (
    ("water_level", "water_level", "m"),
    ("inflow", "inflow", "UNDETERMINED (DEMO - no unit assigned)"),
    ("rainfall", "rainfall", "mm"),
)


def at(hours: float) -> dt.datetime:
    return EPOCH + dt.timedelta(hours=hours)


def _level(hour: float, station_offset: float) -> float:
    """A ramp plus a square wave, offset per station.

    Station B is shifted by a constant so a window that leaked across stations
    would read a level it could not legitimately have seen.
    """
    return (
        2.0
        + station_offset
        + hour * 0.01
        + (0.4 if int(hour) % 8 < 4 else 0.0)
        + 0.05 * math.sin(hour / 3.0)
    )


def _inflow(hour: float, station_offset: float) -> float:
    return 12.0 + station_offset + 0.8 * math.sin(hour / 5.0) + (2.0 if hour % 12 < 6 else 0.0)


def _rainfall(hour: float, station_offset: float) -> float:
    return float(int(hour * 7 + station_offset) % 5)


def _observations(hour: float, station: str, station_offset: float) -> tuple[Observation, ...]:
    """One `Observation` per quantity.

    The domain model restricts a record to quantities its domain accepts — a
    `water_level` record cannot carry rainfall — so three separate records are the
    honest shape rather than one record with three unrelated measurements.
    """
    stamp = at(hour).isoformat().replace("+00:00", "Z")
    values = {
        "water_level": _level(hour, station_offset),
        "inflow": _inflow(hour, station_offset),
        "rainfall": _rainfall(hour, station_offset),
    }
    return tuple(
        Observation(
            domain=domain,
            location_reference=station,
            observed_at=stamp,
            source_reference="synthetic://unit-test/phase4",
            measurements=(
                Measurement(quantity=quantity, value=values[quantity], unit=unit),
            ),
            dataset_type="synthetic",
        )
        for quantity, domain, unit in QUANTITIES
    )


@dataclass
class Phase2Result:
    """The Phase 2 output, in the shape Phase 3 reads.

    Duck-typed rather than imported, for the reason `test_hydro_feature_pipeline`
    gives: the boundary is tested from both sides, so a change to Phase 2's real
    result type cannot satisfy these tests by agreeing with itself.
    """

    train: tuple = ()
    validation: tuple = ()
    test: tuple = ()
    dataset: object = None


def synthetic_descriptor(station: str) -> DatasetDescriptor:
    """Describe this fixture honestly: synthetic, no license, not a measurement.

    Built rather than borrowed from `synthetic_sample_descriptor()` because that
    one reads the committed CSV and would describe *that* file's checksum while
    these rows are a different synthetic series. Attributing one dataset's
    checksum to another's rows is exactly the kind of provenance drift Phase 4
    exists to prevent.
    """
    return DatasetDescriptor(
        reference="synthetic://unit-test/phase4",
        dataset_type=DATASET_TYPE_SYNTHETIC,
        license="none - synthetic data has no license because it is not real data",
        checksum=None,
        sampling_interval="1h",
        station_reference=station,
        source_organisation=None,
        location_kind=None,
        domains=(),
        disclaimer=SYNTHETIC_DATA_DISCLAIMER,
        notes=(
            "SYNTHETIC/DEMO unit-test fixture: a deterministic ramp and square wave, "
            "not a gauge record. No hydrological result may be asserted from it."
        ),
    )


def phase2_sample(
    hours: int = 132,
    *,
    train_until: int = 84,
    valid_until: int = 108,
    stations: Sequence[str] = (STATION_A, STATION_B),
) -> Phase2Result:
    """`hours` hourly readings per station, split three ways chronologically.

    The split is by timestamp, not by row: every station's reading at an instant
    lands in the same split, which is what makes an entity-crossing split boundary
    detectable instead of invisible.
    """
    records: list[Observation] = []
    for index, station in enumerate(stations):
        for hour in range(hours):
            records.extend(_observations(float(hour), station, float(index) * 3.0))

    def part(lo: int, hi: int) -> tuple:
        return tuple(
            record
            for station in stations
            for record in records
            if record.location_reference == station and lo <= hour_of(record) < hi
        )

    return Phase2Result(
        train=part(0, train_until),
        validation=part(train_until, valid_until),
        test=part(valid_until, hours),
        dataset=synthetic_descriptor(stations[0]),
    )


def hour_of(observation: Observation) -> float:
    """Hours since `EPOCH`, so the chronological split can be expressed in integers."""
    stamp = dt.datetime.fromisoformat(observation.observed_at.replace("Z", "+00:00"))
    return (stamp - EPOCH).total_seconds() / HOUR


def feature_config(horizon_hours: float = 6.0) -> FeatureConfig:
    """Phase 3 configured for a 6-hour water-level forecast.

    Every value that would otherwise be inherited from a real gauge configuration
    is stated here, so a Phase 3 default change cannot quietly change what Phase 4
    is being tested against.
    """
    return replace(
        FeatureConfig(),
        quantities=("water_level", "inflow", "rainfall"),
        lag_hours=(1, 3, 6),
        rolling_hours=(3, 6),
        rolling_statistics=("mean", "max"),
        target_quantity="water_level",
        target_hours=(horizon_hours,),
    )


# --------------------------------------------------------------------------- #
# Built objects, cached at module scope
# --------------------------------------------------------------------------- #


def build_feature_result(hours: int = 132, **kwargs: Any):
    """The real Phase 3 output for `phase2_sample`.

    The descriptor is passed explicitly. Phase 3 would otherwise look for it on
    the Phase 2 *report*, which the duck-typed stand-in does not carry, and would
    fall back to labelling every row `UNVERIFIED` — true enough, but it would make
    these fixtures exercise the unknown-source path instead of the synthetic one
    that is what they actually are.
    """
    sample = phase2_sample(hours, **kwargs)
    return build_features(sample, feature_config(), dataset=sample.dataset)


@pytest.fixture(scope="module")
def feature_result():
    return build_feature_result()


@pytest.fixture(scope="module")
def feature_dataset(feature_result):
    return feature_result.dataset


@pytest.fixture(scope="module")
def single_entity_dataset():
    """One station only.

    Some tests need the *absence* of a second entity: the sequence-causality check
    and the cross-entity checks are clearer when a window provably has nowhere else
    to have come from.
    """
    single = phase2_sample(stations=(STATION_A,))
    return build_features(single, feature_config(), dataset=single.dataset).dataset


def assemble(dataset_like, family: str, **changes: Any) -> ModelDataset:
    """The Phase 4 matrices for `dataset_like`, reading cadences from its report."""
    config = config_for(family, **changes)
    return assemble_dataset(
        dataset_like, config, cadences=_cadences_of(dataset_like)
    )


def _cadences_of(dataset_like) -> Mapping[str, Any] | None:
    """Phase 3's cadence map, whether the caller passed a `FeatureResult` or a bare
    `FeatureDataset`.

    `assemble_dataset` accepts either. Accepting both here keeps the tests from
    having to care which one a fixture happens to hand them.
    """
    report = getattr(dataset_like, "report", None)
    if report is not None:
        return report.cadence
    return getattr(dataset_like, "cadences", None)


@pytest.fixture(scope="module")
def model_dataset(feature_result):
    """The Phase 4 matrix set assembled from the real Phase 3 dataset."""
    return assemble(feature_result, "random_forest")


@pytest.fixture(scope="module")
def naive_dataset(feature_result):
    """The same assembly under the baseline's configuration."""
    return assemble(feature_result, "naive")


@pytest.fixture(scope="module")
def lstm_dataset():
    """The short-series assembly, under a sequence family's configuration."""
    return assemble(build_sequence_result(), "lstm", lookback=SEQUENCE_LOOKBACK,
                    scaler_policy="standard")


# --------------------------------------------------------------------------- #
# A longer series, for sequence models
# --------------------------------------------------------------------------- #

#: The default lookback is 24 hourly rows. A 48-row evaluation split shared across
#: two stations leaves each entity 24 rows, of which the last 6 are withheld because
#: their target crosses the split boundary — so a lookback-24 window has nowhere to
#: end. The sequence fixtures therefore use a longer series *and* a shorter lookback,
#: so a window genuinely exists in every split and the audit has something to check.
SEQUENCE_HOURS = 360
SEQUENCE_TRAIN_UNTIL = 240
SEQUENCE_VALID_UNTIL = 300
SEQUENCE_LOOKBACK = 6


def build_sequence_result():
    """A longer synthetic series, enough history for windows in every split."""
    return build_feature_result(
        SEQUENCE_HOURS,
        train_until=SEQUENCE_TRAIN_UNTIL,
        valid_until=SEQUENCE_VALID_UNTIL,
    )


@pytest.fixture(scope="module")
def sequence_result():
    return build_sequence_result()


@pytest.fixture(scope="module")
def sequence_dataset():
    """`ModelDataset` for a sequence family, with windows possible in every split."""
    return assemble(
        build_sequence_result(),
        "lstm",
        lookback=SEQUENCE_LOOKBACK,
        scaler_policy="standard",
    )


def step_seconds(dataset: ModelDataset) -> float:
    """The cadence Phase 3 reported for the fixture's target quantity."""
    from app.engines.hydro.model_dataset import resolve_step_seconds

    resolved = resolve_step_seconds(
        dataset.cadences, dataset.entities, dataset.binding.quantity
    )
    assert resolved is not None, "the fixture reports no cadence for its target quantity"
    return resolved


def config_for(family: str, **changes: Any) -> ModelConfig:
    """A configuration for `family` bound to the fixture target and horizon.

    `changes` wins over the defaults, so a caller can ask for a horizon Phase 3 never
    built without a separate helper. The fixture's 6-hour horizon is the default
    because that is the one `feature_config()` gives Phase 3.
    """
    settings: dict[str, Any] = {"target_quantity": "water_level", "horizon_hours": (6.0,)}
    settings.update(changes)
    return deterministic_config(family, **settings)


def configs_for(*families: str, **shared: Any) -> tuple[ModelConfig, ...]:
    return tuple(config_for(family, **shared) for family in families)


@pytest.fixture(scope="module")
def trained_result():
    """One real `train_models` run over every family the registry declares."""
    result = build_feature_result()
    return train_models(
        result.dataset,
        default_configurations(),
        cadences=result.report.cadence,
    )


@pytest.fixture(scope="module")
def trained_pair():
    """A minimal run: baseline plus random forest, nothing dependency-blocked.

    Metrics tests should not have to reason about which families happened to be
    installable on the machine running them.
    """
    result = build_feature_result()
    configs = configs_for("naive", "random_forest", scaler_policy="standard")
    return train_models(result.dataset, configs, cadences=result.report.cadence)


def dataset_of(result: Any, family: str) -> ModelDataset:
    """The `ModelDataset` behind one family in a run, or `None`."""
    for target, dataset in result.datasets.items():
        if dataset.config.model_family == family:
            return dataset
    return None


def config_of(result: Any, family: str) -> ModelConfig:
    for dataset in result.datasets.values():
        if dataset.config.model_family == family:
            return dataset.config
    raise KeyError(f"no dataset for family {family!r}")


def rows_of(dataset: ModelDataset, split: str) -> Mapping[str, Any]:
    return dataset.splits[split]


__all__ = [
    "EPOCH",
    "HOUR",
    "SEQUENCE_LOOKBACK",
    "Phase2Result",
    "QUANTITIES",
    "STATION_A",
    "STATION_B",
    "SYNTHETIC_DISCLAIMER",
    "UTC",
    "at",
    "build_feature_result",
    "build_sequence_result",
    "config_for",
    "configs_for",
    "config_of",
    "dataset_of",
    "feature_config",
    "hour_of",
    "phase2_sample",
    "rows_of",
    "step_seconds",
    "synthetic_descriptor",
]