/**
 * Sets test-only environment BEFORE any backend module is imported.
 * Import this first in test files.
 */
process.env.NODE_ENV = 'test'
process.env.DATABASE_MODE = 'memory'
process.env.AUTH_ENABLED = 'true'
process.env.JWT_SECRET = 'test-secret-at-least-16-characters'
process.env.FRESHNESS_STALE_MS = '90000'
process.env.RATE_LIMIT_MAX = '10000'

export {}