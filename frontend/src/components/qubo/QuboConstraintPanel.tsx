/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { AlertTriangle, CheckCircle2, HelpCircle, Layers } from 'lucide-react'
import type { QuboFormulation } from '../../types/optimization'

function StatusPill({ status }: { status: 'satisfied' | 'violated' | 'unknown' }) {
  if (status === 'satisfied')
    return (
      <span className="flex items-center gap-1 rounded-md bg-emerald-500/15 px-1.5 py-0.5 text-[11px] text-emerald-300">
        <CheckCircle2 size={11} aria-hidden="true" /> satisfied
      </span>
    )
  if (status === 'violated')
    return (
      <span className="flex items-center gap-1 rounded-md bg-critical-500/20 px-1.5 py-0.5 text-[11px] text-critical-400">
        <AlertTriangle size={11} aria-hidden="true" /> violated
      </span>
    )
  return (
    <span className="flex items-center gap-1 rounded-md bg-forest-700/60 px-1.5 py-0.5 text-[11px] text-mist-500">
      <HelpCircle size={11} aria-hidden="true" /> unknown
    </span>
  )
}

export function QuboConstraintPanel({ constraints, penaltyScale }: { constraints: QuboFormulation['constraints']; penaltyScale: number | null }) {
  return (
    <div className="rounded-lg border border-forest-600 bg-forest-800/40 p-4">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-mist-500">
        <Layers size={13} className="text-emerald-400" aria-hidden="true" />
        Constraint enforcement
        {penaltyScale !== null && (
          <span className="ml-auto rounded border border-forest-600 bg-forest-900 px-1.5 py-0.5 font-mono text-[11px] normal-case text-amber-300">
            P = {penaltyScale}
          </span>
        )}
      </div>
      {constraints.length === 0 ? (
        <p className="text-xs text-mist-500">No operator constraints were configured for this run.</p>
      ) : (
        <ul className="space-y-1.5">
          {constraints.map((constraint) => (
            <li key={constraint.key} className="rounded-lg border border-forest-700/60 bg-forest-900/50 px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-mist-100">{constraint.name}</span>
                <StatusPill status={constraint.status} />
              </div>
              <p className="mt-1 text-[11px] leading-snug text-mist-400">{constraint.detail}</p>
              <div className="mt-1 flex flex-wrap items-center gap-3 font-mono text-[11px] text-mist-500">
                <span>limit: {constraint.configuredLimit}</span>
                <span>
                  QUBO: {constraint.penalty === null ? '—' : constraint.penalty}
                </span>
                <span
                  className={`rounded px-1 py-px text-[10px] ${
                    constraint.penaltyKind === 'qubo'
                      ? 'bg-amber-500/15 text-amber-300'
                      : constraint.penaltyKind === 'post_decode'
                        ? 'bg-ai-500/15 text-ai-300'
                        : 'bg-forest-700/60 text-mist-500'
                  }`}
                >
                  {constraint.penaltyKind === 'post_decode' ? 'post-decode' : constraint.penaltyKind ?? 'none'}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}