/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import {
  CartesianGrid,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ComposedChart,
} from 'recharts'
import { chartColors, timeTick, tooltipStyle } from '../../components/charts/chartTheme'
import { formatDateTime } from '../../lib/format'
import type { NavyaBacktestPoint } from './types'

interface Props {
  points: NavyaBacktestPoint[]
  /** Reference stage in target units. Drawn only when the record supplies one. */
  threshold?: number | null
  /** Appended to the threshold legend entry so a pending stage is visible on the chart. */
  thresholdSuffix?: string
  height?: number
  title: string
}

/**
 * Predicted versus observed over the backtest window.
 *
 * ## What this chart will not do
 *
 * - **It does not smooth.** A smoother would hide exactly the peak error that
 *   matters operationally.
 * - **It does not extrapolate past the last point.** The line ends where the data
 *   ends. A dashed continuation would be a forecast the model did not make.
 * - **It does not invent an axis.** With no points, it renders a message rather
 *   than an empty frame with default-looking bounds.
 * - **It does not draw a threshold line the backend did not send.** The team's
 *   `ForecastChart` has the same rule; a reference line is the single most
 *   persuasive thing on a flood chart, so it is only drawn from a real value.
 *
 * The observed series is required to be non-null per point by the normalizer, so
 * there is no gap-filling to do here — a missing observation was already dropped
 * upstream, and the count on screen is the count of complete pairs.
 */
export function NavyaForecastSeriesChart({
  points,
  threshold = null,
  thresholdSuffix = '',
  height = 320,
  title,
}: Props) {
  if (points.length === 0) {
    return (
      <div
        role="img"
        aria-label={`${title} — no data`}
        className="flex items-center justify-center rounded-lg border border-dashed border-forest-600 bg-forest-800/40 text-xs text-mist-500"
        style={{ height }}
      >
        No backtest data is available for this forecast. Nothing is plotted.
      </div>
    )
  }

  return (
    <div role="img" aria-label={title} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: 12, right: 12, bottom: 4, left: -8 }}>
          <CartesianGrid stroke={chartColors.grid} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="timestamp"
            tickFormatter={timeTick}
            tick={{ fill: chartColors.tick, fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: chartColors.forest }}
            minTickGap={24}
          />
          <YAxis
            tick={{ fill: chartColors.tick, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={56}
            domain={['auto', 'auto']}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(value) => formatDateTime(String(value))}
            formatter={(value, name) => [
              typeof value === 'number' ? value.toFixed(4) : String(value),
              String(name),
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: chartColors.tick }} />
          {threshold !== null && Number.isFinite(threshold) && (
            <ReferenceLine
              y={threshold}
              stroke={chartColors.threshold}
              strokeDasharray="5 4"
              label={{
                value: `threshold ${threshold}${thresholdSuffix}`,
                fill: chartColors.threshold,
                fontSize: 11,
                position: 'insideTopRight',
              }}
            />
          )}
          <Line
            type="monotone"
            dataKey="observed"
            name="observed"
            stroke={chartColors.observed}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="predicted"
            name="predicted"
            stroke={chartColors.predicted}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
