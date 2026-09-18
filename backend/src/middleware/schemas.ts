/** Zod schemas for request validation. Invalid data → 422, never coerced. */

import { z } from 'zod'

const FORECAST_ID_PATTERN = /^FC-\d{8}-\d{1,6}$/

export const forecastIdSchema = z
  .string()
  .regex(FORECAST_ID_PATTERN, 'forecast_id must match FC-YYYYMMDD-###')

export const riskLevelSchema = z.enum(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'])

export const modelIdSchema = z.string().min(1).max(64)

export const prioritySchema = z.enum(['low', 'medium', 'high', 'critical'])

/** Probability must be a finite number within [0,1] — NaN/Inf handled by z.number(). */
export const probabilitySchema = z.number().finite().min(0).max(1)

export const loginSchema = z.object({
  username: z.string().min(1).max(64),
  password: z.string().min(1).max(128),
})

export const listPredictionsQuerySchema = z.object({
  page: z.coerce.number().int().min(1).default(1),
  limit: z.coerce.number().int().min(1).max(100).default(10),
  from: z.string().datetime({ offset: true }).optional(),
  to: z.string().datetime({ offset: true }).optional(),
  risk: riskLevelSchema.optional(),
  model: modelIdSchema.optional(),
})

export const registryStatusSchema = z.enum(['active', 'retired', 'development'])

/**
 * Registry version ids are BIGINT identity values serialized as strings —
 * strictly positive numeric so `/models/:id` never shadows static routes and
 * injected ids ("..", "0", "1; DROP ...") are rejected before hitting SQL.
 */
export const registryModelIdSchema = z
  .string()
  .regex(/^[1-9]\d*$/, 'registry model id must be a positive integer serialized as a string')

export const listModelsQuerySchema = z.object({
  status: registryStatusSchema.optional(),
  algorithm: z.string().trim().min(1).max(64).optional(),
  dataset: z.string().trim().min(1).max(256).optional(),
  page: z.coerce.number().int().min(1).default(1),
  limit: z.coerce.number().int().min(1).max(100).default(20),
})

export const compareModelsBodySchema = z.object({
  model_ids: z.array(registryModelIdSchema).min(1).max(50),
})

export const modelDetailParamsSchema = z.object({
  id: registryModelIdSchema,
})

export const comparisonQuerySchema = z.object({
  sort: z.enum(['name', 'evaluatedAt', 'mae', 'rmse', 'r2', 'inferenceTime']).optional(),
  direction: z.enum(['asc', 'desc']).optional(),
  from: z.string().datetime({ offset: true }).optional(),
  to: z.string().datetime({ offset: true }).optional(),
  status: registryStatusSchema.optional(),
})

export const optimizationBodySchema = z.object({
  forecast_id: forecastIdSchema,
  risk_score: probabilitySchema.optional(),
  priority: prioritySchema.optional(),
  candidate_locations_available: z.boolean().optional(),
  resource_constraints_available: z.boolean().optional(),
})

/** Quantum backend identifiers accepted by the executor (mirror frontend catalog). */
export const quantumBackendSchema = z.enum([
  'qflare_simulator_statevector',
  'aer_simulator_statevector',
  'aer_simulator_matrix_product_state',
  'ibm_brisbane',
  'ibm_kyiv',
])

const objectiveWeightsSchema = z
  .object({
    risk: z.number().finite().min(0),
    populationCoverage: z.number().finite().min(0),
    infrastructureCoverage: z.number().finite().min(0),
    communication: z.number().finite().min(0),
    cost: z.number().finite().min(0),
    redundancy: z.number().finite().min(0),
  })
  .refine((weights) => Object.values(weights).some((value) => value > 0), {
    message: 'at least one objective weight must be greater than 0',
  })

/**
 * `POST /api/optimization/run` body. Snake_case on the wire, mapped to the
 * camelCase `RunOptimizationRequest` by the route. semantic checks that need
 * candidate geometry (budget vs cheapest site) stay in the orchestrator.
 */
export const runOptimizationBodySchema = z
  .object({
    problem_type: z.enum(['sensor_placement', 'resource_allocation']),
    candidate_count: z.number().int().min(2).max(100),
    max_sensors: z.number().int().min(1),
    budget_k: z.number().finite().min(0).nullable(),
    forecast_reference: forecastIdSchema,
    risk_profile: riskLevelSchema.optional(),
    execution_mode: z.enum(['simulator', 'hardware']),
    hardware_enabled: z.boolean(),
    backend: quantumBackendSchema,
    shots: z.number().int().min(1).max(100_000).default(1024),
    layers: z.number().int().min(1).max(10).default(2),
    weights: objectiveWeightsSchema,
    normalize_weights: z.boolean(),
    coverage_requirements: z
      .array(
        z.object({
          metric: z.enum(['population', 'infrastructure']),
          min_fraction: z.number().finite().min(0).max(1),
          origin: z.string().min(1).max(128),
        }),
      )
      .max(10)
      .default([]),
    candidate_locations_reference: z.string().min(1).max(256).optional(),
  })
  .refine((body) => body.max_sensors <= body.candidate_count, {
    message: 'max_sensors cannot exceed candidate_count',
    path: ['max_sensors'],
  })

/** `/api/optimization/:id` and `/api/optimization/jobs/:id/...` params. */
export const optimizationJobParamsSchema = z.object({
  id: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/, 'job id must be a valid identifier'),
})

/** `GET /api/optimization/inputs` query (camelCase per the frontend adapter). */
export const optimizationInputsQuerySchema = z.object({
  candidateCount: z.coerce.number().int().min(2).max(100).default(24),
  forecast: forecastIdSchema.optional(),
  risk: riskLevelSchema.optional(),
})