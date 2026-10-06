/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Optimization adapter seams.
 *
 * The page never talks to a concrete executor directly. `getOptimizationAdapter()`
 * resolves to:
 *  - the **mock** adapter while `VITE_USE_MOCK_DATA !== 'false'` (development),
 *  - the **HTTP** adapter when the flag is `false` (production).
 *
 * The mock is gated behind that single, documented flag and is only bundled
 * through a dynamic import, so a production build that ships with sane env
 * defaults never loads the simulation code. Both adapters return the same
 * contract (types in `types/optimization.ts`); the UI renders an "adapter
 * mode" chip so a demo run is never mistaken for real quantum execution.
 */

import type {
  AdapterMode,
  CandidateLocation,
  OptimizeRequest,
  OptimizationResult,
  PipelineUpdate,
  ProviderProvenance,
  ResourceConstraints,
} from '../../types/optimization'
import type { RiskProfile } from '../../types/optimization'

export type AdapterLazyPromise = Promise<OptimizationAdapter>

export interface ProblemInputsRequest {
  candidateCount: number
  forecastReference: string
  riskProfile: RiskProfile
}

export interface OptimizationAdapter {
  readonly mode: AdapterMode
  getInputs(request: ProblemInputsRequest): Promise<OptimizationInputs>
  run(
    request: OptimizeRequest,
    onUpdate: (update: PipelineUpdate) => void,
    signal: AbortSignal,
  ): Promise<OptimizationResult>
}

export interface OptimizationInputs {
  candidates: CandidateLocation[]
  constraints: ResourceConstraints
  forecastRef: string | null
  providedBy: ProviderProvenance
}

const ALLOW_MOCK_DATA: boolean = import.meta.env.VITE_USE_MOCK_DATA !== 'false'

let lazyAdapter: OptimizationAdapter | null = null

export async function getOptimizationAdapter(): Promise<OptimizationAdapter> {
  if (lazyAdapter) return lazyAdapter
  if (ALLOW_MOCK_DATA) {
    const { MockOptimizationAdapter } = await import('./mockAdapter')
    lazyAdapter = new MockOptimizationAdapter()
  } else {
    const { HttpOptimizationAdapter } = await import('./httpAdapter')
    lazyAdapter = new HttpOptimizationAdapter()
  }
  return lazyAdapter
}

export function adapterModeAvailable(): AdapterMode {
  return ALLOW_MOCK_DATA ? 'mock' : 'http'
}