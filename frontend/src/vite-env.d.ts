/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend base URL. Empty string (default) = same origin via Vite dev proxy. */
  readonly VITE_API_BASE_URL: string
  /**
   * Controls the two data/execution fallbacks in one flag:
   *  - `"false"`  → production: AI Analytics hits the live backend only, and the
   *    Quantum Optimization page selects the HTTP adapter (`services/optimization/httpAdapter.ts`),
   *    which requires the quantum gateway API. The dev-only simulator chunk is never loaded.
   *  - anything else (default) → development: AI Analytics sample-data fallback is allowed,
   *    and Quantum Optimization runs on the clearly-flagged mock adapter (`mockAdapter.ts`).
   */
  readonly VITE_USE_MOCK_DATA: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}