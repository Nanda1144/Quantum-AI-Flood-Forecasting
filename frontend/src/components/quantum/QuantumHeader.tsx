/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Atom, CloudRain, MapPin, ShieldAlert } from 'lucide-react'
import type { ReactElement } from 'react'
import type { RiskProfile } from '../../types/optimization'
import { riskProfileLabel } from '../../lib/quantum'
import type { OptimizationInputsResult } from '../../types/optimization'

interface QuantumHeaderProps {
  adapterMode: 'mock' | 'http' | null
  inputs: OptimizationInputsResult | null
  forecastReference: string
  riskProfile: RiskProfile
}

function backChip(icon: ReactElement, label: string, from: string) {
  return (
    <span
      title={from}
      className="inline-flex items-center gap-1.5 rounded-lg border border-forest-600/70 bg-forest-800/70 px-2.5 py-1 text-xs text-mist-300"
    >
      {icon}
      {label}
    </span>
  )
}

export function QuantumHeader({ adapterMode, inputs, forecastReference, riskProfile }: QuantumHeaderProps) {
  const isMock = adapterMode === 'mock'
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex items-center gap-3">
        <span className="glass-card flex size-12 shrink-0 items-center justify-center text-ai-300">
          <Atom size={24} aria-hidden="true" />
        </span>
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-mist-50">Quantum Optimization</h1>
          <p className="text-sm text-mist-500">
            AI-Guided Combinatorial Decision Optimization
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {inputs && (
          <>
            {backChip(<MapPin size={14} className="text-emerald-300" aria-hidden="true" />, inputs.providedBy.candidateLocations, 'GIS module')}
            {backChip(<CloudRain size={14} className="text-ai-300" aria-hidden="true" />, inputs.providedBy.forecast, 'AI forecasting')}
            {backChip(<ShieldAlert size={14} className="text-amber-400" aria-hidden="true" />, inputs.providedBy.resourceConstraints, 'Planning module')}
          </>
        )}
        {forecastReference && (
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-forest-600/70 bg-forest-800/70 px-2.5 py-1 font-mono text-xs text-mist-300">
            {forecastReference}
          </span>
        )}
        <span
          className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium ${
            isMock
              ? 'border-ai-500/50 bg-ai-500/10 text-ai-300'
              : 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
          }`}
        >
          <span className={`size-1.5 rounded-full ${isMock ? 'bg-ai-400' : 'bg-emerald-400'}`} />
          {isMock ? 'DEV SIMULATOR' : 'LIVE GATEWAY'}
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-xs font-medium text-amber-400">
          <ShieldAlert size={14} aria-hidden="true" />
          {riskProfileLabel(riskProfile)} risk
        </span>
      </div>
    </header>
  )
}