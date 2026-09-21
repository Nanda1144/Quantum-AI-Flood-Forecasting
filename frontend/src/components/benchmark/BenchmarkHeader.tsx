/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Beaker, RefreshCw, Scale } from 'lucide-react'
import { formatDateTime } from '../../lib/format'

interface BenchmarkHeaderProps {
  experimentCount: number
  newestCompletedAt: string | null
  refreshing: boolean
  onRefresh: () => void
}

export function BenchmarkHeader({ experimentCount, newestCompletedAt, refreshing, onRefresh }: BenchmarkHeaderProps) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        <span className="glass-card flex size-12 shrink-0 items-center justify-center text-ai-300">
          <Scale size={24} aria-hidden="true" />
        </span>
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-mist-50">Quantum vs Classical Benchmark</h1>
          <p className="mt-1 text-sm text-mist-400">Experimental Solution Quality and Runtime Comparison</p>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-mist-300">
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-forest-600 bg-forest-800/70 px-2.5 py-1">
              <Beaker size={13} aria-hidden="true" />
              <span>
                {experimentCount === 0
                  ? 'No completed experiments yet'
                  : experimentCount === 1
                    ? '1 completed experiment'
                    : `${experimentCount} completed experiments`}
              </span>
            </span>
            {newestCompletedAt && (
              <span className="rounded-lg border border-forest-600 bg-forest-800/70 px-2.5 py-1">
                Newest: {formatDateTime(newestCompletedAt)}
              </span>
            )}
          </div>
        </div>
      </div>
      <button
        type="button"
        onClick={onRefresh}
        aria-label="Refresh the experiment ledger"
        className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800 px-3.5 py-2 text-xs font-semibold transition-colors hover:border-emerald-500/60 hover:text-emerald-300 focus-visible:outline-2 focus-visible:outline-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
        disabled={refreshing}
      >
        <RefreshCw size={14} aria-hidden="true" className={refreshing ? 'animate-spin' : ''} />
        {refreshing ? 'Refreshing…' : 'Refresh'}
      </button>
    </header>
  )
}