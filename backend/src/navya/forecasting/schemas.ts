/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Zod request validation for the Navya forecast + risk endpoints.
 *
 * Follows the team's conventions (`src/middleware/schemas.ts` and
 * `src/middleware/validate.ts`): invalid input is rejected with a 422 and
 * never silently coerced or defaulted. Generic validators are reused from the
 * team area, not duplicated — `forecastIdSchema` comes from
 * `src/middleware/schemas.ts`.
 *
 * Horizon bounds mirror the AI service's own query constraint
 * (`1..72` hours on `/api/ai/forecast/latest`), so a request the backend
 * accepts is a request the serving boundary also accepts.
 */

import { z } from 'zod'
import { forecastIdSchema } from '../../middleware/schemas.ts'

export const DEFAULT_FORECAST_HORIZON_HOURS = 24

/** POST /api/forecast — the horizon is the only input the serving boundary takes. */
export const createForecastBodySchema = z
  .object({
    horizon_hours: z.number().int().min(1).max(72).optional(),
  })
  .optional()

/** GET /api/forecast/:id — team canonical forecast id shape (`FC-YYYYMMDD-###`). */
export const forecastIdParamsSchema = z.object({
  id: forecastIdSchema,
})

/**
 * GET /api/forecast/station/:id — a structured station identifier.
 *
 * No station registry exists, so this validates shape only; whether any
 * station→forecast mapping exists is answered by the endpoint's typed
 * NOT_EVALUABLE state, never by guessing.
 */
export const stationIdParamsSchema = z.object({
  id: z.string().trim().min(1).max(128),
})

/** GET /api/risk/:areaId — a structured area identifier, shape-only. */
export const areaIdParamsSchema = z.object({
  areaId: z.string().trim().min(1).max(128),
})