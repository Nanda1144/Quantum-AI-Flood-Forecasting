/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Router, type RequestHandler } from 'express'
import { z } from 'zod'
import type { Container } from '../container.ts'
import { AppError, ErrorCodes, success } from '../envelope.ts'
import { authenticate, authorize } from '../middleware/authorize.ts'
import { optimizationRunLimiter } from '../middleware/rate-limit.ts'
import {
  benchmarkListQuerySchema,
  jobDeletionBodySchema,
  optimizationBodySchema,
  optimizationInputsQuerySchema,
  optimizationJobParamsSchema,
  runOptimizationBodySchema,
} from '../middleware/schemas.ts'
import { validate } from '../middleware/validate.ts'
import { config } from '../config.ts'
import { defaultConstraints } from '../services/gis/candidate-store.ts'
import type {
  BenchmarkListFilters,
  CandidateLocation,
  CoverageRequirement,
  FrontendStageId,
  OptimizationJob,
  OptimizationJobStatus,
  OptimizationProblemType,
  PipelineStep,
  QuboBuild,
  QuboDocument,
  QuboStorage,
  QuantumBackend,
  RunOptimizationRequest,
  StepStatus,
} from '../types/optimization.ts'

/**
 * Shared handler for the filterable benchmark ledger (newest first). Used by
 * both `GET /api/optimization/benchmarks` and the external alias
 * `GET /api/benchmarks`. Completed jobs with a stored result only — the list is
 * built from persisted measurements, never recomputed or fabricated.
 */
function benchmarkListHandler(c: Container): RequestHandler {
  return async (req, res, next) => {
    try {
      const query = req.validated!.query as z.infer<typeof benchmarkListQuerySchema>
      const filters: BenchmarkListFilters = {
        ...(query.problem_type !== undefined && { problemType: query.problem_type }),
        ...(query.algorithm !== undefined && { algorithm: query.algorithm }),
        ...(query.execution_mode !== undefined && { executionMode: query.execution_mode }),
        ...(query.from !== undefined && { from: query.from }),
        ...(query.to !== undefined && { to: query.to }),
      }
      res.json(success(await c.optimizationJobs.listBenchmarksForPrincipal(filters, req.principal!)))
    } catch (error) {
      next(error)
    }
  }
}

/** Standalone benchmark ledger route (external contract: `GET /api/benchmarks`). */
export function benchmarkSummaryRouter(c: Container): Router {
  const router = Router()
  router.use(authenticate(c.auth, config.AUTH_ENABLED))
  router.get('/api/benchmarks', authorize('viewer'), validate({ query: benchmarkListQuerySchema }), benchmarkListHandler(c))
  return router
}

/**
 * Optimization orchestration API — the Nanda command surface.
 *
 *   POST /api/optimization/run        validate + queue a pipeline job (202).
 *   GET  /api/optimization/:id        job summary (status, algorithm, mode, …).
 *   GET  /api/optimization/inputs     federated GIS/planning inputs for the UI.
 *   GET  /api/optimization/jobs       experiment ledger (summaries, newest first).
 *   GET  /api/optimization/jobs/:id/pipeline|result|qubo|classical|export
 *                                     fine-grained read surfaces (frontend adapter).
 *   POST /api/optimization/:id/benchmark
 *   GET  /api/optimization/:id/benchmark
 *                                     execute-or-retrieve / read the classical
 *                                     reference benchmark document (raw stored
 *                                     measurements; the frontend explains them).
 *   GET  /api/optimization/benchmarks benchmark ledger, filterable (problem
 *                                     type, date, algorithm, execution mode).
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

  /**
   * GET /api/optimization/jobs/:id/result — full, integrity-audited result
   * document. Legacy path kept for the frontend adapter; delegates to the same
   * read model as `GET /api/optimization/:id/result`.
   */
  router.get('/jobs/:id/result', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      const document = await c.optimizationJobs.getResultDocumentForPrincipal(id, req.principal!)
      await c.optimizationJobs.recordResultAccess(id, req.principal!, 'result_viewed')
      res.json(success(document))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/optimization/jobs/:id/qubo — served QUBO formulation (full visualization payload). */
  router.get('/jobs/:id/qubo', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      const job = await c.optimizationJobs.getJobForPrincipal(id, req.principal!)
      const build = job.qubo ?? (await c.jobRepo.findQuboBuild(job.id))
      const doc = build?.doc ?? jobResult(job)?.qubo ?? null
      res.json(success(await quboFormulationPayload(c, job, build, doc)))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/optimization/jobs/:id/results — normalized persistence row. */
  router.get('/jobs/:id/results', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      res.json(success(await c.optimizationJobs.getResultForPrincipal(id, req.principal!)))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/optimization/jobs/:id/audit — write-once delete-protection trail. */
  router.get('/jobs/:id/audit', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      res.json(success(await c.optimizationJobs.getAuditForPrincipal(id, req.principal!)))
    } catch (error) {
      next(error)
    }
  })

  /**
   * DELETE /api/optimization/jobs/:id — authorized soft-delete with an audit
   * trail. Completed research results are write-once: only an admin may delete
   * them and a reason is always required. The row is never hard-deleted.
   */
  router.delete(
    '/jobs/:id',
    authorize('operator'),
    validate({ params: optimizationJobParamsSchema, body: jobDeletionBodySchema }),
    async (req, res, next) => {
      try {
        const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
        const body = req.validated!.body as z.infer<typeof jobDeletionBodySchema>
        const job = await c.optimizationJobs.deleteJobForPrincipal(id, req.principal!, body.reason)
        res.json(
          success({
            jobId: job.id,
            status: 'deleted',
            softDelete: {
              deletedAt: job.deletedAt,
              deletedBy: job.deletedBy,
              deleteReason: job.deleteReason,
            },
            audit: { action: 'soft_deleted', actor: job.deletedBy, reason: job.deleteReason, createdAt: job.deletedAt },
          }),
        )
      } catch (error) {
        next(error)
      }
    },
  )

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

  /** GET /api/optimization/jobs/:id/export — signed, auditable result document (legacy path). */
  router.get('/jobs/:id/export', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      const document = await c.optimizationJobs.buildExportDocumentForPrincipal(id, req.principal!)
      await c.optimizationJobs.recordResultAccess(id, req.principal!, 'result_exported')
      res.json(success(document))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/optimization/jobs — the researcher's experiment ledger, newest first. */
  router.get('/jobs', authorize('viewer'), async (req, res, next) => {
    try {
      res.json(success(await c.optimizationJobs.listSummariesForPrincipal(req.principal!)))
    } catch (error) {
      next(error)
    }
  })

  /**
   * POST /api/optimization/:id/benchmark — execute-or-retrieve the classical
   * reference benchmark. The pipeline executes the reference solver at run time
   * and the measurements are write-once (re-running would fabricate fresh wall
   * clocks), so POST is the idempotent command that returns the executed
   * benchmark document; 409 while the job has not produced one yet.
   */
  router.post('/:id/benchmark', authorize('operator'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      await c.optimizationJobs.getJobForPrincipal(id, req.principal!)
      try {
        const document = await c.optimizationJobs.getBenchmarkForPrincipal(id, req.principal!)
        res.json(success(document))
      } catch (error) {
        if (error instanceof AppError && error.code === ErrorCodes.RESULT_NOT_FOUND) {
          throw new AppError(
            409,
            ErrorCodes.JOB_NOT_COMPLETE,
            'The classical reference benchmark is computed as part of the optimization pipeline and this job has not produced one yet — poll the job, then retry.',
          )
        }
        throw error
      }
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/optimization/:id/benchmark — the stored classical reference benchmark. */
  router.get('/:id/benchmark', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      res.json(success(await c.optimizationJobs.getBenchmarkForPrincipal(id, req.principal!)))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/optimization/benchmarks — filterable benchmark ledger (newest first). */
  router.get('/benchmarks', authorize('viewer'), validate({ query: benchmarkListQuerySchema }), benchmarkListHandler(c))

  /**
   * GET /api/optimization/:id/result — final result read model: selected
   * locations, bitstring, objective, constraint violations, validation status,
   * runtime, classical + quantum comparison and the exact experiment metadata.
   * Every result is integrity-audited server-side before it is served.
   */
  router.get('/:id/result', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      const document = await c.optimizationJobs.getResultDocumentForPrincipal(id, req.principal!)
      await c.optimizationJobs.recordResultAccess(id, req.principal!, 'result_viewed')
      res.json(success(document))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/optimization/:id/export — structured, auditable result export. */
  router.get('/:id/export', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      const document = await c.optimizationJobs.buildExportDocumentForPrincipal(id, req.principal!)
      await c.optimizationJobs.recordResultAccess(id, req.principal!, 'result_exported')
      res.json(success(document))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/optimization/:id — canonical job detail: summary + audited result. */
  router.get('/:id', authorize('viewer'), validate({ params: optimizationJobParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof optimizationJobParamsSchema>
      const detail = await c.optimizationJobs.getJobDetailForPrincipal(id, req.principal!)
      res.json(success(detail))
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

interface ConstraintRowPayload {
  key: string
  name: string
  configuredLimit: number
  penalty: number | null
  penaltyKind: 'qubo' | 'post_decode' | null
  status: 'satisfied' | 'violated' | 'unknown'
  detail: string
}

interface VariableDetailPayload {
  index: number
  id: string
  candidateId: string
  name: string | null
  zone: string | null
  selected: boolean
  semantic: string
}

interface PenaltyTermPayload {
  key: string
  name: string
  formula: string
  scale: number | null
  detail: string
}

/**
 * Assemble the full QUBO formulation the visualization page renders — the
 * backend is the single source of truth, so nothing is re-derived in React.
 *
 * Every numeric the UI needs comes from the stored QuboBuild (inline row or
 * artifact store) or the job's persisted result: no QUBO math happens here or
 * in the browser.
 */
async function quboFormulationPayload(
  c: Container,
  job: OptimizationJob,
  build: QuboBuild | null,
  doc: QuboDocument | null,
): Promise<{
  jobId: string
  problemType: OptimizationProblemType
  algorithm: string
  status: OptimizationJobStatus
  createdAt: string
  /** Frontend load state: `valid` | `unavailable` | `invalid`. */
  available: 'valid' | 'unavailable' | 'invalid'
  storage: QuboStorage | null
  inline: boolean
  variableCount: number | null
  variables: string[]
  expression: string
  matrix: number[][]
  artifactReference: string | null
  offset: number
  linear: number[] | null
  quadratic: number[][] | null
  penaltyScale: number | null
  summary: {
    variables: number | null
    linearTerms: number | null
    quadraticTerms: number | null
    constraints: number | null
    penaltyStrength: number | null
  }
  constraints: ConstraintRowPayload[]
  penalties: PenaltyTermPayload[]
  objective: {
    target: 'minimize'
    expression: string
    explanation: string
  }
  variablesDetail: VariableDetailPayload[]
  bitstring: string | null
  selectedVariableIds: string[]
  hasResult: boolean
  validationStatus: string | null
  validationSummary: string | null
}> {
  const result = jobResult(job)
  const bitstring = result?.bitstring ?? null
  const violations = new Set((result?.constraintViolations ?? []).map((v) => v.code))
  const variableCount = job.variablesCount ?? doc?.variableCount ?? null
  const variables = doc?.variables ?? []
  const linear = build?.linear ?? null
  const quadratic = build?.quadratic ?? null
  const penaltyScale = build?.penaltyScale ?? null
  const matrix = doc?.matrix ?? []
  const offset = doc?.offset ?? 0
  const request = job.request
  const budgetK = request.budgetK

  // Availability state for the page: a well-formed stored matrix is what the
  // visualization needs. Unavailable = the job never produced a QUBO (still
  // queued, failed before construct_qubo); invalid = stored matrix is malformed.
  let available: 'valid' | 'unavailable' | 'invalid' = 'unavailable'
  const n = variableCount ?? 0
  if (doc?.matrix && n > 0) {
    const wellFormed =
      doc.matrix.length === n &&
      doc.matrix.every((row) => row.length === 2 * n && row.every((value) => Number.isFinite(value)))
    available = wellFormed ? 'valid' : 'invalid'
  }

  // Candidate semantics are re-fetched from the same deterministic store/key the
  // pipeline used — safe because generation is a pure function of the reference.
  let candidateById = new Map<string, CandidateLocation>()
  try {
    const reference = request.candidateLocationsReference ?? `gis://candidates/${request.candidateCount}`
    const candidates = await c.candidates.getCandidates({ reference, count: request.candidateCount })
    for (const candidate of candidates) candidateById.set(candidate.id, candidate)
  } catch {
    candidateById = new Map()
  }

  const variablesDetail: VariableDetailPayload[] = variables.map((id, index) => {
    const candidate = candidateById.get(id)
    return {
      index,
      id,
      candidateId: id,
      name: candidate?.name ?? null,
      zone: candidate?.zone ?? null,
      selected: bitstring ? bitstring[index] === '1' : false,
      semantic: candidate ? `${candidate.name} · ${candidate.zone}` : `Candidate site ${id}`,
    }
  })

  const selectedVariableIds = bitstring
    ? variables.filter((_, index) => bitstring[index] === '1')
    : []

  const statusFor = (code: string): ConstraintRowPayload['status'] => {
    if (!result) return 'unknown'
    return violations.has(code) ? 'violated' : 'satisfied'
  }

  const constraints: ConstraintRowPayload[] = []
  constraints.push({
    key: 'sensor_limit',
    name: 'Sensor limit',
    configuredLimit: request.maxSensors,
    penalty: penaltyScale,
    penaltyKind: penaltyScale !== null ? 'qubo' : null,
    status: statusFor('SENSOR_LIMIT_EXCEEDED'),
    detail: `Cardinality penalty P·(Σx − M)² with P = penaltyScale and M = ${request.maxSensors}`,
  })
  if (budgetK !== null) {
    const budgetScale = penaltyScale !== null ? penaltyScale / Math.max(1, budgetK) : null
    constraints.push({
      key: 'budget',
      name: 'Deployment budget',
      configuredLimit: budgetK,
      penalty: budgetScale,
      penaltyKind: budgetScale !== null ? 'qubo' : null,
      status: statusFor('BUDGET_EXCEEDED'),
      detail: `Budget penalty scale = penaltyScale / budgetK (${penaltyScale ?? 'n/a'} / ${budgetK})`,
    })
  }
  for (const requirement of job.constraints?.coverageRequirements ?? request.coverageRequirements) {
    const metric = requirement.metric.toUpperCase()
    constraints.push({
      key: `coverage_${metric}`,
      name: `Coverage: ${requirement.metric} ≥ ${Math.round(requirement.minFraction * 100)}%`,
      configuredLimit: requirement.minFraction,
      penalty: null,
      penaltyKind: 'post_decode',
      status: statusFor(`COVERAGE_${metric}_BELOW_MINIMUM`),
      detail: `${requirement.origin} — enforced after measurement (decode), not as a QUBO penalty`,
    })
  }

  const penalties: PenaltyTermPayload[] = []
  if (penaltyScale !== null) {
    penalties.push({
      key: 'cardinality',
      name: 'Sensor limit penalty',
      formula: `P·(Σxᵢ − M)²`,
      scale: penaltyScale,
      detail: 'Diagonal += P, off-diagonal += 2P, linear −= 2MP; keeps the solution to M selected sensors.',
    })
    if (budgetK !== null) {
      const budgetScale = penaltyScale / Math.max(1, budgetK)
      penalties.push({
        key: 'budget',
        name: 'Budget penalty',
        formula: `(P/B)·(Σ cᵢ·xᵢ − B)²`,
        scale: Number(budgetScale.toFixed(6)),
        detail: `Weighted by sensor cost cᵢ and the ${budgetK}k budget; discourages exceeding the spend cap.`,
      })
    }
  }

  const explanation =
    'Minimize xᵀQx over binary decision variables xᵢ (1 = sensor deployed at site i, 0 = not). ' +
    'The quadratic term Qᵢⱼ (i≠j) couples pairs of sites, the diagonal combines linear utilities with ' +
    'penalty terms, and the appended column carries the linear coefficients and the constant offset. ' +
    'Penalty terms enforce the operator limits; coverage floors are validated after decode, not in the QUBO.'

  return {
    jobId: job.id,
    problemType: job.problemType,
    algorithm: job.algorithm,
    status: job.status,
    createdAt: job.createdAt,
    available,
    storage: job.quboStorage,
    inline: job.quboStorage === 'inline',
    variableCount,
    variables,
    expression: doc?.expression ?? '',
    matrix,
    artifactReference: job.quboArtifactReference,
    offset,
    linear,
    quadratic,
    penaltyScale,
    summary: {
      variables: variableCount,
      linearTerms: linear?.filter((v) => Math.abs(v) > 1e-9).length ?? null,
      quadraticTerms: quadratic ? quadratic.reduce((count, row, i) => count + row.slice(i).filter((v) => Math.abs(v) > 1e-9).length, 0) : null,
      constraints: constraints.length,
      penaltyStrength: penaltyScale,
    },
    constraints,
    penalties,
    objective: {
      target: 'minimize',
      expression: 'xᵀQx',
      explanation,
    },
    variablesDetail,
    bitstring,
    selectedVariableIds,
    hasResult: result !== null,
    validationStatus: job.validationStatus ?? result?.validationStatus ?? null,
    validationSummary: job.validationSummary ?? result?.validationSummary ?? null,
  }
}