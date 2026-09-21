# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: quantum-service | Owner: Nanda | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README:
# no fabricated data, no invented metrics, every surrogate or fallback is
# clearly labelled, and no quantum speedup is ever claimed.

"""QUBO construction + QAOA execution API.

Contract owner: the Node backend (`backend/src/clients/quantum-service.client.ts`).
The browser never calls this service directly.

`POST /quantum/qubo` accepts two payload families, discriminated by shape:

1. Sensor placement (`candidates` + objective `weights` + `constraints`) —
   the original Node-backend contract; returns `{qubo_id, doc}` unchanged.
2. Generic QUBO (`variables` + explicit `objective` + `constraints`) —
   validated and assembled into a clean-JSON QUBO document for React.

    POST /quantum/qubo                              build + store a QUBO
    GET  /quantum/qubo/:id                          retrieve a stored QUBO
    GET  /quantum/qubo/:id/variables                semantic variable→candidate mapping
    GET  /quantum/qubo/:id/constraints              constraint definitions + penalties
    POST /quantum/optimize                          create a queued QAOA job
    GET  /quantum/jobs/:id/status                   lightweight current job status
    GET  /quantum/result/:id                        current + final job information
    POST /quantum/jobs/:id/cancel                   cancel a job while it is safe
    GET  /health                                    liveness + backend availability

Jobs (`quantum_jobs` + `quantum_results` tables) follow the lifecycle
`queued -> running -> completed | failed | invalid`, with `cancelled`
reachable from `queued` or cooperatively from `running`. Responses are always
clean JSON — no Qiskit objects are ever serialised.
"""

from __future__ import annotations

import importlib
import json
import math
import threading
from typing import Any, Literal

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field

from app import config
from app.core.envelope import QuantumError, success
from app import optimization as qmath
from app import jobs

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


class GenericVariable(BaseModel):
    variable: str = Field(default="", max_length=64)
    candidate_id: str = Field(default="", max_length=64)


class GenericObjective(BaseModel):
    linear: list[float] | dict[str, float] | None = None
    quadratic: list[list[float]] | dict[str, dict[str, float]] | None = None
    constant: float | None = None


class GenericConstraint(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=128)
    type: Literal["cardinality", "budget"]
    limit: float
    coefficients: list[float] | None = None
    penalty: float | None = None


class CreateGenericQuboRequest(BaseModel):
    problem_type: str = Field(min_length=1, max_length=64)
    variables: list[GenericVariable] = Field(min_length=1, max_length=config.MAX_CANDIDATES)
    objective: GenericObjective
    constraints: list[GenericConstraint] = Field(default_factory=list)
    weights: dict[str, float] | None = None


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
# In-memory QUBO store (single process; the backend is the only consumer).
# Job lifecycle state lives in the SQLite `quantum_jobs` / `quantum_results`
# tables managed by `app.jobs.JobStore`.
# --------------------------------------------------------------------------

_lock = threading.Lock()
_counter = 0


def _next_identifier(prefix: str) -> str:
    global _counter
    with _lock:
        _counter += 1
        return f"{prefix}-{_counter}"


QUBOS: dict[str, dict[str, Any]] = {}


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


def _public_generic_qubo(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "problem_type": doc["problem_type"],
        "variable_count": doc["variable_count"],
        "variables": doc["variables"],
        "matrix": doc["matrix"],
        "linear_terms": doc["linear_terms"],
        "quadratic_terms": doc["quadratic_terms"],
        "penalties": doc["penalties"],
        "objective_expression": doc["objective_expression"],
        "constraints": doc["constraints"],
        "offset": doc["offset"],
    }


_GENERIC_KEYS = (
    "problem_type",
    "variable_count",
    "variables",
    "matrix",
    "linear_terms",
    "quadratic_terms",
    "penalties",
    "objective_expression",
    "constraints",
    "offset",
)


def _public_by_kind(doc: dict[str, Any]) -> dict[str, Any]:
    if doc.get("_kind") == "generic":
        return _public_generic_qubo(doc)
    return _public_qubo(doc)


def _create_sensor_placement_qubo(payload: CreateQuboRequest) -> dict:
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
    penalty_scale = doc["_offset"] / max(1.0, float(payload.constraints.max_sensors) ** 2)
    constraint_meta: list[dict[str, Any]] = [
        {
            "key": "max_sensors",
            "name": "Maximum sensors",
            "type": "cardinality",
            "limit": payload.constraints.max_sensors,
            "penalty": round(penalty_scale, 6),
            "formula": f"P·(Σx − {payload.constraints.max_sensors:g})²",
        }
    ]
    if payload.constraints.budget_k is not None:
        budget_scale = penalty_scale / max(1.0, payload.constraints.budget_k)
        constraint_meta.append(
            {
                "key": "budget_k",
                "name": "Sensor budget",
                "type": "budget",
                "limit": payload.constraints.budget_k,
                "penalty": round(budget_scale, 6),
                "formula": f"P·(Σcᵢ·xᵢ − {payload.constraints.budget_k:g})²",
            }
        )
    doc["_constraint_meta"] = constraint_meta
    doc["_kind"] = "sensor_placement"
    qubo_id = _next_identifier("QUBO")
    QUBOS[qubo_id] = doc
    return success({"qubo_id": qubo_id, "doc": _public_qubo(doc)})


def _create_generic_qubo(payload: CreateGenericQuboRequest) -> dict:
    try:
        doc = qmath.build_generic_qubo(
            problem_type=payload.problem_type,
            variables=[variable.model_dump() for variable in payload.variables],
            objective=payload.objective.model_dump(exclude_none=True),
            constraints=[constraint.model_dump(exclude_none=True) for constraint in payload.constraints],
            weights=payload.weights,
        )
    except qmath.QuboInputError as error:
        raise QuantumError(error.code, error.message, 422) from error

    doc["_kind"] = "generic"
    qubo_id = _next_identifier("QUBO")
    QUBOS[qubo_id] = doc
    return success({"qubo_id": qubo_id, **_public_generic_qubo(doc)})


def _get_stored_qubo(qubo_id: str) -> dict[str, Any]:
    doc = QUBOS.get(qubo_id)
    if doc is None:
        raise QuantumError("QUBO_NOT_FOUND", f"QUBO '{qubo_id}' not found", 404)
    return doc


def _status_document(job: dict[str, Any]) -> dict[str, Any]:
    """Lightweight polling document for `GET /quantum/jobs/:id/status`."""
    error: dict[str, str] | None = None
    if job.get("error_code"):
        error = {"code": job["error_code"], "message": job.get("error_message") or job["error_code"]}
    return {
        "job_id": job["id"],
        "status": job["status"],
        "algorithm": job["algorithm"],
        "mode_requested": job["mode_requested"],
        "mode_used": job["mode_used"],
        "backend_requested": job["backend_requested"],
        "backend_used": job["backend_used"],
        "qubit_count": job["qubits"],
        "shot_count": job["shots"],
        "layers": job["layers"],
        "submitted_at": job["submitted_at"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
        "cancellable": job["status"] in (jobs.STATUS_QUEUED, jobs.STATUS_RUNNING),
        "cancel_requested": bool(job["cancel_requested"]),
        "error": error,
    }


def _result_document(job: dict[str, Any], result: dict[str, Any] | None) -> dict[str, Any]:
    """Current + final job information for `GET /quantum/result/:id`.

    Keeps the legacy top-level fields (`measurement_counts`, `top_bitstring`,
    `energy_history`, `execution_time_ms`, `quantum_advantage_claimed`) so the
    Node backend client can read the same payload it always has, alongside the
    richer `result` record sourced from the `quantum_results` table.
    """
    error: dict[str, str] | None = None
    if job.get("error_code"):
        error = {"code": job["error_code"], "message": job.get("error_message") or job["error_code"]}

    document: dict[str, Any] = {
        "job_id": job["id"],
        "execution_id": job["id"],
        "qubo_id": job["qubo_id"],
        "algorithm": job["algorithm"],
        "status": job["status"],
        "qubit_count": job["qubits"],
        "shot_count": job["shots"],
        "layers": job["layers"],
        "submitted_at": job["submitted_at"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
        "cancellable": job["status"] in (jobs.STATUS_QUEUED, jobs.STATUS_RUNNING),
        "cancel_requested": bool(job["cancel_requested"]),
        "error": error,
        "execution": {
            "mode_requested": job["mode_requested"],
            "mode_used": job["mode_used"],
            "backend_requested": job["backend_requested"],
            "backend_used": job["backend_used"],
            "device": job["device"],
            "simulated": bool(job["simulated"]),
            "fallback_applied": bool(job["fallback_applied"]),
            "fallback_reason": job["fallback_reason"],
            "submission_status": job["submission_status"],
        },
        "result": None,
    }

    if result is not None:
        document["result"] = {
            "bitstring": result["bitstring"],
            "counts": json.loads(result["counts"]),
            "objective": result["objective"],
            "runtime_ms": result["runtime_ms"],
            "energy_history": json.loads(result["energy_history"]),
            "metadata": json.loads(result["metadata"]),
        }
        # Legacy top-level fields (backend client compatibility).
        document.update(
            {
                "measurement_counts": json.loads(result["counts"]),
                "top_bitstring": result["bitstring"],
                "energy_history": json.loads(result["energy_history"]),
                "execution_time_ms": job.get("execution_time_ms"),
                "quantum_advantage_claimed": False,
            }
        )

    return document


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
    def create_qubo(payload: CreateGenericQuboRequest | CreateQuboRequest) -> dict:
        if config.QUANTUM_QUBO_DISABLED:
            raise QuantumError("QUBO_UNAVAILABLE", "QUBO construction is disabled on the quantum service", 503)

        if isinstance(payload, CreateGenericQuboRequest):
            return _create_generic_qubo(payload)

        return _create_sensor_placement_qubo(payload)

    @router.post("/quantum/optimize")
    def optimize(payload: OptimizeRequest) -> dict:
        qubo = QUBOS.get(payload.qubo_id)
        if qubo is None:
            raise QuantumError("QUBO_NOT_FOUND", f"QUBO '{payload.qubo_id}' not found", 404)

        execution_id = _next_identifier("EXEC")
        spec = payload.execution.model_dump(exclude_none=True)
        spec["qubo_id"] = payload.qubo_id
        spec["algorithm"] = payload.algorithm
        jobs.start_job(execution_id, qubo, spec)
        return success({"job_id": execution_id, "execution_id": execution_id})

    @router.get("/quantum/jobs/{job_id}/status")
    def job_status(job_id: str = Path(min_length=1, max_length=128)) -> dict:
        job = jobs.STORE.get_job(job_id)
        if job is None:
            raise QuantumError("EXECUTION_NOT_FOUND", f"Execution '{job_id}' not found", 404)
        return success(_status_document(job))

    @router.post("/quantum/jobs/{job_id}/cancel")
    def cancel_job(job_id: str = Path(min_length=1, max_length=128)) -> dict:
        job = jobs.STORE.get_job(job_id)
        if job is None:
            raise QuantumError("EXECUTION_NOT_FOUND", f"Execution '{job_id}' not found", 404)

        status = job["status"]
        if status in jobs.TERMINAL_STATUSES:
            raise QuantumError(
                "EXECUTION_ALREADY_TERMINAL",
                f"Execution '{job_id}' already reached terminal status '{status}'",
                409,
            )

        if status == jobs.STATUS_QUEUED:
            if jobs.STORE.cancel_queued(job_id):
                job = jobs.STORE.get_job(job_id)
                return success({"job_id": job_id, "status": job["status"], "cancellable": False})

        # Running (or the queued job raced into running): cooperative cancel.
        jobs.STORE.request_cancel_running(job_id)
        job = jobs.STORE.get_job(job_id)
        if job["status"] == jobs.STATUS_RUNNING:
            return success(
                {
                    "job_id": job_id,
                    "status": "running",
                    "cancel_requested": True,
                    "cancellable": False,
                    "note": "Cancellation requested; the quantum job stops at its next safe checkpoint.",
                }
            )
        return success({"job_id": job_id, "status": job["status"], "cancel_requested": True, "cancellable": False})

    @router.get("/quantum/result/{execution_id}")
    def get_result(execution_id: str = Path(min_length=1, max_length=128)) -> dict:
        job = jobs.wait_for_terminal(execution_id)
        if job is None:
            raise QuantumError("EXECUTION_NOT_FOUND", f"Execution '{execution_id}' not found", 404)
        return success(_result_document(job, jobs.STORE.get_result(execution_id)))

    @router.get("/quantum/qubo/{qubo_id}")
    def get_qubo(qubo_id: str = Path(min_length=1, max_length=128)) -> dict:
        doc = _get_stored_qubo(qubo_id)
        result = {"qubo_id": qubo_id, **_public_by_kind(doc)}
        if doc.get("_kind") == "sensor_placement":
            result = {"qubo_id": qubo_id, "doc": _public_by_kind(doc)}
        return success(result)

    @router.get("/quantum/qubo/{qubo_id}/variables")
    def get_qubo_variables(qubo_id: str = Path(min_length=1, max_length=128)) -> dict:
        doc = _get_stored_qubo(qubo_id)
        if doc.get("_kind") == "generic":
            variables = [dict(item) for item in doc["variables"]]
        else:
            variables = [{"variable": name, "candidate_id": name} for name in doc["variables"]]
        return success({"qubo_id": qubo_id, "variable_count": doc["variable_count"], "variables": variables})

    @router.get("/quantum/qubo/{qubo_id}/constraints")
    def get_qubo_constraints(qubo_id: str = Path(min_length=1, max_length=128)) -> dict:
        doc = _get_stored_qubo(qubo_id)
        if doc.get("_kind") == "generic":
            constraints = [dict(item) for item in doc["constraints"]]
            penalties = [dict(item) for item in doc["penalties"]]
        else:
            constraints = [dict(item) for item in doc.get("_constraint_meta", [])]
            penalties = [
                {"key": item["key"], "type": item["type"], "limit": item["limit"], "scale": item["penalty"], "formula": item["formula"]}
                for item in doc.get("_constraint_meta", [])
            ]
        return success({"qubo_id": qubo_id, "constraints": constraints, "penalties": penalties})

    return router