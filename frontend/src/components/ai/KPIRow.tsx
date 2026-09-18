import { Boxes, CalendarClock, Droplets, Gauge, ShieldAlert, Waves } from 'lucide-react'
import type { AISnapshot } from '../../types/ai'
import { KPICard } from '../ui/KPICard'

interface KPIRowProps {
  snapshot: AISnapshot
}

export function KPIRow({ snapshot }: KPIRowProps) {
  const { forecast, activeModel } = snapshot
  const probabilityPct = Math.round(forecast.floodProbability * 100)

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Key performance indicators">
      <KPICard
        label="Flood Probability"
        value={`${probabilityPct}%`}
        timestamp={forecast.createdAt}
        trend={{ direction: 'up' }}
        status={forecast.riskLevel}
        icon={<Gauge size={16} aria-hidden="true" />}
      />
      <KPICard
        label="Current Risk Level"
        value={forecast.riskLevel}
        timestamp={forecast.createdAt}
        status={forecast.riskLevel}
        statusText="Active advisory"
        icon={<ShieldAlert size={16} aria-hidden="true" />}
      />
      <KPICard
        label="Predicted Water Level"
        value={forecast.predictedWaterLevel.toFixed(2)}
        unit="m"
        timestamp={forecast.createdAt}
        trend={{ direction: 'up' }}
        icon={<Waves size={16} aria-hidden="true" />}
      />
      <KPICard
        label="Forecast Horizon"
        value={forecast.forecastHorizon}
        timestamp={forecast.createdAt}
        icon={<CalendarClock size={16} aria-hidden="true" />}
      />
      <KPICard
        label="Active Model"
        value={activeModel.name}
        statusText="Inference"
        timestamp={activeModel.lastEvaluatedAt}
        status={forecast.riskLevel}
        icon={<Boxes size={16} aria-hidden="true" />}
      />
      <KPICard
        label="Model Version"
        value={activeModel.version}
        timestamp={activeModel.lastTrainedAt}
        statusText="v-diff"
        icon={<Droplets size={16} aria-hidden="true" />}
      />
    </div>
  )
}