/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Station selection.
 *
 * ## Controlled, and it never chooses for you
 *
 * `value` / `onChange` — no internal state. The parent owns the selection, so
 * the selected station is the same value the rest of the screen validated, and
 * there is no second copy that can drift.
 *
 * The control never auto-selects an option. An auto-selected station would look
 * identical to a chosen one, and the reader would have no way to know the
 * system picked for them.
 *
 * ## What an empty state looks like
 *
 * When there are no options the `<select>` is **not rendered at all**. A select
 * with zero options is a dead control: it looks interactive, accepts focus, and
 * produces no choice. Instead an explicit `StateBanner` states that no registry
 * exists and why. An absent control is honest; a broken one is not.
 *
 * Options come only from `stationsFromRecord`, so there is at most one today and
 * its label is the station reference verbatim — never a place name.
 */

import { MapPin } from 'lucide-react'
import { GlassCard } from '../../components/ui/GlassCard'
import { SectionHeader } from '../../components/ui/SectionHeader'
import { StateBanner } from '../../components/ui/StateBanner'
import { HumanInputNote } from './NavyaProvenancePanel'
import { describeDatasetType } from './contract'
import {
  NO_STATION_REGISTRY_REASON,
  describeStationSelection,
  type NavyaStationOption,
} from './scope'
import type { NavyaForecastRecord } from './types'

interface Props {
  options: NavyaStationOption[]
  /** `null` means nothing is selected. Never auto-populated by this component. */
  value: string | null
  onChange: (stationId: string | null) => void
  /** The loaded record, used to reconcile the selection. See `describeStationSelection`. */
  record: NavyaForecastRecord | null
  disabled?: boolean
}

/** Placeholder for the empty selection. Distinct from an option's label. */
const NO_SELECTION = ''

export function NavyaStationSelector({ options, value, onChange, record, disabled = false }: Props) {
  const note = describeStationSelection(record, value)

  return (
    <GlassCard className="space-y-3">
      <SectionHeader
        icon={MapPin}
        title="Station"
        description="Select the gauge this forecast should belong to."
      />

      {options.length === 0 ? (
        <StateBanner kind="unavailable" title="No station registry available" message={NO_STATION_REGISTRY_REASON} />
      ) : (
        <>
          <label className="block" htmlFor="navya-station-select">
            <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">
              Station reference
            </span>
            <select
              id="navya-station-select"
              aria-label="Station reference"
              className="mt-1 w-full rounded-lg border border-forest-600 bg-forest-800 px-3 py-2 text-sm text-mist-100 disabled:opacity-60"
              value={value ?? NO_SELECTION}
              disabled={disabled}
              onChange={(event) => {
                const next = event.target.value
                onChange(next === NO_SELECTION ? null : next)
              }}
            >
              <option value={NO_SELECTION}>No station selected</option>
              {options.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                  {option.official ? '' : ' — not from an approved registry'}
                </option>
              ))}
            </select>
          </label>

          {/*
            The provenance of whatever the option was derived from, stated next
            to the option rather than in a tooltip. A station reference that came
            from a synthetic record is still a synthetic-derived reference.
          */}
          {options.map((option) =>
            value === option.id && option.datasetType !== 'real' ? (
              <HumanInputNote key={`${option.id}-provenance`} tone="warning">
                Derived from {describeDatasetType(option.datasetType)} data. This is a station
                reference, not a verified gauge registration.
              </HumanInputNote>
            ) : null,
          )}
        </>
      )}

      {note !== null && (
        <HumanInputNote tone={note.tone === 'critical' ? 'critical' : 'warning'}>{note.message}</HumanInputNote>
      )}
    </GlassCard>
  )
}
