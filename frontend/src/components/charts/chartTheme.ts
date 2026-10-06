/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

export const chartColors = {
  grid: 'rgba(53, 97, 78, 0.30)',
  tick: '#64748b',
  tooltipBg: 'rgba(17, 36, 28, 0.96)',
  tooltipBorder: 'rgba(53, 97, 78, 0.6)',
  predicted: '#22d3ee',
  observed: '#94a3b8',
  threshold: '#f59e0b',
  probability: '#10b981',
  risk: '#ef4444',
  emerald: '#34d399',
  critical: '#ef4444',
  amber: '#fbbf24',
  cyan: '#22d3ee',
  forest: '#35614e',
} as const

export const tooltipStyle = {
  backgroundColor: chartColors.tooltipBg,
  border: `1px solid ${chartColors.tooltipBorder}`,
  borderRadius: '0.75rem',
  fontSize: '12px',
  color: '#f8fafc',
  boxShadow: '0 12px 32px -16px rgba(0,0,0,0.8)',
} as const

export function timeTick(timestamp: string | number): string {
  const d = new Date(timestamp)
  return d.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit' })
}