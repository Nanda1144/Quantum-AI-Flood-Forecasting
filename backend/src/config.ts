/**
 * Backend configuration, validated at startup from environment variables.
 *
 * No secrets are ever exposed to the frontend — everything below is
 * server-side only and loaded via dotenv from the service's `.env`.
 */

import { config as dotenvConfig } from 'dotenv'
import { z } from 'zod'

dotenvConfig()

/** Role model for RBAC. */
export type Role = 'admin' | 'operator' | 'viewer'
export const ROLES: readonly Role[] = ['admin', 'operator', 'viewer'] as const

/** Demo user entries — populated from AUTH_USERS (JSON) in production setup. */
export interface AuthUser {
  password: string
  role: Role
}

const roleSchema = z.enum(ROLES)

const envSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).optional().default('development'),
  PORT: z.coerce.number().int().positive().optional().default(3000),
  DATABASE_URL: z
    .string()
    .url()
    .optional()
    .default('postgresql://qflare:qflare@localhost:5432/qflare'),

  /** When true every /api route requires a valid JWT (production default). */
  AUTH_ENABLED: z
    .enum(['true', 'false'])
    .optional()
    .default('true')
    .transform((v) => v === 'true'),
  JWT_SECRET: z.string().min(16).optional().default('dev-only-change-me-please-32chars'),
  JWT_EXPIRES_IN: z.string().optional().default('8h'),

  /** FastAPI forecasting service connection. */
  AI_SERVICE_URL: z.string().url().optional().default('http://localhost:8000'),
  AI_REQUEST_TIMEOUT_MS: z.coerce.number().int().positive().optional().default(5000),

  /** Forecasts older than this are considered stale (drives STALE_DATA). */
  FRESHNESS_STALE_MS: z.coerce.number().int().positive().optional().default(90_000),

  /**
   * Primary metric of the documented model-selection policy (see
   * backend/README.md "Model selection policy"). Lower bounds are better for
   * mae/rmse/inferenceTime; higher is better for r2/nse.
   */
  MODEL_SELECTION_METRIC: z
    .enum(['mae', 'rmse', 'r2', 'nse', 'inferenceTime'])
    .optional()
    .default('r2'),

  /** Rate limiting. */
  RATE_LIMIT_WINDOW_MS: z.coerce.number().int().positive().optional().default(60_000),
  RATE_LIMIT_MAX: z.coerce.number().int().positive().optional().default(120),

  /**
   * Quantum FastAPI service connection (`quantum-service`). The orchestration
   * backend drives QUBO construction and QAOA execution through this service;
   * a failure here never brings the API itself down (see FALLBACK_POLICY).
   */
  QUANTUM_SERVICE_URL: z.string().url().optional().default('http://localhost:8100'),
  QUANTUM_REQUEST_TIMEOUT_MS: z.coerce.number().int().positive().optional().default(15_000),

  /**
   * Wall-clock cap on a whole optimization job. Exceeding it fails the job
   * with `EXECUTION_TIMEOUT` rather than leaving it running forever.
   */
  OPTIMIZATION_EXECUTION_TIMEOUT_MS: z.coerce.number().int().positive().optional().default(120_000),

  /**
   * What to do when the configured quantum execution path fails (hardware
   * down, Aer unavailable, QUBO generation error, …):
   *   - `retry_simulator` (default): retry the failed stage on the simulator.
   *   - `classical_only`:   skip QAOA and return the classical reference result.
   *   - `error`:            fail the job immediately.
   * The system stays available in every mode — the orchestrator never depends
   * on one executor being up.
   */
  OPTIMIZATION_FALLBACK_POLICY: z
    .enum(['retry_simulator', 'classical_only', 'error'])
    .optional()
    .default('retry_simulator'),

  /** Maximum candidate count the classical reference solver exhaustively solves. */
  OPTIMIZATION_EXHAUSTIVE_LIMIT: z.coerce.number().int().positive().optional().default(18),

  /** Stricter per-window cap on the expensive POST /api/optimization/run. */
  OPTIMIZATION_RUN_LIMIT_MAX: z.coerce.number().int().positive().optional().default(10),

  /** Demo RBAC users as JSON: {"alice": {"password": "...", "role": "admin"}}. */
  AUTH_USERS: z.preprocess((value) => {
    if (typeof value !== 'string' || value === '') return undefined
    return JSON.parse(value) as Record<string, AuthUser>
  }, z.record(
    z.string(),
    z.object({ password: z.string().min(1), role: roleSchema }),
  ).optional()),
})

type Env = z.infer<typeof envSchema>

const parsed = envSchema.parse(process.env)

/** Default demo users — used ONLY when AUTH_USERS is not supplied. */
export const DEFAULT_USERS: Record<string, AuthUser> = {
  admin: { password: 'qflare-admin', role: 'admin' },
  operator: { password: 'qflare-operator', role: 'operator' },
  viewer: { password: 'qflare-viewer', role: 'viewer' },
}

export const config: Env & { users: Record<string, AuthUser> } = {
  ...parsed,
  users: parsed.AUTH_USERS ?? DEFAULT_USERS,
}