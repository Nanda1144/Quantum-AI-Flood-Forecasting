import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ModelComparisonRow } from '../../types/ai'
import { chartColors, tooltipStyle } from '../charts/chartTheme'
import { formatDuration, formatMetric } from '../../lib/format'

interface ComparisonChartsProps {
  rows: ModelComparisonRow[]
  selectedModelId: string | null
  onSelectModel: (modelId: string) => void
}

interface ChartDatum {
  modelId: string
  label: string
  value: number
}

interface MetricSpec {
  key: string
  title: string
  unit: string
  pick: (row: ModelComparisonRow) => number | undefined
  /** Reverse so the best value rises to the top of the category axis. */
  bestIsHigh?: boolean
  format: (value: number) => string
}

const METRICS: MetricSpec[] = [
  {
    key: 'mae',
    title: 'MAE comparison',
    unit: 'm',
    pick: (row) => row.metrics.mae,
    format: (value) => formatMetric(value),
  },
  {
    key: 'rmse',
    title: 'RMSE comparison',
    unit: 'm',
    pick: (row) => row.metrics.rmse,
    format: (value) => formatMetric(value),
  },
  {
    key: 'r2',
    title: 'R² comparison',
    unit: '',
    pick: (row) => row.metrics.r2,
    bestIsHigh: true,
    format: (value) => formatMetric(value),
  },
  {
    key: 'inference',
    title: 'Inference-time comparison',
    unit: 'ms',
    pick: (row) => row.inferenceTimeMs,
    format: (value) => formatDuration(value),
  },
]

export function ComparisonCharts({ rows, selectedModelId, onSelectModel }: ComparisonChartsProps) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {METRICS.map((metric) => (
        <MetricChart
          key={metric.key}
          spec={metric}
          rows={rows}
          selectedModelId={selectedModelId}
          onSelectModel={onSelectModel}
        />
      ))}
    </div>
  )
}

function MetricChart({
  spec,
  rows,
  selectedModelId,
  onSelectModel,
}: {
  spec: MetricSpec
  rows: ModelComparisonRow[]
  selectedModelId: string | null
  onSelectModel: (modelId: string) => void
}) {
  const data: ChartDatum[] = rows
    .map((row) => ({ modelId: row.modelId, label: row.name, value: spec.pick(row) ?? NaN }))
    .filter((datum) => Number.isFinite(datum.value))
    .sort((a, b) => a.value - b.value)

  const bestId = data.length > 0 ? (spec.bestIsHigh ? data[data.length - 1].modelId : data[0].modelId) : null

  return (
    <section className="glass-card p-5" aria-label={`${spec.title} chart`}>
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold text-mist-100">{spec.title}</h3>
        <span className="text-[11px] text-mist-600">
          {data.length} of {rows.length} scored
        </span>
      </div>
      {data.length === 0 ? (
        <p className="py-10 text-center text-xs text-mist-600">
          No '{spec.title.split(' ')[0]}' values stored in the current selection.
        </p>
      ) : (
        <div
          role="img"
          aria-label={`${spec.title}. Bars show stored values; the best value is at the top.`}
          style={{ height: 320 }}
        >
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, bottom: 0, left: 8 }} barCategoryGap={4}>
              <CartesianGrid stroke={chartColors.grid} strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tick={{ fill: chartColors.tick, fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis
                dataKey="label"
                type="category"
                width={118}
                tick={{ fill: chartColors.tick, fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                interval={0}
                tickFormatter={(label: string) => (label.length > 16 ? `${label.slice(0, 15)}…` : label)}
              />
              <Tooltip
                contentStyle={tooltipStyle}
                cursor={{ fill: 'rgba(52, 211, 153, 0.08)' }}
                formatter={(value) => [`${spec.format(Number(value))} ${spec.unit}`.trim(), spec.title]}
              />
              <Bar
                dataKey="value"
                name={spec.title}
                radius={[0, 4, 4, 0]}
                onClick={(entry) => {
                  const datum = entry as unknown as { payload: ChartDatum }
                  if (datum?.payload?.modelId) onSelectModel(datum.payload.modelId)
                }}
              >
                {data.map((datum) => {
                  const isBest = datum.modelId === bestId
                  const isSelected = datum.modelId === selectedModelId
                  return (
                    <Cell
                      key={datum.modelId}
                      fill={isSelected ? chartColors.probability : isBest ? chartColors.cyan : chartColors.forest}
                      fillOpacity={isSelected ? 1 : isBest ? 0.9 : 0.55}
                      style={{ cursor: 'pointer' }}
                    />
                  )
                })}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  )
}