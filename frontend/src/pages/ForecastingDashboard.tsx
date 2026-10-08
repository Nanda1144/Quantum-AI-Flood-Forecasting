/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda (integration) + Navya (forecasting module) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Route target for the hydrological forecasting module.
 *
 * The module (`../features/forecasting`) owns its own data loading, so this file
 * stays a thin composition root: it exists so routing lives in `App.tsx` and the
 * forecasting implementation stays inside one feature folder.
 */

import { ForecastDashboard } from '../features/forecasting'

export function ForecastingDashboard() {
  return <ForecastDashboard />
}