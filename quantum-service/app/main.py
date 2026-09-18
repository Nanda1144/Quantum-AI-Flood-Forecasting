"""Q-FLARE quantum service application entry point.

Runs the QUBO construction + QAOA execution contract behind the envelopes the
Node backend consumes. Not reachable from the browser.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import __version__, config
from app.api.routes import build_routes
from app.core.envelope import register_error_handlers, success

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