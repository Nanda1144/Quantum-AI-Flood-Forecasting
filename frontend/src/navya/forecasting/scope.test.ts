/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Tests for the station/river selection scope.
 *
 * The core rule under test: selection is only ever *derived from the loaded
 * record's contract fields*, never invented. A record carries at most one
 * station reference, so `stationsFromRecord` returns at most one option; the
 * river side has no contract field at all, so it is permanently unavailable.
 * The propagation check is tested in all four states so a reader can see which
 * one is reachable on a live screen — a real record, after all, cannot mismatch.
 */

import { describe, expect, it } from 'vitest'
import { realForecastRecord, syntheticForecastRecord } from './fixtures'
import {
  NO_RIVER_IDENTITY_REASON,
  NO_STATION_REGISTRY_REASON,
  describeRiverSelection,
  describeStationSelection,
  riverRegistryAvailability,
  riverScopeStatus,
  riversFromRecord,
  stationRegistryAvailability,
  stationScopeStatus,
  stationsFromRecord,
} from './scope'
import { HUMAN_INPUT_REQUIRED } from './types'

describe('stationsFromRecord', () => {
  it('derives at most one option from the loaded record’s station reference', () => {
    const options = stationsFromRecord(realForecastRecord())
    expect(options).toHaveLength(1)
    expect(options[0].id).toBe('STN-0001')
    expect(options[0].label).toBe('STN-0001')
    expect(options[0].datasetType).toBe('real')
  })

  it('never marks a derived station as official — no approved registry exists', () => {
    expect(stationsFromRecord(realForecastRecord())[0].official).toBe(false)
  })

  it('returns nothing for a record with no station reference', () => {
    expect(stationsFromRecord(syntheticForecastRecord())).toEqual([])
  })

  it('returns nothing for a null record', () => {
    expect(stationsFromRecord(null)).toEqual([])
  })

  it('treats a blank station reference as absent', () => {
    const record = realForecastRecord({
      provenance: { ...realForecastRecord().provenance, stationReference: '   ' },
    })
    expect(stationsFromRecord(record)).toEqual([])
  })
})

describe('riversFromRecord', () => {
  it('is always empty — the contract carries no river identity', () => {
    expect(riversFromRecord(realForecastRecord())).toEqual([])
    expect(riversFromRecord(null)).toEqual([])
  })
})

describe('registry availability', () => {
  it('reports the station control available only when a record-derived option exists', () => {
    expect(stationRegistryAvailability(realForecastRecord())).toBe('available')
    expect(stationRegistryAvailability(syntheticForecastRecord())).toBe('unavailable')
    expect(stationRegistryAvailability(null)).toBe('unavailable')
  })

  it('reports the river control unavailable on every input', () => {
    expect(riverRegistryAvailability(realForecastRecord())).toBe('unavailable')
    expect(riverRegistryAvailability(null)).toBe('unavailable')
  })
})

describe('stationScopeStatus', () => {
  it('is unselected when nothing was chosen', () => {
    expect(stationScopeStatus(realForecastRecord(), null)).toBe('unselected')
  })

  it('is unselected when there is no record to check against', () => {
    expect(stationScopeStatus(null, 'STN-0001')).toBe('unselected')
  })

  it('reports matched when the selection equals the record’s station', () => {
    expect(stationScopeStatus(realForecastRecord(), 'STN-0001')).toBe('matched')
  })

  it('reports a missing station when the record cannot confirm the selection', () => {
    expect(stationScopeStatus(syntheticForecastRecord(), 'STN-0001')).toBe('record_lacks_station')
  })

  it('reports a mismatch when the record belongs to another station', () => {
    expect(stationScopeStatus(realForecastRecord(), 'STN-9999')).toBe('mismatch')
  })
})

describe('riverScopeStatus', () => {
  it('is always no_river_identity', () => {
    expect(riverScopeStatus(realForecastRecord(), null)).toBe('no_river_identity')
    expect(riverScopeStatus(realForecastRecord(), 'any')).toBe('no_river_identity')
  })
})

describe('describeStationSelection', () => {
  it('returns no note for unselected and matched states — no noise for correct states', () => {
    expect(describeStationSelection(realForecastRecord(), null)).toBeNull()
    expect(describeStationSelection(realForecastRecord(), 'STN-0001')).toBeNull()
  })

  it('warns when the record cannot confirm the selection', () => {
    const note = describeStationSelection(syntheticForecastRecord(), 'STN-0001')
    expect(note).not.toBeNull()
    expect(note?.status).toBe('record_lacks_station')
    expect(note?.tone).toBe('warning')
    expect(note?.message).toMatch(/cannot be confirmed/)
  })

  it('is critical and names both stations on a mismatch', () => {
    const record = realForecastRecord({ provenance: { ...realForecastRecord().provenance, stationReference: 'STN-0001' } })
    const note = describeStationSelection(record, 'STN-9999')
    expect(note?.status).toBe('mismatch')
    expect(note?.tone).toBe('critical')
    expect(note?.message).toContain('STN-0001')
    expect(note?.message).toContain('STN-9999')
  })
})

describe('describeRiverSelection', () => {
  it('always states the absent river identity', () => {
    const note = describeRiverSelection()
    expect(note.status).toBe('no_river_identity')
    expect(note.tone).toBe('info')
    expect(note.message).toBe(NO_RIVER_IDENTITY_REASON)
    expect(NO_RIVER_IDENTITY_REASON).toContain(HUMAN_INPUT_REQUIRED)
  })
})

describe('registry reasons', () => {
  it('both unavailability reasons carry the platform convention marker', () => {
    expect(NO_STATION_REGISTRY_REASON).toContain(HUMAN_INPUT_REQUIRED)
    expect(NO_RIVER_IDENTITY_REASON).toContain(HUMAN_INPUT_REQUIRED)
  })

  it('the station reason does not claim a list exists', () => {
    expect(NO_STATION_REGISTRY_REASON.toLowerCase()).toContain('single station reference')
  })
})