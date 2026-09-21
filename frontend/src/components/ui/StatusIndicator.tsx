/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import type { RiskLevel, ServiceStatus } from '../../types/ai'
import { riskStyle, serviceStatusClass, serviceStatusText } from '../../lib/risk'

interface StatusIndicatorProps {
  status: RiskLevel | ServiceStatus
  subtle?: boolean
}

/**
 * Pulsing dot + text. Status is conveyed by text so it never relies on color alone.
 */
export function StatusIndicator({ status, subtle = false }: StatusIndicatorProps) {
  const isRisk = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].includes(status)
  const srText = isRisk ? `Risk level ${status}` : `Service status ${status}`
  const text = isRisk ? riskStyle(status as RiskLevel).label : serviceStatusText(status as ServiceStatus)
  const dot = isRisk ? riskStyle(status as RiskLevel).dot : serviceStatusClass(status as ServiceStatus).dot

  return (
    <span
      role="status"
      aria-label={srText}
      className={`inline-flex items-center gap-1.5 ${subtle ? 'text-[11px]' : 'text-xs'} font-medium tracking-wide`}
    >
      <span className="relative flex size-2">
        <span className={`absolute inline-flex size-full animate-ping rounded-full opacity-60 ${dot}`} />
        <span className={`relative inline-flex size-2 rounded-full ${dot}`} />
      </span>
      <span className="sr-only">{srText}: </span>
      <span className={isRisk ? riskStyle(status as RiskLevel).text : serviceStatusClass(status as ServiceStatus).text}>
        {text}
      </span>
    </span>
  )
}