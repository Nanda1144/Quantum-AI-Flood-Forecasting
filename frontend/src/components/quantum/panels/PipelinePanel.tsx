/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Activity, Check, CircleDashed, Loader2, X } from 'lucide-react'
import type { PipelineStage } from '../../../types/optimization'
import type { RunState } from '../../../hooks/useQuantumOptimization'
import { QuantumPanel } from '../QuantumPanel'

interface PipelinePanelProps {
  stages: PipelineStage[]
  runState: RunState
}

const stageIcon = (stage: PipelineStage) => {
  if (stage.status === 'running') return <Loader2 size={15} className="animate-spin" aria-hidden="true" />
  if (stage.status === 'done') return <Check size={15} aria-hidden="true" />
  if (stage.status === 'failed') return <X size={15} aria-hidden="true" />
  return <CircleDashed size={15} aria-hidden="true" />
}

const stageStyle: Record<PipelineStage['status'], string> = {
  pending: 'text-forest-500',
  running: 'border-emerald-500/60 bg-emerald-500/15 text-emerald-300',
  done: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  failed: 'border-critical-500/60 bg-critical-500/15 text-critical-400',
}

export function PipelinePanel({ stages, runState }: PipelinePanelProps) {
  const anyStarted = stages.some((stage) => stage.status !== 'pending')

  return (
    <QuantumPanel
      step={5}
      icon={Activity}
      title="Live pipeline"
      description="Every stage is surfaced — nothing hidden"
      status={runState === 'running' ? 'running' : runState === 'done' ? 'done' : anyStarted ? 'idle' : 'idle'}
    >
      {!anyStarted ? (
        <div className="rounded-lg border border-dashed border-forest-600 px-3 py-4 text-center text-xs text-mist-500">
          Execute in step 4 to stream the pipeline stages here.
        </div>
      ) : (
        <ol className="space-y-1.5">
          {stages.map((stage, index) => {
            const open = stage.status === 'running' || stage.status === 'failed' || runState === 'running'
            return (
              <li
                key={stage.id}
                className={`flex items-start gap-3 rounded-lg border px-3 py-2 transition-colors ${
                  stage.status === 'failed'
                    ? 'border-critical-500/40 bg-critical-500/10'
                    : stage.status === 'running'
                      ? 'border-emerald-500/40 bg-emerald-500/10'
                      : 'border-forest-700/60 bg-forest-800/40'
                }`}
              >
                <span
                  className={`mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md border ${
                    stage.status === 'pending' ? 'border-forest-600 text-forest-500' : stageStyle[stage.status]
                  }`}
                >
                  {stageIcon(stage)}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <p className="text-sm font-medium text-mist-100">
                      <span className="mr-2 font-mono text-[11px] text-mist-500">{index + 1}</span>
                      {stage.label}
                    </p>
                    {stage.status !== 'pending' && (
                      <span className="text-[11px] uppercase tracking-wide text-mist-500">{stage.status}</span>
                    )}
                  </div>
                  {open && stage.detail && <p className="mt-0.5 text-xs text-mist-300">{stage.detail}</p>}
                  {stage.error && <p className="mt-0.5 text-xs text-critical-400">{stage.error}</p>}
                  {stage.meta && Object.keys(stage.meta).length > 0 && (
                    <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-mist-500">
                      {Object.entries(stage.meta).map(([key, value]) => (
                        <span key={key}>
                          <span className="text-mist-600">{key}:</span> {value}
                        </span>
                      ))}
                    </p>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </QuantumPanel>
  )
}