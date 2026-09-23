/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Production optimization adapter.
 *
 * Talks to the platform's optimization gateway over HTTP:
 *
 *   POST /api/optimization/run        {problem_type, weights, …} → {jobId} (202)
 *   GET  /api/optimization/jobs/:id/pipeline                    → {stages[], completed}
 *   GET  /api/optimization/jobs/:id/result                      → OptimizationResult
 *   GET  /api/optimization/jobs/:id/qubo                        → QuboDocument
 *   GET  /api/optimization/jobs/:id/classical                   → ClassicalComparison
 *   GET  /api/optimization/jobs/:id/export                      → signed document
 *   GET  /api/optimization/inputs?candidateCount=24&forecast=…   → {candidates, constraints, …}
 *
 * Every response arrives wrapped in the backend envelope
 * (`{ success, data, timestamp }`) and is unwrapped here; the run body is
 * converted to the snake_case wire contract. Any failure surfaces as a
 * clearly-labelled ApiError so production ops never mistake a stub for
 * execution.
 */

import type {
  CandidateLocation,
  CoverageRequirement,
  ObjectiveWeights,
  OptimizeRequest,
  OptimizationResult,
  PipelineStageId,
  PipelineUpdate,
  QuantumBackend,
} from '../../types/optimization'
import type { OptimizationAdapter, OptimizationInputs, ProblemInputsRequest } from './adapter'
import { authHeaders, notifyUnauthorized } from '../authService'

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''
const REQUEST_TIMEOUT_MS = 12000

/** Backend envelope: { success: true, data, timestamp } | { success: false, error, timestamp }. */
interface ApiEnvelope<T> {
  success: boolean
  data: T
  timestamp: string
}

interface ApiError {
  code: string
  message: string
}

function toError(error: unknown): ApiError {
  if (typeof error === 'object' && error !== null && 'code' in error && 'message' in error) {
    return error as ApiError
  }
  return { code: 'API_ERROR', message: 'Request to the optimization service failed' }
}

async function fetchOpt<T>(path: string, init?: Omit<RequestInit, 'body'> & { body?: unknown }, timeoutMs = REQUEST_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const headers: Record<string, string> = { Accept: 'application/json', ...authHeaders() }
  let body: BodyInit | undefined
  if (init?.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(init.body)
  }
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      method: init?.method ?? (body ? 'POST' : 'GET'),
      headers,
      body,
      signal: controller.signal,
    })
    if (response.status === 401) {
      notifyUnauthorized()
      throw { code: 'UNAUTHORIZED', message: 'Session expired or not authenticated — please sign in' } satisfies ApiError
    }
    if (!response.ok) {
      let message = `Request to ${path} failed with status ${response.status}`
      let code = 'HTTP_ERROR'
      try {
        const payload = (await response.json()) as { error?: { code?: string; message?: string } }
        if (payload?.error?.message) {
          message = payload.error.message
          code = payload.error.code ?? code
        }
      } catch {
        /* non-JSON error body, keep defaults */
      }
      if (response.status === 503 || response.status === 404) {
        message = `Quantum execution service unavailable — ${message}`
        code = 'QUANTUM_STACK_UNAVAILABLE'
      }
      throw { code, message } satisfies ApiError
    }
    const payload = (await response.json()) as ApiEnvelope<T>
    if (payload && typeof payload === 'object' && payload.success === true && 'data' in payload) {
      return payload.data
    }
    return payload as unknown as T
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw { code: 'TIMEOUT', message: `Optimization request to ${path} timed out` } satisfies ApiError
    }
    throw toError(error)
  } finally {
    clearTimeout(timer)
  }
}

interface RemotePipeline {
  stages: { id: PipelineStageId; label: string; detail: string; status: 'pending' | 'running' | 'done' | 'failed'; error?: string }[]
  completed: boolean
}

interface RemoteRun {
  /** Job summary returned by POST /run; only jobId is consumed here. */
  jobId: string
}

/** Snake_case wire body accepted by POST /api/optimization/run. */
interface RunWireBody {
  problem_type: OptimizeRequest['problemType']
  candidate_count: number
  max_sensors: number
  budget_k: number | null
  forecast_reference: string
  risk_profile?: OptimizeRequest['riskProfile']
  execution_mode: OptimizeRequest['executionMode']
  hardware_enabled: boolean
  backend: QuantumBackend
  shots: number
  layers: number
  weights: ObjectiveWeights
  normalize_weights: boolean
  coverage_requirements: { metric: CoverageRequirement['metric']; min_fraction: number; origin: string }[]
}

function toRunWireBody(request: OptimizeRequest): RunWireBody {
  return {
    problem_type: request.problemType,
    candidate_count: request.candidateCount,
    max_sensors: request.maxSensors,
    budget_k: request.budgetK,
    forecast_reference: request.forecastReference,
    risk_profile: request.riskProfile,
    execution_mode: request.executionMode,
    hardware_enabled: request.hardwareEnabled,
    backend: request.backend,
    shots: request.shots,
    layers: request.layers,
    weights: request.weights,
    normalize_weights: request.normalizeWeights,
    coverage_requirements: request.coverageRequirements.map(({ metric, minFraction, origin }) => ({
      metric,
      min_fraction: minFraction,
      origin,
    })),
  }
}

export class HttpOptimizationAdapter implements OptimizationAdapter {
  readonly mode = 'http' as const

  async getInputs(request: ProblemInputsRequest): Promise<OptimizationInputs> {
    const params = new URLSearchParams()
    params.set('candidateCount', String(request.candidateCount))
    if (request.forecastReference) params.set('forecast', request.forecastReference)
    if (request.riskProfile) params.set('risk', request.riskProfile)
    const raw = await fetchOpt<RemoteInputs>(`/api/optimization/inputs?${params.toString()}`)
    return {
      candidates: (raw.candidates ?? []).map((candidate) => ({
        id: candidate.id ?? '',
        name: candidate.name ?? candidate.id ?? '',
        zone: candidate.zone ?? '—',
        latitude: candidate.latitude ?? 0,
        longitude: candidate.longitude ?? 0,
        floodRisk: candidate.floodRisk ?? 0,
        populationExposure: candidate.populationExposure ?? 0,
        infrastructureCriticality: candidate.infrastructureCriticality ?? 0,
        communicationScore: candidate.communicationScore ?? 0,
        sensorCostK: candidate.sensorCostK ?? 0,
        coverageRadiusKm: candidate.coverageRadiusKm ?? 0,
      })),
      constraints: {
        maxSensors: raw.constraints?.maxSensors ?? Math.max(1, Math.round(request.candidateCount / 4)),
        budgetK: raw.constraints?.budgetK ?? null,
        coverageRequirements: raw.constraints?.coverageRequirements ?? [],
        notes: raw.constraints?.notes ?? [],
      },
      forecastRef: request.forecastReference || null,
      providedBy: {
        candidateLocations: raw.providedBy?.candidateLocations ?? 'GIS module',
        resourceConstraints: raw.providedBy?.resourceConstraints ?? 'Planning module',
        forecast: raw.providedBy?.forecast ?? 'AI forecasting',
      },
    }
  }

  async run(
    request: OptimizeRequest,
    onUpdate: (update: PipelineUpdate) => void,
    signal: AbortSignal,
  ): Promise<OptimizationResult> {
    const run = await fetchOpt<RemoteRun>('/api/optimization/run', { body: toRunWireBody(request) })
    if (signal.aborted) throw new Error('Run aborted')

    const deadline = Date.now() + 90_000
    let timedOut = false
    for (;;) {
      const pipeline = await fetchOpt<RemotePipeline>(`/api/optimization/jobs/${encodeURIComponent(run.jobId)}/pipeline`)
      for (const stage of pipeline.stages ?? []) {
        onUpdate({ stageId: stage.id, status: stage.status, error: stage.error })
      }
      if (pipeline.completed) {
        const failed = (pipeline.stages ?? []).find((stage) => stage.status === 'failed')
        if (failed) {
          throw {
            code: 'RUN_FAILED',
            message: failed.error ?? `Optimization pipeline failed at stage ${failed.label ?? failed.id}`,
          } satisfies ApiError
        }
        break
      }
      if (Date.now() > deadline) {
        timedOut = true
        break
      }
      await sleep(750, signal)
    }
    if (timedOut) {
      throw {
        code: 'RUN_TIMEOUT',
        message: `Optimization job ${run.jobId} did not complete within 90 seconds — check the job record before retrying`,
      } satisfies ApiError
    }

    const result = await fetchOpt<OptimizationResult>(`/api/optimization/jobs/${encodeURIComponent(run.jobId)}/result`)
    return normalizeResult(result)
  }
}

interface RemoteInputs {
  candidates?: (Partial<CandidateLocation>)[]
  constraints?: {
    maxSensors?: number
    budgetK?: number | null
    coverageRequirements?: OptimizationInputs['constraints']['coverageRequirements']
    notes?: string[]
  }
  providedBy?: { candidateLocations?: string; resourceConstraints?: string; forecast?: string }
}

function normalizeResult(raw: OptimizationResult): OptimizationResult {
  return {
    ...raw,
    selectedLocations: Array.isArray(raw.selectedLocations) ? raw.selectedLocations : [],
    constraintViolations: Array.isArray(raw.constraintViolations) ? raw.constraintViolations : [],
    objectiveBreakdown: Array.isArray(raw.objectiveBreakdown) ? raw.objectiveBreakdown : [],
    measurementCounts: Array.isArray(raw.measurementCounts) ? raw.measurementCounts : [],
    energyHistory: Array.isArray(raw.energyHistory) ? raw.energyHistory : [],
    qubo: raw.qubo ?? { variableCount: 0, variables: [], expression: 'unavailable', matrix: [], offset: 0 },
    classicalComparison: raw.classicalComparison ?? {
      method: 'unavailable',
      objectiveValue: 0,
      selectedCount: 0,
      executionTimeMs: 0,
      gapVsQuantum: 0,
    },
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new Error('Run aborted'))
      return
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      clearTimeout(timer)
      reject(new Error('Run aborted'))
    }
    signal.addEventListener('abort', onAbort)
  })
}