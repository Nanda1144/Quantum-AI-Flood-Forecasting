"""
Reference forecasting engine.

Deterministic generator that satisfies the `ForecastEngine` contract so the
platform is demonstrable without a trained model. This is an integration
bridge, NOT an ML pipeline. Navya replaces `get_engine()` wiring or adds her
own engine class implementing `ForecastEngine`.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app.schemas.models import (
    ForecastPoint,
    ForecastPrediction,
    ModelInfo,
    ModelMetrics,
    ModelStatus,
    PredictionRecord,
    RiskAnalytics,
    RiskDistribution,
    RiskLevel,
    RiskSummary,
    TrendDirection,
    TrendPoint,
)

MODEL_ID = "MODEL001"
MODEL_VERSION = "v1.14.0"
THRESHOLD_LEVEL = 8.0  # metres — flood stage reference for the modelled reach
HORIZON_HOURS = 24


def _round(value: float, digits: int = 3) -> float:
    factor = 10**digits
    return math.floor(value * factor + 0.5) / factor


def _hours_ago(hours: float, now: datetime) -> str:
    return (now - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def _stage(progress: float, seed: float) -> float:
    return 6.7 + progress * 1.15 + math.sin(seed * 0.9) * 0.34 + math.sin(seed * 2.7) * 0.08


def _probability_at(stage_value: float) -> float:
    exceedance = max(0.0, (stage_value - THRESHOLD_LEVEL - 1.2) / 1.6)
    return _round(min(0.985, max(0.02, 0.42 + exceedance * 0.58)), 2)


def _risk_level(probability: float) -> RiskLevel:
    if probability >= 0.85:
        return RiskLevel.CRITICAL
    if probability >= 0.65:
        return RiskLevel.HIGH
    if probability >= 0.40:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _forecast_id(now: datetime) -> str:
    day = now.strftime("%Y%m%d")
    suffix = 100 + int((now.timestamp() // 60) % 900)
    return f"FC-{day}-{suffix}"


class ReferenceEngine:
    name = "reference"

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def latest_forecast(self, horizon_hours: int = HORIZON_HOURS) -> ForecastPrediction:
        now = self._now()
        progress = (now.timestamp() % (horizon_hours * 3600)) / (horizon_hours * 3600)
        water = _round(_stage(progress, now.timestamp() / 3600))
        probability = _probability_at(water)
        return ForecastPrediction(
            forecast_id=_forecast_id(now),
            flood_probability=probability,
            risk_level=_risk_level(probability),
            predicted_water_level=water,
            forecast_horizon=f"{horizon_hours}h",
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            prediction_timestamp=_hours_ago(0.05, now),
            status="completed",
        )

    def forecast_series(self, hours: int = HORIZON_HOURS) -> list[ForecastPoint]:
        now = self._now()
        points: list[ForecastPoint] = []
        for offset in range(hours, 0, -1):
            # Sample the same daily cycle as latest_forecast, looking back `hours`.
            progress = ((now.timestamp() - offset * 3600) % (HORIZON_HOURS * 3600)) / (HORIZON_HOURS * 3600)
            raw = _stage(progress, now.timestamp() / 3600)
            points.append(
                ForecastPoint(
                    timestamp=_hours_ago(offset, now),
                    predicted_water_level=_round(raw, 2),
                    observed_water_level=_round(raw - 0.32 - math.sin(progress * 9) * 0.12, 2),
                    flood_probability=_probability_at(raw),
                )
            )
        return points

    def risk_analytics(self) -> RiskAnalytics:
        now = self._now()
        risk_trend: list[TrendPoint] = []
        probability_trend: list[TrendPoint] = []
        for offset in range(12, -1, -1):
            progress = ((now.timestamp() - offset * 3600) % (HORIZON_HOURS * 3600)) / (HORIZON_HOURS * 3600)
            stage_value = _stage(progress, now.timestamp() / 3600)
            risk_trend.append(
                TrendPoint(
                    timestamp=_hours_ago(offset, now),
                    value=_round(min(0.96, max(0.05, 0.34 + progress * 0.58 + math.sin(progress * 7) * 0.05)), 2),
                )
            )
            probability_trend.append(TrendPoint(timestamp=_hours_ago(offset, now), value=_probability_at(stage_value)))

        scale = (now.timestamp() % (HORIZON_HOURS * 3600)) / (HORIZON_HOURS * 3600)
        distribution = [
            RiskDistribution(risk_level=RiskLevel.LOW, count=14 - int(scale * 6)),
            RiskDistribution(risk_level=RiskLevel.MEDIUM, count=9 + int(scale * 2)),
            RiskDistribution(risk_level=RiskLevel.HIGH, count=5 + int(scale * 3)),
            RiskDistribution(risk_level=RiskLevel.CRITICAL, count=int(scale * 2)),
        ]
        summary = RiskSummary(
            high=next(d.count for d in distribution if d.risk_level is RiskLevel.HIGH),
            medium=next(d.count for d in distribution if d.risk_level is RiskLevel.MEDIUM),
            low=next(d.count for d in distribution if d.risk_level is RiskLevel.LOW),
            critical=next(d.count for d in distribution if d.risk_level is RiskLevel.CRITICAL),
        )
        overall = (
            TrendDirection.UP
            if risk_trend[-1].value > risk_trend[0].value + 0.06
            else TrendDirection.DOWN
            if risk_trend[-1].value < risk_trend[0].value - 0.06
            else TrendDirection.FLAT
        )
        return RiskAnalytics(
            risk_trend=risk_trend,
            probability_trend=probability_trend,
            distribution=distribution,
            summary=summary,
            overall_trend=overall,
        )

    def models(self) -> list[ModelInfo]:
        now = self._now()
        return [
            ModelInfo(
                model_id=MODEL_ID,
                name="GRU FloodNet Ensemble",
                version=MODEL_VERSION,
                algorithm="Gated Recurrent Unit ensemble + Bayesian calibration",
                status=ModelStatus.READY,
                last_trained_at=_hours_ago(72, now),
                last_evaluated_at=_hours_ago(2.5, now),
                metrics=ModelMetrics(rmse=0.231, mae=0.174, nse=0.912, accuracy=0.894),
            ),
            ModelInfo(
                model_id="MODEL002",
                name="XGBoost Stage Regressor",
                version="v2.1.3",
                algorithm="Gradient-boosted trees on lagged gauge features",
                status=ModelStatus.READY,
                last_trained_at=_hours_ago(120, now),
                last_evaluated_at=_hours_ago(30, now),
                metrics=ModelMetrics(rmse=0.29, mae=0.21, nse=0.87, accuracy=0.85),
            ),
        ]

    def model_metrics(self, model_id: str) -> ModelInfo | None:
        for model in self.models():
            if model.model_id == model_id:
                return model
        return None

    def recent_predictions(self, limit: int = 6) -> list[PredictionRecord]:
        now = self._now()
        latest = self.latest_forecast()
        records: list[PredictionRecord] = [
            PredictionRecord(
                forecast_id=latest.forecast_id,
                timestamp=latest.prediction_timestamp,
                probability=latest.flood_probability,
                risk_level=latest.risk_level,
                water_level=latest.predicted_water_level,
                model_id=MODEL_ID,
                status="completed",
            )
        ]
        for i in range(1, min(limit, 10)):
            progress = max(0.0, 1 - i * 0.16)
            probability = _probability_at(max(0.0, latest.predicted_water_level - progress * 0.95))
            records.append(
                PredictionRecord(
                    forecast_id=f"FC-{_hours_ago(i, now)[:10].replace('-', '')}-{100 + int((now.timestamp() // 60) % 900) - i}",
                    timestamp=_hours_ago(i * 1.1, now),
                    probability=probability,
                    risk_level=_risk_level(probability),
                    water_level=_round(max(0.0, latest.predicted_water_level - progress * 0.95), 2),
                    model_id="MODEL002" if i % 3 == 0 else MODEL_ID,
                    status="failed" if i == 4 else "completed",
                )
            )
        return records[:limit]