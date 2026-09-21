/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

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
  /** The quantum service's job id for the accepted submission (persistence layer). */
  jobId?: string
}

/** Lifecycle statuses the quantum service persists per job. */
export type QuantumLifecycleStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'invalid'

export interface QuantumExecutionResult {
  executionId: string
  /** The quantum service's own job id, when the service surfaces it (persistence layer). */
  jobId?: string
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
  /** Raw objective of the executed outcome, when the quantum service reports one. */
  objectiveValue?: number | null
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
    const data = await this.request<{ execution_id: string; job_id?: string }>('/quantum/optimize', {
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
    return {
      executionId: data.execution_id,
      ...(data.job_id !== undefined && { jobId: data.job_id }),
    }
  }

  async getResult(executionId: string): Promise<QuantumExecutionResult> {
    const data = await this.request<WireExecutionResult>(`/quantum/result/${encodeURIComponent(executionId)}`, undefined)
    if (data.status !== 'completed') {
      // A non-completed job is a structured failure: surface the stable code
      // (e.g. HARDWARE_UNAVAILABLE / AER_UNAVAILABLE) so the orchestrator's
      // fallback ladder — and not the caller — decides what to do next.
      throw new QuantumServiceError(
        data.error?.code ??
          (data.status === 'cancelled' ? 'EXECUTION_CANCELLED' : data.status === 'invalid' ? 'INVALID_EXECUTION' : 'EXECUTION_FAILED'),
        data.status === 'invalid' ? 422 : data.status === 'cancelled' ? 409 : 500,
        data.error?.message ?? `Execution ${executionId} ended with status '${data.status}'`,
        data.error ?? undefined,
      )
    }
    return {
      executionId: data.execution_id,
      ...(data.job_id !== undefined && { jobId: data.job_id }),
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
      ...(data.objective_value !== undefined && { objectiveValue: data.objective_value }),
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
      const headers: Record<string, string> = { Accept: 'application/json' }
      if (body !== undefined) headers['Content-Type'] = 'application/json'
      if (config.QUANTUM_API_TOKEN) headers.Authorization = `Bearer ${config.QUANTUM_API_TOKEN}`
      const response = await fetch(`${this.baseUrl}${path}`, {
        method: body === undefined ? 'GET' : 'POST',
        headers,
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
  job_id?: string
  qubo_id: string
  algorithm: 'qaoa'
  status: QuantumLifecycleStatus
  error?: { code: string; message: string } | null
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
  objective_value?: number | null
}