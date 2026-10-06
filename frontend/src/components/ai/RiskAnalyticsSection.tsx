/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { ChartArea, Layers } from 'lucide-react'
import type { RiskAnalytics } from '../../types/ai'
import { RiskTrendChart } from '../charts/RiskTrendChart'
import { RiskDistributionChart } from '../charts/RiskDistributionChart'
import { SectionHeader } from '../ui/SectionHeader'
import { riskStyle } from '../../lib/risk'

interface RiskAnalyticsSectionProps {
  analytics: RiskAnalytics
}

export function RiskAnalyticsSection({ analytics }: RiskAnalyticsSectionProps) {
  const isEmpty =
    analytics.riskTrend.length === 0 &&
    analytics.probabilityTrend.length === 0 &&
    analytics.distribution.length === 0
  const bars = [
    { level: 'CRITICAL' as const, count: analytics.summary.critical },
    { level: 'HIGH' as const, count: analytics.summary.high },
    { level: 'MEDIUM' as const, count: analytics.summary.medium },
    { level: 'LOW' as const, count: analytics.summary.low },
  ]
  const maxCount = Math.max(1, ...bars.map((bar) => bar.count))

  return (
    <div className="glass-card p-5">
      <SectionHeader
        icon={ChartArea}
        title="Risk Analytics"
        description="Flood probability and risk evolution"
      />

      {isEmpty ? (
        <div className="mt-4 rounded-lg border border-forest-600/70 bg-forest-800/60 px-4 py-10 text-center">
          <p className="text-sm font-semibold text-mist-200">No risk analytics data</p>
          <p className="mt-1 text-xs text-mist-500">The AI service returned no risk trend or distribution data.</p>
        </div>
      ) : (
        <>
          <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-1">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-mist-500">Risk Trend</p>
          <RiskTrendChart data={analytics.riskTrend} ariaLabel="Risk score trend line chart" />
        </div>

        <div className="lg:col-span-1">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-mist-500">Flood Probability Trend</p>
          <RiskTrendChart
            data={analytics.probabilityTrend}
            color="#10b981"
            ariaLabel="Flood probability trend line chart"
          />
        </div>

        <div className="lg:col-span-1">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-mist-500">Risk Distribution</p>
          <RiskDistributionChart data={analytics.distribution} />
        </div>
      </div>

      <div className="mt-5 border-t border-forest-600/60 pt-4">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-mist-500">
          <Layers size={14} aria-hidden="true" />
          Status Summary
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
          {bars.map((bar) => {
            const s = riskStyle(bar.level)
            return (
              <div key={bar.level}>
                <div className="flex items-center justify-between text-[11px]">
                  <span className={`inline-flex items-center gap-1.5 font-semibold ${s.text}`}>
                    <span className={`size-1.5 rounded-full ${s.dot}`} aria-hidden="true" />
                    {bar.level}
                  </span>
                  <span className="tabular-nums text-mist-500">{bar.count}</span>
                </div>
                <div
                  className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-forest-700/70"
                  role="progressbar"
                  aria-label={`${bar.level} risk locations`}
                  aria-valuenow={bar.count}
                  aria-valuemin={0}
                  aria-valuemax={maxCount}
                >
                  <div
                    className={`h-full rounded-full ${s.dot}`}
                    style={{ width: `${Math.max(6, (bar.count / maxCount) * 100)}%` }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      </div>
        </>
      )}
    </div>
  )
}