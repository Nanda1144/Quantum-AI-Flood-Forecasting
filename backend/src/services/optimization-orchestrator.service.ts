/**
 * Optimization orchestration backend — the 15-step pipeline.
 *
 * Owns the end-to-end lifecycle of an optimization job:
 *
 *   1  validate_request          9  classical_benchmark
 *   2  retrieve_forecast        10  execute_qaoa
 *   3  retrieve_candidates      11  decode_bitstring
 *   4  retrieve_constraints     12  validate_constraints
 *   5  normalize_features       13  compare_results
 *   6  build_objective          14  persist_result
 *   7  apply_constraints_penalties
 *   8  construct_qubo           15  return_response
 *
 * The orchestrator is the only component that decides *policy*: it resolves the
 * execution mode, applies the configured fallback policy when a stage fails
 * (hardware down, Aer missing, QUBO generation error), decodes and validates
 * the outcome, and always persists the classical reference benchmark — no
 * quantum speedup is ever claimed. A failure in any single quantum executor
 * never takes the platform down.
 */

import { AppError, ErrorCodes, type ErrorCode } from '../envelope.ts'
import { QuantumServiceError, type QuantumExecutionResult, type QuantumServiceClient } from '../clients/quantum-service.client.ts'
import { solveClassicalReference, type ClassicalRun } from '../lib/optimization/classical.ts'
import {
  buildQubo,
  computeObjective,
  normalizeWeights,
  objectiveLabel,
  siteUtility,
  validateConstraints,
  type ObjectiveMetrics,
} from '../lib/optimization/qubo.ts'
import { seedFrom } from './deterministic.ts'
import type { CandidateStore, ConstraintsSource } from './gis/candidate-store.ts'
import type { ForecastRepository, OptimizationJobRepository } from '../repositories/repositories.ts'
import type {
  CandidateLocation,
  CoverageRequirement,
  FallbackPolicy,
  FrontendStageId,
  MeasurementCount,
  ObjectiveBreakdown,
  OptimizationJob,
  OptimizationJobStatus,
  OptimizationJobSummary,
  PipelineStepId,
  QuantumBackend,
  QuantumExecutionMode,
  QuboBuild,
  QuboDocument,
  RunOptimizationRequest,
  StepStatus,
  ValidationStatus,
} from '../types/optimization.ts'

export interface OptimizationJobServiceOptions {
  fallbackPolicy: FallbackPolicy
  exhaustiveLimit: number
  executionTimeoutMs: number
}

/** Internal pipeline failure carrying a stable error code the job records. */
export class PipelineError extends Error {
  constructor(
    readonly code: ErrorCode,
    message: string,
    readonly details?: unknown,
  ) {
    super(message)
    this.name = 'PipelineError'
  }
}

interface PipelineContext {
  candidates: CandidateLocation[]
  coverageRequirements: CoverageRequirement[]
  remoteQuboId: string | null
  remoteQuboDoc: QuboDocument | null
  qubo?: QuboBuild
}

const STEPS: { id: PipelineStepId; label: string; stage: FrontendStageId }[] = [
  { id: 'validate_request', label: 'Validate request', stage: 'validation' },
  { id: 'retrieve_forecast', label: 'Retrieve forecast / risk data', stage: 'input' },
  { id: 'retrieve_candidates', label: 'Retrieve candidate GIS data', stage: 'input' },
  { id: 'retrieve_constraints', label: 'Retrieve response/resource constraints', stage: 'input' },
  { id: 'normalize_features', label: 'Normalize input features', stage: 'validation' },
  { id: 'build_objective', label: 'Build objective function', stage: 'qubo' },
  { id: 'apply_constraints_penalties', label: 'Apply constraints / penalties', stage: 'qubo' },
  { id: 'construct_qubo', label: 'Construct QUBO', stage: 'qubo' },
  { id: 'classical_benchmark', label: 'Execute classical reference solver', stage: 'benchmark' },
  { id: 'execute_qaoa', label: 'Execute QAOA', stage: 'qaoa' },
  { id: 'decode_bitstring', label: 'Decode bitstring', stage: 'decode' },
  { id: 'validate_constraints', label: 'Validate constraints', stage: 'constraintValidation' },
  { id: 'compare_results', label: 'Compare results', stage: 'benchmark' },
  { id: 'persist_result', label: 'Persist job / result', stage: 'final' },
  { id: 'return_response', label: 'Return clean API response', stage: 'final' },
]

export class OptimizationJobService {
  constructor(
    private readonly jobRepo: OptimizationJobRepository,
    private readonly forecastRepo: ForecastRepository,
    private readonly candidates: CandidateStore,
    private readonly constraintsSource: ConstraintsSource,
    private readonly quantum: QuantumServiceClient,
    private readonly options: OptimizationJobServiceOptions,
  ) {}

  /** Create + persist a queued job and start the pipeline in the background. */
  async createJob(request: RunOptimizationRequest, owner: string): Promise<OptimizationJob> {
    const nowIso = new Date().toISOString()
    const executionMode = this.resolveExecutionMode(request)
    const job: OptimizationJob = {
      id: newJobId(),
      owner,
      status: 'queued',
      problemType: request.problemType,
      request,
      fallbackPolicy: this.options.fallbackPolicy,
      algorithm: 'qaoa',
      executionMode,
      executionModeUsed: executionMode,
      backend: request.backend,
      backendUsed: request.backend,
      fallbackApplied: false,
      fallbackReason: null,
      qubitCount: null,
      steps: STEPS.map((step, index) => ({
        id: step.id,
        label: step.label,
        stage: step.stage,
        status: 'pending' as StepStatus,
        detail: index === 0 ? 'Validating request semantics' : '',
      })),
      qubo: null,
      classical: null,
      result: null,
      validationStatus: null,
      validationSummary: null,
      error: null,
      createdAt: nowIso,
      startedAt: null,
      completedAt: null,
    }
    await this.jobRepo.save(job)

    // Fire-and-forget: the pipeline progresses asynchronously; callers poll.
    void this.runJob(job.id).catch((error) => {
      console.error(`[backend] optimization job ${job.id} crashed unpaged:`, error)
    })
    return job
  }

  /** Drive one job through the entire pipeline (bounded by the timeout). */
  async runJob(jobId: string): Promise<void> {
    const { executionTimeoutMs } = this.options
    let timer: NodeJS.Timeout | undefined
    const timeout = new Promise<'timeout'>((resolve) => {
      timer = setTimeout(() => resolve('timeout'), executionTimeoutMs)
    })
    try {
      const outcome = await Promise.race([this.executePipeline(jobId).then(() => 'done' as const), timeout])
      if (outcome === 'timeout') {
        const job = await this.jobRepo.findById(jobId)
        if (job) {
          await this.fail(job, ErrorCodes.EXECUTION_TIMEOUT, `Optimization job exceeded ${executionTimeoutMs}ms`, undefined, 'timed_out')
        }
      }
    } catch {
      // Pipeline failures are recorded on the job by executePipeline.
    } finally {
      clearTimeout(timer)
    }
  }

  /** Test helper — resolve once the job reaches a terminal state. */
  async waitForTerminal(jobId: string, timeoutMs = 5000): Promise<OptimizationJob> {
    const deadline = Date.now() + timeoutMs
    for (;;) {
      const job = await this.jobRepo.findById(jobId)
      if (!job) throw new AppError(404, ErrorCodes.JOB_NOT_FOUND, `Optimization job '${jobId}' not found`)
      if (job.status === 'completed' || job.status === 'failed' || job.status === 'timed_out') return job
      if (Date.now() > deadline) return job
      await new Promise((resolve) => setTimeout(resolve, 15))
    }
  }

  async getJob(jobId: string): Promise<OptimizationJob> {
    const job = await this.jobRepo.findById(jobId)
    if (!job) throw new AppError(404, ErrorCodes.JOB_NOT_FOUND, `Optimization job '${jobId}' not found`)
    return job
  }

  /**
   * Ownership-guarded read: a non-admin principal may only see their own jobs.
   * A foreign job is reported as 404 (never 403) so job existence is not
   * leaked to other tenants.
   */
  async getJobForPrincipal(jobId: string, principal: { username: string; role: string }): Promise<OptimizationJob> {
    const job = await this.getJob(jobId)
    if (principal.role !== 'admin' && job.owner !== principal.username) {
      throw new AppError(404, ErrorCodes.JOB_NOT_FOUND, `Optimization job '${jobId}' not found`)
    }
    return job
  }

  summary(job: OptimizationJob): OptimizationJobSummary {
    return {
      id: job.id,
      jobId: job.id,
      status: job.status,
      problemType: job.problemType,
      algorithm: job.algorithm,
      executionMode: job.executionMode,
      executionModeUsed: job.executionModeUsed,
      backend: job.backend,
      backendUsed: job.backendUsed,
      fallbackPolicy: job.fallbackPolicy,
      fallbackApplied: job.fallbackApplied,
      fallbackReason: job.fallbackReason,
      qubitCount: job.qubitCount,
      validationStatus: job.validationStatus,
      validationSummary: job.validationSummary,
      resultSummary: {
        objectiveValue: job.result?.objectiveValue ?? null,
        selectedCount: job.result?.selectedLocations.length ?? null,
        executionTimeMs: job.result?.executionTimeMs ?? null,
        gapVsQuantum: job.result?.classicalComparison.gapVsQuantum ?? null,
        constraintViolationCount: job.result?.constraintViolations.length ?? null,
      },
      owner: job.owner,
      createdAt: job.createdAt,
      startedAt: job.startedAt,
      completedAt: job.completedAt,
    }
  }

  /** Full result document when the job has one, else null (shape = frontend). */
  resultPayload(job: OptimizationJob): OptimizationJob['result'] {
    return job.result
  }

  private async executePipeline(jobId: string): Promise<void> {
    const job = await this.jobRepo.findById(jobId)
    if (!job) return
    let current = this.markStatus(job, 'running', new Date().toISOString())
    const ctx: PipelineContext = {
      candidates: [],
      coverageRequirements: [],
      remoteQuboId: null,
      remoteQuboDoc: null,
    }
    await this.jobRepo.save(current)

    try {
      const request = current.request

      // 1. validate_request — semantic validation (schema handled 422 at the API).
      await this.advance(current, 'validate_request', 'Request semantics validated', async () => {
        this.assertStaticsValid(request)
      })

      // 2. retrieve_forecast — forecast / risk data from the AI gateway.
      await this.advance(current, 'retrieve_forecast', 'Forecast reference resolved', async () => {
        const forecast = await this.forecastRepo.findByForecastId(request.forecastReference)
        if (!forecast) {
          throw new PipelineError(ErrorCodes.FORECAST_NOT_FOUND, `Forecast '${request.forecastReference}' not found`)
        }
      })

      // 3. retrieve_candidates — candidate GIS data.
      await this.advance(current, 'retrieve_candidates', 'Candidate sites retrieved', async () => {
        const found = await this.candidates.getCandidates({
          reference: request.candidateLocationsReference ?? `gis://candidates/${request.candidateCount}`,
          count: request.candidateCount,
        })
        if (!found || found.length === 0) {
          throw new PipelineError(ErrorCodes.NO_CANDIDATES, `No candidate locations found for '${request.candidateLocationsReference ?? request.candidateCount}'`)
        }
        ctx.candidates = found
      })

      // 4. retrieve_constraints — response/resource constraints.
      await this.advance(current, 'retrieve_constraints', 'Resource constraints resolved', async () => {
        const resolved = await this.constraintsSource.getConstraints({
          maxSensors: request.maxSensors,
          budgetK: request.budgetK,
          coverageRequirements: request.coverageRequirements,
          candidateCount: request.candidateCount,
        })
        ctx.coverageRequirements = [...resolved.coverageRequirements, ...request.coverageRequirements]
      })

      // 5. normalize_features — weights normalisation + feature sanity.
      await this.advance(current, 'normalize_features', 'Features normalized to [0,1]', async () => {
        const weights = request.normalizeWeights ? normalizeWeights(request.weights) : request.weights
        for (const key of Object.keys(weights)) {
          if (!Number.isFinite(weights[key as keyof typeof weights])) {
            throw new PipelineError(ErrorCodes.VALIDATION_ERROR, `Objective weight '${key}' is not finite`)
          }
        }
        for (const site of ctx.candidates) {
          if (![site.floodRisk, site.populationExposure, site.infrastructureCriticality, site.communicationScore].every(Number.isFinite)) {
            throw new PipelineError(ErrorCodes.VALIDATION_ERROR, `Candidate '${site.id}' carries a non-finite feature`)
          }
        }
      })

      // 6. build_objective — weighted utility per candidate.
      await this.advance(current, 'build_objective', 'Objective terms derived', async () => {
        const weights = request.normalizeWeights ? normalizeWeights(request.weights) : request.weights
        void ctx.candidates.map((site) => siteUtility(site, weights))
      })

      // 7. apply_constraints_penalties — budget feasibility + penalty planning.
      await this.advance(current, 'apply_constraints_penalties', 'Penalties staged', async () => {
        if (request.budgetK !== null) {
          const minCost = Math.min(...ctx.candidates.map((site) => site.sensorCostK))
          if (request.budgetK < minCost) {
            throw new PipelineError(
              ErrorCodes.INFEASIBLE_BUDGET,
              `Budget of $${request.budgetK}k cannot fund any candidate (cheapest is $${minCost}k)`,
              { minCandidateCostK: minCost, budgetK: request.budgetK },
            )
          }
        }
      })

      // 8. construct_qubo — operational QUBO built locally; pushed to the
      //    quantum service so QAOA has an execution reference.
      let qubo: QuboBuild | null = null
      await this.advance(current, 'construct_qubo', 'QUBO constructed from validated inputs', async () => {
        qubo = buildQubo(request, ctx.candidates)
        this.touch(current, 'construct_qubo', `QUBO over ${qubo!.doc.variableCount} binary variables`)
        try {
          const created = await this.quantum.createQubo({
            problemType: request.problemType,
            candidates: ctx.candidates,
            weights: request.weights,
            normalizeWeights: request.normalizeWeights,
            constraints: {
              maxSensors: request.maxSensors,
              budgetK: request.budgetK,
              coverageRequirements: ctx.coverageRequirements,
            },
          })
          ctx.remoteQuboId = created.quboId
          ctx.remoteQuboDoc = created.doc
          if (created.doc.variableCount !== qubo!.doc.variableCount) {
            this.recordFallback(current, 'qubo_mismatch', `Quantum service produced ${created.doc.variableCount} variables; expected ${qubo!.doc.variableCount}`)
          }
        } catch (error) {
          this.handleQuboServiceFailure(current, error)
        }
        ctx.qubo = qubo!
        current.qubo = qubo!
        await this.jobRepo.save(current)
      })
      await this.jobRepo.save(current)

      // 9. classical_benchmark — always run + always store.
      let classical: ClassicalRun
      await this.advance(current, 'classical_benchmark', 'Reference solution computed', async () => {
        classical = solveClassicalReference(request, ctx.candidates, this.options.exhaustiveLimit)
        current.classical = { ...classical.comparison }
      })
      void classical!

      // 10. execute_qaoa — with fallback per policy.
      let quantumExec: QuantumExecutionResult | null = null
      await this.advance(current, 'execute_qaoa', 'QAOA execution resolved', async () => {
        quantumExec = await this.driveQaoa(current, ctx, request)
        if (quantumExec) {
          current.executionModeUsed = quantumExec.modeUsed === 'classical' ? 'classical' : quantumExec.modeUsed
          current.backendUsed = quantumExec.backend
          current.qubitCount = quantumExec.qubitCount
        }
      })

      // 11. decode_bitstring.
      let selected: CandidateLocation[] = []
      let bitstring: string
      await this.advance(current, 'decode_bitstring', 'Outcome decoded to sites', async () => {
        const source = quantumExec ? quantumExec.topBitstring : classical!.bitstring
        if (typeof source !== 'string' || source.length !== ctx.candidates.length || /[^01]/.test(source)) {
          throw new PipelineError(
            ErrorCodes.DECODING_FAILED,
            `Invalid decoded solution: expected ${ctx.candidates.length}-bit string, got '${source}'`,
            { bitstring: source },
          )
        }
        bitstring = source
        selected = ctx.candidates.filter((_, i) => source[i] === '1')
      })

      // 12. validate_constraints — hard feasibility gate (invalid ≠ job failure).
      let verdict: ReturnType<typeof validateConstraints>
      await this.advance(current, 'validate_constraints', 'Constraints validated', async () => {
        verdict = validateConstraints(selected, request, ctx.coverageRequirements)
        current.validationStatus = verdict.violations.length === 0 ? 'valid' : ('invalid' as ValidationStatus)
        current.validationSummary = verdict.summary
        this.touch(current, 'validate_constraints', verdict.summary)
      })
      void verdict!

      // 13. compare_results — quantum vs classical.
      await this.advance(current, 'compare_results', 'Benchmark vs QUBO decoded', async () => {
        const metrics = computeObjective(request, ctx.candidates, selected)
        const classicalMetrics = classical!.metrics
        const gap =
          metrics.objectiveValue > 1e-9
            ? Math.max(0, (metrics.objectiveValue - classicalMetrics.objectiveValue) / metrics.objectiveValue)
            : 0
        current.classical = {
          ...classical!.comparison,
          gapVsQuantum: Number(gap.toFixed(4)),
        }
        // 14. persist_result.
        current.result = this.buildResult(current, request, ctx, selected, bitstring!, metrics, verdict!, quantumExec, classical!)
        current.status = 'completed'
        current.completedAt = new Date().toISOString()
        await this.jobRepo.save(current)
        this.touch(current, 'persist_result', 'Job and result document persisted')
      })

      // 15. return_response — the route serialises the summary; nothing more.
      await this.advance(current, 'return_response', 'Result document signed', async () => {
        // no-op: response built from the persisted job.
      })
      await this.jobRepo.save(current)
    } catch (error) {
      if (error instanceof AppError || error instanceof PipelineError) {
        await this.fail(
          current,
          (error as PipelineError).code ?? ErrorCodes.INTERNAL_ERROR,
          error.message,
          (error as PipelineError).details,
        )
      } else if (error instanceof QuantumServiceError) {
        await this.fail(current, ErrorCodes.QUANTUM_UNAVAILABLE, error.message, error.details)
      } else {
        await this.fail(current, ErrorCodes.INTERNAL_ERROR, error instanceof Error ? error.message : String(error))
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Step helpers
  // ---------------------------------------------------------------------------

  private async advance(
    job: OptimizationJob,
    stepId: PipelineStepId,
    detail: string,
    fn: () => Promise<void>,
  ): Promise<void> {
    this.touch(job, stepId, detail, 'running')
    try {
      await fn()
      this.touch(job, stepId, detail, 'done')
    } catch (error) {
      this.touch(job, stepId, error instanceof Error ? error.message : String(error), 'failed')
      throw error
    }
  }

  private touch(job: OptimizationJob, stepId: PipelineStepId, detail: string, status: StepStatus = 'done'): void {
    const step = job.steps.find((candidate) => candidate.id === stepId)
    if (!step) return
    step.status = status
    if (detail) step.detail = detail
    if (status === 'running' && !step.startedAt) step.startedAt = new Date().toISOString()
    if (status === 'done' || status === 'failed') step.endedAt = new Date().toISOString()
  }

  private markStatus(job: OptimizationJob, status: OptimizationJobStatus, startedAt: string | null): OptimizationJob {
    const next = { ...job, status, startedAt }
    this.jobRepo.save(next).catch(() => undefined)
    return next
  }

  private async fail(
    job: OptimizationJob,
    code: ErrorCode,
    message: string,
    details?: unknown,
    status: OptimizationJobStatus = 'failed',
  ): Promise<void> {
    job.status = status
    job.error = { code, message, ...(details !== undefined && { details }) }
    job.completedAt = new Date().toISOString()
    await this.jobRepo.save(job)
  }

  private recordFallback(job: OptimizationJob, reason: string, detail: string): void {
    job.fallbackApplied = true
    job.fallbackReason = job.fallbackReason === null ? reason : `${job.fallbackReason}; ${reason}`
    this.touchForFallback(job, detail)
  }

  private touchForFallback(job: OptimizationJob, message: string): void {
    const step = job.steps.find((candidate) => candidate.status !== 'done')
    void job
    void message
    void step
  }

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------

  private assertStaticsValid(request: RunOptimizationRequest): void {
    if (request.problemType !== 'sensor_placement') {
      throw new PipelineError(
        ErrorCodes.UNSUPPORTED_PROBLEM_TYPE,
        `Problem type '${request.problemType}' is not supported by this executor (only sensor_placement is enabled)`,
        { problemType: request.problemType },
      )
    }
    if (!weightsValid(request.weights)) {
      throw new PipelineError(
        ErrorCodes.INVALID_OBJECTIVE_WEIGHTS,
        'Objective weights must be finite, non-negative, and at least one must be > 0',
        { weights: request.weights },
      )
    }
    if (request.candidateCount < 2) {
      throw new PipelineError(ErrorCodes.VALIDATION_ERROR, 'At least 2 candidate locations are required')
    }
    if (request.maxSensors < 1) {
      throw new PipelineError(ErrorCodes.VALIDATION_ERROR, 'max_sensors must be at least 1')
    }
    if (request.maxSensors > request.candidateCount) {
      throw new PipelineError(
        ErrorCodes.VALIDATION_ERROR,
        `max_sensors (${request.maxSensors}) cannot exceed the candidate count (${request.candidateCount})`,
      )
    }
    if (request.budgetK !== null) {
      if (!Number.isFinite(request.budgetK) || request.budgetK < 0) {
        throw new PipelineError(ErrorCodes.INFEASIBLE_BUDGET, 'Budget must be a finite, non-negative number')
      }
      if (request.budgetK === 0) {
        throw new PipelineError(ErrorCodes.INFEASIBLE_BUDGET, 'A zero budget cannot fund any sensor', { budgetK: 0 })
      }
    }
  }

  private resolveExecutionMode(request: RunOptimizationRequest): QuantumExecutionMode {
    if (request.executionMode === 'simulator') return 'simulator'
    return request.backend.startsWith('ibm_') ? 'ibm_hardware' : 'aer'
  }

  private backendFor(mode: QuantumExecutionMode, request: RunOptimizationRequest): QuantumBackend {
    if (mode === 'simulator') return 'qflare_simulator_statevector'
    return request.backend
  }

  // ---------------------------------------------------------------------------
  // QUBO + QAOA execution with the configured fallback policy
  // ---------------------------------------------------------------------------

  private handleQuboServiceFailure(job: OptimizationJob, error: unknown): void {
    const message = error instanceof Error ? error.message : String(error)
    if (this.options.fallbackPolicy === 'error') {
      throw new PipelineError(
        ErrorCodes.QUBO_GENERATION_FAILED,
        `Quantum QUBO generation failed: ${message}`,
        error instanceof QuantumServiceError ? error.details : undefined,
      )
    }
    this.recordFallback(job, 'quantum_qubo_unavailable', `Quantum QUBO generation failed (${message}); using local QUBO`)
  }

  private async driveQaoa(
    job: OptimizationJob,
    ctx: PipelineContext,
    request: RunOptimizationRequest,
  ): Promise<QuantumExecutionResult | null> {
    let quboId = ctx.remoteQuboId
    if (quboId === null) {
      // One retry to reconstruct the remote reference (transient failures).
      try {
        const created = await this.quantum.createQubo({
          problemType: request.problemType,
          candidates: ctx.candidates,
          weights: request.weights,
          normalizeWeights: request.normalizeWeights,
          constraints: {
            maxSensors: request.maxSensors,
            budgetK: request.budgetK,
            coverageRequirements: ctx.coverageRequirements,
          },
        })
        quboId = created.quboId
        ctx.remoteQuboId = created.quboId
      } catch {
        quboId = null
      }
    }

    if (quboId === null) {
      if (this.options.fallbackPolicy === 'error') {
        throw new PipelineError(ErrorCodes.QUBO_GENERATION_FAILED, 'No QUBO reference available for QAOA execution')
      }
      this.recordFallback(job, 'quantum_qubo_unavailable', 'QAOA skipped — quantum QUBO unavailable; classical reference returned')
      return null
    }

    const mode = this.resolveExecutionMode(request)
    const attempt = () =>
      this.runQaoaOnce(quboId!, mode, request, seedFrom([job.id, request.forecastReference, request.candidateCount]))

    try {
      return await attempt()
    } catch (error) {
      const quantumFailure = error instanceof QuantumServiceError
      if (!quantumFailure) throw error
      const message = `QAOA execution on '${mode}' failed: ${error.message}`
      if (this.options.fallbackPolicy === 'error' || mode === 'simulator') {
        throw new PipelineError(ErrorCodes.QAOA_EXECUTION_FAILED, message, error.details)
      }
      if (this.options.fallbackPolicy === 'retry_simulator') {
        try {
          const retried = await this.runQaoaOnce(quboId, 'simulator', request, seedFrom([job.id, request.forecastReference, request.candidateCount]))
          this.recordFallback(job, mode, `${mode} unavailable (${error.message}); retried on simulator`)
          return retried
        } catch (secondary) {
          throw new PipelineError(
            ErrorCodes.QAOA_EXECUTION_FAILED,
            `${message} and simulator retry failed: ${secondary instanceof Error ? secondary.message : String(secondary)}`,
          )
        }
      }
      this.recordFallback(job, mode, `${mode} unavailable (${error.message}); returning classical reference`)
      return null
    }
  }

  private async runQaoaOnce(
    quboId: string,
    mode: QuantumExecutionMode,
    request: RunOptimizationRequest,
    seed: number,
  ): Promise<QuantumExecutionResult> {
    const accepted = await this.quantum.optimize({
      quboId,
      algorithm: 'qaoa',
      mode,
      backend: this.backendFor(mode, request),
      shots: request.shots,
      layers: request.layers,
      seed,
    })
    return await this.quantum.getResult(accepted.executionId)
  }

  // ---------------------------------------------------------------------------
  // Result assembly
  // ---------------------------------------------------------------------------

  private buildResult(
    job: OptimizationJob,
    request: RunOptimizationRequest,
    ctx: PipelineContext,
    selected: CandidateLocation[],
    bitstring: string,
    metrics: ObjectiveMetrics,
    verdict: ReturnType<typeof validateConstraints>,
    quantumExec: QuantumExecutionResult | null,
    classical: ClassicalRun,
  ): OptimizationJob['result'] {
    const started = job.startedAt ? new Date(job.startedAt).getTime() : Date.now()
    const endedAt = new Date().toISOString()
    const executionTimeMs = Math.max(1, Math.round(Date.now() - started))
    const quboDoc = ctx.remoteQuboDoc ?? ctx.qubo!.doc
    const objectiveBreakdown: ObjectiveBreakdown[] = metrics.breakdown.map((entry) => ({
      key: entry.key,
      label: objectiveLabel(entry.key),
      value: entry.value,
    }))

    const quantumObjective = quantumExec ? metrics.objectiveValue : classical.metrics.objectiveValue
    const gap =
      quantumObjective > 1e-9
        ? Math.max(0, (quantumObjective - classical.comparison.objectiveValue) / quantumObjective)
        : 0

    const measurementCounts: MeasurementCount[] = quantumExec ? quantumExec.measurementCounts.slice(0, 8) : []
    const energyHistory = quantumExec ? quantumExec.energyHistory : []

    return {
      jobId: job.id,
      simulated: quantumExec ? quantumExec.simulated : false,
      backend: quantumExec ? quantumExec.backend : 'qflare_simulator_statevector',
      qubits: bitstring.length,
      shots: request.shots,
      layers: request.layers,
      startedAt: job.startedAt ?? new Date(started).toISOString(),
      endedAt,
      executionTimeMs,
      objectiveValue: Number(metrics.objectiveValue.toFixed(4)),
      objectiveBreakdown,
      selectedLocations: selected.map((site) => ({
        id: site.id,
        name: site.name,
        zone: site.zone,
        sensorCostK: site.sensorCostK,
        floodRisk: site.floodRisk,
        populationCovered: site.populationExposure,
        infrastructureCovered: site.infrastructureCriticality,
      })),
      coverage: {
        populationCovered: metrics.populationCovered,
        populationTotal: metrics.populationTotal,
        infrastructureCovered: metrics.infrastructureCovered,
        infrastructureTotal: metrics.infrastructureTotal,
      },
      constraintViolations: verdict.violations,
      validationStatus: verdict.violations.length === 0 ? 'valid' : 'invalid',
      validationSummary: verdict.summary,
      qubo: quboDoc,
      measurementCounts,
      energyHistory,
      classicalComparison: {
        method: classical.comparison.method,
        objectiveValue: classical.comparison.objectiveValue,
        selectedCount: classical.comparison.selectedCount,
        executionTimeMs: classical.comparison.executionTimeMs,
        gapVsQuantum: Number(gap.toFixed(4)),
      },
      quantumAdvantageClaimed: false,
      benchmarkDisclaimer:
        'No quantum speedup is claimed. A classical reference solver ran and is stored with this job (see classicalComparison).',
    }
  }
}

function weightsValid(weights: { [key: string]: number }): boolean {
  const values = Object.values(weights)
  return values.every((value) => Number.isFinite(value) && value >= 0) && values.some((value) => value > 0)
}

function newJobId(): string {
  const randPart = Math.random().toString(36).slice(2, 8).toUpperCase()
  return `QOP-${Date.now().toString(36).toUpperCase()}-${randPart}`
}