# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: quantum-service | Owner: Nanda | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README:
# no fabricated data, no invented metrics, every surrogate or fallback is
# clearly labelled, and no quantum speedup is ever claimed.

"""Tests for the generic QUBO generation + retrieval API.

    POST /quantum/qubo              generic QUBO assembly (variables/objective/…)
    GET  /quantum/qubo/:id          retrieval
    GET  /quantum/qubo/:id/variables    semantic variable→candidate mapping
    GET  /quantum/qubo/:id/constraints  constraint definitions + penalties

Covers the six required scenarios: a valid 4-variable QUBO, dimension
mismatches, missing/invalid variable mappings, numerically invalid
coefficients (incl. symmetry), constraint validation, and large-matrix
handling. No Qiskit objects are ever exposed — every response is clean JSON.
"""

from __future__ import annotations

import json
import math

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _post_raw(payload: dict) -> object:
    """Send the payload as raw JSON text so NaN/Infinity literals survive.

    httpx's `json=` override refuses to serialise non-finite floats, but a
    real caller can always send `NaN`/`Infinity` literals in the body — those
    must still be rejected by the contract, not crash it.
    """
    return client.post("/quantum/qubo", content=json.dumps(payload), headers={"content-type": "application/json"})


def _variables(count: int = 4) -> list[dict]:
    return [{"variable": f"x{i}", "candidate_id": f"L{index:02d}"} for i, index in enumerate(range(1, count + 1))]


def _generic_payload(**overrides) -> dict:
    payload: dict = {
        "problem_type": "generic",
        "variables": _variables(),
        "objective": {
            "linear": [1.0, -2.0, 0.5, 3.0],
            "quadratic": [[0, 0.5, 0, 0], [0.5, 0, -1, 0], [0, -1, 0, 0.25], [0, 0, 0.25, 0]],
            "constant": 0.25,
        },
        "constraints": [{"key": "max_two", "type": "cardinality", "limit": 2, "penalty": 10.0}],
        "weights": None,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 1) Valid 4-variable QUBO
# ---------------------------------------------------------------------------


def test_generic_qubo_returns_well_formed_document() -> None:
    res = client.post("/quantum/qubo", json=_generic_payload())
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    data = body["data"]
    assert data["qubo_id"].startswith("QUBO-")
    assert data["problem_type"] == "generic"
    assert data["variable_count"] == 4

    # matrix dimensions must match variable count (symmetric N×N convention)
    assert len(data["matrix"]) == 4
    assert all(len(row) == 4 for row in data["matrix"])
    for i in range(4):
        for j in range(4):
            assert abs(data["matrix"][i][j] - data["matrix"][j][i]) <= 1e-9

    assert len(data["linear_terms"]) == 4
    assert data["quadratic_terms"] and all(
        term["i"] <= term["j"] and "coefficient" in term for term in data["quadratic_terms"]
    )
    assert data["penalties"] and data["penalties"][0]["key"] == "max_two"
    assert data["objective_expression"]
    assert data["constraints"] and data["constraints"][0]["penalty"] == 10.0
    assert isinstance(data["offset"], float)

    # clean JSON only: no Qiskit objects, no _-prefixed internals leak out
    assert not any(key.startswith("_") for key in data)


def test_generic_qubo_is_retrievable() -> None:
    qubo_id = client.post("/quantum/qubo", json=_generic_payload()).json()["data"]["qubo_id"]
    res = client.get(f"/quantum/qubo/{qubo_id}")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["qubo_id"] == qubo_id
    assert data["variable_count"] == 4
    assert data["objective_expression"]
    assert len(data["matrix"]) == 4


def test_generic_qubo_retrieval_does_not_leak_internals() -> None:
    qubo_id = client.post("/quantum/qubo", json=_generic_payload()).json()["data"]["qubo_id"]
    for path in (f"/quantum/qubo/{qubo_id}", f"/quantum/qubo/{qubo_id}/variables", f"/quantum/qubo/{qubo_id}/constraints"):
        payload = client.get(path).json()["data"]
        assert not any(key.startswith("_") for key in payload if isinstance(key, str))


def test_variables_mapping_endpoint() -> None:
    qubo_id = client.post("/quantum/qubo", json=_generic_payload()).json()["data"]["qubo_id"]
    res = client.get(f"/quantum/qubo/{qubo_id}/variables")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["variable_count"] == 4
    assert data["variables"] == _variables()


def test_constraints_endpoint_returns_definitions_and_penalties() -> None:
    qubo_id = client.post("/quantum/qubo", json=_generic_payload()).json()["data"]["qubo_id"]
    res = client.get(f"/quantum/qubo/{qubo_id}/constraints")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["constraints"][0]["key"] == "max_two"
    assert data["constraints"][0]["type"] == "cardinality"
    assert data["constraints"][0]["penalty"] == 10.0
    assert data["penalties"][0]["scale"] == 10.0


def test_unknown_qubo_retrieval_is_404() -> None:
    assert client.get("/quantum/qubo/QUBO-NOPE").json()["error"]["code"] == "QUBO_NOT_FOUND"
    assert client.get("/quantum/qubo/QUBO-NOPE/variables").json()["error"]["code"] == "QUBO_NOT_FOUND"
    assert client.get("/quantum/qubo/QUBO-NOPE/constraints").json()["error"]["code"] == "QUBO_NOT_FOUND"


# ---------------------------------------------------------------------------
# 2) Invalid dimensions
# ---------------------------------------------------------------------------


def test_linear_dimension_mismatch_rejected() -> None:
    payload = _generic_payload()
    payload["objective"]["linear"] = [1.0, 2.0, 3.0]  # 3 terms, 4 variables
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_DIMENSIONS"


def test_quadratic_row_count_mismatch_rejected() -> None:
    payload = _generic_payload()
    payload["objective"]["quadratic"] = [[0, 0.5], [0.5, 0]]  # 2×2, 4 variables
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_DIMENSIONS"


def test_quadratic_row_width_mismatch_rejected() -> None:
    payload = _generic_payload()
    payload["objective"]["quadratic"] = [[0, 0.5, 0, 0], [0.5, 0, -1, 0], [0, -1, 0, 0.25], [0, 0, 0.25]]  # ragged
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_DIMENSIONS"


# ---------------------------------------------------------------------------
# 3) Missing / invalid variable mapping
# ---------------------------------------------------------------------------


def test_empty_variables_rejected() -> None:
    payload = _generic_payload(variables=[])
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_variable_missing_candidate_id_rejected() -> None:
    payload = _generic_payload(variables=[{"variable": "x1"}])
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_VARIABLE_MAPPING"


def test_duplicate_variable_names_rejected() -> None:
    payload = _generic_payload(variables=[{"variable": "x1", "candidate_id": "A"}, {"variable": "x1", "candidate_id": "B"}])
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_VARIABLE_MAPPING"


def test_duplicate_candidate_ids_rejected() -> None:
    payload = _generic_payload(variables=[{"variable": "x1", "candidate_id": "A"}, {"variable": "x2", "candidate_id": "A"}])
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_VARIABLE_MAPPING"


def test_objective_referencing_unknown_variable_rejected() -> None:
    payload = _generic_payload()
    payload["objective"]["linear"] = {"x1": 1.0, "ghost": 2.0}
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_VARIABLE_MAPPING"


def test_weight_referencing_unknown_variable_rejected() -> None:
    payload = _generic_payload(weights={"ghost": 1.0})
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_VARIABLE_MAPPING"


# ---------------------------------------------------------------------------
# 4) Numerically invalid coefficients (NaN / infra / symmetry)
# ---------------------------------------------------------------------------


def test_nan_linear_coefficient_rejected() -> None:
    payload = _generic_payload()
    payload["objective"]["linear"][0] = float("nan")
    res = _post_raw(payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_COEFFICIENTS"


def test_infinite_linear_coefficient_rejected() -> None:
    payload = _generic_payload()
    payload["objective"]["linear"][0] = float("inf")
    res = _post_raw(payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_COEFFICIENTS"


def test_nan_quadratic_coefficient_rejected() -> None:
    payload = _generic_payload()
    payload["objective"]["quadratic"][0][1] = float("nan")
    res = _post_raw(payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_COEFFICIENTS"


def test_infinite_quadratic_coefficient_rejected() -> None:
    payload = _generic_payload()
    payload["objective"]["quadratic"][0][1] = float("inf")
    res = _post_raw(payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_COEFFICIENTS"


def test_nan_constant_rejected() -> None:
    payload = _generic_payload()
    payload["objective"]["constant"] = float("nan")
    res = _post_raw(payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_COEFFICIENTS"


def test_infinite_constant_rejected() -> None:
    payload = _generic_payload()
    payload["objective"]["constant"] = float("inf")
    res = _post_raw(payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_COEFFICIENTS"


def test_nan_in_dict_quadratic_rejected() -> None:
    payload = _generic_payload()
    payload["objective"]["quadratic"] = {"x1": {"x2": float("nan")}}
    res = _post_raw(payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_COEFFICIENTS"


def test_quadratic_dict_referencing_unknown_variable_rejected() -> None:
    payload = _generic_payload()
    payload["objective"]["quadratic"] = {"x1": {"ghost": 1.0}}
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_VARIABLE_MAPPING"


def test_infinite_weight_rejected() -> None:
    payload = _generic_payload(weights={"x1": float("inf")})
    res = _post_raw(payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_COEFFICIENTS"


def test_non_symmetric_matrix_rejected() -> None:
    payload = _generic_payload()
    payload["objective"]["quadratic"][0][1] = 9.9  # breaks Q01 == Q10
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_SYMMETRY"


def test_negative_weight_rejected() -> None:
    payload = _generic_payload(weights={"x1": -1.0})
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_COEFFICIENTS"


def test_nan_weight_rejected() -> None:
    payload = _generic_payload(weights={"x1": float("nan")})
    res = _post_raw(payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_COEFFICIENTS"


# ---------------------------------------------------------------------------
# 5) Constraint validation
# ---------------------------------------------------------------------------


def test_negative_penalty_rejected() -> None:
    payload = _generic_payload(constraints=[{"key": "c1", "type": "cardinality", "limit": 1, "penalty": -5.0}])
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_CONSTRAINTS"


def test_zero_penalty_rejected() -> None:
    payload = _generic_payload(constraints=[{"key": "c1", "type": "cardinality", "limit": 1, "penalty": 0.0}])
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_CONSTRAINTS"


def test_nan_penalty_rejected() -> None:
    payload = _generic_payload(constraints=[{"key": "c1", "type": "cardinality", "limit": 1, "penalty": float("nan")}])
    res = _post_raw(payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_CONSTRAINTS"


def test_cardinality_limit_exceeding_variables_rejected() -> None:
    payload = _generic_payload(constraints=[{"key": "c1", "type": "cardinality", "limit": 9, "penalty": 10.0}])
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_CONSTRAINTS"


def test_duplicate_constraint_keys_rejected() -> None:
    payload = _generic_payload(constraints=[{"key": "c1", "type": "cardinality", "limit": 1, "penalty": 10.0}] * 2)
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_CONSTRAINTS"


def test_budget_constraint_without_coefficients_rejected() -> None:
    payload = _generic_payload(constraints=[{"key": "c1", "type": "budget", "limit": 100, "penalty": 10.0}])
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_CONSTRAINTS"


def test_budget_constraint_with_bad_coefficient_count_rejected() -> None:
    payload = _generic_payload(constraints=[{"key": "c1", "type": "budget", "limit": 100, "penalty": 10.0, "coefficients": [1.0, 1.0]}])
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_CONSTRAINTS"


def test_budget_constraint_with_nan_coefficient_rejected() -> None:
    payload = _generic_payload(constraints=[{"key": "c1", "type": "budget", "limit": 100, "penalty": 10.0, "coefficients": [1.0, 1.0, 1.0, float("nan")]}])
    res = _post_raw(payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_CONSTRAINTS"


def test_negative_limit_rejected() -> None:
    payload = _generic_payload(constraints=[{"key": "c1", "type": "cardinality", "limit": -1, "penalty": 10.0}])
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_CONSTRAINTS"


def test_nan_constraint_limit_rejected() -> None:
    payload = _generic_payload(constraints=[{"key": "c1", "type": "cardinality", "limit": float("nan"), "penalty": 10.0}])
    res = _post_raw(payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_QUBO_CONSTRAINTS"


def test_empty_constraint_key_rejected() -> None:
    payload = _generic_payload(constraints=[{"key": "", "type": "cardinality", "limit": 1, "penalty": 10.0}])
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["success"] is False


# ---------------------------------------------------------------------------
# 6) Large-matrix handling
# ---------------------------------------------------------------------------


def test_large_matrix_generation() -> None:
    n = config_max_candidates()
    variables = [{"variable": f"x{i}", "candidate_id": f"L{i:03d}"} for i in range(n)]
    payload = {
        "problem_type": "generic",
        "variables": variables,
        "objective": {
            "linear": [float(-i) for i in range(n)],
            "constant": 0.0,
        },
        "constraints": [{"key": "cap", "type": "cardinality", "limit": 10, "penalty": 100.0}],
        "weights": None,
    }
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["variable_count"] == n
    assert len(data["matrix"]) == n and all(len(row) == n for row in data["matrix"])
    assert len(data["linear_terms"]) == n
    # upper-triangle quadratic terms: N·(N+1)/2
    expected = n * (n + 1) // 2
    assert len(data["quadratic_terms"]) == expected
    assert data["constraints"][0]["key"] == "cap"

    # retrieval still cheap and symmetric
    res = client.get(f"/quantum/qubo/{data['qubo_id']}")
    assert res.status_code == 200
    matrix = res.json()["data"]["matrix"]
    assert abs(matrix[0][-1] - matrix[-1][0]) <= 1e-9


def test_over_limit_variables_rejected() -> None:
    n = config_max_candidates() + 1
    variables = [{"variable": f"x{i}", "candidate_id": f"L{i:03d}"} for i in range(n)]
    payload = _generic_payload(variables=variables)
    res = client.post("/quantum/qubo", json=payload)
    assert res.status_code == 422
    assert res.json()["success"] is False


def config_max_candidates() -> int:
    from app import config

    return config.MAX_CANDIDATES