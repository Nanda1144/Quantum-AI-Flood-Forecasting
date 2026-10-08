# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform . It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 3 — every feature policy, and the refusals that keep it honest.

Feature engineering is where a forecasting pipeline most easily becomes quietly
dishonest. Nothing here fits a model or computes a score, so there is no obvious
place for a wrong number to show up; instead the wrong number shows up as a
*reasonable* feature: a 24-hour rainfall total that silently covers only nine
hours, a water-level change computed across two readings in different units, a
"3-hour" window on a gauge that reports every fifteen minutes, a feature that
reads the current observation when the current observation is not yet available.

So this module is mostly a list of refusals. It states which windows are allowed,
which instant each window may reach, what happens when a required reading is
absent, and — for each of those — what it will *not* do.

Three policies carry most of the weight:

**`forcing_cutoff` / `state_cutoff`** — the newest instant a feature may read,
per class of quantity. Rainfall, temperature and humidity are *forcings*: they
drive the catchment and they are observed at the moment a forecast is made, so
an antecedent-rainfall window may end at the prediction instant. Water level,
discharge and inflow are *states*: they are what is being forecast, and the most
recent one a forecaster can rely on is the last validated reading, one step
back. The distinction is a modelling assumption about what is known at
prediction time, so it is a named configuration value rather than an accident of
how each feature was written. `strict_causality=True` collapses both to
"nothing may read the prediction instant".

**`accumulation_min_coverage`** — the fraction of a window's expected sampling
slots that must actually hold an observation before a sum over it is reported.
The default is `1.0`, and it is the single most important number here. Summing
the rainfall that happens to be present in a 24-hour window with three hours
missing produces a *smaller* number that looks like a real answer; downstream it
becomes a claim that little rain fell when in fact nobody knows. A mean is
different: a mean over a partly empty window is a mean of what was there, so
`rolling_min_coverage` defaults to `0.0`.

**`unit_policy`** — Phase 3 never converts, and never guesses. A unit-preserving
feature (a lag, a difference, a sum, a mean) can still be *computed* over a
source unit that Phase 2 could not interpret, but it is flagged, because the
arithmetic is valid while the physical meaning is not. A *rate* is a different
matter: dividing an amount of unknown units by an hour yields a number whose
units are unknown, and a model will happily learn from it. Rate features are
therefore skipped outright unless the unit is understood.

Nothing in this module imputes. Filling a feature with a mean, a zero or the
previous row is a modelling decision that belongs to Phase 4, which can fit it on
training data only; doing it here would also do it before the split, which is how
test-set information leaks into training rows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from .feature_registry import (
    ACCUMULABLE_QUANTITIES,
    ALIGN_EXCLUDE_CURRENT,
    ALIGN_INCLUDE_CURRENT,
    CALENDAR_COMPONENTS,
    CALENDAR_ENCODINGS,
    CAL_DOY,
    CAL_HOUR,
    ENCODING_COS,
    ENCODING_SIN,
    FEATURE_CONTRACT_VERSION,
    FORCING_QUANTITIES,
    INTENSITY_QUANTITIES,
    STATE_QUANTITIES,
    SUPPORTED_QUANTITIES,
    dedupe_windows,
    window_label,
)

# --------------------------------------------------------------------------- #
# Instantaneous cutoffs
# --------------------------------------------------------------------------- #

#: A window may end at the prediction instant. The reading at `T` is used.
#:
#: Correct for a *forcing*: rainfall at 10:00 is known at 10:00, and the
#: antecedent-rainfall total "in the last three hours" conventionally means the
#: three hours ending at 10:00, inclusive.
CUTOFF_AT_PREDICTION = "at_prediction_instant"

#: A window ends one sampling step *before* the prediction instant, so the
#: newest reading used is `T - base_interval`.
#:
#: Correct for a *state*: the level at 10:00 is the thing being predicted, not a
#: known input. A "most recent observed change" feature should therefore describe
#: what the gauge was doing up to the last validated reading, not include a
#: reading that a forecaster issuing a forecast has not yet confirmed.
CUTOFF_ONE_STEP_BACK = "one_step_back"

CUTOFFS = (CUTOFF_AT_PREDICTION, CUTOFF_ONE_STEP_BACK)


# --------------------------------------------------------------------------- #
# Rolling statistics
# --------------------------------------------------------------------------- #

STAT_MEAN = "mean"
STAT_MIN = "min"
STAT_MAX = "max"
STAT_STD = "std"

#: Statistics a rolling window may use.
#:
#: `sum` is deliberately absent. A sum over a window is a *cumulative* feature
#: with different coverage requirements and a different physical meaning, and it
#: has its own operation (`OP_ACCUMULATION`) with its own coverage rule. Letting
#: the two share one code path is how a 24-hour total ends up computed with
#: `min_periods=1` like a mean. `count` is absent for the same reason: Phase 2
#: already reports how many slots a grid had and how many were empty.
ROLLING_STATISTICS: tuple[str, ...] = (STAT_MEAN, STAT_MIN, STAT_MAX, STAT_STD)

#: Statistics that are undefined from a single observation.
STATISTICS_NEEDING_TWO: frozenset[str] = frozenset({STAT_STD})


# --------------------------------------------------------------------------- #
# Missing-value and warm-up policies
# --------------------------------------------------------------------------- #

#: Keep the row and leave the feature absent. The default.
#:
#: The absence stays *visible*: it is counted per feature, attributed to a cause,
#: and reported. This is the honest option, because the alternative reasons to
#: remove a row are worse — dropping silently loses data, and filling silently
#: invents it.
MISSING_RETAIN = "retain"
#: Remove every row in which any temporal feature is absent, and report exactly
#: how many rows and why.
MISSING_DROP_ROWS = "drop_rows"
#: Refuse to produce a dataset at all.
MISSING_ERROR = "error"

MISSING_POLICIES = (MISSING_RETAIN, MISSING_DROP_ROWS, MISSING_ERROR)

#: Warm-up is not missingness. A feature is *in warm-up* when the series began
#: later than the window reaches back to — there is no earlier reading to have
#: used, and none will ever appear. A feature is *missing* when the series
#: existed, the window reached into it, and the required reading was not there.
#: Different causes, different fixes, and both must be reported separately,
#: because "this dataset has 24 hours of missing rainfall" is a statement about
#: the data while "the first 24 rows have no 24-hour total" is a statement about
#: the feature set.
WARMUP_RETAIN = "retain"
WARMUP_DROP_ROWS = "drop_rows"
WARMUP_ERROR = "error"

WARMUP_POLICIES = (WARMUP_RETAIN, WARMUP_DROP_ROWS, WARMUP_ERROR)


# --------------------------------------------------------------------------- #
# Unit policies
# --------------------------------------------------------------------------- #

#: Unit-preserving features over an uninterpretable unit are computed and
#: flagged; rate features over an uninterpretable unit are skipped. The default.
UNIT_FLAG_UNDETERMINED = "flag_undetermined"
#: Any feature whose source unit cannot be interpreted is skipped, whatever the
#: operation.
UNIT_REQUIRE_KNOWN = "require_known"

UNIT_POLICIES = (UNIT_FLAG_UNDETERMINED, UNIT_REQUIRE_KNOWN)


# --------------------------------------------------------------------------- #
# Target alignment
# --------------------------------------------------------------------------- #

#: The target must come from the reading at exactly `T + horizon`. The default.
#:
#: On a regular cadence this is exact and cheap. On an irregular one it means
#: some rows simply have no target, which is the truth: at an irregular instant
#: there is no observation to predict, and substituting a nearby one changes the
#: question being asked.
TARGET_EXACT = "exact"

#: The target comes from the latest reading at or before `T + horizon`, within an
#: explicitly stated tolerance. The *offset* used is recorded on the row, so a
#: target taken 40 minutes early is visible rather than silent.
TARGET_AT_OR_BEFORE = "at_or_before"

TARGET_ALIGNMENTS = (TARGET_EXACT, TARGET_AT_OR_BEFORE)


# --------------------------------------------------------------------------- #
# Strictness
# --------------------------------------------------------------------------- #

STRICTNESS_PERMISSIVE = "permissive"
STRICTNESS_STRICT = "strict"
STRICTNESS_MODES = (STRICTNESS_PERMISSIVE, STRICTNESS_STRICT)

#: Fields `strictness='strict'` narrows, as `(permissive_default, strict_value)`.
#:
#: Read this table to see exactly what strict means: it is the whole contract,
#: held as data rather than scattered through conditionals. A field still at its
#: permissive default is promoted silently; a field deliberately set to anything
#: else is refused.
STRICT_NARROWINGS: Mapping[str, tuple[Any, Any]] = {
    "unit_policy": (UNIT_FLAG_UNDETERMINED, UNIT_REQUIRE_KNOWN),
    "forcing_cutoff": (CUTOFF_AT_PREDICTION, CUTOFF_ONE_STEP_BACK),
    # A narrowing rather than a requirement, so `strictness='strict'` on its own
    # produces the whole strict policy set and `strict_config()` has no extra
    # argument to remember. `strict_causality` is the summary of "no feature may
    # read the prediction instant" that the `forcing_cutoff` entry above already
    # enforces; left settable to False it would let a report describe a run as
    # causal while the code was not.
    "strict_causality": (False, True),
}

#: Fields strict requires to hold a specific value, with no narrower default to
#: promote from. These are the policies whose *permissive* default already
#: satisfies strict, so there is nothing to promote and nothing to forgive.
STRICT_REQUIREMENTS: Mapping[str, Any] = {
    "missing_policy": MISSING_RETAIN,
    "warmup_policy": WARMUP_RETAIN,
    "state_cutoff": CUTOFF_ONE_STEP_BACK,
    "target_alignment": TARGET_EXACT,
    "accumulation_min_coverage": 1.0,
}


class FeatureConfigError(ValueError):
    """Raised when a :class:`FeatureConfig` is self-contradictory.

    Distinct from `feature_pipeline.FeatureError` (the pipeline cannot run) and
    from `feature_temporal.FeatureTemporalError` (a temporal operation is
    impossible). This one is the configuration's own fault.
    """


def _quantities(values: Sequence[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise FeatureConfigError(f"quantity must be a non-empty string, got {value!r}")
        name = value.strip()
        if name not in SUPPORTED_QUANTITIES:
            raise FeatureConfigError(
                f"unknown quantity {name!r}; Phase 3 has feature definitions for "
                f"{SUPPORTED_QUANTITIES} only. A new measurement type needs a Phase 1 "
                "domain and a Phase 3 definition, not a configuration entry"
            )
        if name not in seen:
            seen.append(name)
    return tuple(seen)


@dataclass(frozen=True)
class FeatureConfig:
    """The complete Phase 3 configuration.

    Frozen, so a dataset cannot be built with one setting and reported with
    another. The defaults are the conservative ones described in the module
    docstring: forcings may read the prediction instant, states may not; a
    cumulative sum needs a fully covered window; an uninterpretable unit is
    flagged rather than converted; nothing is imputed.
    """

    #: Which source quantities to build features from. Ordered, and the order
    #: fixes the order features appear in the registry.
    quantities: tuple[str, ...] = SUPPORTED_QUANTITIES

    #: Lags, in hours. `1` is the previous reading, `24` the same hour yesterday.
    lag_hours: tuple[float, ...] = (1.0, 3.0, 6.0)
    #: Difference spans, in hours. `water_level_change_1h` is the change across
    #: one hour of the most recent validated readings.
    change_hours: tuple[float, ...] = (1.0, 3.0)
    #: Rolling window widths, in hours.
    rolling_hours: tuple[float, ...] = (6.0,)
    #: Which order statistics each rolling window produces.
    rolling_statistics: tuple[str, ...] = (STAT_MEAN, STAT_MIN, STAT_MAX)
    #: Antecedent-accumulation windows, in hours. Rainfall only — see
    #: `feature_registry.ACCUMULABLE_QUANTITIES` for why the set is narrow.
    accumulation_hours: tuple[float, ...] = (3.0, 6.0, 24.0)
    #: Mean-rate windows, in hours. Rainfall only, and skipped entirely when the
    #: source unit cannot be interpreted.
    intensity_hours: tuple[float, ...] = (3.0,)

    #: Which calendar components and encodings to emit.
    calendar_components: tuple[str, ...] = (CAL_HOUR, CAL_DOY)
    calendar_encodings: tuple[str, ...] = (ENCODING_SIN, ENCODING_COS)

    #: The quantity being forecast, and the horizons ahead to forecast it at.
    target_quantity: str = "water_level"
    target_hours: tuple[float, ...] = (6.0,)
    target_alignment: str = TARGET_EXACT
    #: Required when `target_alignment` is `at_or_before`; how much earlier than
    #: `T + horizon` a target reading may be.
    target_tolerance_seconds: float | None = None

    #: Newest instant a *forcing* feature may read.
    forcing_cutoff: str = CUTOFF_AT_PREDICTION
    #: Newest instant a *state* feature may read.
    state_cutoff: str = CUTOFF_ONE_STEP_BACK

    #: Fraction of a window's expected sampling slots that must hold an
    #: observation before a sum is reported. `1.0` means every one.
    accumulation_min_coverage: float = 1.0
    #: The same, for rolling statistics. `0.0` means one observation suffices,
    #: which is correct for a mean: it describes what was observed.
    rolling_min_coverage: float = 0.0

    #: What to do with a row that has an absent feature value.
    missing_policy: str = MISSING_RETAIN
    #: What to do with a row that is still inside a feature's warm-up period.
    warmup_policy: str = WARMUP_RETAIN
    #: What to do when the source unit cannot be interpreted.
    unit_policy: str = UNIT_FLAG_UNDETERMINED

    #: Collapse both cutoffs to `one_step_back`: no feature may read the
    #: prediction instant at all.
    strict_causality: bool = False
    #: Declared under `permissive` or `strict`. `strict` narrows several policies
    #: below and refuses the configurations that would undo the narrowing.
    strictness: str = STRICTNESS_PERMISSIVE

    #: Label carried into the report and the dataset contract.
    subject: str = "phase3_features"

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantities", _quantities(self.quantities))
        object.__setattr__(self, "lag_hours", tuple(float(h) for h in self.lag_hours))
        object.__setattr__(self, "change_hours", tuple(float(h) for h in self.change_hours))
        object.__setattr__(self, "rolling_hours", tuple(float(h) for h in self.rolling_hours))
        object.__setattr__(
            self, "accumulation_hours", tuple(float(h) for h in self.accumulation_hours)
        )
        object.__setattr__(self, "intensity_hours", tuple(float(h) for h in self.intensity_hours))
        object.__setattr__(self, "target_hours", tuple(float(h) for h in self.target_hours))
        # These three are normalized here for the same reason the window tuples
        # above are: `to_dict` renders them as JSON lists, and a frozen dataclass
        # holding a list is neither hashable nor equal to an otherwise identical
        # one holding a tuple. Normalizing at the boundary means a configuration
        # rebuilt from its own report compares equal.
        for name in ("rolling_statistics", "calendar_components", "calendar_encodings"):
            object.__setattr__(self, name, tuple(getattr(self, name)))

        for name, values in (
            ("lag_hours", self.lag_hours),
            ("change_hours", self.change_hours),
            ("rolling_hours", self.rolling_hours),
            ("accumulation_hours", self.accumulation_hours),
            ("intensity_hours", self.intensity_hours),
            ("target_hours", self.target_hours),
        ):
            for value in values:
                if not math.isfinite(value) or value <= 0:
                    raise FeatureConfigError(
                        f"{name} must contain positive finite hour counts, got {value!r}"
                    )

        for stat in self.rolling_statistics:
            if stat not in ROLLING_STATISTICS:
                raise FeatureConfigError(
                    f"rolling statistic {stat!r} is not one of {ROLLING_STATISTICS}; "
                    "'sum' is deliberately not available here because a cumulative total has "
                    "different coverage requirements — use an accumulation window instead"
                )
        if not len(set(self.rolling_statistics)) == len(self.rolling_statistics):
            raise FeatureConfigError("rolling_statistics must not repeat a statistic")

        for component in self.calendar_components:
            if component not in CALENDAR_COMPONENTS:
                raise FeatureConfigError(
                    f"calendar component {component!r} is not one of {CALENDAR_COMPONENTS}"
                )
        for encoding in self.calendar_encodings:
            if encoding not in CALENDAR_ENCODINGS:
                raise FeatureConfigError(
                    f"calendar encoding {encoding!r} is not one of {CALENDAR_ENCODINGS}"
                )

        if self.target_quantity not in SUPPORTED_QUANTITIES:
            raise FeatureConfigError(
                f"target quantity {self.target_quantity!r} is not one of {SUPPORTED_QUANTITIES}"
            )
        if self.target_alignment not in TARGET_ALIGNMENTS:
            raise FeatureConfigError(
                f"target_alignment must be one of {TARGET_ALIGNMENTS}, got {self.target_alignment!r}"
            )
        if self.target_tolerance_seconds is not None:
            tolerance = self.target_tolerance_seconds
            if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)):
                raise FeatureConfigError(
                    f"target_tolerance_seconds must be a real number, got {tolerance!r}"
                )
            if not math.isfinite(float(tolerance)) or tolerance <= 0:
                raise FeatureConfigError(
                    f"target_tolerance_seconds must be positive and finite, got {tolerance!r}"
                )
        if self.target_alignment == TARGET_AT_OR_BEFORE:
            if self.target_tolerance_seconds is None:
                raise FeatureConfigError(
                    "target_alignment='at_or_before' requires target_tolerance_seconds: a "
                    "target taken from an unspecified earlier reading is not a forecast "
                    "horizon, it is a coincidence"
                )
        elif self.target_tolerance_seconds is not None:
            # `exact` reads the value at precisely one instant and ignores any
            # tolerance. Accepting one here would be a setting that reads as if it
            # loosened the alignment and does nothing at all.
            raise FeatureConfigError(
                "target_tolerance_seconds is only meaningful with "
                "target_alignment='at_or_before'; 'exact' matches one instant and ignores "
                f"a tolerance, so the value {self.target_tolerance_seconds!r} would be "
                "reported as a setting while having no effect"
            )

        if self.forcing_cutoff not in CUTOFFS:
            raise FeatureConfigError(f"forcing_cutoff must be one of {CUTOFFS}, got {self.forcing_cutoff!r}")
        if self.state_cutoff not in CUTOFFS:
            raise FeatureConfigError(f"state_cutoff must be one of {CUTOFFS}, got {self.state_cutoff!r}")

        for name in ("accumulation_min_coverage", "rolling_min_coverage"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise FeatureConfigError(f"{name} must be a real number, got {value!r}")
            if not 0.0 <= float(value) <= 1.0:
                raise FeatureConfigError(
                    f"{name} must be between 0 and 1 inclusive, got {value!r}"
                )

        if self.missing_policy not in MISSING_POLICIES:
            raise FeatureConfigError(f"missing_policy must be one of {MISSING_POLICIES}, got {self.missing_policy!r}")
        if self.warmup_policy not in WARMUP_POLICIES:
            raise FeatureConfigError(f"warmup_policy must be one of {WARMUP_POLICIES}, got {self.warmup_policy!r}")
        if self.unit_policy not in UNIT_POLICIES:
            raise FeatureConfigError(f"unit_policy must be one of {UNIT_POLICIES}, got {self.unit_policy!r}")
        if self.strictness not in STRICTNESS_MODES:
            raise FeatureConfigError(f"strictness must be one of {STRICTNESS_MODES}, got {self.strictness!r}")

        if self.strictness == STRICTNESS_STRICT:
            self._apply_strict()

    # --- strictness --------------------------------------------------------

    def _apply_strict(self) -> None:
        """Promote default fields to their strict value; refuse deliberate ones.

        Two rules, and the difference between them matters.

        A field still holding its **permissive default** is promoted silently.
        `strictness='strict'` is a statement about the whole configuration, so
        the caller should not also have to restate every policy that strictness
        already implies. Refusing here would make the flag unusable and would
        train callers to paste a template without reading it.

        A field holding **anything else** was chosen deliberately, so it is
        refused. Silently overriding a deliberate choice is how a caller comes
        to believe it configured one thing and has another.
        """
        conflicts: list[str] = []
        for name, (permissive_default, strict_value) in STRICT_NARROWINGS.items():
            current = getattr(self, name)
            if current == permissive_default:
                object.__setattr__(self, name, strict_value)
            elif current != strict_value:
                conflicts.append(f"{name}={current!r}; strict narrows it to {strict_value!r}")
        for name, required in STRICT_REQUIREMENTS.items():
            if getattr(self, name) != required:
                conflicts.append(f"{name}={getattr(self, name)!r}; strict requires {required!r}")
        if conflicts:
            raise FeatureConfigError(
                "strictness='strict' conflicts with: " + "; ".join(conflicts)
            )

    # --- derived quantities -------------------------------------------------

    @property
    def lag_seconds(self) -> tuple[float, ...]:
        return dedupe_windows(h * 3600.0 for h in self.lag_hours)

    @property
    def change_seconds(self) -> tuple[float, ...]:
        return dedupe_windows(h * 3600.0 for h in self.change_hours)

    @property
    def rolling_seconds(self) -> tuple[float, ...]:
        return dedupe_windows(h * 3600.0 for h in self.rolling_hours)

    @property
    def accumulation_seconds(self) -> tuple[float, ...]:
        return dedupe_windows(h * 3600.0 for h in self.accumulation_hours)

    @property
    def intensity_seconds(self) -> tuple[float, ...]:
        return dedupe_windows(h * 3600.0 for h in self.intensity_hours)

    @property
    def target_seconds(self) -> tuple[float, ...]:
        return dedupe_windows(h * 3600.0 for h in self.target_hours)

    @property
    def forcing_quantities(self) -> tuple[str, ...]:
        return tuple(q for q in self.quantities if q in FORCING_QUANTITIES)

    @property
    def state_quantities(self) -> tuple[str, ...]:
        return tuple(q for q in self.quantities if q in STATE_QUANTITIES)

    def cutoff_for(self, quantity: str) -> str:
        """The newest instant a feature on `quantity` may read."""
        if self.strict_causality:
            return CUTOFF_ONE_STEP_BACK
        return self.forcing_cutoff if quantity in FORCING_QUANTITIES else self.state_cutoff

    def include_current(self, quantity: str) -> bool:
        """Whether a window on `quantity` may end at the prediction instant."""
        return self.cutoff_for(quantity) == CUTOFF_AT_PREDICTION

    def alignment_for(self, quantity: str) -> str:
        """The window alignment a feature on `quantity` will declare."""
        return ALIGN_INCLUDE_CURRENT if self.include_current(quantity) else ALIGN_EXCLUDE_CURRENT

    def wants_accumulation(self, quantity: str) -> bool:
        return quantity in ACCUMULABLE_QUANTITIES and bool(self.accumulation_seconds)

    def wants_intensity(self, quantity: str) -> bool:
        return quantity in INTENSITY_QUANTITIES and bool(self.intensity_seconds)

    # --- reporting ---------------------------------------------------------

    @property
    def is_strict(self) -> bool:
        return self.strictness == STRICTNESS_STRICT

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "contract_version": FEATURE_CONTRACT_VERSION,
            "strictness": self.strictness,
            "strict_causality": self.strict_causality,
            "quantities": list(self.quantities),
            "forcing_quantities": list(self.forcing_quantities),
            "state_quantities": list(self.state_quantities),
            "cutoffs": {q: self.cutoff_for(q) for q in self.quantities},
            "lag_hours": list(self.lag_hours),
            "change_hours": list(self.change_hours),
            "rolling_hours": list(self.rolling_hours),
            "rolling_statistics": list(self.rolling_statistics),
            "accumulation_hours": list(self.accumulation_hours),
            "intensity_hours": list(self.intensity_hours),
            "calendar_components": list(self.calendar_components),
            "calendar_encodings": list(self.calendar_encodings),
            "target_quantity": self.target_quantity,
            "target_hours": list(self.target_hours),
            "target_alignment": self.target_alignment,
            "target_tolerance_seconds": self.target_tolerance_seconds,
            "accumulation_min_coverage": self.accumulation_min_coverage,
            "rolling_min_coverage": self.rolling_min_coverage,
            "missing_policy": self.missing_policy,
            "warmup_policy": self.warmup_policy,
            "unit_policy": self.unit_policy,
        }

    def describe(self) -> str:
        lines = [
            f"Feature config ({self.subject}, strictness={self.strictness}"
            f"{', strict_causality' if self.strict_causality else ''}):",
            f"  quantities      : {', '.join(self.quantities)}",
            f"  cutoffs         : "
            + ", ".join(f"{q}={self.cutoff_for(q)}" for q in self.quantities),
            f"  lags (hours)    : {', '.join(window_label(s) for s in self.lag_seconds)}",
            f"  change (hours)  : {', '.join(window_label(s) for s in self.change_seconds)}",
            f"  rolling (hours) : "
            + ", ".join(
                f"{window_label(s)}[{','.join(self.rolling_statistics)}]" for s in self.rolling_seconds
            ),
            f"  accum (hours)   : {', '.join(window_label(s) for s in self.accumulation_seconds)} "
            f"(min coverage {self.accumulation_min_coverage:g})",
            f"  intensity (hrs) : {', '.join(window_label(s) for s in self.intensity_seconds)}",
            f"  calendar        : {', '.join(self.calendar_components)} x "
            f"{', '.join(self.calendar_encodings)}",
            f"  target          : {self.target_quantity} at "
            f"{', '.join(window_label(s) for s in self.target_seconds)} "
            f"(alignment={self.target_alignment})",
            f"  missing/warmup  : {self.missing_policy} / {self.warmup_policy}",
            f"  units           : {self.unit_policy}",
        ]
        return "\n".join(lines)


def conservative_config(**changes: Any) -> FeatureConfig:
    """The default configuration: no imputation, full coverage, honest cutoffs."""
    return replace(FeatureConfig(), **changes)


def strict_config(**changes: Any) -> FeatureConfig:
    """Strict configuration: nothing may read the prediction instant, ever.

    Also requires an interpretable unit for every feature. Identical to
    `FeatureConfig(strictness='strict', strict_causality=True)` — provided as a
    named entry point so the strict policy set has one obvious spelling.

    Passing a contradictory setting raises rather than being overridden, so a
    caller cannot believe they got strict and not have it.
    """
    settings: dict[str, Any] = {"strictness": STRICTNESS_STRICT, "strict_causality": True}
    settings.update(changes)
    return FeatureConfig(**settings)


def build_registry(config: FeatureConfig) -> Any:
    """Compile `config` into a `feature_registry.FeatureRegistry`.

    Lives here rather than in `feature_registry` so the registry module stays a
    pure vocabulary with no dependency on configuration, and so the
    configuration is unambiguously the only thing that decides *which* features
    exist.

    The declaration order is the column order of the produced dataset and is
    itself deterministic: quantities in configuration order, then operations in
    a fixed sequence (lags, changes, rolling, accumulation, intensity), then
    windows in configuration order. Two runs with the same configuration produce
    identical columns in identical positions.
    """
    from .feature_registry import (
        OP_ACCUMULATION,
        OP_CALENDAR,
        OP_CHANGE,
        OP_INTENSITY,
        OP_LAG,
        OP_ROLLING,
        FeatureDefinition,
        FeatureRegistry,
        calendar_feature_name,
        domain_for_quantity,
        feature_name,
    )

    definitions: list[FeatureDefinition] = []
    seen: set[str] = set()

    def add(definition: FeatureDefinition) -> None:
        if definition.name in seen:  # pragma: no cover - guarded by the windows above
            raise FeatureConfigError(
                f"configuration produced the feature {definition.name!r} twice"
            )
        seen.add(definition.name)
        definitions.append(definition)

    for quantity in config.quantities:
        domain = domain_for_quantity(quantity)
        include_current = config.include_current(quantity)
        alignment = config.alignment_for(quantity)
        unit_declared = None  # Phase 3 never converts; the source unit is the feature unit.

        # --- lags -----------------------------------------------------------
        for seconds in config.lag_seconds:
            label = window_label(seconds)
            add(
                FeatureDefinition(
                    name=feature_name(quantity, OP_LAG, window=seconds),
                    operation=OP_LAG,
                    quantity=quantity,
                    source_domain=domain,
                    source_quantity=quantity,
                    window_seconds=seconds,
                    unit=unit_declared,
                    include_current=include_current,
                    description=(
                        f"{quantity} as observed {label} before the prediction instant."
                    ),
                    rationale=(
                        f"Recent {quantity} is the strongest available summary of the "
                        "catchment's present state, and the nearer the reading the less "
                        "it has had time to be superseded by a newer one."
                    ),
                )
            )

        # --- changes -------------------------------------------------------
        for seconds in config.change_seconds:
            label = window_label(seconds)
            add(
                FeatureDefinition(
                    name=feature_name(quantity, OP_CHANGE, window=seconds),
                    operation=OP_CHANGE,
                    quantity=quantity,
                    source_domain=domain,
                    source_quantity=quantity,
                    window_seconds=seconds,
                    unit=unit_declared,
                    include_current=include_current,
                    description=(
                        f"Change in {quantity} across the {label} ending at the newest "
                        f"readable instant (alignment {alignment})."
                    ),
                    rationale=(
                        "A level tells you where a river is and a change tells you which "
                        "way it is going, which is the distinction that separates a "
                        "flood in progress from a flood that has already passed. Taking "
                        "the difference also cancels any vertical datum, since both "
                        "readings come from one gauge."
                    ),
                )
            )

        # --- rolling -------------------------------------------------------
        for seconds in config.rolling_seconds:
            label = window_label(seconds)
            for stat in config.rolling_statistics:
                add(
                    FeatureDefinition(
                        name=feature_name(quantity, OP_ROLLING, window=seconds, statistic=stat),
                        operation=OP_ROLLING,
                        quantity=quantity,
                        source_domain=domain,
                        source_quantity=quantity,
                        window_seconds=seconds,
                        statistic=stat,
                        unit=unit_declared,
                        include_current=include_current,
                        description=(
                            f"{stat} of {quantity} over the {label} window ending at the "
                            f"newest readable instant (alignment {alignment})."
                        ),
                        rationale=(
                            "A window statistic separates the current reading from the "
                            "recent range it sits in, which is what distinguishes a "
                            "record from an ordinary rise."
                        ),
                    )
                )

        # --- accumulation (unit-preserving, needs coverage) -----------------
        if config.wants_accumulation(quantity):
            for seconds in config.accumulation_seconds:
                label = window_label(seconds)
                add(
                    FeatureDefinition(
                        name=feature_name(quantity, OP_ACCUMULATION, window=seconds),
                        operation=OP_ACCUMULATION,
                        quantity=quantity,
                        source_domain=domain,
                        source_quantity=quantity,
                        window_seconds=seconds,
                        unit=unit_declared,
                        include_current=include_current,
                        description=(
                            f"Total {quantity} over the {label} window ending at the "
                            f"newest readable instant, in the source unit. Requires at "
                            f"least {config.accumulation_min_coverage:g} of the window's "
                            "expected sampling slots to hold an observation."
                        ),
                        rationale=(
                            "Flood response is driven by antecedent precipitation, not by "
                            "the rain currently falling. Accumulation over several hours "
                            "is the standard measure of how much water the catchment has "
                            "already been given and has not yet shed. The sum keeps the "
                            "source unit; nothing is converted."
                        ),
                    )
                )

        # --- intensity (needs an interpretable unit) ------------------------
        if config.wants_intensity(quantity):
            for seconds in config.intensity_seconds:
                label = window_label(seconds)
                add(
                    FeatureDefinition(
                        name=feature_name(quantity, OP_INTENSITY, window=seconds),
                        operation=OP_INTENSITY,
                        quantity=quantity,
                        source_domain=domain,
                        source_quantity=quantity,
                        window_seconds=seconds,
                        unit=None,
                        include_current=include_current,
                        description=(
                            f"Mean {quantity} rate over the {label} window, in source "
                            "units per hour. Skipped when the source unit cannot be "
                            "interpreted, because an amount of unknown units per hour is "
                            "not a rate in any meaningful sense."
                        ),
                        rationale=(
                            "The same total rain concentrated in one hour produces a "
                            "different flood from the same total spread over six. An "
                            "accumulation feature cannot tell those apart; a rate can."
                        ),
                    )
                )

    # --- calendar ----------------------------------------------------------
    from .feature_registry import CALENDAR_PERIODS

    for component in config.calendar_components:
        period = CALENDAR_PERIODS[component]
        for encoding in config.calendar_encodings:
            unit_label = "hour" if component == CAL_HOUR else "day of the year"
            add(
                FeatureDefinition(
                    name=calendar_feature_name(component, encoding),
                    operation=OP_CALENDAR,
                    quantity=component,
                    source_domain="observed_at",
                    source_quantity=component,
                    statistic=encoding,
                    window_seconds=None,
                    unit=None,
                    dtype="float64",
                    entity_scope="global",
                    description=(
                        f"{encoding}(2*pi*{component}/{period:g}) — the "
                        f"{'diurnal' if component == CAL_HOUR else 'annual'} cycle of the "
                        "prediction instant."
                    ),
                    rationale=(
                        (
                            "Catchment response has a diurnal signature: evaporation, "
                            "snowmelt and abstractions all peak within a day, so the "
                            "hour a forecast is issued is informative."
                            if component == CAL_HOUR
                            else "Flood regimes are seasonal — monsoon onset, snowmelt "
                            "timing and wet-season antecedent conditions all follow the "
                            "calendar, so the time of year carries real signal."
                        )
                        + " A cyclic encoding rather than the raw integer, so that hour 23 "
                        "and hour 0 are neighbours instead of opposites."
                        + " Read from the timestamp alone, so it cannot encode an observation."
                    ),
                    required_source_fields=("observed_at",),
                )
            )

    registry = FeatureRegistry(definitions=tuple(definitions), subject=config.subject)
    return registry


__all__ = [
    "CUTOFFS",
    "CUTOFF_AT_PREDICTION",
    "CUTOFF_ONE_STEP_BACK",
    "FeatureConfig",
    "FeatureConfigError",
    "MISSING_DROP_ROWS",
    "MISSING_ERROR",
    "MISSING_POLICIES",
    "MISSING_RETAIN",
    "ROLLING_STATISTICS",
    "STATISTICS_NEEDING_TWO",
    "STAT_MAX",
    "STAT_MEAN",
    "STAT_MIN",
    "STAT_STD",
    "STRICTNESS_MODES",
    "STRICTNESS_PERMISSIVE",
    "STRICTNESS_STRICT",
    "TARGET_ALIGNMENTS",
    "TARGET_AT_OR_BEFORE",
    "TARGET_EXACT",
    "UNIT_FLAG_UNDETERMINED",
    "UNIT_POLICIES",
    "UNIT_REQUIRE_KNOWN",
    "WARMUP_DROP_ROWS",
    "WARMUP_ERROR",
    "WARMUP_POLICIES",
    "WARMUP_RETAIN",
    "build_registry",
    "conservative_config",
    "strict_config",
]
