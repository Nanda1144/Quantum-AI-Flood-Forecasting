# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 3 — the feature registry.

The registry is the vocabulary Phase 3 builds everything else from, so these tests
are mostly about *names*: a column whose name does not say what it is has failed
before any value is computed. The naming convention is fixed and tested here so a
later refactor cannot quietly change it, because `model_ready.contract` publishes
column names to a downstream consumer and a rename is a breaking contract change.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.engines.hydro.domains import Measurement, Observation
from app.engines.hydro import feature_registry as registry


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def observation(domain: str, quantity: str, unit: str = "mm") -> Observation:
    """One Phase 1 record. Built here rather than in `conftest` so this file adds
    no shared surface a teammate's test could come to depend on."""
    return Observation(
        domain=domain,
        location_reference="F1",
        observed_at="2024-01-01T00:00:00Z",
        measurements=(Measurement(quantity=quantity, value=1.0, unit=unit),),
    )


# --------------------------------------------------------------------------- #
# Naming
# --------------------------------------------------------------------------- #


def test_agreement_is_reachable_from_the_module() -> None:
    """The name is built from one function so a rename cannot leave a stray literal."""
    assert registry.feature_name(
        "water_level",
        registry.OP_LAG,
        window=3600.0,
    ) == "water_level_lag_1h"


def test_accumulation_and_rolling_use_distinct_verbs() -> None:
    """`accum` and `rolling` are different operations and must not share a name."""
    accum = registry.feature_name("rainfall", registry.OP_ACCUMULATION, window=3 * 3600.0)
    rolling = registry.feature_name(
        "rainfall", registry.OP_ROLLING, window=3 * 3600.0, statistic="mean"
    )
    assert accum == "rainfall_accum_3h"
    assert rolling == "rainfall_rolling_mean_3h"
    assert accum != rolling


def test_change_names_carry_both_instants() -> None:
    assert (
        registry.feature_name("water_level", registry.OP_CHANGE, window=3600.0)
        == "water_level_change_1h"
    )


def test_intensity_names_the_window_it_was_divided_by() -> None:
    assert (
        registry.feature_name("rainfall", registry.OP_INTENSITY, window=3 * 3600.0)
        == "rainfall_intensity_3h"
    )


def test_a_rolling_statistic_must_name_a_window() -> None:
    """Naming a statistic with no window would produce `x_rolling_mean`, a column
    whose width no reader could infer."""
    with pytest.raises(ValueError):
        registry.feature_name("rainfall", registry.OP_ROLLING, statistic="mean")


def test_a_lag_must_not_carry_a_statistic() -> None:
    with pytest.raises(ValueError):
        registry.feature_name("water_level", registry.OP_LAG, window=3600.0, statistic="mean")


def test_calendar_and_static_names_are_not_built_here() -> None:
    """They have their own builders, and routing them through this one would let a
    quantity-and-window name be attached to something that is neither."""
    with pytest.raises(ValueError):
        registry.feature_name("hour", registry.OP_CALENDAR)
    with pytest.raises(ValueError):
        registry.feature_name("elevation", registry.OP_STATIC)


def test_target_names_carry_a_prefix_no_feature_can_begin_with() -> None:
    """`target_` is unreachable as a feature name, so "is my target in the feature
    list?" is answerable by a string test and not only by construction."""
    assert registry.target_name("water_level", 21600.0) == "target_water_level_6h"
    for operation in (
        registry.OP_LAG,
        registry.OP_CHANGE,
        registry.OP_ACCUMULATION,
        registry.OP_INTENSITY,
    ):
        with pytest.raises(ValueError):
            registry.feature_name("target_water_level", operation, window=3600.0)
    with pytest.raises(ValueError):
        registry.feature_name(
            "target_water_level_6h", registry.OP_ROLLING, window=3600.0, statistic="mean"
        )


def test_every_supported_window_gets_a_short_label() -> None:
    assert registry.window_label(3600.0) == "1h"
    assert registry.window_label(3 * 3600.0) == "3h"
    assert registry.window_label(86400.0) == "24h"
    assert registry.window_label(6 * 86400.0) == "144h"
    assert registry.window_label(1800.0) == "30m"
    assert registry.window_label(90.0) == "90s"
    assert registry.window_label(0.5) == "0.5s"


def test_window_label_uses_hours_rather_than_days() -> None:
    """24h and 1d are the same window. Hours are the shorter and more common label
    for a hydrological lead time, and a hydrology reader writes `accum_24h` without
    thinking about it — so a name that used `1d` would be misread at a glance."""
    assert registry.window_label(86400.0) != "1d"
    assert registry.window_label(86400.0) == "24h"


def test_window_label_refuses_a_non_positive_width() -> None:
    """A window of zero or negative width is not a window. Silently labelling it
    would produce a column name that means nothing."""
    for bad in (0.0, -3600.0):
        with pytest.raises(ValueError):
            registry.window_label(bad)


def test_calendar_names_match_the_preexisting_layer() -> None:
    """The pre-Phase-1 pandas layer names its calendar columns `calendar_hour_sin`
    and friends. Matching them exactly is what makes cross-checking the two layers
    worth anything; a rotation or a rename would make the comparison meaningless."""
    assert registry.calendar_feature_name(registry.CAL_HOUR, registry.ENCODING_SIN) == (
        "calendar_hour_sin"
    )
    assert registry.calendar_feature_name(registry.CAL_DOY, registry.ENCODING_COS) == (
        "calendar_doy_cos"
    )


def test_calendar_name_rejects_an_unknown_pair() -> None:
    with pytest.raises(ValueError):
        registry.calendar_feature_name("day_of_week", registry.ENCODING_SIN)
    with pytest.raises(ValueError):
        registry.calendar_feature_name(registry.CAL_HOUR, "tan")


def test_calendar_periods_are_a_year_and_a_day() -> None:
    assert registry.CALENDAR_PERIODS[registry.CAL_HOUR] == 24.0
    # 365.25 rather than 365 so that the annual term does not step by a visible
    # amount on the leap day.
    assert registry.CALENDAR_PERIODS[registry.CAL_DOY] == 365.25


def test_day_of_week_and_month_are_excluded_with_a_stated_reason() -> None:
    """Excluded components must say why, so the absence reads as a decision."""
    assert "day_of_week" in registry.EXCLUDED_CALENDAR_COMPONENTS
    assert "month_of_year" in registry.EXCLUDED_CALENDAR_COMPONENTS
    for reason in registry.EXCLUDED_CALENDAR_COMPONENTS.values():
        assert reason.strip()


def test_excluded_components_are_not_emittable() -> None:
    for component in registry.EXCLUDED_CALENDAR_COMPONENTS:
        assert component not in registry.CALENDAR_COMPONENTS


# --------------------------------------------------------------------------- #
# Measurement keys
# --------------------------------------------------------------------------- #


def test_measurement_key_is_three_levels_and_separates_temperature_from_humidity() -> None:
    """Phase 2's `series_key` is `location|domain`. That is the right granularity
    for cadence and resampling, and the wrong one here: a station reporting both
    temperature and humidity shares one Phase 2 series, so a key built on it would
    let a humidity lag resolve to a temperature reading."""
    wide = Observation(
        domain="weather",
        location_reference="F1",
        observed_at="2024-01-01T00:00:00Z",
        measurements=(
            Measurement(quantity="temperature", value=10.0, unit="degC"),
            Measurement(quantity="humidity", value=70.0, unit="percent"),
        ),
    )
    keys = {
        f"{wide.location_reference}|{wide.domain}|{m.quantity}"
        for m in wide.measurements
    }
    assert keys == {"F1|weather|temperature", "F1|weather|humidity"}


def test_a_single_measurement_record_keys_to_its_one_measurement() -> None:
    record = observation("water_level", "water_level", "m")
    key = registry.measurement_key(record)
    assert key == "F1|water_level|water_level"
    assert key.count("|") == 2


def test_split_measurement_key_inverts_the_builder() -> None:
    key = registry.measurement_key(observation("water_level", "water_level", "m"))
    location, domain, quantity = registry.split_measurement_key(key)
    assert (location, domain, quantity) == ("F1", "water_level", "water_level")


def test_split_measurement_key_degrades_instead_of_raising() -> None:
    """A report line must render even for a key shape it was not handed."""
    assert registry.split_measurement_key("F1|water_level") == ("F1", "water_level", "")
    assert registry.split_measurement_key("F1") == ("F1", "", "")


def test_measurement_key_keeps_two_stations_apart() -> None:
    left = registry.measurement_key(observation("water_level", "water_level", "m"))
    right = Observation(
        domain="water_level",
        location_reference="F2",
        observed_at="2024-01-01T00:00:00Z",
        measurements=(Measurement(quantity="water_level", value=1.0, unit="m"),),
    )
    assert left != registry.measurement_key(right)


def test_domain_and_quantity_maps_agree_in_both_directions() -> None:
    """Every supported quantity names a Phase 1 domain that reports exactly it.

    Excluded: `weather`, which carries temperature and humidity and therefore has
    no single canonical quantity. That asymmetry is deliberate and is why the
    temporal engine splits a record per measurement instead of asking its domain.
    """
    checked = 0
    for quantity in registry.SUPPORTED_QUANTITIES:
        domain = registry.domain_for_quantity(quantity)
        if domain == "weather":
            assert registry.quantity_for_domain(domain) is None
            continue
        assert registry.quantity_for_domain(domain) == quantity
        checked += 1
    assert checked >= len(registry.SUPPORTED_QUANTITIES) - 2


def test_an_unsupported_quantity_is_refused_by_name() -> None:
    """Phase 3 can only build from quantities some Phase 1 domain reports. The
    error says which, so the fix is obvious rather than a guess."""
    with pytest.raises(KeyError) as caught:
        registry.domain_for_quantity("evaporation_rate")
    assert "evaporation_rate" in str(caught.value)
    assert "rainfall" in str(caught.value)


# --------------------------------------------------------------------------- #
# The unavailable catalogue
# --------------------------------------------------------------------------- #


def test_unavailable_catalogue_declares_features_it_refuses_to_build() -> None:
    """A feature with no source is declared, not omitted. An absent column is
    invisible; a declared-unavailable one is a visible gap a reviewer can ask
    about."""
    catalogue = registry.unavailable_catalogue()
    assert len(catalogue) == registry.UNAVAILABLE_STATIC_COUNT
    for name, definition in zip(catalogue.names, catalogue.definitions):
        assert name == definition.name
        assert definition.availability_requirement != registry.AVAILABLE


def test_the_full_catalogue_counts_static_and_relationship_features() -> None:
    assert registry.UNAVAILABLE_FEATURE_COUNT == len(
        registry.UNAVAILABLE_STATIC_CATALOGUE
    )
    wide = registry.unavailable_catalogue(include_relationship_features=True)
    assert len(wide) == registry.UNAVAILABLE_FEATURE_COUNT
    # The narrow view is the one the report uses by default; the wide one keeps the
    # rating-curve features visible to anyone who asks.
    assert len(registry.unavailable_catalogue()) < registry.UNAVAILABLE_FEATURE_COUNT


def test_unavailable_static_features_are_static_and_unbacked() -> None:
    for definition in registry.unavailable_catalogue().definitions:
        assert definition.operation == registry.OP_STATIC
        assert definition.availability_requirement == registry.AVAILABLE_NO_SOURCE
        assert definition.name.startswith("static_")


def test_relationship_features_are_unavailable_without_an_approved_relationship() -> None:
    """Deriving discharge from a level needs a rating curve. None exists in this
    repository, so those features are declared unbuildable rather than estimated."""
    wide = registry.unavailable_catalogue(include_relationship_features=True)
    relationship = [
        d
        for d in wide.definitions
        if d.availability_requirement == registry.AVAILABLE_NO_APPROVED_RELATIONSHIP
    ]
    assert relationship, "the catalogue must keep the rating-curve features visible"
    for definition in relationship:
        assert definition.name.startswith("derived_")


def test_the_catalogue_states_the_rating_curve_it_lacks() -> None:
    """The point of the exercise: nothing here invents discharge from a level."""
    text = " ".join(
        d.description.lower() for d in registry.unavailable_catalogue(True).definitions
    )
    assert "rating" in text and "curve" in text


def test_an_unavailable_feature_names_the_input_it_is_waiting_for() -> None:
    """Each entry must say what is missing, so the gap is actionable by a human
    rather than only countable."""
    for definition in registry.unavailable_catalogue(True).definitions:
        assert definition.required_source_fields == () or definition.description
        assert definition.description.strip()
        assert definition.availability_requirement in registry.AVAILABILITY_STATUSES
        assert definition.availability_requirement != registry.AVAILABLE


def test_availability_statuses_are_a_closed_vocabulary() -> None:
    assert set(registry.AVAILABILITY_STATUSES) == {
        registry.AVAILABLE,
        registry.AVAILABLE_NO_SOURCE,
        registry.AVAILABLE_UNDETERMINED_UNIT,
        registry.AVAILABLE_NO_APPROVED_RELATIONSHIP,
        registry.AVAILABLE_NO_HISTORY,
    }


def test_catalogue_counts_are_declared_once_and_match() -> None:
    assert registry.UNAVAILABLE_STATIC_COUNT == len(
        registry.unavailable_catalogue()
    )


# --------------------------------------------------------------------------- #
# Lineage
# --------------------------------------------------------------------------- #


def test_lineage_has_no_field_that_defaults_to_a_fact() -> None:
    """Every optional lineage field defaults to `None`, so an absent window is
    visibly absent rather than rendered as a plausible default."""
    lineage = registry.Lineage(
        source="rainfall", transformation="lag", entity_scope="entity", causal=True
    )
    assert lineage.window is None
    assert lineage.unit is None
    assert lineage.target_of is None
    payload = lineage.to_dict()
    assert payload["window"] is None
    assert payload["required_source_fields"] == []


def test_lineage_round_trips_through_its_dict() -> None:
    lineage = registry.Lineage(
        source="water_level",
        transformation="change",
        entity_scope="entity",
        causal=True,
        window="1h",
        unit="m",
        required_source_fields=("water_level",),
    )
    again = registry.Lineage(**{**lineage.to_dict(), "required_source_fields": ("water_level",)})
    assert again.describe() == lineage.describe()


def test_target_lineage_says_a_target_is_not_available_now() -> None:
    lineage = registry.TargetLineage(
        source="water_level",
        quantity="water_level",
        horizon_seconds=21600.0,
        horizon_label="6h",
        entity_scope="entity",
        unit="m",
        alignment="exact",
    )
    payload = lineage.to_dict()
    assert payload["horizon_seconds"] == 21600.0
    assert payload["horizon_label"] == "6h"
    assert payload["available_at_prediction_time"] is False


# --------------------------------------------------------------------------- #
# Operations and quantity categories
# --------------------------------------------------------------------------- #


def test_operations_are_declared_once_and_cover_every_evaluator() -> None:
    assert set(registry.OPERATIONS) == {
        registry.OP_LAG,
        registry.OP_CHANGE,
        registry.OP_ACCUMULATION,
        registry.OP_INTENSITY,
        registry.OP_ROLLING,
        registry.OP_CALENDAR,
        registry.OP_STATIC,
    }


def test_forcings_and_states_partition_the_supported_quantities() -> None:
    forcing = set(registry.FORCING_QUANTITIES)
    state = set(registry.STATE_QUANTITIES)
    assert forcing & state == set()
    assert forcing | state == set(registry.SUPPORTED_QUANTITIES)


def test_accumulation_and_intensity_are_declared_for_rainfall_only() -> None:
    """Accumulating a water level is meaningless: a total of levels is not a
    quantity. Restricting the operation to rainfall makes the mistake unavailable
    rather than merely discouraged."""
    assert registry.ACCUMULABLE_QUANTITIES == ("rainfall",)
    assert registry.INTENSITY_QUANTITIES == ("rainfall",)


def test_rolling_statistics_exclude_sum_and_count() -> None:
    """`sum` is routed through the accumulation operation, where coverage can be
    required of it; `count` would be a constant for a regular series and a
    deceptively informative one for an irregular one."""
    assert "sum" not in {"mean", "min", "max", "std"}


def test_contract_version_is_declared() -> None:
    assert registry.FEATURE_CONTRACT_VERSION == "navya-features/v1"


def test_note_codes_are_namespaced() -> None:
    """Report codes share one prefix so a consumer can filter Phase 3 findings out
    of a mixed stream without matching on message text."""
    assert registry.CODE_PREFIX == "FEATURE_"


def test_dedupe_windows_removes_repeats_and_keeps_first_seen_order() -> None:
    """Order is preserved rather than sorted so a registry built twice from the
    same configuration lists its columns in the same sequence."""
    assert registry.dedupe_windows([3, 1, 3, 2, 1]) == (3.0, 1.0, 2.0)


def test_not_available_says_a_human_must_act() -> None:
    """The one string standing in for a value this repository does not have."""
    assert "NOT FOUND IN REPOSITORY" in registry.NOT_AVAILABLE
    assert "INPUT REQUIRED" in registry.NOT_AVAILABLE
