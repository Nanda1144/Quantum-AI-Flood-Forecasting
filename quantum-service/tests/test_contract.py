"""Contract tests for the Q-FLARE quantum service."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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


def test_health() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["service"] == "quantum-service"
    assert "simulator" in body["data"]["backends"]


def test_create_qubo_returns_document() -> None:
    res = client.post("/quantum/qubo", json=_qubo_payload())
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    data = body["data"]
    assert data["qubo_id"].startswith("QUBO-")
    doc = data["doc"]
    assert doc["variable_count"] == 4
    assert len(doc["variables"]) == 4
    assert len(doc["matrix"]) == 4
    assert all(len(row) == 5 for row in doc["matrix"])
    assert doc["expression"]
    assert isinstance(doc["offset"], float)


def test_optimize_then_result_roundtrip() -> None:
    qubo_id = client.post("/quantum/qubo", json=_qubo_payload()).json()["data"]["qubo_id"]
    res = client.post(
        "/quantum/optimize",
        json={"qubo_id": qubo_id, "algorithm": "qaoa", "execution": {"mode": "simulator", "backend": "qflare_simulator_statevector", "shots": 1024, "layers": 2, "seed": 42}},
    )
    assert res.status_code == 200
    execution_id = res.json()["data"]["execution_id"]
    assert execution_id.startswith("EXEC-")

    result = client.get(f"/quantum/result/{execution_id}")
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["execution_id"] == execution_id
    assert data["qubo_id"] == qubo_id
    assert data["algorithm"] == "qaoa"
    assert data["status"] == "completed"
    assert data["execution"]["mode_used"] == "simulator"
    assert data["execution"]["backend_used"] == "qflare_simulator_statevector"
    assert data["execution"]["simulated"] is True
    assert data["execution"]["device"] is None
    assert data["qubit_count"] == 4
    assert data["shot_count"] == 1024
    assert len(data["top_bitstring"]) == 4
    assert set(data["top_bitstring"]) <= {"0", "1"}
    assert data["measurement_counts"]
    assert data["energy_history"][-1]["energy"] <= data["energy_history"][0]["energy"]
    assert data["quantum_advantage_claimed"] is False


def test_top_bitstring_is_feasible_and_cardinality_respecting() -> None:
    qubo_id = client.post("/quantum/qubo", json=_qubo_payload()).json()["data"]["qubo_id"]
    execution_id = client.post(
        "/quantum/optimize",
        json={"qubo_id": qubo_id, "algorithm": "qaoa", "execution": {"mode": "simulator", "shots": 2048, "layers": 2, "seed": 7}},
    ).json()["data"]["execution_id"]
    data = client.get(f"/quantum/result/{execution_id}").json()["data"]
    assert sum(bit == "1" for bit in data["top_bitstring"]) == 2


def test_aer_unavailable_without_runtime() -> None:
    qubo_id = client.post("/quantum/qubo", json=_qubo_payload()).json()["data"]["qubo_id"]
    res = client.post(
        "/quantum/optimize",
        json={"qubo_id": qubo_id, "algorithm": "qaoa", "execution": {"mode": "aer", "backend": "aer_simulator_statevector", "shots": 1024, "layers": 2}},
    )
    # Aer is not installed in the reference stack — the contract error must be stable.
    assert res.status_code == 503
    body = res.json()
    assert body["success"] is False
    assert body["error"]["code"] == "AER_UNAVAILABLE"


def test_ibm_hardware_unavailable_without_runtime() -> None:
    qubo_id = client.post("/quantum/qubo", json=_qubo_payload()).json()["data"]["qubo_id"]
    res = client.post(
        "/quantum/optimize",
        json={"qubo_id": qubo_id, "algorithm": "qaoa", "execution": {"mode": "ibm_hardware", "backend": "ibm_brisbane", "shots": 1024, "layers": 2}},
    )
    assert res.status_code == 503
    body = res.json()
    assert body["success"] is False
    assert body["error"]["code"] == "HARDWARE_UNAVAILABLE"


def test_unknown_execution_id_is_404() -> None:
    res = client.get("/quantum/result/EXEC-NOPE")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "EXECUTION_NOT_FOUND"


def test_unknown_qubo_is_404_on_optimize() -> None:
    res = client.post(
        "/quantum/optimize",
        json={"qubo_id": "QUBO-NOPE", "algorithm": "qaoa", "execution": {"mode": "simulator", "shots": 1024, "layers": 2}},
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "QUBO_NOT_FOUND"


def test_validation_errors_return_422_validaton_envelope() -> None:
    payload = _qubo_payload()
    payload["constraints"]["max_sensors"] = 9  # exceeds candidate count
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("budget", [-1, 0])
def test_non_positive_budget_rejected(budget: float) -> None:
    payload = _qubo_payload()
    payload["constraints"]["budget_k"] = budget
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["success"] is False