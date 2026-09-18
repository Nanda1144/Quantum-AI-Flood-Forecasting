/**
 * Shared API envelope + error contract for the Q-FLARE backend.
 *
 * Success:  { success: true, data: {...}, timestamp: "..." }
 * Error:    { success: false, error: { code, message, details? }, timestamp: "..." }
 */

export interface SuccessBody<T> {
  success: true
  data: T
  timestamp: string
}

export interface ErrorBody {
  success: false
  error: {
    code: string
    message: string
    details?: unknown
  }
  timestamp: string
}

export type ApiBody<T> = SuccessBody<T> | ErrorBody

/** Standardised error codes returned by the backend. */
export const ErrorCodes = {
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  UNAUTHORIZED: 'UNAUTHORIZED',
  FORBIDDEN: 'FORBIDDEN',
  AI_SERVICE_UNAVAILABLE: 'AI_SERVICE_UNAVAILABLE',
  FORECAST_NOT_FOUND: 'FORECAST_NOT_FOUND',
  MODEL_NOT_FOUND: 'MODEL_NOT_FOUND',
  STALE_DATA: 'STALE_DATA',
  RATE_LIMITED: 'RATE_LIMITED',
  OPTIMIZATION_CONFLICT: 'OPTIMIZATION_CONFLICT',
  JOB_NOT_FOUND: 'JOB_NOT_FOUND',
  NO_CANDIDATES: 'NO_CANDIDATES',
  INVALID_OBJECTIVE_WEIGHTS: 'INVALID_OBJECTIVE_WEIGHTS',
  INFEASIBLE_BUDGET: 'INFEASIBLE_BUDGET',
  UNSUPPORTED_PROBLEM_TYPE: 'UNSUPPORTED_PROBLEM_TYPE',
  QUBO_GENERATION_FAILED: 'QUBO_GENERATION_FAILED',
  QAOA_EXECUTION_FAILED: 'QAOA_EXECUTION_FAILED',
  QUANTUM_UNAVAILABLE: 'QUANTUM_UNAVAILABLE',
  DECODING_FAILED: 'DECODING_FAILED',
  EXECUTION_TIMEOUT: 'EXECUTION_TIMEOUT',
  INTERNAL_ERROR: 'INTERNAL_ERROR',
} as const

export type ErrorCode = (typeof ErrorCodes)[keyof typeof ErrorCodes]

/** Application error carrying an HTTP status, code, and optional details. */
export class AppError extends Error {
  constructor(
    readonly status: number,
    readonly code: ErrorCode,
    message: string,
    readonly details?: unknown,
  ) {
    super(message)
    this.name = 'AppError'
  }
}

export function success<T>(data: T): SuccessBody<T> {
  return { success: true, data, timestamp: new Date().toISOString() }
}