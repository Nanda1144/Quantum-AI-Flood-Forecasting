/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Navya forecast + risk routes, mounted at `/api` by `src/app.ts`.
 *
 * Surface:
 *   POST /api/forecast                  create (serve + persist) a forecast
 *   GET  /api/forecast/:id              read one persisted forecast
 *   GET  /api/forecast/station/:id      typed state — no station FK exists
 *   GET  /api/risk-map                  typed state — no GIS/exposure data exists
 *   GET  /api/risk/:areaId              typed state — no area-risk data exists
 *
 * Conventions follow the team's own routes (`src/routes/ai.routes.ts`):
 * one shared router, `authenticate(c.auth, config.AUTH_ENABLED)` gating every
 * route (enforced only when AUTH_ENABLED=true, skipped in local demo), Zod
 * validation via the shared `validate` middleware, and the canonical envelope
 * via `success` / `AppError`. No second Express app, no second error format.
 */

import { Router } from 'express'
import { z } from 'zod'
import { config } from '../../config.ts'
import type { Container } from '../../container.ts'
import { AppError, ErrorCodes, success } from '../../envelope.ts'
import { authenticate } from '../../middleware/authorize.ts'
import { validate } from '../../middleware/validate.ts'
import {
  areaIdParamsSchema,
  createForecastBodySchema,
  DEFAULT_FORECAST_HORIZON_HOURS,
  forecastIdParamsSchema,
  stationIdParamsSchema,
} from './schemas.ts'
import { NavyaForecastService } from './forecast-service.ts'

export function navyaForecastRoutes(c: Container): Router {
  const router = Router()
  router.use(authenticate(c.auth, config.AUTH_ENABLED))
  const service = new NavyaForecastService(c.aiClient, c.forecastRepo)

  /** POST /api/forecast — serve a forecast through the boundary and persist it. */
  router.post('/forecast', validate({ body: createForecastBodySchema }), async (req, res, next) => {
    try {
      const body = (req.validated?.body ?? {}) as z.infer<typeof createForecastBodySchema>
      const horizonHours = body?.horizon_hours ?? DEFAULT_FORECAST_HORIZON_HOURS
      const payload = await service.createForecast(horizonHours)
      res.status(201).json(success(payload))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/forecast/:id — one persisted forecast (404 when absent). */
  router.get('/forecast/:id', validate({ params: forecastIdParamsSchema }), async (req, res, next) => {
    try {
      const { id } = (req.validated?.params ?? {}) as z.infer<typeof forecastIdParamsSchema>
      const payload = await service.getForecast(id)
      if (payload === null) {
        next(new AppError(404, ErrorCodes.FORECAST_NOT_FOUND, `Forecast ${id} not found`))
        return
      }
      res.json(success(payload))
    } catch (error) {
      next(error)
    }
  })

  /**
   * GET /api/forecast/station/:id — typed NOT_EVALUABLE state.
   *
   * The forecasts table has no station FK and no station registry exists, so
   * this endpoint never infers a mapping. The response explains the absence.
   */
  router.get('/forecast/station/:id', validate({ params: stationIdParamsSchema }), (req, res, next) => {
    try {
      const { id } = (req.validated?.params ?? {}) as z.infer<typeof stationIdParamsSchema>
      res.json(success(service.stationForecast(id)))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/risk-map — typed state; no authoritative GIS/exposure data exists. */
  router.get('/risk-map', (_req, res, next) => {
    try {
      res.json(success(service.riskMap()))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/risk/:areaId — typed state; no authoritative area-risk data exists. */
  router.get('/risk/:areaId', validate({ params: areaIdParamsSchema }), (req, res, next) => {
    try {
      const { areaId } = (req.validated?.params ?? {}) as z.infer<typeof areaIdParamsSchema>
      res.json(success(service.riskForArea(areaId)))
    } catch (error) {
      next(error)
    }
  })

  return router
}