# API Integration

**Owner:** forecasting module
**Diagram source:** `api-integration.mmd`
**Status legend:** see [`README.md`](README.md)

---

## 1. Ownership split

| Layer | Owner | Navya may modify |
|---|---|---|
| `ForecastRecord` and guards | Forecasting | Yes |
| `ai-service/app/engines/hydro/**` | Forecasting | Yes |
| `ForecastEngine` protocol / factory | Team seam, Navya-authored | Load-bearing — **not** modified by this work |
| HTTP routes (`ai.routes.ts`) | Team | **No** |
| Team contract types (`backend/src/types/contract.ts`) | Team | **No** |
| `forecast-sync.service.ts` | Team | **No** |
| Optimization input | Team | **No** |
| Team database schema | Team | **No** |

> **Existing optimization currently requires forecast_id. Additional forecast-derived risk
> fields require team-owner integration.**

---

## 2. The forecast contract

Defined in `backend/src/features/forecasting/types.ts` and mirrored for the client in
`frontend/src/features/forecasting/types.ts`.

### 2.1 Forecast identity and time

| Concept | Field | Notes |
|---|---|---|
| Forecast identifier | `forecastId` | The only field the team's optimization consumes today |
| Forecast timestamp | `forecastTimestamp` | When the forecast was issued |
| Origin timestamp | backtest `originTimestamp` | What the forecast was made *from* |
| Horizon | `forecastHorizon` | Parsed from a string such as `'6h'`; unparseable input yields `0`, never a guessed default |
| Lead time | `leadTimeRows` | Rows of lead time, in the model's own terms |

### 2.2 Predicted value

| Concept | Fields | Notes |
|---|---|---|
| Predicted value | `predictedValue`, `predictedWaterLevel` | The single authoritative value |
| Inflow | `predictedInflow` | `null` — **target variable is `[NOT CURRENTLY AVAILABLE]`**; water level vs inflow has not been decided |
| Probability | `floodProbability` | Carried from the contract; **never** presented as a calibrated real-world probability without real data |
| Status | `status` | `completed` / `pending` / `failed` |

### 2.3 Model identification and comparison

| Concept | Fields | Notes |
|---|---|---|
| Model | `modelId`, `modelVersion` | |
| Comparison | `ForecastModelComparison` | Per-candidate rows, the selected model, and whether the held-out split was actually scored |
| Candidate score | `mae`, `rmse`, `r2`, `nse` | Regression metrics only |
| Selection | `isSelected`, `isSelectionStatistic` | A validation score is flagged as a selection statistic |
| Guard | `assertComparisonIsHonest` | **Throws** rather than repairing a broken provenance claim |

**No accuracy, precision, recall or F1 appears anywhere**, for a regression target. The team's
`ModelMetrics` carries `accuracy` for classification; for water-level regression that field is
meaningless, and the contract omits it entirely rather than rendering a misleading number.

### 2.4 Forecast time series

`ForecastBacktestPoint[]` — timestamp, origin timestamp, predicted, observed, flood probability,
risk level. This is the only series the chart renders.

The chart never smooths, extrapolates, invents an axis, or draws a threshold that was not sent
to it.

### 2.5 Risk information

| Concept | Fields | Notes |
|---|---|---|
| Risk band | `riskLevel` | LOW / MEDIUM / HIGH / CRITICAL |
| Risk score | `riskScore` | |
| Threshold | `threshold` | **Never hard-coded.** The team's `ReferenceEngine` placeholder `8.0` is deliberately not reused |
| Threshold policy | `thresholdPolicy` | `approved` / `pending` — **returns `pending` on every path**, because the running contract cannot express approval |
| Threshold source | `thresholdSource` | Rendered alongside the value |
| Optimization priority | `priorityForRiskLevel` | Maps a band to a priority for the handoff |

A pending threshold is never rendered as a bare number.

### 2.6 Uncertainty / residual information

`residualSigma` — dispersion of the model's errors. Deliberately **not** converted into a
confidence interval, prediction band, or calibrated probability, because no distributional
assumption or calibration step has been performed on real data.

### 2.7 Data provenance

`ForecastProvenance` — the fields that make a number auditable:

`datasetReference`, `datasetType` (`real` / `synthetic` / `unknown`), `datasetLicense`,
`datasetChecksum`, `samplingInterval`, `stationReference`, `target`, `targetUnits`,
`forecastHorizonHours`, `leadTimeRows`, `modelId`, `modelVersion`, `contractVersion`,
`featureList`, `disclaimer`, `metricsLabel`, `missingFields`.

`datasetType` is load-bearing: the guards, the UI, and the storage constraint all branch on
it. A record typed `unknown` is **not** treated as real.

`targetUnits` lives **only** in provenance. It previously also existed on the record itself,
where the two copies could disagree — the UI could show metres while the guard judged the same
record "units unknown". Provenance is now the single authority.

### 2.8 Synthetic / demo indicator

When `datasetType` is `synthetic`, the contract requires the verbatim disclaimer:

> **THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL
> OBSERVATION DATA.**

and metrics are labelled:

> **synthetic/demo evaluation only**

### 2.9 Metric provenance

`MetricProvenance` — `split` (`train` / `validation` / `test`) and `isSelectionStatistic`.

A metric is presentable as a result **only** when it comes from the held-out `test` split,
from real data, and is internally consistent. Train and validation metrics are refused and
rendered as fit statistics.

---

## 3. Team-owned API surface — not modified

| File | Why it is a blocker |
|---|---|
| `ai-service/app/api/ai.routes.ts` | No route is registered that serves the forecast record. The frontend service has no endpoint to call. |
| `backend/src/types/contract.ts` | The team's API contract has no provenance, metric-split, threshold-policy, or residual-sigma fields. |
| `ai-service/app/services/forecast-sync.service.ts` | L50–63 maps the AI contract into `Forecast` with **no slot** for any forecast-derived field. |
| Optimization input | Accepts `forecast_id` only. |

Navya did not edit any of these.

---

## 4. forecasting-side integration artefacts

Shipped so that a team owner can complete integration without reverse-engineering intent:

| Artefact | File | Purpose |
|---|---|---|
| `toExistingOptimizationPayload` | `backend/.../contract.ts` | Maps onto the team's currently accepted shape |
| `toProposedForecastHandoff` | same | The richer shape, ready for when the schema is extended |
| `FIELDS_REQUIRING_INTEGRATION` | same | The enumerable list of what cannot cross today |
| `LOSSY_FIELDS` | `forecast-adapter.ts` | Fields the team's mapping would drop, named explicitly |
| `adapterGaps` | same | Human-readable gap descriptions |
| `ForecastAdapter` / `ForecastReader` | same | The adapter seam, so Navya code does not hard-code the team's shape |
| `forecastService.ts` | `frontend/.../` | Fetches via the team's existing `fetchJson`; **deliberately does not** inherit the sample-data fallback, so the provenance panel is never fed invented numbers |

The frontend reuses the team's `fetchJson` (auth, timeout, 401 handling) rather than
duplicating a `fetch` wrapper, and creates **no** fake copy of any team module.

---

## 5. Exact team-owner actions required

1. Register a route in `ai-service/app/api/ai.routes.ts` that returns the Navya forecast
   record, or map the existing forecast response to include the forecast fields.
2. Extend `forecast-sync.service.ts` L50–63 with slots for provenance, metric split,
   threshold policy, and residual sigma.
3. Extend the team contract types in `backend/src/types/contract.ts` to carry them.
4. If optimization should consume risk fields, extend its input beyond `forecast_id`.
5. Mount the forecasting dashboard in team routing.
6. Extend the team `ForecastEngine` protocol if the richer contract should be served directly.

Until items 1–3 are done, the Navya backend and frontend are complete and tested but
**not connected to the running system**.
