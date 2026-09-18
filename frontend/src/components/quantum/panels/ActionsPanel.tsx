import { ClipboardList, FileJson, GitCompareArrows, Layers, Sigma } from 'lucide-react'
import { QuantumPanel } from '../QuantumPanel'
import type { QuantumModalKind } from '../../../types/optimization'

interface ActionsPanelProps {
  hasResult: boolean
  adapterMode: 'mock' | 'http' | null
  onOpen: (kind: QuantumModalKind) => void
}

const BUTTONS: { kind: QuantumModalKind; label: string; icon: typeof Sigma; hint: string }[] = [
  { kind: 'qubo', label: 'View QUBO', icon: Sigma, hint: 'Ising/QUBO matrix' },
  { kind: 'qaoa-job', label: 'View QAOA job', icon: Layers, hint: 'Job, counts, energy' },
  { kind: 'classical', label: 'Compare classical', icon: GitCompareArrows, hint: 'Greedy baseline' },
  { kind: 'final-result', label: 'View final result', icon: ClipboardList, hint: 'Signed decision' },
  { kind: 'export', label: 'Export result', icon: FileJson, hint: 'Download JSON artifact' },
]

export function ActionsPanel({ hasResult, adapterMode, onOpen }: ActionsPanelProps) {
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
      </div>
      {!hasResult && <p className="mt-3 text-xs text-mist-500">Finishing a run in step 6 unlocks the audit and export actions.</p>}
    </QuantumPanel>
  )
}