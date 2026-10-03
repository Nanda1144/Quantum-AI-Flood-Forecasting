# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 3 — the feature configuration.

A configuration is the only place a Phase 3 policy is chosen, so these tests are
about two things: that every knob defaults to the conservative choice, and that
the closed vocabularies actually refuse anything outside themselves. A policy that
accepts a typo silently is worse than no policy at all, because the report will
describe a run that never happened.
"""

from __future__ import annotations

import pytest

from app.engines.hydro import feature_registry as registry
from app.engines.hydro.feature_config import (
    CUTOFF_AT_PREDICTION,
    CUTOFF_ONE_STEP_BACK,
    CUTOFFS,
    MISSING_DROP_ROWS,
    MISSING_ERROR,
    MISSING_POLICIES,
    MISSING_RETAIN,
    ROLLING_STATISTICS,
    STATISTICS_NEEDING_TWO,
    STAT_MAX,
    STAT_MEAN,
    STAT_MIN,
    STAT_STD,
    STRICTNESS_MODES,
    STRICTNESS_PERMISSIVE,
    STRICTNESS_STRICT,
    TARGET_ALIGNMENTS,
    TARGET_AT_OR_BEFORE,
    TARGET_EXACT,
    UNIT_FLAG_UNDETERMINED,
    UNIT_POLICIES,
    UNIT_REQUIRE_KNOWN,
    WARMUP_DROP_ROWS,
    WARMUP_ERROR,
    WARMUP_POLICIES,
    WARMUP_RETAIN,
    FeatureConfig,
    FeatureConfigError,
    build_registry,
    conservative_config,
    strict_config,
)


# --------------------------------------------------------------------------- #
# Defaults are the conservative choice
# --------------------------------------------------------------------------- #


def test_the_default_configuration_is_the_conservative_one() -> None:
    """Calling `build_features` with no configuration must be the safe path. The
    defaults below are therefore not conveniences; they are the guarantee."""
    config = FeatureConfig()
    assert config == conservative_config()
    assert config.strictness == STRICTNESS_PERMISSIVE


def test_missing_and_warmup_values_are_retained_never_dropped_silently() -> None:
    """Deleting rows is the one irreversible thing this package does, so it is
    never the default. Both policies default to keeping the row and recording why
    a value is absent."""
    config = FeatureConfig()
    assert config.missing_policy == MISSING_RETAIN
    assert config.warmup_policy == WARMUP_RETAIN
    assert MISSING_DROP_ROWS in MISSING_POLICIES and MISSING_ERROR in MISSING_POLICIES
    assert WARMUP_DROP_ROWS in WARMUP_POLICIES and WARMUP_ERROR in WARMUP_POLICIES


def test_an_accumulation_must_cover_its_whole_window() -> None:
    """A partial sum is smaller than the truth and still looks like a total, so
    full coverage is required by default for accumulation and intensity."""
    assert FeatureConfig().accumulation_min_coverage == 1.0


def test_a_rolling_mean_may_use_what_was_observed() -> None:
    """The opposite default, on purpose. A mean over the readings that exist is
    exactly what it says it is; refusing it would throw away usable information
    over a hole that is already visible in the data."""
    assert FeatureConfig().rolling_min_coverage == 0.0


def test_state_features_never_read_the_prediction_instant() -> None:
    """Water level at `T` is the thing being predicted. A feature on it that reads
    `T` is the answer wearing a feature's name."""
    assert FeatureConfig().state_cutoff == CUTOFF_ONE_STEP_BACK


def test_forcing_features_may_read_the_prediction_instant_by_default() -> None:
    """Rainfall at `T` is observed, not predicted, so a forcing may use it. It is
    still opt-out — `strict_causality` moves it to one-step-back — but the default
    reflects the physical fact rather than the cautious one."""
    assert FeatureConfig().forcing_cutoff == CUTOFF_AT_PREDICTION


def test_strict_causality_collapses_both_cutoffs_to_one_step_back() -> None:
    """One knob, one meaning: no feature anywhere may read the prediction instant.
    Convenient because it is the property an auditor actually wants to check."""
    config = FeatureConfig(strict_causality=True)
    assert config.cutoff_for("rainfall") == CUTOFF_ONE_STEP_BACK
    assert config.cutoff_for("water_level") == CUTOFF_ONE_STEP_BACK


def test_an_undetermined_unit_is_flagged_by_default_not_used_as_a_rate() -> None:
    """`flag_undetermined` still computes values that are pure arithmetic on the
    raw numbers, and leaves every unit-dependent operation absent."""
    assert FeatureConfig().unit_policy == UNIT_FLAG_UNDETERMINED


def test_targets_are_aligned_exactly_by_default() -> None:
    """`at_or_before` accepts a reading from the wrong instant, and is only
    defensible with an explicit tolerance the caller has thought about."""
    assert FeatureConfig().target_alignment == TARGET_EXACT
    assert FeatureConfig().target_tolerance_seconds is None


def test_the_default_horizon_matches_the_engines_existing_forecast_horizon() -> None:
    """The engine already issues 6-hour forecasts. Defaulting the feature target to
    a different lead time would build a dataset for a problem nobody is asking."""
    assert FeatureConfig().target_hours == (6.0,)
    assert FeatureConfig().target_quantity == "water_level"


# --------------------------------------------------------------------------- #
# Strictness
# --------------------------------------------------------------------------- #


def test_strict_config_promotes_the_permissive_defaults() -> None:
    """`strictness='strict'` alone is enough — a caller should not have to know
    which five knobs move in order to be careful."""
    config = strict_config()
    assert config.strictness == STRICTNESS_STRICT
    assert config.forcing_cutoff == CUTOFF_ONE_STEP_BACK
    assert config.unit_policy == UNIT_REQUIRE_KNOWN
    assert config.strict_causality is True
    assert config.state_cutoff == CUTOFF_ONE_STEP_BACK
    assert config.target_alignment == TARGET_EXACT
    assert config.accumulation_min_coverage == 1.0
    assert config.missing_policy == MISSING_RETAIN
    assert config.warmup_policy == WARMUP_RETAIN


def test_strictness_alone_is_enough_to_promote() -> None:
    assert FeatureConfig(strictness=STRICTNESS_STRICT) == strict_config()


def test_strictness_refuses_a_deliberate_relaxation() -> None:
    """The reachable relaxations are the ones that destroy information: dropping
    rows instead of retaining them, and letting an accumulation sum over a window
    it did not fully observe. Both must be asked for out loud or not at all —
    a strict run that quietly lost 40% of its origins would report a policy it
    never applied."""
    with pytest.raises(FeatureConfigError) as caught:
        FeatureConfig(strictness=STRICTNESS_STRICT, missing_policy=MISSING_DROP_ROWS)
    assert "missing_policy" in str(caught.value)
    assert "retain" in str(caught.value)

    with pytest.raises(FeatureConfigError) as caught:
        FeatureConfig(strictness=STRICTNESS_STRICT, accumulation_min_coverage=0.5)
    assert "accumulation_min_coverage" in str(caught.value)

    with pytest.raises(FeatureConfigError) as caught:
        FeatureConfig(strictness=STRICTNESS_STRICT, warmup_policy=WARMUP_DROP_ROWS)
    assert "warmup_policy" in str(caught.value)


def test_strictness_promotes_a_narrowing_rather_than_refusing_it() -> None:
    """`unit_policy` and `forcing_cutoff` each have exactly two values, so under
    strictness the permissive one *is* the default and gets promoted silently
    rather than refused. A caller who asks for strict and names the permissive
    word has still asked for strict, so raising would be pedantry."""
    config = FeatureConfig(
        strictness=STRICTNESS_STRICT,
        unit_policy=UNIT_FLAG_UNDETERMINED,
        forcing_cutoff=CUTOFF_AT_PREDICTION,
    )
    assert config.unit_policy == UNIT_REQUIRE_KNOWN
    assert config.forcing_cutoff == CUTOFF_ONE_STEP_BACK
    assert config.strict_causality is True


def test_a_relaxation_is_fine_under_permissive_strictness() -> None:
    """Only the strict mode refuses. Naming the policy explicitly must work."""
    config = FeatureConfig(
        strictness=STRICTNESS_PERMISSIVE,
        unit_policy=UNIT_FLAG_UNDETERMINED,
        forcing_cutoff=CUTOFF_AT_PREDICTION,
    )
    assert config.unit_policy == UNIT_FLAG_UNDETERMINED


def test_strict_causality_does_not_conflict_with_strictness() -> None:
    """`strict_causality=True` moves the forcing cutoff the same way strictness
    would, so asking for both is a narrowing, not a contradiction."""
    config = FeatureConfig(strictness=STRICTNESS_STRICT, strict_causality=True)
    assert config.forcing_cutoff == CUTOFF_ONE_STEP_BACK


# --------------------------------------------------------------------------- #
# Closed vocabularies
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "field,bad",
    [
        ("lag_hours", (0.0,)),
        ("lag_hours", (-1.0,)),
        ("rolling_hours", (0.0,)),
        ("accumulation_hours", (-3.0,)),
        ("intensity_hours", (0.0,)),
        ("change_hours", (0.0,)),
        ("target_hours", (0.0,)),
    ],
)
def test_a_window_of_no_length_is_refused(field: str, bad: tuple[float, ...]) -> None:
    """A zero-width window is not a window. Accepting one would emit a column named
    `x_lag_0h` whose value is the reading at the origin."""
    with pytest.raises(FeatureConfigError):
        FeatureConfig(**{field: bad})


@pytest.mark.parametrize(
    "field,bad",
    [
        ("state_cutoff", "whenever"),
        ("forcing_cutoff", "at_the_end"),
        ("missing_policy", "delete"),
        ("warmup_policy", "delete"),
        ("unit_policy", "assume_metres"),
        ("target_alignment", "nearest"),
        ("strictness", "paranoid"),
        ("rolling_statistics", ("p95",)),
    ],
)
def test_an_unknown_policy_word_is_refused(field: str, bad: object) -> None:
    """These are closed vocabularies. A typo must raise, because a run configured
    with `missing_policy='delete'` would otherwise report a policy it never applied."""
    with pytest.raises(FeatureConfigError):
        FeatureConfig(**{field: bad})


def test_a_policy_vocabulary_is_a_closed_set() -> None:
    assert set(CUTOFFS) == {CUTOFF_AT_PREDICTION, CUTOFF_ONE_STEP_BACK}
    assert set(MISSING_POLICIES) == {MISSING_RETAIN, MISSING_DROP_ROWS, MISSING_ERROR}
    assert set(WARMUP_POLICIES) == {WARMUP_RETAIN, WARMUP_DROP_ROWS, WARMUP_ERROR}
    assert set(UNIT_POLICIES) == {UNIT_FLAG_UNDETERMINED, UNIT_REQUIRE_KNOWN}
    assert set(TARGET_ALIGNMENTS) == {TARGET_EXACT, TARGET_AT_OR_BEFORE}
    assert set(STRICTNESS_MODES) == {STRICTNESS_PERMISSIVE, STRICTNESS_STRICT}


def test_an_unknown_quantity_is_refused_by_name() -> None:
    with pytest.raises(FeatureConfigError) as caught:
        FeatureConfig(quantities=("rainfall", "soil_moisture"))
    assert "soil_moisture" in str(caught.value)


def test_an_unknown_calendar_component_is_refused() -> None:
    """A calendar component that is not emitted by the registry must not be
    configurable, or the configuration would promise a column that never appears."""
    with pytest.raises(FeatureConfigError):
        FeatureConfig(calendar_components=("day_of_week",))


def test_a_quantitative_tolerance_requires_the_loose_alignment() -> None:
    """`exact` alignment ignores a tolerance entirely, so accepting one there would
    be a setting that reads as if it did something and does not."""
    with pytest.raises(FeatureConfigError) as caught:
        FeatureConfig(target_alignment=TARGET_EXACT, target_tolerance_seconds=1800.0)
    assert "tolerance" in str(caught.value).lower()


def test_a_tolerance_must_be_positive() -> None:
    with pytest.raises(FeatureConfigError):
        FeatureConfig(
            target_alignment=TARGET_AT_OR_BEFORE, target_tolerance_seconds=0.0
        )


def test_coverage_fractions_must_lie_between_zero_and_one() -> None:
    for field in ("accumulation_min_coverage", "rolling_min_coverage"):
        for bad in (-0.1, 1.1):
            with pytest.raises(FeatureConfigError):
                FeatureConfig(**{field: bad})


# --------------------------------------------------------------------------- #
# Derived properties
# --------------------------------------------------------------------------- #


def test_window_hours_become_seconds_without_duplicates() -> None:
    config = FeatureConfig(lag_hours=(1.0, 1.0, 3.0))
    assert config.lag_seconds == (3600.0, 10800.0)
    assert config.lag_hours == (1.0, 1.0, 3.0)  # the input is not rewritten


def test_forcings_and_states_are_derived_from_the_quantity_list() -> None:
    config = FeatureConfig(quantities=("rainfall", "water_level", "temperature"))
    assert config.forcing_quantities == ("rainfall", "temperature")
    assert config.state_quantities == ("water_level",)


def test_rolling_statistics_cover_the_declared_set() -> None:
    assert set(ROLLING_STATISTICS) == {STAT_MEAN, STAT_MIN, STAT_MAX, STAT_STD}


def test_only_standard_deviation_needs_two_observations() -> None:
    """Getting this wrong would make a 1-hour rolling standard deviation vanish for
    no reason, or let a 2-point one through on a 1-point series."""
    assert STATISTICS_NEEDING_TWO == frozenset({STAT_STD})
    assert STAT_MEAN not in STATISTICS_NEEDING_TWO


def test_target_seconds_follow_the_horizon_order() -> None:
    config = FeatureConfig(target_hours=(6.0, 24.0, 1.0))
    assert config.target_seconds == (21600.0, 86400.0, 3600.0)


def test_multiple_horizons_produce_distinct_target_names() -> None:
    """Multi-horizon forecasting is in scope, so two horizons that collapsed to one
    column would silently halve the supervision."""
    config = FeatureConfig(target_hours=(6.0, 24.0))
    names = {registry.target_name(config.target_quantity, s) for s in config.target_seconds}
    assert len(names) == 2


def test_the_subject_reaches_the_report() -> None:
    """The report says which configuration produced it, so two runs can be told
    apart after the fact."""
    assert FeatureConfig(subject="run_42").subject == "run_42"
    assert "run_42" in FeatureConfig(subject="run_42").describe()


def test_to_dict_carries_the_constructor_fields_unchanged() -> None:
    """`to_dict` is a *report* shape: it adds derived keys (`cutoffs`,
    `forcing_quantities`, the contract version) on top of the constructor fields,
    the same convention Phase 1 and Phase 2 use. So the round-trip is over the
    constructor fields, and the derived keys are checked separately."""
    config = FeatureConfig(subject="round_trip", lag_hours=(2.0,))
    fields = set(FeatureConfig.__dataclass_fields__)
    constructor_fields = {
        key: value for key, value in config.to_dict().items() if key in fields
    }
    assert FeatureConfig(**constructor_fields) == config


def test_to_dict_publishes_the_resolved_cutoffs_per_quantity() -> None:
    """The report says which cutoff each quantity actually got, not just which
    policy names were configured — the two can differ under `strict_causality`."""
    payload = FeatureConfig(strict_causality=True).to_dict()
    assert payload["cutoffs"]["rainfall"] == CUTOFF_ONE_STEP_BACK
    assert payload["cutoffs"]["water_level"] == CUTOFF_ONE_STEP_BACK
    assert payload["contract_version"] == registry.FEATURE_CONTRACT_VERSION


def test_to_dict_is_json_shaped() -> None:
    import json

    payload = FeatureConfig().to_dict()
    assert json.loads(json.dumps(payload)) == payload


def test_describe_mentions_the_policies_that_shape_the_run() -> None:
    text = FeatureConfig().describe()
    for expected in ("missing", "warmup", "cutoff", "coverage", "unit"):
        assert expected in text.lower()


# --------------------------------------------------------------------------- #
# The registry this configuration produces
# --------------------------------------------------------------------------- #


def test_the_default_configuration_builds_a_named_column_per_feature() -> None:
    built = build_registry(FeatureConfig())
    assert len(built) == 56
    assert len(set(built.names)) == len(built.names)


def test_column_order_is_configuration_order_not_alphabetical() -> None:
    """Column order is a published part of the contract, so it must come from one
    ordered declaration and not from a set or a dict."""
    names = build_registry(FeatureConfig()).names
    assert names[0] == "rainfall_lag_1h"
    assert names[-1] == "calendar_doy_cos"
    assert names != tuple(sorted(names))


def test_two_builds_of_one_configuration_are_identical() -> None:
    assert build_registry(FeatureConfig()).to_dict() == build_registry(FeatureConfig()).to_dict()


def test_registry_membership_is_addressable_by_name() -> None:
    built = build_registry(FeatureConfig())
    assert built.get("water_level_lag_1h").quantity == "water_level"
    assert "water_level_lag_1h" in built
    with pytest.raises(KeyError):
        built.get("water_level_lag_1h_typo")


def test_calendar_features_are_global_in_scope() -> None:
    """A calendar term is a function of the timestamp. Attaching it to one station
    would imply it described that station, which it does not."""
    for definition in build_registry(FeatureConfig()).calendar():
        assert definition.entity_scope == "global"
        assert definition.source_domain == "observed_at"


def test_temporal_features_are_measurement_scoped() -> None:
    """Every built feature reads exactly one `location|domain|quantity` series,
    which is narrower than entity isolation strictly requires. Declaring the
    narrower scope is what makes the isolation structural rather than a promise:
    a rainfall lag has no mechanism by which it could reach a water-level reading,
    because the two live under different measurement keys.
    """
    for definition in build_registry(FeatureConfig()).temporal():
        assert definition.entity_scope == "measurement"


def test_no_built_feature_reaches_across_quantities() -> None:
    """The `entity` scope would mean "one location, all of its quantities". No
    feature built today needs it, so it is declared and left unused."""
    assert "entity" in registry.ENTITY_SCOPES
    scopes = {d.entity_scope for d in build_registry(FeatureConfig()).definitions}
    assert "entity" not in scopes


def test_the_entity_scope_vocabulary_is_closed_and_explained() -> None:
    assert set(registry.ENTITY_SCOPES) == set(registry.ENTITY_SCOPE_MEANING)
    for scope in registry.ENTITY_SCOPES:
        assert registry.ENTITY_SCOPE_MEANING[scope].strip()
    with pytest.raises(ValueError):
        registry.FeatureDefinition(
            name="x_lag_1h",
            operation=registry.OP_LAG,
            quantity="rainfall",
            source_domain="rainfall",
            source_quantity="rainfall",
            window_seconds=3600.0,
            entity_scope="basin",
            description="d",
            rationale="r",
        )


def test_restricting_the_quantities_restricts_the_columns() -> None:
    """A dataset with only rainfall must be able to ask for only rainfall, and must
    get a smaller registry rather than 32 empty columns."""
    names = build_registry(FeatureConfig(quantities=("rainfall",))).names
    assert names
    assert all(name.startswith("rainfall_") or name.startswith("calendar_") for name in names)
    assert "water_level_lag_1h" not in names


def test_no_accumulation_feature_is_declared_for_a_level() -> None:
    """A total of water levels is not a quantity, so the operation is not offered
    for one at all."""
    names = build_registry(FeatureConfig()).names
    assert not [n for n in names if n.startswith("water_level_accum")]
    assert not [n for n in names if n.startswith("inflow_accum")]
    assert "rainfall_accum_24h" in names


def test_rolling_sum_is_not_declared() -> None:
    """`sum` is routed through the accumulation operation, where a coverage
    requirement can be applied to it. Declaring it as a rolling statistic too would
    offer the same column twice with different missing-value behaviour."""
    assert not [n for n in build_registry(FeatureConfig()).names if "_rolling_sum_" in n]


def test_every_definition_carries_a_lineage_and_a_rationale() -> None:
    """Lineage is what makes a fitted column auditable; a rationale is what makes a
    feature choice reviewable rather than merely reproducible."""
    for definition in build_registry(FeatureConfig()).definitions:
        assert definition.lineage.source
        assert definition.lineage.transformation
        assert definition.rationale.strip()
        assert definition.description.strip()
