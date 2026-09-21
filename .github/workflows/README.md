# GitHub Actions workflows

Q-FLARE CI/CD. Currently two **frontend → GitHub Pages** deploy workflows;
repository test/build CI gates for the other modules are planned.

| Workflow | Triggers | What it does |
| --- | --- | --- |
| [`deploy.yml`](./deploy.yml) | push to `features/Nanda-ai-quantum`, `workflow_dispatch` | `frontend`: `npm ci` → `npm run build` → upload `frontend/dist` as the Pages artifact → `deploy-pages`. |
| [`static.yml`](./static.yml) | push to `main`, `workflow_dispatch` | Same as above for the default branch. Kept separate so the active feature branch and `main` never fight over the Pages concurrency group. |

Both:

- publish **only the built SPA** — the repository source (backend, secrets,
  `.env` references) is never uploaded as a Pages artifact;
- require the `pages: write` + `id-token: write` permissions and deploy to the
  `github-pages` environment.

## Adding CI for backend / services

The repository test commands are ready to wire into PR workflows:

- `backend`: `npm run lint`, `npm run build`, `npm run test:unit`,
  `npm run test:integration` (integration needs PostgreSQL or skips gracefully).
- `frontend`: `npm run lint`, `npm run build`, `npm test` (23 tests, headless).
- `ai-service` / `quantum-service`: `python -m pytest -q`.

Suggested next workflow: run `backend` lint+build+unit and `frontend`
lint+build+test on every PR against the feature branch.