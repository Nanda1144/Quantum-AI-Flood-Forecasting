/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { ModelComparisonQuery, ModelComparisonResult } from '../types/ai'
import { loadModelComparison } from '../services/aiService'

export interface ModelComparisonState {
  data: ModelComparisonResult | null
  loading: boolean
  error: string | null
}

/**
 * Loads the registry-backed model comparison for the current query. Every query
 * change (sort / direction / evaluation window / status) issues a fresh request
 * with the filter applied server-side; when cached rows exist they stay visible
 * while the newer fetch is in flight. All metrics come from the backend — no
 * sample rows are substituted.
 */
export function useModelComparison() {
  const [query, setQuery] = useState<ModelComparisonQuery>({})
  const [refreshKey, setRefreshKey] = useState(0)
  const [state, setState] = useState<ModelComparisonState>({
    data: null,
    loading: true,
    error: null,
  })
  const requestId = useRef(0)

  const load = useCallback(async (q: ModelComparisonQuery) => {
    const id = ++requestId.current
    try {
      const result = await loadModelComparison(q)
      if (requestId.current !== id) return
      setState({ data: result, loading: false, error: null })
    } catch (error) {
      if (requestId.current !== id) return
      const message = error instanceof Error ? error.message : 'Failed to load model comparison'
      setState((prev) => ({ ...prev, loading: false, error: message }))
    }
  }, [])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- toggles loading for a newer fetch; the request itself is async.
    setState((prev) => (prev.data ? { ...prev, loading: true, error: null } : prev))
    void load(query)
    return () => {
      requestId.current += 1
    }
  }, [query, refreshKey, load])

  const updateQuery = useCallback((patch: Partial<ModelComparisonQuery>) => {
    setQuery((prev) => {
      const next = { ...prev, ...patch }
      const changed =
        (patch.sort ?? null) !== (prev.sort ?? null) ||
        (patch.direction ?? null) !== (prev.direction ?? null) ||
        (patch.from ?? null) !== (prev.from ?? null) ||
        (patch.to ?? null) !== (prev.to ?? null) ||
        (patch.status ?? null) !== (prev.status ?? null)
      return changed ? next : prev
    })
  }, [])

  const reset = useCallback(() => {
    setQuery({})
    setRefreshKey((key) => key + 1)
  }, [])

  const refetch = useCallback(() => {
    setRefreshKey((key) => key + 1)
  }, [])

  return { ...state, query, updateQuery, reset, refetch }
}