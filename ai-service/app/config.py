"""Service configuration loaded from environment variables."""

from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


SERVICE_NAME = "ai-service"
SERVICE_VERSION = "1.0.0"

HOST = os.environ.get("AI_SERVICE_HOST", "0.0.0.0")
PORT = _int("AI_SERVICE_PORT", 8000)

# "reference" runs the deterministic contract engine. Set to the dotted import
# path of your own engine class to use Navya's live pipeline instead, e.g.
#   FORECAST_ENGINE=qflare.engines.gru:GruFloodNetEngine
FORECAST_ENGINE = os.environ.get("FORECAST_ENGINE", "reference")

# Only the Node backend talks to this service; a permissive default is fine.
CORS_ORIGINS = os.environ.get("AI_SERVICE_CORS_ORIGINS", "*").split(",")