/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { AISnapshot } from '../types/ai'
import { loadAIAnalytics } from '../services/aiService'

interface State {
  snapshot: AISnapshot | null
  isMock: boolean
  loading: boolean
  error: string | null
  stale: boolean
}

interface Options {
  /** Auto-load on mount. Default true. */
  loadOnMount?: boolean
}

export function useAIAnalytics({ loadOnMount = true }: Options = {}) {
  const [state, setState] = useState<State>({
    snapshot: null,
    isMock: false,
    loading: loadOnMount,
    error: null,
    stale: false,
  })
  const requestId = useRef(0)

  /**
   * Loads analytics. `resetLoading` is used for user-triggered refreshes so the
   * spinner returns; on mount the initial state already marks loading=true, which
   * keeps this effect free of synchronous setState.
   */
  const load = useCallback(async (resetLoading = false) => {
    const id = ++requestId.current
    if (resetLoading) {
      setState((prev) => ({ ...prev, loading: true, error: null, stale: false }))
    }
    try {
      const { snapshot, isMock } = await loadAIAnalytics()
      if (requestId.current !== id) return
      setState({ snapshot, isMock, loading: false, error: null, stale: false })
    } catch (error) {
      if (requestId.current !== id) return
      const message = error instanceof Error ? error.message : 'Failed to load AI analytics'
      setState((prev) => ({ ...prev, loading: false, error: message }))
    }
  }, [])

  useEffect(() => {
    if (loadOnMount) {
      // oxlint-disable-next-line react/set-state-in-effect -- setState only fires after await, not synchronously.
      void load(false)
    }
    return () => {
      requestId.current += 1
    }
  }, [load, loadOnMount])

  /** Marks current data as stale (e.g. after data-freshness exceeded). */
  const markStale = useCallback(() => {
    setState((prev) => (prev.snapshot ? { ...prev, stale: true } : prev))
  }, [])

  return {
    ...state,
    refetch: load,
    markStale,
  }
}