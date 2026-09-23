/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { X } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'

interface QuantumModalProps {
  title: string
  subtitle?: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}

export function QuantumModal({ title, subtitle, onClose, children, wide = false }: QuantumModalProps) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      <button
        type="button"
        aria-label="Close dialog"
        className="absolute inset-0 bg-forest-950/75 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        className={`glass-card glass-card--glow relative max-h-[86vh] w-full overflow-y-auto p-5 sm:p-6 ${
          wide ? 'max-w-4xl' : 'max-w-2xl'
        }`}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-mist-50">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-mist-500">{subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg border border-forest-600 bg-forest-800 p-1.5 text-mist-300 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}