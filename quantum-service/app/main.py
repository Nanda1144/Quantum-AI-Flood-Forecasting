# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: quantum-service | Owner: Nanda | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README:
# no fabricated data, no invented metrics, every surrogate or fallback is
# clearly labelled, and no quantum speedup is ever claimed.

"""Q-FLARE quantum service application entry point.

Runs the QUBO construction + QAOA execution contract behind the envelopes the
Node backend consumes. Not reachable from the browser.
"""

from __future__ import annotations

import hmac
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__, config
from app.api.routes import build_routes
from app.core.envelope import failure, register_error_handlers, success

app = FastAPI(
    title="Q-FLARE Quantum Service",
    description=(
        "Sensor-placement QUBO construction and QAOA execution contract. "
        "The Node backend orchestrates this service; the browser never calls it directly. "
        "No quantum speedup is ever claimed — results carry quantum_advantage_claimed=false."
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

_quantum_routes = build_routes()
app.include_router(_quantum_routes)


@app.middleware("http")
async def measure_latency(request: Request, call_next):  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Quantum-Service-Latency-Ms"] = f"{round((time.perf_counter() - started) * 1000)}"
    return response


@app.middleware("http")
async def require_bearer_token(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Optional `QUANTUM_API_TOKEN` gate.

    Only enforced when the service has been given a token. The Node backend
    mirrors the same secret (`backend` -> `QUANTUM_API_TOKEN`), so this blocks
    browser/third-party callers without coupling the orchestrator to a shared
    key it doesn't send. `/health` stays public for probe tooling.
    """
    token = config.QUANTUM_API_TOKEN
    if token and request.url.path != "/health":
        expected = f"Bearer {token}"
        provided = request.headers.get("Authorization", "")
        if not hmac.compare_digest(provided.strip(), expected):
            return JSONResponse(status_code=401, content=failure("UNAUTHORIZED", "Missing or invalid bearer token"))
    return await call_next(request)