# frontend — Q-FLARE Command Center (React + TypeScript + Vite)

The single-page command-center UI. Contains the **AI Analytics** dashboard
(Nanda's AI integration module) and the **Quantum Optimization** destination
page.

The dashboard is a data-consumer only: every value (flood probability, water
level, risk, model metrics, timestamps) comes from the `ai-service` REST API —
nothing is hard-coded in the UI.

---

## Quick start

```sh
npm install
npm run dev       # http://localhost:5173  (proxies /api -> localhost:3000)
npm run build     # tsc -b && vite build
npm run lint      # oxlint
npm run preview   # preview the production build
```

Requires `ai-service` to be running alongside (see `../ai-service/README.md`),
or the API layer falls back to clearly-flagged sample data.

## Tests

Vitest + Testing Library + jsdom. Tests run with `VITE_USE_MOCK_DATA=false` so
they exercise the **real HTTP client path** against mocked `fetch`.

```sh
npm test          # one-shot run (23 tests, headless)
npm run test:watch # watch mode
npm run lint      # oxlint
```

| Suite | File | Covers |
| --- | --- | --- |
| `services/aiService.test.ts` | `src/services/aiService` | success/malformed/API-error/timeout, mock gating dev-only, abortable timeout clearing, model comparison |
| `hooks/useAIAnalytics.test.tsx` | `src/hooks/useAIAnalytics` | load/loading/error/refetch states |
| `pages/AIAnalyticsDashboard.test.tsx` | `src/pages/AIAnalyticsDashboard` | all required UI states incl. error + empty + unavailable banners |
| `components/ai/KPIRow.test.tsx` | `src/components/ai/KPIRow` | data-derived trends, mock-badge semantics |
| `components/ai/emptyStates.test.tsx` | `src/components/ai/ForecastSection·PredictionsTable·RiskAnalyticsSection` | honest empty states instead of bare charts/tables |

Test scaffolding lives in `src/test/` (`setup.ts` jest-dom + ResizeObserver +
matchMedia stubs, `fixtures.ts` typed snapshot builders).

## Tech stack

- React 19 + TypeScript, Vite 8, Tailwind CSS v4 (theming via `src/index.css`)
- Recharts (time-series / donut charts), react-router-dom v7, lucide-react

## Page: `/` — AI Analytics

Sections (all built from the snapshot returned by `GET /api/ai/analytics`):

| Section | Component | Data from snapshot |
| --- | --- | --- |
| Header | `components/ai/HeaderSection` | `systemHealth`, `updatedAt` |
| KPI row | `components/ai/KPIRow` | `forecast`, `activeModel` |
| Forecast time-series | `components/ai/ForecastSection` + `charts/ForecastChart` | `forecastSeries`, `thresholds` |
| Risk analytics | `components/ai/RiskAnalyticsSection` | `riskAnalytics` |
| Model information | `components/ai/ModelInfoPanel` | `activeModel` |
| AI → Optimization bridge | `components/ai/OptimizationBridge` | `optimizationReadiness`, `forecast` |
| Recent predictions | `components/ai/PredictionsTable` | `recentPredictions` |
| System state | `components/ai/SystemStatePanel` | `systemHealth` |

### Data hook

`hooks/useAIAnalytics.ts` wraps `services/aiService.ts` and exposes:

- `snapshot` — parsed API payload
- `loading` / `error` / `stale` / `isMock` — UI state
- `refetch()` — manual refresh (Retry button); `markStale()` — auto-stale after
  60 s so the stale-data banner appears

### Required UI states

Loading skeleton · API error banner (+ Retry) · empty state · stale-data
warning · service-unavailable banner · successful state · demo/sample-data
badge.

### AI → Optimization bridge

"Use Forecast for Optimization" navigates to `/quantum-optimization` passing
`forecastId`, `riskScore`, and `priority` via router state only — no global
store is introduced.

### Accessibility & semantics

- Focus-visible rings, keyboard-operable buttons/links
- `aria-label`, `role="status"`, `role="alert"`, table semantics
- Status shown as text + icon/dot, never color alone
- Semantic risk levels (`LOW/MEDIUM/HIGH/CRITICAL`) styled centrally in
  `lib/risk.ts`; number formatting in `lib/format.ts`

## Page: `/quantum-optimization`

Receives the forecast reference from the bridge via `useLocation().state`,
which pre-fills the forecast reference and risk profile. The page is a 7-step
command center backed by a pluggable execution adapter:

- `services/optimization/adapter.ts` — adapter seam. `VITE_USE_MOCK_DATA`
  selects **mock** (development simulator, dynamic-imported so it is excluded
  from production bundles) or **http** (production gateway contract).
- `services/optimization/simulate.ts` — pure, deterministic QUBO → QAOA →
  decode → constraint-validation logic shared by the mock adapter.
- `services/optimization/httpAdapter.ts` — documented future gateway contract
  (`/api/optimization/run`, `/jobs/:id/pipeline|result|qubo|classical|export`,
  `/inputs`); fails loudly until the gateway is deployed.
- `hooks/useQuantumOptimization.ts` — page state machine (config, weights,
  constraints, stage stream, result, abort).
- `lib/quantum.ts` — problem/objective/stage catalog; add a problem here, not
  in the page.
- `components/quantum/` — primitives (`QuantumCircuitBackground`,
  `QuantumModal`, controls, panels) and the 7 step panels.

Invalid decoded solutions are labelled exactly
`INVALID SOLUTION — NOT OPERATIONALLY RECOMMENDED` and never surfaced as a
recommendation.

## Page: `/qubo-visualization/:jobId`

The auditable view of a job's **stored** QUBO formulation — reached from
"Open QUBO visualization" on the optimization page. Every value is served by
`GET /api/optimization/jobs/:id/qubo` (the backend is the single source of
truth; no coefficient is rederived in React).

- Five states, all driven by the payload's `available` field:
  `loading` → `error` / `unavailable` / `invalid` / `valid`.
- Header chips + summary cards (variables, linear terms, quadratic terms,
  constraints, penalty `P`), objective expression panel, an N×2N
  quadratic‖linear heatmap (windowed render above `n > 40`, zoom
  `16/22/30/40`, positive/emerald vs negative/amber), constraint, variable
  and top-bitstring panels, per-term panels, and action exports (QUBO JSON +
  matrix CSV) opening audit modals.
- `services/optimization/quboService.ts` — `fetchQuboFormulation` /
  `fetchQuboPipeline` / `fetchQuboResult`; unwraps the envelope and
  surfacing `unavailable`/`invalid` the moment the payload says so.
- `components/qubo/` — `QuboSummaryCards`, `QuboMatrixHeatmap`,
  `QuboTermPanels`, `QuboObjectivePanel`, `QuboConstraintPanel`,
  `QuboVariablePanel`.
- `types/optimization.ts` — `QuboFormulation` family mirroring the served
  payload (`QuboAvailability`, `QuboConstraintRow`, `QuboPenaltyTerm`,
  `QuboVariableDetail`, …).

## Source layout

```
src/
├── App.tsx                  # routing + layout + nav
├── pages/
│   ├── AIAnalyticsDashboard.tsx
│   ├── QuantumOptimization.tsx   # composition of the 7 quantum panels
│   └── QuboVisualization.tsx     # stored-QUBO audit page (/qubo-visualization/:jobId)
├── components/
│   ├── ai/                 # section components for the dashboard
│   ├── charts/             # Recharts wrappers + theme
│   ├── quantum/            # optimization UI: background, modal, controls, panels
│   ├── qubo/               # QUBO visualization panels: cards, heatmap, terms, objective, constraint, variable
│   └── ui/                 # GlassCard, KPICard, Skeletons, banners, indicators
├── hooks/
│   ├── useAIAnalytics.ts
│   └── useQuantumOptimization.ts
├── services/
│   ├── aiService.ts        # API client (fetch + timeout + error contract)
│   ├── authService.ts      # auth + unauthorized notification helper
│   └── optimization/       # adapter seam + mock/http implementations + simulator + quboService
├── auth/                   # AuthContext (role-aware guards; operator runs optimizations)
├── lib/format.ts · risk.ts · quantum.ts
└── types/optimization.ts   # optimization domain contract; types/ai.ts for analytics
```

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `''` | Override the API base (empty = Vite dev proxy). |
| `VITE_USE_MOCK_DATA` | `''` | `'false'` forces live backends even in dev: disables the AI Analytics sample-data fallback and makes Quantum Optimization select the HTTP adapter. Unset/other → AI Analytics sample fallback is **DEV-only** (`import.meta.env.DEV`, never in production builds); the Optimization page keeps its existing mock/http adapter selection (`services/optimization/adapter.ts`). |