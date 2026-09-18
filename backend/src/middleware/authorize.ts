import type { NextFunction, Request, Response } from 'express'
import { AppError, ErrorCodes } from '../envelope.ts'
import type { AuthService, AuthPrincipal } from '../services/auth.service.ts'

declare module 'express-serve-static-core' {
  interface Request {
    principal?: AuthPrincipal
  }
}

/** JWT verification. Skips enforcement when AUTH_ENABLED=false (local demo). */
export function authenticate(auth: AuthService, enabled: boolean) {
  return (req: Request, _res: Response, next: NextFunction): void => {
    if (!enabled) {
      req.principal = { username: 'local-demo', role: 'admin' }
      next()
      return
    }
    const header = req.headers.authorization
    const token = header?.startsWith('Bearer ') ? header.slice('Bearer '.length) : undefined
    const principal = token ? auth.verifyToken(token) : null
    if (!principal) {
      next(new AppError(401, ErrorCodes.UNAUTHORIZED, 'Authentication required'))
      return
    }
    req.principal = principal
    next()
  }
}

/**
 * Role-based access control. Call AFTER `authenticate`. Requires the
 * authenticated principal to rank at least as high as `minimumRole`.
 */
export function authorize(minimumRole: AuthPrincipal['role']) {
  return (req: Request, _res: Response, next: NextFunction): void => {
    const principal = req.principal
    if (!principal) {
      next(new AppError(401, ErrorCodes.UNAUTHORIZED, 'Authentication required'))
      return
    }
    const rank: Record<AuthPrincipal['role'], number> = { viewer: 1, operator: 2, admin: 3 }
    if (rank[principal.role] < rank[minimumRole]) {
      next(new AppError(403, ErrorCodes.FORBIDDEN, 'Insufficient permissions for this action'))
      return
    }
    next()
  }
}