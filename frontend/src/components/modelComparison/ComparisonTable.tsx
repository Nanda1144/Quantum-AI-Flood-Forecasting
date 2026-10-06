/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { ChevronDown, ChevronUp, ChevronsUpDown } from 'lucide-react'
import type { ComparisonSortKey, ModelComparisonRow } from '../../types/ai'
import { formatDateTime, formatDuration, formatMetric } from '../../lib/format'
import { StatusBadge } from './StatusBadge'

interface ComparisonTableProps {
  rows: ModelComparisonRow[]
  sort: ComparisonSortKey
  direction: 'asc' | 'desc'
  selectedModelId: string | null
  onSelectModel: (modelId: string) => void
  onSort: (key: ComparisonSortKey) => void
}

interface ColumnDef {
  key?: ComparisonSortKey
  label: string
  align?: 'right'
  className?: string
}

const COLUMNS: ColumnDef[] = [
  { key: 'name', label: 'Model' },
  { label: 'Version' },
  { label: 'Dataset' },
  { label: 'Algorithm' },
  { key: 'mae', label: 'MAE', align: 'right' },
  { key: 'rmse', label: 'RMSE', align: 'right' },
  { key: 'r2', label: 'R²', align: 'right' },
  { label: 'Training Time', align: 'right' },
  { key: 'inferenceTime', label: 'Inference', align: 'right' },
  { label: 'Status' },
  { key: 'evaluatedAt', label: 'Evaluated At' },
  { label: '' },
]

export function ComparisonTable({
  rows,
  sort,
  direction,
  selectedModelId,
  onSelectModel,
  onSort,
}: ComparisonTableProps) {
  return (
    <section className="glass-card p-0" aria-label="Model comparison table">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[980px] border-collapse text-left text-xs">
          <caption className="sr-only">
            Model evaluation comparison. Values are exactly as stored in the model registry.
          </caption>
          <thead>
            <tr className="border-b border-forest-700/70 text-[11px] uppercase tracking-wider text-mist-500">
              {COLUMNS.map((column, index) => {
                const active = column.key === sort
                const ariaSort = active
                  ? direction === 'asc'
                    ? 'ascending'
                    : 'descending'
                  : 'none'
                const content = column.key ? (
                  <button
                    type="button"
                    onClick={() => onSort(column.key!)}
                    className="inline-flex items-center gap-1 transition-colors hover:text-emerald-300"
                    aria-label={`Sort by ${column.label}`}
                  >
                    {column.label}
                    {active ? (
                      direction === 'asc' ? (
                        <ChevronUp size={12} aria-hidden="true" />
                      ) : (
                        <ChevronDown size={12} aria-hidden="true" />
                      )
                    ) : (
                      <ChevronsUpDown size={12} className="opacity-50" aria-hidden="true" />
                    )}
                  </button>
                ) : (
                  column.label
                )
                return (
                  <th
                    key={index}
                    scope="col"
                    aria-sort={ariaSort}
                    className={`whitespace-nowrap px-4 py-3 font-semibold ${
                      column.align === 'right' ? 'text-right' : ''
                    } ${column.key ? 'text-mist-300' : ''}`}
                  >
                    {content}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const selected = row.modelId === selectedModelId
              return (
                <tr
                  key={row.modelId}
                  onClick={() => onSelectModel(row.modelId)}
                  aria-selected={selected}
                  className={`cursor-pointer border-b border-forest-800/80 transition-colors hover:bg-forest-800/40 ${
                    selected ? 'bg-emerald-500/10' : ''
                  }`}
                >
                  <th scope="row" className="max-w-[190px] px-4 py-3 font-normal">
                    <p className="truncate font-semibold text-mist-50" title={row.name}>
                      {row.name}
                    </p>
                  </th>
                  <td className="max-w-[140px] truncate px-4 py-3 font-mono text-xs text-mist-400" title={row.version}>
                    {row.version}
                  </td>
                  <td className="max-w-[160px] truncate px-4 py-3 font-mono text-[11px] text-mist-500" title={row.dataset}>
                    {row.dataset}
                  </td>
                  <td className="max-w-[160px] truncate px-4 py-3 text-mist-300" title={row.algorithm}>
                    {row.algorithm}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-mist-200">
                    {formatMetric(row.metrics.mae)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-mist-200">
                    {formatMetric(row.metrics.rmse)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-mist-200">
                    {formatMetric(row.metrics.r2)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-mist-300">
                    {formatDuration(row.trainingTimeMs)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-mist-300">
                    {formatDuration(row.inferenceTimeMs)}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={row.status} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-[11px] text-mist-400">
                    {row.evaluatedAt ? formatDateTime(row.evaluatedAt) : 'Not evaluated'}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation()
                        onSelectModel(row.modelId)
                      }}
                      className="rounded-md border border-forest-600 px-2 py-1 text-[11px] font-semibold text-mist-300 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
                    >
                      Details
                    </button>
                  </td>
                </tr>
              )
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length} className="px-4 py-8 text-center text-sm text-mist-600">
                  Nothing to compare in the current selection.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}