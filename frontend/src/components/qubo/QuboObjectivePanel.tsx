/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Target } from 'lucide-react'
import type { QuboFormulation } from '../../types/optimization'

export function QuboObjectivePanel({ objective }: { objective: QuboFormulation['objective'] }) {
  return (
    <div className="rounded-lg border border-forest-600 bg-forest-800/40 p-4">
      <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-mist-500">
        <Target size={13} className="text-emerald-400" aria-hidden="true" />
        Objective · {objective.target}
      </p>
      <code className="inline-block rounded-md border border-forest-600 bg-forest-900 px-2.5 py-1 font-mono text-sm text-ai-300">
        {objective.expression}
      </code>
      <p className="mt-2 text-xs leading-relaxed text-mist-400">{objective.explanation}</p>
    </div>
  )
}