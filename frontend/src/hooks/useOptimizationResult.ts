/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Data loading for the Optimization Result page (`/optimization/:id/result`).
 *
 * Three gateway reads feed the page, each surfaced honestly:
 *   GET /api/optimization/:id                  → job summary (verdict, config)
 *   GET /api/optimization/jobs/:id/result      → full stored result document
 *   GET /api/optimization/inputs               → GIS candidates (map geometry)
 *
 * The export action calls the backend document endpoint directly. There is no
 * mock path: a decision document is meaningless if it is fabricated, so an
 * unreachable gateway renders an error / empty state instead.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { CandidateLocation, OptimizationResult, QuantumJobSummary } from '../types/optimization'
import {
  fetchJobSummary,
  fetchOptimizationExport,
  fetchOptimizationInputs,
  fetchQuboResult,
} from '../services/optimization/quboService'
import { downloadFile } from '../lib/benchmark'
import type { ExportState } from '../components/optimizationResult/ResultActions'

export interface OptimizationResultState {
  summary: QuantumJobSummary | null
  result: OptimizationResult | null
  candidates: CandidateLocation[] | null
  candidatesError: string | null
  loading: boolean
  error: string | null
  notFound: boolean
  exportState: ExportState
  exportError: string | null
  refresh: () => void
  downloadExport: () => void
}

function toMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'message' in error) {
    return String((error as { message: unknown }).message)
  }
  return error instanceof Error ? error.message : String(error)
}

function isNotFoundError(error: unknown): boolean {
  return typeof error === 'object' && error !== null && (error as { code?: unknown }).code === 'JOB_NOT_FOUND'
}

export function useOptimizationResult(jobId: string): OptimizationResultState {
  const [summary, setSummary] = useState<QuantumJobSummary | null>(null)
  const [result, setResult] = useState<OptimizationResult | null>(null)
  const [candidates, setCandidates] = useState<CandidateLocation[] | null>(null)
  const [candidatesError, setCandidatesError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [exportState, setExportState] = useState<ExportState>('idle')
  const [exportError, setExportError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const requestId = useRef(0)

  const refresh = useCallback(() => {
    setRefreshKey((key) => key + 1)
  }, [])

  useEffect(() => {
    const id = ++requestId.current
    // oxlint-disable-next-line react/set-state-in-effect -- toggles loading for a newer fetch; the request itself is async.
    setLoading(true)
    setError(null)
    setNotFound(false)
    setResult(null)
    setCandidates(null)
    setCandidatesError(null)

    fetchJobSummary(jobId)
      .then(async (loadedSummary) => {
        if (requestId.current !== id) return
        setSummary(loadedSummary)

        if (loadedSummary.status === 'completed') {
          try {
            const loadedResult = await fetchQuboResult(jobId)
            if (requestId.current !== id) return
            setResult(loadedResult)
          } catch (resultError) {
            if (requestId.current !== id) return
            setError(toMessage(resultError))
          }

          const candidateCount = loadedSummary.variablesCount
          const defaultReference = candidateCount !== null && candidateCount !== undefined ? `gis://candidates/${candidateCount}` : null
          const referenceReproducible = loadedSummary.candidateReference === null || loadedSummary.candidateReference === defaultReference
          if (candidateCount !== null && candidateCount !== undefined) {
            if (!referenceReproducible) {
              if (requestId.current !== id) return
              setCandidatesError(
                `candidate geometry is stored under a custom reference (${loadedSummary.candidateReference}); only the default candidate set can be reproduced`,
              )
            } else {
              try {
                const inputs = await fetchOptimizationInputs(candidateCount)
                if (requestId.current !== id) return
                setCandidates(inputs.candidates)
              } catch (inputsError) {
                if (requestId.current !== id) return
                setCandidatesError(toMessage(inputsError))
              }
            }
          }
        }

        if (requestId.current === id) setLoading(false)
      })
      .catch((loadError) => {
        if (requestId.current !== id) return
        setSummary(null)
        setLoading(false)
        if (isNotFoundError(loadError)) {
          setNotFound(true)
          return
        }
        setError(toMessage(loadError))
      })

    return () => {
      requestId.current += 1
    }
  }, [jobId, refreshKey])

  const downloadExport = useCallback(() => {
    setExportState('loading')
    setExportError(null)
    fetchOptimizationExport(jobId)
      .then((document) => {
        downloadFile(
          `qflare-optimization-${jobId}.json`,
          JSON.stringify(document, null, 2),
          'application/json',
        )
        setExportState('idle')
      })
      .catch((exportFailure) => {
        setExportState('error')
        setExportError(toMessage(exportFailure))
      })
  }, [jobId])

  return {
    summary,
    result,
    candidates,
    candidatesError,
    loading,
    error,
    notFound,
    exportState,
    exportError,
    refresh,
    downloadExport,
  }
}
