/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

interface SectionHeaderProps {
  icon: LucideIcon
  title: string
  description?: string
  actions?: ReactNode
}

export function SectionHeader({ icon: Icon, title, description, actions }: SectionHeaderProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-forest-600 bg-forest-800 text-ai-300">
          <Icon size={18} aria-hidden="true" />
        </span>
        <div>
          <h2 className="text-sm font-semibold tracking-wide text-mist-50">{title}</h2>
          {description && <p className="text-xs text-mist-500">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}