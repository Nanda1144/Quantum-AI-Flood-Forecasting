/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Browser-side types for the forecast record.
 *
 * ## Relationship to `src/types/ai.ts`
 *
 * `types/ai.ts` is **team-owned and untouched**. It describes what the running
 * AI service returns today. These types describe what the forecasting engine
 * additionally produces, and — the point of the whole module — which of it may
 * legitimately be shown to a user.
 *
 * `RiskLevel`, `PredictionStatus` and the error-shape are re-used from the team
 * module rather than re-declared, so a change to the platform vocabulary cannot
 * leave two incompatible copies in the tree.
 *
 * The backend's version of this contract is `backend/src/features/forecasting/types.ts`.
 * The two are deliberately parallel; neither is generated from the other because
 * there is no shared build step between `backend/` and `frontend/`.
 */

import type { APIError, RiskLevel } from '../../types/ai'

/** Re-exported so a consumer of this module needs only one import. */
export type { APIError, RiskLevel }

/**
 * Lifecycle of a single prediction.
 *
 * Declared here rather than imported: the team spells this union out inline in
 * two places (`Forecast` consumers, `RecentPrediction.status`) and exports no
 * name for it. Duplicating a three-value union is a far smaller coupling than
 * editing a shared file, and TypeScript will still fail loudly here if the
 * team's set ever changes — the raw payload is typed against it in
 * `forecastService.ts`.
 */
export type ForecastPredictionStatus = 'completed' | 'pending' | 'failed'

/** Which target a forecast is for. Both are configurable; neither is mandated. */
export type ForecastTarget = 'water_level' | 'inflow'

/**
 * Approval state of the flood-stage threshold policy.
 *
 * `pending` is its own state rather than a boolean, because a consumer that
 * ignores the difference will display an unapproved threshold as though it were a
 * validated flood stage.
 */
export type ForecastThresholdPolicy = 'pending' | 'approved'

/** Provenance class of the dataset a number came from. */
export type ForecastDatasetType = 'real' | 'synthetic' | 'unknown'

/** Which chronological split a score was measured on. */
export type ForecastSplitLabel = 'train' | 'validation' | 'test'

/**
 * The platform's unresolved-dependency convention, verbatim.
 *
 * Kept as a constant so a test can assert the exact string, and so it cannot
 * drift as surrounding copy changes.
 */
export const HUMAN_INPUT_REQUIRED = 'NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED'

/** The exact required warning for synthetic data. */
export const SYNTHETIC_DATA_DISCLAIMER =
  'THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION DATA.'

/** The label every score computed on synthetic data must carry. */
export const SYNTHETIC_METRIC_LABEL = 'synthetic/demo evaluation only'

/**
 * The verbatim integration statement required by the platform README.
 *
 * The UI renders it. It is not decoration: it is the honest answer to "what does
 * the optimizer actually get from this forecast?", and a user looking at a
 * forecast that appears to drive sensor placement deserves to see it.
 */
export const INTEGRATION_STATEMENT =
  'Existing optimization currently requires forecast_id. ' +
  'Additional forecast-derived risk fields require team-owner integration.'

/**
 * Regression metrics.
 *
 * Deliberately no `accuracy`, `precision`, `recall` or `f1`. A water-level
 * regression has no class labels, so a classification score would be meaningless
 * and inviting. The team's `ModelMetrics` carries `accuracy` because the registry
 * also serves classifiers; it is not something this model can honestly fill in.
 */
export interface ForecastRegressionMetrics {
  mae: number
  rmse: number
  r2: number
  nse: number
  peakAbsoluteError: number
  /** Mean signed error. Positive means the model over-forecasts. */
  bias: number
  nSamples: number
}

/** How a held-out score was obtained. */
export interface ForecastMetricProvenance {
  split: ForecastSplitLabel
  /** True only for a score the model was selected on. */
  isSelectionStatistic: boolean
}

/** One forecast/observation pair from the backtest. */
export interface ForecastBacktestPoint {
  timestamp: string
  /** The instant the forecast was issued from. Always strictly earlier. */
  originTimestamp: string
  predicted: number
  observed: number
  floodProbability: number
  riskLevel: RiskLevel
}

/** Everything known about where a forecast's numbers came from. */
export interface ForecastProvenance {
  datasetReference: string | null
  datasetType: ForecastDatasetType
  datasetLicense: string | null
  datasetChecksum: string | null
  samplingInterval: string | null
  stationReference: string | null
  target: ForecastTarget
  targetUnits: string | null
  forecastHorizonHours: number
  leadTimeRows: number
  modelId: string
  modelVersion: string
  contractVersion: string
  featureList: string[]
  disclaimer: string | null
  metricsLabel: string | null
  /** Provenance fields still unknown. Empty means the record is complete. */
  missingFields: string[]
}

/** The full forecast record the UI renders. */
export interface ForecastRecord {
  forecastId: string
  forecastTimestamp: string
  forecastHorizon: string
  modelId: string
  modelVersion: string
  status: ForecastPredictionStatus
  target: ForecastTarget
  /**
   * Target units live in `provenance.targetUnits` and NOWHERE else.
   *
   * This field previously existed on both the record and its provenance, and the
   * two copies could disagree — the summary read one while the guards read the
   * other, so a record could display metres while being judged "units unknown".
   * Provenance is the single authority; a duplicated fact that can disagree with
   * itself is worse than no fact.
   */
  predictedValue: number
  predictedWaterLevel: number | null
  predictedInflow: number | null
  floodProbability: number
  riskLevel: RiskLevel
  riskScore: number
  /** Flood threshold in target units. Null when none is configured. */
  threshold: number | null
  thresholdPolicy: ForecastThresholdPolicy
  thresholdSource: string | null
  /** Residual sigma measured on the backtest. Null when unmeasurable. */
  residualSigma: number | null
  provenance: ForecastProvenance
  metrics: ForecastRegressionMetrics | null
  metricProvenance: ForecastMetricProvenance | null
  backtest: ForecastBacktestPoint[]
}

/** One row of the model comparison table. */
export interface ForecastModelComparisonRow {
  key: string
  displayName: string
  algorithm: string
  /** Present only when the candidate actually executed. */
  executed: boolean
  /** The selection-split score. Null when the candidate did not run. */
  rmse: number | null
  mae: number | null
  r2: number | null
  nse: number | null
  nSamples: number | null
  /** True only for the model that won the validation ranking. */
  selected: boolean
  /** Set when a candidate could not be evaluated, and why. */
  unavailableReason: string | null
  /** Mandatory label for the scores in this row. */
  metricsLabel: string
}

/** The comparison, plus the honesty metadata a table needs. */
export interface ForecastModelComparison {
  /** 'validation' is the ranking split; 'test' is scored once, afterwards. */
  selectionSplit: ForecastSplitLabel
  heldOutSplit: ForecastSplitLabel
  selectionMetric: string
  selectedKey: string
  rows: ForecastModelComparisonRow[]
  /** Mandatory label attached to every score in the table. */
  metricsLabel: string
  /** True when the held-out split has already been consumed exactly once. */
  heldOutScored: boolean
}

/** Load state for the dashboard. Mirrors the team's `FetchState` shape. */
export interface ForecastState {
  forecast: ForecastRecord | null
  comparison: ForecastModelComparison | null
  loading: boolean
  error: APIError | null
  /** True when the payload came from the team's clearly-flagged sample data. */
  isSampleData: boolean
  reload: () => void
}
