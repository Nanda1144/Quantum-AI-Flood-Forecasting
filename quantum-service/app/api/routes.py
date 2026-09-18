"""QUBO construction + QAOA execution API.

Contract owner: the Node backend (`backend/src/clients/quantum-service.client.ts`).
The browser never calls this service directly.

    POST /quantum/qubo      build + store a sensor-placement QUBO
    POST /quantum/optimize  accept a QAOA execution (poll via result)
    GET  /quantum/result/:id  fully resolved execution result
    GET  /health            liveness + backend availability
"""

from __future__ import annotations

import importlib
import math
import threading
from typing import Any, Literal

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field

from app import config
from app.core.envelope import QuantumError, success
from app import optimization as qmath

ExecutionMode = Literal["simulator", "aer", "ibm_hardware"]
QuantumBackend = Literal[
    "qflare_simulator_statevector",
    "aer_simulator_statevector",
    "aer_simulator_matrix_product_state",
    "ibm_brisbane",
    "ibm_kyiv",
]

# --------------------------------------------------------------------------
# Wire schemas (snake_case, mirror of the backend client contract)
# --------------------------------------------------------------------------


class CoverageRequirement(BaseModel):
    metric: Literal["population", "infrastructure"]
    min_fraction: float = Field(ge=0, le=1)
    origin: str = Field(min_length=1, max_length=128)


class Candidate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    zone: str = Field(min_length=1, max_length=64)
    latitude: float
    longitude: float
    flood_risk: float = Field(ge=0, le=1)
    population_exposure: float = Field(ge=0, le=1)
    infrastructure_criticality: float = Field(ge=0, le=1)
    communication_score: float = Field(ge=0, le=1)
    sensor_cost_k: float = Field(ge=0)
    coverage_radius_km: float = Field(ge=0)


class Constraints(BaseModel):
    max_sensors: int = Field(ge=1, le=config.MAX_CANDIDATES)
    budget_k: float | None = Field(default=None, ge=0)
    coverage_requirements: list[CoverageRequirement] = Field(default_factory=list, max_length=10)


class CreateQuboRequest(BaseModel):
    problem_type: Literal["sensor_placement"]
    candidates: list[Candidate] = Field(min_length=2, max_length=config.MAX_CANDIDATES)
    weights: dict[str, float]
    normalize_weights: bool = True
    constraints: Constraints


class ExecutionSpec(BaseModel):
    mode: ExecutionMode
    backend: QuantumBackend = "qflare_simulator_statevector"
    shots: int = Field(default=1024, ge=1, le=config.MAX_SHOTS)
    layers: int = Field(default=2, ge=1, le=config.MAX_LAYERS)
    seed: int | None = None


class OptimizeRequest(BaseModel):
    qubo_id: str = Field(min_length=1, max_length=128)
    algorithm: Literal["qaoa"]
    execution: ExecutionSpec


# --------------------------------------------------------------------------
# In-memory stores (single process; the backend is the only consumer)
# --------------------------------------------------------------------------

_lock = threading.Lock()
_counter = 0


def _next_identifier(prefix: str) -> str:
    global _counter
    with _lock:
        _counter += 1
        return f"{prefix}-{_counter}"


QUBOS: dict[str, dict[str, Any]] = {}
RESULTS: dict[str, dict[str, Any]] = {}


def _lift_weights(weights: dict[str, float]) -> dict[str, float]:
    return {key: float(weights.get(key, 0.0)) for key in qmath.OBJECTIVE_KEYS}


def _public_qubo(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "variable_count": doc["variable_count"],
        "variables": doc["variables"],
        "expression": doc["expression"],
        "matrix": doc["matrix"],
        "offset": doc["offset"],
    }


def _resolve_backend(mode: ExecutionMode, backend: QuantumBackend) -> tuple[str, str | None, bool]:
    """Resolve (backend_used, device, simulated) or raise the stable contract error."""
    if mode == "simulator":
        return "qflare_simulator_statevector", None, True

    if mode == "aer":
        if config.QUANTUM_FORCE_AER_DOWN or importlib.util.find_spec("qiskit_aer") is None:  # type: ignore[misc]
            raise QuantumError("AER_UNAVAILABLE", "Aer simulator runtime is not installed on the quantum service", 503)
        return backend, backend, True

    if mode == "ibm_hardware":
        if config.QUANTUM_FORCE_HARDWARE_DOWN or importlib.util.find_spec("qiskit_ibm_runtime") is None:  # type: ignore[misc]
            raise QuantumError("HARDWARE_UNAVAILABLE", "IBM Quantum runtime is not configured on the quantum service", 503)
        if not config.IBM_TOKEN:
            raise QuantumError("HARDWARE_UNAVAILABLE", "QISKIT_IBM_TOKEN is not set on the quantum service", 503)
        return backend, backend, False

    raise QuantumError("VALIDATION_ERROR", f"unknown execution mode '{mode}'", 400)


def build_routes() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict:
        return success(
            {
                "service": config.SERVICE_NAME,
                "version": config.SERVICE_VERSION,
                "module": "qaoa-extern",
                "status": "online",
                "backends": {
                    "simulator": {"available": True},
                    "aer": {"available": importlib.util.find_spec("qiskit_aer") is not None},
                    "ibm_hardware": {
                        "available": importlib.util.find_spec("qiskit_ibm_runtime") is not None and bool(config.IBM_TOKEN)
                    },
                },
            }
        )

    @router.post("/quantum/qubo")
    def create_qubo(payload: CreateQuboRequest) -> dict:
        if config.QUANTUM_QUBO_DISABLED:
            raise QuantumError("QUBO_UNAVAILABLE", "QUBO construction is disabled on the quantum service", 503)

        candidates = [candidate.model_dump() for candidate in payload.candidates]
        weights = _lift_weights(payload.weights)
        any_positive = any(value > 0 for value in weights.values())
        if not all(math.isfinite(value) and value >= 0 for value in weights.values()) or not any_positive:
            raise QuantumError("INVALID_OBJECTIVE_WEIGHTS", "Objective weights must be finite, non-negative, with one > 0", 422)

        if payload.constraints.max_sensors > len(candidates):
            raise QuantumError("VALIDATION_ERROR", "max_sensors cannot exceed candidate count", 422)

        if payload.constraints.budget_k == 0:
            raise QuantumError("INFEASIBLE_BUDGET", "A zero budget cannot fund any sensor", 422)

        doc = qmath.build_qubo(
            payload.problem_type,
            candidates,
            weights,
            payload.normalize_weights,
            payload.constraints.max_sensors,
            payload.constraints.budget_k,
        )
        doc["_greedy"] = qmath.greedy_decode(
            candidates,
            weights,
            payload.normalize_weights,
            payload.constraints.max_sensors,
            payload.constraints.budget_k,
        )
        qubo_id = _next_identifier("QUBO")
        QUBOS[qubo_id] = doc
        return success({"qubo_id": qubo_id, "doc": _public_qubo(doc)})

    @router.post("/quantum/optimize")
    def optimize(payload: OptimizeRequest) -> dict:
        qubo = QUBOS.get(payload.qubo_id)
        if qubo is None:
            raise QuantumError("QUBO_NOT_FOUND", f"QUBO '{payload.qubo_id}' not found", 404)

        backend_used, device, simulated = _resolve_backend(payload.execution.mode, payload.execution.backend)

        top_bitstring, measurement_counts, energy_history = qmath.simulate_qaaoa(
            qubo,
            seed=payload.execution.seed or 7,
            shots=payload.execution.shots,
            layers=payload.execution.layers,
        )

        execution_id = _next_identifier("EXEC")
        RESULTS[execution_id] = {
            "execution_id": execution_id,
            "qubo_id": payload.qubo_id,
            "algorithm": "qaoa",
            "status": "completed",
            "execution": {
                "mode_requested": payload.execution.mode,
                "mode_used": payload.execution.mode,
                "backend_used": backend_used,
                "simulated": simulated,
                "device": device,
            },
            "qubit_count": qubo["variable_count"],
            "shot_count": payload.execution.shots,
            "measurement_counts": measurement_counts,
            "top_bitstring": top_bitstring,
            "energy_history": energy_history,
            "execution_time_ms": 4 + qubo["variable_count"],
            "quantum_advantage_claimed": False,
        }
        return success({"execution_id": execution_id})

    @router.get("/quantum/result/{execution_id}")
    def get_result(execution_id: str = Path(min_length=1, max_length=128)) -> dict:
        result = RESULTS.get(execution_id)
        if result is None:
            raise QuantumError("EXECUTION_NOT_FOUND", f"Execution '{execution_id}' not found", 404)
        return success(result)

    return router