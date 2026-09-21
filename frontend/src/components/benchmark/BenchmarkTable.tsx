/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import type { OptimizationResult, QuantumJobSummary } from '../../types/optimization'
import { benchmarkRows } from '../../lib/benchmark'

interface BenchmarkTableProps {
  summary: QuantumJobSummary
  result: OptimizationResult
}

/** The Metric | Classical | QAOA table — every cell is a stored value or a clear dash. */
export function BenchmarkTable({ summary, result }: BenchmarkTableProps) {
  const rows = benchmarkRows(summary, result)
  return (
    <section className="glass-card p-0" aria-label="Metric comparison table">
      <div className="border-b border-forest-700/70 px-5 py-3">
        <h2 className="text-sm font-semibold text-mist-100">Metric comparison</h2>
        <p className="text-[11px] text-mist-500">
          Values stored with the run — QAOA vs the persisted classical reference. '—' means the gateway records no value.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-xs">
          <caption className="sr-only">
            Quantum vs classical metric comparison for experiment {summary.jobId}.
          </caption>
          <thead>
            <tr className="border-b border-forest-700/70 text-[11px] uppercase tracking-wider text-mist-500">
              <th scope="col" className="whitespace-nowrap px-4 py-3 font-semibold text-mist-300">Metric</th>
              <th scope="col" className="whitespace-nowrap px-4 py-3 text-right font-semibold text-mist-300">Classical</th>
              <th scope="col" className="whitespace-nowrap px-4 py-3 text-right font-semibold text-mist-300">QAOA</th>
              <th scope="col" className="hidden px-4 py-3 font-semibold text-mist-300 lg:table-cell">Note</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.metric} className="border-b border-forest-800/80 transition-colors hover:bg-forest-800/40">
                <th scope="row" className="whitespace-nowrap px-4 py-3 font-medium text-mist-50">{row.metric}</th>
                <td className="px-4 py-3 text-right font-mono text-mist-200">{row.classical}</td>
                <td className="px-4 py-3 text-right font-mono text-mist-200">{row.qaoa}</td>
                <td className="hidden max-w-[360px] px-4 py-3 lg:table-cell">
                  <p className="text-[11px] leading-relaxed text-mist-500">{row.note ?? '—'}</p>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}