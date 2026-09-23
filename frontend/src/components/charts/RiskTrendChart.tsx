/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { TrendPoint } from '../../types/ai'
import { chartColors, timeTick, tooltipStyle } from './chartTheme'
import { formatTime } from '../../lib/format'

interface TrendChartProps {
  data: TrendPoint[]
  /** Stroke/fill color. */
  color?: string
  height?: number
  unit?: string
  ariaLabel?: string
}

export function RiskTrendChart({ data, color = chartColors.risk, height = 220, unit = '', ariaLabel = 'Risk trend chart' }: TrendChartProps) {
  return (
    <div role="img" aria-label={ariaLabel} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -12 }}>
          <defs>
            <linearGradient id={`gradient-${color}-${unit}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={color} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={chartColors.grid} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="timestamp"
            tickFormatter={timeTick}
            tick={{ fill: chartColors.tick, fontSize: 10 }}
            tickLine={false}
            axisLine={{ stroke: chartColors.forest }}
            minTickGap={40}
          />
          <YAxis
            domain={[0, 1]}
            tick={{ fill: chartColors.tick, fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value: number) => `${Math.round(value * 100)}%`}
            width={46}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(label) => formatTime(String(label))}
            formatter={(value) => [`${(Number(value) * 100).toFixed(1)}%${unit}`, 'Score']}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={2}
            fill={`url(#gradient-${color}-${unit})`}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}