/**
 * HTTP client for the Quantum FastAPI service (`../quantum-service`).
 *
 * This is the ONLY place the orchestrator couples to the quantum stack. It
 * exposes a typed seam (`QuantumServiceClient`) so tests can inject a fake and
 * force QUBO/QAOA/hardware failures deterministically. All calls carry a
 * timeout; failures surface as `QuantumServiceError` with a stable `code` the
 * orchestrator's fallback policy can act on.
 *
 * Never claims a speedup: results carry `quantumAdvantageClaimed: false`.
 */

import { config } from '../config.ts'
import type {
  CandidateLocation,
  CoverageRequirement,
  MeasurementCount,
  ObjectiveWeights,
  OptimizationProblemType,
  QuantumBackend,
  QuantumExecutionMode,
  QuboDocument,
} from '../types/optimization.ts'

/** The mode actually used to execute (may differ from the requested mode). */
export type ExecutionModeWire = QuantumExecutionMode | 'classical'

export interface CreateQuboInput {
  problemType: OptimizationProblemType
  candidates: CandidateLocation[]
  weights: ObjectiveWeights
  normalizeWeights: boolean
  constraints: {
    maxSensors: number
    budgetK: number | null
    coverageRequirements: CoverageRequirement[]
  }
}

export interface QuboCreated {
  quboId: string
  doc: QuboDocument
}

export interface OptimizeQaoaInput {
  quboId: string
  algorithm: 'qaoa'
  mode: QuantumExecutionMode
  backend: QuantumBackend
  shots: number
  layers: number
  seed?: number
}

export interface OptimizeAccepted {
  executionId: string
}

export interface QuantumExecutionResult {
  executionId: string
  quboId: string
  algorithm: 'qaoa'
  status: 'completed'
  modeRequested: QuantumExecutionMode
  modeUsed: ExecutionModeWire
  backend: QuantumBackend
  simulated: boolean
  device: string | null
  qubitCount: number
  shotCount: number
  measurementCounts: MeasurementCount[]
  topBitstring: string
  energyHistory: { iteration: number; energy: number }[]
  executionTimeMs: number
  quantumAdvantageClaimed: false
}

export interface QuantumServiceClient {
  createQubo(input: CreateQuboInput): Promise<QuboCreated>
  optimize(input: OptimizeQaoaInput): Promise<OptimizeAccepted>
  getResult(executionId: string): Promise<QuantumExecutionResult>
}

/** Structured failure from the quantum service / transport layer. */
export class QuantumServiceError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
    readonly details?: unknown,
  ) {
    super(message)
    this.name = 'QuantumServiceError'
  }
}

type Envelope<T> = {
  success: boolean
  data?: T
  error?: { code?: string; message?: string }
}

class QuantumRequestError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
    readonly details?: unknown,
  ) {
    super(message)
    this.name = 'QuantumRequestError'
  }
}

export class HttpQuantumServiceClient implements QuantumServiceClient {
  private readonly baseUrl = config.QUANTUM_SERVICE_URL.replace(/\/$/, '')
  private readonly timeoutMs = config.QUANTUM_REQUEST_TIMEOUT_MS

  async createQubo(input: CreateQuboInput): Promise<QuboCreated> {
    const data = await this.request<{ qubo_id: string; doc: WireQubo }>('/quantum/qubo', {
      problem_type: input.problemType,
      candidates: input.candidates.map(toWireCandidate),
      weights: input.weights,
      normalize_weights: input.normalizeWeights,
      constraints: {
        max_sensors: input.constraints.maxSensors,
        budget_k: input.constraints.budgetK,
        coverage_requirements: input.constraints.coverageRequirements,
      },
    })
    return { quboId: data.qubo_id, doc: fromWireQubo(data.doc) }
  }

  async optimize(input: OptimizeQaoaInput): Promise<OptimizeAccepted> {
    const data = await this.request<{ execution_id: string }>('/quantum/optimize', {
      qubo_id: input.quboId,
      algorithm: input.algorithm,
      execution: {
        mode: input.mode,
        backend: input.backend,
        shots: input.shots,
        layers: input.layers,
        ...(input.seed !== undefined && { seed: input.seed }),
      },
    })
    return { executionId: data.execution_id }
  }

  async getResult(executionId: string): Promise<QuantumExecutionResult> {
    const data = await this.request<WireExecutionResult>(`/quantum/result/${encodeURIComponent(executionId)}`, undefined)
    return {
      executionId: data.execution_id,
      quboId: data.qubo_id,
      algorithm: data.algorithm,
      status: data.status,
      modeRequested: data.execution.mode_requested,
      modeUsed: data.execution.mode_used,
      backend: data.execution.backend_used,
      simulated: data.execution.simulated,
      device: data.execution.device,
      qubitCount: data.qubit_count,
      shotCount: data.shot_count,
      measurementCounts: data.measurement_counts,
      topBitstring: data.top_bitstring,
      energyHistory: data.energy_history,
      executionTimeMs: data.execution_time_ms,
      quantumAdvantageClaimed: false,
    }
  }

  async health(): Promise<{ online: boolean }> {
    try {
      await this.request<unknown>('/health', undefined, 2500)
      return { online: true }
    } catch {
      return { online: false }
    }
  }

  private async request<T>(path: string, body: unknown | undefined, timeoutMs = this.timeoutMs): Promise<T> {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method: body === undefined ? 'GET' : 'POST',
        headers: { Accept: 'application/json', ...(body !== undefined && { 'Content-Type': 'application/json' }) },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      })
      const envelope = (await response.json().catch(() => null)) as Envelope<T> | null
      if (!response.ok || envelope === null || envelope.success !== true) {
        const code = envelope?.error?.code ?? 'QUANTUM_ERROR'
        const message = envelope?.error?.message ?? `Quantum service returned HTTP ${response.status} for ${path}`
        throw new QuantumRequestError(code, response.status, message, envelope?.error ?? undefined)
      }
      return envelope.data as T
    } catch (error) {
      if (error instanceof QuantumRequestError) {
        throw new QuantumServiceError(error.code, error.status, error.message, error.details)
      }
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new QuantumServiceError('EXECUTION_TIMEOUT', 504, `Quantum service request to ${path} timed out`)
      }
      throw new QuantumServiceError(
        'QUANTUM_UNAVAILABLE',
        503,
        `Quantum service unreachable: ${error instanceof Error ? error.message : String(error)}`,
      )
    } finally {
      clearTimeout(timer)
    }
  }
}

function toWireCandidate(candidate: CandidateLocation) {
  return {
    id: candidate.id,
    name: candidate.name,
    zone: candidate.zone,
    latitude: candidate.latitude,
    longitude: candidate.longitude,
    flood_risk: candidate.floodRisk,
    population_exposure: candidate.populationExposure,
    infrastructure_criticality: candidate.infrastructureCriticality,
    communication_score: candidate.communicationScore,
    sensor_cost_k: candidate.sensorCostK,
    coverage_radius_km: candidate.coverageRadiusKm,
  }
}

interface WireQubo {
  variable_count: number
  variables: string[]
  expression: string
  matrix: number[][]
  offset: number
}

function fromWireQubo(doc: WireQubo): QuboDocument {
  return {
    variableCount: doc.variable_count,
    variables: doc.variables,
    expression: doc.expression,
    matrix: doc.matrix,
    offset: doc.offset,
  }
}

interface WireExecutionResult {
  execution_id: string
  qubo_id: string
  algorithm: 'qaoa'
  status: 'completed'
  execution: {
    mode_requested: QuantumExecutionMode
    mode_used: ExecutionModeWire
    backend_used: QuantumBackend
    simulated: boolean
    device: string | null
  }
  qubit_count: number
  shot_count: number
  measurement_counts: MeasurementCount[]
  top_bitstring: string
  energy_history: { iteration: number; energy: number }[]
  execution_time_ms: number
}