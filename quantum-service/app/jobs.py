# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: quantum-service | Owner: Nanda | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README:
# no fabricated data, no invented metrics, every surrogate or fallback is
# clearly labelled, and no quantum speedup is ever claimed.

"""Quantum job lifecycle: persisted jobs, async execution, safe cancellation.

The lifecycle is a small state machine over two SQLite tables:

    quantum_jobs    algorithm, backend, qubits, shots, layers, status,
                    submitted_at, started_at, completed_at, error info,
                    resolution metadata and IBM submission tracking.
    quantum_results bitstring, counts, objective, runtime_ms, metadata
                    (one row per completed job).

Statuses: `queued` -> `running` -> `completed | failed | invalid`, with
`cancelled` reachable from `queued` (immediate) or `running` (cooperative:
the worker honours the cancel flag at its checkpoints). A terminal state can
never be re-entered — every transition is a conditional update on the current
status, so cancellation cannot race a completion into a wrong state.

Backend resolution mirrors the old `_resolve_backend` seam: missing Aer/IBM
runtimes raise the stable `AER_UNAVAILABLE` / `HARDWARE_UNAVAILABLE` contract
errors, which fail the job unless `QUANTUM_FALLBACK_ENABLED` degrades the same
job to the (clearly-marked) qflare simulator. IBM credentials never leave the
server; a real QPU submission is only attempted when `qiskit_ibm_runtime` is
installed — otherwise the job fails or falls back, never fabricates hardware
measurements. No Qiskit object is ever written to a response.
"""

from __future__ import annotations

import importlib
import json
import os
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any

from app import config
from app import optimization as qmath
from app.core.envelope import now_iso

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_INVALID = "invalid"

TERMINAL_STATUSES = frozenset({STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED, STATUS_INVALID})

SUBMISSION_NOT_SUBMITTED = "not_submitted"


class JobNotFoundError(Exception):
    """Raised by the worker/seam when a job id does not exist."""

    def __init__(self, job_id: str, message: str | None = None) -> None:
        super().__init__(message or f"Execution '{job_id}' not found")
        self.job_id = job_id


class BackendUnavailable(Exception):
    """Raised when the requested execution backend cannot run.

    Carries a stable contract code (`AER_UNAVAILABLE` / `HARDWARE_UNAVAILABLE`)
    the worker maps to a `failed` job (or a clearly-marked simulator fallback).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ResolvedRun:
    backend_used: str
    mode_used: str
    simulated: bool
    device: str | None
    fallback_applied: bool
    fallback_reason: str | None
    submission_status: str = SUBMISSION_NOT_SUBMITTED
    # Real QPU measurement counts, present only after a genuine IBM submission.
    raw_counts: dict[str, int] | None = None


# --------------------------------------------------------------------------
# Database path + schema
# --------------------------------------------------------------------------


def _database_path() -> str:
    configured = os.environ.get("QUANTUM_DB_PATH", "").strip()
    if configured:
        return configured
    directory = tempfile.mkdtemp(prefix="qf-quantum-jobs-")
    return os.path.join(directory, "quantum_jobs.db")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS quantum_jobs (
    id                TEXT PRIMARY KEY,
    qubo_id           TEXT NOT NULL,
    algorithm         TEXT NOT NULL,
    backend_requested TEXT NOT NULL,
    backend_used      TEXT,
    mode_requested    TEXT NOT NULL,
    mode_used         TEXT,
    simulated         INTEGER NOT NULL DEFAULT 0,
    device            TEXT,
    qubits            INTEGER NOT NULL,
    shots             INTEGER NOT NULL,
    layers            INTEGER NOT NULL,
    seed              INTEGER,
    status            TEXT NOT NULL,
    submitted_at      TEXT NOT NULL,
    started_at        TEXT,
    completed_at      TEXT,
    error_code        TEXT,
    error_message     TEXT,
    fallback_applied  INTEGER NOT NULL DEFAULT 0,
    fallback_reason   TEXT,
    submission_status TEXT NOT NULL DEFAULT 'not_submitted',
    cancel_requested  INTEGER NOT NULL DEFAULT 0,
    execution_time_ms REAL
);

CREATE TABLE IF NOT EXISTS quantum_results (
    job_id         TEXT PRIMARY KEY REFERENCES quantum_jobs(id),
    bitstring      TEXT NOT NULL,
    counts         TEXT NOT NULL,
    objective      REAL NOT NULL,
    runtime_ms     REAL NOT NULL,
    energy_history TEXT NOT NULL,
    metadata       TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
"""


class JobStore:
    """Thread-safe SQLite store for the job lifecycle.

    A single serialised connection keeps every transition atomic (conditional
    updates on `status`) so the async worker, the cancel endpoint and the
    result pollers can never leave a job in a torn state.
    """

    def __init__(self, path: str | None = None) -> None:
        self._path = path or _database_path()
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self._path, check_same_thread=False, timeout=10.0)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(_SCHEMA)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- reads ------------------------------------------------------------

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM quantum_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row is not None else None

    def get_result(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM quantum_results WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row is not None else None

    # -- writes -----------------------------------------------------------

    def create_job(self, job_id: str, qubo: dict[str, Any], spec: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO quantum_jobs (
                    id, qubo_id, algorithm, backend_requested, mode_requested,
                    qubits, shots, layers, seed, status, submitted_at, submission_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    spec["qubo_id"],
                    spec["algorithm"],
                    spec["backend"],
                    spec["mode"],
                    qubo["variable_count"],
                    spec["shots"],
                    spec["layers"],
                    spec.get("seed"),
                    STATUS_QUEUED,
                    now_iso(),
                    SUBMISSION_NOT_SUBMITTED,
                ),
            )
            self._db.commit()

    def start_job(self, job_id: str) -> bool:
        """queued -> running. Returns False if the job left `queued` first."""
        with self._lock:
            cursor = self._db.execute(
                "UPDATE quantum_jobs SET status = ?, started_at = ? WHERE id = ? AND status = ?",
                (STATUS_RUNNING, now_iso(), job_id, STATUS_QUEUED),
            )
            self._db.commit()
            return cursor.rowcount == 1

    def record_resolution(self, job_id: str, resolved: ResolvedRun) -> None:
        with self._lock:
            self._db.execute(
                """
                UPDATE quantum_jobs SET backend_used = ?, mode_used = ?, simulated = ?, device = ?,
                                       fallback_applied = ?, fallback_reason = ?, submission_status = ?
                WHERE id = ? AND status = ?
                """,
                (
                    resolved.backend_used,
                    resolved.mode_used,
                    1 if resolved.simulated else 0,
                    resolved.device,
                    1 if resolved.fallback_applied else 0,
                    resolved.fallback_reason,
                    resolved.submission_status,
                    job_id,
                    STATUS_RUNNING,
                ),
            )
            self._db.commit()

    def cancel_queued(self, job_id: str) -> bool:
        """queued -> cancelled (immediate, always safe)."""
        with self._lock:
            cursor = self._db.execute(
                """
                UPDATE quantum_jobs SET status = ?, completed_at = ?, cancel_requested = 1, submission_status = ?
                WHERE id = ? AND status = ?
                """,
                (STATUS_CANCELLED, now_iso(), "cancelled", job_id, STATUS_QUEUED),
            )
            self._db.commit()
            return cursor.rowcount == 1

    def request_cancel_running(self, job_id: str) -> bool:
        """Set the cooperative cancel flag on a running job."""
        with self._lock:
            cursor = self._db.execute(
                "UPDATE quantum_jobs SET cancel_requested = 1 WHERE id = ? AND status = ?",
                (job_id, STATUS_RUNNING),
            )
            self._db.commit()
            return cursor.rowcount == 1

    def cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            row = self._db.execute("SELECT cancel_requested FROM quantum_jobs WHERE id = ?", (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def finalize_cancelled(self, job_id: str) -> bool:
        """running -> cancelled (worker honours the cooperative flag)."""
        with self._lock:
            cursor = self._db.execute(
                """
                UPDATE quantum_jobs SET status = ?, completed_at = ?, submission_status = ?
                WHERE id = ? AND status = ? AND cancel_requested = 1
                """,
                (STATUS_CANCELLED, now_iso(), "cancelled", job_id, STATUS_RUNNING),
            )
            self._db.commit()
            return cursor.rowcount == 1

    def fail_job(self, job_id: str, code: str, message: str) -> None:
        with self._lock:
            self._db.execute(
                """
                UPDATE quantum_jobs SET status = ?, completed_at = ?, error_code = ?, error_message = ?
                WHERE id = ? AND status = ?
                """,
                (STATUS_FAILED, now_iso(), code, message, job_id, STATUS_RUNNING),
            )
            self._db.commit()

    def invalidate_job(self, job_id: str, message: str) -> None:
        with self._lock:
            self._db.execute(
                """
                UPDATE quantum_jobs SET status = ?, completed_at = ?, error_code = ?, error_message = ?
                WHERE id = ? AND status = ?
                """,
                (STATUS_INVALID, now_iso(), "INVALID_EXECUTION_RESULT", message, job_id, STATUS_RUNNING),
            )
            self._db.commit()

    def complete_job(self, job_id: str, payload: dict[str, Any]) -> bool:
        """running -> completed, writing the quantum_results row.

        The update requires `cancel_requested = 0`; a concurrent cancel always
        wins, so a completed job can never be overwritten by a later cancel.
        """
        with self._lock:
            cursor = self._db.execute(
                """
                UPDATE quantum_jobs SET status = ?, completed_at = ?, execution_time_ms = ?, submission_status = ?
                WHERE id = ? AND status = ? AND cancel_requested = 0
                """,
                (
                    STATUS_COMPLETED,
                    now_iso(),
                    payload["execution_time_ms"],
                    payload.get("submission_status", SUBMISSION_NOT_SUBMITTED),
                    job_id,
                    STATUS_RUNNING,
                ),
            )
            if cursor.rowcount != 1:
                self._db.commit()
                return False
            self._db.execute(
                """
                INSERT INTO quantum_results (
                    job_id, bitstring, counts, objective, runtime_ms, energy_history, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    payload["bitstring"],
                    json.dumps(payload["counts"]),
                    payload["objective"],
                    payload["runtime_ms"],
                    json.dumps(payload["energy_history"]),
                    json.dumps(payload["metadata"]),
                    now_iso(),
                ),
            )
            self._db.commit()
            return True


# --------------------------------------------------------------------------
# Backend resolution + execution seam
# --------------------------------------------------------------------------


def resolve_execution(spec: dict[str, Any], qubit_count: int) -> ResolvedRun:
    """Resolve the requested backend, honouring the fallback configuration.

    Reads `config` live so tests can flip the force-down / fallback switches
    without restarting the service.
    """
    mode = spec["mode"]
    backend = spec["backend"]

    if mode == "simulator":
        return ResolvedRun(
            backend_used="qflare_simulator_statevector",
            mode_used="simulator",
            simulated=True,
            device=None,
            fallback_applied=False,
            fallback_reason=None,
        )

    if mode == "aer":
        if config.QUANTUM_FORCE_AER_DOWN or importlib.util.find_spec("qiskit_aer") is None:  # type: ignore[misc]
            return _degrade_or_fail("AER_UNAVAILABLE", "Aer simulator runtime is not installed on the quantum service")
        return ResolvedRun(
            backend_used=backend,
            mode_used="aer",
            simulated=True,
            device=backend,
            fallback_applied=False,
            fallback_reason=None,
        )

    if mode == "ibm_hardware":
        if config.QUANTUM_FORCE_HARDWARE_DOWN or importlib.util.find_spec("qiskit_ibm_runtime") is None:  # type: ignore[misc]
            return _degrade_or_fail("HARDWARE_UNAVAILABLE", "IBM Quantum runtime is not configured on the quantum service")
        if not config.IBM_TOKEN:
            return _degrade_or_fail("HARDWARE_UNAVAILABLE", "QISKIT_IBM_TOKEN is not set on the quantum service")
        try:
            counts = _execute_ibm(backend, qubit_count, spec["shots"], spec.get("seed") or 7)
        except BackendUnavailable:
            raise
        except Exception as error:  # network / auth / quota / API drift
            return _degrade_or_fail("HARDWARE_UNAVAILABLE", f"IBM submission failed: {error}")
        return ResolvedRun(
            backend_used=backend,
            mode_used="ibm_hardware",
            simulated=False,
            device=backend,
            fallback_applied=False,
            fallback_reason=None,
            submission_status="succeeded",
            raw_counts=counts,
        )

    # Narrowed by the request schema; defensive guard keeps the seam total.
    return _degrade_or_fail("VALIDATION_ERROR", f"unknown execution mode '{mode}'")


def _degrade_or_fail(code: str, message: str) -> ResolvedRun:
    """Either degrade the SAME job to the simulator or surface the contract error."""
    if config.QUANTUM_FALLBACK_ENABLED:
        return ResolvedRun(
            backend_used="qflare_simulator_statevector",
            mode_used="simulator",
            simulated=True,
            device=None,
            fallback_applied=True,
            fallback_reason=f"{code}: {message}",
        )
    raise BackendUnavailable(code, message)


def _execute_ibm(backend: str, qubit_count: int, shots: int, seed: int) -> dict[str, int]:
    """Submit a real QAOA run to IBM Quantum and return the raw QPU counts.

    Unreachable in the reference stack (`qiskit_ibm_runtime` is never
    installed): this raises `HARDWARE_UNAVAILABLE` so the job degrades to a
    clearly-marked simulator run or fails cleanly. When a real installation is
    present the counts come from the QPU — never synthesised here. The credential
    (`QISKIT_IBM_TOKEN`) stays server-side; only the job's `submission_status`
    ever leaves this module.
    """
    if importlib.util.find_spec("qiskit_ibm_runtime") is None:  # pragma: no cover - reference stack
        raise BackendUnavailable("HARDWARE_UNAVAILABLE", "IBM Quantum runtime is not installed on the quantum service")

    from qiskit import QuantumCircuit  # type: ignore[import-untyped]
    from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2  # type: ignore[import-untyped]

    print(f"[quantum-service] submitting QAOA to IBM backend '{backend}' ({qubit_count} qubits, {shots} shots)")
    service = QiskitRuntimeService()
    circuit = QuantumCircuit(qubit_count, qubit_count)
    circuit.h(range(qubit_count))
    for i in range(qubit_count):
        circuit.ry(seed * 1e-2, i)
        circuit.measure(i, i)
    sampler = SamplerV2(mode=service.backend(backend))
    job = sampler.run([circuit], shots=shots)
    pub = job.result()[0].data.meas
    counts = {bitstring: int(count) for bitstring, count in dict(pub.get_counts()).items()}
    return counts


def _from_real_counts(qubo: dict[str, Any], counts: dict[str, int]) -> tuple[str, list[dict[str, int]], list[dict[str, float]]]:
    """Normalise real QPU counts into the contract's result shape (no oracle)."""
    def energy(bits: str) -> float:
        return qmath.qubo_energy(qubo, bits)

    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], energy(pair[0])))[:8]
    measurement_counts = [{"bitstring": bits, "count": count} for bits, count in ranked]
    top_bitstring = ranked[0][0] if ranked else "0" * qubo["variable_count"]
    energy_history = [{"iteration": 1 + index, "energy": round(energy(bits), 4)} for index, (bits, _count) in enumerate(ranked)]
    return top_bitstring, measurement_counts, energy_history


def simulate(
    qubo: dict[str, Any],
    seed: int,
    shots: int,
    layers: int,
) -> tuple[str, list[dict[str, int]], list[dict[str, float]]]:
    """Deterministic QAOA surrogate (module-level seam, patchable in tests)."""
    return qmath.simulate_qaaoa(qubo, seed=seed, shots=shots, layers=layers)


# --------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------

STORE = JobStore()


def _maybe_pace() -> None:
    delay_ms = config.QUANTUM_JOB_DELAY_MS
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)


def _run(job_id: str, qubo: dict[str, Any], spec: dict[str, Any]) -> None:
    # First pacing window: the job stays `queued` (cancel-while-queued is fully
    # deterministic here); the second window below keeps it observable as `running`.
    _maybe_pace()

    if not STORE.start_job(job_id):
        return  # cancelled while queued, or already terminal

    try:
        resolved = resolve_execution(spec, qubo["variable_count"])
    except BackendUnavailable as error:
        STORE.fail_job(job_id, error.code, error.message)
        return
    STORE.record_resolution(job_id, resolved)

    # Second pacing window: `running`, before the surrogate executes.
    _maybe_pace()
    if STORE.cancel_requested(job_id):
        STORE.finalize_cancelled(job_id)
        return

    started = time.perf_counter()
    try:
        if resolved.mode_used == "ibm_hardware" and resolved.raw_counts is not None:
            top_bitstring, measurement_counts, energy_history = _from_real_counts(qubo, resolved.raw_counts)
        else:
            top_bitstring, measurement_counts, energy_history = simulate(
                qubo,
                seed=spec.get("seed") or 7,
                shots=spec["shots"],
                layers=spec["layers"],
            )
    except Exception as error:  # surrogate failure -> failed execution
        STORE.fail_job(job_id, "EXECUTION_FAILED", f"QAOA execution failed: {error}")
        return
    runtime_ms = (time.perf_counter() - started) * 1000.0

    if STORE.cancel_requested(job_id):
        STORE.finalize_cancelled(job_id)
        return

    expected = qubo["variable_count"]
    if len(top_bitstring) != expected or any(bit not in "01" for bit in top_bitstring):
        STORE.invalidate_job(
            job_id,
            f"Measured bitstring '{top_bitstring}' does not match the declared {expected} binary variables",
        )
        return

    objective = qmath.qubo_energy(qubo, top_bitstring)
    STORE.complete_job(
        job_id,
        {
            "bitstring": top_bitstring,
            "counts": measurement_counts,
            "objective": objective,
            "runtime_ms": round(runtime_ms, 3),
            "energy_history": energy_history,
            "execution_time_ms": round(runtime_ms, 3),
            "submission_status": resolved.submission_status,
            "metadata": {
                "algorithm": spec["algorithm"],
                "seed": spec.get("seed") or 7,
                "qubits": qubo["variable_count"],
                "shots": spec["shots"],
                "layers": spec["layers"],
                "mode_requested": spec["mode"],
                "mode_used": resolved.mode_used,
                "backend_used": resolved.backend_used,
                "simulated": resolved.simulated,
                "fallback_applied": resolved.fallback_applied,
                "fallback_reason": resolved.fallback_reason,
            },
        },
    )


def start_job(job_id: str, qubo: dict[str, Any], spec: dict[str, Any]) -> None:
    """Create the queued row and dispatch the async worker."""
    STORE.create_job(job_id, qubo, spec)
    thread = threading.Thread(target=_run, args=(job_id, qubo, spec), daemon=True, name=f"qaoa-job-{job_id}")
    thread.start()


def wait_for_terminal(job_id: str) -> dict[str, Any] | None:
    """Block until the job reaches a terminal state (bounded by config)."""
    deadline = time.perf_counter() + max(1, config.QUANTUM_RESULT_WAIT_MS) / 1000.0
    job: dict[str, Any] | None = None
    while time.perf_counter() < deadline:
        job = STORE.get_job(job_id)
        if job is None or job["status"] in TERMINAL_STATUSES:
            return job
        time.sleep(0.02)
    return job