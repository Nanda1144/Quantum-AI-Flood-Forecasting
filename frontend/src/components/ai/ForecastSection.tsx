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
    </div>
  )
}