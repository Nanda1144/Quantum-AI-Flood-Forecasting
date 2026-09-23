/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { pathToFileURL } from 'node:url'
import { config } from './config.ts'
import { createApp } from './app.ts'

/* Bootstrap the HTTP server only when this file is the entry point. */
const isMain = process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href

if (isMain) {
  const app = await createApp()
  app.listen(config.PORT, () => {
    console.log(
      `[backend] listening on http://localhost:${config.PORT} (auth: ${config.AUTH_ENABLED ? 'enabled' : 'DISABLED (demo)'}, mode: ${process.env.DATABASE_MODE ?? 'postgres'})`,
    )
  })
}

export { createApp }