/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * HTTP client for the QUBO Visualization page.
 *
 * Every endpoint it talks to belongs to the optimization gateway and every
 * response unwraps the backend envelope ({ success, data, timestamp }) that
 * `fetchJson`-style clients already consume. The backend serves the stored
 * formulation; this module does not re-derive or re-compute any QUBO
 * coefficients.
 *
 *   GET /api/optimization/jobs           → experiment ledger (newest first)
 *   GET /api/optimization/jobs/:id/qubo      → QuboFormulation (full payload)
 *   GET /api/optimization/jobs/:id/pipeline  → pipeline stages
 *   GET /api/optimization/jobs/:id/result    → OptimizationResult
 *   GET /api/optimization/jobs/:id/export    → backend-generated export document
 *   GET /api/optimization/inputs             → federated GIS candidates + constraints
 *   GET /api/optimization/:id                → QuantumJobSummary (status page)
 */

import type {
  OptimizationExportDocument,
  OptimizationInputsPayload,
  PipelineStage,
  OptimizationResult,
  QuboFormulation,
  QuantumJobSummary,
} from '../../types/optimization'
import type { BenchmarkDocument, BenchmarkListEntry } from '../../types/benchmark'
import { authHeaders, notifyUnauthorized } from '../authService'

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''
const REQUEST_TIMEOUT_MS = 12000

interface ApiError {
  code: string
  message: string
}

interface ApiEnvelope<T> {
  success: boolean
  data: T
  timestamp: string
}

function toError(error: unknown): ApiError {
  if (typeof error === 'object' && error !== null && 'code' in error && 'message' in error) {
    return error as ApiError
  }
  return { code: 'API_ERROR', message: 'Request to the optimization service failed' }
}

async function fetchOpt<T>(path: string): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { Accept: 'application/json', ...authHeaders() },
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
      throw { code, message } satisfies ApiError
    }
    const payload = (await response.json()) as ApiEnvelope<T>
    if (payload && typeof payload === 'object' && payload.success === true && 'data' in payload) {
      return payload.data
    }
    return payload as unknown as T
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw { code: 'TIMEOUT', message: `Request to ${path} timed out` } satisfies ApiError
    }
    throw toError(error)
  } finally {
    clearTimeout(timer)
  }
}

/** Full formulation served for a job — the single data source for the page. */
export async function fetchQuboFormulation(jobId: string): Promise<QuboFormulation> {
  return fetchOpt<QuboFormulation>(`/api/optimization/jobs/${encodeURIComponent(jobId)}/qubo`)
}

/**
 * Experiment ledger for the Quantum vs Classical Benchmark page — every job
 * the caller may read, newest first, as `QuantumJobSummary` records. The page
 * filters for completed runs with a stored result; nothing here is fabricated.
 */
export async function fetchOptimizationJobs(): Promise<QuantumJobSummary[]> {
  return fetchOpt<QuantumJobSummary[]>('/api/optimization/jobs')
}

/** Pipeline stages for the "view execution" action. */
export async function fetchQuboPipeline(jobId: string): Promise<PipelineStage[]> {
  const payload = await fetchOpt<{ stages?: PipelineStage[]; completed?: boolean }>(
    `/api/optimization/jobs/${encodeURIComponent(jobId)}/pipeline`,
  )
  return payload.stages ?? []
}

/** Full result document for the "view result" action. */
export async function fetchQuboResult(jobId: string): Promise<OptimizationResult> {
  return fetchOpt<OptimizationResult>(`/api/optimization/jobs/${encodeURIComponent(jobId)}/result`)
}

/** Canonical job summary — the primary source for the status page. */
export async function fetchJobSummary(jobId: string): Promise<QuantumJobSummary> {
  return fetchOpt<QuantumJobSummary>(`/api/optimization/${encodeURIComponent(jobId)}`)
}

/**
 * Federated GIS candidate sites (with coordinates) + planning constraints, used
 * by the Optimization Result page to place the decoded selection on the map.
 * The deterministic generator keys off the candidate count, so passing the
 * job's `variablesCount` reproduces the geometry the pipeline consumed.
 */
export async function fetchOptimizationInputs(candidateCount: number): Promise<OptimizationInputsPayload> {
  return fetchOpt<OptimizationInputsPayload>(
    `/api/optimization/inputs?candidateCount=${encodeURIComponent(String(candidateCount))}`,
  )
}

/**
 * Backend-generated, auditable export document for a job. The page downloads
 * this object verbatim — it is never reconstructed from the in-memory result.
 */
export async function fetchOptimizationExport(jobId: string): Promise<OptimizationExportDocument> {
  return fetchOpt<OptimizationExportDocument>(`/api/optimization/jobs/${encodeURIComponent(jobId)}/export`)
}

/**
 * Filterable benchmark ledger — completed runs with a stored result, newest
 * first, served by the gateway's benchmark endpoint. This is the ONLY ledger
 * source for the Quantum vs Classical Benchmark page: the rows carry the
 * stored classical/quantum measurements and the approximation ratio verbatim.
 */
export async function fetchBenchmarkLedger(): Promise<BenchmarkListEntry[]> {
  return fetchOpt<BenchmarkListEntry[]>('/api/optimization/benchmarks')
}

/**
 * Full benchmark document for one experiment — the raw, stored measurements
 * the backend assembled from the persisted run (objective, runtime, constraint
 * violations, approximation ratio + basis, seed, experiment configuration).
 * Never re-executed: it is the same write-once snapshot the pipeline persisted.
 */
export async function fetchBenchmarkDocument(jobId: string): Promise<BenchmarkDocument> {
  return fetchOpt<BenchmarkDocument>(`/api/optimization/${encodeURIComponent(jobId)}/benchmark`)
}