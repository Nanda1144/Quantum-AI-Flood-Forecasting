"""
Q-FLARE AI service.

FastAPI microservice that exposes Navya's flood forecasting engine through a
stable REST contract. Nanda's Node backend consumes this contract; the
frontend never talks to this service directly.

OWNERSHIP BOUNDARY
------------------
This package is the *integration seam* for the forecasting pipeline. Navya owns
the actual models (XGBoost / LSTM / GRU). The default `ReferenceEngine`
produces deterministic sample forecasts so the whole platform is demonstrable
end-to-end. Navya may add a new engine (or swap the implementation of the
existing ones) behind the `ForecastEngine` protocol without changing the Node
backend or the REST contract.
"""

__version__ = "1.0.0"