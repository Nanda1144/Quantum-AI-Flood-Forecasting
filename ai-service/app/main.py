# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Nanda (API contract) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform . It is honest by construction, per the platform README:
# no fabricated data, no invented metrics, every surrogate or fallback is
# clearly labelled, and no quantum speedup is ever claimed.

"""Q-FLARE AI service application entry point.

Runs the forecasting engine behind a stable REST contract consumed by the Node
backend.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app import __version__, config
from app.api.routes import build_routes
from app.core.envelope import register_error_handlers, success
from app.engines.factory import get_engine

app = FastAPI(
    title="Q-FLARE AI Service",
    description=(
        "Forecasting engine contract. the XGBoost/LSTM/GRU pipelines implement "
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


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🌊</text></svg>'
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/v1/usage/current", include_in_schema=False)
def usage_probe() -> dict:
    return {"status": "ok", "usage": "unlimited"}


@app.get("/", response_class=HTMLResponse)
def root_index(request: Request) -> Response:
    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        return JSONResponse(
            content={
                "service": config.SERVICE_NAME,
                "version": config.SERVICE_VERSION,
                "engine": _engine.name,
                "status": "online",
                "docs": "/docs",
                "health": "/health",
            }
        )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Q-FLARE AI Forecasting Microservice</title>
    <link rel="icon" href="/favicon.ico">
    <style>
        :root {{
            --bg: #0b0f19;
            --surface: #131b2e;
            --border: #1e293b;
            --accent: #0284c7;
            --accent-glow: #38bdf8;
            --text: #f8fafc;
            --muted: #94a3b8;
            --success: #10b981;
        }}
        body {{
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }}
        .container {{
            width: 100%;
            max-width: 640px;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 2.5rem;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4), 0 0 40px rgba(2, 132, 199, 0.15);
        }}
        .header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 1.5rem;
            border-bottom: 1px solid var(--border);
            padding-bottom: 1.5rem;
        }}
        .title-area h1 {{
            font-size: 1.6rem;
            margin: 0 0 0.4rem 0;
            color: var(--text);
            display: flex;
            align-items: center;
            gap: 0.6rem;
        }}
        .status-badge {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--success);
            border: 1px solid rgba(16, 185, 129, 0.3);
            font-size: 0.8rem;
            font-weight: 600;
            padding: 4px 12px;
            border-radius: 9999px;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .status-badge::before {{
            content: "";
            width: 8px;
            height: 8px;
            background: var(--success);
            border-radius: 50%;
            display: inline-block;
            box-shadow: 0 0 8px var(--success);
        }}
        p {{
            line-height: 1.6;
            color: var(--muted);
            margin: 0 0 1.5rem 0;
        }}
        .card-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
            margin-bottom: 1.5rem;
        }}
        .info-card {{
            background: rgba(11, 15, 25, 0.6);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 1rem;
        }}
        .info-label {{
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--muted);
            margin-bottom: 0.3rem;
        }}
        .info-val {{
            font-size: 1.1rem;
            font-weight: 600;
            color: var(--accent-glow);
            font-family: monospace;
        }}
        .btn-group {{
            display: flex;
            gap: 0.75rem;
            flex-wrap: wrap;
        }}
        .btn {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: var(--accent);
            color: white;
            padding: 0.65rem 1.25rem;
            border-radius: 8px;
            text-decoration: none;
            font-size: 0.9rem;
            font-weight: 500;
            transition: all 0.2s ease;
        }}
        .btn:hover {{
            background: var(--accent-glow);
            color: #0b0f19;
            box-shadow: 0 0 16px rgba(56, 189, 248, 0.4);
        }}
        .btn-secondary {{
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text);
        }}
        .btn-secondary:hover {{
            background: var(--border);
            color: var(--accent-glow);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title-area">
                <h1>🌊 Q-FLARE AI Service</h1>
                <div style="color: var(--muted); font-size: 0.85rem;">Hydrological Forecasting Microservice</div>
            </div>
            <div class="status-badge">ONLINE</div>
        </div>
        <p>This microservice executes hydrological flood forecasting models, predicting water-level crests and risk levels. It communicates directly with the Node.js API Gateway.</p>
        <div class="card-grid">
            <div class="info-card">
                <div class="info-label">Active Engine</div>
                <div class="info-val">{_engine.name}</div>
            </div>
            <div class="info-card">
                <div class="info-label">Listener Port</div>
                <div class="info-val">8000 (FastAPI)</div>
            </div>
        </div>
        <div class="btn-group">
            <a href="/docs" class="btn">📖 Interactive API Docs</a>
            <a href="/health" class="btn btn-secondary">🩺 Health Check</a>
            <a href="/openapi.json" class="btn btn-secondary">📜 OpenAPI JSON</a>
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


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
    import uvicorn

    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=False)