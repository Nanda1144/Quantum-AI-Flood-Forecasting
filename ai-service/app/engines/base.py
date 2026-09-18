"""Forecast engine contract (the seam where Navya's pipeline plugs in).

Navya owns the forecasting models. She implements this protocol — swapping
XGBoost / LSTM / GRU behind it — and the REST contract, the Node backend, and
the Q-FLARE frontend remain untouched.

A "short docstring model" is used on purpose: the protocol describes WHAT an
engine must provide; engines decide HOW.
"""

from __future__ import annotations

from typing import Protocol

from app.schemas.models import (
    ForecastPrediction,
    ForecastPoint,
    ModelInfo,
    PredictionRecord,
    RiskAnalytics,
)


class ForecastEngine(Protocol):
    """Contract every forecasting engine must satisfy."""

    name: str

    def latest_forecast(self, horizon_hours: int = 24) -> ForecastPrediction: ...

    def forecast_series(self, hours: int = 24) -> list[ForecastPoint]: ...

    def risk_analytics(self) -> RiskAnalytics: ...

    def models(self) -> list[ModelInfo]: ...

    def model_metrics(self, model_id: str) -> ModelInfo | None: ...

    def recent_predictions(self, limit: int = 6) -> list[PredictionRecord]: ...