/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { CloudOff, RotateCw, Sparkles } from 'lucide-react'
import { GlassCard } from '../../components/ui/GlassCard'
import { SectionHeader } from '../../components/ui/SectionHeader'
import { Skeleton } from '../../components/ui/Skeleton'
import { StateBanner } from '../../components/ui/StateBanner'
import { NavyaForecastSeriesChart } from './NavyaForecastSeriesChart'
import { NavyaForecastSummary } from './NavyaForecastSummary'
import { NavyaModelComparison } from './NavyaModelComparison'
import { NavyaProvenancePanel } from './NavyaProvenancePanel'
import { NavyaRiskDisplay } from './NavyaRiskDisplay'
import { useNavyaForecast } from './useNavyaForecast'
import type { NavyaForecastRecord, NavyaModelComparison as Comparison } from './types'

interface Props {
  /**
   * Supply a record to render instead of fetching.
   *
   * Exists so the component can be driven by a caller that already has the data —
   * a test, or a future page that has a forecast in hand. Passing a record skips
   * the network entirely.
   */
  forecast?: NavyaForecastRecord
  comparison?: Comparison | null
  loadOnMount?: boolean
}

/**
 * Navya's forecasting section.
 *
 * ## Not mounted
 *
 * This component is **not** registered on any team route. `App.tsx` and
 * `pages/AIAnalyticsDashboard.tsx` are team-owned and are not modified, so nothing
 * on the running application changes until a team owner mounts it. See
 * `01_Flood_Forecasting/TEAM_INTEGRATION_REQUIREMENTS.md`.
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
 * neither falls back to sample data — see `navyaForecastService.ts` for why.
 */
export function NavyaForecastDashboard({ forecast, comparison, loadOnMount = true }: Props) {
  // A caller-supplied record suppresses the network fetch entirely.
  const fetched = useNavyaForecast({ loadOnMount: loadOnMount && forecast === undefined })
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
        <SectionHeader icon={CloudOff} title="Navya forecasting" />
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
    <div className="space-y-4" data-testid="navya-forecast-dashboard">
      <GlassCard className="flex flex-wrap items-center justify-between gap-3">
        <SectionHeader
          icon={Sparkles}
          title="Navya forecasting"
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

      <NavyaForecastSummary forecast={record} />
      <NavyaProvenancePanel forecast={record} />
      <NavyaRiskDisplay forecast={record} />

      <GlassCard className="space-y-3">
        <SectionHeader
          icon={Sparkles}
          title="Forecast series"
          description="Predicted versus observed across the recorded backtest window."
        />
        <NavyaForecastSeriesChart
          points={record.backtest}
          threshold={record.threshold}
          thresholdSuffix={
            record.thresholdPolicy === 'approved' ? '' : ' — PENDING, not official'
          }
          title="Predicted versus observed water level, backtest window"
        />
      </GlassCard>

      <NavyaModelComparison
        comparison={table}
        error={fetched.comparisonError?.message ?? null}
      />
    </div>
  )
}

function LoadingState() {
  return (
    <GlassCard className="space-y-3" data-testid="navya-forecast-loading">
      <SectionHeader icon={Sparkles} title="Navya forecasting" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-40 w-full" />
    </GlassCard>
  )
}
