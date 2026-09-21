/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * The four scientific comparison charts for the selected experiment:
 * runtime, objective, solution quality (approximation ratio vs a 1.0
 * reference) and constraint violations. All values render exactly as stored —
 * nothing is re-derived except formatting.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { OptimizationResult } from '../../types/optimization'
import { approximationRatio } from '../../lib/benchmark'
import { chartColors, tooltipStyle } from '../charts/chartTheme'
import { formatDuration } from '../../lib/format'

interface BenchmarkChartsProps {
  result: OptimizationResult
}

const CLASSICAL_COLOR = chartColors.forest
const QAOA_COLOR = chartColors.cyan
const VALID_COLOR = chartColors.emerald
const INVALID_COLOR = chartColors.critical

export function BenchmarkCharts({ result }: BenchmarkChartsProps) {
  const classical = result.classicalComparison
  const ratio = approximationRatio(result)
  const feasible = result.constraintViolations.length === 0

  return (
    <section className="grid grid-cols-1 gap-4 lg:grid-cols-2" aria-label="Benchmark charts">
      <PairChart
        title="Runtime comparison"
        ariaLabel="Runtime comparison. Bars show the stored wall time for the classical reference and for QAOA; lower is faster but no speedup is claimed."
        data={[{ name: 'Wall time', classical: classical.executionTimeMs, qaoa: result.executionTimeMs }]}
        formatValue={(value: number) => formatDuration(value)}
      />
      <PairChart
        title="Objective comparison"
        ariaLabel="Objective comparison. Bars show the fraction of weighted utility captured; the higher bar is better on this metric."
        data={[{ name: 'Objective', classical: classical.objectiveValue * 100, qaoa: result.objectiveValue * 100 }]}
        formatValue={(value: number) => `${value.toFixed(2)}%`}
      />
      <section className="glass-card p-5" aria-label="Solution quality chart">
        <h3 className="text-sm font-semibold text-mist-100">Solution quality</h3>
        <p className="mt-0.5 text-[11px] text-mist-500">
          Approximation ratio = QAOA objective ÷ classical objective. The amber line is parity (1.0).
        </p>
        <div role="img" aria-label="Approximation ratio. Values below 1.0 mean the classical reference found a better solution; equal to 1.0 is parity." style={{ height: 300 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={[{ name: 'Approximation ratio', value: ratio ?? 0 }]} margin={{ top: 24, right: 16, bottom: 4, left: 8 }}>
              <CartesianGrid stroke={chartColors.grid} strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fill: chartColors.tick, fontSize: 11 }} tickLine={false} axisLine={false} />
              <YAxis
                domain={[0, (dataMax: number) => Math.max(1.1, dataMax * 1.15)]}
                tick={{ fill: chartColors.tick, fontSize: 10 }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip contentStyle={tooltipStyle} formatter={(value) => [Number(value).toFixed(3), 'Approximation ratio']} />
              <ReferenceLine
                y={1}
                stroke={chartColors.threshold}
                strokeDasharray="4 4"
                label={{ value: 'parity 1.0', fill: chartColors.threshold, fontSize: 10, position: 'insideTopRight' }}
              />
              <Bar dataKey="value" name="Approximation ratio" radius={[4, 4, 0, 0]} maxBarSize={80}>
                <Cell fill={ratio !== null && ratio >= 1 ? VALID_COLOR : ratio !== null ? INVALID_COLOR : chartColors.forest} />
                <LabelList
                  dataKey="value"
                  position="top"
                  formatter={(value) => (ratio !== null ? Number(value).toFixed(3) : '—')}
                  style={{ fill: chartColors.tick, fontSize: 11 }}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
      <section className="glass-card p-5" aria-label="Constraint violations chart">
        <h3 className="text-sm font-semibold text-mist-100">Constraint violations</h3>
        <p className="mt-0.5 text-[11px] text-mist-500">
          Violations in the QAOA decode. The classical reference is feasible by construction (0 stored).
        </p>
        <div role="img" aria-label="Constraint violations recorded for this experiment." style={{ height: 300 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={[{ name: 'Constraint violations', value: result.constraintViolations.length }]} margin={{ top: 24, right: 16, bottom: 4, left: 8 }}>
              <CartesianGrid stroke={chartColors.grid} strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fill: chartColors.tick, fontSize: 11 }} tickLine={false} axisLine={false} />
              <YAxis allowDecimals={false} tick={{ fill: chartColors.tick, fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} formatter={(value) => [`${value}`, 'Violations']} />
              <Bar dataKey="value" name="Constraint violations" radius={[4, 4, 0, 0]} maxBarSize={80}>
                <Cell fill={feasible ? VALID_COLOR : INVALID_COLOR} />
                <LabelList dataKey="value" position="top" style={{ fill: chartColors.tick, fontSize: 11 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
    </section>
  )
}

interface PairChartProps {
  title: string
  ariaLabel: string
  data: { name: string; classical: number; qaoa: number }[]
  formatValue: (value: number) => string
}

function PairChart({ title, ariaLabel, data, formatValue }: PairChartProps) {
  return (
    <section className="glass-card p-5" aria-label={title}>
      <h3 className="text-sm font-semibold text-mist-100">{title}</h3>
      <div role="img" aria-label={ariaLabel} style={{ height: 300 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 8 }} barCategoryGap={4}>
            <CartesianGrid stroke={chartColors.grid} strokeDasharray="3 3" />
            <XAxis dataKey="name" tick={{ fill: chartColors.tick, fontSize: 11 }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fill: chartColors.tick, fontSize: 10 }} tickLine={false} axisLine={false} width={64} />
            <Tooltip contentStyle={tooltipStyle} formatter={(value, name) => [formatValue(Number(value)), name]} />
            <Bar dataKey="classical" name="Classical" fill={CLASSICAL_COLOR} radius={[4, 4, 0, 0]} maxBarSize={90} />
            <Bar dataKey="qaoa" name="QAOA" fill={QAOA_COLOR} radius={[4, 4, 0, 0]} maxBarSize={90} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}