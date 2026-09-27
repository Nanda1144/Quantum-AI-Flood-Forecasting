/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Droplets, Gauge, Timer, Waves } from 'lucide-react'
import { GlassCard } from '../../components/ui/GlassCard'
import { KPICard } from '../../components/ui/KPICard'
import { SectionHeader } from '../../components/ui/SectionHeader'
import { describeDatasetType, thresholdIsOfficial } from './contract'
import type { NavyaForecastRecord } from './types'
import { HumanInputNote } from './NavyaProvenancePanel'

/** Renders `—` for an absent number. Never a zero, never a placeholder score. */
function num(value: number | null, digits = 3): string {
  return value === null ? '—' : value.toFixed(digits)
}

/**
 * A probability as a percentage, or `—`.
 *
 * Refuses to render a value outside 0..1 rather than clamping it. A probability
 * of 1.4 is a backend defect, and silently clamping it to "100%" would convert a
 * visible bug into an invisible wrong answer.
 */
function probability(value: number): string {
  if (!Number.isFinite(value) || value < 0 || value > 1) return '—'
  return `${(value * 100).toFixed(1)}%`
}

interface Props {
  forecast: NavyaForecastRecord
}

/**
 * The headline numbers for one forecast.
 *
 * ## What is on this card, and what is deliberately not
 *
 * Present: the predicted value, the target, the horizon, the flood probability,
 * the model identity, and the threshold with its approval state.
 *
 * Absent: RMSE, MAE, R², NSE, and any accuracy figure. Those live in
 * `NavyaProvenancePanel`, and they only appear there — attached to the split
 * they were measured on and the label they are allowed to carry. Putting a bare
 * regression score next to a big prediction number is how a fit statistic ends
 * up being read as accuracy, and the summary card is the wrong place to defend
 * against that.
 *
 * The card is driven entirely by the record. There is no fallback number, no
 * "typical value", and no placeholder: a field the backend did not send is shown
 * as absent, because the alternative is inventing it.
 */
export function NavyaForecastSummary({ forecast }: Props) {
  // Units are read from provenance, the single authority. See the note on
  // `NavyaForecastRecord` — a second copy of this fact on the record itself
  // could contradict what the guards check.
  const units = forecast.provenance.targetUnits
  const unitsLabel = units === null ? 'units not recorded' : units
  const official = thresholdIsOfficial(forecast)

  return (
    <GlassCard className="space-y-4">
      <SectionHeader
        icon={Waves}
        title="Forecast summary"
        description={`${forecast.forecastId} · issued ${forecast.forecastTimestamp}`}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KPICard
          label="Predicted"
          value={num(forecast.predictedValue)}
          unit={unitsLabel}
          icon={<Waves size={16} aria-hidden="true" />}
          status={forecast.riskLevel}
        />
        <KPICard
          label="Flood probability"
          value={probability(forecast.floodProbability)}
          icon={<Gauge size={16} aria-hidden="true" />}
          statusText={`risk ${forecast.riskLevel}`}
        />
        <KPICard
          label="Horizon"
          value={forecast.forecastHorizon}
          icon={<Timer size={16} aria-hidden="true" />}
          statusText={`${forecast.provenance.forecastHorizonHours} h ahead`}
        />
        <KPICard
          label="Threshold"
          value={forecast.threshold === null ? '—' : num(forecast.threshold, 2)}
          unit={forecast.threshold === null ? undefined : unitsLabel}
          icon={<Droplets size={16} aria-hidden="true" />}
          statusText={official ? 'approved' : 'PENDING — not official'}
        />
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 border-t border-forest-600/60 pt-3 text-xs sm:grid-cols-4">
        <Field label="Target" value={forecast.target} />
        <Field label="Model" value={forecast.modelId} />
        <Field label="Version" value={forecast.modelVersion} />
        <Field label="Status" value={forecast.status} />
        <Field label="Data" value={describeDatasetType(forecast.provenance.datasetType)} />
        <Field label="Station" value={forecast.provenance.stationReference ?? 'not recorded'} />
        <Field label="Lead time" value={`${forecast.provenance.leadTimeRows} rows`} />
        <Field label="Contract" value={forecast.provenance.contractVersion} />
      </dl>

      {forecast.provenance.datasetType !== 'real' && (
        <HumanInputNote tone="warning">
          Every number on this card is derived from{' '}
          <strong>{describeDatasetType(forecast.provenance.datasetType)}</strong> data. It is not a
          hydrological observation and must not be reported as one.
        </HumanInputNote>
      )}
    </GlassCard>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-[0.14em] text-mist-600">{label}</dt>
      <dd className="mt-0.5 font-medium text-mist-200">{value}</dd>
    </div>
  )
}
