/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Data loading for the Quantum vs Classical Benchmark page.
 *
 * The experiment ledger comes from the optimization gateway's
 * `GET /api/optimization/jobs` (summaries only) and the selected run's full
 * document from `GET /api/optimization/jobs/:id/result`. There is no mock path:
 * a benchmark of persisted experiments is meaningless if it fabricates runs, so
 * the page reads the real ledger and surfaces an honest empty / unavailable
 * state whenever the gateway cannot be reached.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { OptimizationResult, QuantumJobSummary } from '../types/optimization'
import { adapterModeAvailable } from '../services/optimization/adapter'
import { fetchOptimizationJobs, fetchQuboResult } from '../services/optimization/quboService'
import { isCompleteRun } from '../lib/benchmark'

export interface QuantumBenchmarkState {
  ledger: QuantumJobSummary[] | null
  completedRuns: QuantumJobSummary[]
  /** True while the sample-data flag routes the optimization console to the mock adapter. */
  sampleMode: boolean
  loading: boolean
  error: string | null
  selectedJobId: string | null
  selectedSummary: QuantumJobSummary | null
  result: OptimizationResult | null
  resultLoading: boolean
  resultError: string | null
  refresh: () => void
  selectRun: (jobId: string) => void
}

function toMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'message' in error) {
    return String((error as { message: unknown }).message)
  }
  return error instanceof Error ? error.message : String(error)
}

export function useQuantumBenchmark(): QuantumBenchmarkState {
  const [ledger, setLedger] = useState<QuantumJobSummary[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [result, setResult] = useState<OptimizationResult | null>(null)
  const [resultLoading, setResultLoading] = useState(false)
  const [resultError, setResultError] = useState<string | null>(null)
  const requestId = useRef(0)

  const refresh = useCallback(() => {
    setSelectedJobId(null)
    setRefreshKey((key) => key + 1)
  }, [])

  useEffect(() => {
    const id = ++requestId.current
    // oxlint-disable-next-line react/set-state-in-effect -- toggles the loading state for a newer fetch; the request itself is async.
    setLoading(true)
    setError(null)
    fetchOptimizationJobs()
      .then((jobs) => {
        if (requestId.current !== id) return
        const completed = jobs.filter(isCompleteRun)
        setLedger(jobs)
        // Default to the most recent completed experiment, if any.
        setSelectedJobId((previous) => {
          if (previous && jobs.some((job) => job.jobId === previous && isCompleteRun(job))) return previous
          return completed.length > 0 ? completed[0].jobId : null
        })
        setLoading(false)
      })
      .catch((loadError) => {
        if (requestId.current !== id) return
        setLedger(null)
        setLoading(false)
        setError(toMessage(loadError))
      })
    return () => {
      requestId.current += 1
    }
  }, [refreshKey])

  const selectedSummary = ledger?.find((job) => job.jobId === selectedJobId) ?? null
  const completedRuns = (ledger ?? []).filter(isCompleteRun)

  useEffect(() => {
    if (!selectedSummary) {
      // oxlint-disable-next-line react/set-state-in-effect -- clears the previous run's document when the selection changes.
      setResult(null)
      setResultError(null)
      return
    }
    let cancelled = false
    setResultLoading(true)
    setResultError(null)
    fetchQuboResult(selectedSummary.jobId)
      .then((loaded) => {
        if (cancelled) return
        setResult(loaded)
        setResultLoading(false)
      })
      .catch((loadError) => {
        if (cancelled) return
        setResult(null)
        setResultLoading(false)
        setResultError(toMessage(loadError))
      })
    return () => {
      cancelled = true
    }
  }, [selectedSummary?.jobId, selectedSummary])

  const selectRun = useCallback((jobId: string) => {
    setSelectedJobId(jobId)
  }, [])

  return {
    ledger,
    completedRuns,
    sampleMode: adapterModeAvailable() === 'mock',
    loading,
    error,
    selectedJobId,
    selectedSummary,
    result,
    resultLoading,
    resultError,
    refresh,
    selectRun,
  }
}