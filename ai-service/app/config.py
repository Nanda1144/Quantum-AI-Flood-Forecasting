# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Nanda (API contract) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform . It is honest by construction, per the platform README:
# no fabricated data, no invented metrics, every surrogate or fallback is
# clearly labelled, and no quantum speedup is ever claimed.

"""Service configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    _root_env = Path(__file__).resolve().parent.parent.parent / ".env"
    _local_env = Path(__file__).resolve().parent.parent / ".env"
    if _root_env.exists():
        load_dotenv(dotenv_path=_root_env)
    elif _local_env.exists():
        load_dotenv(dotenv_path=_local_env)
    else:
        load_dotenv()
except ImportError:
    pass


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
# path of your own engine class to use the live pipeline instead, e.g.
#   FORECAST_ENGINE=qflare.engines.gru:GruFloodNetEngine
FORECAST_ENGINE = os.environ.get("FORECAST_ENGINE", "reference")

# Only the Node backend talks to this service; a permissive default is fine.
CORS_ORIGINS = os.environ.get("AI_SERVICE_CORS_ORIGINS", "*").split(",")