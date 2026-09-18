import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ForecastPoint } from '../../types/ai'
import { chartColors, timeTick, tooltipStyle } from './chartTheme'
import { formatTime } from '../../lib/format'

interface ForecastChartProps {
  data: ForecastPoint[]
  /** Reference/alert level in metres. Rendered only when the API provides it. */
  threshold?: number
  height?: number
}

export function ForecastChart({ data, threshold, height = 320 }: ForecastChartProps) {
  const hasObserved = data.some((point) => typeof point.observedWaterLevel === 'number')

  return (
    <div role="img" aria-label="Forecast water level time-series chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 12, right: 12, bottom: 4, left: -8 }}>
          <CartesianGrid stroke={chartColors.grid} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="timestamp"
            tickFormatter={timeTick}
            tick={{ fill: chartColors.tick, fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: chartColors.forest }}
            minTickGap={48}
          />
          <YAxis
            domain={['auto', 'auto']}
            tick={{ fill: chartColors.tick, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value: number) => `${value}m`}
            width={52}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(label) => formatTime(String(label))}
            formatter={(value, name) => {
              const mapping: Record<string, string> = {
                predictedWaterLevel: 'Predicted water level',
                observedWaterLevel: 'Observed',
              }
              return [`${Number(value).toFixed(2)} m`, mapping[String(name)] ?? String(name)]
            }}
          />
          {hasObserved && (
            <Area
              type="monotone"
              dataKey="observedWaterLevel"
              stroke={chartColors.observed}
              strokeWidth={1.5}
              strokeDasharray="5 4"
              fill={chartColors.observed}
              fillOpacity={0.08}
              dot={false}
              activeDot={{ r: 4 }}
            />
          )}
          <Line
            type="monotone"
            dataKey="predictedWaterLevel"
            stroke={chartColors.predicted}
            strokeWidth={2.5}
            dot={false}
            activeDot={{ r: 5, strokeWidth: 0 }}
          />
          {typeof threshold === 'number' && (
            <ReferenceLine
              y={threshold}
              stroke={chartColors.threshold}
              strokeDasharray="8 4"
              strokeOpacity={0.9}
              label={{
                value: `Threshold ${threshold}m`,
                position: 'insideTopRight',
                fill: chartColors.threshold,
                fontSize: 11,
              }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}