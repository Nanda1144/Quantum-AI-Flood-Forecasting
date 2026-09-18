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
 *   - `resultOverrides`      → corrupt the decoded outcome (bad bitstring, …).
 */

import { QuantumServiceError, type CreateQuboInput, type OptimizeQaoaInput, type OptimizeAccepted, type QuantumExecutionResult, type QuantumServiceClient, type QuboCreated } from '../../src/clients/quantum-service.client.ts'
import { buildQubo, greedyDecode } from '../../src/lib/optimization/qubo.ts'
import type { CandidateLocation, QuantumBackend, QuantumExecutionMode, RunOptimizationRequest } from '../../src/types/optimization.ts'

export type OptimizeFailureRule = (mode: QuantumExecutionMode, backend: QuantumBackend) => Error | null

export class FakeQuantumServiceClient implements QuantumServiceClient {
  quboError: Error | null = null
  optimizeErrorFor: OptimizeFailureRule = () => null
  resultOverrides: Partial<Omit<QuantumExecutionResult, 'executionId' | 'quboId' | 'algorithm' | 'status'>> = {}

  createQuboCalls = 0
  optimizeCalls: OptimizeQaoaInput[] = []

  private quboInput: CreateQuboInput | null = null
  private optimizeInput: OptimizeQaoaInput | null = null

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
    return { executionId: `exec-${this.optimizeCalls.length}` }
  }

  async getResult(executionId: string): Promise<QuantumExecutionResult> {
    const input = this.quboInput
    const candidates = input?.candidates ?? []
    const mode = this.optimizeInput?.mode ?? 'simulator'
    const backend = this.optimizeInput?.backend ?? 'qflare_simulator_statevector'
    const request = input ? requestFromQuboInput(input) : null
    const topBitstring = request ? greedyDecode(request, candidates).bitstring : '0'.repeat(candidates.length)

    const base: QuantumExecutionResult = {
      executionId,
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