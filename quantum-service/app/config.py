# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: quantum-service | Owner: Nanda | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README:
# no fabricated data, no invented metrics, every surrogate or fallback is
# clearly labelled, and no quantum speedup is ever claimed.

"""Service configuration loaded from environment variables."""

from __future__ import annotations

import os


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "true" if default else "false").strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


SERVICE_NAME = "quantum-service"
SERVICE_VERSION = "1.0.0"

HOST = os.environ.get("QUANTUM_SERVICE_HOST", "0.0.0.0")
PORT = _int("QUANTUM_SERVICE_PORT", 8100)

CORS_ORIGINS = os.environ.get("QUANTUM_SERVICE_CORS_ORIGINS", "*").split(",")

# Force the QUBO endpoint to fail (503 QUBO_UNAVAILABLE) so the backend's
# fallback policy can be exercised against the live stack.
QUANTUM_QUBO_DISABLED = _bool("QUANTUM_QUBO_DISABLED")

# Force the Aer / IBM hardware executors to fail so the backend's
# `retry_simulator` fallback ladder is verifiable end-to-end.
QUANTUM_FORCE_AER_DOWN = _bool("QUANTUM_FORCE_AER_DOWN")
QUANTUM_FORCE_HARDWARE_DOWN = _bool("QUANTUM_FORCE_HARDWARE_DOWN")

# Optional live backends. The reference service samples QUBO solutions with a
# deterministic classical surrogate; set these to pull in Qiskit Aer/IBM where
# present. Missing runtimes degrade to the documented 503 contract instead of
# crashing the service.
IBM_TOKEN = os.environ.get("QISKIT_IBM_TOKEN", "")

# Quantum job lifecycle persistence. Empty (default) uses an ephemeral per-process
# SQLite database under the OS temp dir — the same lifetime as the in-memory stores
# it replaces. Set a stable path (e.g. ./quantum_jobs.db) to keep the
# `quantum_jobs` / `quantum_results` tables across restarts.
QUANTUM_DB_PATH = os.environ.get("QUANTUM_DB_PATH", "")

# Optional bearer-token gate. When set, every request except `/health` must carry
# `Authorization: Bearer <token>` (constant-time compared). The Node backend mirrors
# the same secret as its `QUANTUM_API_TOKEN`, so browser callers are rejected unless
# an operator deliberately shares the token. Empty (default) keeps the service open,
# exactly as before.
QUANTUM_API_TOKEN = os.environ.get("QUANTUM_API_TOKEN", "")

# Pacing knob (ms) inserted between the queued->running transition and the surrogate
# run, so the job lifecycle (queued / running / …) is observable in tests and demos.
# Capped to keep it a demonstration aid, never a throughput limiter.
QUANTUM_JOB_DELAY_MS = min(_int("QUANTUM_JOB_DELAY_MS", 0), 5000)

# When true, an Aer/IBM failure degrades the SAME job to the qflare simulator
# (`mode_used: "simulator"`, `fallback_applied: true`). Default false keeps the
# strict contract — the backend's `retry_simulator` ladder owns cross-job fallback.
QUANTUM_FALLBACK_ENABLED = _bool("QUANTUM_FALLBACK_ENABLED")

# How long `GET /quantum/result/:id` waits for a job to reach a terminal state before
# returning the current (in-progress) document. The backend orchestrator calls the
# result endpoint synchronously after `POST /quantum/optimize`, so this keeps that
# contract intact while still exposing the lightweight polling status endpoint.
QUANTUM_RESULT_WAIT_MS = _int("QUANTUM_RESULT_WAIT_MS", 30_000)

MAX_SHOTS = 100_000
MAX_LAYERS = 10
MAX_CANDIDATES = 100