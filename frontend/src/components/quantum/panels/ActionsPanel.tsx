/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Activity, ClipboardList, FileJson, GitCompareArrows, Layers, Sigma } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { QuantumPanel } from '../QuantumPanel'
import type { QuantumModalKind } from '../../../types/optimization'

interface ActionsPanelProps {
  hasResult: boolean
  adapterMode: 'mock' | 'http' | null
  onOpen: (kind: QuantumModalKind) => void
  /** Job id routed to the standalone QUBO visualization page. */
  jobId?: string | null
}

const BUTTONS: { kind: QuantumModalKind; label: string; icon: typeof Sigma; hint: string }[] = [
  { kind: 'qubo', label: 'View QUBO', icon: Sigma, hint: 'Ising/QUBO matrix' },
  { kind: 'qaoa-job', label: 'View QAOA job', icon: Layers, hint: 'Job, counts, energy' },
  { kind: 'classical', label: 'Compare classical', icon: GitCompareArrows, hint: 'Greedy baseline' },
  { kind: 'final-result', label: 'View final result', icon: ClipboardList, hint: 'Signed decision' },
  { kind: 'export', label: 'Export result', icon: FileJson, hint: 'Download JSON artifact' },
]

export function ActionsPanel({ hasResult, adapterMode, onOpen, jobId }: ActionsPanelProps) {
  const navigate = useNavigate()
  return (
    <QuantumPanel
      step={7}
      icon={GitCompareArrows}
      title="Actions"
      description="Audit or export the signed result"
      status={hasResult ? 'done' : 'idle'}
      actions={
        <span className="rounded-md bg-forest-800/70 px-2 py-1 text-[11px] text-mist-500">
          {adapterMode === 'mock' ? 'development adapter' : 'live gateway'}
        </span>
      }
    >
      <div className="flex flex-wrap gap-2">
        {BUTTONS.map(({ kind, label, icon: Icon, hint }) => (
          <button
            key={kind}
            type="button"
            disabled={!hasResult}
            onClick={() => onOpen(kind)}
            title={hint}
            className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Icon size={15} className="text-ai-300" aria-hidden="true" />
            {label}
          </button>
        ))}
        <button
          type="button"
          disabled={!hasResult || !jobId}
          onClick={() => jobId && navigate(`/qubo-visualization/${encodeURIComponent(jobId)}`)}
          title="Open the full QUBO visualization page"
          className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Sigma size={15} className="text-ai-300" aria-hidden="true" />
          Open QUBO visualization
        </button>
        <button
          type="button"
          disabled={!jobId}
          onClick={() => jobId && navigate(`/quantum/jobs/${encodeURIComponent(jobId)}`)}
          title="Open the live Quantum Job Status page"
          className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Activity size={15} className="text-ai-300" aria-hidden="true" />
          Open job status
        </button>
      </div>
      {!hasResult && <p className="mt-3 text-xs text-mist-500">Finishing a run in step 6 unlocks the audit and export actions.</p>}
    </QuantumPanel>
  )
}