/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { useEffect, useRef } from 'react'
import { HeaderSection } from '../components/ai/HeaderSection'
import { KPIRow } from '../components/ai/KPIRow'
import { ForecastSection } from '../components/ai/ForecastSection'
import { RiskAnalyticsSection } from '../components/ai/RiskAnalyticsSection'
import { ModelInfoPanel } from '../components/ai/ModelInfoPanel'
import { OptimizationBridge } from '../components/ai/OptimizationBridge'
import { PredictionsTable } from '../components/ai/PredictionsTable'
import { SystemStatePanel } from '../components/ai/SystemStatePanel'
import { useAIAnalytics } from '../hooks/useAIAnalytics'
import { KPISkeleton, ChartSkeleton } from '../components/ui/Skeleton'
import { StateBanner } from '../components/ui/StateBanner'

const DATA_FRESHNESS_MS = 60_000

function LoadingSkeleton() {
  return (
    <div className="space-y-5" role="status" aria-label="Loading AI analytics">
      <span className="sr-only">Loading AI analytics data…</span>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <KPISkeleton key={i} />
        ))}
      </div>
      <ChartSkeleton height={380} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartSkeleton height={280} />
        <ChartSkeleton height={280} />
      </div>
    </div>
  )
}

export function AIAnalyticsDashboard() {
  const { snapshot, isMock, loading, error, stale, refetch, markStale } = useAIAnalytics()
  const handleRefresh = () => refetch(true)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Auto-invalidate data after DATA_FRESHNESS_MS so users see the stale banner
  useEffect(() => {
    if (!snapshot) return
    timerRef.current = setTimeout(() => markStale(), DATA_FRESHNESS_MS)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [snapshot, markStale])

  return (
    <div className="min-h-screen px-4 pb-12 pt-6 sm:px-6 lg:px-10">
      <div className="mx-auto max-w-[1440px] space-y-5">
        {/* ---- Demo badge ---- */}
        {isMock && (
          <StateBanner
            kind="demo"
            title="Sample Data Mode"
            message="Showing sample data. Connect the backend API for live analytics."
          />
        )}

        {/* ---- Loading ---- */}
        {loading && !snapshot && <LoadingSkeleton />}

        {/* ---- Error (no fallback) ---- */}
        {error && !loading && !snapshot && (
          <StateBanner kind="error" title="Unable to load AI analytics" message={error} onRetry={handleRefresh} />
        )}

        {/* ---- Empty (loaded but null forecast — unexpected but handled) ---- */}
        {!loading && !error && !snapshot && (
          <StateBanner kind="empty" title="No analytics data available" message="The AI service returned an empty response." onRetry={handleRefresh} />
        )}

        {/* ---- Stale warning ---- */}
        {stale && snapshot && (
          <StateBanner kind="stale" title="Data may be outdated" message="Analytics data was last updated over a minute ago." onRetry={handleRefresh} />
        )}

        {/* ---- Unavailable (system-level flag in snapshot) ---- */}
        {!loading && snapshot && snapshot.systemHealth?.status !== 'online' && (
          <StateBanner
            kind="unavailable"
            title="AI service is unavailable"
            message="The AI inference service is not responding. Showing last known data."
            onRetry={handleRefresh}
          />
        )}

        {/* ---- Full Dashboard ---- */}
        {snapshot && (
          <>
            <HeaderSection
              lastUpdated={snapshot.updatedAt}
              refreshing={loading}
              onRefresh={handleRefresh}
              serviceHealth={snapshot.systemHealth}
            />

            <KPIRow snapshot={snapshot} />

            <ForecastSection
              data={snapshot.forecastSeries}
              threshold={snapshot.thresholds.thresholdLevel}
              thresholdLabel={snapshot.thresholds.label}
            />

            <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
              <div className="xl:col-span-2">
                <RiskAnalyticsSection analytics={snapshot.riskAnalytics} />
              </div>
              <div className="xl:col-span-1">
                <ModelInfoPanel model={snapshot.activeModel} />
              </div>
            </div>

            <OptimizationBridge
              readiness={snapshot.optimizationReadiness}
              riskLevel={snapshot.forecast.riskLevel}
            />

            <PredictionsTable predictions={snapshot.recentPredictions} />

            <SystemStatePanel health={snapshot.systemHealth} />
          </>
        )}
      </div>
    </div>
  )
}