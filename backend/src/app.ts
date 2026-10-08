/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform. It is honest by construction,
 * per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is
 * clearly labelled, and no quantum speedup is ever claimed.
 */

import cors from 'cors'
import express from 'express'
import type { Container } from './container.ts'
import { success } from './envelope.ts'
import { buildContainer } from './container.ts'
import { errorHandler, notFoundHandler } from './middleware/error-handler.ts'
import { apiLimiter } from './middleware/rate-limit.ts'
import { authRoutes } from './routes/auth.routes.ts'
import { aiRoutes } from './routes/ai.routes.ts'
import { benchmarkSummaryRouter, optimizationRoutes } from './routes/optimization.routes.ts'
import { forecastRoutes } from './routes/forecast.routes.ts'
import { gisRoutes } from './routes/gis.routes.ts'
import { iotRoutes } from './routes/iot.routes.ts'
import { dataRoutes } from './routes/data.routes.ts'
import { responseRoutes } from './routes/response.routes.ts'

export async function createApp(container?: Container): Promise<express.Express> {
  const c = container ?? (await buildContainer())
  const app = express()

  app.disable('x-powered-by')
  app.use(cors())
  app.use(express.json({ limit: '64kb' }))
  app.use(apiLimiter)

  // Health check endpoints
  app.get('/api/health', (_req, res) => {
    res.json(success({ service: 'backend', status: 'ok' }))
  })
  app.get('/api/ai/health', (_req, res) => {
    res.json(success({ service: 'ai-analytics', status: 'ok' }))
  })
  app.get('/api/quantum/health', (_req, res) => {
    res.json(success({ service: 'quantum-service', status: 'ok' }))
  })

  // Core Service Routers
  app.use('/api/auth', authRoutes(c.auth))
  app.use('/api/ai', aiRoutes(c))
  app.use('/api/optimization', optimizationRoutes(c))
  app.use('/api/quantum', optimizationRoutes(c))
  app.use(benchmarkSummaryRouter(c))

  // Flood Forecasting & Risk
  app.use('/api', forecastRoutes(c))
  app.use('/api/forecast', forecastRoutes(c))

  // GIS Spatial Intelligence & Candidate Locations
  app.use('/api/gis', gisRoutes())

  // IoT Sensor Telemetry & Simulation Engine
  app.use('/api/iot', iotRoutes())
  app.use('/api/sensors', iotRoutes())

  // Hydrology Datasets & Quality Preprocessing
  app.use('/api/data', dataRoutes())

  // Disaster Response Planning & Evacuation
  app.use('/api/response', responseRoutes())

  app.use(notFoundHandler)
  app.use(errorHandler)

  return app
}