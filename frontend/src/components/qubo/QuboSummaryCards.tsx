/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import type { ReactElement } from 'react'
import { Layers, Link2, Scale, Sigma, Variable } from 'lucide-react'
import type { QuboFormulation } from '../../types/optimization'

const CARD_ICONS: Record<keyof QuboFormulation['summary'], ReactElement> = {
  variables: <Variable size={16} aria-hidden="true" />,
  linearTerms: <Link2 size={16} aria-hidden="true" />,
  quadraticTerms: <Sigma size={16} aria-hidden="true" />,
  constraints: <Layers size={16} aria-hidden="true" />,
  penaltyStrength: <Scale size={16} aria-hidden="true" />,
}

const CARD_LABELS: Record<keyof QuboFormulation['summary'], string> = {
  variables: 'Variables',
  linearTerms: 'Linear terms',
  quadraticTerms: 'Quadratic terms',
  constraints: 'Constraints',
  penaltyStrength: 'Penalty strength (P)',
}

function MetricCard({ value }: { value: number | null }) {
  return (
    <p className="mt-0.5 font-mono text-sm text-mist-50">{value === null ? '—' : String(value)}</p>
  )
}

export function QuboSummaryCards({ summary }: { summary: QuboFormulation['summary'] }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {(Object.keys(summary) as (keyof QuboFormulation['summary'])[]).map((key) => (
        <div
          key={key}
          className="rounded-lg border border-forest-600 bg-forest-800/50 px-3 py-2.5"
        >
          <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-mist-500">
            <span className="text-emerald-400">{CARD_ICONS[key]}</span>
            {CARD_LABELS[key]}
          </div>
          <MetricCard value={summary[key]} />
        </div>
      ))}
    </div>
  )
}