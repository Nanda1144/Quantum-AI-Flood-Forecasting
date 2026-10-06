/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Boxes, CalendarClock, Droplets, Gauge, ShieldAlert, Waves } from 'lucide-react'
import type { AISnapshot, TrendDirection } from '../../types/ai'
import { modelStatusText } from '../../lib/risk'
import { KPICard } from '../ui/KPICard'

interface KPIRowProps {
  snapshot: AISnapshot
}

/** Trend derived from the bracketing values of a real series (never invented). */
function trendFromSeries(values: number[], tolerance = 0.02): TrendDirection {
  if (values.length < 2) return 'flat'
  const delta = values[values.length - 1] - values[0]
  if (delta > tolerance) return 'up'
  if (delta < -tolerance) return 'down'
  return 'flat'
}

export function KPIRow({ snapshot }: KPIRowProps) {
  const { forecast, activeModel } = snapshot
  const probabilityPct = Math.round(forecast.floodProbability * 100)
  const probabilityTrend = trendFromSeries(snapshot.riskAnalytics.probabilityTrend.map((p) => p.value))
  const waterLevelTrend = trendFromSeries(snapshot.forecastSeries.map((p) => p.predictedWaterLevel))

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Key performance indicators">
      <KPICard
        label="Flood Probability"
        value={`${probabilityPct}%`}
        timestamp={forecast.createdAt}
        trend={{ direction: probabilityTrend }}
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
        trend={{ direction: waterLevelTrend }}
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
        statusText={modelStatusText(activeModel.status)}
        icon={<Droplets size={16} aria-hidden="true" />}
      />
    </div>
  )
}