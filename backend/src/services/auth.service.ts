/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import jwt from 'jsonwebtoken'
import { AppError, ErrorCodes } from '../envelope.ts'
import { config, type AuthUser, type Role } from '../config.ts'

const { sign, verify } = jwt
const ROLE_SET = new Set<Role>(['admin', 'operator', 'viewer'])

export interface AuthPrincipal {
  username: string
  role: Role
}

/** Role ranking used by the RBAC authorize middleware. */
export const ROLE_RANK: Record<Role, number> = { viewer: 1, operator: 2, admin: 3 }

/** Issues and verifies JWTs; resolves demo users from config into principals. */
export class AuthService {
  constructor(private readonly cfg: typeof config) {}

  login(username: string, password: string): { token: string; user: AuthPrincipal } {
    const entry: AuthUser | undefined = this.cfg.users[username]
    if (!entry || entry.password !== password) {
      throw new AppError(401, ErrorCodes.UNAUTHORIZED, 'Invalid username or password')
    }
    const user = { username, role: entry.role }
    return { token: markSigned(sign({ username, role: entry.role }, this.cfg.JWT_SECRET, { expiresIn: this.cfg.JWT_EXPIRES_IN as jwt.SignOptions['expiresIn'] })), user }
  }

  verifyToken(token: string): AuthPrincipal | null {
    try {
      const payload = verify(token, this.cfg.JWT_SECRET) as jwt.JwtPayload
      if (typeof payload.username !== 'string' || !ROLE_SET.has(payload.role as Role)) return null
      return { username: payload.username, role: payload.role as Role }
    } catch {
      return null
    }
  }
}

function markSigned(token: string): string {
  return token
}