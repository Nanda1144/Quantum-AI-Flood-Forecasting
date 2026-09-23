/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Link2, Sigma, Scale } from 'lucide-react'
import type { QuboFormulation } from '../../types/optimization'

function Term({ label, value, children }: { label: string; value: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-forest-700/50 py-1.5 last:border-0">
      <span className="flex items-center gap-1.5 font-mono text-xs text-ai-300">{children}{label}</span>
      <span className="font-mono text-xs text-mist-100">{value}</span>
    </div>
  )
}

export function QuboTermPanels({ formulation }: { formulation: QuboFormulation }) {
  const { linear, quadratic, penalties, variables } = formulation
  const n = variables.length

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      {/* ---- Linear terms ---- */}
      <div className="rounded-lg border border-forest-600 bg-forest-800/40 p-3">
        <p className="mb-1 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-mist-500">
          <Link2 size={13} className="text-emerald-400" aria-hidden="true" />
          Linear terms (β)
        </p>
        {linear && linear.length > 0 ? (
          <div className="max-h-56 overflow-y-auto">
            {linear.map((value, index) => (
              <Term key={variables[index]} label={`· ${variables[index]}`} value={String(value)}>
                <span />
              </Term>
            ))}
          </div>
        ) : (
          <p className="text-xs text-mist-500">No stored linear coefficients.</p>
        )}
      </div>

      {/* ---- Quadratic terms ---- */}
      <div className="rounded-lg border border-forest-600 bg-forest-800/40 p-3">
        <p className="mb-1 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-mist-500">
          <Sigma size={13} className="text-emerald-400" aria-hidden="true" />
          Quadratic terms (Q)
        </p>
        {quadratic && quadratic.length > 0 ? (
          <div className="max-h-56 overflow-y-auto">
            {quadratic.map((row, rowIndex) =>
              row.map((value, colIndex) => {
                if (Math.abs(value) < 1e-9) return null
                return (
                  <Term
                    key={`${rowIndex}-${colIndex}`}
                    label={`${variables[rowIndex]} × ${variables[colIndex]}`}
                    value={String(value)}
                  >
                    <span />
                  </Term>
                )
              }),
            )}
          </div>
        ) : (
          <p className="text-xs text-mist-500">No stored quadratic coefficients.</p>
        )}
      </div>

      {/* ---- Penalty terms ---- */}
      <div className="rounded-lg border border-forest-600 bg-forest-800/40 p-3">
        <p className="mb-1 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-mist-500">
          <Scale size={13} className="text-amber-400" aria-hidden="true" />
          Penalty terms (P)
        </p>
        {penalties.length > 0 ? (
          <div>
            {penalties.map((penalty) => (
              <div key={penalty.key} className="border-b border-forest-700/50 py-1.5 last:border-0">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-mono text-xs text-amber-300">{penalty.name}</span>
                  <span className="font-mono text-xs text-mist-100">
                    {penalty.scale === null ? 'post-decode' : penalty.scale}
                  </span>
                </div>
                <p className="mt-0.5 font-mono text-[11px] text-mist-500">{penalty.formula}</p>
                <p className="mt-0.5 text-[11px] leading-snug text-mist-400">{penalty.detail}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-mist-500">No penalty terms in this QUBO — only the ${n}-variable objective remains.</p>
        )}
      </div>
    </div>
  )
}