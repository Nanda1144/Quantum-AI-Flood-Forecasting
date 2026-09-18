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

MAX_SHOTS = 100_000
MAX_LAYERS = 10
MAX_CANDIDATES = 100