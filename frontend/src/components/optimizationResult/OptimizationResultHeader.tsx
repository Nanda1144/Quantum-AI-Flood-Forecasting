/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { ClipboardCheck } from 'lucide-react'
import type { QuantumJobSummary } from '../../types/optimization'
import { PROBLEM_TYPES } from '../../lib/quantum'
import { formatDateTime } from '../../lib/format'

const BACKEND_LABELS: Record<string, string> = {
  qflare_simulator_statevector: 'Q-Flare · statevector',
  aer_simulator_statevector: 'Aer · statevector',
  aer_simulator_matrix_product_state: 'Aer · MPS',
  ibm_brisbane: 'ibm_brisbane',
  ibm_kyiv: 'ibm_kyiv',
  classical: 'Classical reference',
}

const EXECUTION_MODE_LABELS: Record<string, string> = {
  simulator: 'Simulator',
  aer: 'Aer simulator',
  ibm_hardware: 'IBM Quantum hardware',
  classical: 'Classical',
}

interface OptimizationResultHeaderProps {
  summary: QuantumJobSummary
}

function Chip({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <span
      className="inline-flex items-center gap-2 rounded-lg border border-forest-600/70 bg-forest-800/70 px-2.5 py-1 text-xs"
      title={title}
    >
      <span className="uppercase tracking-wide text-mist-600">{label}</span>
      <span className="font-mono text-mist-300">{value}</span>
    </span>
  )
}

export function OptimizationResultHeader({ summary }: OptimizationResultHeaderProps) {
  const problem = PROBLEM_TYPES[summary.problemType]?.label ?? summary.problemType
  const backend = BACKEND_LABELS[summary.backendUsed] ?? summary.backendUsed
  const mode = EXECUTION_MODE_LABELS[summary.executionModeUsed] ?? summary.executionModeUsed

  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex items-center gap-3">
        <span className="glass-card flex size-12 shrink-0 items-center justify-center text-ai-300">
          <ClipboardCheck size={24} aria-hidden="true" />
        </span>
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-mist-50">Optimization Result</h1>
          <p className="text-sm text-mist-500">
            Validated decision document — the stored outcome, its evidence and its limits
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Chip label="Job ID" value={summary.jobId} title="Optimization job identity" />
        <Chip label="Problem" value={problem} />
        <Chip label="Completed" value={formatDateTime(summary.completedAt)} />
        <Chip label="Algorithm" value={summary.algorithm} />
        <Chip label="Backend" value={backend} />
        <Chip label="Mode" value={mode} />
      </div>
    </header>
  )
}
