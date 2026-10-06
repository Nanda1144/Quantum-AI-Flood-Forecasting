/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'
import type { PluginOption } from 'vite'

export default defineConfig({
  // vitest ships its own bundled vite whose Plugin types diverge from the
  // project's rolldown-based vite 8; cast to bridge the two. (This file runs
  // via vitest's esbuild at test time and is not part of the tsc build.)
  plugins: [react() as unknown as PluginOption],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    env: {
      // Tests default to NO sample-data fallback: the dashboard must prove it
      // renders real backend responses. Individual tests opt back in.
      VITE_USE_MOCK_DATA: 'false',
    },
  },
})