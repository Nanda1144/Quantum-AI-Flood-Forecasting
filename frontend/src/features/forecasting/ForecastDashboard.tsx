/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { CloudOff, RotateCw, Sparkles } from 'lucide-react'
import { GlassCard } from '../../components/ui/GlassCard'
import { SectionHeader } from '../../components/ui/SectionHeader'
import { Skeleton } from '../../components/ui/Skeleton'
import { StateBanner } from '../../components/ui/StateBanner'
import { ForecastSeriesChart } from './ForecastSeriesChart'
import { ForecastSummary } from './ForecastSummary'
import { ForecastModelComparison } from './ForecastModelComparison'
import { ProvenancePanel } from './ProvenancePanel'
import { ForecastRiskDisplay } from './ForecastRiskDisplay'
import { useForecast } from './useForecast'
import type { ForecastRecord, ForecastModelComparison as Comparison } from './types'

interface Props {
  /**
   * Supply a record to render instead of fetching.
   *
   * Exists so the component can be driven by a caller that already has the data —
   * a test, or a future page that has a forecast in hand. Passing a record skips
   * the network entirely.
   */
  forecast?: ForecastRecord
  comparison?: Comparison | null
  loadOnMount?: boolean
}

/**
 * the forecasting section.
 *
 * ## Where it is mounted
 *
 * Mounted by the platform owner at `/forecasting` (see `App.tsx`), which closed
 * register item FE-ROUTE-01 in
 * `docs/forecasting/TEAM_INTEGRATION_REQUIREMENTS.md`. The remaining open items
 * in that register are contract extensions owned by the platform team, not by
 * this module.
 *
 * ## Reading order is deliberate
 *
 * Provenance sits directly under the summary, before the risk panel and the
 * chart. That is the order in which the numbers become trustworthy: what the data
 * is, what the score means, then the risk reading and the series. A layout that
 * puts the chart first and the caveats in a tooltip has already lost the reader
 * who screenshots the top of the page.
 *
 * ## Empty and error states
 *
 * Both render an explicit message. Neither substitutes a placeholder forecast, and
 * neither falls back to sample data — see `forecastService.ts` for why.
 */
export function ForecastDashboard({ forecast, comparison, loadOnMount = true }: Props) {
  // A caller-supplied record suppresses the network fetch entirely.
  const fetched = useForecast({ loadOnMount: loadOnMount && forecast === undefined })
  // `?? null` collapses `undefined` into `null` so one guard below narrows the
  // type completely. Without it, `forecast` stays possibly-undefined while
  // `fetched.forecast` is possibly-null, and no single `=== undefined` check
  // removes both.
  const record = forecast ?? fetched.forecast ?? null
  const table = comparison ?? fetched.comparison

  if (record === null) {
    return fetched.loading ? (
      <LoadingState />
    ) : (
      <GlassCard className="space-y-3">
        <SectionHeader icon={CloudOff} title="forecasting" />
        <StateBanner
          kind="error"
          title="Forecast unavailable"
          message={
            fetched.error?.message ??
            'No forecast record is available. Nothing is displayed in its place.'
          }
          onRetry={fetched.reload}
        />
        <p className="text-[11px] text-mist-600">
          This section does not substitute sample data when the backend is unreachable. A
          fabricated forecast here would contradict the provenance panel below it.
        </p>
      </GlassCard>
    )
  }

  return (
    <div className="space-y-4" data-testid="hydro-forecast-dashboard">
      <GlassCard className="flex flex-wrap items-center justify-between gap-3">
        <SectionHeader
          icon={Sparkles}
          title="forecasting"
          description="Forecasting engine, provenance and evaluation status."
          actions={
            <button
              type="button"
              onClick={fetched.reload}
              className="inline-flex items-center gap-1.5 rounded-md border border-forest-600 px-2.5 py-1 text-xs text-mist-300 transition hover:border-ai-500/60 hover:text-ai-300"
            >
              <RotateCw size={13} aria-hidden="true" />
              Refresh
            </button>
          }
        />
      </GlassCard>

      <ForecastSummary forecast={record} />
      <ProvenancePanel forecast={record} />
      <ForecastRiskDisplay forecast={record} />

      <GlassCard className="space-y-3">
        <SectionHeader
          icon={Sparkles}
          title="Forecast series"
          description="Predicted versus observed across the recorded backtest window."
        />
        <ForecastSeriesChart
          points={record.backtest}
          threshold={record.threshold}
          thresholdSuffix={
            record.thresholdPolicy === 'approved' ? '' : ' — PENDING, not official'
          }
          title="Predicted versus observed water level, backtest window"
        />
      </GlassCard>

      <ForecastModelComparison
        comparison={table}
        error={fetched.comparisonError?.message ?? null}
      />
    </div>
  )
}

function LoadingState() {
  return (
    <GlassCard className="space-y-3" data-testid="hydro-forecast-loading">
      <SectionHeader icon={Sparkles} title="forecasting" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-40 w-full" />
    </GlassCard>
  )
}
