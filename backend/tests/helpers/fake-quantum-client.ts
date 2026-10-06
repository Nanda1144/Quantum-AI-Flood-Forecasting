/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Fake quantum FastAPI client for orchestration tests.
 *
 * Deterministic by construction: QUBOs are built with the same backend math the
 * orchestrator uses and the default decode is the greedy (feasible) solution,
 * so the happy path always passes constraint validation. Knobs inject failures
 * exactly where the fallback policy must act:
 *
 *   - `quboError`            → QUBO generation failure (createQubo throws).
 *   - `optimizeErrorFor`     → per-mode QAOA/hardware failure (optimize throws).
 *   - `resultErrorFor`       → per-mode post-submission failure (getResult throws;
 *                              the service accepted the job, then failed) —
 *                              mirrors real executor down/abort behavior.
 *   - `resultOverrides`      → corrupt the decoded outcome (bad bitstring, …).
 *
 * Since a real service persists a job id per accepted submission, optimize()
 * hands back a fresh job id (execution id → job id) and every later result for
 * that execution carries the same id, which the persistence tests rely on.
 */

import { QuantumServiceError, type CreateQuboInput, type OptimizeQaoaInput, type OptimizeAccepted, type QuantumExecutionResult, type QuantumJobStatusDocument, type QuantumLifecycleStatus, type QuantumServiceClient, type QuboCreated } from '../../src/clients/quantum-service.client.ts'
import { buildQubo, greedyDecode } from '../../src/lib/optimization/qubo.ts'
import type { CandidateLocation, QuantumBackend, QuantumExecutionMode, RunOptimizationRequest } from '../../src/types/optimization.ts'

export type OptimizeFailureRule = (mode: QuantumExecutionMode, backend: QuantumBackend) => Error | null
export type ResultFailureRule = (mode: QuantumExecutionMode, backend: QuantumBackend) => Error | null

export class FakeQuantumServiceClient implements QuantumServiceClient {
  quboError: Error | null = null
  optimizeErrorFor: OptimizeFailureRule = () => null
  resultErrorFor: ResultFailureRule = () => null
  /** When false, optimize() returns no jobId and getResult() supplies it. */
  jobIdFromOptimize = true
  resultOverrides: Partial<Omit<QuantumExecutionResult, 'executionId' | 'quboId' | 'algorithm' | 'status' | 'jobId'>> = {}
  /**
   * Lifecycle statuses to serve from getStatus(), one per call (shifted FIFO).
   * When empty, the first getStatus() reports `completed` (success) or `failed`
   * (when resultErrorFor matches), mirroring a service that already finished.
   */
  statusSequence: QuantumLifecycleStatus[] = []
  /** When true, getStatus() never resolves — the runJob wall clock owns timeout. */
  statusHang = false

  createQuboCalls = 0
  optimizeCalls: OptimizeQaoaInput[] = []
  getStatusCalls = 0

  private quboInput: CreateQuboInput | null = null
  private optimizeInput: OptimizeQaoaInput | null = null
  /** execution id → the quantum service's job id for that submission. */
  private jobIds = new Map<string, string>()

  async createQubo(input: CreateQuboInput): Promise<QuboCreated> {
    this.createQuboCalls += 1
    this.quboInput = input
    if (this.quboError) throw this.quboError
    const request = requestFromQuboInput(input)
    const qubo = buildQubo(request, input.candidates)
    return { quboId: `qubo-${this.createQuboCalls}`, doc: qubo.doc }
  }

  async optimize(input: OptimizeQaoaInput): Promise<OptimizeAccepted> {
    this.optimizeCalls.push(input)
    this.optimizeInput = input
    const failure = this.optimizeErrorFor(input.mode, input.backend)
    if (failure) throw failure
    const executionId = `exec-${this.optimizeCalls.length}`
    const jobId = `jb-${this.optimizeCalls.length}`
    this.jobIds.set(executionId, jobId)
    return this.jobIdFromOptimize ? { executionId, jobId } : { executionId }
  }

  async getStatus(jobId: string): Promise<QuantumJobStatusDocument> {
    this.getStatusCalls += 1
    if (this.statusHang) return new Promise<never>(() => {})
    const mode = this.optimizeInput?.mode ?? 'simulator'
    const backend = this.optimizeInput?.backend ?? 'qflare_simulator_statevector'
    const timestamp = '2026-09-16T09:00:00.000Z'
    const statusDocument = (
      status: QuantumLifecycleStatus,
      error: { code: string; message: string } | null,
    ): QuantumJobStatusDocument => ({
      jobId,
      status,
      algorithm: 'qaoa',
      modeRequested: mode,
      modeUsed: mode,
      backendRequested: backend,
      backendUsed: backend,
      qubitCount: this.quboInput?.candidates.length ?? 0,
      shotCount: this.optimizeInput?.shots ?? 1024,
      layers: this.optimizeInput?.layers ?? 2,
      submittedAt: timestamp,
      startedAt: status === 'queued' ? null : timestamp,
      completedAt: status === 'queued' || status === 'running' ? null : timestamp,
      cancellable: status === 'queued' || status === 'running',
      cancelRequested: false,
      error,
    })

    const override = this.statusSequence.shift()
    if (override !== undefined) {
      return statusDocument(
        override,
        override === 'completed'
          ? null
          : {
              code: override === 'invalid' ? 'INVALID_EXECUTION_RESULT' : override === 'cancelled' ? 'EXECUTION_CANCELLED' : 'AER_EXECUTION_FAILED',
              message: `quantum service reported lifecycle status '${override}'`,
            },
      )
    }
    const failure = this.resultErrorFor(mode, backend)
    if (failure) {
      return statusDocument('failed', {
        code: failure instanceof QuantumServiceError ? failure.code : 'EXECUTION_FAILED',
        message: failure.message,
      })
    }
    return statusDocument('completed', null)
  }

  async getResult(executionId: string): Promise<QuantumExecutionResult> {
    const input = this.quboInput
    const candidates = input?.candidates ?? []
    const mode = this.optimizeInput?.mode ?? 'simulator'
    const backend = this.optimizeInput?.backend ?? 'qflare_simulator_statevector'
    const failure = this.resultErrorFor(mode, backend)
    if (failure) throw failure
    const request = input ? requestFromQuboInput(input) : null
    const topBitstring = request ? greedyDecode(request, candidates).bitstring : '0'.repeat(candidates.length)

    const base: QuantumExecutionResult = {
      executionId,
      jobId: this.jobIds.get(executionId),
      quboId: input ? `qubo-${this.createQuboCalls}` : 'qubo-1',
      algorithm: 'qaoa',
      status: 'completed',
      modeRequested: mode,
      modeUsed: mode,
      backend,
      simulated: mode === 'simulator',
      device: null,
      qubitCount: candidates.length,
      shotCount: this.optimizeInput?.shots ?? 1024,
      measurementCounts: [{ bitstring: topBitstring, count: 728 }],
      topBitstring,
      energyHistory: [{ iteration: 1, energy: -1.42 }, { iteration: 2, energy: -1.41 }],
      executionTimeMs: 4,
      objectiveValue: -1.42,
      quantumAdvantageClaimed: false,
    }
    return { ...base, ...this.resultOverrides }
  }

  /** Convenience: fail optimize for a specific mode (e.g. hardware down). */
  failMode(mode: QuantumExecutionMode): void {
    this.optimizeErrorFor = (candidateMode) =>
      candidateMode === mode
        ? new QuantumServiceError(mode === 'ibm_hardware' ? 'HARDWARE_UNAVAILABLE' : 'AER_UNAVAILABLE', 503, `executor '${candidateMode}' unavailable`)
        : null
  }

  /** Convenience: fail getResult for a specific mode (service accepted, then failed). */
  failResult(mode: QuantumExecutionMode): void {
    this.resultErrorFor = (candidateMode, candidateBackend) =>
      candidateMode === mode
        ? new QuantumServiceError(
            candidateBackend === 'ibm_kyiv' ? 'HARDWARE_EXECUTION_FAILED' : 'AER_EXECUTION_FAILED',
            500,
            `executor '${candidateBackend}' failed after accepting the job`,
          )
        : null
  }

  /** Reset all bookkeeping (execution→job id map, counters, captured inputs). */
  resetQuantumPersistence(): void {
    this.jobIds.clear()
    this.createQuboCalls = 0
    this.optimizeCalls = []
    this.getStatusCalls = 0
    this.quboInput = null
    this.optimizeInput = null
  }
}

/** Rebuild the domain request the backend math consumes from a QUBO input. */
function requestFromQuboInput(input: CreateQuboInput): RunOptimizationRequest {
  const candidates: CandidateLocation[] = input.candidates
  return {
    problemType: input.problemType,
    candidateCount: candidates.length,
    maxSensors: input.constraints.maxSensors,
    budgetK: input.constraints.budgetK,
    forecastReference: 'FC-20260916-0001',
    executionMode: 'simulator',
    hardwareEnabled: false,
    backend: 'qflare_simulator_statevector',
    shots: 1024,
    layers: 2,
    weights: input.weights,
    normalizeWeights: input.normalizeWeights,
    coverageRequirements: input.constraints.coverageRequirements,
  }
}