/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Public surface of the Navya forecasting module.
 *
 * ## What a team owner needs to mount this
 *
 * ```tsx
 * import { NavyaForecastDashboard } from './navya/forecasting'
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

export { NavyaForecastDashboard } from './NavyaForecastDashboard'
export { NavyaForecastSummary } from './NavyaForecastSummary'
export { NavyaRiskDisplay } from './NavyaRiskDisplay'
export { NavyaForecastSeriesChart } from './NavyaForecastSeriesChart'
export { NavyaModelComparison } from './NavyaModelComparison'
export { NavyaProvenancePanel, HumanInputNote } from './NavyaProvenancePanel'
export { NavyaForecastPage } from './NavyaForecastPage'
export { NavyaForecastScope } from './NavyaForecastScope'
export { NavyaStationSelector } from './NavyaStationSelector'
export { NavyaRiverSelector } from './NavyaRiverSelector'
export { NavyaSeriesAvailability } from './NavyaSeriesAvailability'
export { NavyaExposureDisplay } from './NavyaExposureDisplay'

export { useNavyaForecast } from './useNavyaForecast'

export {
  loadNavyaComparison,
  loadNavyaForecast,
  navyaForecastApi,
  parseHorizonHours,
  toNavyaForecastRecord,
  toNavyaModelComparison,
} from './navyaForecastService'
export type { RawForecastPayload } from './navyaForecastService'

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
  NO_RIVER_IDENTITY_REASON,
  NO_STATION_REGISTRY_REASON,
  describeRiverSelection,
  describeStationSelection,
  riverRegistryAvailability,
  riverScopeStatus,
  riversFromRecord,
  stationRegistryAvailability,
  stationScopeStatus,
  stationsFromRecord,
} from './scope'
export type {
  NavyaRiverOption,
  NavyaRiverScopeStatus,
  NavyaScopeAvailability,
  NavyaScopeNote,
  NavyaScopeTone,
  NavyaStationOption,
  NavyaStationScopeStatus,
} from './scope'

export { expectedPeakOf, forecastSeriesOf, timeToThreshold } from './derived'
export type {
  ExpectedPeakResult,
  NavyaForecastSeriesPoint,
  TimeToThresholdResult,
} from './derived'

export {
  INFRASTRUCTURE_EXPOSURE_REASON,
  POPULATION_EXPOSURE_REASON,
  RESPONSE_PRIORITY_REASON,
  describeExposureReading,
  exposureReadings,
  infrastructureExposure,
  populationExposure,
  responsePriority,
} from './exposure'
export type {
  NavyaExposureAvailability,
  NavyaExposureKind,
  NavyaExposureReading,
} from './exposure'

export {
  HUMAN_INPUT_REQUIRED,
  INTEGRATION_STATEMENT,
  SYNTHETIC_DATA_DISCLAIMER,
  SYNTHETIC_METRIC_LABEL,
} from './types'
export type {
  NavyaBacktestPoint,
  NavyaDatasetType,
  NavyaForecastRecord,
  NavyaForecastState,
  NavyaForecastTarget,
  NavyaMetricProvenance,
  NavyaModelComparison as NavyaModelComparisonData,
  NavyaModelComparisonRow,
  NavyaPredictionStatus,
  NavyaProvenance,
  NavyaRegressionMetrics,
  NavyaSplitLabel,
  NavyaThresholdPolicy,
} from './types'
