# deployment

Run topology, containerisation notes, and CI/CD workflows for Q-FLARE.

> **Status:** build/deploy workflows for the frontend are live on GitHub
> Actions; container manifests (Docker Compose / Kubernetes) are planned but
> not yet written. Each service currently runs standalone in dev.

## Runtime topology

```
Browser
   │  /api (same-origin proxy in dev; static SPA in production)
   ▼
┌────────────────────── backend  (Node/Express gateway, :3000) ──────────────┐
│ /api/health · /api/auth · /api/ai/* · /api/optimization/*                  │
│   └── ForecastClient ──► ai-service (FastAPI, :8000)                       │
│   └── QuantumClient  ──► quantum-service (FastAPI, :8100)                  │
│   └── PostgreSQL (:5432)  ←— ensured via database/migrations at boot       │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Service | Port | Runs | Notes |
| --- | --- | --- | --- |
| `frontend` | 5173 (dev) / static | Vite dev server or built `dist/` | Proxies `/api` → backend in dev (`frontend/vite.config.ts`). Production serves just static assets. |
| `backend` | 3000 | Node/Express gateway | **Single consumer** of `ai-service` and `quantum-service`; owns auth/RBAC, validation, rate limiting, Postgres persistence. No secrets leave this process. |
| `ai-service` | 8000 | FastAPI (uvicorn) | Forecasting contract + `ForecastEngine` seam. Stateless — persists nothing. |
| `quantum-service` | 8100 | FastAPI (uvicorn) | QUBO construction + QAOA execution; job lifecycle in an SQLite store. |
| PostgreSQL | 5432 | Database | Schema bootstrapped automatically (`ensureSchema`); in-memory repos used when unreachable (`DATABASE_MODE=memory`). |

Start order for a full local stack: `database` → `ai-service` → `quantum-service`
(optional; the fallback policy covers its absence) → `backend` → `frontend`. See
the module READMEs and the root `README.md` "Quick start".

## GitHub Pages (frontend)

Two Action workflows publish the **built frontend only** (never repository
source) to Pages:

- `.github/workflows/deploy.yml` — on push to `features/Nanda-ai-quantum` (the
  current active branch).
- `.github/workflows/static.yml` — on push to `main`.

Both run `frontend: npm ci && npm run build`, upload `frontend/dist` as the
Pages artifact, and deploy. See `.github/workflows/README.md`.

## Security posture

- The browser only ever talks to the `backend` gateway; services are
  server-to-server behind it. `/api` routes require a JWT
  (`AUTH_ENABLED=true`, default).
- Credentials (`DATABASE_URL`, `JWT_SECRET`, `QISKIT_IBM_TOKEN`, demo
  passwords) live only in server-side `.env` files and are never shipped to
  the SPA bundle.
- Operator scratch scripts and local env files are git-ignored
  (`.gitignore`: `backend/check_*.mjs`, `*.pem`, `.env*`).

## Secrets hygiene (important)

Real connection/token values must **never** be committed. `backend/check_*.mjs`
and `backend/*.scratch.*` operator scripts used for ad-hoc DB checks are
git-ignored on purpose — if you ever need to run one, keep it local and delete
it after the check. Rotate any credential that was ever pushed.

## Planned

- `docker-compose.yml` orchestrating `backend` + `ai-service` +
  `quantum-service` + PostgreSQL with the backend as the shared edge gateway.
- Per-branch preview deploys and CI gate (build + lint + test) on PR.
- Kubernetes manifests for the long-running services.