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

## Source layout

```
src/
├── App.tsx                  # routing + layout + nav
├── pages/
│   ├── AIAnalyticsDashboard.tsx
│   └── QuantumOptimization.tsx   # composition of the 7 quantum panels
├── components/
│   ├── ai/                 # section components for the dashboard
│   ├── charts/             # Recharts wrappers + theme
│   ├── quantum/            # optimization UI: background, modal, controls, panels
│   └── ui/                 # GlassCard, KPICard, Skeletons, banners, indicators
├── hooks/
│   ├── useAIAnalytics.ts
│   └── useQuantumOptimization.ts
├── services/
│   ├── aiService.ts        # API client (fetch + timeout + error contract)
│   └── optimization/       # adapter seam + mock/http implementations + simulator
├── lib/format.ts · risk.ts · quantum.ts
└── types/optimization.ts   # optimization domain contract; types/ai.ts for analytics
```

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `''` | Override the API base (empty = Vite dev proxy). |
| `VITE_USE_MOCK_DATA` | `'true'` | `'false'` → production: live backend for analytics AND the HTTP quantum adapter (`httpAdapter.ts`); the dev simulator chunk is never loaded. Otherwise the analytics sample fallback is allowed and the optimization page runs the flagged mock adapter (`mockAdapter.ts`). |
| `VITE_USE_MOCK_DATA` | `true` | `false` disables the sample-data fallback. |