/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform . It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { AlertTriangle, ShieldAlert } from 'lucide-react'
import { GlassCard } from '../../components/ui/GlassCard'
import { SectionHeader } from '../../components/ui/SectionHeader'
import { riskStyle } from '../../lib/risk'
import { describeThreshold, thresholdIsOfficial } from './contract'
import type { ForecastBacktestPoint, ForecastRecord } from './types'
import type { RiskLevel } from '../../types/ai'
import { HumanInputNote } from './ProvenancePanel'

/** A probability as a percentage, or `—` when out of range. */
function pct(value: number): string {
  if (!Number.isFinite(value) || value < 0 || value > 1) return '—'
  return `${(value * 100).toFixed(1)}%`
}

/** Counts per band, computed from the backtest rather than stored. */
function bandCounts(points: ForecastBacktestPoint[]): Record<RiskLevel, number> {
  const counts: Record<RiskLevel, number> = { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 }
  for (const point of points) {
    if (point.riskLevel in counts) counts[point.riskLevel] += 1
  }
  return counts
}

interface Props {
  forecast: ForecastRecord
}

/**
 * The current risk reading and the distribution behind it.
 *
 * ## The unavoidable caveat
 *
 * A risk level is a banded form of a probability, and the band edges come from a
 * policy that does not exist in this repository. The team reference engine
 * hard-codes a single placeholder stage; that value is not reproduced here, and
 * this module never hard-codes one either. The threshold is configurable
 * end-to-end and the record says which state it is in.
 *
 * So the panel always shows, next to the risk level:
 *   - the probability, which is the measured quantity, and
 *   - the threshold's approval state, which is the missing authority.
 *
 * A red CRITICAL badge is a colour, not a verified emergency, and this component
 * is written so that reading is hard to arrive at by accident.
 *
 * The distribution is counted from the backtest points in the record. It is not
 * smoothed, not fitted to a distribution, and not extrapolated beyond the window
 * it was measured on.
 */
export function ForecastRiskDisplay({ forecast }: Props) {
  const style = riskStyle(forecast.riskLevel)
  const official = thresholdIsOfficial(forecast)
  const points = forecast.backtest
  const counts = bandCounts(points)
  const bands: RiskLevel[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

  return (
    <GlassCard className="space-y-4">
      <SectionHeader
        icon={ShieldAlert}
        title="Risk"
        description={forecast.forecastId}
        actions={
          <span
            className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-semibold ${style.bg} ${style.border} ${style.text}`}
          >
            <span className={`size-1.5 rounded-full ${style.dot}`} aria-hidden="true" />
            {forecast.riskLevel}
          </span>
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">
            Exceedance probability
          </p>
          <p className="mt-1 text-2xl font-bold tabular-nums text-mist-50">
            {pct(forecast.floodProbability)}
          </p>
        </div>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">
            Residual sigma
          </p>
          <p className="mt-1 text-2xl font-bold tabular-nums text-mist-50">
            {forecast.residualSigma === null ? '—' : forecast.residualSigma.toFixed(4)}
          </p>
        </div>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">
            Backtest points
          </p>
          <p className="mt-1 text-2xl font-bold tabular-nums text-mist-50">{points.length}</p>
        </div>
      </div>

      <HumanInputNote tone={official ? 'info' : 'warning'}>
        {describeThreshold(forecast)}
      </HumanInputNote>

      {points.length === 0 ? (
        <HumanInputNote tone="warning">
          No backtest points are available for this forecast, so no risk distribution can be shown.
          A distribution is not estimated from a single prediction.
        </HumanInputNote>
      ) : (
        <section aria-label="Risk band distribution">
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">
            Risk bands across the backtest
          </h3>
          <ul className="mt-2 space-y-1.5">
            {bands.map((band) => {
              const bandStyle = riskStyle(band)
              const count = counts[band]
              const share = points.length === 0 ? 0 : (count / points.length) * 100
              return (
                <li key={band} className="flex items-center gap-3 text-xs">
                  <span className={`w-16 shrink-0 font-medium ${bandStyle.text}`}>{band}</span>
                  <span className="h-2 flex-1 overflow-hidden rounded-full bg-forest-800">
                    <span
                      className={`block h-full rounded-full ${bandStyle.dot}`}
                      style={{ width: `${share.toFixed(1)}%` }}
                    />
                  </span>
                  <span className="w-20 shrink-0 text-right tabular-nums text-mist-400">
                    {count} ({share.toFixed(1)}%)
                  </span>
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {!official && (
        <p className="flex items-start gap-1.5 text-[11px] text-amber-400/80">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
          The band edges behind LOW / MEDIUM / HIGH / CRITICAL have no approved policy in this
          repository. Treat the level as an uncalibrated ranking, not a flood warning.
        </p>
      )}
    </GlassCard>
  )
}
