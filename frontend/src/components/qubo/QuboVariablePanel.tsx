/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { MapPin } from 'lucide-react'
import type { QuboFormulation } from '../../types/optimization'

export function QuboVariablePanel({ variablesDetail }: { variablesDetail: QuboFormulation['variablesDetail'] }) {
  return (
    <div className="rounded-lg border border-forest-600 bg-forest-800/40 p-4">
      <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-mist-500">
        <MapPin size={13} className="text-emerald-400" aria-hidden="true" />
        Decision variables · sites
      </p>
      {variablesDetail.length === 0 ? (
        <p className="text-xs text-mist-500">No variable details were served.</p>
      ) : (
        <div className="max-h-64 overflow-y-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-forest-600 bg-forest-800 text-mist-500">
                <th className="px-2 py-1.5 font-medium">Variable</th>
                <th className="px-2 py-1.5 font-medium">Site / zone</th>
                <th className="px-2 py-1.5 text-right font-medium">Selected</th>
              </tr>
            </thead>
            <tbody>
              {variablesDetail.map((variable) => (
                <tr key={variable.id} className="border-b border-forest-700/50 last:border-0">
                  <td className="px-2 py-1.5 font-mono text-ai-300">{variable.id}</td>
                  <td className="px-2 py-1.5 text-mist-300">{variable.semantic}</td>
                  <td className="px-2 py-1.5 text-right">
                    <span
                      className={`rounded px-1.5 py-px font-mono text-[11px] ${
                        variable.selected
                          ? 'bg-emerald-500/15 text-emerald-300'
                          : 'bg-forest-700/60 text-mist-500'
                      }`}
                    >
                      {variable.selected ? '1' : '0'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}