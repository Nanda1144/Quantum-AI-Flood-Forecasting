/**
 * Dependency container — wires repositories, the AI client, and services.
 *
 * `POSTGRES` mode uses real PostgreSQL; `MEMORY` mode uses in-memory repos
 * (tests, or graceful fallback when the database is unreachable).
 */

import { z } from 'zod'
import type { ForecastClient } from './clients/ai-service.client.ts'
import { AIServiceClient } from './clients/ai-service.client.ts'
import type { QuantumServiceClient } from './clients/quantum-service.client.ts'
import { HttpQuantumServiceClient } from './clients/quantum-service.client.ts'
import { config } from './config.ts'
import { MemoryForecastRepository, MemoryModelComparisonRepository, MemoryModelRepository, MemoryOptimizationJobRepository, MemoryOptimizationRepository } from './repositories/memory/repositories.ts'
import { PostgresForecastRepository, PostgresModelComparisonRepository, PostgresModelRepository, PostgresOptimizationJobRepository, PostgresOptimizationRepository } from './repositories/postgres/repositories.ts'
import { ensureSchema } from './repositories/postgres/pool.ts'
import type { ForecastRepository, ModelComparisonRepository, ModelRepository, OptimizationJobRepository, OptimizationRepository } from './repositories/repositories.ts'
import { AnalyticsService } from './services/analytics.service.ts'
import { AuthService } from './services/auth.service.ts'
import { ForecastSyncService } from './services/forecast-sync.service.ts'
import { ModelsComparisonService } from './services/models-comparison.service.ts'
import { ModelsRegistryService } from './services/models-registry.service.ts'
import { OptimizationService } from './services/optimization.service.ts'
import { OptimizationJobService, type OptimizationJobServiceOptions } from './services/optimization-orchestrator.service.ts'
import { ServerCandidateStore, ServerConstraintsSource, type CandidateStore, type ConstraintsSource } from './services/gis/candidate-store.ts'
import { PredictionsService } from './services/predictions.service.ts'
import { StatusService } from './services/status.service.ts'

const driverSchema = z.enum(['postgres', 'memory'])

export interface Container {
  forecastRepo: ForecastRepository
  modelRepo: ModelRepository
  optimizationRepo: OptimizationRepository
  comparisonRepo: ModelComparisonRepository
  jobRepo: OptimizationJobRepository
  aiClient: ForecastClient
  quantumClient: QuantumServiceClient
  candidates: CandidateStore
  constraintsSource: ConstraintsSource
  forecastSync: ForecastSyncService
  analytics: AnalyticsService
  predictions: PredictionsService
  modelsComparison: ModelsComparisonService
  modelsRegistry: ModelsRegistryService
  status: StatusService
  optimization: OptimizationService
  optimizationJobs: OptimizationJobService
  auth: AuthService
}

async function buildRepos(): Promise<{
  forecastRepo: ForecastRepository
  modelRepo: ModelRepository
  optimizationRepo: OptimizationRepository
  optimizationJobRepo: OptimizationJobRepository
  comparisonRepo: ModelComparisonRepository
  mode: 'postgres' | 'memory'
}> {
  const driver = driverSchema.parse(process.env.DATABASE_MODE ?? 'postgres')
  if (driver === 'memory') {
    return {
      forecastRepo: new MemoryForecastRepository(),
      modelRepo: new MemoryModelRepository(),
      optimizationRepo: new MemoryOptimizationRepository(),
      optimizationJobRepo: new MemoryOptimizationJobRepository(),
      comparisonRepo: new MemoryModelComparisonRepository(),
      mode: 'memory',
    }
  }
  try {
    await ensureSchema()
    return {
      forecastRepo: new PostgresForecastRepository(),
      modelRepo: new PostgresModelRepository(),
      optimizationRepo: new PostgresOptimizationRepository(),
      optimizationJobRepo: new PostgresOptimizationJobRepository(),
      comparisonRepo: new PostgresModelComparisonRepository(),
      mode: 'postgres',
    }
  } catch (error) {
    // Graceful fallback keeps the local demo working without a DB.
    console.warn('[backend] PostgreSQL unavailable, falling back to in-memory repositories:', error instanceof Error ? error.message : error)
    return {
      forecastRepo: new MemoryForecastRepository(),
      modelRepo: new MemoryModelRepository(),
      optimizationRepo: new MemoryOptimizationRepository(),
      optimizationJobRepo: new MemoryOptimizationJobRepository(),
      comparisonRepo: new MemoryModelComparisonRepository(),
      mode: 'memory',
    }
  }
}

/** Test/demo overrides for the optimization orchestration stack. */
export interface OptimizationOverrides {
  quantumClient?: QuantumServiceClient
  jobRepo?: OptimizationJobRepository
  candidateStore?: CandidateStore
  constraintsSource?: ConstraintsSource
  options?: Partial<OptimizationJobServiceOptions>
}

export async function buildContainer(options: {
  aiClient?: ForecastClient
  comparisonRepo?: ModelComparisonRepository
  optimization?: OptimizationOverrides
} = {}): Promise<Container> {
  const repos = await buildRepos()
  const aiClient = options.aiClient ?? new AIServiceClient()
  const comparisonRepo = options.comparisonRepo ?? repos.comparisonRepo
  const quantumClient = options.optimization?.quantumClient ?? new HttpQuantumServiceClient()
  const jobRepo = options.optimization?.jobRepo ?? repos.optimizationJobRepo
  const candidateStore = options.optimization?.candidateStore ?? new ServerCandidateStore()
  const constraintsSource = options.optimization?.constraintsSource ?? new ServerConstraintsSource()

  const forecastSync = new ForecastSyncService(aiClient, repos.forecastRepo, repos.modelRepo)
  const analytics = new AnalyticsService(forecastSync, repos.modelRepo, repos.optimizationRepo, aiClient)
  const predictions = new PredictionsService(repos.forecastRepo)
  const modelsComparison = new ModelsComparisonService(comparisonRepo)
  const modelsRegistry = new ModelsRegistryService(comparisonRepo, config.MODEL_SELECTION_METRIC)
  const status = new StatusService(repos.forecastRepo, aiClient)
  const optimization = new OptimizationService(repos.optimizationRepo, repos.forecastRepo)
  const optimizationJobs = new OptimizationJobService(
    jobRepo,
    repos.forecastRepo,
    candidateStore,
    constraintsSource,
    quantumClient,
    {
      fallbackPolicy: options.optimization?.options?.fallbackPolicy ?? config.OPTIMIZATION_FALLBACK_POLICY,
      exhaustiveLimit: options.optimization?.options?.exhaustiveLimit ?? config.OPTIMIZATION_EXHAUSTIVE_LIMIT,
      executionTimeoutMs: options.optimization?.options?.executionTimeoutMs ?? config.OPTIMIZATION_EXECUTION_TIMEOUT_MS,
    },
  )

  return {
    ...repos,
    comparisonRepo,
    jobRepo,
    aiClient,
    quantumClient,
    candidates: candidateStore,
    constraintsSource,
    forecastSync,
    analytics,
    predictions,
    modelsComparison,
    modelsRegistry,
    status,
    optimization,
    optimizationJobs,
    auth: new AuthService(config),
  }
}