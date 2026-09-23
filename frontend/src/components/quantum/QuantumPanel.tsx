/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { GlassCard } from '../ui/GlassCard'

interface QuantumPanelProps {
  step: number
  icon: LucideIcon
  title: string
  description: string
  children: ReactNode
  actions?: ReactNode
  status?: 'idle' | 'ready' | 'running' | 'done'
}

const statusDot: Record<NonNullable<QuantumPanelProps['status']>, string> = {
  idle: 'bg-forest-500',
  ready: 'bg-ai-400',
  running: 'bg-emerald-400 animate-pulse',
  done: 'bg-emerald-300',
}

export function QuantumPanel({ step, icon: Icon, title, description, children, actions, status = 'idle' }: QuantumPanelProps) {
  return (
    <GlassCard className="stage-enter">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span
            className={`flex size-8 shrink-0 items-center justify-center rounded-lg border font-mono text-xs font-semibold ${
              status === 'done' ? 'border-emerald-500/50 bg-emerald-500/15 text-emerald-300' : 'border-forest-600 bg-forest-800 text-mist-300'
            }`}
          >
            {step}
          </span>
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-forest-600 bg-forest-800 text-ai-300">
            <Icon size={18} aria-hidden="true" />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold tracking-wide text-mist-50">{title}</h2>
              {status !== 'idle' && (
                <span className={`size-1.5 rounded-full ${statusDot[status]}`} aria-label={`Status: ${status}`} />
              )}
            </div>
            <p className="text-xs text-mist-500">{description}</p>
          </div>
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {children}
    </GlassCard>
  )
}