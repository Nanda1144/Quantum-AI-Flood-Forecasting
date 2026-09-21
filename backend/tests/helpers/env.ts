/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

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