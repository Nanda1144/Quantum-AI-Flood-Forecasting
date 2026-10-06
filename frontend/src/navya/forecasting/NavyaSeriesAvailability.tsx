/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * The series the forecast graph section must account for: rainfall and inflow.
 *
 * ## Why both are shown as unavailable instead of omitted
 *
 * The task list requires a rainfall graph and an inflow graph. Neither has a data
 * source:
 *
 * - **Rainfall** — no rainfall field exists in the forecast contract. The model
 *   *input* list may name a rainfall feature (`featureList`), but a feature name
 *   is not a measurement, and rendering it next to "rainfall" would let it be
 *   read as data.
 * - **Inflow** — `predictedInflow` is part of the record but every normalised
 *   payload sends `null`, and the contract sends no inflow series.
 *
 * So the panel renders an explicit absence with the reason, exactly as the
 * provenance panel renders "not recorded". A blank space where a graph belongs
 * is read as a loading failure or an oversight; a stated absence is read as the
 * truth. Every number stays where it is: none are invented here.
 *
 * ## Historical vs predicted
 *
 * The observed-versus-predicted distinction for the water-level series lives in
 * `NavyaForecastSeriesChart`'s legend (`observed` / `predicted`). The caption
 * below repeats it next to the panels so the whole section reads consistently.
 */

import { CloudRain, Waves } from 'lucide-react'
import { GlassCard } from '../../components/ui/GlassCard'
import { SectionHeader } from '../../components/ui/SectionHeader'
import { HumanInputNote } from './NavyaProvenancePanel'
import type { NavyaForecastRecord } from './types'

interface Props {
  forecast: NavyaForecastRecord
}

/** True when the model's input list references rainfall at all. */
function hasRainfallFeature(forecast: NavyaForecastRecord): boolean {
  return forecast.provenance.featureList.some((feature) => /rain|precip/i.test(feature))
}

export function NavyaSeriesAvailability({ forecast }: Props) {
  const rainfallMentioned = hasRainfallFeature(forecast)
  const inflowKnown = forecast.predictedInflow !== null && Number.isFinite(forecast.predictedInflow)
  const units = forecast.provenance.targetUnits

  return (
    <GlassCard className="space-y-4">
      <SectionHeader
        icon={Waves}
        title="Rainfall & inflow"
        description="The series the contract does and does not carry, stated plainly."
      />

      <section aria-label="Rainfall series" className="border-t border-forest-600/60 pt-3">
        <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">
          <CloudRain size={12} aria-hidden="true" />
          Rainfall
        </h3>
        <HumanInputNote tone="info">
          No rainfall series is carried by the forecast contract.
          {rainfallMentioned
            ? ' Rainfall appears only as an input feature name in the model feature list — a feature name is not a measurement, so nothing is plotted.'
            : ' Nothing is plotted in its place.'}
        </HumanInputNote>
      </section>

      <section aria-label="Inflow series" className="border-t border-forest-600/60 pt-3">
        <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">
          <Waves size={12} aria-hidden="true" />
          Inflow
        </h3>
        {inflowKnown ? (
          <p className="text-sm font-medium text-mist-200">
            {forecast.predictedInflow?.toFixed(3)} {units ?? 'units not recorded'}
          </p>
        ) : (
          <HumanInputNote tone="info">
            The contract sends no inflow prediction or series for this forecast; the inflow
            value is not recorded. Nothing is plotted in its place.
          </HumanInputNote>
        )}
      </section>

      <p className="border-t border-forest-600/60 pt-3 text-[11px] text-mist-600">
        In the forecast series chart above, the <strong>observed</strong> line is the historical
        record and the <strong>predicted</strong> line is the model output. Neither line is
        extrapolated past the data it was given.
      </p>
    </GlassCard>
  )
}