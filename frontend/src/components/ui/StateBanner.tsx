/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { AlertTriangle, CloudOff, Database, RotateCw, Sparkles } from 'lucide-react'
import type { ReactNode } from 'react'

type StateKind = 'error' | 'empty' | 'stale' | 'unavailable' | 'demo'

interface StateBannerProps {
  kind: StateKind
  title: string
  message: string
  onRetry?: () => void
  children?: ReactNode
}

const styles: Record<StateKind, { icon: ReactNode; panel: string; accent: string }> = {
  error: {
    icon: <AlertTriangle size={18} aria-hidden="true" />,
    panel: 'border-critical-500/40 bg-critical-500/10',
    accent: 'text-critical-400',
  },
  empty: {
    icon: <Database size={18} aria-hidden="true" />,
    panel: 'border-forest-600 bg-forest-800/60',
    accent: 'text-mist-300',
  },
  stale: {
    icon: <AlertTriangle size={18} aria-hidden="true" />,
    panel: 'border-amber-500/40 bg-amber-500/10',
    accent: 'text-amber-400',
  },
  unavailable: {
    icon: <CloudOff size={18} aria-hidden="true" />,
    panel: 'border-mist-600/40 bg-forest-800/60',
    accent: 'text-mist-300',
  },
  demo: {
    icon: <Sparkles size={18} aria-hidden="true" />,
    panel: 'border-ai-500/40 bg-ai-500/10',
    accent: 'text-ai-300',
  },
}

export function StateBanner({ kind, title, message, onRetry, children }: StateBannerProps) {
  const s = styles[kind]
  return (
    <div
      role="alert"
      className={`rounded-xl border px-4 py-3.5 ${s.panel}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className={`mt-0.5 shrink-0 ${s.accent}`}>{s.icon}</span>
          <div>
            <p className={`text-sm font-semibold ${s.accent}`}>{title}</p>
            <p className="mt-0.5 text-xs text-mist-300">{message}</p>
            {children && <div className="mt-2 text-sm">{children}</div>}
          </div>
        </div>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center gap-1.5 rounded-lg border border-forest-600 bg-forest-800 px-3 py-1.5 text-xs font-medium text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300 focus-visible:outline-2 focus-visible:outline-emerald-400"
          >
            <RotateCw size={14} aria-hidden="true" />
            Retry
          </button>
        )}
      </div>
    </div>
  )
}