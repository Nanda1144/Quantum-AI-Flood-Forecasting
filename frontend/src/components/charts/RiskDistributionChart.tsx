/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import type { RiskDistribution } from '../../types/ai'
import { riskStyle } from '../../lib/risk'
import { tooltipStyle } from './chartTheme'

interface RiskDistributionChartProps {
  data: RiskDistribution[]
  height?: number
}

export function RiskDistributionChart({ data, height = 200 }: RiskDistributionChartProps) {
  const total = data.reduce((sum, item) => sum + item.count, 0)

  return (
    <div role="img" aria-label="Risk level distribution donut chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(value, name, item) => {
              const payload = (item as { payload?: RiskDistribution } | undefined)?.payload
              const level = payload?.riskLevel ?? String(name).replace(/^riskLevel/, '').replace(/^Risk /, '')
              return [`${value} stations`, `Risk ${String(level).trim()}`]
            }}
          />
          <Pie
            data={data}
            dataKey="count"
            nameKey="riskLevel"
            innerRadius="58%"
            outerRadius="86%"
            paddingAngle={3}
            stroke="none"
            cornerRadius={4}
          >
            {data.map((entry) => (
              <Cell key={entry.riskLevel} fill={riskStyle(entry.riskLevel).dot} className="outline-none" />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <p className="mt-1 text-center text-[11px] text-mist-600">
        {total} monitored locations
      </p>
      <div className="sr-only">
        {data.map((entry) => `${entry.riskLevel}: ${entry.count}`).join(', ')}
      </div>
    </div>
  )
}