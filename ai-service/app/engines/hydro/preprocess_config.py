# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 2 — preprocessing policy: every judgement call made explicit.

What this module is for
----------------------
Phase 1 (`domains`, `quality`, `datasets`) decides whether a record is *well
formed*. Phase 2 has to make a series of decisions that are **not** determined
by the data alone, and every one of them can be made the wrong way silently:

| Decision | The silent wrong answer |
| --- | --- |
| A naive timestamp means… | "UTC, obviously" |
| Two rows share an instant, so… | keep one, silently |
| A source disagrees with itself, so… | average them |
| A value is missing, so… | fill it |
| A unit is unfamiliar, so… | it is probably mm |
| Hourly data goes into daily bins, so… | average it like everything else |
| Splitting rows, so… | shuffle |

This module names each of those decisions, gives it a vocabulary, and picks a
**conservative default** for all of them. The defaults are the point: a caller
who configures nothing gets the behaviour that refuses to guess.

How this differs from `config.py`
---------------------------------
`config.HydroConfig` is *environment-driven dataset declaration* — where the
file is, what the target is, which model to fit. This is *preprocessing policy*:
how to clean the data. They do not overlap, and neither is a superset of the
other. `config.MISSING_POLICIES` (`ffill`/`drop`/`error`) describes the legacy
wide-`DataFrame` pipeline in `preprocessing.py`; the policies here describe the
record-level pipeline and are deliberately more conservative — see
`PREPROCESS_MISSING_POLICIES` for the difference that matters.

The approval pattern
--------------------
`conflict_policy="keep_last"` is not a preference, it is a **claim about
someone else's data**, so it requires a citation in `conflict_policy_source`.
That mirrors `config.RiskPolicy.threshold_source` and
`domains.RiskScoreRecord.threshold_source`: an approval with no evidence is not
an approval, it is an unrecorded guess. `__post_init__` refuses it.

Pure standard library. Importing this module must not drag NumPy or pandas in
behind it, for the same reason `domains.py`/`quality.py` do not.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Mapping

# --------------------------------------------------------------------------- #
# Timestamp timezone policy
# --------------------------------------------------------------------------- #

#: Refuse a timestamp that carries no UTC offset. **The default.** A naive
#: timestamp is not evidence of UTC; it is evidence that nobody recorded the
#: zone, and assuming UTC is how a series silently shifts by an offset while
#: every downstream boundary still looks self-consistent.
TIMEZONE_REQUIRE_EXPLICIT = "require_explicit"

#: Attach the zone the *source* declares (`source_timezone`). Legitimate when a
#: data supplier states "all times are Asia/Kolkata" in a data dictionary — the
#: zone comes from the supplier's documentation, not from a guess.
TIMEZONE_SOURCE_DECLARED = "source_declared"

#: Attach UTC to a naive timestamp because the caller explicitly said so. An
#: opt-in, never a default, and the report counts every instant it touched.
TIMEZONE_ASSUME_UTC = "assume_utc"

TIMEZONE_POLICIES = (
    TIMEZONE_REQUIRE_EXPLICIT,
    TIMEZONE_SOURCE_DECLARED,
    TIMEZONE_ASSUME_UTC,
)

# --------------------------------------------------------------------------- #
# Duplicate policy (identical values at one identity)
# --------------------------------------------------------------------------- #

#: Detect, count and report; change nothing. **The default.** Duplication is a
#: fact about the supplier's export that an operator should see before rows
#: disappear.
DUPLICATE_REPORT = "report"
#: Keep the first row for a duplicated identity.
DUPLICATE_KEEP_FIRST = "keep_first"
#: Keep the last row for a duplicated identity.
DUPLICATE_KEEP_LAST = "keep_last"
#: Refuse to process a batch containing exact duplicates.
DUPLICATE_ERROR = "error"

DUPLICATE_POLICIES = (
    DUPLICATE_REPORT,
    DUPLICATE_KEEP_FIRST,
    DUPLICATE_KEEP_LAST,
    DUPLICATE_ERROR,
)

#: Policies that actually remove rows. `report` and `error` are not among them,
#: so "do we delete anything?" is answerable by membership rather than by reading
#: the policy name.
DUPLICATE_REMOVING_POLICIES = frozenset({DUPLICATE_KEEP_FIRST, DUPLICATE_KEEP_LAST})

# --------------------------------------------------------------------------- #
# Conflict policy (same identity, different values)
# --------------------------------------------------------------------------- #

#: Refuse. **The default, and the only safe one without a citation.** A source
#: that reports two different values for one instant of one gauge is disagreeing
#: with itself, and this repository has no basis to pick a winner.
CONFLICT_ERROR = "error"
#: Keep the first. Requires `conflict_policy_source`.
CONFLICT_KEEP_FIRST = "keep_first"
#: Keep the last. Requires `conflict_policy_source`.
CONFLICT_KEEP_LAST = "keep_last"

CONFLICT_POLICIES = (CONFLICT_ERROR, CONFLICT_KEEP_FIRST, CONFLICT_KEEP_LAST)

CONFLICT_REMOVING_POLICIES = frozenset({CONFLICT_KEEP_FIRST, CONFLICT_KEEP_LAST})

#: There is deliberately no "average", "sum", "median" or "nearest" conflict
#: policy. Every one of them manufactures a value that no gauge ever reported,
#: and a fabricated history is worse than a refused one because it is
#: undetectable downstream. Asserted by the tests, not just documented.
CONFLICT_POLICIES_THAT_FABRICATE: tuple[str, ...] = ()

# --------------------------------------------------------------------------- #
# Missing-value policy
# --------------------------------------------------------------------------- #

#: Keep the gap, report it, change nothing. **The default.** A hydrograph gap is
#: a fact about the instrument — a sensor failure, a telemetry outage, a
#: withheld reading — and filling it asserts an observation that did not happen.
MISSING_RETAIN = "retain"
#: Refuse to process a series containing a gap.
MISSING_REJECT = "reject"
#: Remove slots that have no value.
MISSING_DROP = "drop"
#: Carry the most recent earlier value forward. **Causal** — it only ever reads
#: the past, so it cannot leak a future reading into an earlier row.
MISSING_FORWARD_FILL = "forward_fill"
#: Carry the next later value backward. **Not causal.** Acknowledgement required.
MISSING_BACKWARD_FILL = "backward_fill"
#: Continue the line through the last two *earlier* values. **Causal.**
MISSING_LINEAR_CAUSAL = "linear_causal"
#: Interpolate between the surrounding values, as `pandas.interpolate` does by
#: default. **Not causal.** Acknowledgement required, because the pandas default
#: reads to the right and this pipeline's whole purpose is to not do that.
MISSING_LINEAR_BIDIRECTIONAL = "linear_bidirectional"

PREPROCESS_MISSING_POLICIES = (
    MISSING_RETAIN,
    MISSING_REJECT,
    MISSING_DROP,
    MISSING_FORWARD_FILL,
    MISSING_BACKWARD_FILL,
    MISSING_LINEAR_CAUSAL,
    MISSING_LINEAR_BIDIRECTIONAL,
)

#: Policies that can read an instant *later* than the row being filled. Each
#: needs `allow_leakage_sensitive=True` **and** a matching entry in
#: `PreprocessConfig.acknowledged_leakage_operations` before it may be used.
LEAKAGE_SENSITIVE_MISSING_POLICIES = frozenset(
    {MISSING_BACKWARD_FILL, MISSING_LINEAR_BIDIRECTIONAL}
)

#: Policies that invent a value that no source reported. `retain`, `reject` and
#: `drop` are all conservative in different ways; the other four are not.
IMPUTING_MISSING_POLICIES = frozenset(
    {
        MISSING_FORWARD_FILL,
        MISSING_BACKWARD_FILL,
        MISSING_LINEAR_CAUSAL,
        MISSING_LINEAR_BIDIRECTIONAL,
    }
)

#: Policies that invent a value *and* only ever look backwards. The first four
#: are causal; the two in `LEAKAGE_SENSITIVE_MISSING_POLICIES` are not. Named so
#: the refusal message can point at the alternative rather than just complaining.
CAUSAL_MISSING_POLICIES = frozenset(
    {
        MISSING_FORWARD_FILL,
        MISSING_LINEAR_CAUSAL,
        MISSING_RETAIN,
        MISSING_REJECT,
        MISSING_DROP,
    }
)

# --------------------------------------------------------------------------- #
# Unit policy
# --------------------------------------------------------------------------- #

#: Convert what can be converted with a documented factor; leave an unrecognised
#: unit as `UNDETERMINED` with the value untouched, and warn. **The default.**
#: The committed synthetic sample's `inflow` column is declared
#: `"UNDETERMINED (DEMO — no unit assigned)"`, and this policy is what lets such
#: a column through honestly rather than guessing `m3/s` for it.
UNIT_PRESERVE_UNDETERMINED = "preserve_undetermined"
#: Refuse a measurement whose unit cannot be converted. For a pipeline where the
#: target unit has been declared and an undetermined unit would silently poison
#: the series.
UNIT_REQUIRE_KNOWN = "require_known"

UNIT_POLICIES = (UNIT_PRESERVE_UNDETERMINED, UNIT_REQUIRE_KNOWN)

#: The string a value keeps when no conversion exists. Says "not known" rather
#: than inventing a plausible unit.
UNDETERMINED_UNIT = "UNDETERMINED (no conversion available)"

# --------------------------------------------------------------------------- #
# Resampling policy
# --------------------------------------------------------------------------- #

#: Keep the source resolution. **The default.** Nothing in this repository
#: establishes what cadence a real gauge network reports, and downsampling an
#: hourly gauge to daily is a scientific decision, not a housekeeping one.
RESAMPLE_DISABLED = "disabled"

#: Aggregation functions available when a caller *does* opt into resampling.
#: `mean` is listed because it is common, not because it is correct for every
#: quantity — §13 of the brief is explicit that averaging everything is wrong.
AGG_SUM = "sum"
AGG_MEAN = "mean"
AGG_MIN = "min"
AGG_MAX = "max"
AGG_FIRST = "first"
AGG_LAST = "last"
AGG_COUNT = "count"

AGGREGATION_FUNCTIONS = (
    AGG_SUM,
    AGG_MEAN,
    AGG_MIN,
    AGG_MAX,
    AGG_FIRST,
    AGG_LAST,
    AGG_COUNT,
)

#: Aggregations that make physical sense for a cumulative quantity. Offered as a
#: *default* a caller can accept per quantity, never applied automatically: a
#: rainfall intensity summed over a bin is only correct if the bin is the
#: measurement window the source declared, which this repository does not know.
CUMULATIVE_QUANTITIES = ("rainfall",)

# --------------------------------------------------------------------------- #
# Split policy
# --------------------------------------------------------------------------- #

#: Cut on global time, so every entity shares the same boundaries. **The
#: default**, and the stronger leakage guarantee: an entity cannot be in train
#: for January while its neighbour is in test for the same January.
SPLIT_GLOBAL = "global"
#: Cut each entity on its own row proportions. Legitimate when the entities are
#: genuinely independent catchments, but then entity A's test period can overlap
#: entity B's training period in absolute time, which the report says out loud.
SPLIT_PER_ENTITY = "per_entity"

SPLIT_STRATEGIES = (SPLIT_GLOBAL, SPLIT_PER_ENTITY)

#: What to do with an entity that has too few rows to split three ways.
INSUFFICIENT_ERROR = "error"
#: Report the entity and exclude it from the split. Never silently: an entity
#: quietly vanishing from a dataset is how a whole catchment disappears from a
#: model without anyone deciding to drop it.
INSUFFICIENT_REPORT_AND_DROP = "report_and_drop"

INSUFFICIENT_GROUP_POLICIES = (INSUFFICIENT_ERROR, INSUFFICIENT_REPORT_AND_DROP)

#: Minimum rows an entity needs for a non-empty train/validation/test split.
#: Three is the floor — the same floor `preprocessing.chronological_split` uses.
MIN_ROWS_PER_ENTITY = 3

# --------------------------------------------------------------------------- #
# Strictness
# --------------------------------------------------------------------------- #

#: Tolerate and report. **The default.** A warning travels with the data.
STRICTNESS_PERMISSIVE = "permissive"
#: Anything that changes or discards data becomes an error unless the caller has
#: separately opted in. Useful for a curation pass, wrong for a demo — it would
#: reject the committed synthetic sample's deliberately-undetermined inflow unit.
STRICTNESS_STRICT = "strict"

STRICTNESS_MODES = (STRICTNESS_PERMISSIVE, STRICTNESS_STRICT)


# --------------------------------------------------------------------------- #
# Aggregation rules
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AggregationRule:
    """How one quantity is aggregated when its bin is collapsed.

    Declared per quantity and never inferred. A `rainfall` intensity summed over
    an hour is a depth; the same intensity averaged over an hour is a different
    quantity with the same name. Nothing in this repository knows which one a
    source meant, so the caller says, in writing, which it is.

    `unit` records the unit of the *result*, which is not always the unit of the
    input: summing `mm/h` over an hour yields `mm`, and silently keeping the
    `mm/h` label on a depth is one of the classic rainfall unit bugs.
    """

    quantity: str
    function: str
    unit: str | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, str) or not self.quantity.strip():
            raise PreprocessConfigError(
                f"AggregationRule.quantity must be a non-empty string, got {self.quantity!r}"
            )
        if self.function not in AGGREGATION_FUNCTIONS:
            raise PreprocessConfigError(
                f"AggregationRule.function must be one of {AGGREGATION_FUNCTIONS}, "
                f"got {self.function!r}"
            )
        for name in ("unit", "note"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise PreprocessConfigError(
                    f"AggregationRule.{name} must be a string or None, "
                    f"got {type(value).__name__}"
                )

    @property
    def is_cumulative(self) -> bool:
        """True for a summation, which is only right for a cumulative quantity."""
        return self.function == AGG_SUM

    def to_dict(self) -> dict[str, Any]:
        return {
            "quantity": self.quantity,
            "function": self.function,
            "unit": self.unit,
            "note": self.note,
        }


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class PreprocessConfigError(ValueError):
    """Raised when a preprocessing configuration is unusable or self-contradictory.

    A configuration error is always fatal. There is no "fall back to a sensible
    default" here, because every one of these settings exists precisely because
    a sensible-looking default would be a guess about someone else's data.
    """


# --------------------------------------------------------------------------- #
# The configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PreprocessConfig:
    """Every Phase 2 policy decision, in one immutable object.

    Constructible with no arguments, and the no-argument construction is the
    conservative one: refuse naive timestamps, report duplicates without
    removing them, refuse conflicts without a citation, keep gaps, keep
    unfamiliar units as `UNDETERMINED`, keep the source resolution, and split
    globally.
    """

    # --- timestamps --------------------------------------------------------
    timezone_policy: str = TIMEZONE_REQUIRE_EXPLICIT
    #: The zone the source documents, used only with `TIMEZONE_SOURCE_DECLARED`.
    #: A `datetime` tzinfo or a fixed offset string. `None` means "nobody said".
    source_timezone: str | None = None

    # --- duplicates and conflicts -----------------------------------------
    duplicate_policy: str = DUPLICATE_REPORT
    conflict_policy: str = CONFLICT_ERROR
    #: Required for any conflict policy other than `error`. Who approved it, and
    #: against what document.
    conflict_policy_source: str | None = None

    # --- missing values ----------------------------------------------------
    missing_policy: str = MISSING_RETAIN
    #: Longest gap a forward fill may bridge, in slots. `3` matches
    #: `preprocessing.apply_missing_policy`'s documented default; a longer gap is
    #: a genuine outage and is left visible rather than papered over.
    max_fill_gap: int = 3

    # --- units -------------------------------------------------------------
    unit_policy: str = UNIT_PRESERVE_UNDETERMINED
    #: quantity → the unit this pipeline works in. A quantity absent from this
    #: mapping is reported as undetermined; one present here with an
    #: unconvertible unit is an error under `UNIT_REQUIRE_KNOWN`.
    target_units: Mapping[str, str] = field(default_factory=dict)

    # --- resampling --------------------------------------------------------
    #: `None` or `RESAMPLE_DISABLED` keeps the source resolution.
    resample_frequency: str | None = None
    aggregations: tuple[AggregationRule, ...] = ()

    # --- splitting ---------------------------------------------------------
    split_strategy: str = SPLIT_GLOBAL
    train_fraction: float = 0.7
    validation_fraction: float = 0.15
    insufficient_group_policy: str = INSUFFICIENT_REPORT_AND_DROP

    # --- reporting / strictness -------------------------------------------
    strictness: str = STRICTNESS_PERMISSIVE
    #: Opt-in required before any leakage-sensitive policy may be used at all.
    allow_leakage_sensitive: bool = False
    #: Names of the specific leakage-sensitive operations the caller accepts.
    #: Recorded verbatim in the report so an auditor can see *what* was accepted
    #: rather than only that something was.
    acknowledged_leakage_operations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # --- free choices ----------------------------------------------------
        if self.timezone_policy not in TIMEZONE_POLICIES:
            raise PreprocessConfigError(
                f"timezone_policy must be one of {TIMEZONE_POLICIES}, got {self.timezone_policy!r}"
            )
        if self.duplicate_policy not in DUPLICATE_POLICIES:
            raise PreprocessConfigError(
                f"duplicate_policy must be one of {DUPLICATE_POLICIES}, got {self.duplicate_policy!r}"
            )
        if self.conflict_policy not in CONFLICT_POLICIES:
            raise PreprocessConfigError(
                f"conflict_policy must be one of {CONFLICT_POLICIES}, got {self.conflict_policy!r}"
            )
        if self.missing_policy not in PREPROCESS_MISSING_POLICIES:
            raise PreprocessConfigError(
                f"missing_policy must be one of {PREPROCESS_MISSING_POLICIES}, "
                f"got {self.missing_policy!r}"
            )
        if self.unit_policy not in UNIT_POLICIES:
            raise PreprocessConfigError(
                f"unit_policy must be one of {UNIT_POLICIES}, got {self.unit_policy!r}"
            )
        if self.split_strategy not in SPLIT_STRATEGIES:
            raise PreprocessConfigError(
                f"split_strategy must be one of {SPLIT_STRATEGIES}, got {self.split_strategy!r}"
            )
        if self.insufficient_group_policy not in INSUFFICIENT_GROUP_POLICIES:
            raise PreprocessConfigError(
                "insufficient_group_policy must be one of "
                f"{INSUFFICIENT_GROUP_POLICIES}, got {self.insufficient_group_policy!r}"
            )
        if self.strictness not in STRICTNESS_MODES:
            raise PreprocessConfigError(
                f"strictness must be one of {STRICTNESS_MODES}, got {self.strictness!r}"
            )

        # --- numeric ranges --------------------------------------------------
        if self.max_fill_gap < 0:
            raise PreprocessConfigError(f"max_fill_gap must be >= 0, got {self.max_fill_gap!r}")
        for name in ("train_fraction", "validation_fraction"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise PreprocessConfigError(f"{name} must be a number, got {value!r}")
            if not 0.0 < float(value) < 1.0:
                raise PreprocessConfigError(
                    f"{name} must be strictly between 0 and 1, got {value!r}"
                )
        if self.train_fraction + self.validation_fraction >= 1.0:
            raise PreprocessConfigError(
                "train_fraction + validation_fraction must leave room for a test split, "
                f"got {self.train_fraction} + {self.validation_fraction}"
            )

        # --- source timezone -------------------------------------------------
        if self.timezone_policy == TIMEZONE_SOURCE_DECLARED and not self.source_timezone:
            raise PreprocessConfigError(
                "timezone_policy='source_declared' requires source_timezone; the whole point "
                "of that policy is that the zone comes from the source's documentation, and "
                "an empty string is not documentation"
            )
        if self.source_timezone is not None and not isinstance(self.source_timezone, str):
            raise PreprocessConfigError(
                f"source_timezone must be a string or None, got {type(self.source_timezone).__name__}"
            )

        # --- approval requires a citation ------------------------------------
        if self.conflict_policy != CONFLICT_ERROR and not (
            self.conflict_policy_source and self.conflict_policy_source.strip()
        ):
            raise PreprocessConfigError(
                f"conflict_policy={self.conflict_policy!r} requires a conflict_policy_source: "
                "choosing between two disagreeing readings of one gauge instant is a decision "
                "about someone else's data and needs a citation, the same way "
                "config.RiskPolicy.threshold_source is required for an approved threshold. "
                "Leave conflict_policy='error' if nobody has approved a resolution."
            )
        object.__setattr__(
            self,
            "conflict_policy_source",
            self.conflict_policy_source.strip() if self.conflict_policy_source else None,
        )

        # --- acknowledgement of leakage-sensitive operations -----------------
        requested = self._requested_leakage_operations()
        if requested and not self.allow_leakage_sensitive:
            raise PreprocessConfigError(
                f"configuration requests leakage-sensitive operation(s) {requested} but "
                "allow_leakage_sensitive is False. These operations read an instant later than "
                "the row they fill, so a row can depend on a reading taken after it. If that is "
                "genuinely acceptable for this use, set allow_leakage_sensitive=True and name "
                f"each operation in acknowledged_leakage_operations. ({self.missing_policy!r} is "
                f"not causal; the causal fills are {sorted(CAUSAL_MISSING_POLICIES)}.)"
            )
        missing_acks = sorted(
            operation for operation in requested if operation not in self.acknowledged_leakage_operations
        )
        if missing_acks:
            raise PreprocessConfigError(
                f"leakage-sensitive operation(s) {missing_acks} are not acknowledged; add each "
                "name to PreprocessConfig.acknowledged_leakage_operations so the report can "
                "record what was accepted and why"
            )

        # --- resampling needs an explicit rule per quantity -------------------
        if self.resample_frequency is not None and self.resample_frequency != RESAMPLE_DISABLED:
            if not self.resample_frequency.strip():
                raise PreprocessConfigError(
                    "resample_frequency must be a non-blank frequency string or None"
                )
            if not self.aggregations:
                raise PreprocessConfigError(
                    "resample_frequency is set but no aggregations were declared. Downsampling "
                    "is a scientific decision: a rainfall intensity summed over an hour is a "
                    "depth, the same intensity averaged over an hour is a different quantity, and "
                    "a water level has no obviously correct average. Declare an "
                    "AggregationRule per quantity, or set resample_frequency=None to keep the "
                    "source resolution."
                )
            seen: set[str] = set()
            for rule in self.aggregations:
                if rule.quantity in seen:
                    raise PreprocessConfigError(
                        f"two AggregationRules declared for quantity {rule.quantity!r}; a quantity "
                        "is aggregated one way or not at all"
                    )
                seen.add(rule.quantity)
        elif self.aggregations:
            raise PreprocessConfigError(
                "aggregations were declared but resample_frequency is not set; aggregation rules "
                "without a frequency describe nothing. Set resample_frequency, or drop the rules."
            )
        object.__setattr__(self, "aggregations", tuple(self.aggregations))

        # --- strict mode is a coherence requirement, not a flag -------------
        if self.strictness == STRICTNESS_STRICT:
            if self.duplicate_policy in DUPLICATE_REMOVING_POLICIES:
                raise PreprocessConfigError(
                    "strictness='strict' contradicts duplicate_policy="
                    f"{self.duplicate_policy!r}: strict mode refuses to remove rows, so the only "
                    "duplicate policies available to it are 'report' and 'error'"
                )
            if self.missing_policy in IMPUTING_MISSING_POLICIES:
                raise PreprocessConfigError(
                    "strictness='strict' contradicts missing_policy="
                    f"{self.missing_policy!r}: strict mode does not fabricate observations, so it "
                    f"allows only {tuple(sorted(set(PREPROCESS_MISSING_POLICIES) - IMPUTING_MISSING_POLICIES))}"
                )
            if self.unit_policy != UNIT_REQUIRE_KNOWN:
                raise PreprocessConfigError(
                    "strictness='strict' contradicts unit_policy="
                    f"{self.unit_policy!r}: strict mode does not carry an undetermined unit "
                    "through, so it requires unit_policy='require_known'"
                )
            if self.timezone_policy == TIMEZONE_ASSUME_UTC:
                raise PreprocessConfigError(
                    "strictness='strict' contradicts timezone_policy='assume_utc': assuming a "
                    "timezone is precisely the guess strict mode exists to prevent"
                )

        # --- immutability of the unit mapping -------------------------------
        normalised: dict[str, str] = {}
        for quantity, unit in dict(self.target_units).items():
            if not isinstance(quantity, str) or not quantity.strip():
                raise PreprocessConfigError(
                    f"target_units key must be a non-empty string, got {quantity!r}"
                )
            if not isinstance(unit, str) or not unit.strip():
                raise PreprocessConfigError(
                    f"target_units[{quantity!r}] must be a non-empty string, got {unit!r}"
                )
            normalised[quantity.strip()] = unit.strip()
        object.__setattr__(self, "target_units", MappingProxyType(dict(sorted(normalised.items()))))

        object.__setattr__(
            self,
            "train_fraction",
            float(self.train_fraction),
        )
        object.__setattr__(
            self,
            "validation_fraction",
            float(self.validation_fraction),
        )
        object.__setattr__(
            self,
            "acknowledged_leakage_operations",
            tuple(str(item).strip() for item in self.acknowledged_leakage_operations if str(item).strip()),
        )

    # --- derived -----------------------------------------------------------

    @property
    def test_fraction(self) -> float:
        """Fraction reserved for the held-out test split (the remainder)."""
        return 1.0 - self.train_fraction - self.validation_fraction

    @property
    def resampling_enabled(self) -> bool:
        return self.resample_frequency is not None and self.resample_frequency != RESAMPLE_DISABLED

    @property
    def removes_duplicates(self) -> bool:
        return self.duplicate_policy in DUPLICATE_REMOVING_POLICIES

    @property
    def resolves_conflicts(self) -> bool:
        return self.conflict_policy in CONFLICT_REMOVING_POLICIES

    @property
    def imputes_missing(self) -> bool:
        return self.missing_policy in IMPUTING_MISSING_POLICIES

    @property
    def leakage_sensitive_operations(self) -> tuple[str, ...]:
        """Every leakage-sensitive operation this configuration actually requests.

        This is the honest, computed list — not what the caller asked to be
        permitted, but what is live. A report that echoed the acknowledgement
        list would claim sensitivity for operations the config never used.
        """
        return self._requested_leakage_operations()

    def _requested_leakage_operations(self) -> tuple[str, ...]:
        operations: list[str] = []
        if self.missing_policy in LEAKAGE_SENSITIVE_MISSING_POLICIES:
            operations.append(f"missing_policy:{self.missing_policy}")
        # Right-labelled bins are the only labelling this module emits, so a
        # resample never needs acknowledging. If that ever changes, this is
        # where the new sensitivity has to be declared.
        return tuple(operations)

    @property
    def is_causal(self) -> bool:
        """True when no configured operation can read a later instant.

        The single flag an auditor wants: "can any row in the output depend on a
        value from after it?"
        """
        return not self.leakage_sensitive_operations

    # --- lookups -----------------------------------------------------------

    def target_unit_for(self, quantity: str) -> str | None:
        """The declared unit for `quantity`, or `None` when nobody declared one."""
        return self.target_units.get(quantity)

    def aggregation_for(self, quantity: str) -> AggregationRule | None:
        """The declared aggregation for `quantity`, or `None`."""
        for rule in self.aggregations:
            if rule.quantity == quantity:
                return rule
        return None

    # --- derivation --------------------------------------------------------

    def with_overrides(self, **changes: Any) -> "PreprocessConfig":
        """A validated copy with the given fields replaced.

        Re-validates, so an override cannot produce a configuration that the
        constructor would have refused.
        """
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        """Machine-readable form, for the preprocessing report.

        Stable key order and plain types only, so it can go straight into JSON
        beside the record counts and boundaries.
        """
        return {
            "timezone_policy": self.timezone_policy,
            "source_timezone": self.source_timezone,
            "duplicate_policy": self.duplicate_policy,
            "conflict_policy": self.conflict_policy,
            "conflict_policy_source": self.conflict_policy_source,
            "missing_policy": self.missing_policy,
            "max_fill_gap": self.max_fill_gap,
            "unit_policy": self.unit_policy,
            "target_units": dict(self.target_units),
            "resample_frequency": self.resample_frequency,
            "aggregations": [rule.to_dict() for rule in self.aggregations],
            "resampling_enabled": self.resampling_enabled,
            "split_strategy": self.split_strategy,
            "train_fraction": self.train_fraction,
            "validation_fraction": self.validation_fraction,
            "test_fraction": self.test_fraction,
            "insufficient_group_policy": self.insufficient_group_policy,
            "strictness": self.strictness,
            "allow_leakage_sensitive": self.allow_leakage_sensitive,
            "acknowledged_leakage_operations": list(self.acknowledged_leakage_operations),
            "leakage_sensitive_operations": list(self.leakage_sensitive_operations),
            "is_causal": self.is_causal,
            "removes_duplicates": self.removes_duplicates,
            "resolves_conflicts": self.resolves_conflicts,
            "imputes_missing": self.imputes_missing,
        }


def conservative_config() -> PreprocessConfig:
    """The no-argument configuration, named.

    Provided so a caller can be explicit about wanting the defaults rather than
    inheriting them, and so the test suite has something to assert against.
    """
    return PreprocessConfig()


def strict_config(**changes: Any) -> PreprocessConfig:
    """A strict configuration, for a curation pass.

    Refuses naive timestamps, refuses undetermined units, reports duplicates
    without removing them and keeps gaps. Cannot be combined with a filling or
    duplicate-removing policy — `__post_init__` rejects the contradiction rather
    than quietly resolving it.
    """
    return PreprocessConfig(
        strictness=STRICTNESS_STRICT,
        unit_policy=UNIT_REQUIRE_KNOWN,
        timezone_policy=TIMEZONE_REQUIRE_EXPLICIT,
        missing_policy=MISSING_RETAIN,
        duplicate_policy=DUPLICATE_REPORT,
        **changes,
    )


__all__ = [
    "AGG_COUNT",
    "AGG_FIRST",
    "AGG_LAST",
    "AGG_MAX",
    "AGG_MEAN",
    "AGG_MIN",
    "AGG_SUM",
    "AGGREGATION_FUNCTIONS",
    "CONFLICT_ERROR",
    "CONFLICT_KEEP_FIRST",
    "CONFLICT_KEEP_LAST",
    "CONFLICT_POLICIES",
    "CONFLICT_POLICIES_THAT_FABRICATE",
    "CONFLICT_REMOVING_POLICIES",
    "CUMULATIVE_QUANTITIES",
    "DUPLICATE_ERROR",
    "DUPLICATE_KEEP_FIRST",
    "DUPLICATE_KEEP_LAST",
    "DUPLICATE_POLICIES",
    "DUPLICATE_REMOVING_POLICIES",
    "DUPLICATE_REPORT",
    "IMPUTING_MISSING_POLICIES",
    "INSUFFICIENT_ERROR",
    "INSUFFICIENT_GROUP_POLICIES",
    "INSUFFICIENT_REPORT_AND_DROP",
    "LEAKAGE_SENSITIVE_MISSING_POLICIES",
    "CAUSAL_MISSING_POLICIES",
    "MIN_ROWS_PER_ENTITY",
    "MISSING_BACKWARD_FILL",
    "MISSING_DROP",
    "MISSING_FORWARD_FILL",
    "MISSING_LINEAR_BIDIRECTIONAL",
    "MISSING_LINEAR_CAUSAL",
    "MISSING_REJECT",
    "MISSING_RETAIN",
    "PREPROCESS_MISSING_POLICIES",
    "RESAMPLE_DISABLED",
    "SPLIT_GLOBAL",
    "SPLIT_PER_ENTITY",
    "SPLIT_STRATEGIES",
    "STRICTNESS_MODES",
    "STRICTNESS_PERMISSIVE",
    "STRICTNESS_STRICT",
    "TIMEZONE_ASSUME_UTC",
    "TIMEZONE_POLICIES",
    "TIMEZONE_REQUIRE_EXPLICIT",
    "TIMEZONE_SOURCE_DECLARED",
    "UNDETERMINED_UNIT",
    "UNIT_POLICIES",
    "UNIT_PRESERVE_UNDETERMINED",
    "UNIT_REQUIRE_KNOWN",
    "AggregationRule",
    "PreprocessConfig",
    "PreprocessConfigError",
    "conservative_config",
    "strict_config",
]