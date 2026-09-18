"""API route handlers for the AI service contract."""

from __future__ import annotations

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


def build_routes(engine: ForecastEngine) -> APIRouter:
    api = APIRouter(prefix="/api/ai")

    @api.get("/forecast/latest", response_model=Envelope)
    def latest_forecast(horizon_hours: int = Query(default=24, ge=1, le=72)) -> dict:
        try:
            forecast: ForecastPrediction = engine.latest_forecast(horizon_hours=horizon_hours)
        except Exception as exc:  # noqa: BLE001 — surface engine failure through contract
            raise AIError("FORECAST_ENGINE_ERROR", f"Engine failed to produce a forecast: {exc}", 502) from exc
        return success(forecast.model_dump())

    @api.get("/forecast/series", response_model=Envelope)
    def forecast_series(hours: int = Query(default=24, ge=1, le=72)) -> dict:
        points = engine.forecast_series(hours=hours)
        return success(SeriesResponse(points=points).model_dump())

    @api.get("/risk-analytics", response_model=Envelope)
    def risk_analytics() -> dict:
        return success(engine.risk_analytics().model_dump())

    @api.get("/models", response_model=Envelope)
    def models() -> dict:
        return success([m.model_dump() for m in engine.models()])

    @api.get("/models/{model_id}/metrics", response_model=Envelope)
    def model_metrics(model_id: str) -> dict:
        model = engine.model_metrics(model_id)
        if model is None:
            raise AIError("MODEL_NOT_FOUND", f"No model found with id '{model_id}'", 404)
        metrics: ModelMetrics = model.metrics
        return success(metrics.model_dump())

    @api.get("/predictions", response_model=Envelope)
    def predictions(limit: int = Query(default=6, ge=1, le=25)) -> dict:
        records: list[PredictionRecord] = engine.recent_predictions(limit=limit)
        return success([r.model_dump() for r in records])

    return api