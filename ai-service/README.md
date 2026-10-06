# ai-service — Q-FLARE AI Forecasting API (FastAPI)

The **AI FastAPI service** in the platform's data path:

```
React → Node backend → AI FastAPI service → PostgreSQL → React
```

This service exposes the forecasting pipeline through a **stable REST
contract**. Nanda's Node backend (`../backend`) is its only consumer; the
browser never talks to it directly.

> **Ownership boundary:** Navya owns the actual forecasting models
> (XGBoost / LSTM / GRU). This package is the *integration seam*: it defines
> the `ForecastEngine` protocol and ships a **reference engine** that produces
> deterministic sample forecasts so the platform works end-to-end. It does
> **not** train or fit any model, and it does not re-implement Navya's
> pipeline. Navya swaps in her engine behind the protocol — the REST contract,
> the Node backend, and the frontend stay untouched.

---

## Quick start

Requires Python 3.12+ (tested on 3.14).

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # (Windows)
# source .venv/bin/activate && pip install -r requirements.txt   # (macOS/Linux)

cp .env.example .env        # adjust env as needed

.venv/Scripts/python -m uvicorn app.main:app --port 8000
# or after activation:
uvicorn app.main:app --port 8000
```

Run the contract tests:

```sh
.venv/Scripts/python -m pytest tests -q
```

Interactive API browser: http://localhost:8000/docs

## Endpoints

All responses use the shared envelope (`{ success, data, timestamp }`; errors:
`{ success: false, error: { code, message } }`). Errors exit non-2xx.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Service availability + active engine. |
| `GET` | `/api/ai/forecast/latest` | Latest forecast (`?horizon_hours=1..72`). |
| `GET` | `/api/ai/forecast/series` | Water-level series (`?hours=1..72`). |
| `GET` | `/api/ai/risk-analytics` | Risk trend + probability trend + distribution. |
| `GET` | `/api/ai/models` | Registered model versions. |
| `GET` | `/api/ai/models/{model_id}/metrics` | Stored evaluation metrics. |
| `GET` | `/api/ai/predictions` | Recent prediction records (`?limit=1..25`). |

### Forecast object (canonical)

```json
{
  "forecast_id": "FC-20260916-422",
  "flood_probability": 0.42,
  "risk_level": "MEDIUM",
  "predicted_water_level": 7.606,
  "forecast_horizon": "24h",
  "model_id": "MODEL001",
  "model_version": "v1.14.0",
  "prediction_timestamp": "2026-09-16T...+00:00",
  "status": "completed"
}
```

The Node backend maps this snake_case payload into the camelCase contract the
frontend already consumes (see `backend/src/types`).

## Pluggable engine (Navya's seam)

The active engine is resolved by `app/engines/factory.py`:

- `FORECAST_ENGINE=reference` (default) → `ReferenceEngine`, deterministic.
- `FORECAST_ENGINE=<module>:<ClassName>` → your live pipeline, e.g.
  `FORECAST_ENGINE=floodnet.gru:GruFloodNetEngine`.

Implement the protocol in `app/engines/base.py`:

```python
class ForecastEngine(Protocol):
    name: str
    def latest_forecast(self, horizon_hours: int = 24) -> ForecastPrediction: ...
    def forecast_series(self, hours: int = 24) -> list[ForecastPoint]: ...
    def risk_analytics(self) -> RiskAnalytics: ...
    def models(self) -> list[ModelInfo]: ...
    def model_metrics(self, model_id: str) -> ModelInfo | None: ...
    def recent_predictions(self, limit: int = 6) -> list[PredictionRecord]: ...
```

Swapping XGBoost → LSTM → GRU (or any implementation) never changes the Node
backend or the frontend because they depend only on this contract.

## Source layout

```
app/
├── main.py                 # FastAPI app + latency middleware + health
├── config.py               # env config
├── core/envelope.py        # shared success/error envelopes
├── schemas/models.py       # pydantic contract types (OpenAPI surface)
├── api/routes.py           # route handlers
└── engines/
    ├── base.py             # ForecastEngine protocol        ← Navya implements
    ├── reference.py        # deterministic reference engine  ← replace in prod
    └── factory.py          # engine resolution from env
tests/test_contract.py      # envelope + payload contract tests
```

## Environment variables (`ai-service/.env`)

| Variable | Default | Description |
| --- | --- | --- |
| `AI_SERVICE_HOST` | `0.0.0.0` | Listener host. |
| `AI_SERVICE_PORT` | `8000` | Listener port (the Node backend calls this). |
| `FORECAST_ENGINE` | `reference` | Engine resolver — see [Pluggable engine](#pluggable-engine-navyas-seam). |
| `AI_SERVICE_CORS_ORIGINS` | `*` | Comma-separated allowed origins. |

## Related

- [`../backend/README.md`](../backend/README.md) — Node API gateway that
  consumes this contract and stores forecasts in PostgreSQL.
- [`../frontend/README.md`](../frontend/README.md) — Q-FLARE command-center UI.