/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend base URL. Empty string (default) = same origin via Vite dev proxy. */
  readonly VITE_API_BASE_URL: string
  /**
   * Controls the data/execution fallbacks:
   *  - `"false"` → forces live backends even in dev: disables the AI Analytics
   *    sample-data fallback and makes Quantum Optimization select the HTTP
   *    adapter (`services/optimization/httpAdapter.ts`).
   *  - unset / anything else → the AI Analytics sample fallback is PERMITTED
   *    but *only* when `import.meta.env.DEV` is true (never in production);
   *    Quantum Optimization keeps its existing mock/http adapter selection.
   */
  readonly VITE_USE_MOCK_DATA: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}