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
import type { OptimizationJob as OptimizationJobRecord } from '../../types/optimization.ts'
import type {
  ForecastRepository,
  ModelComparisonRepository,
  ModelRepository,
  OptimizationJobRepository,
  OptimizationRepository,
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

  async save(job: OptimizationJobRecord): Promise<OptimizationJobRecord> {
    this.rows.set(job.id, structuredClone(job))
    return job
  }

  async findById(id: string): Promise<OptimizationJobRecord | null> {
    const row = this.rows.get(id)
    return row ? structuredClone(row) : null
  }

  async deleteAll(): Promise<void> {
    this.rows.clear()
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