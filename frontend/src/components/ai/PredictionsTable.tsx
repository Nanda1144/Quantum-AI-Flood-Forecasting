/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { History } from 'lucide-react'
import type { RecentPrediction } from '../../types/ai'
import { SectionHeader } from '../ui/SectionHeader'
import { riskStyle } from '../../lib/risk'
import { formatTime, formatRelative } from '../../lib/format'

interface PredictionsTableProps {
  predictions: RecentPrediction[]
}

const statusStyles: Record<RecentPrediction['status'], string> = {
  completed: 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300',
  pending: 'bg-ai-500/10 border-ai-500/40 text-ai-300',
  failed: 'bg-critical-500/10 border-critical-500/40 text-critical-400',
}

export function PredictionsTable({ predictions }: PredictionsTableProps) {
  return (
    <div className="glass-card p-5">
      <SectionHeader
        icon={History}
        title="Recent Predictions"
        description="Latest forecast executions"
      />

      <div className="mt-4 -mx-1 overflow-x-auto px-1 pb-1">
        {predictions.length === 0 ? (
          <div className="rounded-lg border border-forest-600/70 bg-forest-800/60 px-4 py-8 text-center">
            <p className="text-sm font-semibold text-mist-200">No recent predictions</p>
            <p className="mt-1 text-xs text-mist-500">The AI service has not produced any prediction records yet.</p>
          </div>
        ) : (
        <table className="w-full min-w-[680px] text-left text-xs" role="table">
          <thead>
            <tr className="border-b border-forest-600/60 text-[11px] font-semibold uppercase tracking-wider text-mist-500">
              <th className="pb-2 pr-4">Forecast ID</th>
              <th className="pb-2 pr-4">Timestamp</th>
              <th className="pb-2 pr-4 text-right">Probability</th>
              <th className="pb-2 pr-4">Risk</th>
              <th className="pb-2 pr-4 text-right">Water Level</th>
              <th className="pb-2 pr-4">Model</th>
              <th className="pb-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-forest-700/50 text-mist-200">
            {predictions.map((pred) => {
              const risk = riskStyle(pred.riskLevel)
              return (
                <tr key={pred.forecastId} className="group transition-colors hover:bg-forest-800/60">
                  <td className="py-2.5 pr-4 font-mono font-semibold text-mist-50">{pred.forecastId}</td>
                  <td className="py-2.5 pr-4">
                    <span className="text-mist-300">{formatTime(pred.timestamp)}</span>
                    <span className="ml-2 text-[10px] text-mist-600">{formatRelative(pred.timestamp)}</span>
                  </td>
                  <td className="py-2.5 pr-4 text-right tabular-nums text-mist-100">
                    {Math.round(pred.probability * 100)}%
                  </td>
                  <td className="py-2.5 pr-4">
                    <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-semibold ${risk.bg} ${risk.border} ${risk.text}`}>
                      <span className={`size-1.5 rounded-full ${risk.dot}`} aria-hidden="true" />
                      {risk.label}
                    </span>
                  </td>
                  <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-mist-100">
                    {pred.waterLevel.toFixed(2)}m
                  </td>
                  <td className="py-2.5 pr-4 text-mist-300">{pred.modelId}</td>
                  <td className="py-2.5">
                    <span className={`inline-flex rounded-md border px-2 py-0.5 text-[11px] font-semibold ${statusStyles[pred.status]}`}>
                      {pred.status}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        )}
      </div>
    </div>
  )
}