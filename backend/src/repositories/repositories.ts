/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

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
import type {
  OptimizationJob,
  OptimizationJobAuditEntry,
  OptimizationResultRecord,
  QuboBuild,
  QuboMetadata,
  QuantumJobRecord,
  QuantumResultRecord,
} from '../types/optimization.ts'

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
 *
 * Completed research results are write-once: `deleteJob` only ever soft-deletes
 * (sets deleted_at/deleted_by/delete_reason and writes an audit trail). The
 * database rejects hard DELETEs of completed jobs/results unless the
 * administrative escape hatch is set (see migration 004).
 */
export interface OptimizationJobRepository {
  save(job: OptimizationJob): Promise<OptimizationJob>
  findById(id: string): Promise<OptimizationJob | null>
  /**
   * Every non-deleted job, newest first. The experiment ledger the benchmark
   * page renders; soft-deleted rows (deleted_at set) are excluded. Stops at
   * `limit` rows so the listing stays bounded.
   */
  list(limit?: number): Promise<OptimizationJob[]>
  /**
   * Read the full QUBO build for a job. Inline rows carry `job.qubo`; artifact
   * rows keep the build in the artifact store referenced by the job. Never the
   * result document's QuboDocument — this returns the complete stored build
   * (`linear`, `quadratic`, `penaltyScale`) so the visualization endpoint can
   * serve it wholesale without re-calculating anything.
   */
  findQuboBuild(jobId: string): Promise<QuboBuild | null>
  /** Persist the normalized result row for a completed job (one per job). */
  saveResult(result: OptimizationResultRecord): Promise<OptimizationResultRecord>
  /** Read the normalized result row for a job, or null when none exists. */
  findResult(jobId: string): Promise<OptimizationResultRecord | null>
  /**
   * Persist the QUBO metadata audit record for a job (migration 005, one row
   * per job). Small problems inline the plain-JSON representation; large ones
   * are recorded by reference + checksum only — never the matrix cells.
   */
  saveQuboMetadata(metadata: QuboMetadata): Promise<QuboMetadata>
  /** Read the QUBO metadata audit record for a job, or null when none exists. */
  findQuboMetadata(jobId: string): Promise<QuboMetadata | null>
  /** Authorized soft-delete: records the audit trail, never hard-deletes. */
  deleteJob(jobId: string, actor: string, reason: string): Promise<OptimizationJob>
  /**
   * Append one write-once audit entry for a job (delete-protection events and
   * sensitive result actions — e.g. result access/export). Never updates or
   * removes an existing entry.
   */
  appendAudit(entry: {
    optimizationJobId: string
    action: string
    actor: string
    reason: string | null
  }): Promise<OptimizationJobAuditEntry>
  /** Write-once audit trail for a job (delete-protection events). */
  listAudit(jobId: string): Promise<OptimizationJobAuditEntry[]>
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

/**
 * Persisted quantum submissions (`quantum_jobs` / `quantum_results`, migration
 * 006). One row per REAL quantum-service job; each submission — including every
 * failed attempt on a fallback ladder — gets its own honest row so the
 * simulator/hardware distinction is preserved. Only configuration scalars,
 * plain-JSON counts and artifact references are stored: never credentials,
 * never raw circuit objects.
 */
export interface QuantumJobRepository {
  /** Upsert a quantum submission lifecycle row (id is the service's job id). */
  saveJob(job: QuantumJobRecord): Promise<QuantumJobRecord>
  /** Read one submission by its quantum job id. */
  findJobById(id: string): Promise<QuantumJobRecord | null>
  /** Every submission for one pipeline job, oldest first. */
  findJobsByOptimizationJobId(optimizationJobId: string): Promise<QuantumJobRecord[]>
  /** Persist the normalized result row for a completed quantum job (one per job). */
  saveResult(result: QuantumResultRecord): Promise<QuantumResultRecord>
  /** Read the normalized result row for a quantum job, or null when none exists. */
  findResult(quantumJobId: string): Promise<QuantumResultRecord | null>
  deleteAll(): Promise<void>
}

export type { ModelMetrics }