/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'
import type { ReactNode } from 'react'
import type { RiskLevel } from '../../types/ai'
import { riskStyle, trendDirectionClass } from '../../lib/risk'
import { formatTime } from '../../lib/format'
import type { TrendDirection } from '../../types/ai'

interface TrendBadgeProps {
  direction: TrendDirection
  label?: string
}

export function TrendBadge({ direction, label }: TrendBadgeProps) {
  const Icon = direction === 'up' ? ArrowUpRight : direction === 'down' ? ArrowDownRight : Minus
  return (
    <span
      className={`inline-flex items-center gap-1 text-[11px] font-medium ${trendDirectionClass(direction)}`}
    >
      <Icon size={13} aria-hidden="true" />
      {label ?? (direction === 'up' ? 'Rising' : direction === 'down' ? 'Falling' : 'Steady')}
    </span>
  )
}

interface KPICardProps {
  label: string
  value: string
  unit?: string
  icon?: ReactNode
  /** ISO timestamp shown under the value where appropriate. */
  timestamp?: string | null
  trend?: TrendBadgeProps
  /** Semantic status: LOW/MEDIUM/HIGH/CRITICAL or a plain tone. */
  status?: RiskLevel
  statusText?: string
}

export function KPICard({ label, value, unit, icon, timestamp, trend, status, statusText }: KPICardProps) {
  const risk = status ? riskStyle(status) : null
  return (
    <article className="glass-card p-5">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">{label}</p>
        {icon && <span className="text-mist-600">{icon}</span>}
      </div>

      <div className="mt-3 flex items-baseline gap-1.5">
        <p className="text-3xl font-bold tabular-nums tracking-tight text-mist-50">{value}</p>
        {unit && <span className="text-sm font-medium text-mist-500">{unit}</span>}
      </div>

      <div className="mt-2 flex items-center gap-2">
        {risk && (
          <span
            className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-semibold ${risk.bg} ${risk.border} ${risk.text}`}
          >
            <span className={`size-1.5 rounded-full ${risk.dot}`} aria-hidden="true" />
            {risk.label}
          </span>
        )}
        {statusText && <span className="text-xs font-medium text-mist-300">{statusText}</span>}
        {trend && <TrendBadge {...trend} />}
      </div>

      {timestamp && (
        <p className="mt-3 border-t border-forest-600/60 pt-2 text-[11px] text-mist-600">
          Updated {formatTime(timestamp)}
        </p>
      )}
    </article>
  )
}