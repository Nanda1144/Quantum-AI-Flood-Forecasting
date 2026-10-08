/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform. It is honest by construction,
 * per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is
 * clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Flood forecast + risk routes, mounted at `/api` by `src/app.ts`.
 *
 * Surface:
 *   POST /api/forecast                  create (serve + persist) a forecast
 *   POST /api/forecast/run              run forecast (endpoint alias)
 *   GET  /api/forecast/latest           read the most recent forecast
 *   GET  /api/forecast/history          list past forecasts
 *   GET  /api/forecast/:id              read one persisted forecast
 *   GET  /api/forecast/station/:id      typed state — no station FK exists
 *   GET  /api/risk-map                  typed state — GIS/exposure data surface
 *   GET  /api/risk/:areaId              typed state — area-risk data surface
 *   GET  /api/forecast/health           health check
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
import { ForecastService } from './forecast-service.ts'

export function forecastRoutes(c: Container): Router {
  const router = Router()
  router.use(authenticate(c.auth, config.AUTH_ENABLED))
  const service = new ForecastService(c.aiClient, c.forecastRepo)

  /** GET /api/forecast/health — forecast service health. */
  router.get('/forecast/health', (_req, res) => {
    res.json(success({ status: 'ok', service: 'flood-forecast' }))
  })

  /** GET /api/forecast/latest — fetch latest persisted forecast. */
  router.get('/forecast/latest', async (_req, res, next) => {
    try {
      const payload = await service.getLatest()
      if (payload === null) {
        // Run on-demand if no forecast stored yet
        const created = await service.createForecast(DEFAULT_FORECAST_HORIZON_HOURS)
        res.json(success(created))
        return
      }
      res.json(success(payload))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/forecast/history — fetch forecast history. */
  router.get('/forecast/history', async (_req, res, next) => {
    try {
      const list = await service.getHistory(30)
      res.json(success(list))
    } catch (error) {
      next(error)
    }
  })

  /** POST /api/forecast & POST /api/forecast/run — serve a forecast through the boundary and persist it. */
  const handleCreate = async (req: any, res: any, next: any) => {
    try {
      const body = (req.validated?.body ?? {}) as z.infer<typeof createForecastBodySchema>
      const horizonHours = body?.horizon_hours ?? DEFAULT_FORECAST_HORIZON_HOURS
      const payload = await service.createForecast(horizonHours)
      res.status(201).json(success(payload))
    } catch (error) {
      next(error)
    }
  }

  router.post('/forecast', validate({ body: createForecastBodySchema }), handleCreate)
  router.post('/forecast/run', validate({ body: createForecastBodySchema }), handleCreate)

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
   * GET /api/forecast/station/:id — typed state.
   */
  router.get('/forecast/station/:id', validate({ params: stationIdParamsSchema }), (req, res, next) => {
    try {
      const { id } = (req.validated?.params ?? {}) as z.infer<typeof stationIdParamsSchema>
      res.json(success(service.stationForecast(id)))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/risk-map — typed state; GIS/exposure data state. */
  router.get('/risk-map', (_req, res, next) => {
    try {
      res.json(success(service.riskMap()))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/risk/:areaId — typed state; area-risk data. */
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

export const navyaForecastRoutes = forecastRoutes
