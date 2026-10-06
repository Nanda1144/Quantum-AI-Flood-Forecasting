/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Link } from 'react-router-dom'
import { ArrowLeft, Atom, Download, Loader2, Scale } from 'lucide-react'

export type ExportState = 'idle' | 'loading' | 'error'

interface ResultActionsProps {
  jobId: string
  exportState: ExportState
  exportError: string | null
  onExport: () => void
}

const linkClass =
  'inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300'

export function ResultActions({ jobId, exportState, exportError, onExport }: ResultActionsProps) {
  const encoded = encodeURIComponent(jobId)
  return (
    <section className="glass-card flex flex-wrap items-center gap-2" aria-label="Result actions">
      <Link to={`/qubo-visualization/${encoded}`} className={linkClass}>
        <Atom size={15} className="text-ai-300" aria-hidden="true" />
        View QUBO
      </Link>
      <Link to={`/quantum/jobs/${encoded}`} className={linkClass}>
        <span className="size-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
        View Quantum Job
      </Link>
      <Link to="/quantum-benchmark" className={linkClass}>
        <Scale size={15} className="text-ai-300" aria-hidden="true" />
        View Benchmark
      </Link>
      <button
        type="button"
        onClick={onExport}
        disabled={exportState === 'loading'}
        className={`${linkClass} disabled:cursor-not-allowed disabled:opacity-60`}
      >
        {exportState === 'loading' ? (
          <Loader2 size={15} className="animate-spin text-ai-300" aria-hidden="true" />
        ) : (
          <Download size={15} className="text-ai-300" aria-hidden="true" />
        )}
        {exportState === 'loading' ? 'Exporting…' : 'Export Result'}
      </button>
      <Link to="/quantum-optimization" className={linkClass}>
        <ArrowLeft size={15} className="text-ai-300" aria-hidden="true" />
        Return to Optimization
      </Link>

      {exportState === 'error' && exportError && (
        <p className="w-full text-[11px] text-critical-400" role="alert">
          Export failed: {exportError}. The document is produced by the backend — no local copy was generated.
        </p>
      )}
      <p className="w-full text-[11px] text-mist-600">
        Export downloads the backend-generated document verbatim; it is never rebuilt in the browser.
      </p>
    </section>
  )
}
