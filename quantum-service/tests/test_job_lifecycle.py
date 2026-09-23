# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: quantum-service | Owner: Nanda | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README:
# no fabricated data, no invented metrics, every surrogate or fallback is
# clearly labelled, and no quantum speedup is ever claimed.

"""Quantum job lifecycle tests.

Covers the eight required scenarios: job creation, status transitions,
successful completion, failed execution, invalid result, hardware failure,
polling, and authorization. Contributes to the platform's honest-by-construction
pledge: every measurement comes from the surrogate or (where configured) a real
QPU submission — never from fabricated data.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)

TERMINAL = {"completed", "failed", "cancelled", "invalid"}


def _candidate(identifier: str, cost: float = 30.0) -> dict:
    return {
        "id": f"SIT-{identifier}",
        "name": f"Sensor {identifier}",
        "zone": "Delta North",
        "latitude": 9.0 + float(identifier) * 0.05,
        "longitude": -79.8,
        "flood_risk": 0.7,
        "population_exposure": 0.6,
        "infrastructure_criticality": 0.5,
        "communication_score": 0.4,
        "sensor_cost_k": cost,
        "coverage_radius_km": 12,
    }


def _qubo_payload() -> dict:
    return {
        "problem_type": "sensor_placement",
        "candidates": [_candidate("001"), _candidate("002"), _candidate("003"), _candidate("004", 40.0)],
        "weights": {
            "risk": 0.3,
            "populationCoverage": 0.3,
            "infrastructureCoverage": 0.2,
            "communication": 0.1,
            "cost": 0.1,
            "redundancy": 0,
        },
        "normalize_weights": True,
        "constraints": {"max_sensors": 2, "budget_k": None, "coverage_requirements": []},
    }


def _new_qubo() -> str:
    return client.post("/quantum/qubo", json=_qubo_payload()).json()["data"]["qubo_id"]


def _optimize(qubo_id: str, mode: str = "simulator", **overrides) -> dict:
    execution: dict = {"mode": mode, "backend": "qflare_simulator_statevector", "shots": 1024, "layers": 2}
    execution.update(overrides)
    response = client.post("/quantum/optimize", json={"qubo_id": qubo_id, "algorithm": "qaoa", "execution": execution})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _drain(execution_id: str, headers: dict | None = None) -> dict:
    """Wait for the worker to finish so no background thread lingers across tests."""
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        status = client.get(f"/quantum/jobs/{execution_id}/status", headers=headers).json()["data"]["status"]
        if status in TERMINAL:
            return status
        time.sleep(0.01)
    raise AssertionError(f"job {execution_id} did not reach a terminal state in time")


# ---------------------------------------------------------------------------
# 1) Job creation
# ---------------------------------------------------------------------------


def test_optimize_creates_a_queued_job() -> None:
    qubo_id = _new_qubo()
    data = _optimize(qubo_id)
    assert data["job_id"] == data["execution_id"]
    assert data["job_id"].startswith("EXEC-")

    status = client.get(f"/quantum/jobs/{data['job_id']}/status").json()["data"]
    assert status["job_id"] == data["job_id"]
    assert status["status"] in {"queued", "running", "completed"}
    assert status["qubit_count"] == 4
    assert status["shot_count"] == 1024
    assert status["layers"] == 2
    assert status["mode_requested"] == "simulator"
    assert status["backend_requested"] == "qflare_simulator_statevector"
    assert status["submitted_at"]
    _drain(data["job_id"])


# ---------------------------------------------------------------------------
# 2) Status transition + 7) Polling
# ---------------------------------------------------------------------------


def test_status_transitions_queued_running_completed_while_polling() -> None:
    original = config.QUANTUM_JOB_DELAY_MS
    config.QUANTUM_JOB_DELAY_MS = 250  # widen the queued/running windows
    try:
        execution_id = _optimize(_new_qubo())["execution_id"]

        seen: list[str] = []
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            response = client.get(f"/quantum/jobs/{execution_id}/status")
            assert response.status_code == 200
            payload = response.json()
            assert payload["success"] is True
            status = payload["data"]["status"]
            assert status in {"queued", "running", "completed"}
            seen.append(status)
            if status in TERMINAL:
                break
            time.sleep(0.01)

        assert seen[-1] == "completed"
        assert "running" in seen, f"expected a visible running window, saw {seen}"

        final = client.get(f"/quantum/result/{execution_id}").json()["data"]
        assert final["status"] == "completed"
        assert final["started_at"] is not None
        assert final["completed_at"] is not None
    finally:
        config.QUANTUM_JOB_DELAY_MS = original


# ---------------------------------------------------------------------------
# 3) Successful completion
# ---------------------------------------------------------------------------


def test_successful_completion_roundtrip() -> None:
    qubo_id = _new_qubo()
    data = _optimize(qubo_id, seed=42)
    result = client.get(f"/quantum/result/{data['job_id']}").json()["data"]

    assert result["status"] == "completed"
    assert result["error"] is None
    assert len(result["top_bitstring"]) == 4
    assert result["execution"]["mode_used"] == "simulator"
    assert result["execution"]["simulated"] is True
    assert result["quantum_advantage_claimed"] is False
    assert sum(bit == "1" for bit in result["top_bitstring"]) == 2

    record = result["result"]
    assert record["bitstring"] == result["top_bitstring"]
    assert record["objective"] == pytest.approx(result["energy_history"][-1]["energy"], abs=0.1)
    assert isinstance(record["runtime_ms"], float)
    assert record["metadata"]["seed"] == 42
    assert record["metadata"]["mode_used"] == "simulator"


# ---------------------------------------------------------------------------
# 4) Failed execution
# ---------------------------------------------------------------------------


def test_failed_execution_when_surrogate_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args, **_kwargs) -> None:
        raise RuntimeError("catastrophic simulator failure")

    monkeypatch.setattr("app.jobs.simulate", _boom)
    execution_id = _optimize(_new_qubo())["execution_id"]

    data = client.get(f"/quantum/result/{execution_id}").json()["data"]
    assert data["status"] == "failed"
    assert data["error"]["code"] == "EXECUTION_FAILED"
    assert data["result"] is None


# ---------------------------------------------------------------------------
# 5) Invalid result
# ---------------------------------------------------------------------------


def test_invalid_result_when_bitstring_does_not_match_qubo(monkeypatch: pytest.MonkeyPatch) -> None:
    def _malformed(*_args, **_kwargs):
        return "11011", [], []  # 5 bits declared, qubo has 4 variables

    monkeypatch.setattr("app.jobs.simulate", _malformed)
    execution_id = _optimize(_new_qubo())["execution_id"]

    data = client.get(f"/quantum/result/{execution_id}").json()["data"]
    assert data["status"] == "invalid"
    assert data["error"]["code"] == "INVALID_EXECUTION_RESULT"
    assert data["result"] is None


# ---------------------------------------------------------------------------
# 6) Hardware failure (+ configured simulator degradation)
# ---------------------------------------------------------------------------


def test_hardware_failure_fails_job_with_stable_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.QUANTUM_FORCE_HARDWARE_DOWN", True)
    execution_id = _optimize(_new_qubo(), mode="ibm_hardware", backend="ibm_brisbane")["execution_id"]

    data = client.get(f"/quantum/result/{execution_id}").json()["data"]
    assert data["status"] == "failed"
    assert data["error"]["code"] == "HARDWARE_UNAVAILABLE"
    assert data["execution"]["mode_used"] is None  # never executed a fake hardware run
    assert data["execution"]["submission_status"] == "not_submitted"


def test_hardware_failure_degrades_to_simulator_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.QUANTUM_FORCE_HARDWARE_DOWN", True)
    monkeypatch.setattr("app.config.QUANTUM_FALLBACK_ENABLED", True)
    execution_id = _optimize(_new_qubo(), mode="ibm_hardware", backend="ibm_brisbane")["execution_id"]

    data = client.get(f"/quantum/result/{execution_id}").json()["data"]
    assert data["status"] == "completed"
    assert data["execution"]["mode_used"] == "simulator"
    assert data["execution"]["simulated"] is True
    assert data["execution"]["fallback_applied"] is True
    assert "HARDWARE_UNAVAILABLE" in data["execution"]["fallback_reason"]


# ---------------------------------------------------------------------------
# Cancellation (safe transitions)
# ---------------------------------------------------------------------------


def test_cancelling_a_queued_job_with_populated_fields() -> None:
    original = config.QUANTUM_JOB_DELAY_MS
    config.QUANTUM_JOB_DELAY_MS = 250  # keep the job in `queued` while we cancel it
    try:
        job_id = _optimize(_new_qubo())["job_id"]

        response = client.post(f"/quantum/jobs/{job_id}/cancel")
        assert response.status_code == 200
        body = response.json()["data"]
        assert body["status"] == "cancelled"
        assert body["cancellable"] is False

        # A terminal job can never be cancelled again.
        res = client.post(f"/quantum/jobs/{job_id}/cancel")
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "EXECUTION_ALREADY_TERMINAL"

        result = client.get(f"/quantum/result/{job_id}").json()["data"]
        assert result["status"] == "cancelled"
        assert result["result"] is None
    finally:
        config.QUANTUM_JOB_DELAY_MS = original


def test_cooperative_cancel_of_a_running_job() -> None:
    original = config.QUANTUM_JOB_DELAY_MS
    config.QUANTUM_JOB_DELAY_MS = 250
    try:
        job_id = _optimize(_new_qubo())["job_id"]

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if client.get(f"/quantum/jobs/{job_id}/status").json()["data"]["status"] == "running":
                break
            time.sleep(0.01)

        response = client.post(f"/quantum/jobs/{job_id}/cancel")
        assert response.status_code == 200
        body = response.json()["data"]
        assert body["status"] == "running"
        assert body["cancel_requested"] is True

        assert _drain(job_id) == "cancelled"
        result = client.get(f"/quantum/result/{job_id}").json()["data"]
        assert result["status"] == "cancelled"
        assert result["result"] is None
    finally:
        config.QUANTUM_JOB_DELAY_MS = original


def test_cancelling_a_completed_job_is_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _optimize(_new_qubo())["job_id"]
    assert _drain(job_id) == "completed"

    response = client.post(f"/quantum/jobs/{job_id}/cancel")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXECUTION_ALREADY_TERMINAL"


# ---------------------------------------------------------------------------
# 8) Authorization
# ---------------------------------------------------------------------------


def test_authorization_gate_when_token_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.QUANTUM_API_TOKEN", "contractual-secret")
    headers = {"Authorization": "Bearer contractual-secret"}
    qubo_id = client.post("/quantum/qubo", json=_qubo_payload(), headers=headers).json()["data"]["qubo_id"]
    payload = {"qubo_id": qubo_id, "algorithm": "qaoa", "execution": {"mode": "simulator", "shots": 1024, "layers": 2}}

    # /health stays public for probe tooling.
    assert client.get("/health").status_code == 200

    # Missing / wrong token -> 401 with the UNAUTHORIZED code.
    missing = client.post("/quantum/optimize", json=payload)
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "UNAUTHORIZED"

    wrong = client.post("/quantum/optimize", json=payload, headers={"Authorization": "Bearer wrong-token"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "UNAUTHORIZED"

    # Correct token -> job created normally.
    ok = client.post("/quantum/optimize", json=payload, headers=headers)
    assert ok.status_code == 200
    job_id = ok.json()["data"]["job_id"]
    _drain(job_id, headers=headers)


def test_open_service_without_token_requires_no_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.QUANTUM_API_TOKEN", "")
    job_id = _optimize(_new_qubo())["job_id"]
    assert _drain(job_id) == "completed"