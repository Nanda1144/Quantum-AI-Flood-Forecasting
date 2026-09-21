# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Nanda (API contract) + Navya (engine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README:
# no fabricated data, no invented metrics, every surrogate or fallback is
# clearly labelled, and no quantum speedup is ever claimed.

"""Q-FLARE AI service application entry point.

Runs the forecasting engine behind a stable REST contract consumed by the Node
backend. Not reachable from the browser.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import __version__, config
from app.api.routes import build_routes
from app.core.envelope import register_error_handlers, success
from app.engines.factory import get_engine

app = FastAPI(
    title="Q-FLARE AI Service",
    description=(
        "Forecasting engine contract. Navya's XGBoost/LSTM/GRU pipelines implement "
        "this contract; the Node backend and the frontend only depend on it."
    ),
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

_engine = get_engine()

_ai_routes = build_routes(_engine)
app.include_router(_ai_routes)


@app.middleware("http")
async def measure_latency(request: Request, call_next):  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-AI-Service-Latency-Ms"] = f"{round((time.perf_counter() - started) * 1000)}"
    return response


@app.get("/health")
def health() -> dict:
    return success(
        {
            "service": config.SERVICE_NAME,
            "version": config.SERVICE_VERSION,
            "engine": _engine.name,
            "status": "online",
        }
    )


if __name__ == "__main__":
    # `python -m app.main` honours AI_SERVICE_HOST / AI_SERVICE_PORT. The
    # documented uvicorn command (`uvicorn app.main:app`) keeps its own flags.
    import uvicorn

    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=False)