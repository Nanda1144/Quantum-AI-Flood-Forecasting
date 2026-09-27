/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { APIError } from '../../types/ai'
import { loadNavyaComparison, loadNavyaForecast } from './navyaForecastService'
import type { NavyaForecastRecord, NavyaModelComparison } from './types'

interface Options {
  /** Auto-load on mount. Default true. */
  loadOnMount?: boolean
}

interface InternalState {
  forecast: NavyaForecastRecord | null
  comparison: NavyaModelComparison | null
  loading: boolean
  error: APIError | null
  /** Set when the forecast loaded but the comparison did not. */
  comparisonError: APIError | null
}

const initialState: InternalState = {
  forecast: null,
  comparison: null,
  loading: false,
  error: null,
  comparisonError: null,
}

/**
 * Loads Navya's forecast record and the model comparison.
 *
 * ## Two requests, two error slots
 *
 * The comparison is fetched separately and its failure is recorded in
 * `comparisonError` rather than `error`. The forecast is the point of the
 * screen; losing the comparison table is a degraded screen, not a broken one,
 * and conflating the two would hide which part is missing.
 *
 * ## No sample-data fallback
 *
 * `useAIAnalytics` swaps in a clearly-flagged snapshot when the backend is down.
 * This hook does not, for the reason given in `navyaForecastService.ts`: a
 * component whose job is to report provenance cannot be handed invented numbers
 * to report provenance *about*.
 *
 * ## `isSampleData` is always false
 *
 * It is kept in the returned shape because `NavyaForecastState` declares it and
 * because a future owner adding a real sample-data path needs the field to
 * exist. Returning a hard `false` is a statement: as written, this module has no
 * sample-data path, so the flag can never be anything else.
 */
export function useNavyaForecast({ loadOnMount = true }: Options = {}) {
  const [state, setState] = useState<InternalState>({
    ...initialState,
    loading: loadOnMount,
  })
  const requestId = useRef(0)

  const load = useCallback(async (resetLoading = false) => {
    const id = ++requestId.current
    if (resetLoading) {
      setState((prev) => ({ ...prev, loading: true, error: null, comparisonError: null }))
    }
    try {
      const forecast = await loadNavyaForecast()
      if (requestId.current !== id) return
      // The comparison is a separate, non-fatal request. The forecast is
      // committed first so the screen is useful even if the second call hangs.
      setState((prev) => ({ ...prev, forecast, loading: false, error: null }))
    } catch (error) {
      if (requestId.current !== id) return
      setState((prev) => ({
        ...prev,
        loading: false,
        forecast: null,
        error: toApiError(error),
      }))
      return
    }

    try {
      const comparison = await loadNavyaComparison()
      if (requestId.current !== id) return
      setState((prev) => ({ ...prev, comparison, comparisonError: null }))
    } catch (error) {
      if (requestId.current !== id) return
      setState((prev) => ({ ...prev, comparison: null, comparisonError: toApiError(error) }))
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

  return {
    ...state,
    isSampleData: false as const,
    reload: useCallback(() => void load(true), [load]),
  }
}

function toApiError(error: unknown): APIError {
  if (typeof error === 'object' && error !== null && 'code' in error && 'message' in error) {
    return error as APIError
  }
  if (error instanceof Error) {
    return { code: 'NAVYA_FORECAST_ERROR', message: error.message }
  }
  return { code: 'NAVYA_FORECAST_ERROR', message: 'Failed to load the Navya forecast record' }
}
