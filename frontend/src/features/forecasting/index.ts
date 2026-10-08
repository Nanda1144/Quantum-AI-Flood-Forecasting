/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform . It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Public surface of the forecasting module.
 *
 * ## What a team owner needs to mount this
 *
 * ```tsx
 * import { ForecastDashboard } from './features/forecasting'
 * ```
 *
 * That is the whole integration on the frontend side. The component fetches its
 * own data, renders its own provenance and evaluation status, and is not mounted
 * on any existing route.
 *
 * ## What is exported and why
 *
 * - **Components** — the five panels plus the dashboard that composes them.
 * - **The hook** — for an owner who wants the data without the layout.
 * - **The guards** — pure, DOM-free, and the part worth unit-testing. They encode
 *   every honesty rule in this module, so a change to the rules is a visible
 *   change in `contract.ts` rather than a silent change in a JSX branch.
 * - **The service** — exposed so an owner can point the client at a different
 *   endpoint without copying the normalizers.
 * - **The types and the required statements** — `INTEGRATION_STATEMENT` and
 *   `SYNTHETIC_DATA_DISCLAIMER` are exported so a test can assert the exact
 *   string and so the wording cannot drift between the code and the docs.
 *
 * `RawForecastPayload` is exported for the same reason: it is the shape the
 * running contract actually sends, and an owner extending the backend contract
 * needs a named type to extend rather than an inline literal.
 */

export { ForecastDashboard } from './ForecastDashboard'
export { ForecastSummary } from './ForecastSummary'
export { ForecastRiskDisplay } from './ForecastRiskDisplay'
export { ForecastSeriesChart } from './ForecastSeriesChart'
export { ForecastModelComparison } from './ForecastModelComparison'
export { ProvenancePanel, HumanInputNote } from './ProvenancePanel'

export { useForecast } from './useForecast'

export {
  loadForecastComparison,
  loadForecast,
  forecastApi,
  parseHorizonHours,
  toForecastRecord,
  toForecastModelComparison,
} from './forecastService'
export type { RawForecastPayload } from './forecastService'

export {
  assertComparisonIsHonest,
  bannerSeverity,
  describeDatasetType,
  describeThreshold,
  humanInputRequired,
  integrationStatement,
  isPresentableAsRealResult,
  mandatoryForecastLabel,
  mandatoryMetricLabel,
  metricPresentation,
  openQuestions,
  rowIsScored,
  rowUnavailableReason,
  summariseProvenance,
  thresholdIsOfficial,
} from './contract'

export {
  HUMAN_INPUT_REQUIRED,
  INTEGRATION_STATEMENT,
  SYNTHETIC_DATA_DISCLAIMER,
  SYNTHETIC_METRIC_LABEL,
} from './types'
export type {
  ForecastBacktestPoint,
  ForecastDatasetType,
  ForecastRecord,
  ForecastState,
  ForecastTarget,
  ForecastMetricProvenance,
  ForecastModelComparison as ForecastModelComparisonData,
  ForecastModelComparisonRow,
  ForecastPredictionStatus,
  ForecastProvenance,
  ForecastRegressionMetrics,
  ForecastSplitLabel,
  ForecastThresholdPolicy,
} from './types'
