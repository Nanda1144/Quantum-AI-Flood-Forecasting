# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform . It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Environment-driven configuration for the hydrological forecasting pipeline.

Design rules enforced here (see `docs/forecasting/Forecast_Implementation.md`):

* **Everything dataset-dependent is configuration, never a hard-coded default.**
  The target column, its units, the forecast horizon, the station/reach
  reference, the timestamp semantics and the sampling interval are all declared
  by whoever supplies a real dataset. Nothing here invents them.
* **No official flood threshold is assumed.** `flood_threshold` defaults to
  `None` and `risk_threshold_policy` defaults to `pending`. The `8.0 m` value in
  `app.engines.reference.reference` is a demo placeholder owned by Nanda and is
  deliberately NOT reused as a real threshold here.
* **Every value can be overridden from the environment** so the engine stays
  constructible with zero arguments (see `app.engines.factory.get_engine`).
* **Unknown stays unknown.** Fields that cannot be determined are `None`; they
  are never replaced with a plausible-looking constant.

Environment variables (all optional; prefix `HYDRO_`):

| Variable | Meaning | Default |
| --- | --- | --- |
| `HYDRO_ENABLED` | Master switch. When `false`, the engine reports itself unavailable instead of forecasting. | `true` |
| `HYDRO_DATASET_PATH` | Path to the training/inference CSV. | `None` |
| `HYDRO_DATASET_REFERENCE` | Stable lineage identifier for the dataset. | `None` |
| `HYDRO_DATASET_TYPE` | `real` / `synthetic` / `unknown`. | `unknown` |
| `HYDRO_DATASET_LICENSE` | Dataset license. | `None` |
| `HYDRO_TIMESTAMP_COLUMN` | Timestamp column name. | `timestamp` |
| `HYDRO_TARGET` | Column to forecast (`water_level`, `inflow`, ...). | `water_level` |
| `HYDRO_TARGET_UNITS` | Units of the target. | `None` |
| `HYDRO_FORECAST_HORIZON_HOURS` | Lead time of a single prediction step. | `6` |
| `HYDRO_STATION_REFERENCE` | Station / reach / gauge identifier. | `None` |
| `HYDRO_EXOGENOUS_COLUMNS` | Comma-separated extra predictors actually present in the dataset. | `` (empty) |
| `HYDRO_RAINFALL_COLUMN` | Rainfall column, if the dataset has one. | `None` (auto-detected) |
| `HYDRO_ID_COLUMNS` | Columns that identify a series (grouping keys). | `` (empty) |
| `HYDRO_SAMPLING_INTERVAL` | Declared sampling interval (e.g. `1h`). | `None` (inferred) |
| `HYDRO_TRAIN_FRACTION` | Fraction of history used for training. | `0.6` |
| `HYDRO_VALIDATION_FRACTION` | Fraction used for validation. | `0.2` |
| `HYDRO_MISSING_POLICY` | `ffill` / `drop` / `error`. | `ffill` |
| `HYDRO_MAX_FILL_GAP` | Maximum consecutive NaNs a forward fill may bridge. | `3` |
| `HYDRO_MAX_LAG` | Largest lag feature to build. | `6` |
| `HYDRO_ROLLING_WINDOWS` | Comma-separated rolling window sizes (in rows). | `3,6,12` |
| `HYDRO_SCALER` | `standard` / `none`. Fitted on the training split only. | `standard` |
| `HYDRO_MODEL` | Registry key of the estimator to use. | `ridge` |
| `HYDRO_RIDGE_ALPHA` | L2 penalty for the `ridge` estimator. | `1.0` |
| `HYDRO_ARTIFACT_DIR` | Directory where model artifacts are written. | `None` |
| `HYDRO_FLOOD_THRESHOLD` | Official flood stage for the target, in `HYDRO_TARGET_UNITS`. | `None` (unknown) |
| `HYDRO_FLOOD_THRESHOLD_SOURCE` | Where the threshold came from (authority + document). | `None` |
| `HYDRO_RISK_THRESHOLD_POLICY` | `pending` / `approved`. | `pending` |
| `HYDRO_RISK_BANDS` | Comma-separated ascending probability band edges. | `` (empty) |
| `HYDRO_RISK_BAND_LABELS` | Comma-separated band labels, LOW to CRITICAL. | `LOW,MEDIUM,HIGH,CRITICAL` |
| `HYDRO_CONTRACT_VERSION` | Version tag written into every forecast payload. | `hydro-forecast/v1` |
| `HYDRO_MODEL_ID` | Model identifier reported in the forecast payload. | `NAVYA-HYDRO-001` |
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Mapping, Sequence

# Canonical values used for the discrete switches. Keeping them as module
# constants (rather than inline strings) lets the validation code and the tests
# refer to one definition.
ENABLED_VALUES = ("true", "false")
DATASET_TYPES = ("real", "synthetic", "unknown")
MISSING_POLICIES = ("ffill", "drop", "error")
SCALERS = ("standard", "none")
THRESHOLD_POLICIES = ("pending", "approved")

#: Default risk band labels, ordered from the lowest band to the highest. These
#: are the *labels* only — the numeric edges are configuration and default to
#: empty, so no band can be assigned without an explicit policy.
DEFAULT_RISK_BAND_LABELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


class ConfigError(ValueError):
    """Raised when the forecasting configuration is unusable.

    A `ConfigError` is a hard failure on purpose: silently falling back to a
    guess would produce a forecast nobody can trace back to a declared dataset,
    target and threshold, which the platform pledge forbids.
    """


def _env(source: Mapping[str, str], name: str) -> str | None:
    """Read a stripped environment value, treating blanks as absent."""
    raw = source.get(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _bool(source: Mapping[str, str], name: str, default: bool) -> bool:
    value = _env(source, name)
    if value is None:
        return default
    lowered = value.lower()
    if lowered not in ENABLED_VALUES:
        raise ConfigError(f"{name} must be one of {ENABLED_VALUES}, got {value!r}")
    return lowered == "true"


def _int(source: Mapping[str, str], name: str, default: int) -> int:
    value = _env(source, name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from exc


def _float(source: Mapping[str, str], name: str, default: float) -> float:
    value = _env(source, name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {value!r}") from exc
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        raise ConfigError(f"{name} must be a finite number, got {value!r}")
    return parsed


def _optional_float(source: Mapping[str, str], name: str) -> float | None:
    value = _env(source, name)
    if value is None:
        return None
    return _float(source, name, 0.0)  # reuse the finite check


def _csv(source: Mapping[str, str], name: str) -> tuple[str, ...]:
    value = _env(source, name)
    if value is None:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _csv_ints(source: Mapping[str, str], name: str) -> tuple[int, ...]:
    parsed: list[int] = []
    for item in _csv(source, name):
        try:
            parsed.append(int(item))
        except ValueError as exc:
            raise ConfigError(f"{name} must be a comma-separated list of integers, got {item!r}") from exc
    return tuple(parsed)


def _csv_floats(source: Mapping[str, str], name: str) -> tuple[float, ...]:
    parsed: list[float] = []
    for item in _csv(source, name):
        try:
            value = float(item)
        except ValueError as exc:
            raise ConfigError(f"{name} must be a comma-separated list of numbers, got {item!r}") from exc
        if value != value or value in (float("inf"), float("-inf")):
            raise ConfigError(f"{name} must contain finite numbers, got {item!r}")
        parsed.append(value)
    return tuple(parsed)


def _choice(source: Mapping[str, str], name: str, default: str, allowed: Sequence[str]) -> str:
    value = _env(source, name)
    if value is None:
        return default
    lowered = value.lower()
    if lowered not in allowed:
        raise ConfigError(f"{name} must be one of {tuple(allowed)}, got {value!r}")
    return lowered


@dataclass(frozen=True)
class DatasetSpec:
    """Everything a real dataset must declare before the pipeline may use it.

    This is the "data honesty" gate. The pipeline never infers provenance; the
    supplier of the dataset states it, and a missing value stays `None` all the
    way into the provenance record written next to a model artifact.
    """

    path: str | None = None
    reference: str | None = None
    dataset_type: str = "unknown"
    license: str | None = None
    sampling_interval: str | None = None
    timestamp_column: str = "timestamp"
    id_columns: tuple[str, ...] = ()
    station_reference: str | None = None

    @property
    def is_synthetic(self) -> bool:
        """True when the supplier declared the dataset synthetic/demo."""
        return self.dataset_type == "synthetic"

    def missing_fields(self) -> tuple[str, ...]:
        """Names of the honesty fields that are still unknown."""
        missing: list[str] = []
        if self.path is None:
            missing.append("path")
        if self.reference is None:
            missing.append("reference")
        if self.license is None:
            missing.append("license")
        if self.sampling_interval is None:
            missing.append("sampling_interval")
        if self.station_reference is None:
            missing.append("station_reference")
        return tuple(missing)


@dataclass(frozen=True)
class TargetSpec:
    """The forecast target and the lead time it is predicted at.

    UC-067 requires a configurable target because the repository has no
    approved decision yet. `water_level` is the default *name* only; choosing a
    different column changes both the modelling target and the units that flow
    into every downstream artifact.
    """

    column: str = "water_level"
    units: str | None = None
    horizon_hours: int = 6

    def __post_init__(self) -> None:
        if not self.column.strip():
            raise ConfigError("target column must not be blank")
        # A non-positive lead time would align each feature row with a target
        # that is not strictly in its future, which is the definition of the
        # leakage this pipeline exists to prevent.
        if self.horizon_hours <= 0:
            raise ConfigError(
                f"horizon_hours must be a positive integer, got {self.horizon_hours!r}"
            )

    def describe(self) -> str:
        """Human-readable description including the unit when known."""
        if self.units is None:
            return f"{self.column} (units unknown)"
        return f"{self.column} ({self.units})"


@dataclass(frozen=True)
class SplitSpec:
    """Chronological split ratios. The test split is always the remainder.

    There is deliberately no shuffle option: a shuffled split of a hydrological
    series leaks future conditions into the training set, so the only supported
    strategy is a contiguous time-ordered split.
    """

    train_fraction: float = 0.6
    validation_fraction: float = 0.2

    def __post_init__(self) -> None:
        for name, value in (
            ("train_fraction", self.train_fraction),
            ("validation_fraction", self.validation_fraction),
        ):
            if not 0.0 < value < 1.0:
                raise ConfigError(f"{name} must be strictly between 0 and 1, got {value!r}")
        if self.train_fraction + self.validation_fraction >= 1.0:
            raise ConfigError(
                "train_fraction + validation_fraction must leave room for a test split, "
                f"got {self.train_fraction} + {self.validation_fraction}"
            )

    @property
    def test_fraction(self) -> float:
        """Fraction reserved for the held-out test split."""
        return 1.0 - self.train_fraction - self.validation_fraction


@dataclass(frozen=True)
class RiskPolicy:
    """Configurable flood-risk policy.

    The platform ships LOW/MEDIUM/HIGH/CRITICAL band *labels*; the numeric edges
    and the flood stage that makes "flood" meaningful are dataset-dependent and
    therefore configuration. With no threshold configured, `flood_threshold` is
    `None` and no band edge exists, so the pipeline reports an *unavailable* risk
    rather than an invented one.
    """

    flood_threshold: float | None = None
    threshold_source: str | None = None
    policy_status: str = "pending"
    band_edges: tuple[float, ...] = ()
    band_labels: tuple[str, ...] = DEFAULT_RISK_BAND_LABELS

    @property
    def is_usable(self) -> bool:
        """True only when both a flood stage and at least one band edge exist."""
        return self.flood_threshold is not None and len(self.band_edges) > 0

    def describe(self) -> str:
        """One-line description that is honest about what is missing."""
        if not self.is_usable:
            return (
                "threshold policy pending: no official flood stage configured, "
                "risk bands unavailable"
            )
        return (
            f"threshold {self.flood_threshold} from {self.threshold_source or 'unrecorded source'}; "
            f"bands {list(self.band_edges)}"
        )


@dataclass(frozen=True)
class FeatureSpec:
    """Lag / rolling / temporal feature configuration.

    `max_lag` and `rolling_windows` are expressed in *rows* because the row
    count of one lag is only meaningful once the sampling interval is known;
    `preprocessing` converts them to timestamps when it can.
    """

    max_lag: int = 6
    rolling_windows: tuple[int, ...] = (3, 6, 12)
    exogenous_columns: tuple[str, ...] = ()
    rainfall_column: str | None = None
    include_calendar: bool = True

    def __post_init__(self) -> None:
        if self.max_lag < 1:
            raise ConfigError(f"max_lag must be at least 1, got {self.max_lag}")
        for window in self.rolling_windows:
            if window < 2:
                raise ConfigError(f"rolling window must be at least 2 rows, got {window}")
        if len(set(self.rolling_windows)) != len(self.rolling_windows):
            raise ConfigError(f"rolling windows must be unique, got {self.rolling_windows}")


@dataclass(frozen=True)
class HydroConfig:
    """Immutable, fully validated configuration for the hydro pipeline."""

    enabled: bool = True
    dataset: DatasetSpec = field(default_factory=DatasetSpec)
    target: TargetSpec = field(default_factory=TargetSpec)
    split: SplitSpec = field(default_factory=SplitSpec)
    features: FeatureSpec = field(default_factory=FeatureSpec)
    risk: RiskPolicy = field(default_factory=RiskPolicy)
    missing_policy: str = "ffill"
    max_fill_gap: int = 3
    scaler: str = "standard"
    model_name: str = "ridge"
    ridge_alpha: float = 1.0
    model_id: str = "NAVYA-HYDRO-001"
    artifact_dir: str | None = None
    contract_version: str = "hydro-forecast/v1"

    def __post_init__(self) -> None:
        if self.missing_policy not in MISSING_POLICIES:
            raise ConfigError(f"missing_policy must be one of {MISSING_POLICIES}, got {self.missing_policy!r}")
        if self.max_fill_gap < 0:
            raise ConfigError(f"max_fill_gap must be >= 0, got {self.max_fill_gap}")
        if self.scaler not in SCALERS:
            raise ConfigError(f"scaler must be one of {SCALERS}, got {self.scaler!r}")
        if self.target.horizon_hours < 1:
            raise ConfigError(f"forecast horizon must be at least 1 hour, got {self.target.horizon_hours}")
        if self.ridge_alpha < 0:
            raise ConfigError(f"ridge_alpha must be >= 0, got {self.ridge_alpha}")
        if not self.contract_version.strip():
            raise ConfigError("contract_version must not be blank")
        if not self.model_id.strip():
            raise ConfigError("model_id must not be blank")

    def readiness(self) -> tuple[str, ...]:
        """Blockers that stop the engine from emitting a forecast at all.

        An empty tuple means the configuration is complete enough to forecast.
        Every entry names something a human must supply — none of them can be
        resolved by a sensible default.

        Only *fabrication-avoiding* blockers belong here. A threshold that is
        configured but not formally approved does **not** block serving: the
        engine reports it with `status="pending"` and labels the bands as
        configured rather than official, which is honest. Such a state is an
        `advisories()` item, not a blocker, so that `is_ready()` and the serving
        methods can never disagree.
        """
        blockers: list[str] = []
        if self.dataset.path is None:
            blockers.append("no dataset path configured (HYDRO_DATASET_PATH)")
        if self.target.units is None:
            blockers.append("no target units configured (HYDRO_TARGET_UNITS)")
        if not self.risk.is_usable:
            blockers.append(
                "no configured flood threshold / risk band edges; the contract requires "
                "flood_probability and risk_level and this pipeline will not invent them "
                "(set HYDRO_FLOOD_THRESHOLD, HYDRO_FLOOD_THRESHOLD_SOURCE and "
                "HYDRO_RISK_BAND_EDGES)"
            )
        return tuple(blockers)

    def advisories(self) -> tuple[str, ...]:
        """Non-blocking facts an operator should know before trusting output.

        These do not prevent serving. Each one is carried into the forecast
        payload or the log line so the reader can judge the output.
        """
        notes: list[str] = []
        if self.risk.policy_status != "approved":
            notes.append(
                "flood-risk threshold policy is PENDING approval; risk bands are configured "
                "but not official (set HYDRO_RISK_THRESHOLD_POLICY=approved after sign-off)"
            )
        if self.dataset.dataset_type != "real":
            notes.append(
                f"dataset_type is {self.dataset.dataset_type!r}; only 'real' data may be "
                "reported as a hydrological result"
            )
        if self.dataset.license is None:
            notes.append("no dataset license declared (HYDRO_DATASET_LICENSE)")
        if self.dataset.reference is None:
            notes.append("no dataset reference declared (HYDRO_DATASET_REFERENCE)")
        if self.dataset.sampling_interval is None:
            notes.append(
                "no sampling interval declared; it will be inferred from the data and may "
                "remain unknown for an irregular series"
            )
        return tuple(notes)

    def is_ready(self) -> bool:
        """True when the engine may serve a forecast without inventing a value."""
        return not self.readiness()

    def with_overrides(self, **changes: object) -> "HydroConfig":
        """Return a copy with the given top-level fields replaced."""
        return replace(self, **changes)  # type: ignore[arg-type]


def _build_dataset_spec(env: Mapping[str, str]) -> DatasetSpec:
    return DatasetSpec(
        path=_env(env, "HYDRO_DATASET_PATH"),
        reference=_env(env, "HYDRO_DATASET_REFERENCE"),
        dataset_type=_choice(env, "HYDRO_DATASET_TYPE", "unknown", DATASET_TYPES),
        license=_env(env, "HYDRO_DATASET_LICENSE"),
        sampling_interval=_env(env, "HYDRO_SAMPLING_INTERVAL"),
        timestamp_column=_env(env, "HYDRO_TIMESTAMP_COLUMN") or "timestamp",
        id_columns=_csv(env, "HYDRO_ID_COLUMNS"),
        station_reference=_env(env, "HYDRO_STATION_REFERENCE"),
    )


def _build_target_spec(env: Mapping[str, str]) -> TargetSpec:
    return TargetSpec(
        column=_env(env, "HYDRO_TARGET") or "water_level",
        units=_env(env, "HYDRO_TARGET_UNITS"),
        horizon_hours=_int(env, "HYDRO_FORECAST_HORIZON_HOURS", 6),
    )


def _build_risk_policy(env: Mapping[str, str]) -> RiskPolicy:
    labels = _csv(env, "HYDRO_RISK_BAND_LABELS")
    return RiskPolicy(
        flood_threshold=_optional_float(env, "HYDRO_FLOOD_THRESHOLD"),
        threshold_source=_env(env, "HYDRO_FLOOD_THRESHOLD_SOURCE"),
        policy_status=_choice(env, "HYDRO_RISK_THRESHOLD_POLICY", "pending", THRESHOLD_POLICIES),
        band_edges=_csv_floats(env, "HYDRO_RISK_BANDS"),
        band_labels=labels or DEFAULT_RISK_BAND_LABELS,
    )


def _build_feature_spec(env: Mapping[str, str]) -> FeatureSpec:
    windows = _csv_ints(env, "HYDRO_ROLLING_WINDOWS")
    return FeatureSpec(
        max_lag=_int(env, "HYDRO_MAX_LAG", 6),
        rolling_windows=windows or (3, 6, 12),
        exogenous_columns=_csv(env, "HYDRO_EXOGENOUS_COLUMNS"),
        rainfall_column=_env(env, "HYDRO_RAINFALL_COLUMN"),
        include_calendar=_bool(env, "HYDRO_INCLUDE_CALENDAR", True),
    )


def load_config(env: Mapping[str, str] | None = None) -> HydroConfig:
    """Build a validated `HydroConfig` from the environment.

    `env` defaults to `os.environ`; tests pass an explicit mapping so they never
    depend on the developer's shell.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    return HydroConfig(
        enabled=_bool(source, "HYDRO_ENABLED", True),
        dataset=_build_dataset_spec(source),
        target=_build_target_spec(source),
        split=SplitSpec(
            train_fraction=_float(source, "HYDRO_TRAIN_FRACTION", 0.6),
            validation_fraction=_float(source, "HYDRO_VALIDATION_FRACTION", 0.2),
        ),
        features=_build_feature_spec(source),
        risk=_build_risk_policy(source),
        missing_policy=_choice(source, "HYDRO_MISSING_POLICY", "ffill", MISSING_POLICIES),
        max_fill_gap=_int(source, "HYDRO_MAX_FILL_GAP", 3),
        scaler=_choice(source, "HYDRO_SCALER", "standard", SCALERS),
        model_name=_env(source, "HYDRO_MODEL") or "ridge",
        ridge_alpha=_float(source, "HYDRO_RIDGE_ALPHA", 1.0),
        model_id=_env(source, "HYDRO_MODEL_ID") or "NAVYA-HYDRO-001",
        artifact_dir=_env(source, "HYDRO_ARTIFACT_DIR"),
        contract_version=_env(source, "HYDRO_CONTRACT_VERSION") or "hydro-forecast/v1",
    )
