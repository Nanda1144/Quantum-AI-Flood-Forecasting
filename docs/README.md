# docs

Index of Q-FLARE design documentation and architecture decision records
(ADRs).

> **Status:** the modules document themselves in their own `README.md` files
> (below); ADRs land here as they are written.

## Where the documentation lives

| Topic | Document |
| --- | --- |
| Platform architecture, data flow, module ownership, quick start, config | [`../README.md`](../README.md) |
| Node API gateway — endpoint reference, error codes, security model, fallback policy, persistence | [`../backend/README.md`](../backend/README.md) |
| Frontend command center — pages, adapters, accessibility, test suites | [`../frontend/README.md`](../frontend/README.md) |
| AI forecasting contract + `ForecastEngine` seam (Navya's pipeline) | [`../ai-service/README.md`](../ai-service/README.md) |
| QUBO/QAOA service — payload families, job lifecycle, execution backends | [`../quantum-service/README.md`](../quantum-service/README.md) |
| PostgreSQL schema, migrations, seeds, delete protection | [`../database/README.md`](../database/README.md) |
| Run topology, GitHub Pages workflows, secrets hygiene | [`../deployment/README.md`](../deployment/README.md) |
| GIS / IoT module contracts (planned implementation) | [`../gis/README.md`](../gis/README.md), [`../iot/README.md`](../iot/README.md) |
| Per-feature before/after test reports | [`../tests/README.md`](../tests/README.md) → [`../tests/reports/`](../tests/reports/) |

## ADRs

Planned decision records — each will capture the problem, options considered,
the chosen decision, and consequences:

- **ADR-001** — microservice boundaries and ownership (backend gateway as the
  only consumer of `ai-service`/`quantum-service`; AI vs. quantum ownership
  split between Nanda and Navya).
- **ADR-002** — AI analytics API contract (`GET /api/ai/analytics`) and why the
  gateway, not the frontend, owns the sync into PostgreSQL.
- **ADR-003** — generic QUBO generation/retrieval API (landed in `quantum-service`
  v1.1.0): `POST /quantum/qubo` sensor-placement + generic payloads,
  `GET /quantum/qubo/:id`, `/:id/variables`, `/:id/constraints`).
- **ADR-004** — optimization fallback policy (`retry_simulator` default) and
  why no quantum speedup is ever claimed.
- **ADR-005** — write-once quantum/optimization persistence and the
  `qflare_guard_optimization_delete` trigger.

## Contributing a document

- Keep the **platform pledge** in mind: no fabricated data, no invented
  metrics; every surrogate/fallback is clearly labelled.
- ADR format: Status → Context → Decision → Consequences. One file per ADR,
  numbered.