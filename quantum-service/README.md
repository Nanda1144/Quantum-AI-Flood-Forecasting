# quantum-service

Quantum optimization microservice for Q-FLARE — sensor-placement **QUBO**
construction and **QAOA** execution behind a stable REST contract.

> The **Node backend is the only consumer** (see
> `backend/src/clients/quantum-service.client.ts`); the browser never calls this
> service directly. **No quantum speedup is ever claimed** — every result is
> a simulation and always paired with a classical reference benchmark.

## What it does

- `POST /quantum/qubo` — builds a penalty-based sensor-placement QUBO over the
  supplied candidate sites and stores it. The math mirrors
  `backend/src/lib/optimization/qubo.ts` 1:1, so the document here is identical
  to the one the orchestrator builds locally.
- `POST /quantum/optimize` — accepts a QAOA execution
  (`mode`: `simulator` | `aer` | `ibm_hardware`, `backend`, `shots`, `layers`,
  optional `seed`), resolves the backend, runs the deterministic QAOA surrogate,
  and stores the resolved result.
- `GET /quantum/result/:id` — a fully resolved result: measurement counts,
  top bitstring, energy history, execution metadata.
- `GET /health` — liveness + per-backend availability.

All endpoints use the shared `{ success, data | error, timestamp }` envelope
(`app/core/envelope.py`). Error codes are stable so the orchestrator's fallback
policy can act on them (`AER_UNAVAILABLE`, `HARDWARE_UNAVAILABLE`,
`QUBO_UNAVAILABLE`, `QUBO_NOT_FOUND`, `EXECUTION_NOT_FOUND`,
`INVALID_OBJECTIVE_WEIGHTS`).

## Execution backends

| Mode | Reference behaviour | When it `503`s |
| --- | --- | --- |
| `simulator` | Deterministic seeded QAOA surrogate (greedy-centred sampling, hill-climb, energy history), `simulated: true` | — |
| `aer` | Real Qiskit Aer path when installed | `QUANTUM_FORCE_AER_DOWN=true` or `qiskit_aer` not installed → `AER_UNAVAILABLE` |
| `ibm_hardware` | Real Qiskit IBM runtime path when configured | `QUANTUM_FORCE_HARDWARE_DOWN=true`, no `qiskit_ibm_runtime`, or no `QISKIT_IBM_TOKEN` → `HARDWARE_UNAVAILABLE` |

The reference stack ships **without Qiskit** — the Aer/IBM modes therefore
`503` by contract, which is exactly what the backend's
`retry_simulator`/`classical_only` fallback is designed to absorb. The forced
`QUANTUM_*_DOWN` switches let you drill those fallbacks against the live stack
without uninstalling anything.

## Run

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # (Windows)
cp .env.example .env                                       # optional
.venv/Scripts/python -m uvicorn app.main:app --port 8100  # http://localhost:8100
```

## Test

```sh
.venv/Scripts/python -m pytest -q                          # 11 contract tests
```

## Example flow

```sh
# 1) QUBO construction
curl -s -X POST http://localhost:8100/quantum/qubo \
  -H 'Content-Type: application/json' \
  -d '{"problem_type":"sensor_placement","candidates":[{"id":"SIT-001","name":"Sensor 01","zone":"Delta North","latitude":9.0,"longitude":-79.8,"flood_risk":0.7,"population_exposure":0.6,"infrastructure_criticality":0.5,"communication_score":0.4,"sensor_cost_k":30,"coverage_radius_km":12}],"weights":{"risk":0.3,"populationCoverage":0.3,"infrastructureCoverage":0.2,"communication":0.1,"cost":0.1,"redundancy":0},"normalize_weights":true,"constraints":{"max_sensors":1,"budget_k":null,"coverage_requirements":[]}}'

# 2) QAOA execution
curl -s -X POST http://localhost:8100/quantum/optimize \
  -H 'Content-Type: application/json' \
  -d '{"qubo_id":"QUBO-1","algorithm":"qaoa","execution":{"mode":"simulator","backend":"qflare_simulator_statevector","shots":1024,"layers":2,"seed":42}}'

# 3) Resolved result
curl -s http://localhost:8100/quantum/result/EXEC-1
```

## Environment

| Variable | Default | Description |
| --- | --- | --- |
| `QUANTUM_SERVICE_HOST` / `QUANTUM_SERVICE_PORT` | `0.0.0.0` / `8100` | Listener. |
| `QUANTUM_SERVICE_CORS_ORIGINS` | `*` | CORS allow-list (only the Node backend calls this). |
| `QUANTUM_QUBO_DISABLED` | `false` | Force the QUBO endpoint to 503. |
| `QUANTUM_FORCE_AER_DOWN` | `false` | Force Aer executor to 503. |
| `QUANTUM_FORCE_HARDWARE_DOWN` | `false` | Force IBM executor to 503. |
| `QISKIT_IBM_TOKEN` | — | IBM Quantum token for the live-QPU path. |

## Related

- `backend/README.md` — the optimization orchestration API and fallback policy.
- `../frontend/README.md` — the Quantum Optimization page and its HTTP adapter.
- `../backend/src/lib/optimization/qubo.ts` — the twin math this service mirrors.