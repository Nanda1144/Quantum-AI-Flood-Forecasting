"""Contract tests for the AI service — validate the envelope, shapes, and errors."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_online() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["service"] == "ai-service"
    assert body["data"]["status"] == "online"
    assert body["data"]["engine"] == "reference"


def test_latest_forecast_contract() -> None:
    res = client.get("/api/ai/forecast/latest")
    assert res.status_code == 200
    forecast = res.json()["data"]
    assert forecast["forecast_id"].startswith("FC-")
    assert 0.0 <= forecast["flood_probability"] <= 1.0
    assert forecast["risk_level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert forecast["predicted_water_level"] > 0
    assert forecast["forecast_horizon"] == "24h"
    assert forecast["model_id"]
    assert forecast["status"] == "completed"


def test_forecast_series_and_risk_analytics() -> None:
    series = client.get("/api/ai/forecast/series").json()["data"]["points"]
    assert len(series) == 24
    point = series[0]
    assert "timestamp" in point
    assert 0 < point["predicted_water_level"] < 50
    assert 0.0 <= point["flood_probability"] <= 1.0
    for p in series:
        assert 0 < p["predicted_water_level"] < 50

    risk = client.get("/api/ai/risk-analytics").json()["data"]
    assert len(risk["risk_trend"]) > 0
    assert len(risk["probability_trend"]) > 0
    assert len(risk["distribution"]) == 4
    assert risk["overall_trend"] in {"up", "down", "flat"}
    for p in risk["risk_trend"]:
        assert 0.0 < p["value"] <= 1.0
    for p in risk["probability_trend"]:
        assert 0.0 <= p["value"] <= 1.0
    assert len({p["value"] for p in risk["risk_trend"]}) > 1, "risk trend must actually vary"


def test_models_and_metrics() -> None:
    models = client.get("/api/ai/models").json()["data"]
    assert models, "expected at least one model"
    first = models[0]
    assert first["model_id"]
    assert isinstance(first["metrics"]["rmse"], float)

    metrics = client.get(f"/api/ai/models/{first['model_id']}/metrics").json()["data"]
    assert metrics["accuracy"] is not None

    missing = client.get("/api/ai/models/DOES_NOT_EXIST/metrics")
    assert missing.status_code == 404
    err = missing.json()
    assert err["success"] is False
    assert err["error"]["code"] == "MODEL_NOT_FOUND"


def test_horizon_validation_surfaces_error() -> None:
    res = client.get("/api/ai/forecast/latest", params={"horizon_hours": 999})
    assert res.status_code == 422
    body = res.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"