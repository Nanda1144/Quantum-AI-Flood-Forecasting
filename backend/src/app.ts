/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
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
import { optimizationRoutes } from './routes/optimization.routes.ts'

export async function createApp(container?: Container): Promise<express.Express> {
  const c = container ?? (await buildContainer())
  const app = express()

  app.disable('x-powered-by')
  app.use(cors())
  app.use(express.json({ limit: '64kb' }))
  app.use(apiLimiter)

  app.get('/api/health', (_req, res) => {
    res.json(success({ service: 'backend', status: 'ok' }))
  })

  app.use('/api/auth', authRoutes(c.auth))
  app.use('/api/ai', aiRoutes(c))
  app.use('/api/optimization', optimizationRoutes(c))

  app.use(notFoundHandler)
  app.use(errorHandler)

  return app
}