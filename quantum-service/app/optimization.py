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
        "matrix": [quadratic[i] + [linear[i]] for i in range(n)],
        "offset": round(offset, 3),
        "_linear": linear,
        "_quadratic": quadratic,
        "_offset": offset,
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