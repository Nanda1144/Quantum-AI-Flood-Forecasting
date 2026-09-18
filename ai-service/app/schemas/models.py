"""Pydantic schema definitions — the public contract of the AI service."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ModelStatus(str, Enum):
    READY = "ready"
    TRAINING = "training"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class TrendDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class ForecastPrediction(BaseModel):
    """The canonical forecast object produced by the forecasting engine."""

    model_config = ConfigDict(frozen=True)

    forecast_id: str = Field(pattern=r"^FC-\d{8}-\d{1,6}$")
    flood_probability: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    predicted_water_level: float = Field(ge=0.0)
    forecast_horizon: str
    model_id: str
    model_version: str
    prediction_timestamp: str
    status: Literal["completed", "pending", "failed"] = "completed"


class ForecastPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: str
    predicted_water_level: float = Field(ge=0.0)
    observed_water_level: float | None = Field(default=None, ge=0.0)
    flood_probability: float = Field(ge=0.0, le=1.0)


class TrendPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: str
    value: float = Field(ge=0.0, le=1.0)


class RiskDistribution(BaseModel):
    risk_level: RiskLevel
    count: int = Field(ge=0)


class RiskSummary(BaseModel):
    high: int = Field(ge=0)
    medium: int = Field(ge=0)
    low: int = Field(ge=0)
    critical: int = Field(ge=0)


class RiskAnalytics(BaseModel):
    risk_trend: list[TrendPoint]
    probability_trend: list[TrendPoint]
    distribution: list[RiskDistribution]
    summary: RiskSummary
    overall_trend: TrendDirection


class ModelMetrics(BaseModel):
    rmse: float | None = None
    mae: float | None = None
    nse: float | None = None
    accuracy: float | None = None


class ModelInfo(BaseModel):
    model_id: str
    name: str
    version: str
    algorithm: str
    status: ModelStatus
    last_trained_at: str
    last_evaluated_at: str
    metrics: ModelMetrics


class PredictionRecord(BaseModel):
    forecast_id: str
    timestamp: str
    probability: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    water_level: float = Field(ge=0.0)
    model_id: str
    status: Literal["completed", "pending", "failed"]


class SeriesResponse(BaseModel):
    points: list[ForecastPoint]


class PredictionsResponse(BaseModel):
    predictions: list[PredictionRecord]


class Envelope(BaseModel):
    """Uniform { success, data, timestamp } response body."""

    success: bool
    data: object
    timestamp: str