import { rateLimit } from 'express-rate-limit'
import { config } from '../config.ts'

/**
 * Tests run hundreds of requests through supertest against the same app
 * instance; bypass limiter bookkeeping there so outcomes reflect the API
 * contract rather than shared quota state.
 */
const skipInTest = (): boolean => config.NODE_ENV === 'test'

/** General API rate limiter. */
export const apiLimiter = rateLimit({
  windowMs: config.RATE_LIMIT_WINDOW_MS,
  limit: config.RATE_LIMIT_MAX,
  standardHeaders: 'draft-7',
  legacyHeaders: false,
  skip: skipInTest,
  message: {
    success: false,
    error: { code: 'RATE_LIMITED', message: 'Too many requests, please slow down' },
    timestamp: new Date().toISOString(),
  },
})

/** Stricter limiter for authentication attempts. */
export const authLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  limit: 20,
  standardHeaders: 'draft-7',
  legacyHeaders: false,
  skip: skipInTest,
  message: {
    success: false,
    error: { code: 'RATE_LIMITED', message: 'Too many login attempts, please try again later' },
    timestamp: new Date().toISOString(),
  },
})

/** Stricter limiter for the expensive `POST /api/optimization/run`. */
export const optimizationRunLimiter = rateLimit({
  windowMs: config.RATE_LIMIT_WINDOW_MS,
  limit: config.OPTIMIZATION_RUN_LIMIT_MAX,
  standardHeaders: 'draft-7',
  legacyHeaders: false,
  skip: skipInTest,
  message: {
    success: false,
    error: { code: 'RATE_LIMITED', message: 'Too many optimization runs, please slow down' },
    timestamp: new Date().toISOString(),
  },
})