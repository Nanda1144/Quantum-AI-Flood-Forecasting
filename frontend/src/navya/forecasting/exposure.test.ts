/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Tests for exposure and response-priority availability.
 *
 * The rule under test is the whole point of the F5 risk additions: statuses may
 * be shown, values may not. Every reading in this revision is `NOT_EVALUABLE`
 * with a reason, and the value slot is always `null` — no population count, no
 * infrastructure inventory, no priority score is ever produced by this module.
 */

import { describe, expect, it } from 'vitest'
import {
  INFRASTRUCTURE_EXPOSURE_REASON,
  POPULATION_EXPOSURE_REASON,
  RESPONSE_PRIORITY_REASON,
  describeExposureReading,
  exposureReadings,
  infrastructureExposure,
  populationExposure,
  responsePriority,
} from './exposure'
import { realForecastRecord, syntheticForecastRecord } from './fixtures'
import { HUMAN_INPUT_REQUIRED } from './types'

/**
 * A number attached to an exposure quantity would be an invented exposure
 * figure. The reasons may legitimately say "Phase 8", so this checks for numbers
 * *next to a quantity word*, not for digits in general.
 */
const EXPOSURE_QUANTITY = /(\d+(?:\.\d+)?)\s*(people|population|affected|resident|building|road|hospital|structure|percent|%)\b/i

describe('populationExposure', () => {
  it('is NOT_EVALUABLE with no value, for a real record', () => {
    const reading = populationExposure(realForecastRecord())
    expect(reading.availability).toBe('NOT_EVALUABLE')
    expect(reading.value).toBeNull()
    expect(reading.reason).toBe(POPULATION_EXPOSURE_REASON)
  })

  it('is NOT_EVALUABLE with no value, for a synthetic record', () => {
    const reading = populationExposure(syntheticForecastRecord())
    expect(reading.availability).toBe('NOT_EVALUABLE')
    expect(reading.value).toBeNull()
  })

  it('carries the platform convention marker and no invented exposure quantity', () => {
    expect(POPULATION_EXPOSURE_REASON).toContain(HUMAN_INPUT_REQUIRED)
    expect(POPULATION_EXPOSURE_REASON).not.toMatch(EXPOSURE_QUANTITY)
  })
})

describe('infrastructureExposure', () => {
  it('is NOT_EVALUABLE with no value', () => {
    const reading = infrastructureExposure(realForecastRecord())
    expect(reading.availability).toBe('NOT_EVALUABLE')
    expect(reading.value).toBeNull()
    expect(reading.reason).toBe(INFRASTRUCTURE_EXPOSURE_REASON)
  })

  it('contains no invented infrastructure quantity', () => {
    expect(INFRASTRUCTURE_EXPOSURE_REASON).not.toMatch(EXPOSURE_QUANTITY)
  })
})

describe('responsePriority', () => {
  it('is NOT_EVALUABLE with no value', () => {
    const reading = responsePriority(realForecastRecord())
    expect(reading.availability).toBe('NOT_EVALUABLE')
    expect(reading.value).toBeNull()
    expect(reading.reason).toBe(RESPONSE_PRIORITY_REASON)
  })

  it('contains no invented priority value', () => {
    expect(RESPONSE_PRIORITY_REASON).not.toMatch(EXPOSURE_QUANTITY)
  })
})

describe('exposureReadings', () => {
  it('returns the three readings in display order', () => {
    const readings = exposureReadings(realForecastRecord())
    expect(readings.map((r) => r.kind)).toEqual([
      'population_exposure',
      'infrastructure_exposure',
      'response_priority',
    ])
    for (const reading of readings) {
      expect(reading.availability).toBe('NOT_EVALUABLE')
      expect(reading.value).toBeNull()
    }
  })
})

describe('describeExposureReading', () => {
  it('states the status and the reason and never an invented quantity', () => {
    const sentence = describeExposureReading(populationExposure(realForecastRecord()))
    expect(sentence).toContain('NOT_EVALUABLE')
    expect(sentence).toContain(POPULATION_EXPOSURE_REASON)
    expect(sentence).not.toMatch(EXPOSURE_QUANTITY)
  })
})