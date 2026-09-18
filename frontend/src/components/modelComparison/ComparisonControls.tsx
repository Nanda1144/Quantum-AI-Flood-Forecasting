import { ArrowDownWideNarrow, ArrowUpNarrowWide, RotateCcw } from 'lucide-react'
import type { ComparisonSortKey, ModelComparisonQuery } from '../../types/ai'
import { SORT_OPTIONS } from '../../lib/comparison'

interface ComparisonControlsProps {
  modelNames: string[]
  selectedNames: Set<string>
  onToggleModel: (name: string) => void
  onToggleAll: () => void
  dateFrom: string
  dateTo: string
  onDateFromChange: (value: string) => void
  onDateToChange: (value: string) => void
  sort: ModelComparisonQuery['sort']
  direction: ModelComparisonQuery['direction']
  onSortChange: (key: ComparisonSortKey) => void
  onDirectionToggle: () => void
  onReset: () => void
}

const inputClass =
  'rounded-lg border border-forest-600 bg-forest-900/80 px-2.5 py-1.5 text-xs text-mist-100 outline-none transition-colors hover:border-forest-500 focus:border-emerald-500/70'

export function ComparisonControls({
  modelNames,
  selectedNames,
  onToggleModel,
  onToggleAll,
  dateFrom,
  dateTo,
  onDateFromChange,
  onDateToChange,
  sort,
  direction,
  onSortChange,
  onDirectionToggle,
  onReset,
}: ComparisonControlsProps) {
  const allSelected = modelNames.length > 0 && modelNames.every((name) => selectedNames.has(name))

  return (
    <section className="glass-card p-4" aria-label="Comparison filters">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
        {/* ---- Model multi-select ---- */}
        <fieldset className="min-w-0 flex-1">
          <legend className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-mist-500">
            Compare models
          </legend>
          <div className="flex flex-wrap items-center gap-2">
            <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-forest-600 bg-forest-800/80 px-2.5 py-1 text-xs text-mist-300 transition-colors hover:border-emerald-500/50 hover:text-emerald-300">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={onToggleAll}
                className="size-3.5 accent-emerald-500"
              />
              All
            </label>
            {modelNames.map((name) => {
              const checked = selectedNames.has(name)
              return (
                <label
                  key={name}
                  className={`inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors ${
                    checked
                      ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                      : 'border-forest-600 bg-forest-800/80 text-mist-400 hover:text-mist-200'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => onToggleModel(name)}
                    className="size-3.5 accent-emerald-500"
                  />
                  {name}
                </label>
              )
            })}
            {modelNames.length === 0 && (
              <span className="text-xs text-mist-600">No models in the current view</span>
            )}
          </div>
        </fieldset>

        {/* ---- Evaluation window ---- */}
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-mist-500">Evaluated from</span>
            <input
              type="date"
              value={dateFrom}
              max={dateTo || undefined}
              onChange={(event) => onDateFromChange(event.target.value)}
              className={inputClass}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-mist-500">Evaluated to</span>
            <input
              type="date"
              value={dateTo}
              min={dateFrom || undefined}
              onChange={(event) => onDateToChange(event.target.value)}
              className={inputClass}
            />
          </label>
        </div>

        {/* ---- Metric selector ---- */}
        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-mist-500">Metric</span>
          <select
            value={sort}
            onChange={(event) => onSortChange(event.target.value as ComparisonSortKey)}
            className={`${inputClass} pr-8`}
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        {/* ---- Sort direction ---- */}
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-mist-500">Order</span>
          <div className="flex overflow-hidden rounded-lg border border-forest-600" role="group" aria-label="Sort direction">
            <button
              type="button"
              onClick={() => direction === 'asc' || onDirectionToggle()}
              aria-pressed={direction === 'asc'}
              className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs transition-colors disabled:cursor-default"
              disabled={direction === 'asc'}
              style={direction === 'asc' ? { background: 'rgba(16,185,129,0.15)', color: '#6ee7b7' } : undefined}
            >
              <ArrowUpNarrowWide size={13} aria-hidden="true" />
              Asc
            </button>
            <button
              type="button"
              onClick={() => direction === 'desc' || onDirectionToggle()}
              aria-pressed={direction === 'desc'}
              className="inline-flex items-center gap-1 border-l border-forest-600 px-2.5 py-1.5 text-xs transition-colors disabled:cursor-default"
              disabled={direction === 'desc'}
              style={direction === 'desc' ? { background: 'rgba(16,185,129,0.15)', color: '#6ee7b7' } : undefined}
            >
              <ArrowDownWideNarrow size={13} aria-hidden="true" />
              Desc
            </button>
          </div>
        </div>

        {/* ---- Reset ---- */}
        <button
          type="button"
          onClick={onReset}
          className="inline-flex items-center gap-1.5 rounded-lg border border-forest-600 bg-forest-800 px-3 py-1.5 text-xs font-semibold text-mist-300 transition-colors hover:border-amber-500/60 hover:text-amber-400"
        >
          <RotateCcw size={13} aria-hidden="true" />
          Reset filters
        </button>
      </div>
      <p className="mt-3 text-[11px] text-mist-600">
        Filtering, sorting and metric values are served by the backend — the UI only selects between stored
        evaluations.
      </p>
    </section>
  )
}