/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import type { NextFunction, Request, Response } from 'express'
import type { ZodType } from 'zod'
import { AppError, ErrorCodes } from '../envelope.ts'

/** Parsed request values, attached after validation so handlers read them. */
export interface ValidatedRequest {
  params?: unknown
  query?: unknown
  body?: unknown
}

declare module 'express-serve-static-core' {
  interface Request {
    validated?: ValidatedRequest
  }
}

/**
 * Validates request params/query/body with a Zod schema. Invalid input is
 * rejected (422) — values are never silently coerced or defaulted. Parsed
 * values are exposed on `req.validated` (re-assigning `req.params`/`req.query`
 * is impossible — Express exposes them as getter-only).
 */
export function validate(schema: {
  params?: ZodType
  query?: ZodType
  body?: ZodType
}) {
  return (req: Request, _res: Response, next: NextFunction): void => {
    try {
      const validated: ValidatedRequest = {}
      if (schema.params) validated.params = schema.params.parse(req.params)
      if (schema.query) validated.query = schema.query.parse(req.query)
      if (schema.body) validated.body = schema.body.parse(req.body)
      req.validated = validated
      next()
    } catch (error) {
      const issues = zIssues(error)
      next(new AppError(422, ErrorCodes.VALIDATION_ERROR, 'Request validation failed', issues))
    }
  }
}

function zIssues(error: unknown): unknown {
  if (typeof error === 'object' && error !== null && 'issues' in error) {
    return (error as { issues: unknown }).issues
  }
  return undefined
}