/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useModelComparison } from '../hooks/useModelComparison'
import { ComparisonHeader } from '../components/modelComparison/ComparisonHeader'
import { SummaryCards } from '../components/modelComparison/SummaryCards'
import { ComparisonControls } from '../components/modelComparison/ComparisonControls'
import { NATURAL_DIRECTION } from '../lib/comparison'
import { ComparisonTable } from '../components/modelComparison/ComparisonTable'
import { ComparisonCharts } from '../components/modelComparison/ComparisonCharts'
import { ModelDetailPanel } from '../components/modelComparison/ModelDetailPanel'
import { ComparisonSkeleton } from '../components/modelComparison/ComparisonSkeleton'
import { StateBanner } from '../components/ui/StateBanner'
import type { ComparisonSortKey, ModelComparisonRow } from '../types/ai'

function toIsoDate(date: string, endOfDay = false): string {
  if (!date) return ''
  return endOfDay ? `${date}T23:59:59.999Z` : `${date}T00:00:00.000Z`
}

/** A row is comparable when it carries at least one of the shown metrics. */
function hasScores(row: ModelComparisonRow): boolean {
  return (
    typeof row.metrics.mae === 'number' ||
    typeof row.metrics.rmse === 'number' ||
    typeof row.metrics.r2 === 'number' ||
    typeof row.inferenceTimeMs === 'number'
  )
}

export function ModelComparison() {
  const { data, loading, error, query, updateQuery, reset, refetch } = useModelComparison()
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null)
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set())
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const detailRef = useRef<HTMLDivElement | null>(null)

  const allNames = useMemo(
    () => [...new Set((data?.items ?? []).map((row) => row.name))].sort(),
    [data],
  )

  // Default the multi-select to every model; keep a user-adjusted selection
  // stable across server-side refetches, dropping names no longer present.
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- syncs the multi-select to the latest model set after a refetch.
    setSelectedNames((prev) => {
      const still = new Set([...prev].filter((name) => allNames.includes(name)))
      if (prev.size === 0) return new Set(allNames)
      return still.size === prev.size ? prev : still
    })
  }, [allNames])

  const visibleRows = useMemo(
    () => (data?.items ?? []).filter((row) => selectedNames.has(row.name)),
    [data, selectedNames],
  )

  const comparableCount = useMemo(() => visibleRows.filter(hasScores).length, [visibleRows])

  const detailModel = useMemo(
    () => data?.items.find((row) => row.modelId === selectedModelId) ?? null,
    [data, selectedModelId],
  )

  const sort: ComparisonSortKey = query.sort ?? 'evaluatedAt'
  const direction = query.direction ?? 'desc'

  const handleSort = (key: ComparisonSortKey) => {
    if (key === sort) {
      updateQuery({ direction: direction === 'asc' ? 'desc' : 'asc' })
    } else {
      updateQuery({ sort: key, direction: NATURAL_DIRECTION[key] })
    }
  }

  const handleSelectModel = (modelId: string) => {
    setSelectedModelId(modelId)
    detailRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' })
  }

  const toggleModel = (name: string) => {
    setSelectedNames((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const toggleAll = () => {
    const fresh = new Set(allNames)
    setSelectedNames((prev) => (prev.size === fresh.size && fresh.size > 0 ? new Set<string>() : fresh))
  }

  const handleDateFrom = (value: string) => {
    setDateFrom(value)
    updateQuery({ from: value ? toIsoDate(value) : undefined })
  }

  const handleDateTo = (value: string) => {
    setDateTo(value)
    updateQuery({ to: value ? toIsoDate(value, true) : undefined })
  }

  const applyReset = () => {
    reset()
    setDateFrom('')
    setDateTo('')
    setSelectedNames(new Set(allNames))
  }

  return (
    <div
      className="min-h-screen px-4 pb-12 pt-6 sm:px-6 lg:px-10"
      aria-busy={loading}
    >
      <div className="mx-auto max-w-[1440px] space-y-5">
        {/* ---- Loading (first paint only) ---- */}
        {loading && !data && <ComparisonSkeleton />}

        {/* ---- Error with no data ---- */}
        {error && !data && (
          <StateBanner
            kind="error"
            title="Unable to load model comparison"
            message={error}
            onRetry={refetch}
          />
        )}

        {/* ---- Loaded but empty registry ---- */}
        {!loading && !error && data && data.items.length === 0 && (
          <StateBanner
            kind="empty"
            title="No model evaluations found"
            message="The model registry returned no versions. Evaluations are added by the training pipeline."
            onRetry={refetch}
          />
        )}

        {/* ---- Data views ---- */}
        {data && data.items.length > 0 && (
          <>
            <ComparisonHeader
              evaluationDatasets={data.evaluationDatasets}
              evaluatedRange={data.evaluatedRange}
              refreshing={loading}
              onRefresh={refetch}
            />

            {error && (
              <StateBanner
                kind="stale"
                title="Refresh failed"
                message={`${error} — showing the last successfully loaded comparison.`}
                onRetry={refetch}
              />
            )}

            {comparableCount === 0 && (
              <StateBanner
                kind="unavailable"
                title="No comparable models"
                message="The registry has versions, but none carry scored evaluations (MAE / RMSE / R² / inference time) in the current filter. Nothing can be compared yet."
                onRetry={refetch}
              />
            )}

            {visibleRows.length === 0 && comparableCount > 0 && (
              <StateBanner
                kind="empty"
                title="No models selected"
                message="Use the 'Compare models' chips to include at least one model, or reset the filters."
                onRetry={() => toggleAll()}
              />
            )}

            <ComparisonControls
              modelNames={allNames}
              selectedNames={selectedNames}
              onToggleModel={toggleModel}
              onToggleAll={toggleAll}
              dateFrom={dateFrom}
              dateTo={dateTo}
              onDateFromChange={handleDateFrom}
              onDateToChange={handleDateTo}
              sort={sort}
              direction={direction}
              onSortChange={handleSort}
              onDirectionToggle={() => updateQuery({ direction: direction === 'asc' ? 'desc' : 'asc' })}
              onReset={applyReset}
            />

            {visibleRows.length > 0 && (
              <>
                <SummaryCards rows={visibleRows} highlightKey={sort} />
                <ComparisonTable
                  rows={visibleRows}
                  sort={sort}
                  direction={direction}
                  selectedModelId={selectedModelId}
                  onSelectModel={handleSelectModel}
                  onSort={handleSort}
                />
                <ComparisonCharts
                  rows={visibleRows}
                  selectedModelId={selectedModelId}
                  onSelectModel={handleSelectModel}
                />
                <div ref={detailRef} className="scroll-mt-24">
                  <ModelDetailPanel model={detailModel} />
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}