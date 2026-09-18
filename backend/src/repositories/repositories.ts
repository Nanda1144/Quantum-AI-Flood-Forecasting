import type {
  Forecast,
  ModelComparisonRow,
  ModelInfo,
  ModelMetricsHistoryItem,
  ModelRegistryQuery,
  OptimizationReference,
  Paginated,
  PredictionQuery,
  ModelMetrics,
} from '../types/domain.ts'
import type { OptimizationJob } from '../types/optimization.ts'

/** Persistence seam. Postgres and in-memory (test) impls both satisfy it. */
export interface ForecastRepository {
  save(forecast: Forecast): Promise<Forecast>
  findByForecastId(forecastId: string): Promise<Forecast | null>
  getLatest(): Promise<Forecast | null>
  queryPredictions(query: PredictionQuery): Promise<Paginated<Forecast>>
  deleteAll(): Promise<void>
}

export interface ModelRepository {
  upsert(model: ModelInfo): Promise<ModelInfo>
  findById(modelId: string): Promise<ModelInfo | null>
  findActive(): Promise<ModelInfo | null>
  findAll(): Promise<ModelInfo[]>
  deleteAll(): Promise<void>
}

export interface OptimizationRepository {
  save(reference: OptimizationReference): Promise<OptimizationReference>
  findById(id: string): Promise<OptimizationReference | null>
  findByForecastId(forecastId: string): Promise<OptimizationReference | null>
  deleteAll(): Promise<void>
}

/**
 * Persisted optimization jobs (the orchestration pipeline's operational
 * record). Whole-row upsert keyed by job id; Postgres stores JSONB blobs.
 */
export interface OptimizationJobRepository {
  save(job: OptimizationJob): Promise<OptimizationJob>
  findById(id: string): Promise<OptimizationJob | null>
  deleteAll(): Promise<void>
}

/**
 * Model registry reads for the comparison page.
 *
 * Every listing/count reads `model_versions` joined to its most recent
 * `model_metrics` row; history reads all metric rows for one version.
 * Filtering/sorting/policy decisions that are pure logic run in the service
 * layer; row-scoped SQL (WHERE/pagination) runs here.
 */
export interface ModelComparisonRepository {
  /** Every registry version with its latest evaluation (comparison page). */
  listComparable(): Promise<ModelComparisonRow[]>
  /** Filtered + paginated registry listing (`GET /api/ai/models`). */
  listVersions(query: ModelRegistryQuery): Promise<Paginated<ModelComparisonRow>>
  /** Versions matching the given ids (server lookup for compare; order not guaranteed). */
  getVersionsByIds(ids: string[]): Promise<ModelComparisonRow[]>
  /** Full metadata row for one version, or null. */
  getVersionById(id: string): Promise<ModelComparisonRow | null>
  /** Historical evaluation runs for one version, newest first. */
  listMetricHistory(versionId: string): Promise<ModelMetricsHistoryItem[]>
}

export type { ModelMetrics }