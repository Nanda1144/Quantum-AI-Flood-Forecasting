/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Station and river selection scope.
 *
 * ## The situation this file exists to describe honestly
 *
 * The task list asks for station selection and river selection. Neither can be
 * populated from a registry, because neither registry exists:
 *
 * - **Stations.** `ai-service` Phase 1-8 carries `station_reference: str | None`
 *   — a *single* configured gauge identifier read from `HYDRO_STATION_REFERENCE`
 *   (`ai-service/app/engines/hydro/config.py`), and `config.py` records it as
 *   missing when it is `None`. There is no station collection, no station list
 *   endpoint, and no `station_id -> station` mapping anywhere in this
 *   repository. The frontend contract mirrors this exactly: one nullable
 *   `provenance.stationReference` on the record.
 * - **Rivers.** There is no river, reach, or catchment field in the forecast
 *   contract at all. `river`, `basin` and `catchment` appear in Phase 1-8 only
 *   inside prose. The team's `src/test/fixtures.ts` does contain a
 *   "Panama Basin" zone with lat/long and exposure fractions — that is a
 *   **sensor-placement / QUBO candidate** fixture for a different subsystem,
 *   owned by the team, and treating it as a hydrological river registry would be
 *   inventing a river catalogue out of optimizer test data.
 *
 * So the selectors in this module are built to be *correct when empty*. They
 * render an explicit unavailable state with a reason, and they refuse to offer
 * an option that no contract field backs.
 *
 * ## What a station option may be derived from
 *
 * Exactly one source, and it is a real contract field rather than a registry:
 * `provenance.stationReference` on a record that was actually loaded. That
 * yields **at most one** option, labelled with the reference verbatim. It is
 * marked `official: false` unconditionally, because an official designation
 * would require an approved station registry, and `thresholdIsOfficial`-style
 * approval logic must not be quietly reused to imply a station is registered.
 *
 * ## What this module will not do
 *
 * It does not invent station names, river names, coordinates, or reach
 * identifiers. It does not add a `river` field to `NavyaForecastRecord` to
 * pretend the backend sends one. It does not auto-select anything: the caller
 * owns selection, and `null` is a legitimate, rendered state.
 *
 * Pure functions only — no DOM, no network, no React — so every rule here is
 * unit-testable directly.
 */

import { HUMAN_INPUT_REQUIRED, type NavyaDatasetType, type NavyaForecastRecord } from './types'

/**
 * Whether a selection list can be offered at all.
 *
 * Deliberately not the Phase 8 availability vocabulary (`valid` / `missing` /
 * `unavailable` / `not_applicable` / `stale`). That vocabulary describes a
 * *measurement*; this describes whether a *control* has anything truthful to
 * show. Reusing the measurement words here would imply a station reading was
 * missing rather than that no catalogue exists.
 */
export type NavyaScopeAvailability = 'available' | 'unavailable'

/**
 * One selectable station.
 *
 * `official` is always `false` in this revision. It exists as an explicit field
 * rather than being omitted so that adding an approved registry later is a data
 * change with a visible label, not a silent re-interpretation of existing rows.
 */
export interface NavyaStationOption {
  id: string
  label: string
  /** Provenance of whatever the option was derived from. Drives the caveat. */
  datasetType: NavyaDatasetType
  /** True only for a station from an approved registry. Never true yet. */
  official: boolean
}

/**
 * One selectable river.
 *
 * Structurally identical to `NavyaStationOption`. It is a separate type because
 * the two will not necessarily share a source: a river catalogue, if one is ever
 * approved, may be keyed on catchment rather than on a gauge reference, and
 * conflating them would force a false assumption about that mapping.
 */
export interface NavyaRiverOption {
  id: string
  label: string
  datasetType: NavyaDatasetType
  official: boolean
}

/** Why no station list can be offered. Reuses the platform's own convention. */
export const NO_STATION_REGISTRY_REASON =
  'No station registry exists in this repository. The forecast contract carries a single ' +
  'station reference for one configured gauge, not a list of selectable stations. ' +
  HUMAN_INPUT_REQUIRED

/** Why no river list can be offered. */
export const NO_RIVER_IDENTITY_REASON =
  'The forecast contract carries no river, reach, or catchment field, so there is nothing to ' +
  'select. Naming a river here would mean inventing one. ' + HUMAN_INPUT_REQUIRED

/**
 * Stations derivable from a loaded record.
 *
 * At most one option, and only when the record carries a station reference. An
 * empty array is the normal case and is not an error: it means the record has no
 * station identity, which the provenance panel already reports as
 * "station reference: not recorded".
 *
 * A blank or whitespace-only reference is treated as absent rather than becoming
 * an option whose label is invisible.
 */
export function stationsFromRecord(record: NavyaForecastRecord | null): NavyaStationOption[] {
  if (record === null) return []
  const reference = record.provenance.stationReference
  if (reference === null || reference.trim() === '') return []
  return [
    {
      id: reference,
      label: reference,
      datasetType: record.provenance.datasetType,
      // No approved station registry exists, so nothing here is official.
      official: false,
    },
  ]
}

/**
 * Rivers derivable from a loaded record: always none.
 *
 * The parameter is accepted so this stays drop-in compatible with
 * `stationsFromRecord` and so a future contract field has an obvious home. It is
 * deliberately unused, and that is the point — there is no river field to read.
 */
export function riversFromRecord(_record: NavyaForecastRecord | null): NavyaRiverOption[] {
  return []
}

/** Whether the station control has anything truthful to show. */
export function stationRegistryAvailability(
  record: NavyaForecastRecord | null,
): NavyaScopeAvailability {
  return stationsFromRecord(record).length > 0 ? 'available' : 'unavailable'
}

/**
 * Whether the river control has anything truthful to show. Always unavailable.
 *
 * A function rather than a constant so a caller cannot read "unavailable" as a
 * stale assumption, and so the day a river field lands the answer can change in
 * exactly one place.
 */
export function riverRegistryAvailability(
  _record: NavyaForecastRecord | null,
): NavyaScopeAvailability {
  return 'unavailable'
}

/**
 * How a station selection relates to the record actually on screen.
 *
 * This is the propagation check. `/api/ai/forecast` takes no station
 * parameter — the running contract has nowhere to put one — so selection
 * cannot be pushed into the request. Instead the selection is *reconciled
 * against the record that came back*. A mismatch means the screen would
 * otherwise show one station's forecast under another station's selection,
 * which is the specific bug this status exists to make impossible to ship.
 */
export type NavyaStationScopeStatus =
  | 'unselected'
  | 'matched'
  | 'record_lacks_station'
  | 'mismatch'

export function stationScopeStatus(
  record: NavyaForecastRecord | null,
  selectedStationId: string | null,
): NavyaStationScopeStatus {
  // Nothing chosen, or nothing loaded to check against: no claim is being made.
  if (selectedStationId === null || record === null) return 'unselected'
  const actual = record.provenance.stationReference
  // The record cannot confirm the selection. Not a mismatch — an absence.
  if (actual === null || actual.trim() === '') return 'record_lacks_station'
  return actual === selectedStationId ? 'matched' : 'mismatch'
}

/** How a river selection relates to the record on screen. */
export type NavyaRiverScopeStatus = 'unselected' | 'no_river_identity'

export function riverScopeStatus(
  _record: NavyaForecastRecord | null,
  _selectedRiverId: string | null,
): NavyaRiverScopeStatus {
  return 'no_river_identity'
}

/** Tone for a scope note. `warning` and `critical` are the two that need action. */
export type NavyaScopeTone = 'info' | 'warning' | 'critical'

export interface NavyaScopeNote {
  status: NavyaStationScopeStatus | NavyaRiverScopeStatus
  tone: NavyaScopeTone
  message: string
}

/**
 * The sentence shown under the station control.
 *
 * Returns `null` for `matched` — a correct selection needs no annotation, and
 * an "all good" banner on every load is noise that trains readers to ignore the
 * one that matters. Returns `null` for `unselected` too: no selection is not an
 * error, and the control already shows its own "no station selected" state.
 */
export function describeStationSelection(
  record: NavyaForecastRecord | null,
  selectedStationId: string | null,
): NavyaScopeNote | null {
  const status = stationScopeStatus(record, selectedStationId)
  if (status === 'unselected' || status === 'matched') return null
  if (status === 'record_lacks_station') {
    return {
      status,
      tone: 'warning',
      message:
        'The loaded forecast record carries no station reference, so it cannot be confirmed as ' +
        'belonging to the selected station. It is shown unverified.',
    }
  }
  return {
    status,
    tone: 'critical',
    message:
      `The loaded forecast record is for station "${record?.provenance.stationReference ?? 'unrecorded'}", ` +
      `not the selected "${selectedStationId}". The forecast contract takes no station parameter, ` +
      'so the record cannot be re-requested for a different station. Treat the forecast below as ' +
      'not belonging to the selected station.',
  }
}

/**
 * The sentence shown under the river control.
 *
 * Always a note, because there is always something true to say: no river
 * identity exists in the contract. Returning `null` when nothing is selectable
 * would leave the control looking broken rather than explained.
 */
export function describeRiverSelection(): NavyaScopeNote {
  return { status: 'no_river_identity', tone: 'info', message: NO_RIVER_IDENTITY_REASON }
}
