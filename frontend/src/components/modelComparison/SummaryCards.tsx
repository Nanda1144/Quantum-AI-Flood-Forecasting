import { Award, Gauge, TrendingUp, Timer, Zap } from 'lucide-react'
import type { ComparisonSortKey, ModelComparisonRow } from '../../types/ai'
import { formatDuration, formatMetric } from '../../lib/format'

interface SummaryCardsProps {
  rows: ModelComparisonRow[]
  /** Column currently driving the table sort — highlighted when it matches. */
  highlightKey: ComparisonSortKey
}

interface CardData {
  value: string
  sub: string
}

function bestScored(
  rows: ModelComparisonRow[],
  pick: (row: ModelComparisonRow) => number | undefined,
  mode: 'min' | 'max' = 'min',
): { value: number; row: ModelComparisonRow } | null {
  let found: { value: number; row: ModelComparisonRow } | null = null
  for (const row of rows) {
    const value = pick(row)
    if (value === undefined) continue
    if (found === null || (mode === 'min' ? value < found.value : value > found.value)) {
      found = { value, row }
    }
  }
  return found
}

/**
 * Ranks rows using the values the backend stored — the frontend only sorts and
 * selects extrema; it never computes a metric.
 */
export function SummaryCards({ rows, highlightKey }: SummaryCardsProps) {
  const bestRmse = bestScored(rows, (r) => r.metrics.rmse)
  const bestMae = bestScored(rows, (r) => r.metrics.mae)
  const bestR2 = bestScored(rows, (r) => r.metrics.r2, 'max')
  const fastest = bestScored(rows, (r) => r.inferenceTimeMs)

  const overall = bestR2 ?? bestRmse
  const overallMetric = bestR2 ? 'R²' : bestRmse ? 'RMSE' : null

  const cards: {
    key: ComparisonSortKey
    label: string
    icon: typeof Award
    data: CardData | null
  }[] = [
    {
      key: 'r2',
      label: 'Best performing',
      icon: Award,
      data: overall
        ? {
            value: `${overallMetric}: ${formatMetric(overall.value)}`,
            sub: `${overall.row.name} · ${overall.row.version}`,
          }
        : null,
    },
    {
      key: 'mae',
      label: 'Lowest MAE',
      icon: Gauge,
      data: bestMae ? { value: formatMetric(bestMae.value), sub: `${bestMae.row.name} · ${bestMae.row.version}` } : null,
    },
    {
      key: 'rmse',
      label: 'Lowest RMSE',
      icon: TrendingUp,
      data: bestRmse ? { value: formatMetric(bestRmse.value), sub: `${bestRmse.row.name} · ${bestRmse.row.version}` } : null,
    },
    {
      key: 'r2',
      label: 'Highest R²',
      icon: Zap,
      data: bestR2 ? { value: formatMetric(bestR2.value), sub: `${bestR2.row.name} · ${bestR2.row.version}` } : null,
    },
    {
      key: 'inferenceTime',
      label: 'Fastest inference',
      icon: Timer,
      data: fastest
        ? { value: formatDuration(fastest.value), sub: `${fastest.row.name} · ${fastest.row.version}` }
        : null,
    },
  ]

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      {cards.map((card) => (
        <section
          key={card.label}
          className={`glass-card p-4 ${card.key === highlightKey ? 'ring-1 ring-emerald-500/40' : ''}`}
          aria-label={card.label}
        >
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-mist-500">
            <card.icon size={14} className="text-emerald-400" aria-hidden="true" />
            {card.label}
          </div>
          {card.data ? (
            <>
              <p className="mt-2 font-mono text-lg font-bold text-mist-50">{card.data.value}</p>
              <p className="mt-1 truncate text-xs text-mist-400" title={card.data.sub}>
                {card.data.sub}
              </p>
            </>
          ) : (
            <p className="mt-2 text-sm text-mist-600">No scored evaluation in selection</p>
          )}
        </section>
      ))}
    </div>
  )
}