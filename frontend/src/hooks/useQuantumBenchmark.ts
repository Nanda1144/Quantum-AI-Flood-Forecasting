/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Data loading for the Quantum vs Classical Benchmark page.
 *
 * The experiment ledger comes from the gateway's benchmark endpoint
 * `GET /api/optimization/benchmarks` (completed runs with a stored result, the
 * measured rows verbatim) and the selected experiment's raw document from
 * `GET /api/optimization/:id/benchmark`. There is no mock path: a benchmark of
 * persisted experiments is meaningless if it fabricates runs, so the page reads
 * the real measurements and surfaces an honest empty / unavailable state
 * whenever the gateway cannot be reached or a run has no benchmark yet.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { BenchmarkDocument, BenchmarkListEntry } from '../types/benchmark'
import { adapterModeAvailable } from '../services/optimization/adapter'
import { fetchBenchmarkDocument, fetchBenchmarkLedger } from '../services/optimization/quboService'

export interface QuantumBenchmarkState {
  /** Completed experiments with a stored result, newest first (served verbatim). */
  ledger: BenchmarkListEntry[] | null
  /** Alias of `ledger` — every ledger row is a completed, comparable run. */
  completedRuns: BenchmarkListEntry[]
  /** True while the sample-data flag routes the optimization console to the mock adapter. */
  sampleMode: boolean
  loading: boolean
  error: string | null
  selectedJobId: string | null
  /** The raw stored benchmark document for the selected experiment. */
  document: BenchmarkDocument | null
  documentLoading: boolean
  documentError: string | null
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
  const [ledger, setLedger] = useState<BenchmarkListEntry[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [document, setDocument] = useState<BenchmarkDocument | null>(null)
  const [documentLoading, setDocumentLoading] = useState(false)
  const [documentError, setDocumentError] = useState<string | null>(null)
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
    fetchBenchmarkLedger()
      .then((rows) => {
        if (requestId.current !== id) return
        setLedger(rows)
        // Default to the most recent completed experiment — the ledger is
        // served newest first, so the first row is the newest measurement.
        setSelectedJobId((previous) => {
          if (previous && rows.some((row) => row.jobId === previous)) return previous
          return rows.length > 0 ? rows[0].jobId : null
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

  useEffect(() => {
    if (selectedJobId === null) {
      // oxlint-disable-next-line react/set-state-in-effect -- clears the previous experiment's document when the selection changes.
      setDocument(null)
      setDocumentError(null)
      return
    }
    let cancelled = false
    setDocumentLoading(true)
    setDocumentError(null)
    fetchBenchmarkDocument(selectedJobId)
      .then((loaded) => {
        if (cancelled) return
        setDocument(loaded)
        setDocumentLoading(false)
      })
      .catch((loadError) => {
        if (cancelled) return
        setDocument(null)
        setDocumentLoading(false)
        setDocumentError(toMessage(loadError))
      })
    return () => {
      cancelled = true
    }
  }, [selectedJobId])

  const selectRun = useCallback((jobId: string) => {
    setSelectedJobId(jobId)
  }, [])

  return {
    ledger,
    completedRuns: ledger ?? [],
    sampleMode: adapterModeAvailable() === 'mock',
    loading,
    error,
    selectedJobId,
    document,
    documentLoading,
    documentError,
    refresh,
    selectRun,
  }
}