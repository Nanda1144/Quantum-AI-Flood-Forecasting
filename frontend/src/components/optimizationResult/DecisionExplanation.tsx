/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Compass, Info, ShieldAlert } from 'lucide-react'
import { GlassCard } from '../ui/GlassCard'
import { SectionHeader } from '../ui/SectionHeader'
import { decisionExplanation } from '../../lib/decision'
import type { OptimizationResult, QuantumJobSummary } from '../../types/optimization'

interface DecisionExplanationProps {
  summary: QuantumJobSummary
  result: OptimizationResult
}

export function DecisionExplanation({ summary, result }: DecisionExplanationProps) {
  const narrative = decisionExplanation(summary, result)

  return (
    <GlassCard>
      <SectionHeader
        icon={Compass}
        title="Decision explanation"
        description="Assembled from the stored result — no causes are inferred beyond the recorded inputs"
      />
      <p className="mt-4 text-sm font-semibold text-mist-100">{narrative.headline}</p>
      <ul className="mt-2 space-y-1.5">
        {narrative.reasons.map((reason) => (
          <li key={reason} className="flex items-start gap-2 text-xs text-mist-300">
            <span className="mt-1.5 size-1 shrink-0 rounded-full bg-emerald-400" aria-hidden="true" />
            {reason}
          </li>
        ))}
      </ul>

      <div className="mt-3 space-y-2">
        {narrative.caveats.map((caveat) => (
          <p key={caveat} className="flex items-start gap-2 rounded-lg border border-forest-700/60 bg-forest-800/40 px-3 py-2 text-xs text-mist-400">
            {caveat.startsWith('Constraint validation failed') ? (
              <ShieldAlert size={13} className="mt-0.5 shrink-0 text-critical-400" aria-hidden="true" />
            ) : (
              <Info size={13} className="mt-0.5 shrink-0 text-forest-400" aria-hidden="true" />
            )}
            {caveat}
          </p>
        ))}
      </div>
    </GlassCard>
  )
}
