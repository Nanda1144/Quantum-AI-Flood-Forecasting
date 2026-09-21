/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Router } from 'express'
import { z } from 'zod'
import { authLimiter } from '../middleware/rate-limit.ts'
import { loginSchema } from '../middleware/schemas.ts'
import { validate } from '../middleware/validate.ts'
import { AuthService } from '../services/auth.service.ts'
import { success } from '../envelope.ts'

export function authRoutes(auth: AuthService): Router {
  const router = Router()

  router.post('/login', authLimiter, validate({ body: loginSchema }), (req, res) => {
    const { username, password } = req.validated!.body as z.infer<typeof loginSchema>
    const { token, user } = auth.login(username, password)
    res.json(success({ token, user }))
  })

  return router
}