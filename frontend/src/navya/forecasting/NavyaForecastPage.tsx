/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * The Navya forecast page: the routed host for `NavyaForecastDashboard`.
 *
 * ## Why a page at all
 *
 * The dashboard was built to be mounted by an owner and was never routed. This
 * is that mount, and the only team-facing change is one import, one `NavLink`
 * and one `Route` in `App.tsx`.
 *
 * ## Selection state lives here
 *
 * Both selections are held in this page and passed down, so there is exactly one
 * source of truth for the selection and the same value that the user picked is
 * the value that gets reconciled against the loaded record. Neither control
 * auto-selects; `null` is rendered as an explicit empty state.
 *
 * ## Why selection is not pushed into the request
 *
 * `/api/ai/forecast` takes no station or river parameter, and the contract
 * carries no river field. Adding a query string would create a request the
 * backend silently ignores, which reads as working propagation while changing
 * nothing. The selection is instead propagated into reconciliation — see
 * `NavyaForecastScope` and `scope.ts`.
 *
 * ## Data loading lives here, not in the dashboard
 *
 * This page owns `useNavyaForecast` and renders the dashboard as a pure
 * presenter (`loadOnMount={false}`). The alternative — letting the dashboard
 * fetch while the page masks it — would run two copies of the same request and
 * show the dashboard's *own* empty state during the page's loading phase. With
 * the page as the owner, loading renders a skeleton, an error renders an error
 * card with a working retry, and a loaded record renders the dashboard.
 */

import { CloudOff, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { GlassCard } from '../../components/ui/GlassCard'
import { SectionHeader } from '../../components/ui/SectionHeader'
import { Skeleton } from '../../components/ui/Skeleton'
import { StateBanner } from '../../components/ui/StateBanner'
import { NavyaForecastDashboard } from './NavyaForecastDashboard'
import { NavyaForecastScope } from './NavyaForecastScope'
import { useNavyaForecast } from './useNavyaForecast'
import type { APIError } from '../../types/ai'

export function NavyaForecastPage() {
  const forecast = useNavyaForecast()
  const [stationId, setStationId] = useState<string | null>(null)
  const [riverId, setRiverId] = useState<string | null>(null)

  const record = forecast.forecast

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-10">
      <NavyaForecastScope
        record={record}
        stationId={stationId}
        riverId={riverId}
        onStationChange={setStationId}
        onRiverChange={setRiverId}
        disabled={forecast.loading}
      />
      <div className="mt-4">
        {record === null ? (
          forecast.loading ? (
            <LoadingState />
          ) : (
            <ErrorState error={forecast.error} onRetry={forecast.reload} />
          )
        ) : (
          <NavyaForecastDashboard
            forecast={record}
            comparison={forecast.comparison}
            loadOnMount={false}
          />
        )}
      </div>
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

function ErrorState({ error, onRetry }: { error: APIError | null; onRetry: () => void }) {
  return (
    <GlassCard className="space-y-3">
      <SectionHeader icon={CloudOff} title="Navya forecasting" />
      <StateBanner
        kind="error"
        title="Forecast unavailable"
        message={error?.message ?? 'No forecast record is available. Nothing is displayed in its place.'}
        onRetry={onRetry}
      />
      <p className="text-[11px] text-mist-600">
        This section does not substitute sample data when the backend is unreachable. A
        fabricated forecast here would contradict the provenance panel below it.
      </p>
    </GlassCard>
  )
}