/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * In-memory repository implementations.
 *
 * Used by unit/integration tests and by the local demo runtime when the
 * database is unavailable (DATABASE_URL unreachable), so the API stays
 * testable without a running PostgreSQL instance.
 */

import { randomUUID } from 'node:crypto'
import type {
  Forecast,
  ModelComparisonRow,
  ModelMetricsHistoryItem,
  ModelRegistryQuery,
  OptimizationReference,
  Paginated,
  PredictionQuery,
  ModelInfo,
} from '../../types/domain.ts'
import type {
  OptimizationJob as OptimizationJobRecord,
  OptimizationJobAuditEntry,
  OptimizationResultRecord,
  QuboBuild,
  QuboMetadata,
  QuantumJobRecord,
  QuantumResultRecord,
} from '../../types/optimization.ts'
import { AppError, ErrorCodes } from '../../envelope.ts'
import { deriveQuboMetadata } from '../../lib/optimization/qubo-metadata.ts'
import type {
  ForecastRepository,
  ModelComparisonRepository,
  ModelRepository,
  OptimizationJobRepository,
  OptimizationRepository,
  QuantumJobRepository,
} from '../repositories.ts'

export class MemoryForecastRepository implements ForecastRepository {
  private rows = new Map<string, Forecast>()

  async save(forecast: Forecast): Promise<Forecast> {
    this.rows.set(forecast.forecastId, forecast)
    return forecast
  }

  async findByForecastId(forecastId: string): Promise<Forecast | null> {
    return this.rows.get(forecastId) ?? null
  }

  async getLatest(): Promise<Forecast | null> {
    const sorted = [...this.rows.values()].sort((a, b) => b.predictionTimestamp.localeCompare(a.predictionTimestamp))
    return sorted[0] ?? null
  }

  async queryPredictions(query: PredictionQuery): Promise<Paginated<Forecast>> {
    let items = [...this.rows.values()].sort((a, b) => b.predictionTimestamp.localeCompare(a.predictionTimestamp))
    if (query.risk) items = items.filter((f) => f.riskLevel === query.risk)
    if (query.modelId) items = items.filter((f) => f.modelId === query.modelId)
    if (query.from) items = items.filter((f) => f.predictionTimestamp >= query.from!)
    if (query.to) items = items.filter((f) => f.predictionTimestamp <= query.to!)
    const total = items.length
    const start = (query.page - 1) * query.limit
    return {
      items: items.slice(start, start + query.limit),
      page: query.page,
      limit: query.limit,
      total,
      totalPages: Math.max(1, Math.ceil(total / query.limit)),
    }
  }

  async deleteAll(): Promise<void> {
    this.rows.clear()
  }
}

export class MemoryModelRepository implements ModelRepository {
  private rows = new Map<string, ModelInfo>()

  async upsert(model: ModelInfo): Promise<ModelInfo> {
    this.rows.set(model.model_id, model)
    return model
  }

  async findById(modelId: string): Promise<ModelInfo | null> {
    return this.rows.get(modelId) ?? null
  }

  async findActive(): Promise<ModelInfo | null> {
    // First inserted model is treated as the active one.
    return this.rows.values().next().value ?? null
  }

  async findAll(): Promise<ModelInfo[]> {
    return [...this.rows.values()]
  }

  async deleteAll(): Promise<void> {
    this.rows.clear()
  }
}

export class MemoryOptimizationJobRepository implements OptimizationJobRepository {
  private rows = new Map<string, OptimizationJobRecord>()
  private results = new Map<string, OptimizationResultRecord>()
  private audits = new Map<string, OptimizationJobAuditEntry[]>()
  private artifacts = new Map<string, { reference: string; qubo: NonNullable<OptimizationJobRecord['qubo']> }>()
  private metadata = new Map<string, QuboMetadata>()
  private auditSeq = 1

  async save(job: OptimizationJobRecord): Promise<OptimizationJobRecord> {
    const stored = structuredClone(job)
    // Mirror Postgres: large QUBOs are held by reference, not inline.
    if (stored.quboStorage === 'artifact' && stored.qubo !== null && stored.quboArtifactReference) {
      this.artifacts.set(stored.id, { reference: stored.quboArtifactReference, qubo: stored.qubo })
      stored.qubo = null
    }
    // QUBO metadata audit record (migration 005) — derived, never raw objects.
    if (job.qubo !== null) {
      this.saveQuboMetadata(deriveQuboMetadata(job))
    }
    this.rows.set(stored.id, stored)
    return job
  }

  async findById(id: string): Promise<OptimizationJobRecord | null> {
    const row = this.rows.get(id)
    return row ? structuredClone(row) : null
  }

  async list(limit = 200): Promise<OptimizationJobRecord[]> {
    const rows = [...this.rows.values()]
      .filter((row) => row.deletedAt === null)
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
      .slice(0, limit)
    return rows.map((row) => structuredClone(row))
  }

  async findQuboBuild(jobId: string): Promise<QuboBuild | null> {
    const row = this.rows.get(jobId)
    if (row?.qubo) return structuredClone(row.qubo)
    const artifact = this.artifacts.get(jobId)
    return artifact ? structuredClone(artifact.qubo) : null
  }

  async saveResult(result: OptimizationResultRecord): Promise<OptimizationResultRecord> {
    // Mirror Postgres (migration 007): the classical benchmark reference snapshot
    // is WRITE-ONCE — a re-save never overwrites a previously stored snapshot.
    const existing = this.results.get(result.optimizationJobId)
    const stored: OptimizationResultRecord = existing
      ? {
          ...result,
          classicalSolver: existing.classicalSolver ?? result.classicalSolver,
          classicalRuntimeMs: existing.classicalRuntimeMs ?? result.classicalRuntimeMs,
          approximationRatio: existing.approximationRatio ?? result.approximationRatio,
          approximationBasis: existing.approximationBasis ?? result.approximationBasis,
          approximationInvalidReason: existing.approximationInvalidReason ?? result.approximationInvalidReason,
          randomSeed: existing.randomSeed ?? result.randomSeed,
          validationTimestamp: existing.validationTimestamp ?? result.validationTimestamp,
          validationDetails: existing.validationDetails ?? result.validationDetails,
          explanationMetadata: existing.explanationMetadata ?? result.explanationMetadata,
        }
      : result
    this.results.set(result.optimizationJobId, structuredClone(stored))
    return result
  }

  async findResult(jobId: string): Promise<OptimizationResultRecord | null> {
    const result = this.results.get(jobId)
    return result ? structuredClone(result) : null
  }

  async saveQuboMetadata(metadata: QuboMetadata): Promise<QuboMetadata> {
    this.metadata.set(metadata.optimizationJobId, structuredClone(metadata))
    return metadata
  }

  async findQuboMetadata(jobId: string): Promise<QuboMetadata | null> {
    const metadata = this.metadata.get(jobId)
    return metadata ? structuredClone(metadata) : null
  }

  async deleteJob(jobId: string, actor: string, reason: string): Promise<OptimizationJobRecord> {
    const row = this.rows.get(jobId)
    if (!row) throw new AppError(404, ErrorCodes.JOB_NOT_FOUND, `Optimization job '${jobId}' not found`)
    const next = structuredClone(row)
    next.deletedAt = new Date().toISOString()
    next.deletedBy = actor
    next.deleteReason = reason
    this.rows.set(jobId, next)
    this.audits.set(jobId, [
      ...(this.audits.get(jobId) ?? []),
      {
        id: this.auditSeq++,
        optimizationJobId: jobId,
        action: 'soft_deleted',
        actor,
        reason,
        createdAt: next.deletedAt,
      },
    ])
    return next
  }

  async appendAudit(entry: {
    optimizationJobId: string
    action: string
    actor: string
    reason: string | null
  }): Promise<OptimizationJobAuditEntry> {
    const stored: OptimizationJobAuditEntry = {
      id: this.auditSeq++,
      optimizationJobId: entry.optimizationJobId,
      action: entry.action,
      actor: entry.actor,
      reason: entry.reason,
      createdAt: new Date().toISOString(),
    }
    this.audits.set(entry.optimizationJobId, [...(this.audits.get(entry.optimizationJobId) ?? []), stored])
    return structuredClone(stored)
  }

  async listAudit(jobId: string): Promise<OptimizationJobAuditEntry[]> {
    return (this.audits.get(jobId) ?? []).map((entry) => structuredClone(entry))
  }

  async deleteAll(): Promise<void> {
    this.rows.clear()
    this.results.clear()
    this.audits.clear()
    this.artifacts.clear()
    this.metadata.clear()
  }
}

export class MemoryModelComparisonRepository implements ModelComparisonRepository {
  private rows: ModelComparisonRow[]
  private history: Map<string, ModelMetricsHistoryItem[]>

  constructor(
    rows: ModelComparisonRow[] = [],
    history: Map<string, ModelMetricsHistoryItem[]> = new Map(),
  ) {
    this.rows = rows
    this.history = history
  }

  async listComparable(): Promise<ModelComparisonRow[]> {
    return [...this.rows]
  }

  async listVersions(query: ModelRegistryQuery): Promise<Paginated<ModelComparisonRow>> {
    let items = [...this.rows]
    if (query.status) items = items.filter((row) => row.status === query.status)
    if (query.algorithm) {
      const needle = query.algorithm.toLowerCase()
      items = items.filter((row) => row.algorithm.toLowerCase().includes(needle))
    }
    if (query.dataset) {
      const needle = query.dataset.toLowerCase()
      items = items.filter((row) => row.dataset.toLowerCase().includes(needle))
    }
    items.sort((a, b) => a.name.localeCompare(b.name) || a.version.localeCompare(b.version))
    const total = items.length
    const start = (query.page - 1) * query.limit
    return {
      items: items.slice(start, start + query.limit),
      page: query.page,
      limit: query.limit,
      total,
      totalPages: Math.max(1, Math.ceil(total / query.limit)),
    }
  }

  async getVersionsByIds(ids: string[]): Promise<ModelComparisonRow[]> {
    const wanted = new Set(ids)
    return this.rows.filter((row) => wanted.has(row.modelId))
  }

  async getVersionById(id: string): Promise<ModelComparisonRow | null> {
    return this.rows.find((row) => row.modelId === id) ?? null
  }

  async listMetricHistory(versionId: string): Promise<ModelMetricsHistoryItem[]> {
    const history = this.history.get(versionId) ?? []
    return [...history].sort((a, b) => b.evaluatedAt.localeCompare(a.evaluatedAt))
  }
}

/**
 * In-memory quantum job persistence (migration 006).
 *
 * Mirrors Postgres: a result row may only be stored for a job that exists
 * (FK-like guard), and one result row per job is enforced by keying on the
 * `<quantumJobId>-R1` id.
 */
export class MemoryQuantumJobRepository implements QuantumJobRepository {
  private jobs = new Map<string, QuantumJobRecord>()
  private results = new Map<string, QuantumResultRecord>()

  async saveJob(job: QuantumJobRecord): Promise<QuantumJobRecord> {
    const stored = structuredClone(job)
    const existing = this.jobs.get(stored.id)
    if (existing) {
      // Lifecycle transitions update the mutable fields; identity timestamps
      // (submitted_at / created_at) are preserved from the original row.
      stored.submittedAt = existing.submittedAt
      stored.createdAt = existing.createdAt
    }
    this.jobs.set(stored.id, stored)
    return job
  }

  async findJobById(id: string): Promise<QuantumJobRecord | null> {
    const row = this.jobs.get(id)
    return row ? structuredClone(row) : null
  }

  async findJobsByOptimizationJobId(optimizationJobId: string): Promise<QuantumJobRecord[]> {
    return [...this.jobs.values()]
      .filter((row) => row.optimizationJobId === optimizationJobId)
      .sort((a, b) => a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id))
      .map((row) => structuredClone(row))
  }

  async saveResult(result: QuantumResultRecord): Promise<QuantumResultRecord> {
    if (!this.jobs.has(result.quantumJobId)) {
      throw new AppError(500, ErrorCodes.INTERNAL_ERROR, `Cannot persist a result for unknown quantum job '${result.quantumJobId}'`)
    }
    if (result.id !== `${result.quantumJobId}-R1`) {
      throw new AppError(500, ErrorCodes.INTERNAL_ERROR, `Quantum result id '${result.id}' does not match '<quantumJobId>-R1'`)
    }
    this.results.set(result.id, structuredClone(result))
    return result
  }

  async findResult(quantumJobId: string): Promise<QuantumResultRecord | null> {
    const row = this.results.get(`${quantumJobId}-R1`)
    return row ? structuredClone(row) : null
  }

  async deleteAll(): Promise<void> {
    this.jobs.clear()
    this.results.clear()
  }
}

export class MemoryOptimizationRepository implements OptimizationRepository {
  private rows = new Map<string, OptimizationReference>()

  async save(reference: OptimizationReference): Promise<OptimizationReference> {
    if (!reference.id) reference.id = randomUUID()
    this.rows.set(reference.forecastId, reference)
    return reference
  }

  async findById(id: string): Promise<OptimizationReference | null> {
    return [...this.rows.values()].find((r) => r.id === id) ?? null
  }

  async findByForecastId(forecastId: string): Promise<OptimizationReference | null> {
    return this.rows.get(forecastId) ?? null
  }

  async deleteAll(): Promise<void> {
    this.rows.clear()
  }
}