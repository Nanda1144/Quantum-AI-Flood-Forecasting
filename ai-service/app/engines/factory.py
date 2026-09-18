"""Engine factory — resolves the active `ForecastEngine` from configuration."""

from __future__ import annotations

import importlib

from app import config
from app.engines.base import ForecastEngine
from app.engines.reference import ReferenceEngine


def get_engine() -> ForecastEngine:
    """Return the configured engine.

    `FORECAST_ENGINE=reference` uses the deterministic contract engine. Set it
    to the dotted import path of a `ForecastEngine` implementation (e.g.
    Navya's pipeline) to serve live forecasts, e.g.

        FORECAST_ENGINE=qflare.pipeline:GruFloodNetEngine
    """
    if config.FORECAST_ENGINE == "reference":
        return ReferenceEngine()
    module_path, _, class_name = config.FORECAST_ENGINE.partition(":")
    module = importlib.import_module(module_path)
    engine_class = getattr(module, class_name)
    return engine_class()