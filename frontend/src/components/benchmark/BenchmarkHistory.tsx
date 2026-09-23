/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Experiment history — every completed, comparable experiment in the caller's
 * ledger, newest first (served by the gateway's benchmark ledger endpoint).
 * Every row carries a stored result by construction; nothing is implied about
 * runs the gateway recorded no benchmark for, because this ledger never
 * includes them.
 */

import { Check, CircleDashed, FlaskConical, type LucideIcon } from 'lucide-react'
import type { BenchmarkListEntry } from '../../types/benchmark'
import { isLedgerEntryComplete } from '../../lib/benchmark'
import { formatDateTime, formatDuration } from '../../lib/format'

interface BenchmarkHistoryProps {
  ledger: BenchmarkListEntry[]
  selectedJobId: string | null
  onSelect: (jobId: string) => void
}

export function BenchmarkHistory({ ledger, selectedJobId, onSelect }: BenchmarkHistoryProps) {
  return (
    <section className="glass-card p-0" aria-label="Experiment history">
      <div className="border-b border-forest-700/70 px-5 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-mist-100">
          <FlaskConical size={15} className="text-ai-300" aria-hidden="true" />
          Experiment history
        </h2>
        <p className="text-[11px] text-mist-500">
          Select a previous run. Only completed experiments with a stored benchmark can be compared.
        </p>
      </div>
      <ul className="max-h-[420px] overflow-y-auto p-2">
        {ledger.length === 0 && (
          <li className="px-3 py-6 text-center text-xs text-mist-600">
            No experiments are visible to your account yet.
          </li>
        )}
        {ledger.map((entry) => {
          const complete = isLedgerEntryComplete(entry)
          const selected = entry.jobId === selectedJobId
          const Icon: LucideIcon = complete ? Check : CircleDashed
          const objectiveText =
            entry.quantum.objectiveValue !== null && Number.isFinite(entry.quantum.objectiveValue)
              ? `${(entry.quantum.objectiveValue * 100).toFixed(1)}%`
              : '—'
          const ratioText = entry.approximationRatio.value !== null ? entry.approximationRatio.value.toFixed(2) : '—'
          const runtimeText = formatDuration(entry.quantum.runtimeMs ?? entry.classical.runtimeMs ?? undefined)
          return (
            <li key={entry.jobId}>
              <button
                type="button"
                onClick={() => (complete ? onSelect(entry.jobId) : undefined)}
                disabled={!complete}
                aria-pressed={selected && complete}
                className={`flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors ${
                  selected && complete
                    ? 'border-emerald-500/50 bg-emerald-500/10'
                    : complete
                      ? 'border-forest-700/60 bg-forest-800/40 hover:border-emerald-500/50 hover:bg-forest-800/70'
                      : 'cursor-not-allowed border-forest-800 bg-forest-900/40 opacity-50'
                }`}
              >
                <span
                  className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border ${
                    selected && complete
                      ? 'border-emerald-500/60 text-emerald-300'
                      : 'border-forest-600 text-forest-500'
                  }`}
                  title={complete ? 'Has a stored benchmark result' : 'No completed benchmark yet'}
                >
                  <Icon size={12} aria-hidden="true" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span className="truncate font-mono text-xs font-semibold text-mist-100">{entry.jobId}</span>
                    <span className="text-[10px] uppercase tracking-wide text-mist-500">{entry.status}</span>
                  </span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[11px] text-mist-400">
                    <span className="capitalize">{entry.problemType.replace('_', ' ')}</span>
                    <span>
                      {complete
                        ? `objective ${objectiveText} · ratio ${ratioText} · ${runtimeText}`
                        : `created ${formatDateTime(entry.createdAt)}`}
                    </span>
                    <span>{formatDateTime(entry.completedAt ?? entry.createdAt)}</span>
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}