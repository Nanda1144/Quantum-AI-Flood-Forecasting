/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import type { HTMLAttributes, ReactNode } from 'react'

interface GlassCardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
  glow?: boolean
  padded?: boolean
}

export function GlassCard({ children, glow = false, padded = true, className = '', ...rest }: GlassCardProps) {
  const padding = padded ? 'p-5' : ''
  return (
    <section
      {...rest}
      className={`glass-card ${glow ? 'glass-card--glow' : ''} ${padding} ${className}`}
    >
      {children}
    </section>
  )
}