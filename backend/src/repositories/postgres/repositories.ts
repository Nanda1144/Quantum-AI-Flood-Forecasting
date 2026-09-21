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
} from '../../types/domain.ts'
import type {
  OptimizationJob,
  OptimizationJobAuditEntry,
  OptimizationResultRecord,
  QuboBuild,
  QuboMetadata,
  QuantumJobRecord,
  QuantumResultRecord,
} from '../../types/optimization.ts'
import { AppError, ErrorCodes } from '../../envelope.ts'
import { getPool } from './pool.ts'
import { deriveQuboMetadata } from '../../lib/optimization/qubo-metadata.ts'
import type {
  ForecastRepository,
  ModelComparisonRepository,
  ModelRepository,
  OptimizationJobRepository,
  OptimizationRepository,
  QuantumJobRepository,
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

    const limitIndex = params.length + 1
    const offsetIndex = params.length + 2
    const result = await getPool().query<ComparisonRow>(
      `${VERSION_WITH_LATEST_METRICS_SQL}
       ${where}
       ORDER BY v.model_name ASC, v.version ASC
       LIMIT $${limitIndex} OFFSET $${offsetIndex}`,
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
    const artifact = job.quboStorage === 'artifact'
    const quboReference = artifact ? (job.quboArtifactReference ?? `qflare://qubo/${job.id}`) : null
    // Large QUBOs travel by reference: the row keeps a pointer, the full plain
    // JSON matrix lives in the artifact store (never Qiskit objects inline).
    await getPool().query(
      `INSERT INTO optimization_jobs (
         id, owner, status, problem_type, request, fallback_policy, algorithm,
         execution_mode, execution_mode_used, backend, backend_used,
         fallback_applied, fallback_reason, qubit_count, steps, qubo, classical,
         result, validation_status, validation_summary, error,
         forecast_reference, candidate_reference, input_reference, variables_count,
         constraints, objective_configuration, error_message, qubo_storage,
         qubo_artifact_reference, deleted_at, deleted_by, delete_reason,
         created_at, started_at, completed_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,$33,$34,$35,$36)
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
         forecast_reference = EXCLUDED.forecast_reference,
         candidate_reference = EXCLUDED.candidate_reference,
         input_reference = EXCLUDED.input_reference,
         variables_count = EXCLUDED.variables_count,
         constraints = EXCLUDED.constraints,
         objective_configuration = EXCLUDED.objective_configuration,
         error_message = EXCLUDED.error_message,
         qubo_storage = EXCLUDED.qubo_storage,
         qubo_artifact_reference = EXCLUDED.qubo_artifact_reference,
         deleted_at = EXCLUDED.deleted_at, deleted_by = EXCLUDED.deleted_by,
         delete_reason = EXCLUDED.delete_reason,
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
        artifact ? null : (job.qubo !== null ? JSON.stringify(job.qubo) : null),
        job.classical !== null ? JSON.stringify(job.classical) : null,
        job.result !== null ? JSON.stringify(job.result) : null,
        job.validationStatus,
        job.validationSummary,
        job.error !== null ? JSON.stringify(job.error) : null,
        job.forecastReference,
        job.candidateReference,
        job.inputReference,
        job.variablesCount,
        job.constraints !== null ? JSON.stringify(job.constraints) : null,
        job.objectiveConfiguration !== null ? JSON.stringify(job.objectiveConfiguration) : null,
        job.errorMessage,
        job.quboStorage,
        quboReference,
        job.deletedAt,
        job.deletedBy,
        job.deleteReason,
        job.createdAt,
        job.startedAt,
        job.completedAt,
      ],
    )
    if (artifact && job.qubo !== null) {
      await getPool().query(
        `INSERT INTO optimization_qubo_artifacts (optimization_job_id, variable_count, storage_reference, qubo)
         VALUES ($1, $2, $3, $4)
         ON CONFLICT (optimization_job_id) DO UPDATE SET
           variable_count = EXCLUDED.variable_count,
           storage_reference = EXCLUDED.storage_reference,
           qubo = EXCLUDED.qubo,
           stored_at = now()`,
        [job.id, job.qubo.doc.variableCount, quboReference, JSON.stringify(job.qubo)],
      )
    }
    // QUBO metadata audit record (migration 005): inline rows carry the full
    // plain-JSON representation; artifact rows carry reference + checksum +
    // dimensions only — never the matrix cells.
    if (job.qubo !== null) {
      await this.saveQuboMetadata(deriveQuboMetadata(job))
    }
    return job
  }

  async findById(id: string): Promise<OptimizationJob | null> {
    const result = await getPool().query<OptimizationJobRow>('SELECT * FROM optimization_jobs WHERE id = $1', [id])
    return result.rows[0] ? rowToOptimizationJob(result.rows[0]) : null
  }

  async list(limit = 200): Promise<OptimizationJob[]> {
    const result = await getPool().query<OptimizationJobRow>(
      `SELECT * FROM optimization_jobs
        WHERE deleted_at IS NULL
        ORDER BY created_at DESC
        LIMIT $1`,
      [limit],
    )
    return result.rows.map((row) => rowToOptimizationJob(row))
  }

  async findQuboBuild(jobId: string): Promise<QuboBuild | null> {
    const result = await getPool().query<{ qubo: QuboBuild }>(
      'SELECT qubo FROM optimization_qubo_artifacts WHERE optimization_job_id = $1',
      [jobId],
    )
    return result.rows[0]?.qubo ?? null
  }

  async saveResult(resultRecord: OptimizationResultRecord): Promise<OptimizationResultRecord> {
    // The approximation_ratio/basis/reason + classical reference snapshot is
    // WRITE-ONCE (migration 007): a re-run of this upsert never overwrites a
    // previously stored snapshot — COALESCE keeps the historical row intact.
    await getPool().query(
      `INSERT INTO optimization_results (
         id, optimization_job_id, bitstring, selected_locations, objective_value,
         constraint_violations, validation_status, runtime_ms,
         classical_objective, quantum_objective, approximation_quality,
         classical_solver, classical_runtime_ms,
         approximation_ratio, approximation_basis, approximation_invalid_reason,
         random_seed, validation_timestamp, validation_details, explanation_metadata,
         created_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)
       ON CONFLICT (id) DO UPDATE SET
         bitstring = EXCLUDED.bitstring,
         selected_locations = EXCLUDED.selected_locations,
         objective_value = EXCLUDED.objective_value,
         constraint_violations = EXCLUDED.constraint_violations,
         validation_status = EXCLUDED.validation_status,
         runtime_ms = EXCLUDED.runtime_ms,
         classical_objective = EXCLUDED.classical_objective,
         quantum_objective = EXCLUDED.quantum_objective,
         approximation_quality = EXCLUDED.approximation_quality,
         classical_solver = COALESCE(optimization_results.classical_solver, EXCLUDED.classical_solver),
         classical_runtime_ms = COALESCE(optimization_results.classical_runtime_ms, EXCLUDED.classical_runtime_ms),
         approximation_ratio = COALESCE(optimization_results.approximation_ratio, EXCLUDED.approximation_ratio),
         approximation_basis = COALESCE(optimization_results.approximation_basis, EXCLUDED.approximation_basis),
         approximation_invalid_reason = COALESCE(optimization_results.approximation_invalid_reason, EXCLUDED.approximation_invalid_reason),
         random_seed = COALESCE(optimization_results.random_seed, EXCLUDED.random_seed),
         validation_timestamp = COALESCE(optimization_results.validation_timestamp, EXCLUDED.validation_timestamp),
         validation_details = COALESCE(optimization_results.validation_details, EXCLUDED.validation_details),
         explanation_metadata = COALESCE(optimization_results.explanation_metadata, EXCLUDED.explanation_metadata),
         created_at = EXCLUDED.created_at`,
      [
        resultRecord.id,
        resultRecord.optimizationJobId,
        resultRecord.bitstring,
        JSON.stringify(resultRecord.selectedLocationIds),
        resultRecord.objectiveValue,
        JSON.stringify(resultRecord.constraintViolations),
        resultRecord.validationStatus,
        resultRecord.runtimeMs,
        resultRecord.classicalObjective,
        resultRecord.quantumObjective,
        resultRecord.approximationQuality,
        resultRecord.classicalSolver,
        resultRecord.classicalRuntimeMs,
        resultRecord.approximationRatio,
        resultRecord.approximationBasis,
        resultRecord.approximationInvalidReason,
        resultRecord.randomSeed,
        resultRecord.validationTimestamp,
        resultRecord.validationDetails ? JSON.stringify(resultRecord.validationDetails) : null,
        resultRecord.explanationMetadata ? JSON.stringify(resultRecord.explanationMetadata) : null,
        resultRecord.createdAt,
      ],
    )
    return resultRecord
  }

  async findResult(jobId: string): Promise<OptimizationResultRecord | null> {
    const result = await getPool().query<OptimizationResultRow>(
      'SELECT * FROM optimization_results WHERE optimization_job_id = $1',
      [jobId],
    )
    return result.rows[0] ? rowToOptimizationResult(result.rows[0]) : null
  }

  async saveQuboMetadata(metadata: QuboMetadata): Promise<QuboMetadata> {
    const inline = metadata.storageMode === 'inline'
    await getPool().query(
      `INSERT INTO optimization_qubo_metadata (
         qubo_id, optimization_job_id, storage_mode, variable_count,
         matrix, linear_terms, quadratic_terms, penalty_configuration, objective_expression,
         artifact_reference, checksum, matrix_dimensions, storage_location, metadata, created_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
       ON CONFLICT (qubo_id) DO UPDATE SET
         storage_mode = EXCLUDED.storage_mode,
         variable_count = EXCLUDED.variable_count,
         matrix = EXCLUDED.matrix,
         linear_terms = EXCLUDED.linear_terms,
         quadratic_terms = EXCLUDED.quadratic_terms,
         penalty_configuration = EXCLUDED.penalty_configuration,
         objective_expression = EXCLUDED.objective_expression,
         artifact_reference = EXCLUDED.artifact_reference,
         checksum = EXCLUDED.checksum,
         matrix_dimensions = EXCLUDED.matrix_dimensions,
         storage_location = EXCLUDED.storage_location,
         metadata = EXCLUDED.metadata,
         created_at = EXCLUDED.created_at`,
      [
        metadata.quboId,
        metadata.optimizationJobId,
        metadata.storageMode,
        metadata.variableCount,
        inline ? JSON.stringify(metadata.matrix) : null,
        inline ? JSON.stringify(metadata.linearTerms) : null,
        inline ? JSON.stringify(metadata.quadraticTerms) : null,
        inline ? JSON.stringify(metadata.penaltyConfiguration) : null,
        inline ? metadata.objectiveExpression ?? null : null,
        inline ? null : metadata.artifactReference,
        inline ? null : metadata.checksum,
        inline ? null : JSON.stringify(metadata.matrixDimensions),
        inline ? null : metadata.storageLocation,
        inline ? null : JSON.stringify(metadata.metadata),
        metadata.createdAt ?? new Date().toISOString(),
      ],
    )
    return metadata
  }

  async findQuboMetadata(jobId: string): Promise<QuboMetadata | null> {
    const result = await getPool().query<QuboMetadataRow>(
      'SELECT * FROM optimization_qubo_metadata WHERE optimization_job_id = $1',
      [jobId],
    )
    return result.rows[0] ? rowToQuboMetadata(result.rows[0]) : null
  }

  async deleteJob(jobId: string, actor: string, reason: string): Promise<OptimizationJob> {
    await getPool().query(
      `WITH updated AS (
         UPDATE optimization_jobs
            SET deleted_at = now(), deleted_by = $2, delete_reason = $3
          WHERE id = $1
          RETURNING id
       )
       INSERT INTO optimization_job_audit (optimization_job_id, action, actor, reason)
       SELECT id, 'soft_deleted', $2, $3 FROM updated`,
      [jobId, actor, reason],
    )
    const job = await this.findById(jobId)
    if (!job) throw new AppError(404, ErrorCodes.JOB_NOT_FOUND, `Optimization job '${jobId}' not found`)
    return job
  }

  async appendAudit(entry: {
    optimizationJobId: string
    action: string
    actor: string
    reason: string | null
  }): Promise<OptimizationJobAuditEntry> {
    const result = await getPool().query<OptimizationAuditRow>(
      `INSERT INTO optimization_job_audit (optimization_job_id, action, actor, reason)
       VALUES ($1, $2, $3, $4)
       RETURNING id, optimization_job_id, action, actor, reason, created_at`,
      [entry.optimizationJobId, entry.action, entry.actor, entry.reason],
    )
    const row = result.rows[0]
    return {
      id: Number(row.id),
      optimizationJobId: row.optimization_job_id,
      action: row.action,
      actor: row.actor,
      reason: row.reason,
      createdAt: row.created_at.toISOString(),
    }
  }

  async listAudit(jobId: string): Promise<OptimizationJobAuditEntry[]> {
    const result = await getPool().query<OptimizationAuditRow>(
      `SELECT id, optimization_job_id, action, actor, reason, created_at
         FROM optimization_job_audit WHERE optimization_job_id = $1 ORDER BY id`,
      [jobId],
    )
    return result.rows.map((row) => ({
      id: Number(row.id),
      optimizationJobId: row.optimization_job_id,
      action: row.action,
      actor: row.actor,
      reason: row.reason,
      createdAt: row.created_at.toISOString(),
    }))
  }

  async deleteAll(): Promise<void> {
    const client = await getPool().connect()
    try {
      await client.query('BEGIN')
      // Administrative cleanup: enable the migration 004 escape hatch so the
      // write-once guard is lifted for the test-purge statement only.
      await client.query(`SET LOCAL "app.allow_optimization_delete" = 'true'`)
      await client.query('DELETE FROM optimization_jobs')
      await client.query('COMMIT')
    } catch (error) {
      await client.query('ROLLBACK').catch(() => undefined)
      throw error
    } finally {
      client.release()
    }
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
  forecast_reference: string | null
  candidate_reference: string | null
  input_reference: string | null
  variables_count: number | null
  constraints: OptimizationJob['constraints']
  objective_configuration: OptimizationJob['objectiveConfiguration']
  error_message: string | null
  qubo_storage: OptimizationJob['quboStorage']
  qubo_artifact_reference: string | null
  deleted_at: string | null
  deleted_by: string | null
  delete_reason: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

interface OptimizationResultRow {
  id: string
  optimization_job_id: string
  bitstring: string | null
  selected_locations: string[]
  objective_value: number
  constraint_violations: unknown[]
  validation_status: OptimizationResultRecord['validationStatus']
  runtime_ms: number
  classical_objective: number | null
  quantum_objective: number | null
  approximation_quality: number | null
  classical_solver: OptimizationResultRecord['classicalSolver'] | string | null
  classical_runtime_ms: number | null
  approximation_ratio: number | null
  approximation_basis: OptimizationResultRecord['approximationBasis'] | string | null
  approximation_invalid_reason: OptimizationResultRecord['approximationInvalidReason'] | string | null
  random_seed: string | number | null
  validation_timestamp: string | Date | null
  validation_details: OptimizationResultRecord['validationDetails']
  explanation_metadata: OptimizationResultRecord['explanationMetadata']
  created_at: string
}

interface OptimizationAuditRow {
  id: number
  optimization_job_id: string
  action: string
  actor: string
  reason: string | null
  created_at: Date
}

interface QuboMetadataRow {
  qubo_id: string
  optimization_job_id: string
  storage_mode: QuboMetadata['storageMode']
  variable_count: number
  matrix: QuboMetadata['matrix'] | null
  linear_terms: QuboMetadata['linearTerms'] | null
  quadratic_terms: QuboMetadata['quadraticTerms'] | null
  penalty_configuration: QuboMetadata['penaltyConfiguration'] | null
  objective_expression: string | null
  artifact_reference: string | null
  checksum: string | null
  matrix_dimensions: QuboMetadata['matrixDimensions'] | null
  storage_location: string | null
  metadata: QuboMetadata['metadata'] | null
  created_at: string
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
    forecastReference: row.forecast_reference,
    candidateReference: row.candidate_reference,
    inputReference: row.input_reference,
    variablesCount: row.variables_count,
    constraints: row.constraints,
    objectiveConfiguration: row.objective_configuration,
    errorMessage: row.error_message,
    quboStorage: row.qubo_storage,
    quboArtifactReference: row.qubo_artifact_reference,
    deletedAt: row.deleted_at,
    deletedBy: row.deleted_by,
    deleteReason: row.delete_reason,
  }
}

function rowToOptimizationResult(row: OptimizationResultRow): OptimizationResultRecord {
  return {
    id: row.id,
    optimizationJobId: row.optimization_job_id,
    bitstring: row.bitstring,
    selectedLocationIds: row.selected_locations,
    objectiveValue: row.objective_value,
    constraintViolations: row.constraint_violations as OptimizationResultRecord['constraintViolations'],
    validationStatus: row.validation_status,
    runtimeMs: row.runtime_ms,
    classicalObjective: row.classical_objective,
    quantumObjective: row.quantum_objective,
    approximationQuality: row.approximation_quality,
    classicalSolver: (row.classical_solver as OptimizationResultRecord['classicalSolver']) ?? null,
    classicalRuntimeMs: row.classical_runtime_ms,
    approximationRatio: row.approximation_ratio,
    approximationBasis: (row.approximation_basis as OptimizationResultRecord['approximationBasis']) ?? null,
    approximationInvalidReason: (row.approximation_invalid_reason as OptimizationResultRecord['approximationInvalidReason']) ?? null,
    randomSeed: row.random_seed === null ? null : Number(row.random_seed),
    validationTimestamp: row.validation_timestamp ? new Date(row.validation_timestamp).toISOString() : null,
    validationDetails: row.validation_details ?? null,
    explanationMetadata: row.explanation_metadata ?? null,
    createdAt: row.created_at,
  }
}

function rowToQuboMetadata(row: QuboMetadataRow): QuboMetadata {
  return {
    quboId: row.qubo_id,
    optimizationJobId: row.optimization_job_id,
    storageMode: row.storage_mode,
    variableCount: row.variable_count,
    ...(row.matrix !== null && { matrix: row.matrix }),
    ...(row.linear_terms !== null && { linearTerms: row.linear_terms }),
    ...(row.quadratic_terms !== null && { quadraticTerms: row.quadratic_terms }),
    ...(row.penalty_configuration !== null && { penaltyConfiguration: row.penalty_configuration }),
    ...(row.objective_expression !== null && { objectiveExpression: row.objective_expression }),
    ...(row.artifact_reference !== null && { artifactReference: row.artifact_reference }),
    ...(row.checksum !== null && { checksum: row.checksum }),
    ...(row.matrix_dimensions !== null && { matrixDimensions: row.matrix_dimensions }),
    ...(row.storage_location !== null && { storageLocation: row.storage_location }),
    ...(row.metadata !== null && { metadata: row.metadata }),
    createdAt: row.created_at,
  }
}

/**
 * Persisted quantum submissions (`quantum_jobs` / `quantum_results`, migration
 * 006). Lifecycle is upsert-driven: `saveJob` records a queued/running row at
 * submission time and updates it to a terminal state with the same id — every
 * attempt on a fallback ladder gets its own honest row, preserving the
 * simulator/hardware distinction. Only configuration scalars and plain-JSON
 * counts are stored; raw circuits are never persisted.
 */
export class PostgresQuantumJobRepository implements QuantumJobRepository {
  async saveJob(job: QuantumJobRecord): Promise<QuantumJobRecord> {
    await getPool().query(
      `INSERT INTO quantum_jobs (
         id, optimization_job_id, algorithm, backend, execution_mode, qubits,
         shots, layers, status, submitted_at, started_at, completed_at,
         error_code, error_message, created_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
       ON CONFLICT (id) DO UPDATE SET
         status = EXCLUDED.status,
         qubits = EXCLUDED.qubits,
         started_at = EXCLUDED.started_at,
         completed_at = EXCLUDED.completed_at,
         error_code = EXCLUDED.error_code,
         error_message = EXCLUDED.error_message`,
      [
        job.id,
        job.optimizationJobId,
        job.algorithm,
        job.backend,
        job.executionMode,
        job.qubits,
        job.shots,
        job.layers,
        job.status,
        job.submittedAt,
        job.startedAt,
        job.completedAt,
        job.errorCode,
        job.errorMessage,
        job.createdAt,
      ],
    )
    return job
  }

  async findJobById(id: string): Promise<QuantumJobRecord | null> {
    const result = await getPool().query<QuantumJobRow>('SELECT * FROM quantum_jobs WHERE id = $1', [id])
    return result.rows[0] ? rowToQuantumJob(result.rows[0]) : null
  }

  async findJobsByOptimizationJobId(optimizationJobId: string): Promise<QuantumJobRecord[]> {
    const result = await getPool().query<QuantumJobRow>(
      `SELECT * FROM quantum_jobs WHERE optimization_job_id = $1 ORDER BY created_at ASC, id ASC`,
      [optimizationJobId],
    )
    return result.rows.map(rowToQuantumJob)
  }

  async saveResult(result: QuantumResultRecord): Promise<QuantumResultRecord> {
    await getPool().query(
      `INSERT INTO quantum_results (
         id, quantum_job_id, bitstring, counts, objective_value, runtime_ms,
         raw_metadata_reference, created_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
       ON CONFLICT (id) DO UPDATE SET
         bitstring = EXCLUDED.bitstring,
         counts = EXCLUDED.counts,
         objective_value = EXCLUDED.objective_value,
         runtime_ms = EXCLUDED.runtime_ms,
         raw_metadata_reference = EXCLUDED.raw_metadata_reference,
         created_at = EXCLUDED.created_at`,
      [
        result.id,
        result.quantumJobId,
        result.bitstring,
        JSON.stringify(result.counts),
        result.objectiveValue,
        result.runtimeMs,
        result.rawMetadataReference,
        result.createdAt,
      ],
    )
    return result
  }

  async findResult(quantumJobId: string): Promise<QuantumResultRecord | null> {
    const result = await getPool().query<QuantumResultRow>(
      'SELECT * FROM quantum_results WHERE quantum_job_id = $1',
      [quantumJobId],
    )
    return result.rows[0] ? rowToQuantumResult(result.rows[0]) : null
  }

  async deleteAll(): Promise<void> {
    await getPool().query('DELETE FROM quantum_results')
    await getPool().query('DELETE FROM quantum_jobs')
  }
}

interface QuantumJobRow {
  id: string
  optimization_job_id: string
  algorithm: string
  backend: QuantumJobRecord['backend']
  execution_mode: QuantumJobRecord['executionMode']
  qubits: number | null
  shots: number
  layers: number
  status: QuantumJobRecord['status']
  submitted_at: Date | string
  started_at: Date | string | null
  completed_at: Date | string | null
  error_code: string | null
  error_message: string | null
  created_at: Date | string
}

interface QuantumResultRow {
  id: string
  quantum_job_id: string
  bitstring: string | null
  counts: Record<string, number>
  objective_value: number | null
  runtime_ms: number
  raw_metadata_reference: string | null
  created_at: Date | string
}

function toIso(value: Date | string | null): string | null {
  return value === null ? null : value instanceof Date ? value.toISOString() : String(value)
}

function rowToQuantumJob(row: QuantumJobRow): QuantumJobRecord {
  return {
    id: row.id,
    optimizationJobId: row.optimization_job_id,
    algorithm: row.algorithm,
    backend: row.backend,
    executionMode: row.execution_mode,
    qubits: row.qubits,
    shots: row.shots,
    layers: row.layers,
    status: row.status,
    submittedAt: toIso(row.submitted_at)!,
    startedAt: toIso(row.started_at),
    completedAt: toIso(row.completed_at),
    errorCode: row.error_code,
    errorMessage: row.error_message,
    createdAt: toIso(row.created_at)!,
  }
}

function rowToQuantumResult(row: QuantumResultRow): QuantumResultRecord {
  return {
    id: row.id,
    quantumJobId: row.quantum_job_id,
    bitstring: row.bitstring,
    counts: row.counts ?? {},
    objectiveValue: row.objective_value,
    runtimeMs: row.runtime_ms,
    rawMetadataReference: row.raw_metadata_reference,
    createdAt: toIso(row.created_at)!,
  }
}