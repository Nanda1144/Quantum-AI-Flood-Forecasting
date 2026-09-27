# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Tests for `app.engines.hydro.config`.

The point of these tests is the *honesty contract* of the configuration layer:

* no default flood threshold exists,
* no default dataset provenance exists,
* malformed configuration raises instead of silently falling back,
* the target is genuinely configurable between water level and inflow.
"""

from __future__ import annotations

import pytest

from app.engines.hydro.config import (
    DEFAULT_RISK_BAND_LABELS,
    DatasetSpec,
    FeatureSpec,
    HydroConfig,
    RiskPolicy,
    SplitSpec,
    TargetSpec,
    load_config,
)


# --- defaults are honest absences, not plausible guesses --------------------


def test_no_default_flood_threshold():
    policy = RiskPolicy()
    assert policy.flood_threshold is None
    assert policy.threshold_source is None
    assert policy.policy_status == "pending"
    assert policy.band_edges == ()
    assert policy.is_usable is False


def test_risk_policy_describe_states_pending():
    policy = RiskPolicy()
    assert "pending" in policy.describe()
    assert "no official flood stage" in policy.describe()


def test_default_risk_band_labels_are_labels_only():
    # The four band names exist so the platform vocabulary is available, but no
    # numeric edge is defined, so no band can be assigned.
    assert DEFAULT_RISK_BAND_LABELS == ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert RiskPolicy().band_labels == DEFAULT_RISK_BAND_LABELS
    assert RiskPolicy().band_edges == ()


def test_no_default_dataset_provenance():
    dataset = DatasetSpec()
    assert dataset.path is None
    assert dataset.reference is None
    assert dataset.license is None
    assert dataset.sampling_interval is None
    assert dataset.station_reference is None
    assert dataset.dataset_type == "unknown"
    assert dataset.missing_fields() == (
        "path",
        "reference",
        "license",
        "sampling_interval",
        "station_reference",
    )


def test_default_target_units_are_unknown_not_guessed():
    target = TargetSpec()
    assert target.column == "water_level"
    assert target.units is None
    assert "units unknown" in target.describe()


# --- readiness / advisories separation --------------------------------------


def test_unusable_risk_policy_blocks_serving():
    config = HydroConfig(
        dataset=DatasetSpec(path="x.csv", reference="r", license="l", station_reference="s"),
        target=TargetSpec(column="water_level", units="m"),
    )
    blockers = config.readiness()
    assert any("flood threshold" in blocker for blocker in blockers)
    assert config.is_ready() is False


def test_configured_but_unapproved_threshold_does_not_block():
    config = HydroConfig(
        dataset=DatasetSpec(path="x.csv", reference="r", license="l", station_reference="s"),
        target=TargetSpec(column="water_level", units="m"),
        risk=RiskPolicy(flood_threshold=5.0, threshold_source="doc", band_edges=(0.5,)),
    )
    # Serving is possible: the engine reports status="pending" and labels the
    # bands as configured rather than official. That is honest, so it must not
    # be reported as a blocker.
    assert config.readiness() == ()
    assert config.is_ready() is True
    assert any("PENDING approval" in note for note in config.advisories())


def test_advisories_flag_non_real_dataset_type():
    config = HydroConfig(
        dataset=DatasetSpec(path="x.csv", reference="r", license="l", station_reference="s"),
        target=TargetSpec(column="water_level", units="m"),
    )
    assert any("dataset_type is 'unknown'" in note for note in config.advisories())


# --- validation failures -----------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"train_fraction": 0.0},
        {"train_fraction": 1.0},
        {"validation_fraction": 0.0},
        {"train_fraction": 0.8, "validation_fraction": 0.3},
    ],
)
def test_invalid_split_fractions_are_rejected(kwargs):
    with pytest.raises(ValueError):
        SplitSpec(**kwargs)


def test_test_split_is_the_remainder():
    split = SplitSpec(train_fraction=0.6, validation_fraction=0.2)
    assert split.test_fraction == pytest.approx(0.2)


def test_invalid_horizon_is_rejected():
    with pytest.raises(ValueError):
        TargetSpec(column="water_level", units="m", horizon_hours=0)


def test_invalid_lag_and_window_are_rejected():
    with pytest.raises(ValueError):
        FeatureSpec(max_lag=0)
    with pytest.raises(ValueError):
        FeatureSpec(rolling_windows=(1,))
    with pytest.raises(ValueError):
        FeatureSpec(rolling_windows=(3, 3))


def test_blank_contract_version_is_rejected():
    with pytest.raises(ValueError):
        HydroConfig(contract_version="   ")


def test_blank_model_id_is_rejected():
    with pytest.raises(ValueError):
        HydroConfig(model_id="")


# --- environment parsing -----------------------------------------------------


def test_load_config_with_empty_env_is_all_unknown():
    config = load_config({})
    assert config.dataset.path is None
    assert config.target.units is None
    assert config.risk.flood_threshold is None
    assert config.risk.band_edges == ()
    assert config.is_ready() is False


def test_load_config_reads_target_and_units():
    config = load_config({"HYDRO_TARGET": "inflow", "HYDRO_TARGET_UNITS": "m3/s"})
    assert config.target.column == "inflow"
    assert config.target.units == "m3/s"
    assert "inflow (m3/s)" == config.target.describe()


def test_load_config_parses_csv_lists():
    config = load_config(
        {
            "HYDRO_EXOGENOUS_COLUMNS": "upstream_level, gate_position",
            "HYDRO_ROLLING_WINDOWS": "4,8,16",
            "HYDRO_RISK_BANDS": "0.2,0.5,0.8",
            "HYDRO_ID_COLUMNS": "station",
        }
    )
    assert config.features.exogenous_columns == ("upstream_level", "gate_position")
    assert config.features.rolling_windows == (4, 8, 16)
    assert config.risk.band_edges == (0.2, 0.5, 0.8)
    assert config.dataset.id_columns == ("station",)


def test_load_config_rejects_non_numeric_numbers():
    with pytest.raises(ValueError):
        load_config({"HYDRO_RIDGE_ALPHA": "not-a-number"})
    with pytest.raises(ValueError):
        load_config({"HYDRO_FORECAST_HORIZON_HOURS": "six"})


def test_load_config_rejects_non_finite_numbers():
    with pytest.raises(ValueError):
        load_config({"HYDRO_RIDGE_ALPHA": "nan"})
    with pytest.raises(ValueError):
        load_config({"HYDRO_FLOOD_THRESHOLD": "inf"})


def test_load_config_rejects_unknown_enum_values():
    with pytest.raises(ValueError):
        load_config({"HYDRO_MISSING_POLICY": "impute-with-vibes"})
    with pytest.raises(ValueError):
        load_config({"HYDRO_SCALER": "minmax"})
    with pytest.raises(ValueError):
        load_config({"HYDRO_DATASET_TYPE": "probably-real"})
    with pytest.raises(ValueError):
        load_config({"HYDRO_ENABLED": "yes"})


def test_load_config_rejects_malformed_csv_numbers():
    with pytest.raises(ValueError):
        load_config({"HYDRO_ROLLING_WINDOWS": "3,six"})
    with pytest.raises(ValueError):
        load_config({"HYDRO_RISK_BANDS": "0.2,banana"})


def test_load_config_blank_values_are_treated_as_absent():
    # An operator exporting an empty shell variable must not turn "" into a
    # dataset path or a threshold of zero.
    config = load_config(
        {
            "HYDRO_DATASET_PATH": "   ",
            "HYDRO_FLOOD_THRESHOLD": "",
            "HYDRO_TARGET_UNITS": "  ",
        }
    )
    assert config.dataset.path is None
    assert config.risk.flood_threshold is None
    assert config.target.units is None


def test_load_config_reads_model_id():
    assert load_config({}).model_id == "NAVYA-HYDRO-001"
    assert load_config({"HYDRO_MODEL_ID": "HYDRO-B"}).model_id == "HYDRO-B"


def test_with_overrides_returns_a_new_config():
    original = load_config({})
    changed = original.with_overrides(model_name="linear")
    assert original.model_name == "ridge"
    assert changed.model_name == "linear"
    assert changed is not original
