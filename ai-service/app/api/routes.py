# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Nanda (API contract) + Navya (engine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README:
# no fabricated data, no invented metrics, every surrogate or fallback is
# clearly labelled, and no quantum speedup is ever claimed.

"""API route handlers for the AI service contract."""

from __future__ import annotations

from typing import Callable, TypeVar

from fastapi import APIRouter, Query

from app.core.envelope import AIError, success
from app.engines.base import ForecastEngine
from app.schemas.models import (
    Envelope,
    ForecastPrediction,
    ModelMetrics,
    PredictionRecord,
    SeriesResponse,
)

router = APIRouter()

T = TypeVar("T")


def _engine_call(operation: str, fn: Callable[[], T]) -> T:
    """Run an engine call, surfacing any failure through the error contract.

    Every endpoint goes through this so a misbehaving engine returns a
    structured ``FORECAST_ENGINE_ERROR`` (502) instead of a generic 500.
    """
    try:
        return fn()
    except AIError:
        raise
    except Exception as exc:  # noqa: BLE001 — surface engine failure through contract
        raise AIError("FORECAST_ENGINE_ERROR", f"Engine failed to produce {operation}: {exc}", 502) from exc


def build_routes(engine: ForecastEngine) -> APIRouter:
    api = APIRouter(prefix="/api/ai")

    @api.get("/forecast/latest", response_model=Envelope)
    def latest_forecast(horizon_hours: int = Query(default=24, ge=1, le=72)) -> dict:
        forecast: ForecastPrediction = _engine_call(
            "a forecast", lambda: engine.latest_forecast(horizon_hours=horizon_hours)
        )
        return success(forecast.model_dump())

    @api.get("/forecast/series", response_model=Envelope)
    def forecast_series(hours: int = Query(default=24, ge=1, le=72)) -> dict:
        points = _engine_call("a forecast series", lambda: engine.forecast_series(hours=hours))
        return success(SeriesResponse(points=points).model_dump())

    @api.get("/risk-analytics", response_model=Envelope)
    def risk_analytics() -> dict:
        return success(_engine_call("risk analytics", engine.risk_analytics).model_dump())

    @api.get("/models", response_model=Envelope)
    def models() -> dict:
        return success([m.model_dump() for m in _engine_call("the model list", engine.models)])

    @api.get("/models/{model_id}/metrics", response_model=Envelope)
    def model_metrics(model_id: str) -> dict:
        model = _engine_call("model metrics", lambda: engine.model_metrics(model_id))
        if model is None:
            raise AIError("MODEL_NOT_FOUND", f"No model found with id '{model_id}'", 404)
        metrics: ModelMetrics = model.metrics
        return success(metrics.model_dump())

    @api.get("/predictions", response_model=Envelope)
    def predictions(limit: int = Query(default=6, ge=1, le=25)) -> dict:
        records: list[PredictionRecord] = _engine_call(
            "recent predictions", lambda: engine.recent_predictions(limit=limit)
        )
        return success([r.model_dump() for r in records])

    return api