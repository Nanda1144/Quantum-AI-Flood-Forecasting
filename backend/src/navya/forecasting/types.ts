/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Types for Navya's forecast → optimization contract.
 *
 * ## Relationship to `src/types/contract.ts`
 *
 * `contract.ts` is **team-owned and deliberately untouched**. It describes the
 * payload the *running* AI service returns today. The types here describe what
 * Navya's forecasting engine additionally produces, and — crucially — which of
 * those additions the running optimizer can already accept.
 *
 * The split matters because it is the honest answer to "what does the optimizer
 * get?":
 *
 * - `ExistingOptimizationPayload` — the exact subset
 *   `OptimizationService.createFromForecast` understands today. Fully
 *   backward-compatible; usable right now.
 * - `ProposedForecastHandoff` — the full record Navya produces. **Not**
 *   consumable today. Every field beyond the existing payload needs a
 *   team-owner change, listed in `TEAM_INTEGRATION_REQUIREMENTS.md`.
 *
 * Nothing in this file is mounted into a team route. It is a declared contract
 * plus the pure functions that build it, so the mapping can be reviewed and
 * tested before anyone wires it up.
 */

import type {
  ForecastContract,
  PredictionStatus,
  RiskLevel,
} from '../../types/contract.ts'

/** Which target a forecast is for. Both are configurable; neither is mandated. */
export type ForecastTarget = 'water_level' | 'inflow'

/**
 * Approval state of the flood-stage threshold policy behind a risk level.
 *
 * `pending` means a threshold exists and is being used, but nobody has signed it
 * off as official. It is reported as its own state rather than being flattened
 * into a boolean, because a consumer that ignores the difference will otherwise
 * display an unapproved threshold as though it were a validated flood stage.
 */
export type ThresholdPolicy = 'pending' | 'approved'

/** Provenance class of the dataset a number came from. */
export type DatasetType = 'real' | 'synthetic' | 'unknown'

/**
 * Verbatim integration statement required by the platform README.
 *
 * Kept as an exported constant (not inlined) so a test can assert the exact
 * string, and so it cannot drift silently as surrounding code changes.
 */
export const INTEGRATION_STATEMENT =
  'Existing optimization currently requires forecast_id. ' +
  'Additional forecast-derived risk fields require team-owner integration.'

/** Marks a value that came from the SYNTHETIC/DEMO generator. */
export const SYNTHETIC_DATA_DISCLAIMER =
  'THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION DATA.'

/** Marks metrics computed on synthetic data. */
export const SYNTHETIC_METRIC_LABEL = 'synthetic/demo evaluation only'

/**
 * Regression metrics computed by the forecasting pipeline.
 *
 * Deliberately no `accuracy`, `precision`, `recall` or `f1`. A regression
 * forecast has no class labels, so a classification score would be meaningless
 * and inviting. `accuracy` is present on the team's `ModelMetricsContract`
 * because the registry also serves classifiers; it is not something a
 * water-level regression can honestly fill in.
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

/** Which split a score was computed on. */
export type SplitLabel = 'train' | 'validation' | 'test'

/**
 * How a held-out score was obtained.
 *
 * A `validation` score was optimised against and is optimistic by construction.
 * A `test` score was computed once, by the selected model, and is the only
 * figure that should be shown as the model's performance.
 */
export interface MetricProvenance {
  split: SplitLabel
  /** True only for a score the model was selected on. */
  isSelectionStatistic: boolean
}

/** One held-out forecast/observation pair from the backtest. */
export interface BacktestPoint {
  /** The instant being predicted. */
  timestamp: string
  /** The instant the forecast was issued from. Always strictly earlier. */
  originTimestamp: string
  predicted: number
  observed: number
  /** P(level > threshold) computed from the MEASURED residual spread. */
  floodProbability: number
  riskLevel: RiskLevel
}

/** Everything Navya knows about where a forecast's numbers came from. */
export interface ForecastProvenance {
  datasetReference: string | null
  datasetType: DatasetType
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
  /**
   * Provenance fields that are still unknown. An empty array means the record is
   * complete; a non-empty one is a list of open questions, not a defect to be
   * hidden by filling in a default.
   */
  missingFields: string[]
}

/** The full forecast record Navya produces, before any handoff narrowing. */
export interface NavyaForecastRecord {
  forecastId: string
  forecastTimestamp: string
  forecastHorizon: string
  modelId: string
  modelVersion: string
  status: PredictionStatus
  target: ForecastTarget
  targetUnits: string | null
  predictedValue: number
  predictedWaterLevel: number | null
  predictedInflow: number | null
  floodProbability: number
  riskLevel: RiskLevel
  riskScore: number
  /** Flood threshold used, in target units. Null when none is configured. */
  threshold: number | null
  thresholdPolicy: ThresholdPolicy
  thresholdSource: string | null
  /** Residual sigma measured on the backtest. Null when unmeasurable. */
  residualSigma: number | null
  provenance: ForecastProvenance
  metrics: ForecastRegressionMetrics | null
  metricProvenance: MetricProvenance | null
  backtest: BacktestPoint[]
}

/**
 * The exact payload `POST /api/optimization/from-forecast` accepts today.
 *
 * Mirrors `OptimizationHandoffPayload` in `src/services/optimization.service.ts`.
 * Every key here is understood by the running code with no change required.
 */
export interface ExistingOptimizationPayload {
  forecast_id: string
  risk_score?: number
  priority?: 'low' | 'medium' | 'high' | 'critical'
  /**
   * Sent as an explicit `false`. The running service reads
   * `payload.candidate_locations_available ?? true`, so omitting it would make
   * the platform record that candidate locations exist. They do not: no
   * authoritative candidate set exists in this repository.
   */
  candidate_locations_available?: boolean
  /** Same reasoning as `candidate_locations_available`. */
  resource_constraints_available?: boolean
}

/**
 * The full proposed handoff. **Only the `ExistingOptimizationPayload` subset is
 * consumable today.** The remaining fields require the team-owner changes
 * enumerated in `TEAM_INTEGRATION_REQUIREMENTS.md`.
 */
export interface ProposedForecastHandoff {
  contract_version: string
  forecast_id: string
  forecast_timestamp: string
  forecast_horizon: string
  target: ForecastTarget
  target_units: string | null
  predicted_value: number
  predicted_water_level: number | null
  predicted_inflow: number | null
  flood_probability: number
  risk_level: RiskLevel
  risk_score: number
  threshold: number | null
  threshold_policy: ThresholdPolicy
  residual_sigma: number | null
  station_reference: string | null
  provenance_reference: string | null
  dataset_type: DatasetType
  status: PredictionStatus
  /** Always present, verbatim. */
  integration_statement: typeof INTEGRATION_STATEMENT
}

/** Forecast-risk attribution to one optimization candidate location. */
export interface CandidateRiskAttribution {
  candidateLocationId: string
  forecastId: string
  stationReference: string | null
  reachReference: string | null
  /** Risk score of the forecast as a whole. */
  forecastRiskScore: number
  /**
   * Risk attributed to this specific candidate. Null when it cannot be derived
   * — which is the current state, because no station→candidate geometry exists.
   */
  derivedFloodRisk: number | null
  mappingProvenance: string
  isSynthetic: boolean
  notes: string[]
}

/** The candidate-risk mapping spec, plus the reason it is currently synthetic. */
export interface CandidateRiskMappingSpec {
  forecastId: string
  synthetic: boolean
  source: string
  attributions: CandidateRiskAttribution[]
}

/** Re-exported so consumers need only one import. */
export type { ForecastContract, PredictionStatus, RiskLevel }
