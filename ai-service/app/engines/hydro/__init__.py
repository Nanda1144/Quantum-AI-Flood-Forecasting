# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Navya's hydrological forecasting pipeline (`app.engines.hydro`).

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
`01_Flood_Forecasting/TEAM_INTEGRATION_REQUIREMENTS.md`.
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

#: Attribute name -> (module, symbol) for the lazily-imported engine surface.
_LAZY: dict[str, tuple[str, str]] = {
    "HydroForecastEngine": (".engine", "HydroForecastEngine"),
    "EngineNotReadyError": (".engine", "EngineNotReadyError"),
}


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute access for the engine surface."""
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
