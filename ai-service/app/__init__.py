# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Nanda (API contract) + Navya (engine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README:
# no fabricated data, no invented metrics, every surrogate or fallback is
# clearly labelled, and no quantum speedup is ever claimed.

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