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