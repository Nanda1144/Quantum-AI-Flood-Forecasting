/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * River selection.
 *
 * ## Deliberately unavailable, and that is the feature
 *
 * The forecast contract carries no river, reach, or catchment field. So this
 * control renders an explicit unavailable state and nothing else. See
 * `scope.ts` for the full evidence, including why the team's sensor-placement
 * fixtures are not a river catalogue.
 *
 * The component is **not** a stub. It is the same controlled contract the
 * station selector uses, so when a river field is added to the backend contract
 * this becomes a populated control by supplying `options` — with no change to the
 * caller's state handling.
 *
 * ## Why no `river` field was added to `NavyaForecastRecord`
 *
 * Adding one would make the record claim the backend carries river identity
 * when it does not, and every downstream guard would then be validating a field
 * that is always empty while readers believe the screen is showing a river. The
 * gap is represented in the selection state instead, which is where it belongs.
 *
 * The `onChange` prop is therefore required even though nothing can currently
 * call it. That is intentional: it keeps the caller's `useState` wired, so
 * enabling rivers later is a data change and not a refactor of every parent.
 */

import { Waves } from 'lucide-react'
import { GlassCard } from '../../components/ui/GlassCard'
import { SectionHeader } from '../../components/ui/SectionHeader'
import { StateBanner } from '../../components/ui/StateBanner'
import { HumanInputNote } from './NavyaProvenancePanel'
import { NO_RIVER_IDENTITY_REASON, type NavyaRiverOption } from './scope'
import type { NavyaForecastRecord } from './types'

interface Props {
  /** Always empty in this revision. See `riversFromRecord`. */
  options: NavyaRiverOption[]
  /** Always `null` in this revision. */
  value: string | null
  /** Wired but not currently reachable. See the module note. */
  onChange: (riverId: string | null) => void
  /** Accepted so the caller's reconciliation is uniform with the station control. */
  record: NavyaForecastRecord | null
  disabled?: boolean
}

const NO_SELECTION = ''

export function NavyaRiverSelector({ options, value, onChange, record, disabled = false }: Props) {
  void record
  return (
    <GlassCard className="space-y-3">
      <SectionHeader
        icon={Waves}
        title="River"
        description="Select the river or reach this forecast belongs to."
      />

      {options.length === 0 ? (
        <StateBanner kind="unavailable" title="No river identity in the contract" message={NO_RIVER_IDENTITY_REASON} />
      ) : (
        <label className="block" htmlFor="navya-river-select">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">
            River
          </span>
          <select
            id="navya-river-select"
            aria-label="River"
            className="mt-1 w-full rounded-lg border border-forest-600 bg-forest-800 px-3 py-2 text-sm text-mist-100 disabled:opacity-60"
            value={value ?? NO_SELECTION}
            disabled={disabled}
            onChange={(event) => {
              const next = event.target.value
              onChange(next === NO_SELECTION ? null : next)
            }}
          >
            <option value={NO_SELECTION}>No river selected</option>
            {options.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
                {option.official ? '' : ' — not from an approved registry'}
              </option>
            ))}
          </select>
        </label>
      )}

      <HumanInputNote tone="info">{NO_RIVER_IDENTITY_REASON}</HumanInputNote>
    </GlassCard>
  )
}
