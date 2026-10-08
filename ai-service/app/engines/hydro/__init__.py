# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""the hydrological forecasting pipeline (`app.engines.hydro`).

This package is **entirely new**. Nothing the team owns is modified, removed or
re-implemented: `app/engines/base.py` (the `ForecastEngine` protocol),
`app/engines/factory.py` (the zero-argument resolver), `app/engines/reference.py`
(the labelled demo engine) and `app/schemas/models.py` (the Pydantic contract) are
all read-only inputs to this code.

Module map
----------
| Module | Responsibility |
| --- | --- |
| `config` | Environment-driven, validated configuration; every dataset-dependent fact is declared, never guessed. |
| `domains` | **Phase 1.** Record schemas for each data domain (weather, rainfall, water level, discharge, inflow, flood event, risk score) and the domain registry. Pure stdlib. |
| `quality` | **Phase 1.** Structural validation and data-quality metadata: issue codes, one-pass reporting, duplicate and conflict detection. Reports; never repairs. Pure stdlib. |
| `datasets` | **Phase 1.** Dataset descriptors and the domain-coverage matrix. What a dataset is *and what it does not contain*. Pure stdlib. |
| `preprocess_config` | **Phase 2.** Every preprocessing policy and its refusal rules, in one place. Declares what is conservative, what fabricates and what leaks. Pure stdlib. |
| `preprocess_units` | **Phase 2.** Exact documented unit conversions. Guesses nothing; an unrecognised unit becomes `UNDETERMINED` and the value is kept. Pure stdlib. |
| `preprocess_temporal` | **Phase 2.** Timestamps, ordering, cadence inference, gap grids, gap policy, right-labelled resampling, chronological splitting. Pure stdlib. |
| `preprocess_pipeline` | **Phase 2.** The orchestrator: runs the stages in order and returns records plus a machine-readable report. Pure stdlib. |
| `feature_registry` | **Phase 3.** The feature vocabulary: definitions, naming, entity scopes, lineage and the catalogue of features that cannot honestly be built. Pure stdlib. |
| `feature_config` | **Phase 3.** Every feature policy and its refusal rules — cutoffs, coverage, missing, warm-up, units, targets, strictness. Pure stdlib. |
| `feature_temporal` | **Phase 3.** Causal window arithmetic: lags, changes, accumulation, intensity, rolling statistics, calendar terms and target alignment. Pure stdlib. |
| `feature_pipeline` | **Phase 3.** The orchestrator: records in, a model-ready feature dataset plus a quality report out. Pure stdlib. |
| `preprocessing` | Validation, timestamp parsing, ordering, duplicate handling, missing-value policy, chronological split, train-fitted scaler/imputer. |
| `features` | Strictly-causal lag / rolling / rainfall / calendar features and forward-time supervision alignment. |
| `models` | Executable model registry (NumPy linear + ridge; optional scikit-learn ensembles) plus the documented-but-unimplemented roadmap. |
| `evaluation` | MAE / RMSE / R² / NSE computed from arrays; chronological evaluation reports and candidate comparison. |
| `risk` | Configurable flood-risk assessment. No default threshold; the reference engine's demo `8.0` is deliberately not reused. |
| `contract` | `ForecastOutput`, the forecast → optimization handoff, and the candidate-risk attribution specification. |
| `provenance` | Dataset / split / model provenance records. Unknown stays `null`. |
| `artifacts` | JSON artifact store with checksums, atomic writes and an opt-in pickle path. |
| `synthetic` | Deterministic SYNTHETIC/DEMO generator, clearly labelled, for runnable demos only. |
| `training` | End-to-end training, comparison, artifact writing and the CLI entrypoint. |
| `engine` | `HydroForecastEngine` behind the team's `ForecastEngine` protocol. |

Phase 1 (`domains`, `quality`, `datasets`)
----------------------------------------
The first three modules are the data / schema foundation. Importing any of them
loads nothing outside the standard library — no NumPy, no pandas, no
scikit-learn — so a schema question never drags the training stack in behind it.
See `PHASE1_DATA_FOUNDATION.md` for what they do and, more importantly, for what
they deliberately do not.

(Importing *through* this package still runs `from .synthetic import ...` below,
which needs NumPy. That is pre-existing and unchanged by Phase 1.)

They are also *additive*: they consume `config`, `contract` and `provenance`
rather than restating them, so the forecast contract's field names and the
mandatory data disclaimer each keep exactly one definition in this package.

Phase 2 (`preprocess_config`, `preprocess_units`, `preprocess_temporal`,
`preprocess_pipeline`)
------------------------------------------------------------------------------
Phase 2 turns validated Phase 1 records into a chronologically split, unit-aware,
duplicate-free, gap-aware dataset — and reports exactly what it did. Like Phase 1
it is pure standard library, and for the same reason: a preprocessing question
should not require the training stack.

See `PHASE2_PREPROCESSING.md`. The headline is what it does **not** do: Phase 2
performs no feature engineering at all. No lags, no rolling windows, no rainfall
accumulation, no flood-risk arithmetic. Those belong to `features` (Phase 3) and
`risk`, and Phase 2 has no way to reach them.

Phase 2 introduces no second validation framework and no second provenance
record. Phase 1's `QualityIssue` remains the validation vocabulary, its results
are embedded in the report under `phase1_quality`, and `SYNTHETIC_DATA_DISCLAIMER`
and `SplitBoundaries` still have exactly one definition each.

The Phase 2 entry point `preprocess` is resolved **lazily** (see `_LAZY` below)
for the same reason `engine` is: importing it must not pull NumPy in through
`synthetic`.

Phase 3 (`feature_registry`, `feature_config`, `feature_temporal`,
`feature_pipeline`)
-----------------------------------------------------------------------------
Phase 3 turns Phase 2's records into a feature dataset a model can be fitted on:
causal lags, changes, rolling statistics, rainfall accumulations and intensities,
calendar terms, and forward-time targets — each with its own column, unit and
lineage. Like Phases 1 and 2 it is pure standard library: a "what does this column
mean" question should not require the training stack, and Phase 3 adds no
dependency in order to be useful.

See `PHASE3_FEATURE_ENGINEERING.md`. The headline is what it does **not** do:
**PHASE 3 DOES NOT TRAIN MODELS.** It fits no parameter, selects no algorithm,
scores no prediction and computes no RMSE, MAE or R². Those belong to `models`,
`training` and `evaluation`, and Phase 3 has no way to reach them.

Phase 3 adds no second feature-engineering system. The pre-Phase-1 pandas layer in
`features` remains, untouched, for `training` and `engine`; `feature_*.py` is a
parallel record-based path for the same reason `preprocess_*.py` sits beside
`preprocessing.py`. Phase 3 also reuses Phase 2 rather than re-implementing it —
cadence comes from `preprocess_temporal.infer_base_interval`, units from
`preprocess_units`, splits from `preprocess_pipeline` — and imputes nothing, since
fitting an imputer belongs to Phase 4 on training rows only.

Its hard rule is point-in-time correctness: `Feature(T)` depends only on
observations at or before `T`. That is enforced structurally (every operation is a
slice ending at a cutoff), checked at runtime against the produced rows, and
verified behaviourally by deleting the future and confirming no feature changes.

Importing `engine` is **lazy** so that `app.engines.hydro.config` and friends can be
imported by tooling without pulling in the team Pydantic contract, and so the
only path that constructs the engine remains `app.engines.factory.get_engine()`.

Wiring
------
The service is started from the `ai-service/` directory (`uvicorn app.main:app`),
so `app` is the top-level package and the resolver value is::

    FORECAST_ENGINE=app.engines.hydro.engine:HydroForecastEngine

`app.engines.hydro` requires `numpy` and `pandas` (see `requirements-hydro.txt`).
`scikit-learn` is optional and unlocks two extra candidate models. None of these
are in the team's `ai-service/requirements.txt`; that file is team-owned and the
required change is recorded in
`docs/forecasting/TEAM_INTEGRATION_REQUIREMENTS.md`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .config import (
    DatasetSpec,
    FeatureSpec,
    HydroConfig,
    RiskPolicy,
    SplitSpec,
    TargetSpec,
    load_config,
)
from .datasets import (
    NO_VERIFIED_DATASETS,
    SCHEMA_VERSION,
    DatasetCatalog,
    DatasetDescriptor,
    DomainCoverage,
    committed_sample_catalog,
    coverage_matrix,
    synthetic_sample_descriptor,
)
from .domains import (
    DATA_DOMAINS,
    MEASUREMENT_DOMAINS,
    NOT_AVAILABLE,
    ColumnBinding,
    FloodEvent,
    Measurement,
    Observation,
    RiskScoreRecord,
    SchemaError,
    domain_spec,
    observations_from_row,
)
from .quality import (
    ConflictReport,
    IngestReport,
    QualityIssue,
    ValidationReport,
    check_flood_events,
    check_observation_collection,
    check_risk_records,
    ingest_observations,
    summarise,
    validate_observation,
    validate_observation_payload,
)
from .contract import (
    FORECAST_CONTRACT_VERSION,
    INTEGRATION_STATEMENT,
    CandidateRiskAttribution,
    CandidateRiskMappingSpec,
    ForecastOutput,
    OptimizationHandoff,
)
from .provenance import (
    DATASET_TYPE_REAL,
    DATASET_TYPE_SYNTHETIC,
    DATASET_TYPE_UNKNOWN,
    PENDING_THRESHOLD_DISCLAIMER,
    SYNTHETIC_DATA_DISCLAIMER,
    SYNTHETIC_METRIC_DISCLAIMER,
    ProvenanceRecord,
    SplitBoundaries,
)
from .risk import RiskAssessment, RiskAssessor
from .synthetic import SYNTHETIC_REFERENCE_PREFIX, SyntheticSeriesSpec, generate_synthetic_series

if TYPE_CHECKING:  # pragma: no cover - type-checking only
    from .engine import EngineNotReadyError, HydroForecastEngine

__all__ = [
    # configuration
    "HydroConfig",
    "DatasetSpec",
    "TargetSpec",
    "SplitSpec",
    "FeatureSpec",
    "RiskPolicy",
    "load_config",
    # Phase 1 — data / schema foundation (pure stdlib, no NumPy/pandas)
    "DATA_DOMAINS",
    "MEASUREMENT_DOMAINS",
    "NOT_AVAILABLE",
    "ColumnBinding",
    "FloodEvent",
    "Measurement",
    "Observation",
    "RiskScoreRecord",
    "SchemaError",
    "domain_spec",
    "observations_from_row",
    "ConflictReport",
    "IngestReport",
    "QualityIssue",
    "ValidationReport",
    "check_flood_events",
    "check_observation_collection",
    "check_risk_records",
    "ingest_observations",
    "summarise",
    "validate_observation",
    "validate_observation_payload",
    "DatasetCatalog",
    "DatasetDescriptor",
    "DomainCoverage",
    "NO_VERIFIED_DATASETS",
    "SCHEMA_VERSION",
    "committed_sample_catalog",
    "coverage_matrix",
    "synthetic_sample_descriptor",
    # Phase 2 — preprocessing (pure stdlib; resolved lazily, see `_LAZY`)
    "PreprocessConfig",
    "PreprocessConfigError",
    "PreprocessError",
    "PreprocessingReport",
    "PreprocessingResult",
    "conservative_config",
    "preprocess",
    "strict_config",
    # Phase 3 — feature engineering (pure stdlib; resolved lazily, see `_LAZY`)
    "FeatureConfig",
    "FeatureConfigError",
    "FeatureError",
    "FeatureResult",
    "FeatureQualityReport",
    "ModelReadyDataset",
    "build_features",
    "conservative_feature_config",
    "strict_feature_config",
    # contract
    "ForecastOutput",
    "OptimizationHandoff",
    "CandidateRiskAttribution",
    "CandidateRiskMappingSpec",
    "FORECAST_CONTRACT_VERSION",
    "INTEGRATION_STATEMENT",
    # provenance
    "ProvenanceRecord",
    "SplitBoundaries",
    "DATASET_TYPE_REAL",
    "DATASET_TYPE_SYNTHETIC",
    "DATASET_TYPE_UNKNOWN",
    "SYNTHETIC_DATA_DISCLAIMER",
    "SYNTHETIC_METRIC_DISCLAIMER",
    "PENDING_THRESHOLD_DISCLAIMER",
    # risk
    "RiskAssessor",
    "RiskAssessment",
    # synthetic
    "SyntheticSeriesSpec",
    "generate_synthetic_series",
    "SYNTHETIC_REFERENCE_PREFIX",
    # engine (lazy)
    "HydroForecastEngine",
    "EngineNotReadyError",
]

#: Attribute name -> (module, symbol) for the lazily-imported surfaces.
#:
#: Two groups, one mechanism, two different reasons.
#:
#: The engine is lazy because importing it pulls in the team Pydantic contract,
#: and only `app.engines.factory.get_engine()` should build it.
#:
#: Phase 2 and Phase 3 are lazy because they are standard-library-only and say so:
#: exposing `preprocess` or `build_features` here as eager imports would make
#: `from app.engines.hydro import build_features` load NumPy via `synthetic`, and the
#: purity claim would only be reachable by importing the submodule directly. Lazy
#: resolution keeps `from app.engines.hydro import build_features` honest.
_LAZY: dict[str, tuple[str, str]] = {
    "HydroForecastEngine": (".engine", "HydroForecastEngine"),
    "EngineNotReadyError": (".engine", "EngineNotReadyError"),
    "preprocess": (".preprocess_pipeline", "preprocess"),
    "PreprocessError": (".preprocess_pipeline", "PreprocessError"),
    "PreprocessingReport": (".preprocess_pipeline", "PreprocessingReport"),
    "PreprocessingResult": (".preprocess_pipeline", "PreprocessingResult"),
    "PreprocessConfig": (".preprocess_config", "PreprocessConfig"),
    "PreprocessConfigError": (".preprocess_config", "PreprocessConfigError"),
    "conservative_config": (".preprocess_config", "conservative_config"),
    "strict_config": (".preprocess_config", "strict_config"),
    "build_features": (".feature_pipeline", "build_features"),
    "FeatureError": (".feature_pipeline", "FeatureError"),
    "FeatureResult": (".feature_pipeline", "FeatureResult"),
    "FeatureQualityReport": (".feature_pipeline", "FeatureQualityReport"),
    "ModelReadyDataset": (".feature_pipeline", "ModelReadyDataset"),
    "FeatureConfig": (".feature_config", "FeatureConfig"),
    "FeatureConfigError": (".feature_config", "FeatureConfigError"),
    "conservative_feature_config": (".feature_config", "conservative_config"),
    "strict_feature_config": (".feature_config", "strict_config"),
}


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute access for the engine and the Phase 2 / Phase 3 surfaces.

    The lazy map holds entry points and their result types, not every constant:
    a caller who wants a policy constant reaches for the module that declares it,
    where the documentation lives beside the code that uses it.
    """
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module = import_module(target[0], __name__)
    value = getattr(module, target[1])
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
