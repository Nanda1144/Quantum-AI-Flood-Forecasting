# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README:
# no fabricated data, no invented metrics, every surrogate or fallback is
# clearly labelled, and no quantum speedup is ever claimed.

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