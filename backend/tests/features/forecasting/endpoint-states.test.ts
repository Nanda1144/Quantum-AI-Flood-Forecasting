/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform. It is honest by construction,
 * per the platform README: no fabricated data, no invented metrics, every surrogate or
 * fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Pure invariants of the forecast endpoint availability states.
 *
 * These are the honesty-critical constants and builders behind the risk and
 * station surfaces. The tests pin the exact required copy (the
 * forecast→station sentence), the Phase 7 decision vocabulary (WITHHELD safe
 * default, emergency states unconfigurable), and the rule that exposure
 * absence is `null` — never `0`, never a fabricated number.
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  AvailabilityCodes,
  RESPONSE_DECISION_UNCONFIGURABLE,
  RESPONSE_DECISION_VOCABULARY,
  SAFE_DEFAULT_RESPONSE_DECISION,
  STATION_MAPPING_UNAVAILABLE_MESSAGE,
  exposureBlock,
  riskAreaState,
  riskMapState,
  stationForecastState,
} from '../../../src/features/forecasting/endpoint-states.ts'
import { HUMAN_INPUT_REQUIRED } from '../../../src/features/forecasting/candidate-risk.ts'

describe('stationForecastState', () => {
  it('carries the required sentence and no forecast data', () => {
    const state = stationForecastState('gauge-01')
    assert.equal(state.status, 'NOT_EVALUABLE')
    assert.equal(state.code, AvailabilityCodes.FORECAST_TO_STATION_MAPPING_UNAVAILABLE)
    assert.equal(state.message, STATION_MAPPING_UNAVAILABLE_MESSAGE)
    assert.equal(state.stationId, 'gauge-01')
    assert.ok(!('forecast_id' in state), 'a station state must never carry forecast data')
    assert.ok(!('flood_probability' in state))
    assert.ok(state.reasons.length >= 3)
  })

  it('explains the schema gap and forbids inference', () => {
    const state = stationForecastState('gauge-01')
    const joined = state.reasons.join(' ')
    assert.match(joined, /no station foreign key/i)
    assert.match(joined, /nearest-station|coordinate inference/i)
    assert.ok(joined.includes(HUMAN_INPUT_REQUIRED))
  })

  it('is structural: every station id produces the same typed state', () => {
    const a = stationForecastState('any-station')
    const b = stationForecastState('any-other-station')
    assert.equal(a.status, b.status)
    assert.equal(a.code, b.code)
    assert.equal(a.message, b.message)
    assert.equal(a.stationId, 'any-station')
    assert.equal(b.stationId, 'any-other-station')
  })
})

describe('riskMapState / riskAreaState', () => {
  it('both are NOT_EVALUABLE with stable codes', () => {
    const map = riskMapState()
    assert.equal(map.status, 'NOT_EVALUABLE')
    assert.equal(map.code, AvailabilityCodes.RISK_MAP_NOT_EVALUABLE)
    const area = riskAreaState('zone-7')
    assert.equal(area.status, 'NOT_EVALUABLE')
    assert.equal(area.code, AvailabilityCodes.AREA_RISK_NOT_EVALUABLE)
    assert.equal(area.areaId, 'zone-7')
  })

  it('explains the missing GIS/exposure/area context', () => {
    const map = riskMapState()
    const joined = map.reasons.join(' ')
    assert.match(joined, /GIS/)
    assert.match(joined, /population-exposure/)
    assert.match(joined, /infrastructure-exposure/)
    assert.ok(joined.includes(HUMAN_INPUT_REQUIRED))
  })
})

describe('exposureBlock', () => {
  it('every reading is NOT_EVALUABLE with value null', () => {
    const block = exposureBlock()
    assert.equal(block.readings.length, 3)
    for (const reading of block.readings) {
      assert.equal(reading.availability, 'NOT_EVALUABLE')
      assert.equal(reading.value, null)
      assert.ok(reading.reason.length > 0)
    }
  })

  it('serialises to JSON with no numeric value anywhere', () => {
    const serialised = JSON.stringify(exposureBlock())
    assert.ok(!/["']value["']\s*:\s*\d/.test(serialised), 'exposure values must never be numbers')
  })
})

describe('Phase 7 response-decision vocabulary', () => {
  it('WITHHELD is the safe default and the only reachable decision', () => {
    assert.equal(SAFE_DEFAULT_RESPONSE_DECISION, 'WITHHELD')
    assert.deepEqual(RESPONSE_DECISION_VOCABULARY, [
      'WITHHELD',
      'MONITOR',
      'HEIGHTENED_MONITORING',
      'REVIEW_WARNING',
    ])
    assert.deepEqual(RESPONSE_DECISION_UNCONFIGURABLE, [
      'EVACUATE',
      'MANDATORY_EVACUATION',
      'EMERGENCY_DECLARED',
    ])
    // The structural guarantee: every allowed decision is in the vocabulary,
    // and no emergency state can be reached from the configured vocabulary.
    assert.ok(!RESPONSE_DECISION_VOCABULARY.some((d) => RESPONSE_DECISION_UNCONFIGURABLE.includes(d)))
  })

  it('the response priority reading is WITHHELD / NOT_EVALUABLE / null', () => {
    const block = exposureBlock()
    assert.equal(block.responsePriority.decision, 'WITHHELD')
    assert.equal(block.responsePriority.availability, 'NOT_EVALUABLE')
    assert.equal(block.responsePriority.value, null)
  })
})
