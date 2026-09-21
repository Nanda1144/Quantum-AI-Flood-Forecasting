# quantum-service

Quantum optimization microservice for Q-FLARE — **QUBO** construction and
**QAOA** execution behind a stable REST contract.

> The **Node backend is the only consumer** (see
> `backend/src/clients/quantum-service.client.ts`); the browser never calls this
> service directly. **No quantum speedup is ever claimed** — every result is
> a simulation and always paired with a classical reference benchmark.

## What it does

- `POST /quantum/qubo` — builds a penalty QUBO and stores it. Two payload
  families share the path, discriminated by shape:

  1. **Sensor placement** (`problem_type: "sensor_placement"`, `candidates`,
     objective `weights`, `constraints`) — the original Node-backend contract;
     math mirrors `backend/src/lib/optimization/qubo.ts` 1:1, returns
     `{ qubo_id, doc }` unchanged.
  2. **Generic QUBO** (`variables`, explicit `objective`, `constraints`,
     optional `weights`) — for the React visualization layer. Returns a
     clean-JSON document: `qubo_id`, `problem_type`, `variable_count`,
     symmetric `matrix` (N×N), `linear_terms`, `quadratic_terms` (upper
     triangle, i ≤ j), `penalties`, `objective_expression`, `constraints`,
     `offset`.

- `GET /quantum/qubo/:id` — retrieve the stored QUBO (same shape as its
  creation response).
- `GET /quantum/qubo/:id/variables` — semantic `{ variable, candidate_id }`
  mapping in declaration order.
- `GET /quantum/qubo/:id/constraints` — constraint definitions and the
  penalties each contributes.
- `POST /quantum/optimize` — creates a **job** and returns immediately with
  `{ job_id, execution_id }`. The job then runs asynchronously:
  `queued -> running -> completed | failed | invalid`, with `cancelled`
  reachable from `queued` (immediate) or `running` (cooperative). Accepts the
  `execution` spec (`mode`: `simulator` | `aer` | `ibm_hardware`, `backend`,
  `shots`, `layers`, optional `seed`) plus a `qubo_id`; works on both payload
  families.
- `GET /quantum/jobs/:id/status` — lightweight current job status for polling
  (`status`, timestamps, `cancellable`, `cancel_requested`, `error`).
- `GET /quantum/result/:id` — **current + final job information**. Blocks
  briefly for a terminal state so the synchronous backend consumer keeps the
  original contract, then returns the full document (legacy fields preserved)
  plus the `quantum_results` record. A failed/cancelled/invalid job returns
  `200` with `status` + `error` set — the Node client converts that into a
  `QuantumServiceError` with the stable code.
- `POST /quantum/jobs/:id/cancel` — cancels only when safe: `queued` jobs are
  cancelled immediately; `running` jobs get a cooperative flag the worker
  honours at its checkpoints; a terminal job returns `409`
  `EXECUTION_ALREADY_TERMINAL`.
- `GET /health` — liveness + per-backend availability.

## Job lifecycle + persistence

Every job is a row in the SQLite **`quantum_jobs`** table (algorithm, backend,
qubits, shots, layers, status, `submitted_at` / `started_at` / `completed_at`,
error info, fallback + IBM submission tracking); each completed job writes a
**`quantum_results`** row (bitstring, counts, objective = QUBO energy of the
top bitstring, runtime in ms, metadata). States: `queued | running | completed
| failed | cancelled | invalid`, with every transition a conditional update so
cancel cannot race a completion into a torn state. All state transitions are
atomic (single serialised connection); responses are clean JSON — **no Qiskit
object is ever serialised**.

Storage is ephemeral by default (per-process temp database, same lifetime as
the old in-memory stores); set `QUANTUM_DB_PATH` to a file for persistence.

## Execution backends

### Generic QUBO representation convention

`QUBO(x) = Σᵢ Q[i][i]·xᵢ + Σ_{i<j} 2·Q[i][j]·xᵢ·xⱼ + hᵀx + c`, with **Q stored
as a symmetric N×N matrix** (`Q[i][j] == Q[j][i]`, tolerance `1e-9`); the
`matrix` field is the full symmetric Q. The `objective` input accepts list or
dict-keyed coefficients, and `constraints` are folded as squared penalties
`P·(Σ cᵢ·xᵢ − L)²` (`cardinality` = unit coefficients, `budget` = explicit
per-variable `coefficients`). Coefficients are validated finite (NaN/inf
rejected), matrices dimension-checked against the variable count, variable
mappings and constraint penalties checked, and no Qiskit/NumPy objects ever
leak into responses.

All endpoints use the shared `{ success, data | error, timestamp }` envelope
(`app/core/envelope.py`). Error codes are stable so the orchestrator's fallback
policy can act on them (`AER_UNAVAILABLE`, `HARDWARE_UNAVAILABLE`,
`QUBO_UNAVAILABLE`, `QUBO_NOT_FOUND`, `EXECUTION_NOT_FOUND`,
`EXECUTION_ALREADY_TERMINAL`, `INVALID_EXECUTION_RESULT`, `UNAUTHORIZED`,
`INVALID_OBJECTIVE_WEIGHTS`, `INVALID_QUBO_DIMENSIONS`,
`INVALID_QUBO_COEFFICIENTS`, `INVALID_QUBO_SYMMETRY`,
`INVALID_VARIABLE_MAPPING`, `INVALID_QUBO_CONSTRAINTS`).

## Execution backends

| Mode | Reference behaviour | When it `503`s |
| --- | --- | --- |
| `simulator` | Deterministic seeded QAOA surrogate (greedy-centred sampling, hill-climb, energy history), `simulated: true` | — |
| `aer` | Real Qiskit Aer path when installed | `QUANTUM_FORCE_AER_DOWN=true` or `qiskit_aer` not installed → `AER_UNAVAILABLE` |
| `ibm_hardware` | Real Qiskit IBM runtime path when configured | `QUANTUM_FORCE_HARDWARE_DOWN=true`, no `qiskit_ibm_runtime`, or no `QISKIT_IBM_TOKEN` → `HARDWARE_UNAVAILABLE` |

The reference stack ships **without Qiskit** — Aer/IBM requests therefore fail
their job with the stable contract code (`AER_UNAVAILABLE` /
`HARDWARE_UNAVAILABLE`), which is exactly what the backend's
`retry_simulator`/`classical_only` fallback is designed to absorb. With
`QUANTUM_FALLBACK_ENABLED=true` the **same job** degrades instead to the qflare
simulator, recording `mode_used: "simulator"` + `fallback_applied: true` so the
execution mode is never misrepresented. The forced `QUANTUM_*_DOWN` switches
let you drill both behaviours against the live stack without uninstalling
anything.

## Run

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # (Windows)
cp .env.example .env                                       # optional
.venv/Scripts/python -m uvicorn app.main:app --port 8100  # http://localhost:8100
```

## Test

```sh
.venv/Scripts/python -m pytest -q                          # 63 contract + lifecycle tests
```

## Example flow

```sh
# 1) QUBO construction
curl -s -X POST http://localhost:8100/quantum/qubo \
  -H 'Content-Type: application/json' \
  -d '{"problem_type":"sensor_placement","candidates":[{"id":"SIT-001","name":"Sensor 01","zone":"Delta North","latitude":9.0,"longitude":-79.8,"flood_risk":0.7,"population_exposure":0.6,"infrastructure_criticality":0.5,"communication_score":0.4,"sensor_cost_k":30,"coverage_radius_km":12}],"weights":{"risk":0.3,"populationCoverage":0.3,"infrastructureCoverage":0.2,"communication":0.1,"cost":0.1,"redundancy":0},"normalize_weights":true,"constraints":{"max_sensors":1,"budget_k":null,"coverage_requirements":[]}}'

# 2) QAOA execution -> async job
curl -s -X POST http://localhost:8100/quantum/optimize \
  -H 'Content-Type: application/json' \
  -d '{"qubo_id":"QUBO-1","algorithm":"qaoa","execution":{"mode":"simulator","backend":"qflare_simulator_statevector","shots":1024,"layers":2,"seed":42}}'
# -> data.job_id (== execution_id), e.g. "EXEC-2"

# 3) Poll the lightweight status, or fetch the resolved result
curl -s http://localhost:8100/quantum/jobs/EXEC-2/status
curl -s http://localhost:8100/quantum/result/EXEC-2

# Cancel a job while it is safe (queued -> cancelled; running -> cooperative)
curl -s -X POST http://localhost:8100/quantum/jobs/EXEC-2/cancel

# 4) Generic QUBO (React)
curl -s -X POST http://localhost:8100/quantum/qubo \
  -H 'Content-Type: application/json' \
  -d '{"problem_type":"generic","variables":[{"variable":"x1","candidate_id":"L01"},{"variable":"x2","candidate_id":"L02"},{"variable":"x3","candidate_id":"L03"}],"objective":{"linear":[1.0,-2.0,0.5],"quadratic":[[0,0.5,0],[0.5,0,-1],[0,-1,0]],"constant":0.25},"constraints":[{"key":"max_two","type":"cardinality","limit":2,"penalty":10}]}'

# 5) Retrieve it (doc, variable mapping, constraints)
curl -s http://localhost:8100/quantum/qubo/QUBO-3
curl -s http://localhost:8100/quantum/qubo/QUBO-3/variables
curl -s http://localhost:8100/quantum/qubo/QUBO-3/constraints
```

## Environment

| Variable | Default | Description |
| --- | --- | --- |
| `QUANTUM_SERVICE_HOST` / `QUANTUM_SERVICE_PORT` | `0.0.0.0` / `8100` | Listener. |
| `QUANTUM_SERVICE_CORS_ORIGINS` | `*` | CORS allow-list (only the Node backend calls this). |
| `QUANTUM_QUBO_DISABLED` | `false` | Force the QUBO endpoint to 503. |
| `QUANTUM_FORCE_AER_DOWN` | `false` | Force Aer executor to fail jobs with `AER_UNAVAILABLE`. |
| `QUANTUM_FORCE_HARDWARE_DOWN` | `false` | Force IBM executor to fail jobs with `HARDWARE_UNAVAILABLE`. |
| `QISKIT_IBM_TOKEN` | — | IBM Quantum token for the live-QPU path (server-side only). |
| `QUANTUM_DB_PATH` | *ephemeral* | SQLite file for the `quantum_jobs` / `quantum_results` tables. |
| `QUANTUM_API_TOKEN` | — | Optional bearer-token gate (all endpoints except `/health`). |
| `QUANTUM_FALLBACK_ENABLED` | `false` | Degrade a failed Aer/IBM job to the simulator in the same job. |
| `QUANTUM_JOB_DELAY_MS` | `0` | Pacing knob (≤5000 ms) so queued/running states are observable. |
| `QUANTUM_RESULT_WAIT_MS` | `30000` | How long `GET /quantum/result/:id` waits for a terminal state. |

## Related

- `backend/README.md` — the optimization orchestration API and fallback policy.
- `../frontend/README.md` — the Quantum Optimization page and its HTTP adapter.
- `../backend/src/lib/optimization/qubo.ts` — the twin math this service mirrors.