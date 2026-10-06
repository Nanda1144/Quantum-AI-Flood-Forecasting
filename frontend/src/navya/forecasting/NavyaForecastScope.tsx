/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Station + river selection for the forecast screen.
 *
 * ## Where selection actually flows
 *
 * The honest answer is that it does **not** flow into the request, because the
 * request has nowhere to put it: `/api/ai/forecast` takes no station or river
 * parameter, and the running contract carries no such field. Inventing a query
 * string here would produce a URL the backend silently ignores, which is worse
 * than no propagation at all — it would look wired up.
 *
 * So selection is propagated in the only direction that is real: **from the
 * screen into a reconciliation against the record that actually came back.**
 * `stationScopeStatus` compares the chosen station with
 * `record.provenance.stationReference`, and a disagreement is surfaced as a
 * critical note rather than quietly rendering one station's forecast under
 * another station's selection.
 *
 * ## Controlled
 *
 * Selection state lives in the parent (`NavyaForecastPage`). This component
 * receives it and reports changes. That keeps one source of truth for the
 * selection, so the value the user picked is the value that gets validated.
 *
 * ## Composition only
 *
 * Both selectors are reusable on their own and are tested independently. This
 * file only places them and derives their options from the record.
 */

import { NavyaRiverSelector } from './NavyaRiverSelector'
import { NavyaStationSelector } from './NavyaStationSelector'
import { riversFromRecord, stationsFromRecord } from './scope'
import type { NavyaForecastRecord } from './types'

interface Props {
  record: NavyaForecastRecord | null
  stationId: string | null
  riverId: string | null
  onStationChange: (stationId: string | null) => void
  onRiverChange: (riverId: string | null) => void
  /** Disabled while a load is in flight, so the selection cannot race the record. */
  disabled?: boolean
}

export function NavyaForecastScope({
  record,
  stationId,
  riverId,
  onStationChange,
  onRiverChange,
  disabled = false,
}: Props) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2" data-testid="navya-forecast-scope">
      <NavyaStationSelector
        options={stationsFromRecord(record)}
        value={stationId}
        onChange={onStationChange}
        record={record}
        disabled={disabled}
      />
      <NavyaRiverSelector
        options={riversFromRecord(record)}
        value={riverId}
        onChange={onRiverChange}
        record={record}
        disabled={disabled}
      />
    </div>
  )
}
