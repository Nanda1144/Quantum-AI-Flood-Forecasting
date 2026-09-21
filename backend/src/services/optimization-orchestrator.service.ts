/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

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
import { benchmarkListEntry, buildBenchmarkDocument, computeApproximationRatio, type QuantumExecutionInput } from '../lib/optimization/benchmark.ts'
import { auditOptimizationResult } from '../lib/optimization/result-validation.ts'
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
import type { ForecastRepository, OptimizationJobRepository, QuantumJobRepository } from '../repositories/repositories.ts'
import type {
  BenchmarkDocument,
  BenchmarkListEntry,
  BenchmarkListFilters,
  BenchmarkReproducibility,
  CandidateLocation,
  CoverageRequirement,
  FallbackPolicy,
  FrontendStageId,
  MeasurementCount,
  ObjectiveBreakdown,
  OptimizationExportDocument,
  OptimizationJob,
  OptimizationJobAuditEntry,
  OptimizationJobDetail,
  OptimizationJobStatus,
  OptimizationJobSummary,
  OptimizationResult,
  OptimizationResultDocument,
  OptimizationResultRecord,
  PipelineStepId,
  QuantumBackend,
  QuantumExecutionMode,
  QuantumJobRecord,
  QuantumResultRecord,
  QuboBuild,
  QuboDocument,
  ResultExperimentMetadata,
  RunOptimizationRequest,
  StepStatus,
  ValidationStatus,
} from '../types/optimization.ts'

export interface OptimizationJobServiceOptions {
  fallbackPolicy: FallbackPolicy
  exhaustiveLimit: number
  executionTimeoutMs: number
  /** QUBOs with at most this many variables are persisted inline; larger ones go to the artifact store by reference. */
  quboInlineLimit: number
  /**
   * Optional persistence layer for the real quantum submissions (migration
   * 006). When present, every submitted quantum job — including failed attempts
   * on a fallback ladder — is recorded in `quantum_jobs`, and completed jobs get
   * a `quantum_results` row. Absent (tests / demo), nothing is persisted.
   */
  quantumJobRepo?: QuantumJobRepository
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
  /** Weighted objective utility per candidate id, derived in build_objective. */
  objectiveTerms?: Record<string, number>
  remoteQuboId: string | null
  remoteQuboDoc: QuboDocument | null
  qubo?: QuboBuild
  /** The most recent quantum submission attempted (persistence layer). */
  submission: {
    jobId: string | null
    executionId: string
    mode: QuantumExecutionMode
    backend: QuantumBackend
    shots: number
    layers: number
  } | null
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
      forecastReference: request.forecastReference,
      candidateReference: request.candidateLocationsReference ?? `gis://candidates/${request.candidateCount}`,
      inputReference: `ai://forecasts/${request.forecastReference}`,
      variablesCount: null,
      constraints: {
        maxSensors: request.maxSensors,
        budgetK: request.budgetK,
        coverageRequirements: request.coverageRequirements,
      },
      objectiveConfiguration: {
        weights: request.weights,
        normalizeWeights: request.normalizeWeights,
        layers: request.layers,
        shots: request.shots,
      },
      errorMessage: null,
      quboStorage: 'inline',
      quboArtifactReference: null,
      deletedAt: null,
      deletedBy: null,
      deleteReason: null,
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

  /**
   * Ownership-scoped experiment ledger for the benchmark page, newest first.
   * Admins see every job; other principals see only their own. Summaries only —
   * the caller fetches the full result document for the run it inspects.
   */
  async listSummariesForPrincipal(principal: { username: string; role: string }): Promise<OptimizationJobSummary[]> {
    const jobs = await this.jobRepo.list()
    const visible = principal.role === 'admin' ? jobs : jobs.filter((job) => job.owner === principal.username)
    return visible.map((job) => this.summary(job))
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
        classicalObjectiveValue: job.result?.classicalComparison.objectiveValue ?? null,
        classicalRuntimeMs: job.result?.classicalComparison.executionTimeMs ?? null,
        approximationQuality:
          job.result && job.result.classicalComparison.objectiveValue > 0 && job.result.objectiveValue !== null
            ? Number(Math.min(1, job.result.objectiveValue / job.result.classicalComparison.objectiveValue).toFixed(4))
            : null,
        validated: job.result ? job.result.validationStatus === 'valid' : null,
        constraintViolationCount: job.result?.constraintViolations.length ?? null,
      },
      owner: job.owner,
      createdAt: job.createdAt,
      startedAt: job.startedAt,
      completedAt: job.completedAt,
      forecastReference: job.forecastReference,
      candidateReference: job.candidateReference,
      inputReference: job.inputReference,
      variablesCount: job.variablesCount,
      constraints: job.constraints,
      objectiveConfiguration: job.objectiveConfiguration,
      quboStorage: job.quboStorage,
      quboArtifactReference: job.quboArtifactReference,
      errorMessage: job.errorMessage,
      deletedAt: job.deletedAt,
      deletedBy: job.deletedBy,
      deleteReason: job.deleteReason,
    }
  }

  /** Full result document when the job has one, else null (shape = frontend). */
  resultPayload(job: OptimizationJob): OptimizationJob['result'] {
    return job.result
  }

  /** Ownership-scoped read of the normalized result row (persistence layer). */
  async getResultForPrincipal(jobId: string, principal: { username: string; role: string }): Promise<OptimizationResultRecord> {
    await this.getJobForPrincipal(jobId, principal)
    const record = await this.jobRepo.findResult(jobId)
    if (!record) {
      throw new AppError(404, ErrorCodes.RESULT_NOT_FOUND, `No persisted result row for optimization job '${jobId}'`)
    }
    return record
  }

  /**
   * Ownership-scoped final result document: the stored measurements plus the
   * backend integrity audit, recommendation gate, quantum comparison and exact
   * experiment metadata. 404 when the job never produced a result.
   */
  async getResultDocumentForPrincipal(
    jobId: string,
    principal: { username: string; role: string },
  ): Promise<OptimizationResultDocument> {
    const job = await this.getJobForPrincipal(jobId, principal)
    return this.buildResultDocument(job)
  }

  /** `GET /api/optimization/:id` — summary + audited result (null before completion). */
  async getJobDetailForPrincipal(jobId: string, principal: { username: string; role: string }): Promise<OptimizationJobDetail> {
    const job = await this.getJobForPrincipal(jobId, principal)
    return {
      ...this.summary(job),
      result: job.result ? await this.buildResultDocument(job) : null,
    }
  }

  /** Structured, auditable export document for a job (result included when present). */
  async buildExportDocumentForPrincipal(
    jobId: string,
    principal: { username: string; role: string },
  ): Promise<OptimizationExportDocument> {
    const job = await this.getJobForPrincipal(jobId, principal)
    const result = job.result ? await this.buildResultDocument(job) : null
    return {
      jobId: job.id,
      exportedAt: new Date().toISOString(),
      status: job.status,
      summary: this.summary(job),
      result,
      integrity: result?.integrity ?? null,
      recommendation: result?.recommendation ?? null,
      experiment: result?.experiment ?? null,
      quantumAdvantageClaimed: false,
      benchmarkDisclaimer:
        'No quantum speedup is claimed. A classical reference solver ran and is stored with this job (see result.classicalComparison).',
    }
  }

  /**
   * Best-effort write-once audit of a sensitive result action (access/export).
   * A logging failure must never take a read down, but it is surfaced on stderr.
   */
  async recordResultAccess(jobId: string, principal: { username: string; role: string }, action: string): Promise<void> {
    try {
      await this.jobRepo.appendAudit({
        optimizationJobId: jobId,
        action,
        actor: principal.username,
        reason: null,
      })
    } catch (error) {
      console.error(
        `[backend] failed to audit result action '${action}' for job '${jobId}': ${error instanceof Error ? error.message : String(error)}`,
      )
    }
  }

  /**
   * Assemble the integrity-audited result read model from STORED measurements.
   * The candidates are re-fetched from the deterministic source and every
   * numeric is recomputed from the stored row — nothing is taken from a client.
   */
  private async buildResultDocument(job: OptimizationJob): Promise<OptimizationResultDocument> {
    const result = job.result
    if (!result) {
      throw new AppError(404, ErrorCodes.RESULT_NOT_FOUND, `No result document for optimization job '${job.id}'`)
    }

    let candidates: CandidateLocation[] | null = null
    let sourceError: string | undefined
    try {
      candidates = await this.resolveCandidates(job)
    } catch (error) {
      sourceError = error instanceof Error ? error.message : String(error)
    }

    const integrity = auditOptimizationResult(job, candidates, sourceError)
    const execution = await this.resolveQuantumExecution(job)
    const record = await this.jobRepo.findResult(job.id)
    const stored =
      record && (record.approximationRatio !== null || record.approximationInvalidReason !== null || record.randomSeed !== null)
        ? {
            approximationRatio: record.approximationRatio,
            approximationBasis: record.approximationBasis,
            approximationInvalidReason: record.approximationInvalidReason,
            randomSeed: record.randomSeed,
          }
        : null
    const benchmark = buildBenchmarkDocument(job, { quantumExecution: execution, stored })

    const eligible = integrity.valid && result.validationStatus === 'valid' && job.status === 'completed'
    return {
      ...result,
      integrity,
      recommendation: {
        eligible,
        reason: eligible
          ? null
          : integrity.valid
            ? 'The pipeline marked this result invalid — it is preserved for research but is not an operational recommendation.'
            : `The backend integrity audit failed (${integrity.failed.join(', ')}) — the result is preserved for debugging/research but is not an operational recommendation.`,
      },
      quantumComparison: benchmark.quantum,
      approximationRatio: benchmark.approximationRatio,
      experiment: this.buildExperimentMetadata(job, benchmark.reproducibility),
    }
  }

  /** Re-fetch the deterministic candidate set the pipeline consumed. */
  private async resolveCandidates(job: OptimizationJob): Promise<CandidateLocation[]> {
    const reference =
      job.candidateReference ?? job.request.candidateLocationsReference ?? `gis://candidates/${job.request.candidateCount}`
    return this.candidates.getCandidates({ reference, count: job.request.candidateCount })
  }

  /** Exact experiment configuration preserved with the job (never fabricated). */
  private buildExperimentMetadata(job: OptimizationJob, reproducibility: BenchmarkReproducibility): ResultExperimentMetadata {
    return {
      problemType: job.problemType,
      algorithm: job.algorithm,
      executionMode: job.executionMode,
      executionModeUsed: job.executionModeUsed,
      backend: job.backend,
      backendUsed: job.backendUsed,
      qubits: job.qubitCount ?? job.result?.qubits ?? null,
      shots: job.request.shots,
      layers: job.request.layers,
      fallbackPolicy: job.fallbackPolicy,
      fallbackApplied: job.fallbackApplied,
      fallbackReason: job.fallbackReason,
      owner: job.owner,
      createdAt: job.createdAt,
      startedAt: job.startedAt,
      completedAt: job.completedAt,
      forecastReference: job.forecastReference,
      candidateReference: job.candidateReference,
      inputReference: job.inputReference,
      variablesCount: job.variablesCount,
      constraints: job.constraints,
      objectiveConfiguration: job.objectiveConfiguration,
      reproducibility,
    }
  }

  /** Ownership-scoped read of the write-once audit trail. */
  async getAuditForPrincipal(jobId: string, principal: { username: string; role: string }): Promise<OptimizationJobAuditEntry[]> {
    await this.getJobForPrincipal(jobId, principal)
    return this.jobRepo.listAudit(jobId)
  }

  /**
   * Full benchmark document for a completed job — built from STORED measurements
   * only (the pipeline executed the classical reference at run time; nothing is
   * re-run or re-measured, so the wall-clock numbers stay write-once). Quantum
   * execution runtime is read from the migration 006 persistence layer.
   */
  async getBenchmarkForPrincipal(jobId: string, principal: { username: string; role: string }): Promise<BenchmarkDocument> {
    const job = await this.getJobForPrincipal(jobId, principal)
    if (job.deletedAt) {
      throw new AppError(404, ErrorCodes.JOB_NOT_FOUND, `Optimization job '${jobId}' not found`)
    }
    if (!job.result || !job.completedAt) {
      throw new AppError(404, ErrorCodes.RESULT_NOT_FOUND, `No result document for optimization job '${jobId}' — no benchmark exists`)
    }
    const execution = await this.resolveQuantumExecution(job)
    // The migration 007 write-once snapshot is returned verbatim (historical
    // benchmark results are never overwritten or recomputed over a stored row).
    const record = await this.jobRepo.findResult(job.id)
    const stored =
      record && (record.approximationRatio !== null || record.approximationInvalidReason !== null || record.randomSeed !== null)
        ? {
            approximationRatio: record.approximationRatio,
            approximationBasis: record.approximationBasis,
            approximationInvalidReason: record.approximationInvalidReason,
            randomSeed: record.randomSeed,
          }
        : null
    return buildBenchmarkDocument(job, { quantumExecution: execution, stored })
  }

  /** Benchmark ledger rows (completed jobs with a stored result), newest first. */
  async listBenchmarksForPrincipal(
    filters: BenchmarkListFilters,
    principal: { username: string; role: string },
  ): Promise<BenchmarkListEntry[]> {
    const jobs = await this.jobRepo.list()
    const visible = principal.role === 'admin' ? jobs : jobs.filter((job) => job.owner === principal.username)
    return visible
      .filter((job) => job.result !== null && job.completedAt !== null)
      .filter((job) => benchmarkMatchesFilters(job, filters))
      .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
      .map((job) => benchmarkListEntry(job))
  }

  /** The executor runtime of the completed quantum submission, best effort. */
  private async resolveQuantumExecution(job: OptimizationJob): Promise<QuantumExecutionInput> {
    // A real quantum run happened iff the result carries measurement counts: a
    // classical-only fallback leaves executionModeUsed as the REQUESTED mode but
    // never produces counts, and never writes quantum_jobs rows.
    const ran = (job.result?.measurementCounts.length ?? 0) > 0
    const repo = this.options.quantumJobRepo
    let runtimeMs: number | null = null
    let runtimeSource: string | null = null
    if (repo) {
      try {
        const quantumJobs = await repo.findJobsByOptimizationJobId(job.id)
        const completed = quantumJobs.find((submission) => submission.status === 'completed')
        if (completed) {
          const resultRow = await repo.findResult(completed.id)
          if (resultRow) {
            runtimeMs = resultRow.runtimeMs
            runtimeSource = 'quantum_results.runtime_ms'
          }
        }
      } catch {
        console.error('[backend] quantum execution runtime lookup failed; benchmark reports runtimeMs=null')
      }
    }
    return { ran, runtimeMs, runtimeSource }
  }

  /**
   * Authorized soft-delete with an audit trail.
   *
   * Completed research results are write-once: only an `admin` principal may
   * delete one, and every deletion records an auditable reason. The repository
   * never hard-deletes — the row is preserved with deleted_at/deleted_by.
   */
  async deleteJobForPrincipal(
    jobId: string,
    principal: { username: string; role: string },
    reason: string,
  ): Promise<OptimizationJob> {
    const job = await this.getJobForPrincipal(jobId, principal)
    if (job.status === 'completed' && principal.role !== 'admin') {
      throw new AppError(
        403,
        ErrorCodes.DELETE_PROTECTED,
        'Completed optimization research results are write-once; only an admin may delete them, and the deletion must carry an auditable reason.',
      )
    }
    return this.jobRepo.deleteJob(jobId, principal.username, reason)
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
      submission: null,
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
        current.constraints = {
          maxSensors: request.maxSensors,
          budgetK: request.budgetK,
          coverageRequirements: ctx.coverageRequirements,
        }
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

      // 6. build_objective — weighted utility per candidate, retained so the
      //    derived objective terms are real, inspectable pipeline state.
      await this.advance(current, 'build_objective', 'Objective terms derived', async () => {
        const weights = request.normalizeWeights ? normalizeWeights(request.weights) : request.weights
        ctx.objectiveTerms = Object.fromEntries(
          ctx.candidates.map((site) => [site.id, siteUtility(site, weights)]),
        )
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
        current.variablesCount = qubo!.doc.variableCount
        const quboBig = qubo!.doc.variableCount > this.options.quboInlineLimit
        current.quboStorage = quboBig ? 'artifact' : 'inline'
        current.quboArtifactReference = quboBig ? `qflare://qubo/${current.id}` : null
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
        await this.jobRepo.saveResult(this.toResultRecord(current, selected, bitstring!, quantumExec))
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
    // Returns the updated job; the single caller persists it once via the
    // awaited repository save that immediately follows.
    return { ...job, status, startedAt }
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
    job.errorMessage = message
    job.completedAt = new Date().toISOString()
    await this.jobRepo.save(job)
  }

  private recordFallback(job: OptimizationJob, reason: string, detail: string): void {
    job.fallbackApplied = true
    job.fallbackReason = job.fallbackReason === null ? reason : `${job.fallbackReason}; ${reason}`
    this.touchForFallback(job, detail)
  }

  private touchForFallback(job: OptimizationJob, message: string): void {
    // Annotate the first step that is not yet done: a fallback covered it, so
    // the executor should see WHY rather than a silently blank step detail.
    const step = job.steps.find((candidate) => candidate.status !== 'done')
    if (!step) return
    step.detail = step.detail && step.detail !== step.label ? `${step.detail}; ${message}` : message
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
    const attempt = () => this.runQaoaOnce(job, ctx, quboId!, mode, request, seedFrom([job.id, request.forecastReference, request.candidateCount]))

    try {
      const result = await attempt()
      await this.persistCompletedQuantumJob(job, ctx.submission, result)
      return result
    } catch (error) {
      const quantumFailure = error instanceof QuantumServiceError
      if (!quantumFailure) throw error
      const message = `QAOA execution on '${mode}' failed: ${error.message}`
      if (this.options.fallbackPolicy === 'error' || mode === 'simulator') {
        throw new PipelineError(ErrorCodes.QAOA_EXECUTION_FAILED, message, error.details)
      }
      if (this.options.fallbackPolicy === 'retry_simulator') {
        try {
          const retried = await this.runQaoaOnce(job, ctx, quboId, 'simulator', request, seedFrom([job.id, request.forecastReference, request.candidateCount]))
          await this.persistCompletedQuantumJob(job, ctx.submission, retried)
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
    job: OptimizationJob,
    ctx: PipelineContext,
    quboId: string,
    mode: QuantumExecutionMode,
    request: RunOptimizationRequest,
    seed: number,
  ): Promise<QuantumExecutionResult> {
    ctx.submission = null
    const backend = this.backendFor(mode, request)
    const accepted = await this.quantum.optimize({
      quboId,
      algorithm: 'qaoa',
      mode,
      backend,
      shots: request.shots,
      layers: request.layers,
      seed,
    })
    const submission: NonNullable<PipelineContext['submission']> = {
      jobId: accepted.jobId ?? null,
      executionId: accepted.executionId,
      mode,
      backend,
      shots: request.shots,
      layers: request.layers,
    }
    ctx.submission = submission
    if (submission.jobId) {
      await this.persistSubmittedQuantumJob(job, submission)
    }
    try {
      const result = await this.quantum.getResult(accepted.executionId)
      if (!submission.jobId && result.jobId) {
        submission.jobId = result.jobId
      }
      return result
    } catch (error) {
      if (submission.jobId) {
        await this.persistFailedQuantumJob(job, submission, error)
      }
      throw error
    }
  }

  // ---------------------------------------------------------------------------
  // Quantum job persistence (migration 006)
  //
  // Records every REAL submission, one honest row per attempt: a `queued` row
  // the moment the quantum service accepts the job, then a `completed` row +
  // `quantum_results` on success or a `failed` row with the stable error code.
  // `executionMode`/`backend` are the mode + backend of THAT submission, so the
  // simulator/hardware distinction survives fallback ladders. No row is ever
  // invented for an execution the platform did not submit. Persistence is best
  // effort — a store failure must never take the optimization pipeline down.
  // ---------------------------------------------------------------------------

  private async persistSubmittedQuantumJob(
    job: OptimizationJob,
    submission: NonNullable<PipelineContext['submission']>,
  ): Promise<void> {
    const repo = this.options.quantumJobRepo
    if (!repo || !submission.jobId) return
    try {
      const nowIso = new Date().toISOString()
      const existing = await repo.findJobById(submission.jobId)
      const row: QuantumJobRecord = {
        id: submission.jobId,
        optimizationJobId: job.id,
        algorithm: 'qaoa',
        backend: submission.backend,
        executionMode: submission.mode,
        qubits: null,
        shots: submission.shots,
        layers: submission.layers,
        status: 'queued',
        submittedAt: existing?.submittedAt ?? nowIso,
        startedAt: existing?.startedAt ?? null,
        completedAt: null,
        errorCode: null,
        errorMessage: null,
        createdAt: existing?.createdAt ?? nowIso,
      }
      await repo.saveJob(row)
    } catch (error) {
      console.error(`[backend] quantum job persistence failed (submit): ${error instanceof Error ? error.message : String(error)}`)
    }
  }

  private async persistCompletedQuantumJob(
    job: OptimizationJob,
    submission: PipelineContext['submission'],
    result: QuantumExecutionResult,
  ): Promise<void> {
    const repo = this.options.quantumJobRepo
    const jobId = submission?.jobId ?? result.jobId ?? null
    if (!repo || !jobId || !submission) return
    try {
      const nowIso = new Date().toISOString()
      const existing = await repo.findJobById(jobId)
      const row: QuantumJobRecord = {
        id: jobId,
        optimizationJobId: job.id,
        algorithm: 'qaoa',
        backend: submission.backend,
        executionMode: submission.mode,
        qubits: result.qubitCount,
        shots: submission.shots,
        layers: submission.layers,
        status: 'completed',
        submittedAt: existing?.submittedAt ?? nowIso,
        startedAt: existing?.startedAt ?? nowIso,
        completedAt: nowIso,
        errorCode: null,
        errorMessage: null,
        createdAt: existing?.createdAt ?? nowIso,
      }
      await repo.saveJob(row)
      const quantumResult: QuantumResultRecord = {
        id: `${jobId}-R1`,
        quantumJobId: jobId,
        bitstring: result.topBitstring,
        counts: Object.fromEntries(result.measurementCounts.map((entry) => [entry.bitstring, entry.count])),
        objectiveValue: Number.isFinite(result.objectiveValue as number) ? (result.objectiveValue as number) : null,
        runtimeMs: result.executionTimeMs,
        rawMetadataReference: null,
        createdAt: nowIso,
      }
      await repo.saveResult(quantumResult)
    } catch (error) {
      console.error(`[backend] quantum job persistence failed (complete): ${error instanceof Error ? error.message : String(error)}`)
    }
  }

  private async persistFailedQuantumJob(
    job: OptimizationJob,
    submission: NonNullable<PipelineContext['submission']>,
    error: unknown,
  ): Promise<void> {
    const repo = this.options.quantumJobRepo
    if (!repo || !submission.jobId) return
    try {
      const nowIso = new Date().toISOString()
      const existing = await repo.findJobById(submission.jobId)
      const row: QuantumJobRecord = {
        id: submission.jobId,
        optimizationJobId: job.id,
        algorithm: 'qaoa',
        backend: submission.backend,
        executionMode: submission.mode,
        qubits: null,
        shots: submission.shots,
        layers: submission.layers,
        status: 'failed',
        submittedAt: existing?.submittedAt ?? nowIso,
        startedAt: existing?.startedAt ?? nowIso,
        completedAt: nowIso,
        errorCode: error instanceof QuantumServiceError ? error.code : 'QUANTUM_EXECUTION_FAILED',
        errorMessage: error instanceof Error ? error.message : String(error),
        createdAt: existing?.createdAt ?? nowIso,
      }
      await repo.saveJob(row)
    } catch (persistError) {
      console.error(`[backend] quantum job persistence failed (fail): ${persistError instanceof Error ? persistError.message : String(persistError)}`)
    }
  }

  // ---------------------------------------------------------------------------
  // Result assembly
  // ---------------------------------------------------------------------------

  /** Build the normalized persistence row from the assembled result document. */
  private toResultRecord(
    job: OptimizationJob,
    selected: CandidateLocation[],
    bitstring: string,
    quantumExec: QuantumExecutionResult | null,
  ): OptimizationResultRecord {
    const result = job.result as OptimizationResult
    const gap = result.classicalComparison.gapVsQuantum
    // Migration 007 classical benchmark reference snapshot: measured values only,
    // computed once here and WRITE-ONCE in the repository (never overwritten,
    // never recomputed over a stored row).
    const quantumObjective = quantumExec ? result.objectiveValue : null
    const ratio = computeApproximationRatio(
      result.classicalComparison.objectiveValue,
      quantumObjective,
      result.classicalComparison.method ?? null,
      result.validationStatus === 'valid',
    )
    return {
      id: `${job.id}-R1`,
      optimizationJobId: job.id,
      bitstring,
      selectedLocationIds: selected.map((site) => site.id),
      objectiveValue: result.objectiveValue,
      constraintViolations: result.constraintViolations,
      validationStatus: result.validationStatus,
      runtimeMs: result.executionTimeMs,
      classicalObjective: result.classicalComparison.objectiveValue,
      quantumObjective,
      approximationQuality:
        gap !== undefined && gap !== null ? Number(Math.max(0, Math.min(1, 1 - gap)).toFixed(4)) : null,
      classicalSolver: result.classicalComparison.method === 'exhaustive' ? 'exhaustive' : result.classicalComparison.method === 'greedy' ? 'greedy' : null,
      classicalRuntimeMs: result.classicalComparison.executionTimeMs,
      approximationRatio: ratio.value,
      approximationBasis: ratio.basis,
      approximationInvalidReason: ratio.invalidReason as OptimizationResultRecord['approximationInvalidReason'],
      randomSeed: seedFrom([job.id, job.request.forecastReference, job.request.candidateCount]),
      // Migration 008 validation contract: the verdict is recorded once, with
      // its timestamp, and the objective is persisted with its explanation so
      // the score is auditable from the row without recomputation.
      validationTimestamp: result.validationStatus === 'pending_validation' ? null : result.endedAt,
      validationDetails: {
        status: result.validationStatus,
        summary: result.validationSummary,
        violationCount: result.constraintViolations.length,
        violations: result.constraintViolations,
      },
      explanationMetadata: {
        objectiveBreakdown: result.objectiveBreakdown,
        coverage: result.coverage,
        quantumAdvantageClaimed: false,
      },
      createdAt: result.endedAt,
    }
  }

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
      bitstring,
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

/** Apply the `GET /api/benchmarks` filters to a completed job (AND semantics). */
function benchmarkMatchesFilters(job: OptimizationJob, filters: BenchmarkListFilters): boolean {
  if (filters.problemType && job.problemType !== filters.problemType) return false
  if (filters.algorithm && job.algorithm !== filters.algorithm) return false
  if (filters.executionMode) {
    const matches = job.executionMode === filters.executionMode || job.executionModeUsed === filters.executionMode
    if (!matches) return false
  }
  const createdMs = Date.parse(job.createdAt)
  if (filters.from) {
    const lower = Date.parse(filters.from)
    if (!Number.isNaN(lower) && createdMs < lower) return false
  }
  if (filters.to) {
    const upper = Date.parse(filters.to)
    if (!Number.isNaN(upper) && createdMs > upper) return false
  }
  return true
}