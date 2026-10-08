# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service/tests | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 3 — the causal window engine.

This is the module the whole of Phase 3 rests on, because it is the only place a
feature value is decided. Every test here is written from one question: *could
this value have been computed by somebody standing at `T`, holding only what had
been observed up to `T`?* If the answer is no, the test fails, however plausible
the number looks.

The fixtures use deliberately recognisable values (`0.0, 1.0, 2.0, ...`) so that a
wrong window shows up as a specific wrong number rather than a mysterious one.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.engines.hydro import feature_registry as registry
from app.engines.hydro import feature_temporal as temporal
from app.engines.hydro.domains import Measurement, Observation
from app.engines.hydro.feature_config import (
    CUTOFF_AT_PREDICTION,
    CUTOFF_ONE_STEP_BACK,
    TARGET_AT_OR_BEFORE,
    TARGET_EXACT,
    FeatureConfig,
)


UTC = dt.timezone.utc
EPOCH = dt.datetime(2024, 1, 1, tzinfo=UTC)
HOUR = 3600.0


# --------------------------------------------------------------------------- #
# Fixtures — local to this file, so it adds no shared surface for a teammate's
# test to come to depend on.
# --------------------------------------------------------------------------- #


def at(hours: float) -> dt.datetime:
    """Hour `hours` after `EPOCH`, as an aware datetime."""
    return EPOCH + dt.timedelta(hours=hours)


def iso(instant: dt.datetime) -> str:
    return instant.isoformat().replace("+00:00", "Z")


def record(
    hour: float,
    value: float,
    *,
    quantity: str = "rainfall",
    domain: str = "rainfall",
    unit: str = "mm",
    location: str = "F1",
    quality_status: str = "ok",
) -> Observation:
    return Observation(
        domain=domain,
        location_reference=location,
        observed_at=iso(at(hour)),
        measurements=(Measurement(quantity=quantity, value=value, unit=unit),),
        quality_status=quality_status,
    )


def ramp(count: int, **kwargs: object) -> list[Observation]:
    """`count` hourly readings whose values are `0.0, 1.0, ..., count - 1`."""
    return [record(hour, float(hour), **kwargs) for hour in range(count)]


def timeline(
    count: int = 12,
    *,
    cadence: float | None = HOUR,
    **kwargs: object,
) -> temporal.SeriesTimeline:
    """One hourly timeline, with the cadence Phase 2 would have inferred."""
    base = {"F1|rainfall": HOUR} if cadence is not None else None
    built = temporal.build_timelines(ramp(count, **kwargs), base_intervals=base)
    return built["F1|rainfall|rainfall"]


def definition(name: str):
    """The registry entry for a default-configuration feature, by name."""
    from app.engines.hydro.feature_config import build_registry

    return build_registry(FeatureConfig()).get(name)


# --------------------------------------------------------------------------- #
# The window contract
# --------------------------------------------------------------------------- #


def test_a_lag_reads_the_instant_it_names_and_nothing_else() -> None:
    """`rainfall_lag_1h` at 06:00 is the reading stamped 05:00. Not the nearest
    one, not the most recent one before it — the one at 05:00, or nothing."""
    line = timeline()
    result = temporal.op_lag(line, at(6), at(6), HOUR)
    assert result.value == 5.0
    assert result.instants == (at(5),)
    assert result.observations == 1


def test_a_lag_never_reaches_past_its_own_cutoff() -> None:
    """A lag shorter than the step between origin and cutoff would otherwise land
    *after* the cutoff. This is the state-series case: cutoff 05:00, origin 06:00,
    a half-hour lag. Unclamped it would read 05:30 — a reading later than the
    cutoff the policy chose, which is the leakage this clamp exists to stop."""
    line = temporal.build_timelines(
        [record(h / 2.0, float(h)) for h in range(0, 24)], base_intervals={"F1|rainfall": 1800.0}
    )["F1|rainfall|rainfall"]
    clamped = temporal.op_lag(line, at(6), at(5), 0.5 * HOUR)
    assert clamped.value == 10.0
    assert clamped.instants == (at(5),)
    assert max(clamped.instants) <= clamped.cutoff


def test_an_accumulation_sums_the_window_and_only_the_window() -> None:
    """Window is open on the left — `(cutoff - window, cutoff]` — so a 3-hour
    accumulation ending at 06:00 holds 03:00, 04:00 and 05:00? No: it holds
    04:00, 05:00 and 06:00. Three readings, and the value is 4 + 5 + 6."""
    line = timeline()
    result = temporal.op_accumulation(line, at(6), at(6), 3 * HOUR, 1.0)
    assert result.value == 15.0
    assert result.observations == 3
    assert result.expected == 3
    assert result.instants == (at(4), at(5), at(6))


def test_a_window_of_width_w_holds_exactly_w_over_base_readings() -> None:
    """The slot count is the contract that makes coverage assessable, and it is
    what lets the engine agree with `pandas.Series.rolling(w)` slot for slot."""
    line = timeline(48)
    for hours in (1.0, 3.0, 6.0, 24.0):
        result = temporal.op_accumulation(line, at(40), at(40), hours * HOUR, 1.0)
        assert result.expected == int(hours)
        assert result.observations == int(hours)


def test_a_window_open_on_the_left_agrees_with_the_value_a_reader_would_pick() -> None:
    """Written out longhand so the convention is checkable by eye: the reading at
    the window's own start instant is *excluded*."""
    line = timeline()
    result = temporal.op_accumulation(line, at(6), at(6), 6 * HOUR, 1.0)
    assert result.instants == tuple(at(h) for h in range(1, 7))
    assert 0.0 not in result.instants


def test_a_change_is_the_difference_between_two_named_instants() -> None:
    line = timeline()
    result = temporal.op_change(line, at(6), at(6), HOUR)
    assert result.value == 1.0
    assert result.instants == (at(5), at(6))


def test_a_change_cancels_the_datum_so_it_compares_across_gauges() -> None:
    """Two gauges on different vertical datums have levels that cannot be
    compared. Their *changes* can be, because the offset cancels. This is why the
    change feature exists and why Phase 3 does not attempt a datum conversion."""
    left = timeline.build if False else None  # placeholder to keep linters quiet
    a = temporal.build_timelines(
        [record(0, 100.0, quantity="water_level", domain="water_level", unit="m", location="A"),
         record(1, 100.5, quantity="water_level", domain="water_level", unit="m", location="A")]
    )["A|water_level|water_level"]
    b = temporal.build_timelines(
        [record(0, 12.0, quantity="water_level", domain="water_level", unit="m", location="B"),
         record(1, 12.5, quantity="water_level", domain="water_level", unit="m", location="B")]
    )["B|water_level|water_level"]
    assert temporal.op_change(a, at(1), at(1), HOUR).value == 0.5
    assert temporal.op_change(b, at(1), at(1), HOUR).value == 0.5


def test_a_change_refuses_to_subtract_across_two_units() -> None:
    """A difference between metres and centimetres is not a small error, it is a
    number with no meaning. This refuses rather than converting."""
    records = [
        record(0, 1.0, unit="m"),
        record(1, 1.5, unit="cm"),
    ]
    line = temporal.build_timelines(records)["F1|rainfall|rainfall"]
    result = temporal.op_change(line, at(1), at(1), HOUR)
    assert result.value is None
    assert result.reason == temporal.CAUSE_UNIT_MISMATCH


def test_an_intensity_is_the_accumulation_over_the_nominal_window() -> None:
    """15 mm over 3 hours is 5 mm/h. Divided by the *nominal* window, because the
    coverage requirement has already established the window is complete — a rate
    over a partly empty window would be scaled by whatever fraction was missing."""
    line = timeline()
    result = temporal.op_intensity(line, at(6), at(6), 3 * HOUR, 1.0, True)
    assert result.value == pytest.approx(5.0)


def test_an_intensity_is_refused_outright_when_the_unit_is_undetermined() -> None:
    """Dividing an amount of unstated units by an hour yields a quantity whose
    units nobody can name, and a model will fit it as confidently as any other
    column. The arithmetic would succeed; that is exactly the danger."""
    line = timeline()
    result = temporal.op_intensity(line, at(6), at(6), 3 * HOUR, 1.0, False)
    assert result.value is None
    assert result.reason == temporal.CAUSE_UNDETERMINED_UNIT


def test_an_undetermined_unit_does_not_block_the_lag_that_does_not_need_one() -> None:
    """A lag is a copy. It does not claim to be a number of anything, so an
    uninterpretable unit is not a reason to refuse it. Refusing everything would
    throw away usable history over a labelling problem."""
    line = timeline(unit="UNDETERMINED")
    assert temporal.op_lag(line, at(3), at(3), HOUR).value == 2.0


# --------------------------------------------------------------------------- #
# Warm-up and missingness are different facts
# --------------------------------------------------------------------------- #


def test_warm_up_is_reported_as_insufficient_history_not_bad_data() -> None:
    """At 02:00 a 6-hour window reaches back before the series began. Nothing is
    wrong with the data; there simply is not enough of it yet. The two causes are
    kept apart precisely so a report reader is not told the first hours of a
    gauge failed."""
    line = timeline()
    result = temporal.op_accumulation(line, at(2), at(2), 6 * HOUR, 1.0)
    assert result.value is None
    assert result.reason == temporal.CAUSE_WARMUP
    assert result.reason != temporal.CAUSE_MISSING_SOURCE


def test_a_missing_reading_inside_the_series_is_a_missing_source() -> None:
    """Same absent value, different cause: 06:00 simply has no reading, and the
    series had already begun."""
    records = [record(h, float(h)) for h in range(12) if h != 5]
    line = temporal.build_timelines(records, base_intervals={"F1|rainfall": HOUR})[
        "F1|rainfall|rainfall"
    ]
    result = temporal.op_lag(line, at(6), at(6), HOUR)
    assert result.value is None
    assert result.reason == temporal.CAUSE_MISSING_SOURCE
    assert result.reason != temporal.CAUSE_WARMUP  # the series had already begun


def test_the_warm_up_boundary_is_decided_by_the_slots_not_by_the_edge() -> None:
    """The trap here is checking whether the window's left edge has reached the
    first reading. That is the wrong question. A 6-hour window ending at 05:00
    starts at 23:00 the previous day, a full hour before the series began — and it
    is nonetheless complete, because its six hourly slots land on 00:00 through
    05:00, every one of them observed.

    Deciding by the edge instead declares this row short by history and throws away
    a perfectly well-defined accumulation. Deciding by the slots cannot."""
    line = timeline()

    complete = temporal.op_accumulation(line, at(5), at(5), 6 * HOUR, 1.0)
    assert complete.reason is None
    assert complete.observations == complete.expected == 6
    assert complete.instants == tuple(at(h) for h in range(6))

    assert complete.instants[0] > (at(5) - dt.timedelta(hours=6))  # edge is before it
    assert complete.instants[0] == line.first_instant

    one_short = temporal.op_accumulation(line, at(4), at(4), 6 * HOUR, 1.0)
    assert one_short.reason == temporal.CAUSE_WARMUP
    assert one_short.observations == 5
    assert one_short.expected == 6


def test_a_partly_observed_accumulation_is_refused_not_quietly_summed() -> None:
    """A sum over a window with a hole in it is smaller than the truth and still
    looks like a total. The default requires every expected slot, and the reported
    count says how short it was."""
    records = [record(h, 1.0) for h in range(12) if h != 5]
    line = temporal.build_timelines(records, base_intervals={"F1|rainfall": HOUR})[
        "F1|rainfall|rainfall"
    ]
    result = temporal.op_accumulation(line, at(6), at(6), 3 * HOUR, 1.0)
    assert result.value is None
    assert result.reason == temporal.CAUSE_MISSING_SOURCE
    assert result.observations == 2
    assert result.expected == 3


def test_a_window_that_overruns_the_end_of_the_series_is_not_warm_up() -> None:
    """Warm-up is a statement about the *beginning* of a record. A window reaching
    past the end is short because the data stopped, which is a different fact and
    a different fix — and telling an operator their gauge lacked history when it
    had plenty sends them looking in the wrong place entirely."""
    line = temporal.build_timelines(
        ramp(8), base_intervals={"F1|rainfall": HOUR}
    )["F1|rainfall|rainfall"]
    result = temporal.op_accumulation(line, at(10), at(10), 3 * HOUR, 1.0)
    assert result.value is None
    assert result.reason == temporal.CAUSE_MISSING_SOURCE
    assert result.reason != temporal.CAUSE_WARMUP


def test_a_partly_observed_rolling_mean_is_still_computed_by_default() -> None:
    """The opposite policy, on purpose: a mean over the readings that exist is
    exactly what it says it is. The count travels with it so the report can show
    how thin the window was."""
    records = [record(h, 1.0) for h in range(12) if h != 5]
    line = temporal.build_timelines(records, base_intervals={"F1|rainfall": HOUR})[
        "F1|rainfall|rainfall"
    ]
    result = temporal.op_rolling(line, at(6), at(6), 3 * HOUR, "mean", 0.0)
    assert result.value == 1.0
    assert result.observations == 2
    assert result.expected == 3


def test_coverage_that_cannot_be_assessed_counts_as_unmet() -> None:
    """With no established cadence nobody can say how many readings a window
    should hold. Treating that as perfect coverage would be inventing a cadence,
    so an accumulation refuses."""
    line = timeline(cadence=None)
    result = temporal.op_accumulation(line, at(6), at(6), 3 * HOUR, 1.0)
    assert result.value is None
    assert result.reason == temporal.CAUSE_INSUFFICIENT
    assert result.expected is None


def test_every_absence_carries_one_of_the_declared_causes() -> None:
    """A blank `reason` would read as "there is no reason", which is exactly the
    impression this module exists to prevent."""
    for cause in temporal.ABSENT_CAUSES:
        assert cause
    assert len(set(temporal.ABSENT_CAUSES)) == len(temporal.ABSENT_CAUSES)
    assert set(temporal.ABSENT_CAUSES) == {
        getattr(temporal, name)
        for name in temporal.__all__
        if name.startswith("CAUSE_")
    }


def test_the_absent_sentinel_carries_no_value_and_no_reason() -> None:
    assert temporal.ABSENT.value is None
    assert temporal.ABSENT.reason is None
    assert not temporal.ABSENT.is_present


# --------------------------------------------------------------------------- #
# Rolling statistics
# --------------------------------------------------------------------------- #


def test_rolling_statistics_agree_with_their_definitions() -> None:
    line = timeline()
    origin = cutoff = at(6)
    assert temporal.op_rolling(line, origin, cutoff, 3 * HOUR, "mean", 0.0).value == 5.0
    assert temporal.op_rolling(line, origin, cutoff, 3 * HOUR, "min", 0.0).value == 4.0
    assert temporal.op_rolling(line, origin, cutoff, 3 * HOUR, "max", 0.0).value == 6.0


def test_a_standard_deviation_needs_two_readings_and_refuses_one() -> None:
    """Reporting `0.0` from a single reading would claim two identical readings
    when there is only one."""
    line = temporal.build_timelines(
        [record(0, 5.0), record(1, 9.0)], base_intervals={"F1|rainfall": HOUR}
    )["F1|rainfall|rainfall"]
    two = temporal.op_rolling(line, at(1), at(1), 2 * HOUR, "std", 0.0)
    assert two.observations == 2
    assert two.value == pytest.approx(4.0 / 2**0.5)  # sample std of 5 and 9

    one = temporal.op_rolling(line, at(1), at(1), HOUR, "std", 0.0)
    assert one.value is None
    assert one.reason == temporal.CAUSE_INSUFFICIENT


def test_an_unknown_statistic_is_refused_by_name() -> None:
    line = timeline()
    with pytest.raises(temporal.FeatureTemporalError) as caught:
        temporal.op_rolling(line, at(6), at(6), 3 * HOUR, "p95", 0.0)
    assert "p95" in str(caught.value)


# --------------------------------------------------------------------------- #
# Cutoffs — the point-in-time guarantee
# --------------------------------------------------------------------------- #


def test_a_state_cutoff_lands_one_step_behind_the_origin() -> None:
    """`water_level` at the prediction instant is the thing being predicted, so a
    state feature reads the previous reading instead."""
    config = FeatureConfig()
    cutoff, policy, unknown = temporal.resolve_cutoff(config, "water_level", at(6), HOUR)
    assert cutoff == at(5)
    assert policy == CUTOFF_ONE_STEP_BACK
    assert unknown is False


def test_a_forcing_cutoff_may_land_on_the_origin_by_default() -> None:
    """Rainfall at the prediction instant is observed, not predicted. Using it is
    the physically correct choice, and `strict_causality` exists to move it."""
    config = FeatureConfig()
    cutoff, policy, _unknown = temporal.resolve_cutoff(config, "rainfall", at(6), HOUR)
    assert cutoff == at(6)
    assert policy == CUTOFF_AT_PREDICTION


def test_strict_causality_never_lets_a_feature_read_the_origin() -> None:
    config = FeatureConfig(strict_causality=True)
    for quantity in ("rainfall", "water_level", "discharge", "inflow"):
        cutoff, _policy, _unknown = temporal.resolve_cutoff(config, quantity, at(6), HOUR)
        assert cutoff == at(5), quantity
        assert cutoff < at(6)


def test_an_unknown_cadence_falls_back_to_the_origin_for_a_forcing() -> None:
    """Rainfall at the prediction instant is an observation, so staying at the
    origin is conservative in the causal direction: it can only ever read *less*,
    never more."""
    cutoff, policy, downgraded = temporal.resolve_cutoff(
        FeatureConfig(), "rainfall", at(6), None
    )
    assert cutoff == at(6)
    assert policy == CUTOFF_AT_PREDICTION
    # Not downgraded: for a forcing the cadence has no bearing on the cutoff, so
    # the policy was applied exactly as configured.
    assert downgraded is False


def test_an_unknown_cadence_does_not_fall_back_to_the_origin_for_a_state() -> None:
    """This is the case that makes the difference above matter. Falling back to the
    origin for a *state* would put the water level at `T` inside a window that
    claims to summarize the hours before `T` — the quantity being predicted,
    wearing a feature's name.

    Found by `audit_point_in_time`, which truncates the data at each origin and
    watches for a feature that changes. A truncated series has no resolvable
    cadence, so this is exactly the branch it exercised.
    """
    cutoff, policy, downgraded = temporal.resolve_cutoff(
        FeatureConfig(), "water_level", at(6), None, previous_instant=at(5)
    )
    assert cutoff == at(5)
    assert cutoff < at(6)
    assert policy == CUTOFF_ONE_STEP_BACK
    assert downgraded is True  # the requested one_step_back was placed on real data


def test_a_state_feature_with_no_earlier_reading_is_absent_rather_than_read_at_the_origin() -> None:
    """The remaining case, and the one that has no correct answer. With an
    unresolvable cadence and nothing observed before the origin, a one-step-back
    window cannot be placed. Evaluating it anyway would report a value; that value
    would be the prediction instant, labelled as history."""
    line = temporal.build_timelines([record(0, 1.0)])["F1|rainfall|rainfall"]
    result = temporal.evaluate(
        definition("water_level_lag_1h"),
        temporal.build_timelines(
            [record(0, 1.0, quantity="water_level", domain="water_level", unit="m")]
        )["F1|water_level|water_level"],
        at(0),
        FeatureConfig(),
        unit_is_understood=True,
    )
    assert result.value is None
    assert result.reason == temporal.CAUSE_CUTOFF_UNDEFINED
    assert line.base_interval_seconds is None


def test_a_forcing_still_evaluates_under_the_same_unresolvable_cadence() -> None:
    """The refusal above is scoped to state cutoffs. A forcing's fallback is
    legitimate, and refusing it too would empty columns that are perfectly
    well defined."""
    line = temporal.build_timelines([record(0, 1.0)])["F1|rainfall|rainfall"]
    result = temporal.evaluate(
        definition("rainfall_lag_1h"), line, at(0), FeatureConfig(), unit_is_understood=True
    )
    assert result.value is None
    assert result.reason == temporal.CAUSE_WARMUP  # nothing before the origin, not a refusal


def test_a_cutoff_is_never_later_than_the_origin_for_any_configuration() -> None:
    """The invariant behind the whole point-in-time claim, stated once and checked
    across the configuration space rather than case by case — including the
    unknown-cadence branch and a previous-instant fallback, because those are
    where an off-by-one would hide."""
    configs = (
        FeatureConfig(),
        FeatureConfig(strict_causality=True),
        FeatureConfig(strictness="strict"),
    )
    for config in configs:
        for quantity in registry.SUPPORTED_QUANTITIES:
            for cadence in (HOUR, 900.0, None):
                for previous in (None, at(5), at(6), at(7)):
                    cutoff, _policy, _downgraded = temporal.resolve_cutoff(
                        config, quantity, at(6), cadence, previous
                    )
                    assert cutoff <= at(6), (config.strictness, quantity, cadence, previous)


# --------------------------------------------------------------------------- #
# The dispatch
# --------------------------------------------------------------------------- #


def test_evaluate_routes_each_operation_to_its_own_window_semantics() -> None:
    """One dispatch point, so a feature cannot be computed by a different path
    than its registry entry describes."""
    line = timeline()
    config = FeatureConfig()
    origin = at(6)
    got = {
        name: temporal.evaluate(definition(name), line, origin, config, unit_is_understood=True)
        for name in (
            "rainfall_lag_1h",
            "rainfall_change_1h",
            "rainfall_accum_3h",
            "rainfall_intensity_3h",
            "rainfall_rolling_mean_6h",
        )
    }
    assert got["rainfall_lag_1h"].value == 5.0  # 1h before the 06:00 cutoff
    assert got["rainfall_change_1h"].value == 1.0
    assert got["rainfall_accum_3h"].value == 15.0
    assert got["rainfall_intensity_3h"].value == pytest.approx(5.0)
    assert got["rainfall_rolling_mean_6h"].value == 3.5


def test_a_calendar_feature_must_not_be_handed_a_series() -> None:
    """Passing one anyway means something wired the wrong thing up. Refusing makes
    that visible instead of papered over."""
    line = timeline()
    with pytest.raises(temporal.FeatureTemporalError) as caught:
        temporal.evaluate(
            definition("calendar_hour_sin"), line, at(6), FeatureConfig(), unit_is_understood=True
        )
    assert "calendar" in str(caught.value)


def test_evaluate_applies_the_one_step_back_cutoff_to_a_state_feature() -> None:
    """The end-to-end version of the cutoff rule: at 06:00 the 1-hour water-level
    lag is 05:00, not 06:00."""
    records = [
        record(h, float(h), quantity="water_level", domain="water_level", unit="m")
        for h in range(12)
    ]
    line = temporal.build_timelines(
        records, base_intervals={"F1|water_level": HOUR}
    )["F1|water_level|water_level"]
    result = temporal.evaluate(
        definition("water_level_lag_1h"), line, at(6), FeatureConfig(), unit_is_understood=True
    )
    assert result.value == 5.0
    assert result.instants == (at(5),)


# --------------------------------------------------------------------------- #
# Calendar terms
# --------------------------------------------------------------------------- #


def test_a_calendar_term_reads_only_the_timestamp() -> None:
    """It has nowhere else to get information from, which is why it is safe by
    construction rather than by test."""
    result = temporal.evaluate(
        definition("calendar_hour_sin"), None, at(6), FeatureConfig(), unit_is_understood=True
    )
    assert result.value == pytest.approx(1.0)  # sin(2*pi*6/24) == sin(pi/2)
    assert result.instants == (at(6),)
    assert result.cutoff == at(6)


def test_hour_sin_is_zero_at_midnight_and_one_at_six_in_the_morning() -> None:
    for hour, expected in ((0, 0.0), (6, 1.0), (12, 0.0), (18, -1.0)):
        result = temporal.evaluate(
            definition("calendar_hour_sin"), None, at(hour), FeatureConfig(), unit_is_understood=True
        )
        assert result.value == pytest.approx(expected, abs=1e-12), hour


def test_the_cyclic_encoding_makes_the_last_hour_and_midnight_neighbours() -> None:
    """On the raw integers, 23 and 0 are the two extremes of a 0-23 range and a
    linear model reads them as as far apart as it is possible to be. On a circle
    they are one hour apart, and the encoded values say so.

    `cos` rather than `sin`: `sin` is symmetric about 06:00, so 11:00 encodes close
    to midnight and the demonstration would show the opposite of the point.
    """
    def encoded(hour: float) -> float:
        return temporal.evaluate(
            definition("calendar_hour_cos"), None, at(hour), FeatureConfig(), unit_is_understood=True
        ).value

    assert abs(encoded(23) - encoded(0)) < 0.05  # one hour apart on the circle
    assert abs(encoded(11) - encoded(0)) > 1.9  # half a day apart
    assert 23 - 0 == 23  # ...even though the raw integers are as far apart as they get


def test_day_of_year_is_one_based_to_match_the_layer_below() -> None:
    """1 January is day 1, not day 0 — matching `tm_yday` and the pre-Phase-1
    pandas layer, which is what makes cross-checking the two worth anything."""
    result = temporal.evaluate(
        definition("calendar_doy_sin"), None, EPOCH, FeatureConfig(), unit_is_understood=True
    )
    assert result.value == pytest.approx(
        __import__("math").sin(2 * __import__("math").pi * 1.0 / 365.25)
    )


# --------------------------------------------------------------------------- #
# Target alignment
# --------------------------------------------------------------------------- #


def test_a_target_is_the_value_exactly_one_horizon_ahead() -> None:
    line = timeline()
    result = temporal.op_target(line, at(3), 6 * HOUR, TARGET_EXACT, None)
    assert result.value == 9.0
    assert result.instants == (at(9),)
    assert result.cutoff == at(9)


def test_a_target_past_the_end_of_the_series_is_absent_not_clamped() -> None:
    """Clamping would put the last observed value under a target column that
    claims to be six hours ahead of something. That is the quietest and worst
    version of target leakage."""
    line = timeline()
    result = temporal.op_target(line, at(10), 6 * HOUR, TARGET_EXACT, None)
    assert result.value is None
    assert result.reason == temporal.CAUSE_MISSING_SOURCE


def test_exact_alignment_refuses_a_reading_from_the_wrong_instant() -> None:
    """Records at 03:00 and 05:00; origin 03:00 with a 3-hour horizon wants 06:00,
    which nobody observed. 05:00 is the nearest reading, and exact alignment must
    not quietly hand it over — doing so would put a 2-hour-old number under a
    column labelled `target_rainfall_3h`."""
    records = [record(3, 3.0), record(5, 5.0)]
    line = temporal.build_timelines(records, base_intervals={"F1|rainfall": HOUR})[
        "F1|rainfall|rainfall"
    ]
    assert temporal.op_target(line, at(3), 3 * HOUR, TARGET_EXACT, None).value is None

    tolerated = temporal.op_target(line, at(3), 3 * HOUR, TARGET_AT_OR_BEFORE, 2 * HOUR)
    assert tolerated.value == 5.0
    assert tolerated.instants == (at(5),)


def test_at_or_before_alignment_will_not_reach_past_the_tolerance() -> None:
    """A tolerance is a bound on how wrong the instant may be, not a licence to
    take whatever reading is nearest."""
    records = [record(1, 1.0), record(4, 4.0)]
    line = temporal.build_timelines(records, base_intervals={"F1|rainfall": HOUR})[
        "F1|rainfall|rainfall"
    ]
    assert temporal.op_target(line, at(1), 6 * HOUR, TARGET_AT_OR_BEFORE, HOUR).value is None


def test_at_or_before_alignment_needs_a_tolerance_to_be_configurable() -> None:
    """An unspecified earlier reading is a coincidence, not a forecast horizon."""
    from app.engines.hydro.feature_config import FeatureConfigError

    with pytest.raises(FeatureConfigError):
        FeatureConfig(target_alignment=TARGET_AT_OR_BEFORE)
    assert FeatureConfig(
        target_alignment=TARGET_AT_OR_BEFORE, target_tolerance_seconds=HOUR
    ).target_tolerance_seconds == HOUR


# --------------------------------------------------------------------------- #
# Entity isolation
# --------------------------------------------------------------------------- #


def test_a_rainfall_lag_cannot_reach_a_water_level_reading() -> None:
    """The reason measurement keys are three levels deep. Both series live at the
    same station and the same instants, so nothing but the key stands between a
    rainfall lag and a water level."""
    records = [
        record(0, 10.0, quantity="rainfall", domain="rainfall"),
        record(0, 2.0, quantity="water_level", domain="water_level", unit="m"),
        record(1, 11.0, quantity="rainfall", domain="rainfall"),
        record(1, 2.5, quantity="water_level", domain="water_level", unit="m"),
    ]
    built = temporal.build_timelines(records, base_intervals={"F1": HOUR})
    assert set(built) == {"F1|rainfall|rainfall", "F1|water_level|water_level"}
    rainfall = built["F1|rainfall|rainfall"]
    assert temporal.op_lag(rainfall, at(1), at(1), HOUR).value == 10.0


def test_one_station_never_sees_another_stations_readings() -> None:
    records = [
        record(0, 1.0, location="A"),
        record(0, 100.0, location="B"),
        record(1, 2.0, location="A"),
        record(1, 200.0, location="B"),
    ]
    built = temporal.build_timelines(records, base_intervals={"A": HOUR, "B": HOUR})
    assert temporal.op_lag(built["A|rainfall|rainfall"], at(1), at(1), HOUR).value == 1.0
    assert temporal.op_lag(built["B|rainfall|rainfall"], at(1), at(1), HOUR).value == 100.0


def test_a_wide_weather_record_splits_into_one_timeline_per_measurement() -> None:
    """A record carrying both a temperature and a humidity reading yields two
    timelines. Keyed on the domain's canonical quantity instead — and `weather`
    has none — it would yield zero, and the temperature and humidity columns would
    sit permanently empty while the report said the features were built."""
    wide = Observation(
        domain="weather",
        location_reference="F1",
        observed_at=iso(at(0)),
        measurements=(
            Measurement(quantity="temperature", value=10.0, unit="degC"),
            Measurement(quantity="humidity", value=70.0, unit="percent"),
        ),
    )
    built = temporal.build_timelines([wide])
    assert set(built) == {"F1|weather|temperature", "F1|weather|humidity"}
    assert built["F1|weather|temperature"].unit == "degC"
    assert built["F1|weather|humidity"].unit == "percent"


def test_timelines_can_be_grouped_by_entity_for_reporting() -> None:
    """Grouped by *location*, because a forecast is issued for a catchment while
    every feature is read from one measurement key. The two levels are different
    and this is where both are available."""
    records = [
        record(0, 1.0, location="A"),
        record(0, 2.0, quantity="water_level", domain="water_level", unit="m", location="A"),
        record(0, 3.0, location="B"),
    ]
    built = temporal.build_timelines(records)
    grouped = temporal.timelines_by_entity(built)
    assert grouped["A"] == ("A|rainfall|rainfall", "A|water_level|water_level")
    assert grouped["B"] == ("B|rainfall|rainfall",)
    assert list(grouped) == ["A", "B"]  # sorted, so a report renders the same twice


def test_entity_instants_are_the_union_of_every_series_and_are_sorted() -> None:
    """The origin instants of a row come from the whole dataset, not from one
    series, so a station that starts late does not silently truncate the rows."""
    records = [record(0, 1.0), record(1, 1.0, location="B")]
    instants = temporal.entity_instants(list(temporal.build_timelines(records).values()))
    assert instants == (at(0), at(1))


# --------------------------------------------------------------------------- #
# Filled slots
# --------------------------------------------------------------------------- #


def test_a_gap_filled_by_the_phase_two_policy_is_not_treated_as_observed() -> None:
    """A filled slot is a policy decision, not an observation. Feeding it to an
    accumulation would inflate a rainfall total by an invented amount."""
    records = [record(0, 1.0), record(1, 2.0, quality_status="missing"), record(2, 3.0)]
    kept = temporal.build_timelines(records, base_intervals={"F1|rainfall": HOUR})
    assert temporal.op_lag(kept["F1|rainfall|rainfall"], at(2), at(2), HOUR).reason == (
        temporal.CAUSE_MISSING_SOURCE
    )

    included = temporal.build_timelines(
        records, base_intervals={"F1|rainfall": HOUR}, exclude_filled=False
    )
    assert temporal.op_lag(included["F1|rainfall|rainfall"], at(2), at(2), HOUR).value == 2.0


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_permuting_the_input_records_cannot_change_a_single_value() -> None:
    """Determinism is not cosmetic. A feature set whose columns change when the
    rows are shuffled is not a feature set, it is a snapshot of one sort order."""
    forward = ramp(24)
    backward = list(reversed(forward))
    base = {"F1|rainfall": HOUR}
    a = temporal.build_timelines(forward, base_intervals=base)
    b = temporal.build_timelines(backward, base_intervals=base)
    assert list(a) == list(b)

    for name in ("rainfall_lag_1h", "rainfall_accum_24h", "rainfall_rolling_mean_6h"):
        spec = definition(name)
        left = temporal.evaluate(
            spec, a["F1|rainfall|rainfall"], at(20), FeatureConfig(), unit_is_understood=True
        )
        right = temporal.evaluate(
            spec, b["F1|rainfall|rainfall"], at(20), FeatureConfig(), unit_is_understood=True
        )
        assert left.value == right.value, name
        assert left.instants == right.instants, name


# --------------------------------------------------------------------------- #
# Cross-check against an independent implementation
# --------------------------------------------------------------------------- #


def pandas_series(line: temporal.SeriesTimeline):
    """The same readings as a `pandas.Series` indexed by instant.

    The point of this section. Phase 3's window arithmetic was written from a
    description of the convention, and a description can be wrong in a way that
    is internally consistent. Agreeing slot for slot with an implementation that
    was written independently of this codebase is the only evidence here that the
    convention was chosen correctly rather than merely implemented consistently.
    """
    import pandas as pd

    return pd.Series(
        [reading.value for reading in line.readings],
        index=pd.DatetimeIndex([reading.instant for reading in line.readings]),
        dtype="float64",
    )


def test_a_window_agrees_with_pandas_rolling_slot_for_slot() -> None:
    """The decisive case. Phase 3's window is open on the left — `(cutoff - w,
    cutoff]` — which is exactly what `pandas.Series.rolling(w)` computes for a
    regular hourly index: `w` slots ending at and including the label.

    Every window width and every origin in a 48-hour series is compared, not a
    hand-picked few. One agreeing value would show the arithmetic works; agreeing
    on all of them shows the boundary is in the same place throughout, which is
    where a window convention actually goes wrong.
    """
    import pandas as pd

    line = temporal.build_timelines(ramp(48), base_intervals={"F1|rainfall": HOUR})[
        "F1|rainfall|rainfall"
    ]
    series = pandas_series(line)

    compared = 0
    for hours in (1.0, 3.0, 6.0, 24.0):
        width = int(hours)
        for hour in range(24, 48):
            cutoff = at(hour)
            ours = temporal.op_accumulation(line, cutoff, cutoff, hours * HOUR, 1.0)
            theirs = series.rolling(width).sum().loc[cutoff]
            assert ours.value == pytest.approx(float(theirs)), (hours, hour)
            assert ours.observations == width, (hours, hour)
            compared += 1
    assert compared == 4 * 24

    for statistic, method in (
        ("mean", lambda w: series.rolling(w).mean()),
        ("min", lambda w: series.rolling(w).min()),
        ("max", lambda w: series.rolling(w).max()),
        ("std", lambda w: series.rolling(w).std(ddof=1)),
    ):
        windowed = method(6)
        for hour in range(6, 48):
            cutoff = at(hour)
            ours = temporal.op_rolling(line, cutoff, cutoff, 6 * HOUR, statistic, 0.0)
            assert ours.value == pytest.approx(float(windowed.loc[cutoff])), (statistic, hour)


def test_a_lag_agrees_with_a_pandas_shift() -> None:
    """`shift(1)` is the other implementation of "the previous reading", and the
    legacy pandas layer in `features.py` is built on it. Agreeing with it means
    Phase 3 can be compared against the layer it sits beside."""
    line = temporal.build_timelines(ramp(48), base_intervals={"F1|rainfall": HOUR})[
        "F1|rainfall|rainfall"
    ]
    series = pandas_series(line)
    shifted = series.shift(1)

    for hour in range(1, 48):
        result = temporal.op_lag(line, at(hour), at(hour), HOUR)
        assert result.value == pytest.approx(float(shifted.loc[at(hour)])), hour


def test_a_state_features_one_step_back_cutoff_matches_pandas_at_the_earlier_label() -> None:
    """The whole point of the state cutoff in one line: Phase 3's water-level
    rolling mean for origin `T` is `pandas`'s for label `T - 1h`.

    If the one-step-back policy were removed or ignored, this is the test that
    would say so, and it says so by disagreeing with an independent
    implementation rather than by asserting a constant."""
    line = temporal.build_timelines(
        ramp(48, quantity="water_level", domain="water_level", unit="m"),
        base_intervals={"F1|water_level": HOUR},
    )["F1|water_level|water_level"]
    series = pandas_series(line)
    windowed = series.rolling(6).mean()

    compared = 0
    thin = 0
    for hour in range(1, 48):
        origin = at(hour)
        cutoff, policy, _downgraded = temporal.resolve_cutoff(
            FeatureConfig(), "water_level", origin, HOUR
        )
        assert policy == CUTOFF_ONE_STEP_BACK
        assert cutoff == at(hour - 1)

        ours = temporal.op_rolling(line, origin, cutoff, 6 * HOUR, "mean", 0.0)
        theirs = windowed.loc[cutoff]

        if ours.value is None:
            # Warm-up: the window reaches before the series began.
            assert cutoff - dt.timedelta(hours=6) < line.first_instant, hour
            continue

        if theirs == theirs:  # not NaN: pandas had a full window to work with
            assert ours.value == pytest.approx(float(theirs)), hour
            assert ours.observations == 6, hour
            compared += 1
        else:
            # pandas refuses a partly filled window outright. Phase 3 computes the
            # mean of what it did see, which is a real answer, and reports how many
            # readings it was — so a consumer can tell a six-reading mean from a
            # one-reading mean that happens to be the same number.
            thin += 1
            assert 1 <= ours.observations < 6, hour
            expected_slots = line.readings_in(
                cutoff - dt.timedelta(hours=6), cutoff, inclusive_start=False
            )
            assert ours.observations == len(expected_slots), hour
            assert ours.value == pytest.approx(
                sum(r.value for r in expected_slots) / len(expected_slots)
            ), hour

    assert compared == 42  # hours 7 through 47
    assert thin == 5  # hours 1 through 6, one short window per size of shortfall


def test_the_change_feature_agrees_with_a_pandas_difference() -> None:
    """`diff()` is the standard spelling of the same quantity, and it differs from
    Phase 3 only in which pairs it is willing to report."""
    line = temporal.build_timelines(ramp(48), base_intervals={"F1|rainfall": HOUR})[
        "F1|rainfall|rainfall"
    ]
    series = pandas_series(line)

    for hour in range(1, 48):
        result = temporal.op_change(line, at(hour), at(hour), HOUR)
        assert result.value == pytest.approx(float(series.diff().loc[at(hour)])), hour


def test_a_timeline_reports_the_same_readings_whatever_order_it_was_built_in() -> None:
    base = {"F1|rainfall": HOUR}
    a = temporal.build_timelines(ramp(10), base_intervals=base)["F1|rainfall|rainfall"]
    b = temporal.build_timelines(list(reversed(ramp(10))), base_intervals=base)[
        "F1|rainfall|rainfall"
    ]
    assert [r.instant for r in a.readings] == [r.instant for r in b.readings]
    assert a.readings == b.readings