/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import type { NextFunction, Request, Response } from 'express'
import { AppError, ErrorCodes, type ErrorBody } from '../envelope.ts'

/** Express error middleware — always emits the shared error envelope. */
export function errorHandler(error: unknown, _req: Request, res: Response, _next: NextFunction): void {
  if (error instanceof AppError) {
    const body: ErrorBody = {
      success: false,
      error: { code: error.code, message: error.message, ...(error.details !== undefined && { details: error.details }) },
      timestamp: new Date().toISOString(),
    }
    res.status(error.status).json(body)
    return
  }
  console.error('[backend] unhandled error:', error)
  const body: ErrorBody = {
    success: false,
    error: { code: ErrorCodes.INTERNAL_ERROR, message: 'Unexpected server error' },
    timestamp: new Date().toISOString(),
  }
  res.status(500).json(body)
}

/** 404 handler for unknown routes. */
export function notFoundHandler(_req: Request, res: Response): void {
  res.status(404).json({
    success: false,
    error: { code: 'NOT_FOUND', message: 'Endpoint not found' },
    timestamp: new Date().toISOString(),
  })
}