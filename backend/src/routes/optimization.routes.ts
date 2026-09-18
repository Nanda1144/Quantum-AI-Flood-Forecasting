import { Router } from 'express'
import { z } from 'zod'
import type { Container } from '../container.ts'
import { success } from '../envelope.ts'
import { authenticate, authorize } from '../middleware/authorize.ts'
import { optimizationRunLimiter } from '../middleware/rate-limit.ts'
import {
  optimizationBodySchema,
  optimizationInputsQuerySchema,
  optimizationJobParamsSchema,
  runOptimizationBodySchema,
} from '../middleware/schemas.ts'
import { validate } from '../middleware/validate.ts'
import { config } from '../config.ts'
import { defaultConstraints } from '../services/gis/candidate-store.ts'
import type {
  CoverageRequirement,
  FrontendStageId,
  OptimizationJob,
  PipelineStep,
  QuantumBackend,
  RunOptimizationRequest,
  StepStatus,
} from '../types/optimization.ts'

/**
 * Optimization orchestration API — the Nanda command surface.
 *
 *   POST /api/optimization/run        validate + queue a pipeline job (202).
 *   GET  /api/optimization/:id        job summary (status, algorithm, mode, …).
 *   GET  /api/optimization/inputs     federated GIS/planning inputs for the UI.
 *   GET  /api/optimization/jobs/:id/pipeline|result|qubo|classical|export
 *                                     fine-grained read surfaces (frontend adapter).
 *
 * Every route is authenticated; writes require `operator`, reads `viewer`.
 * Reads are ownership-scoped: a job is only visible to its owner or an admin.
 */
export function optimizationRoutes(c: Container): Router {
  const router = Router()

  router.use(authenticate(c.auth, config.AUTH_ENABLED))

  /** Validation paths of POST /api/optimization/from-forecast (existing handoff). */
  router.post('/from-forecast', authorize('operator'), validate({ body: optimizationBodySchema }), async (req, res, next) => {
    try {
      const reference = await c.optimization.createFromForecast(req.validated?.body as z.infer<typeof optimizationBodySchema>)
      res.json(success(reference))
    } catch (error) {
      next(error)
    }
  })

  /** POST /api/optimization/run — validate, queue, and start the pipeline. */
  router.post(
    '/run',
    authorize('operator'),
    optimizationRunLimiter,
    validate({ body: runOptimizationBodySchema }),
    async (req, res, next) => {
      try {
        const body = req.validated!.body as z.infer<typeof runOptimizationBodySchema>
        const request = toRunOptimizationRequest(body)
        const job = await c.optimizationJobs.createJob(request, req.principal!.username)
        res.status(202).json(success(c.optimizationJobs.summary(job)))
      } catch (error) {
        next(error)
      }
    },
  )

  /** GET /api/optimization/inputs — federated GIS candidates + planner constraints. */
  router.get('/inputs', authorize('viewer'), validate({ query: optimizationInputsQuerySchema }), async (req, res, next) => {
    try {
      const query = req.validated!.query as z.infer<typeof optimizationInputsQuerySchema>
      const count = query.candidateCount
      const reference = query.forecast ?? `gis://candidates/${count}`
      const candidates = await c.candidates.getCandidates({ reference, count })
      const defaults = defaultConstraints(count)
      res.json(
        success({
          candidates,
          constraints: {
            maxSensors: defaults.maxSensors,
            budgetK: null,
            coverageRequirements: [] as CoverageRequirement[],
            notes: ['Resource constraints resolved from planning module defaults (reference).'],
          },
          providedBy: {
            candidateLocations: 'GIS module (reference)',
            resourceConstraints: 'Planning module (reference)',
            forecast: 'AI forecasting',
          },
        }),
      )
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/optimization/jobs/:id/pipeline — aggregated stages for the UI. */
  router.get('/jobs/:id/pipeline', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      const job = await c.optimizationJobs.getJobForPrincipal(id, req.principal!)
      res.json(success(pipelinePayload(job)))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/optimization/jobs/:id/result — full result document. */
  router.get('/jobs/:id/result', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      const job = await c.optimizationJobs.getJobForPrincipal(id, req.principal!)
      res.json(success(c.optimizationJobs.resultPayload(job)))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/optimization/jobs/:id/qubo — served QUBO document. */
  router.get('/jobs/:id/qubo', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      const job = await c.optimizationJobs.getJobForPrincipal(id, req.principal!)
      res.json(success(jobResult(job)?.qubo ?? job.qubo?.doc ?? null))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/optimization/jobs/:id/classical — persisted classical benchmark. */
  router.get('/jobs/:id/classical', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      const job = await c.optimizationJobs.getJobForPrincipal(id, req.principal!)
      res.json(success(jobResult(job)?.classicalComparison ?? job.classical ?? null))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/optimization/jobs/:id/export — signed, auditable result document. */
  router.get('/jobs/:id/export', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      const job = await c.optimizationJobs.getJobForPrincipal(id, req.principal!)
      const result = jobResult(job)
      res.json(
        success({
          jobId: job.id,
          exportedAt: new Date().toISOString(),
          status: job.status,
          summary: c.optimizationJobs.summary(job),
          result,
          quantumAdvantageClaimed: false,
          benchmarkDisclaimer:
            'No quantum speedup is claimed. A classical reference solver ran and is stored with this job (see result.classicalComparison).',
        }),
      )
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/optimization/:id — canonical job summary (spec contract). */
  router.get('/:id', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      const job = await c.optimizationJobs.getJobForPrincipal(id, req.principal!)
      res.json(success(c.optimizationJobs.summary(job)))
    } catch (error) {
      next(error)
    }
  })

  return router
}

function jobResult(job: OptimizationJob): OptimizationJob['result'] {
  return job.result
}

/** Map the validated snake_case wire body to the orchestration domain request. */
function toRunOptimizationRequest(body: z.infer<typeof runOptimizationBodySchema>): RunOptimizationRequest {
  return {
    problemType: body.problem_type,
    candidateCount: body.candidate_count,
    maxSensors: body.max_sensors,
    budgetK: body.budget_k,
    forecastReference: body.forecast_reference,
    ...(body.risk_profile !== undefined && { riskProfile: body.risk_profile }),
    executionMode: body.execution_mode,
    hardwareEnabled: body.hardware_enabled,
    backend: body.backend as QuantumBackend,
    shots: body.shots,
    layers: body.layers,
    weights: body.weights,
    normalizeWeights: body.normalize_weights,
    coverageRequirements: body.coverage_requirements.map((requirement) => ({
      metric: requirement.metric,
      minFraction: requirement.min_fraction,
      origin: requirement.origin,
    })),
    ...(body.candidate_locations_reference !== undefined && { candidateLocationsReference: body.candidate_locations_reference }),
  }
}

const STAGE_LABELS: Record<FrontendStageId, string> = {
  input: 'Federated inputs',
  validation: 'Validation',
  qubo: 'QUBO construction',
  hamiltonian: 'Hamiltonian',
  qaoa: 'QAOA execution',
  measurement: 'Measurement',
  decode: 'Decode result',
  constraintValidation: 'Constraint validation',
  benchmark: 'Classical benchmark',
  final: 'Final',
}

const STAGE_ORDER: FrontendStageId[] = [
  'input',
  'validation',
  'qubo',
  'hamiltonian',
  'qaoa',
  'measurement',
  'decode',
  'constraintValidation',
  'benchmark',
  'final',
]

interface PipelineStagePayload {
  id: FrontendStageId
  label: string
  status: StepStatus
  detail: string
  error?: string
}

interface PipelinePayload {
  jobId: string
  status: OptimizationJob['status']
  completed: boolean
  stages: PipelineStagePayload[]
}

/** Fold the 15 backend steps into the stage buckets the frontend renders. */
function pipelinePayload(job: OptimizationJob): PipelinePayload {
  const byStage = new Map<FrontendStageId | 'unmapped', PipelineStep[]>()
  for (const step of job.steps) {
    const key = step.stage
    const bucket = byStage.get(key) ?? []
    bucket.push(step)
    byStage.set(key, bucket)
  }

  const stages: PipelineStagePayload[] = []
  for (const stageId of STAGE_ORDER) {
    const steps = byStage.get(stageId)
    if (!steps || steps.length === 0) continue
    const failed = steps.find((step) => step.status === 'failed')
    const running = steps.find((step) => step.status === 'running')
    const done = steps.filter((step) => step.status === 'done').length
    const status: StepStatus = failed ? 'failed' : running ? 'running' : done === steps.length ? 'done' : 'pending'
    const lastActive = [...steps].reverse().find((step) => step.status !== 'pending')
    stages.push({
      id: stageId,
      label: STAGE_LABELS[stageId],
      status,
      detail: lastActive?.detail ?? `${done}/${steps.length} steps complete`,
      ...(failed?.error !== undefined && { error: failed.error }),
    })
  }

  return {
    jobId: job.id,
    status: job.status,
    completed: job.status === 'completed' || job.status === 'failed' || job.status === 'timed_out',
    stages,
  }
}