# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""B4 — the configured serving engine: `FORECAST_ENGINE` seam activation.

These tests prove, in-process, that the documented configuration

    FORECAST_ENGINE=app.engines.hydro.engine:HydroForecastEngine

resolves through the team's untouched factory to `HydroForecastEngine`, that the
engine serves a forecast end-to-end from a demo/synthetic dataset loaded through
the environment, that an unconfigured engine refuses honestly (dependency
blocked), and that the HTTP API built on the same wiring either surfaces a
served synthetic forecast or the canonical `502 FORECAST_ENGINE_ERROR` — never a
silently substituted engine and never a fabricated number.

Like every hydro test module, this file skips when numpy/pandas are missing or
when the team seam (`app/schemas/models.py`, `app/engines/base.py`,
`app/engines/factory.py`) is absent, so the team's run can never be broken by it.
"""

from __future__ import annotations

import importlib.util
import os

import pytest

pd = pytest.importorskip("pandas")


def _seam_available() -> bool:
    return all(
        importlib.util.find_spec(name) is not None
        for name in ("app.schemas.models", "app.engines.base", "app.engines.factory")
    )


if not _seam_available():
    # A mark would only suppress execution; the module-level imports below still
    # run during collection and would raise ModuleNotFoundError, which pytest
    # reports as a collection ERROR that interrupts the whole run.
    pytest.skip(
        "requires the team seam (app/schemas/models.py, app/engines/base.py, "
        "app/engines/factory.py); those files are team-owned and are not present "
        "on this branch. Runs after the integration merge.",
        allow_module_level=True,
    )

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config as app_config  # noqa: E402
from app.api.routes import build_routes  # noqa: E402
from app.core.envelope import register_error_handlers  # noqa: E402
from app.engines.factory import get_engine  # noqa: E402
from app.engines.hydro.engine import (  # noqa: E402
    EngineNotReadyError,
    HydroForecastEngine,
)
from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER  # noqa: E402
from app.engines.hydro.synthetic import (  # noqa: E402
    SyntheticSeriesSpec,
    generate_synthetic_series,
)

#: The one and only value B4 wires through the seam.
HYDRO_ENGINE_PATH = "app.engines.hydro.engine:HydroForecastEngine"


def _clear_hydro_env(monkeypatch) -> None:
    """Drop every HYDRO_* variable so tests never depend on the developer shell."""
    for name in list(os.environ):
        if name.startswith("HYDRO_"):
            monkeypatch.delenv(name, raising=False)


def _configure_seam(tmp_path, monkeypatch) -> None:
    """Point the whole seam at a synthetic CSV through the environment only.

    The dataset is written by the labelled synthetic writer's generator, so the
    `synthetic` type declaration and the disclaimer that travels with it are
    already the platform's own, not values invented by this test.
    """
    _clear_hydro_env(monkeypatch)
    frame = generate_synthetic_series(SyntheticSeriesSpec(n_rows=1200))
    csv_path = tmp_path / "synthetic_hydro.csv"
    frame.to_csv(csv_path, index=False)

    env: dict[str, str] = {
        "HYDRO_DATASET_PATH": str(csv_path),
        "HYDRO_DATASET_TYPE": "synthetic",
        "HYDRO_DATASET_REFERENCE": "synthetic://unit-test/b4-seam",
        "HYDRO_DATASET_LICENSE": "none -- synthetic demo data has no license",
        "HYDRO_SAMPLING_INTERVAL": "1h",
        "HYDRO_TIMESTAMP_COLUMN": "timestamp",
        "HYDRO_STATION_REFERENCE": "SYNTHETIC-STATION-0001",
        "HYDRO_TARGET": "water_level",
        "HYDRO_TARGET_UNITS": "m (demo assumption -- NOT datum verified)",
        "HYDRO_FORECAST_HORIZON_HOURS": "3",
        "HYDRO_FLOOD_THRESHOLD": "5.5",
        "HYDRO_FLOOD_THRESHOLD_SOURCE": "DEMO value; NOT an official flood stage",
        "HYDRO_RISK_THRESHOLD_POLICY": "pending",
        "HYDRO_RISK_BANDS": "0.1,0.3,0.6,0.9",
        "HYDRO_RAINFALL_COLUMN": "rainfall_mm",
        "HYDRO_MODEL": "ridge",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    # `app/engines/factory.py` reads the module attribute, not the environment
    # (it was bound at import time), so both are patched exactly as the existing
    # seam contract test does.
    monkeypatch.setattr(app_config, "FORECAST_ENGINE", HYDRO_ENGINE_PATH)


def _http_client(engine: HydroForecastEngine) -> TestClient:
    """A FastAPI app wired exactly like `app.main`: routes + error handlers."""
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(build_routes(engine))
    return TestClient(app, raise_server_exceptions=False)


# --------------------------------------------------------------------------- #
# Engine loading (task §5)
# --------------------------------------------------------------------------- #


def test_the_configured_engine_path_resolves_to_hydro(monkeypatch):
    monkeypatch.setattr(app_config, "FORECAST_ENGINE", HYDRO_ENGINE_PATH)
    engine = get_engine()
    assert isinstance(engine, HydroForecastEngine)
    assert engine.name == "navya-hydro"


def test_an_invalid_engine_configuration_fails_safely_and_never_substitutes(monkeypatch):
    """A bad path must raise loudly, never fall back to the reference engine."""
    from app.engines.reference import ReferenceEngine

    cases = (
        ("no.such.module:Engine", (ModuleNotFoundError, ImportError)),
        ("app.engines.hydro.engine:NoSuchClass", AttributeError),
        ("not-a-dotted-path-without-a-class", (ModuleNotFoundError, ImportError)),
    )
    for value, errors in cases:
        monkeypatch.setattr(app_config, "FORECAST_ENGINE", value)
        with pytest.raises(errors):
            get_engine()
    # Proof of non-substitution: the default selector still returns the labelled
    # demo/fallback engine and nothing else.
    monkeypatch.setattr(app_config, "FORECAST_ENGINE", "reference")
    assert isinstance(get_engine(), ReferenceEngine)


# --------------------------------------------------------------------------- #
# In-process serving through the factory (task §6)
# --------------------------------------------------------------------------- #


def test_factory_serves_a_synthetic_forecast_via_the_seam(tmp_path, monkeypatch):
    _configure_seam(tmp_path, monkeypatch)
    engine = get_engine()
    assert isinstance(engine, HydroForecastEngine)

    forecast = engine.latest_forecast(3)
    assert forecast.model_id == "NAVYA-HYDRO-001"
    assert forecast.forecast_horizon == "3h"
    assert forecast.status == "pending"
    assert 0.0 <= forecast.flood_probability <= 1.0
    assert forecast.risk_level is not None
    assert forecast.predicted_water_level is not None


def test_the_served_forecast_carries_the_mandatory_synthetic_disclaimer(tmp_path, monkeypatch):
    _configure_seam(tmp_path, monkeypatch)
    engine = get_engine()
    output = engine.contract()
    assert output is not None
    assert output.disclaimer == (
        "THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL "
        "HYDROLOGICAL OBSERVATION DATA."
    )
    assert output.disclaimer == SYNTHETIC_DATA_DISCLAIMER


# --------------------------------------------------------------------------- #
# Dependency-blocked behaviour (task §7)
# --------------------------------------------------------------------------- #


def test_unconfigured_engine_refuses_and_names_the_prerequisites(monkeypatch):
    _clear_hydro_env(monkeypatch)
    engine = HydroForecastEngine()
    assert engine.is_ready() is False

    blockers = " ".join(engine.readiness())
    assert "HYDRO_DATASET_PATH" in blockers
    assert "HYDRO_TARGET_UNITS" in blockers
    assert "HYDRO_FLOOD_THRESHOLD" in blockers

    with pytest.raises(EngineNotReadyError) as excinfo:
        engine.latest_forecast(24)
    message = str(excinfo.value)
    # The honest refusal names the missing prerequisite; it is a raised blocker,
    # never a served baseline number and never a fabricated probability.
    assert "no dataset configured" in message
    assert "SYNTHETIC" in message or "synthetic" in message


# --------------------------------------------------------------------------- #
# HTTP surface: API/client -> factory -> HydroForecastEngine -> serving (task §6/§12)
# --------------------------------------------------------------------------- #


def test_the_api_serves_through_the_configured_engine(tmp_path, monkeypatch):
    _configure_seam(tmp_path, monkeypatch)
    engine = get_engine()  # the configured engine, built by the untouched factory
    client = _http_client(engine)

    res = client.get("/api/ai/forecast/latest?horizon_hours=3")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    data = body["data"]
    # The hydro engine served — the API never substituted the reference engine.
    assert data["model_id"] == "NAVYA-HYDRO-001"
    assert data["status"] == "pending"
    assert 0.0 <= data["flood_probability"] <= 1.0
    assert data["risk_level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def test_the_api_exposes_the_dependency_blocked_refusal_as_502(monkeypatch):
    _clear_hydro_env(monkeypatch)
    client = _http_client(HydroForecastEngine())

    res = client.get("/api/ai/forecast/latest")
    assert res.status_code == 502
    body = res.json()
    assert body["success"] is False
    assert body["error"]["code"] == "FORECAST_ENGINE_ERROR"
    assert "no dataset configured" in body["error"]["message"]
    assert "data" not in body