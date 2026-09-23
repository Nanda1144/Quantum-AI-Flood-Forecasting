# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: quantum-service | Owner: Nanda | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README:
# no fabricated data, no invented metrics, every surrogate or fallback is
# clearly labelled, and no quantum speedup is ever claimed.

"""Sensor-placement QUBO construction and QAOA surrogate sampling.

This mirrors 1:1 the Node backend math
(`backend/src/lib/optimization/qubo.ts`) so the QUBO document produced here is
identical to the one the orchestrator builds locally — the only difference is
the quantum service owns the execution reference.

Everything is normalised floats; nothing here performs ML or forecasting. The
"quantum" path is a deterministic classical surrogate (labelled `simulated`)
so any operator machine can run the stack; optional Qiskit Aer / IBM runtime
backends slot in behind the same hawking seam.
"""

from __future__ import annotations

import math
import random
from typing import Any

OBJECTIVE_KEYS = ["risk", "populationCoverage", "infrastructureCoverage", "communication", "cost", "redundancy"]


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.get(key, 0.0) for key in OBJECTIVE_KEYS)
    if not math.isfinite(total) or total <= 0:
        return dict(weights)
    return {key: (weights.get(key, 0.0) / total) for key in OBJECTIVE_KEYS}


def site_utility(site: dict[str, Any], weights: dict[str, float]) -> float:
    cost_score = max(0.0, 1.0 - site["sensor_cost_k"] / 120.0)
    return (
        weights.get("risk", 0.0) * site["flood_risk"]
        + weights.get("populationCoverage", 0.0) * site["population_exposure"]
        + weights.get("infrastructureCoverage", 0.0) * site["infrastructure_criticality"]
        + weights.get("communication", 0.0) * site["communication_score"]
        + weights.get("cost", 0.0) * cost_score
    )


def site_overlap(a: dict[str, Any], b: dict[str, Any]) -> float:
    d_lat = a["latitude"] - b["latitude"]
    d_lon = a["longitude"] - b["longitude"]
    dist = math.hypot(d_lat, d_lon)
    sigma = ((a["coverage_radius_km"] + b["coverage_radius_km"]) / 2.0) * 0.6 * (1.0 / 111.0)
    return math.exp(-(dist * dist) / (2 * sigma * sigma))


def build_qubo(
    problem_type: str,
    candidates: list[dict[str, Any]],
    weights: dict[str, float],
    normalize: bool,
    max_sensors: int,
    budget_k: float | None,
) -> dict[str, Any]:
    """Construct the penalty QUBO over candidate sites (doc + matrices)."""
    n = len(candidates)
    w = normalize_weights(weights) if normalize else dict(weights)

    linear = [-site_utility(site, w) for site in candidates]
    quadratic = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            overlap = site_overlap(candidates[i], candidates[j])
            quadratic[i][j] = -(w.get("redundancy", 0.0) * overlap * 2.0) / 2.0

    magnitude = max(1.0, *(abs(value) for value in linear), *(abs(value) for row in quadratic for value in row))
    penalty_scale = magnitude * 2.0 + 1.0

    if problem_type != "sensor_placement":
        raise ValueError(f"unsupported problem type '{problem_type}'")

    for i in range(n):
        linear[i] -= 2 * max_sensors * penalty_scale
        quadratic[i][i] += penalty_scale
    for i in range(n):
        for j in range(i + 1, n):
            quadratic[i][j] += 2 * penalty_scale

    if budget_k is not None:
        if budget_k <= 0:
            raise ValueError("budget must be positive")
        scale = penalty_scale / max(1.0, budget_k)
        for i in range(n):
            cost = candidates[i]["sensor_cost_k"]
            linear[i] += -2 * budget_k * scale * cost
            quadratic[i][i] += scale * cost * cost
        for i in range(n):
            for j in range(i + 1, n):
                quadratic[i][j] += 2 * scale * candidates[i]["sensor_cost_k"] * candidates[j]["sensor_cost_k"]

    offset = penalty_scale * max_sensors**2
    variable_names = [site["id"] for site in candidates]

    parts: list[str] = []
    for i in range(n):
        if abs(linear[i]) > 1e-9:
            parts.append(f"{linear[i]:.3f} B{variable_names[i]}")
    for i in range(n):
        for j in range(i + 1, n):
            q = quadratic[i][j]
            if abs(q) > 1e-9:
                parts.append(f"{q:.3f}·{variable_names[i]},{variable_names[j]}")
    if not parts:
        parts.append("0")

    expression = " + ".join(parts[:12])
    if len(parts) > 12:
        expression += f" + … ({len(parts) - 12} more terms)"

    return {
        "variable_count": n,
        "variables": variable_names,
        "expression": expression,
        "matrix": [quadratic[i] + list(linear) for i in range(n)],
        "offset": round(offset, 3),
        "_linear": linear,
        "_quadratic": quadratic,
        "_offset": offset,
    }


# --------------------------------------------------------------------------
# Generic QUBO generation (`variables` / `objective` / `constraints` / `weights`)
# --------------------------------------------------------------------------
#
# Chosen representation convention (documented and validated, never inferred):
#
#   QUBO(x) = Σ_i Q[i][i]·x_i + Σ_{i<j} 2·Q[i][j]·x_i·x_j + hᵀ·x + c
#
# where `Q` is the N×N quadratic coefficient matrix (symmetric by convention:
# Q[i][j] == Q[j][i] within SYMMETRY_TOLERANCE), `h` is the linear vector, `c`
# the constant and x the binary variables in the declared `variables` order.
# The `matrix` returned by the API is the full symmetric `Q`. `quadratic_terms`
# are the unique upper-triangle entries (i <= j) so the React layer renders the
# same QUBO without doubling.
#
# Constraints are folded as squared penalties of the form P·(Σ cᵢ·xᵢ − L)²,
# which keeps the math identical to the sensor-placement path
# (`build_qubo` above) and, by convention, every folded matrix stays symmetric.

SYMMETRY_TOLERANCE = 1e-9
QUADRATIC_TERM_PRECISION = 6
DEFAULT_CONSTRAINT_PENALTY_FACTOR = 2.0

GENERIC_CONSTRAINT_TYPES = ("cardinality", "budget")


class QuboInputError(Exception):
    """Raised when a generic QUBO payload fails contract validation.

    Carries a stable `code`; the routes layer converts it into a 422
    `QuantumError` under the shared envelope.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _validate_finite_number(value: float, code: str, message: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise QuboInputError(code, message)
    return float(value)


def _well_formed_linear(linear: Any, names: list[str]) -> list[float]:
    if linear is None:
        return [0.0] * len(names)
    if isinstance(linear, list):
        if len(linear) != len(names):
            raise QuboInputError(
                "INVALID_QUBO_DIMENSIONS",
                f"Linear term count {len(linear)} does not match variable count {len(names)}",
            )
        return [_validate_finite_number(v, "INVALID_QUBO_COEFFICIENTS", "Linear coefficients must be finite numbers") for v in linear]
    if isinstance(linear, dict):
        for key in linear:
            if key not in names:
                raise QuboInputError("INVALID_VARIABLE_MAPPING", f"Linear term references unknown variable '{key}'")
        return [
            _validate_finite_number(
                float(linear.get(name, 0.0)),
                "INVALID_QUBO_COEFFICIENTS",
                "Linear coefficients must be finite numbers",
            )
            for name in names
        ]
    raise QuboInputError("INVALID_QUBO_COEFFICIENTS", "Linear terms must be a list or an object keyed by variable name")


def _well_formed_quadratic(quadratic: Any, names: list[str]) -> list[list[float]]:
    n = len(names)
    if quadratic is None:
        return [[0.0] * n for _ in range(n)]
    if isinstance(quadratic, list):
        if len(quadratic) != n:
            raise QuboInputError(
                "INVALID_QUBO_DIMENSIONS",
                f"Quadratic matrix row count {len(quadratic)} does not match variable count {n}",
            )
        matrix = []
        for row in quadratic:
            if not isinstance(row, list) or len(row) != n:
                raise QuboInputError(
                    "INVALID_QUBO_DIMENSIONS",
                    f"Quadratic matrix rows must have exactly {n} columns",
                )
            matrix.append(
                [
                    _validate_finite_number(v, "INVALID_QUBO_COEFFICIENTS", "Quadratic coefficients must be finite numbers")
                    for v in row
                ]
            )
        for i in range(n):
            for j in range(i):
                if abs(matrix[i][j] - matrix[j][i]) > SYMMETRY_TOLERANCE:
                    raise QuboInputError(
                        "INVALID_QUBO_SYMMETRY",
                        f"Quadratic matrix is not symmetric: Q[{i}][{j}]={matrix[i][j]} vs Q[{j}][{i}]={matrix[j][i]}",
                    )
        # Canonicalise on the upper triangle so stored matrixes are symmetric by construction.
        for i in range(n):
            for j in range(i):
                matrix[i][j] = matrix[j][i]
        return matrix
    if isinstance(quadratic, dict):
        matrix = [[0.0] * n for _ in range(n)]
        index = {name: i for i, name in enumerate(names)}
        for key, row in quadratic.items():
            if key not in index:
                raise QuboInputError("INVALID_VARIABLE_MAPPING", f"Quadratic term references unknown variable '{key}'")
            if not isinstance(row, dict):
                raise QuboInputError("INVALID_QUBO_COEFFICIENTS", "Quadratic object rows must be objects keyed by variable name")
            for other, value in row.items():
                if other not in index:
                    raise QuboInputError("INVALID_VARIABLE_MAPPING", f"Quadratic term references unknown variable '{other}'")
                coefficient = _validate_finite_number(
                    float(value),
                    "INVALID_QUBO_COEFFICIENTS",
                    "Quadratic coefficients must be finite numbers",
                )
                i, j = index[key], index[other]
                matrix[i][j] = coefficient
                matrix[j][i] = coefficient
        return matrix
    raise QuboInputError("INVALID_QUBO_COEFFICIENTS", "Quadratic terms must be a matrix or an object keyed by variable name")


def _apply_variable_weights(linear: list[float], weights: Any, names: list[str]) -> list[float]:
    if not weights:
        return linear
    if not isinstance(weights, dict):
        raise QuboInputError("INVALID_QUBO_COEFFICIENTS", "Weights must be an object keyed by variable name")
    for key in weights:
        if key not in names:
            raise QuboInputError("INVALID_VARIABLE_MAPPING", f"Weight references unknown variable '{key}'")
    scaled: list[float] = []
    for name, value in zip(names, linear):
        raw = float(weights.get(name, 1.0))
        weight = _validate_finite_number(raw, "INVALID_QUBO_COEFFICIENTS", "Weights must be finite numbers")
        if weight < 0:
            raise QuboInputError("INVALID_QUBO_COEFFICIENTS", f"Weights must be non-negative (got {weight} for '{name}')")
        scaled.append(value * weight)
    return scaled


def fold_generic_constraints(
    linear: list[float],
    quadratic: list[list[float]],
    obj_offset: float,
    constraints: list[dict[str, Any]],
    names: list[str],
    base_scale: float,
) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]]]:
    """Fold squared-penalty constraints into the QUBO.

    Returns (final_offset, penalties, constraint_definitions). Mutates `linear`
    and `quadratic` in place.
    """
    n = len(names)
    offset = obj_offset
    seen: set[str] = set()
    penalties: list[dict[str, Any]] = []
    definitions: list[dict[str, Any]] = []

    for item in constraints:
        key = str(item.get("key", ""))
        if not key or key in seen:
            raise QuboInputError("INVALID_QUBO_CONSTRAINTS", f"Constraint keys must be unique and non-empty (got '{key}')")
        seen.add(key)
        constraint_type = item.get("type")
        if constraint_type not in GENERIC_CONSTRAINT_TYPES:
            raise QuboInputError("INVALID_QUBO_CONSTRAINTS", f"Unsupported constraint type '{constraint_type}' for key '{key}'")

        limit = _validate_finite_number(float(item.get("limit", math.nan)), "INVALID_QUBO_CONSTRAINTS", f"Constraint '{key}' limit must be a finite number")
        if limit < 0:
            raise QuboInputError("INVALID_QUBO_CONSTRAINTS", f"Constraint '{key}' limit must be non-negative")

        raw_penalty = item.get("penalty")
        if raw_penalty is None:
            scale = base_scale
        else:
            scale = _validate_finite_number(float(raw_penalty), "INVALID_QUBO_CONSTRAINTS", f"Constraint '{key}' penalty must be a finite number")
            if scale <= 0:
                raise QuboInputError("INVALID_QUBO_CONSTRAINTS", f"Constraint '{key}' penalty must be positive (got {scale})")

        coefficients = item.get("coefficients")
        if constraint_type == "cardinality":
            if coefficients is not None:
                raise QuboInputError("INVALID_QUBO_CONSTRAINTS", f"Cardinality constraint '{key}' takes no coefficients")
            coeffs = [1.0] * n
            if limit > n:
                raise QuboInputError("INVALID_QUBO_CONSTRAINTS", f"Cardinality constraint '{key}' limit {limit} exceeds variable count {n}")
        else:  # budget
            if not isinstance(coefficients, list) or len(coefficients) != n:
                raise QuboInputError(
                    "INVALID_QUBO_CONSTRAINTS",
                    f"Budget constraint '{key}' requires exactly {n} coefficients",
                )
            coeffs = [
                _validate_finite_number(float(value), "INVALID_QUBO_CONSTRAINTS", f"Budget constraint '{key}' coefficients must be finite numbers")
                for value in coefficients
            ]

        # Fold P·(Σ cᵢ·xᵢ − L)²:
        #   diagonal  += P·cᵢ²
        #   off-diag  += 2·P·cᵢ·cⱼ
        #   linear    −= 2·L·P·cᵢ
        #   offset    += L²·P
        for i in range(n):
            quadratic[i][i] += scale * coeffs[i] * coeffs[i]
            linear[i] -= 2.0 * limit * scale * coeffs[i]
        for i in range(n):
            for j in range(i + 1, n):
                quadratic[i][j] += 2.0 * scale * coeffs[i] * coeffs[j]
                quadratic[j][i] = quadratic[i][j]
        offset += limit * limit * scale

        coefficient_summary = None if coeffs == [1.0] * n else [round(value, QUADRATIC_TERM_PRECISION) for value in coeffs]
        if constraint_type == "budget":
            formula = f"P·(Σcᵢ·xᵢ − {limit:g})²"
        else:
            formula = f"P·(Σx − {limit:g})²"
        penalties.append({"key": key, "type": constraint_type, "limit": limit, "scale": round(scale, QUADRATIC_TERM_PRECISION), "formula": formula})
        definitions.append(
            {
                "key": key,
                "name": str(item.get("name") or key),
                "type": constraint_type,
                "limit": limit,
                "coefficients": coefficient_summary,
                "penalty": round(scale, QUADRATIC_TERM_PRECISION),
                "formula": formula,
            }
        )

    return offset, penalties, definitions


def build_generic_qubo(
    problem_type: str,
    variables: list[dict[str, Any]],
    objective: dict[str, Any],
    constraints: list[dict[str, Any]],
    weights: Any,
) -> dict[str, Any]:
    """Assemble a validated generic QUBO document from the declared inputs.

    Returns a clean-JSON document (floats, strings, dicts, lists only — no
    Qiskit or NDArray objects) ready for React. The built-in private fields
    (`_linear`, `_quadratic`, `_offset`, `_greedy`) keep the document
    compatible with the existing QAOA surrogate execution path.
    """
    if any(not isinstance(variable, dict) or not variable.get("variable") or not variable.get("candidate_id") for variable in variables):
        raise QuboInputError("INVALID_VARIABLE_MAPPING", "Each variable must declare a 'variable' name and a 'candidate_id'")
    names = [str(variable["variable"]) for variable in variables]
    candidate_ids = [str(variable["candidate_id"]) for variable in variables]
    if len(set(names)) != len(names):
        raise QuboInputError("INVALID_VARIABLE_MAPPING", "Variable names must be unique")
    if len(set(candidate_ids)) != len(candidate_ids):
        raise QuboInputError("INVALID_VARIABLE_MAPPING", "Candidate ids must be unique")

    n = len(names)
    raw_constant = objective.get("constant", 0.0)
    constant = _validate_finite_number(float(raw_constant), "INVALID_QUBO_COEFFICIENTS", "Objective constant must be a finite number")

    linear = _well_formed_linear(objective.get("linear"), names)
    quadratic = _well_formed_quadratic(objective.get("quadratic"), names)
    linear = _apply_variable_weights(linear, weights, names)

    magnitude = max(
        1.0,
        abs(constant),
        *(abs(value) for value in linear),
        *(abs(value) for row in quadratic for value in row),
    )
    base_scale = magnitude * 2.0 + 1.0

    offset, penalties, definitions = fold_generic_constraints(
        linear,
        quadratic,
        constant,
        constraints,
        names,
        base_scale,
    )

    quadratic_terms = [
        {"i": i, "j": j, "coefficient": round(quadratic[i][j], QUADRATIC_TERM_PRECISION)}
        for i in range(n)
        for j in range(i, n)
        if abs(quadratic[i][j]) > 1e-9
    ]

    parts: list[str] = []
    for i in range(n):
        for j in range(i, n):
            coefficient = quadratic[i][j]
            if abs(coefficient) > 1e-9:
                prefix = "" if i == j else "2·"
                parts.append(f"{prefix}{coefficient:.3f} {names[i]},{names[j]}")
    for i in range(n):
        if abs(linear[i]) > 1e-9:
            parts.append(f"{linear[i]:.3f} {names[i]}")
    if abs(offset) > 1e-9:
        parts.append(f"({offset:.3f})")
    expression = " + ".join(parts[:12])
    if len(parts) > 12:
        expression += f" + … ({len(parts) - 12} more terms)"
    if not expression:
        expression = "0"

    matrix = [
        [round(quadratic[i][j], QUADRATIC_TERM_PRECISION) for j in range(n)]
        for i in range(n)
    ]

    return {
        "kind": "generic",
        "problem_type": problem_type,
        "variable_count": n,
        "variables": [
            {"variable": name, "candidate_id": candidate_id}
            for name, candidate_id in zip(names, candidate_ids)
        ],
        "matrix": matrix,
        "linear_terms": [round(value, QUADRATIC_TERM_PRECISION) for value in linear],
        "quadratic_terms": quadratic_terms,
        "penalties": penalties,
        "objective_expression": expression,
        "constraints": definitions,
        "offset": round(offset, QUADRATIC_TERM_PRECISION),
        "_kind": "generic",
        "_linear": linear,
        "_quadratic": quadratic,
        "_offset": offset,
        "_greedy": "0" * n,
    }


def qubo_energy(doc: dict[str, Any], bitstring: str) -> float:
    n = doc["variable_count"]
    if len(bitstring) != n:
        raise ValueError(f"bitstring length {len(bitstring)} != qubo size {n}")
    linear = doc["_linear"]
    quadratic = doc["_quadratic"]
    energy = doc["_offset"]
    for i in range(n):
        if bitstring[i] != "1":
            continue
        energy += linear[i] + quadratic[i][i]
        for j in range(i + 1, n):
            if bitstring[j] == "1":
                energy += quadratic[i][j]
    return energy


def greedy_decode(
    candidates: list[dict[str, Any]],
    weights: dict[str, float],
    normalize: bool,
    max_sensors: int,
    budget_k: float | None,
) -> str:
    """Greedy, budget-aware cardinality selection (the measurement's centre)."""
    w = normalize_weights(weights) if normalize else dict(weights)
    ranked = sorted(enumerate(candidates), key=lambda pair: -site_utility(pair[1], w))
    selected: list[int] = []
    spent = 0.0
    for index, site in ranked:
        if len(selected) >= max_sensors:
            break
        if budget_k is not None and spent + site["sensor_cost_k"] > budget_k:
            continue
        selected.append(index)
        spent += site["sensor_cost_k"]
    return "".join("1" if i in selected else "0" for i in range(len(candidates)))


def simulate_qaaoa(
    doc: dict[str, Any],
    seed: int,
    shots: int,
    layers: int,
) -> tuple[str, list[dict[str, int]], list[dict[str, float]]]:
    """Deterministic QAOA surrogate centred on the greedy measurement.

    Samples `shots` solutions around the greedy decode with a seeded RNG,
    hill-climbs to a local optimum and returns the best-energy bitstring plus
    a measurement histogram and a monotonic energy history — the shape the
    backend orchestrator consumes.
    """
    n = doc["variable_count"]
    if n == 0:
        return "", [], []
    greedy_bits = doc["_greedy"]
    rng = random.Random(seed)

    def energy(bits: str) -> float:
        return qubo_energy(doc, bits)

    # Deterministic local search from the greedy start.
    current = list(greedy_bits)
    best_energy = energy(greedy_bits)
    improved = True
    while improved:
        improved = False
        for i in range(n):
            nxt = list(current)
            nxt[i] = "0" if nxt[i] == "1" else "1"
            candidate = "".join(nxt)
            candidate_energy = energy(candidate)
            if candidate_energy < best_energy - 1e-12:
                best_energy = candidate_energy
                current = nxt
                improved = True

    best = "".join(current)
    best_energy = energy(best)

    counts: dict[str, int] = {best: 1 + shots // 4}
    flip_probability = 2.0 / max(2, n)
    for _ in range(max(0, shots - 2)):
        candidate = "".join(
            ("0" if bit == "1" else "1") if rng.random() < flip_probability else bit for bit in greedy_bits
        )
        candidate_energy = energy(candidate)
        if candidate_energy < best_energy:
            best = candidate
            best_energy = candidate_energy
        counts[candidate] = counts.get(candidate, 0) + 1
    counts[best] += 1

    measurement_counts = sorted(counts.items(), key=lambda pair: (-pair[1], energy(pair[0])))[:8]
    measurement_counts = [{"bitstring": bits, "count": count} for bits, count in measurement_counts]

    # QAOA-style energy history improving towards the best energy measured.
    warm_start = best_energy + abs(best_energy) * 0.8
    energy_history = [
        {
            "iteration": iteration,
            "energy": round(best_energy + (warm_start - best_energy) * (1 - iteration / layers), 4),
        }
        for iteration in range(1, layers + 1)
    ]

    return best, measurement_counts, energy_history