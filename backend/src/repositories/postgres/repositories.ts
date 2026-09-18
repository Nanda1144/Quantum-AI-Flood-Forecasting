import type {
  Forecast,
  ModelComparisonRow,
  ModelInfo,
  ModelMetricsHistoryItem,
  ModelRegistryQuery,
  OptimizationReference,
  Paginated,
  PredictionQuery,
} from '../../types/domain.ts'
import type { OptimizationJob } from '../../types/optimization.ts'
import { getPool } from './pool.ts'
import type {
  ForecastRepository,
  ModelComparisonRepository,
  ModelRepository,
  OptimizationJobRepository,
  OptimizationRepository,
} from '../repositories.ts'

interface ForecastRow {
  forecast_id: string
  flood_probability: number
  risk_level: Forecast['riskLevel']
  predicted_water_level: number
  forecast_horizon: string
  model_id: string
  model_name: string
  model_version: string
  prediction_timestamp: string
  status: Forecast['status']
  created_at: string
}

function rowToForecast(row: ForecastRow): Forecast {
  return {
    forecastId: row.forecast_id,
    floodProbability: row.flood_probability,
    riskLevel: row.risk_level,
    predictedWaterLevel: row.predicted_water_level,
    forecastHorizon: row.forecast_horizon,
    modelId: row.model_id,
    modelName: row.model_name,
    modelVersion: row.model_version,
    predictionTimestamp: row.prediction_timestamp,
    status: row.status,
    priority: priorityForRisk(row.risk_level),
    createdAt: row.created_at,
  }
}

function priorityForRisk(risk: Forecast['riskLevel']): Forecast['priority'] {
  switch (risk) {
    case 'CRITICAL':
      return 'critical'
    case 'HIGH':
      return 'high'
    case 'MEDIUM':
      return 'medium'
    default:
      return 'low'
  }
}

export class PostgresForecastRepository implements ForecastRepository {
  async save(forecast: Forecast): Promise<Forecast> {
    await getPool().query(
      `INSERT INTO forecasts
         (forecast_id, flood_probability, risk_level, predicted_water_level, forecast_horizon,
          model_id, model_name, model_version, prediction_timestamp, status)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
       ON CONFLICT (forecast_id) DO UPDATE SET
         flood_probability = EXCLUDED.flood_probability,
         risk_level = EXCLUDED.risk_level,
         predicted_water_level = EXCLUDED.predicted_water_level,
         forecast_horizon = EXCLUDED.forecast_horizon,
         model_id = EXCLUDED.model_id,
         model_name = EXCLUDED.model_name,
         model_version = EXCLUDED.model_version,
         prediction_timestamp = EXCLUDED.prediction_timestamp,
         status = EXCLUDED.status`,
      [
        forecast.forecastId,
        forecast.floodProbability,
        forecast.riskLevel,
        forecast.predictedWaterLevel,
        forecast.forecastHorizon,
        forecast.modelId,
        forecast.modelName,
        forecast.modelVersion,
        forecast.predictionTimestamp,
        forecast.status,
      ],
    )
    return forecast
  }

  async findByForecastId(forecastId: string): Promise<Forecast | null> {
    const result = await getPool().query<ForecastRow>('SELECT * FROM forecasts WHERE forecast_id = $1', [forecastId])
    return result.rows[0] ? rowToForecast(result.rows[0]) : null
  }

  async getLatest(): Promise<Forecast | null> {
    const result = await getPool().query<ForecastRow>(
      'SELECT * FROM forecasts ORDER BY prediction_timestamp DESC LIMIT 1',
    )
    return result.rows[0] ? rowToForecast(result.rows[0]) : null
  }

  async queryPredictions(query: PredictionQuery): Promise<Paginated<Forecast>> {
    const conditions: string[] = []
    const params: unknown[] = []
    const next = (): number => params.length + 1

    if (query.risk) {
      conditions.push(`risk_level = $${next()}`)
      params.push(query.risk)
    }
    if (query.modelId) {
      conditions.push(`model_id = $${next()}`)
      params.push(query.modelId)
    }
    if (query.from) {
      conditions.push(`prediction_timestamp >= $${next()}`)
      params.push(query.from)
    }
    if (query.to) {
      conditions.push(`prediction_timestamp <= $${next()}`)
      params.push(query.to)
    }
    const where = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : ''

    const totalResult = await getPool().query<{ count: string }>(`SELECT count(*) AS count FROM forecasts ${where}`, params)
    const total = Number(totalResult.rows[0].count)

    const limit = query.limit
    const offset = (query.page - 1) * limit
    const result = await getPool().query<ForecastRow>(
      `SELECT * FROM forecasts ${where} ORDER BY prediction_timestamp DESC LIMIT $${next()} OFFSET $${next()}`,
      [...params, limit, offset],
    )

    return {
      items: result.rows.map(rowToForecast),
      page: query.page,
      limit,
      total,
      totalPages: Math.max(1, Math.ceil(total / limit)),
    }
  }

  async deleteAll(): Promise<void> {
    await getPool().query('DELETE FROM forecasts')
  }
}

export class PostgresModelRepository implements ModelRepository {
  async upsert(model: ModelInfo): Promise<ModelInfo> {
    const { metrics } = model
    await getPool().query(
      `INSERT INTO models
         (model_id, name, version, algorithm, status, last_trained_at, last_evaluated_at,
          rmse, mae, nse, accuracy)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
       ON CONFLICT (model_id) DO UPDATE SET
         name = EXCLUDED.name, version = EXCLUDED.version, algorithm = EXCLUDED.algorithm,
         status = EXCLUDED.status, last_trained_at = EXCLUDED.last_trained_at,
         last_evaluated_at = EXCLUDED.last_evaluated_at, rmse = EXCLUDED.rmse,
         mae = EXCLUDED.mae, nse = EXCLUDED.nse, accuracy = EXCLUDED.accuracy,
         updated_at = now()`,
      [
        model.model_id,
        model.name,
        model.version,
        model.algorithm,
        model.status,
        model.last_trained_at,
        model.last_evaluated_at,
        metrics.rmse ?? null,
        metrics.mae ?? null,
        metrics.nse ?? null,
        metrics.accuracy ?? null,
      ],
    )
    return model
  }

  async findById(modelId: string): Promise<ModelInfo | null> {
    const result = await getPool().query<ModelInfoRow>('SELECT * FROM models WHERE model_id = $1', [modelId])
    return result.rows[0] ? rowToModel(result.rows[0]) : null
  }

  async findActive(): Promise<ModelInfo | null> {
    const result = await getPool().query<ModelInfoRow>('SELECT * FROM models ORDER BY version DESC LIMIT 1')
    return result.rows[0] ? rowToModel(result.rows[0]) : null
  }

  async findAll(): Promise<ModelInfo[]> {
    const result = await getPool().query<ModelInfoRow>('SELECT * FROM models ORDER BY model_id')
    return result.rows.map(rowToModel)
  }

  async deleteAll(): Promise<void> {
    await getPool().query('DELETE FROM models')
  }
}

interface ModelInfoRow {
  model_id: string
  name: string
  version: string
  algorithm: string
  status: ModelInfo['status']
  last_trained_at: string
  last_evaluated_at: string
  rmse: number | null
  mae: number | null
  nse: number | null
  accuracy: number | null
}

function rowToModel(row: ModelInfoRow): ModelInfo {
  return {
    model_id: row.model_id,
    name: row.name,
    version: row.version,
    algorithm: row.algorithm,
    status: row.status,
    last_trained_at: row.last_trained_at,
    last_evaluated_at: row.last_evaluated_at,
    metrics: {
      ...(row.rmse !== null && { rmse: row.rmse }),
      ...(row.mae !== null && { mae: row.mae }),
      ...(row.nse !== null && { nse: row.nse }),
      ...(row.accuracy !== null && { accuracy: row.accuracy }),
    },
  }
}

/** Same shape as the JSON contract table of the db index file. */
export class PostgresOptimizationRepository implements OptimizationRepository {
  async save(reference: OptimizationReference): Promise<OptimizationReference> {
    await getPool().query(
      `INSERT INTO optimization_references
         (id, forecast_id, risk_score, priority, candidate_locations_available,
          resource_constraints_available, ready)
       VALUES ($1,$2,$3,$4,$5,$6,$7)
       ON CONFLICT (forecast_id) DO UPDATE SET
         risk_score = EXCLUDED.risk_score, priority = EXCLUDED.priority,
         candidate_locations_available = EXCLUDED.candidate_locations_available,
         resource_constraints_available = EXCLUDED.resource_constraints_available,
         ready = EXCLUDED.ready`,
      [
        reference.id,
        reference.forecastId,
        reference.riskScore,
        reference.priority,
        reference.candidateLocationsAvailable,
        reference.resourceConstraintsAvailable,
        reference.ready,
      ],
    )
    return reference
  }

  async findById(id: string): Promise<OptimizationReference | null> {
    const result = await getPool().query<OptimizationRow>('SELECT * FROM optimization_references WHERE id = $1', [id])
    return result.rows[0] ? rowToOptimization(result.rows[0]) : null
  }

  async findByForecastId(forecastId: string): Promise<OptimizationReference | null> {
    const result = await getPool().query<OptimizationRow>(
      'SELECT * FROM optimization_references WHERE forecast_id = $1',
      [forecastId],
    )
    return result.rows[0] ? rowToOptimization(result.rows[0]) : null
  }

  async deleteAll(): Promise<void> {
    await getPool().query('DELETE FROM optimization_references')
  }
}

interface OptimizationRow {
  id: string
  forecast_id: string
  risk_score: number
  priority: OptimizationReference['priority']
  candidate_locations_available: boolean
  resource_constraints_available: boolean
  ready: boolean
  created_at: string
}

function rowToOptimization(row: OptimizationRow): OptimizationReference {
  return {
    id: row.id,
    forecastId: row.forecast_id,
    riskScore: row.risk_score,
    priority: row.priority,
    candidateLocationsAvailable: row.candidate_locations_available,
    resourceConstraintsAvailable: row.resource_constraints_available,
    ready: row.ready,
    createdAt: row.created_at,
  }
}

interface ComparisonRow {
  id: string
  model_name: string
  algorithm: string
  version: string
  status: ModelComparisonRow['status']
  dataset_reference: string
  model_artifact_reference: string
  rmse: number | null
  mae: number | null
  r2: number | null
  nse: number | null
  accuracy: number | null
  precision: number | null
  recall: number | null
  f1: number | null
  training_time_ms: string | null
  inference_time_ms: string | null
  evaluated_at: Date | null
  evaluation_dataset: string | null
  training_started_at: Date | null
  training_completed_at: Date | null
  deployed_at: Date | null
  created_at: Date | null
  updated_at: Date | null
}

/** Registry version rows joined to the version's most recent metric run. */
const VERSION_WITH_LATEST_METRICS_SQL = `
  SELECT v.id, v.model_name, v.algorithm, v.version, v.status,
         v.dataset_reference, v.model_artifact_reference,
         m.rmse, m.mae, m.r2, m.nse, m.accuracy, m.precision, m.recall, m.f1,
         m.training_time_ms, m.inference_time_ms, m.evaluated_at, m.evaluation_dataset,
         v.training_started_at, v.training_completed_at, v.deployed_at,
         v.created_at, v.updated_at
  FROM model_versions v
  LEFT JOIN LATERAL (
    SELECT rmse, mae, r2, nse, accuracy, precision, recall, f1,
           training_time_ms, inference_time_ms, evaluated_at, evaluation_dataset
    FROM model_metrics mm
    WHERE mm.model_version_id = v.id
    ORDER BY mm.evaluated_at DESC
    LIMIT 1
  ) m ON true`

function asNumber(value: string | number | null): number | undefined {
  return value === null ? undefined : Number(value)
}

function rowToComparison(row: ComparisonRow): ModelComparisonRow {
  const metrics = {
    ...(row.rmse !== null && { rmse: row.rmse }),
    ...(row.mae !== null && { mae: row.mae }),
    ...(row.r2 !== null && { r2: row.r2 }),
    ...(row.nse !== null && { nse: row.nse }),
    ...(row.accuracy !== null && { accuracy: row.accuracy }),
    ...(row.precision !== null && { precision: row.precision }),
    ...(row.recall !== null && { recall: row.recall }),
    ...(row.f1 !== null && { f1: row.f1 }),
  }
  const trainingTimeMs = asNumber(row.training_time_ms)
  const inferenceTimeMs = asNumber(row.inference_time_ms)
  return {
    modelId: row.id,
    name: row.model_name,
    version: row.version,
    algorithm: row.algorithm,
    status: row.status,
    dataset: row.dataset_reference,
    artifactReference: row.model_artifact_reference,
    metrics,
    ...(trainingTimeMs !== undefined && { trainingTimeMs }),
    ...(inferenceTimeMs !== undefined && { inferenceTimeMs }),
    evaluatedAt: row.evaluated_at ? row.evaluated_at.toISOString() : '',
    evaluationDataset: row.evaluation_dataset ?? '',
    trainingStartedAt: row.training_started_at ? row.training_started_at.toISOString() : null,
    trainingCompletedAt: row.training_completed_at ? row.training_completed_at.toISOString() : null,
    deployedAt: row.deployed_at ? row.deployed_at.toISOString() : null,
    createdAt: row.created_at ? row.created_at.toISOString() : undefined,
    updatedAt: row.updated_at ? row.updated_at.toISOString() : undefined,
  }
}

export class PostgresModelComparisonRepository implements ModelComparisonRepository {
  async listComparable(): Promise<ModelComparisonRow[]> {
    const result = await getPool().query<ComparisonRow>(
      `${VERSION_WITH_LATEST_METRICS_SQL}
       ORDER BY v.model_name ASC, v.version ASC`,
    )
    return result.rows.map(rowToComparison)
  }

  async listVersions(query: ModelRegistryQuery): Promise<Paginated<ModelComparisonRow>> {
    const conditions: string[] = []
    const params: unknown[] = []
    const next = (): number => params.length + 1

    if (query.status) {
      conditions.push(`v.status = $${next()}`)
      params.push(query.status)
    }
    if (query.algorithm) {
      conditions.push(`v.algorithm ILIKE $${next()}`)
      params.push(`%${query.algorithm}%`)
    }
    if (query.dataset) {
      conditions.push(`v.dataset_reference ILIKE $${next()}`)
      params.push(`%${query.dataset}%`)
    }
    const where = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : ''

    const totalResult = await getPool().query<{ count: string }>(
      `SELECT count(*) AS count FROM model_versions v ${where}`,
      params,
    )
    const total = Number(totalResult.rows[0].count)

    const result = await getPool().query<ComparisonRow>(
      `${VERSION_WITH_LATEST_METRICS_SQL}
       ${where}
       ORDER BY v.model_name ASC, v.version ASC
       LIMIT $${next()} OFFSET $${next()}`,
      [...params, query.limit, (query.page - 1) * query.limit],
    )

    return {
      items: result.rows.map(rowToComparison),
      page: query.page,
      limit: query.limit,
      total,
      totalPages: Math.max(1, Math.ceil(total / query.limit)),
    }
  }

  async getVersionsByIds(ids: string[]): Promise<ModelComparisonRow[]> {
    if (ids.length === 0) return []
    const result = await getPool().query<ComparisonRow>(
      `${VERSION_WITH_LATEST_METRICS_SQL}
       WHERE v.id::text = ANY($1::text[])`,
      [ids],
    )
    return result.rows.map(rowToComparison)
  }

  async getVersionById(id: string): Promise<ModelComparisonRow | null> {
    const result = await getPool().query<ComparisonRow>(
      `${VERSION_WITH_LATEST_METRICS_SQL}
       WHERE v.id = $1::bigint`,
      [id],
    )
    return result.rows[0] ? rowToComparison(result.rows[0]) : null
  }

  async listMetricHistory(versionId: string): Promise<ModelMetricsHistoryItem[]> {
    const result = await getPool().query<MetricsHistoryRow>(
      `SELECT rmse, mae, r2, nse, accuracy, precision, recall, f1,
              training_time_ms, inference_time_ms, evaluation_dataset, evaluated_at
       FROM model_metrics
       WHERE model_version_id = $1
       ORDER BY evaluated_at DESC`,
      [versionId],
    )
    return result.rows.map(rowToMetricsHistory)
  }
}

interface MetricsHistoryRow {
  rmse: number | null
  mae: number | null
  r2: number | null
  nse: number | null
  accuracy: number | null
  precision: number | null
  recall: number | null
  f1: number | null
  training_time_ms: string | null
  inference_time_ms: string | null
  evaluation_dataset: string
  evaluated_at: Date
}

function rowToMetricsHistory(row: MetricsHistoryRow): ModelMetricsHistoryItem {
  return {
    metrics: {
      ...(row.rmse !== null && { rmse: row.rmse }),
      ...(row.mae !== null && { mae: row.mae }),
      ...(row.r2 !== null && { r2: row.r2 }),
      ...(row.nse !== null && { nse: row.nse }),
      ...(row.accuracy !== null && { accuracy: row.accuracy }),
      ...(row.precision !== null && { precision: row.precision }),
      ...(row.recall !== null && { recall: row.recall }),
      ...(row.f1 !== null && { f1: row.f1 }),
    },
    ...(asNumber(row.training_time_ms) !== undefined && { trainingTimeMs: asNumber(row.training_time_ms)! }),
    ...(asNumber(row.inference_time_ms) !== undefined && { inferenceTimeMs: asNumber(row.inference_time_ms)! }),
    evaluationDataset: row.evaluation_dataset,
    evaluatedAt: row.evaluated_at.toISOString(),
  }
}

/**
 * Persisted optimization jobs. The heavy payloads (request, QUBO, result,
 * pipeline steps, classical benchmark) are stored as JSONB; scalar summary
 * columns mirror the `GET /api/optimization/:id` contract.
 */
export class PostgresOptimizationJobRepository implements OptimizationJobRepository {
  async save(job: OptimizationJob): Promise<OptimizationJob> {
    await getPool().query(
      `INSERT INTO optimization_jobs (
         id, owner, status, problem_type, request, fallback_policy, algorithm,
         execution_mode, execution_mode_used, backend, backend_used,
         fallback_applied, fallback_reason, qubit_count, steps, qubo, classical,
         result, validation_status, validation_summary, error,
         created_at, started_at, completed_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24)
       ON CONFLICT (id) DO UPDATE SET
         status = EXCLUDED.status, problem_type = EXCLUDED.problem_type,
         request = EXCLUDED.request, fallback_policy = EXCLUDED.fallback_policy,
         algorithm = EXCLUDED.algorithm, execution_mode = EXCLUDED.execution_mode,
         execution_mode_used = EXCLUDED.execution_mode_used,
         backend = EXCLUDED.backend, backend_used = EXCLUDED.backend_used,
         fallback_applied = EXCLUDED.fallback_applied,
         fallback_reason = EXCLUDED.fallback_reason,
         qubit_count = EXCLUDED.qubit_count, steps = EXCLUDED.steps,
         qubo = EXCLUDED.qubo, classical = EXCLUDED.classical,
         result = EXCLUDED.result, validation_status = EXCLUDED.validation_status,
         validation_summary = EXCLUDED.validation_summary, error = EXCLUDED.error,
         started_at = EXCLUDED.started_at, completed_at = EXCLUDED.completed_at`,
      [
        job.id,
        job.owner,
        job.status,
        job.problemType,
        JSON.stringify(job.request),
        job.fallbackPolicy,
        job.algorithm,
        job.executionMode,
        job.executionModeUsed,
        job.backend,
        job.backendUsed,
        job.fallbackApplied,
        job.fallbackReason,
        job.qubitCount,
        JSON.stringify(job.steps),
        job.qubo !== null ? JSON.stringify(job.qubo) : null,
        job.classical !== null ? JSON.stringify(job.classical) : null,
        job.result !== null ? JSON.stringify(job.result) : null,
        job.validationStatus,
        job.validationSummary,
        job.error !== null ? JSON.stringify(job.error) : null,
        job.createdAt,
        job.startedAt,
        job.completedAt,
      ],
    )
    return job
  }

  async findById(id: string): Promise<OptimizationJob | null> {
    const result = await getPool().query<OptimizationJobRow>('SELECT * FROM optimization_jobs WHERE id = $1', [id])
    return result.rows[0] ? rowToOptimizationJob(result.rows[0]) : null
  }

  async deleteAll(): Promise<void> {
    await getPool().query('DELETE FROM optimization_jobs')
  }
}

interface OptimizationJobRow {
  id: string
  owner: string
  status: OptimizationJob['status']
  problem_type: OptimizationJob['problemType']
  request: OptimizationJob['request']
  fallback_policy: OptimizationJob['fallbackPolicy']
  algorithm: string
  execution_mode: OptimizationJob['executionMode']
  execution_mode_used: OptimizationJob['executionModeUsed']
  backend: OptimizationJob['backend']
  backend_used: OptimizationJob['backendUsed']
  fallback_applied: boolean
  fallback_reason: string | null
  qubit_count: number | null
  steps: OptimizationJob['steps']
  qubo: OptimizationJob['qubo']
  classical: OptimizationJob['classical']
  result: OptimizationJob['result']
  validation_status: OptimizationJob['validationStatus']
  validation_summary: string | null
  error: OptimizationJob['error']
  created_at: string
  started_at: string | null
  completed_at: string | null
}

function rowToOptimizationJob(row: OptimizationJobRow): OptimizationJob {
  return {
    id: row.id,
    owner: row.owner,
    status: row.status,
    problemType: row.problem_type,
    request: row.request,
    fallbackPolicy: row.fallback_policy,
    algorithm: row.algorithm,
    executionMode: row.execution_mode,
    executionModeUsed: row.execution_mode_used,
    backend: row.backend,
    backendUsed: row.backend_used,
    fallbackApplied: row.fallback_applied,
    fallbackReason: row.fallback_reason,
    qubitCount: row.qubit_count,
    steps: row.steps,
    qubo: row.qubo,
    classical: row.classical,
    result: row.result,
    validationStatus: row.validation_status,
    validationSummary: row.validation_summary,
    error: row.error,
    createdAt: row.created_at,
    startedAt: row.started_at,
    completedAt: row.completed_at,
  }
}