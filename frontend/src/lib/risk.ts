/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import type { ModelStatus, RiskLevel, ServiceStatus } from '../types/ai'

export interface RiskStyle {
  label: string
  /** Tailwind text color */
  text: string
  /** Tailwind bg color */
  bg: string
  /** Tailwind border color */
  border: string
  /** Dot / accent color */
  dot: string
  /** Soft glow for prominent elements */
  glow: string
  /** Machine-readable priority hint */
  priority: 'low' | 'medium' | 'high' | 'critical'
}

const style: Record<RiskLevel, RiskStyle> = {
  LOW: {
    label: 'LOW',
    text: 'text-emerald-300',
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/40',
    dot: 'bg-emerald-400',
    glow: 'shadow-[0_0_18px_-4px_rgba(16,185,129,0.6)]',
    priority: 'low',
  },
  MEDIUM: {
    label: 'MEDIUM',
    text: 'text-amber-400',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/40',
    dot: 'bg-amber-400',
    glow: 'shadow-[0_0_18px_-4px_rgba(245,158,11,0.6)]',
    priority: 'medium',
  },
  HIGH: {
    label: 'HIGH',
    text: 'text-critical-400',
    bg: 'bg-critical-500/10',
    border: 'border-critical-500/40',
    dot: 'bg-critical-400',
    glow: 'shadow-[0_0_18px_-4px_rgba(239,68,68,0.55)]',
    priority: 'high',
  },
  CRITICAL: {
    label: 'CRITICAL',
    text: 'text-critical-400',
    bg: 'bg-critical-500/15',
    border: 'border-critical-500/60',
    dot: 'bg-critical-400',
    glow: 'shadow-[0_0_24px_-4px_rgba(239,68,68,0.7)]',
    priority: 'critical',
  },
}

const trend = (() => {
  const dir = { up: 'text-critical-400', down: 'text-emerald-300', flat: 'text-mist-500' } as const
  return dir
})()

export function riskStyle(level: RiskLevel): RiskStyle {
  return style[level] ?? style.MEDIUM
}

export function trendDirectionClass(direction: 'up' | 'down' | 'flat'): string {
  return trend[direction] ?? trend.flat
}

export function modelStatusText(status: ModelStatus): string {
  switch (status) {
    case 'ready':
      return 'Ready'
    case 'training':
      return 'Training'
    case 'degraded':
      return 'Degraded'
    case 'offline':
      return 'Offline'
  }
}

const serviceStatusStyle: Record<ServiceStatus, { text: string; dot: string }> = {
  online: { text: 'text-emerald-300', dot: 'bg-emerald-400' },
  degraded: { text: 'text-amber-400', dot: 'bg-amber-400' },
  offline: { text: 'text-critical-400', dot: 'bg-critical-400' },
  unavailable: { text: 'text-mist-500', dot: 'bg-mist-500' },
}

export function serviceStatusText(status: ServiceStatus): string {
  switch (status) {
    case 'online':
      return 'Online'
    case 'degraded':
      return 'Degraded'
    case 'offline':
      return 'Offline'
    case 'unavailable':
      return 'Unavailable'
  }
}

export function serviceStatusClass(status: ServiceStatus): { text: string; dot: string } {
  return serviceStatusStyle[status] ?? serviceStatusStyle.unavailable
}