# Test Report — AI Analytics Dashboard

## Feature

- **Name:** AI Analytics Dashboard (`/` page)
- **Scope (module(s)):** frontend · backend · ai-service · database · data · tests
- **Owner:** Nanda
- **Date:** 2026-09-21
- **Status:** COMPLETE-PARTIAL (remaining items listed in §7)

## 1. Before (baseline / audit findings)

Compiled from the authoritative `# AI ANALYTICS QA REPORT` audit of the whole
module.

| Area | Finding | Severity |
| --- | --- | --- |
| Frontend | KPI trend badges were hardcoded (`Rising`/`Falling`/`Flat`), not derived from the real series — QA misread real data on the lead card. | high |
| Frontend | Forecast threshold line was dead: `thresholdLevel` never arrived from the backend (`ForecastChart` threshold `undefined`), and body box static text doesn't render. | high |
| Frontend | "AI service unavailable" banner was dead code — it only rendered on `systemHealth.status === 'unavailable'`, which the backend never emits (it emits `degraded` when serving cache). | medium |
| Frontend | No frontend test framework or tests existed at all. | medium |
| Frontend | Sample-data fallback gating was described as controllable by env alone; verified only `import.meta.env.DEV` semantics in production builds. | medium |
| Frontend | `ModelInfoPanel` showed version status as literal `"v-diff"` text; fallback "active model" (no registry row) was shown as if it were registry data. | medium |
| Frontend | Active-model fallback was unlabelled — users saw a registry-look record that was really assembled from the forecast. | medium |
| Frontend | Charts/tables had no empty states (`ForecastSection`, `PredictionsTable`, `RiskAnalyticsSection`). | low |
| Frontend | Donut tooltip label was wrong (`"Risk "` prefix from `name`) making the legend suspect. | low |
| Frontend | No `ErrorBoundary` — a render error would blank the whole SPA. | medium |
| Backend | `RiskAnalyticsContract` omitted threshold fields; `analytics.service.ts` never populated `snapshot.thresholds` (only default `Derived`), so the threshold feature was dead end-to-end. | high |
| Backend | Latency health probe results were never captured into the snapshot (`apiLatencyMs`). | low |
| AI service | Engine errors bubbled as raw Python exceptions with HTTP 500 on most endpoints; only `/forecast` used structured `AIError`. | high |
| AI service | `main.py` had no `__main__` runner honoring `AI_SERVICE_HOST`/`AI_SERVICE_PORT` (server could not be started standalone with its own config). | medium |
| AI service | `RiskAnalytics` had no threshold fields to forward. | medium |
| Database | (unchanged) `models` table is where the gateway upserts AI models; `model_versions`/`model_metrics` power the comparison page; migration 008 + `ensureSchema` boot re-apply already resolved. | n/a |
| Tests | No threshold, no contract-prediction, no ai-service structured-error tests; no backend derived-fallback test; no frontend tests. | high |

## 2. Problems identified

1. **Dead threshold feature** — thresholds never crossed the wire: ai-service
   didn't expose them, backend contract+service didn't map them, frontend got
   `undefined`.
2. **Misleading UI data** — hardcoded trends, `"v-diff"`, unlabelled derived
   active model, inaccurate tooltip labels, dead unavailable banner.
3. **Raw 500s** — engine failures on `risk-analytics`, `status`, `predictions`,
   `models` returned unstructed Python tracebacks on 500 instead of the
   consistent `{ error: { code, message } }` envelope.
4. **No bundle-of-proof** — no frontend test suite; no tests proving threshold
   flow, structured errors, or derived-model labelling.
5. **Environment friction** — `ai-service` could not run standalone honoring
   `AI_SERVICE_HOST`/`AI_SERVICE_PORT`; docs described `ai-service` as
   "Node/Express on :3000" (it is FastAPI on :8000).

## 3. What we did (resolution)

**ai-service**
- `app/schemas/models.py`: added `threshold_level` (`ge=0.0`) and
  `threshold_label` to `RiskAnalytics`; removed unused `PredictionsResponse`.
- `app/engines/reference.py`: reference engine now returns
  `threshold_level=THRESHOLD_LEVEL` (8.0 m) and `threshold_label="Flood stage reference"`.
- `app/api/routes.py`: added `_engine_call(operation, fn)` helper wrapping every
  engine call; all endpoints now raise structured `AIError(
  "FORECAST_ENGINE_ERROR", …, 502)` instead of leaking raw exceptions. CORS kept
  `*` (documented as a remaining item).
- `app/main.py`: added `if __name__ == "__main__"` runner using
  `uvicorn.run("app.main:app", host=config.HOST, port=config.PORT)` so
  `python -m app.main` honors `AI_SERVICE_HOST`/`AI_SERVICE_PORT`.

**backend**
- `src/types/contract.ts` / `src/types/domain.ts`: `RiskAnalyticsContract` +
  `threshold_level`/`threshold_label`; `AnalyticsSnapshot.activeModel.derived?`.
- `src/services/analytics.service.ts`: parallel health probe via
  `client.health().catch(() => null)` → `apiLatencyMs`; thresholds now sourced
  from `riskAnalytics.thresholdLevel/thresholdLabel` (fallback keeps the old
  default when upstream omits them); `activeModel` fallback labelled
  `derived: true`; `systemHealth.status` = `'online'` only when
  `source === 'ai' && !isStale`, else `'degraded'` (truthful when serving cache).
- Data/DB layer untouched (no migration needed); `models` table + registry
  behaviour unchanged.

**frontend**
- `services/aiService.ts`: mock fallback now gated by
  `import.meta.env.DEV && VITE_USE_MOCK_DATA !== 'false'` via exported
  `shouldAllowMockData()` (lazy eval so tests can toggle); production builds
  NEVER serve sample data.
- `components/ai/KPIRow.tsx`: trends derived from the real
  `probabilityTrend`/`forecastSeries` via `trendFromSeries(values, 0.02)`;
  Model Version status text now `modelStatusText(activeModel.status)`.
- `components/charts/RiskDistributionChart.tsx`: tooltip reads
  `item?.payload?.riskLevel` (correct labels).
- `components/ai/ForecastSection.tsx`, `PredictionsTable.tsx`,
  `RiskAnalyticsSection.tsx`: empty states instead of bare charts/tables.
- `pages/AIAnalyticsDashboard.tsx`: unavailable banner now triggers whenever
  `snapshot.systemHealth?.status !== 'online'` with `onRetry` (previously dead).
- `components/ai/ModelInfoPanel.tsx` + `types/ai.ts`: `ModelInfo.derived?` →
  amber note "Assembled from the forecast record — no stored registry row".
- `components/ErrorBoundary.tsx` (new) wraps the routed pages in `App.tsx` —
  a render error shows a contained fallback with Reload instead of a blank SPA.
- `test/setup.ts` + `vitest.config.ts`: jsdom env, jest-dom matchers,
  ResizeObserver/matchMedia polyfills; `package.json` `test`/`test:watch`;
  vitest default env `VITE_USE_MOCK_DATA=false`.
- Added 23 tests across 5 files (see §5); verified `prefers-reduced-motion`
  global CSS already disables `animate-ping`/`animate-pulse` (no change needed).

**docs / env**
- `frontend/.env.example` added; `frontend/README.md` env table deduplicated and
  rewritten for DEV-only analytics semantics (Quantum Optimization's existing
  adapter selection still keys off the same flag and was NOT changed, out of
  scope); `src/vite-env.d.ts` comment corrected;
  `deployment/README.md` corrected (`backend` gateway :3000, `ai-service`
  FastAPI :8000, `frontend` proxies `/api` to the gateway).

## 4. After (verified state)

| Area | Verification | Result |
| --- | --- | --- |
| Frontend KPI trends | KPIRow test: rising/falling derived from series; no `Rising` on a falling series | PASS |
| Frontend model status | `modelStatusText` no longer emits `v-diff` | PASS |
| Threshold end-to-end | backend integration asserts `snapshot.thresholds.thresholdLevel === 8.0` + label; ai-service contract test asserts threshold fields | PASS |
| Latency wiring | backend integration asserts `apiLatencyMs === 42` | PASS |
| Derived active model | backend integration uses registry-less client → `activeModel.derived === true`; ModelInfoPanel note renders | PASS |
| Unavailable banner | dashboard test: degraded snapshot → "AI service is unavailable" + Retry calls refetch | PASS |
| Empty states | ForecastSection/PredictionsTable/RiskAnalyticsSection tests | PASS |
| Structured AI errors | ai-service `_FailingEngine` test: 5 endpoints → 502 `FORECAST_ENGINE_ERROR` | PASS |
| Standalone ai-service | `main.py` runner honors host/port | PASS |
| Sample-data gating | aiService tests: success (no mock), 401 (no fallback), disabled → API error, enabled → flagged mock | PASS |
| Auth integrity | UNAUTHORIZED never falls back to sample data | PASS |
| Error boundary | component added; wrapped routes | PASS |

## 5. Tests

| Suite | Before | After |
| --- | --- | --- |
| `ai-service` pytest (`test_contract.py` + engine suites) | 5 passed | 8 passed, 0 failed |
| `backend` unit (`npm run test:unit`, vitest) | 123 passed | 123 passed, 0 failed |
| `backend` integration (`npm run test:integration`, vitest, live Postgres) | 146 passed | 147 passed, 0 failed |
| `frontend` vitest (`npm test`) | — (no suite) | 23 passed, 0 failed (5 files) |

Commands used (exact):

```
# ai-service
ai-service/.venv/Scripts/python.exe -m pytest -q
# backend
npm run build && npm run lint && npm run test:unit && npm run test:integration
# frontend
npm run build && npm run lint && npm test
```

## 6. Build & lint

| Check | Command | Result |
| --- | --- | --- |
| backend build (tsc) | `npm run build` (backend) | PASS |
| backend lint (oxlint) | `npm run lint` (backend) | PASS |
| ai-service import/build | `python -m app.main` path runner + pytest collection | PASS |
| frontend build (`tsc -b && vite build`) | `npm run build` (frontend) | PASS |
| frontend lint (oxlint) | `npm run lint` (frontend) | PASS |

## 7. Remaining issues (not fixed, with reason)

- **Default demo credentials & default JWT secret** (`backend/src/config.ts:135-139`,
  `config.ts:47`) — security hygiene outside this feature's scope; the QA report
  lists them for a separate security pass.
- **CORS allowed for all origins** (`ai-service/app/main.py`/config) — operationally
  acceptable for the local tool; tighten for public exposure.
- **No `helmet`, tokens in sessionStorage** — auth hardening, separate concern
  (existing backend system, not re-designed).
- **Credential-bearing untracked scripts** (`backend/check_registry.mjs`,
  `backend/check_listversions.mjs`, `backend/check_registry_list.mjs`) — flagged
  in QA; remove or move `.env`-driven before any public repo push.
- **Registry vocabulary mismatch** — registry `active|retired|development`
  vs ai-service `ready|training|degraded|offline`; semantically different
  domains (lifecycle vs runtime); documented, not coerced.
- **`optimizationReadiness` fallback** — pre-existing, unrelated to this feature
  review; left as-is.
- **Unused `PredictionsResponse`** — existed only in `ai-service/app/schemas/models.py`
  and was removed during this work; nothing remains in the backend.
- **Bundle size warning** (Vite `>500 kB` chunk) — needs code-splitting; not a
  correctness issue.

## 8. Final verdict

**Status:** COMPLETE-PARTIAL

The AI Analytics Dashboard now renders only from the live API in production,
shows honestly-derived trends and threshold data that actually flows
ai-service → backend → frontend, labels derived model records as such, surfaces
structured AI errors with retry, and never lies about availability. All four
test suites are green (301 passing tests total across the module) and builds +
lint pass. The remaining items are security hardening and packaging concerns
outside this feature review, tracked in §7.