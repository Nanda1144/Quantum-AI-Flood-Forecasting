/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { LineChart } from 'lucide-react'
import type { ForecastPoint } from '../../types/ai'
import { ForecastChart } from '../charts/ForecastChart'
import { SectionHeader } from '../ui/SectionHeader'

interface ForecastSectionProps {
  data: ForecastPoint[]
  threshold?: number
  thresholdLabel?: string
}

export function ForecastSection({ data, threshold, thresholdLabel }: ForecastSectionProps) {
  const hasThreshold = typeof threshold === 'number'
  const hasObserved = data.some((point) => typeof point.observedWaterLevel === 'number')

  const legend = [
    { color: '#22d3ee', label: 'Predicted water level' },
    ...(hasObserved ? [{ color: '#94a3b8', label: 'Observed / historical' }] : []),
    ...(hasThreshold ? [{ color: '#f59e0b', label: thresholdLabel ?? 'Threshold level' }] : []),
  ]

  return (
    <div className="glass-card p-5">
      <SectionHeader
        icon={LineChart}
        title="Forecast Time-Series"
        description="Predicted water level over the forecast horizon"
      />
      {data.length === 0 ? (
        <div className="mt-4 rounded-lg border border-forest-600/70 bg-forest-800/60 px-4 py-10 text-center">
          <p className="text-sm font-semibold text-mist-200">No forecast series data</p>
          <p className="mt-1 text-xs text-mist-500">The AI service returned no forecast points to chart.</p>
        </div>
      ) : (
        <>
          <div className="mt-4">
            <ForecastChart data={data} threshold={threshold} height={320} />
          </div>
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 border-t border-forest-600/60 pt-3">
            {legend.map((item) => (
              <span key={item.label} className="inline-flex items-center gap-2 text-xs text-mist-300">
                <span
                  className={`h-0.5 w-6 rounded-full ${item.label.includes('Threshold') ? 'border-t-2 border-dashed border-[#f59e0b] bg-transparent' : ''}`}
                  style={
                    item.label.includes('Threshold')
                      ? undefined
                      : { backgroundColor: item.color }
                  }
                  aria-hidden="true"
                />
                {item.label}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  )
}