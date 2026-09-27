# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Pytest configuration for Navya's hydro-forecasting tests.

Two hard rules govern this file, because `tests/conftest.py` is shared with the
team's own `tests/test_contract.py`:

1. **It must never break the team's test run.** Everything here is guarded. If
   `numpy`/`pandas` are missing, the hydro test modules are removed from
   collection via `collect_ignore_glob` so the team sees *skipped*, not *errored*.
2. **It must not import `app.engines.hydro` at module scope**, because a failing
   import in a `conftest.py` aborts collection for the whole directory.
"""

from __future__ import annotations

import os
import sys

# --- path bootstrap ----------------------------------------------------------
# The service is started from `ai-service/` with `uvicorn app.main:app`, so `app`
# is the top-level package. Adding the directory that holds it to `sys.path` is
# a no-op when pytest already resolved it, and a fix when it has not.
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_AI_SERVICE_ROOT = os.path.dirname(_TESTS_DIR)
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

# --- optional-dependency guard ----------------------------------------------
try:  # pragma: no cover - import guard
    import numpy  # noqa: F401
    import pandas  # noqa: F401

    NUMPY_PANDAS_AVAILABLE = True
except ImportError:  # pragma: no cover - import guard
    NUMPY_PANDAS_AVAILABLE = False

if not NUMPY_PANDAS_AVAILABLE:
    # Only Navya's modules are ignored. The team's tests are untouched.
    collect_ignore_glob = ["test_hydro_*.py"]

# --- team-seam guard ---------------------------------------------------------
# `app.engines.hydro.engine` imports the team's Pydantic contract
# (`app.schemas.models`) and is checked against `app.engines.base`. Those files
# live on the team branch; on a branch that does not contain them the engine
# tests are skipped rather than failing on a missing import.
TEAM_SEAM_AVAILABLE = False
if NUMPY_PANDAS_AVAILABLE:  # pragma: no cover - import guard
    import importlib.util

    TEAM_SEAM_AVAILABLE = all(
        importlib.util.find_spec(name) is not None
        for name in ("app.schemas.models", "app.engines.base", "app.engines.factory")
    )

# --- shared fixtures ---------------------------------------------------------
# Fixtures are defined lazily inside the guard so that a missing numpy/pandas
# never turns a `conftest.py` import into a collection error.

if NUMPY_PANDAS_AVAILABLE:  # pragma: no branch
    import pandas as pd
    import pytest

    from app.engines.hydro.config import (
        DatasetSpec,
        FeatureSpec,
        HydroConfig,
        RiskPolicy,
        SplitSpec,
        TargetSpec,
    )
    from app.engines.hydro.synthetic import SyntheticSeriesSpec, generate_synthetic_series

    #: Every fixture below is SYNTHETIC/DEMO DATA. No fixture produces real
    #: hydrological observations, and no test asserts a hydrological result.
    SYNTHETIC_NOTE = "synthetic/demo fixture — not real hydrological observation data"

    def hydro_demo_frame() -> pd.DataFrame:
        """Small deterministic synthetic series (1200 hourly rows).

        Small enough to train on quickly in a unit test, large enough for a
        three-way chronological split plus a multi-row lead-time alignment.
        """
        return generate_synthetic_series(SyntheticSeriesSpec(n_rows=1200))

    def hydro_demo_config() -> HydroConfig:
        """Configuration bound to the synthetic fixture dataset.

        Declared `synthetic` throughout, with demo units and a synthetic station
        reference, so provenance is complete *and* correctly labelled.
        """
        return HydroConfig(
            enabled=True,
            dataset=DatasetSpec(
                reference="synthetic://unit-test/hydro",
                dataset_type="synthetic",
                license="none — synthetic data has no license because it is not real data",
                sampling_interval="1h",
                timestamp_column="timestamp",
                station_reference="SYNTHETIC-STATION-0001",
            ),
            target=TargetSpec(
                column="water_level",
                units="m (demo assumption — NOT datum verified)",
                horizon_hours=3,
            ),
            split=SplitSpec(train_fraction=0.6, validation_fraction=0.2),
            features=FeatureSpec(
                max_lag=4,
                rolling_windows=(3, 6),
                rainfall_column="rainfall_mm",
            ),
            risk=RiskPolicy(
                flood_threshold=None,
                threshold_source=None,
                policy_status="pending",
                band_edges=(),
            ),
            missing_policy="ffill",
            max_fill_gap=3,
            scaler="standard",
            model_name="ridge",
            ridge_alpha=1.0,
        )

    def hydro_servable_config(config: HydroConfig) -> HydroConfig:
        """`config` plus an explicitly DEMO threshold policy.

        The policy status stays `pending`: a threshold chosen by a test is not an
        approved flood stage, and the fixture must not pretend otherwise.
        """
        from dataclasses import replace

        return replace(
            config,
            risk=RiskPolicy(
                flood_threshold=5.5,
                threshold_source="DEMO value; NOT an official flood stage",
                policy_status="pending",
                band_edges=(0.1, 0.3, 0.6, 0.9),
            ),
        )

    # --- function-scoped fixtures ------------------------------------------
    # Every fixture is function-scoped by default: the objects are mutable
    # (`DataFrame`, dataclasses) and sharing one instance across tests would let
    # a test that mutates in place corrupt every later test. Tests that need
    # module-scoped lifetimes - a trained engine, a finished training run -
    # request the `shared_*` variants below, which hand out a freshly built
    # object rather than a shared one.

    @pytest.fixture
    def demo_frame() -> pd.DataFrame:
        return hydro_demo_frame()

    @pytest.fixture
    def demo_config() -> HydroConfig:
        return hydro_demo_config()

    @pytest.fixture
    def servable_config(demo_config: HydroConfig) -> HydroConfig:
        return hydro_servable_config(demo_config)

    @pytest.fixture
    def unsorted_frame(demo_frame: pd.DataFrame) -> pd.DataFrame:
        """`demo_frame` with its rows shuffled, to prove ordering is enforced."""
        return demo_frame.sample(frac=1.0, random_state=7).reset_index(drop=True)

    # --- module-scoped fixtures -------------------------------------------
    # For fixtures that represent an expensive finished computation rather than
    # input data. Each still builds a fresh object, so a test that mutates the
    # value it receives cannot affect a sibling.

    @pytest.fixture(scope="module")
    def shared_demo_frame() -> pd.DataFrame:
        return hydro_demo_frame()

    @pytest.fixture(scope="module")
    def shared_demo_config() -> HydroConfig:
        return hydro_demo_config()

    @pytest.fixture(scope="module")
    def shared_servable_config() -> HydroConfig:
        return hydro_servable_config(hydro_demo_config())
