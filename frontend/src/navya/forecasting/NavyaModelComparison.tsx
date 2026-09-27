/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { GitCompareArrows } from 'lucide-react'
import { GlassCard } from '../../components/ui/GlassCard'
import { SectionHeader } from '../../components/ui/SectionHeader'
import { assertComparisonIsHonest, humanInputRequired, rowIsScored, rowUnavailableReason } from './contract'
import type { NavyaModelComparison as Comparison, NavyaModelComparisonRow } from './types'
import { HumanInputNote } from './NavyaProvenancePanel'

/** `—` for an absent score. A dash is never read as a zero here. */
function num(value: number | null, digits = 4): string {
  return value === null ? '—' : value.toFixed(digits)
}

interface Props {
  comparison: Comparison | null
  /** Set when the comparison request failed while the forecast succeeded. */
  error?: string | null
}

/**
 * The candidate ranking, with the selection rule visible.
 *
 * ## The one invariant this table exists to protect
 *
 * Model selection uses the **validation** split. The **test** split is scored
 * once, afterwards, by the already-chosen model. If the test split had any part
 * in ranking, the resulting score would be a selection statistic wearing a
 * held-out label — the single most common way a reported score stops meaning
 * anything.
 *
 * So the header states the ranking split and the selection metric, the selected
 * row is marked, and `assertComparisonIsHonest` refuses to render a payload that
 * claims to have ranked on the test split at all. It throws rather than
 * degrading: a table that silently repairs a broken provenance claim is worse
 * than a visible failure, because the reader has no way to know a repair
 * happened.
 *
 * ## Rows that could not run
 *
 * A candidate that did not execute is shown with its reason, not with a dash.
 * A dash in an RMSE column is ambiguous between "not measured" and "measured as
 * zero", and only one of those is a real result.
 */
export function NavyaModelComparison({ comparison, error = null }: Props) {
  if (error !== null) {
    return (
      <GlassCard className="space-y-3">
        <SectionHeader icon={GitCompareArrows} title="Model comparison" />
        <HumanInputNote tone="warning">
          The model comparison could not be loaded: {error} The forecast above is unaffected. No
          substitute table is shown.
        </HumanInputNote>
      </GlassCard>
    )
  }

  if (comparison === null) {
    return (
      <GlassCard className="space-y-3">
        <SectionHeader icon={GitCompareArrows} title="Model comparison" />
        <HumanInputNote tone="warning">
          No model comparison is available. {humanInputRequired()}
        </HumanInputNote>
      </GlassCard>
    )
  }

  assertComparisonIsHonest(comparison)

  const executed = comparison.rows.filter(rowIsScored)

  return (
    <GlassCard className="space-y-3">
      <SectionHeader
        icon={GitCompareArrows}
        title="Model comparison"
        description={`ranked on the ${comparison.selectionSplit} split by ${comparison.selectionMetric}`}
      />

      <HumanInputNote tone="info">
        These scores were measured on the <strong>{comparison.selectionSplit}</strong> split, which
        the model was selected on. They are optimistic by construction and are not a held-out
        estimate. {comparison.heldOutScored
          ? `The ${comparison.heldOutSplit} split has been scored once by the selected model only.`
          : `The ${comparison.heldOutSplit} split has not been scored.`}
      </HumanInputNote>

      <HumanInputNote tone="warning">{comparison.metricsLabel}</HumanInputNote>

      {comparison.rows.length === 0 ? (
        <HumanInputNote tone="warning">
          The comparison carries no candidates. No ranking is displayed.
        </HumanInputNote>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <caption className="sr-only">
              Candidate models ranked on the {comparison.selectionSplit} split. Metrics are{' '}
              {comparison.metricsLabel}
            </caption>
            <thead>
              <tr className="border-b border-forest-600 text-[10px] uppercase tracking-[0.14em] text-mist-500">
                <th scope="col" className="py-2 pr-3">Candidate</th>
                <th scope="col" className="py-2 pr-3">Algorithm</th>
                <th scope="col" className="py-2 pr-3 text-right">RMSE</th>
                <th scope="col" className="py-2 pr-3 text-right">MAE</th>
                <th scope="col" className="py-2 pr-3 text-right">R²</th>
                <th scope="col" className="py-2 pr-3 text-right">NSE</th>
                <th scope="col" className="py-2 pr-3 text-right">n</th>
                <th scope="col" className="py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {comparison.rows.map((row) => (
                <Row key={row.key} row={row} metric={comparison.selectionMetric} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[11px] text-mist-600">
        {executed.length} of {comparison.rows.length} candidates executed. Scores are reproduced
        from the engine; this component computes none of them.
      </p>
    </GlassCard>
  )
}

function Row({ row, metric }: { row: NavyaModelComparisonRow; metric: string }) {
  const scored = rowIsScored(row)
  return (
    <tr
      className={`border-b border-forest-600/40 ${row.selected ? 'bg-ai-500/5' : ''}`}
      data-selected={row.selected}
    >
      <th scope="row" className="py-2 pr-3 font-medium text-mist-100">
        {row.displayName}
        {row.selected && (
          <span className="ml-2 rounded border border-ai-500/40 px-1.5 py-0.5 text-[10px] font-semibold text-ai-300">
            SELECTED
          </span>
        )}
      </th>
      <td className="py-2 pr-3 text-mist-400">{row.algorithm || '—'}</td>
      <ScoreCell value={row.rmse} />
      <ScoreCell value={row.mae} />
      <ScoreCell value={row.r2} />
      <ScoreCell value={row.nse} />
      <td className="py-2 pr-3 text-right tabular-nums text-mist-400">
        {row.nSamples === null ? '—' : row.nSamples}
      </td>
      <td className="py-2 text-mist-400">
        {scored ? (
          <span className="text-emerald-300">executed</span>
        ) : (
          <span className="text-amber-400">
            {rowUnavailableReason(row)}
            <span className="block text-[10px] text-mist-600">no {metric} recorded</span>
          </span>
        )}
      </td>
    </tr>
  )
}

/** A score cell. An absent score is a dash, never a 0.00. */
function ScoreCell({ value }: { value: number | null }) {
  return (
    <td className="py-2 pr-3 text-right tabular-nums text-mist-200">
      {value === null ? <span className="text-mist-600">—</span> : num(value)}
    </td>
  )
}
