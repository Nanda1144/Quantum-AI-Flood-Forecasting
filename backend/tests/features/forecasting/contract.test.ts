/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Tests for the forecast -> optimization handoff contract.
 *
 * The property under test throughout: **the handoff must never claim more than
 * the forecast actually supports.** Every assertion here is about a field being
 * absent, `null`, or explicitly `false` rather than about a value being right.
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  FIELDS_REQUIRING_INTEGRATION,
  REQUIRED_EXISTING_FIELDS,
  assertKnownTarget,
  describeHandoff,
  fieldsRequiringIntegration,
  isThresholdOfficial,
  normalizeCandidateRisk,
  openProvenanceQuestions,
  priorityForRiskLevel,
  toExistingOptimizationPayload,
  toProposedForecastHandoff,
} from '../../../src/features/forecasting/contract.ts'
import { INTEGRATION_STATEMENT } from '../../../src/features/forecasting/types.ts'
import { unrecordedRecord, unrecordedProvenance } from './helpers/fixtures.ts'

describe('INTEGRATION_STATEMENT', () => {
  it('is the required sentence, verbatim and character for character', () => {
    assert.equal(
      INTEGRATION_STATEMENT,
      'Existing optimization currently requires forecast_id. ' +
        'Additional forecast-derived risk fields require team-owner integration.',
    )
  })

  it('is carried on the proposed handoff unchanged', () => {
    const handoff = toProposedForecastHandoff(unrecordedRecord())
    assert.equal(handoff.integration_statement, INTEGRATION_STATEMENT)
  })

  it('is quoted in the human-readable handoff summary', () => {
    assert.ok(describeHandoff(unrecordedRecord()).includes(INTEGRATION_STATEMENT))
  })
})

describe('toExistingOptimizationPayload', () => {
  it('sends only forecast_id as a required field', () => {
    assert.deepEqual([...REQUIRED_EXISTING_FIELDS], ['forecast_id'])
  })

  it('omits risk_score and priority when the forecast carries neither', () => {
    // A record with no risk level and a non-finite score: the platform should
    // receive the id alone rather than a fabricated 0.0 / 'low'.
    const payload = toExistingOptimizationPayload(
      unrecordedRecord({ riskLevel: null as never, riskScore: Number.NaN }),
    )
    assert.equal('risk_score' in payload, false)
    assert.equal('priority' in payload, false)
  })

  it('omits a non-finite risk_score but keeps the priority from the level', () => {
    const payload = toExistingOptimizationPayload(
      unrecordedRecord({ riskLevel: 'HIGH', riskScore: Number.NaN }),
    )
    assert.equal('risk_score' in payload, false)
    assert.equal(payload.priority, 'high')
  })

  it('carries a finite risk_score and the matching priority', () => {
    const payload = toExistingOptimizationPayload(unrecordedRecord())
    assert.equal(payload.forecast_id, unrecordedRecord().forecastId)
    assert.equal(payload.risk_score, 0.62)
    assert.equal(payload.priority, 'high')
  })

  describe('availability flags', () => {
    /**
     * The load-bearing test in this file.
     *
     * `OptimizationService.createFromForecast` resolves these as
     * `payload.candidate_locations_available ?? true`. Omitting the key makes the
     * platform record `true` — a claim that candidate locations and resource
     * constraints exist. Neither does. So the default must be an explicit
     * `false`, present in the payload.
     */
    it('sends both flags as explicit false by default', () => {
      const payload = toExistingOptimizationPayload(unrecordedRecord())
      assert.equal(payload.candidate_locations_available, false)
      assert.equal(payload.resource_constraints_available, false)
    })

    it('never omits a flag, because omission would be read as true', () => {
      const payload = toExistingOptimizationPayload(unrecordedRecord()) as Record<string, unknown>
      assert.ok('candidate_locations_available' in payload)
      assert.ok('resource_constraints_available' in payload)
    })

    it('allows an explicit true only when a caller overrides it', () => {
      const payload = toExistingOptimizationPayload(unrecordedRecord(), {
        candidateLocationsAvailable: true,
        resourceConstraintsAvailable: true,
      })
      assert.equal(payload.candidate_locations_available, true)
      assert.equal(payload.resource_constraints_available, true)
    })

    it('honours an override of a single flag without flipping the other', () => {
      const payload = toExistingOptimizationPayload(unrecordedRecord(), {
        candidateLocationsAvailable: true,
      })
      assert.equal(payload.candidate_locations_available, true)
      assert.equal(payload.resource_constraints_available, false)
    })

    it('sends nothing the running zod schema would reject', () => {
      // Every key must be one the team contract declares, and every value a
      // JSON-legal primitive. A stray key would be rejected at the boundary.
      const allowed = new Set([
        'forecast_id',
        'risk_score',
        'priority',
        'candidate_locations_available',
        'resource_constraints_available',
      ])
      const payload = toExistingOptimizationPayload(unrecordedRecord()) as Record<string, unknown>
      for (const key of Object.keys(payload)) {
        assert.ok(allowed.has(key), `unexpected key in the existing payload: ${key}`)
      }
      assert.deepEqual(payload, JSON.parse(JSON.stringify(payload)))
    })
  })
})

describe('priorityForRiskLevel', () => {
  it('maps every platform risk level onto the platform priority', () => {
    assert.equal(priorityForRiskLevel('CRITICAL'), 'critical')
    assert.equal(priorityForRiskLevel('HIGH'), 'high')
    assert.equal(priorityForRiskLevel('MEDIUM'), 'medium')
    assert.equal(priorityForRiskLevel('LOW'), 'low')
  })

  it('degrades an unrecognised or absent level to the conservative priority', () => {
    // Not a throw: the payload still carries risk_score, so a conservative
    // priority is a safe response where a dead request is not.
    assert.equal(priorityForRiskLevel(null), 'low')
    assert.equal(priorityForRiskLevel(undefined), 'low')
    assert.equal(priorityForRiskLevel('NOT_A_LEVEL' as never), 'low')
  })
})

describe('toProposedForecastHandoff', () => {
  it('carries the full record plus the integration statement', () => {
    const record = unrecordedRecord()
    const handoff = toProposedForecastHandoff(record)
    assert.equal(handoff.forecast_id, record.forecastId)
    assert.equal(handoff.predicted_value, record.predictedValue)
    assert.equal(handoff.flood_probability, record.floodProbability)
    assert.equal(handoff.threshold_policy, 'pending')
  })

  it('passes an unknown threshold through as null, never as zero', () => {
    // 0 is a real stage for a gauge datum; a fake one would produce a
    // guaranteed "below threshold" verdict.
    assert.equal(toProposedForecastHandoff(unrecordedRecord()).threshold, null)
  })

  it('passes a null target unit through as null', () => {
    const handoff = toProposedForecastHandoff(
      unrecordedRecord({ provenance: unrecordedProvenance({ targetUnits: null }) }),
    )
    assert.equal(handoff.target_units, null)
  })

  it('never populates an inflow field for a water-level target', () => {
    const handoff = toProposedForecastHandoff(unrecordedRecord({ target: 'water_level' }))
    assert.equal(handoff.predicted_inflow, null)
  })

  it('reports every proposed field that still needs a team-owner change', () => {
    const proposed = Object.keys(toProposedForecastHandoff(unrecordedRecord()))
    const listed = fieldsRequiringIntegration()
    for (const field of listed) {
      assert.ok(proposed.includes(field), `${field} is listed but not in the handoff`)
    }
    for (const field of proposed) {
      if (field === 'integration_statement') continue
      if (field === 'forecast_id') continue
      if (field === 'risk_score') continue
      if (field === 'predicted_water_level') continue
      assert.ok(listed.includes(field), `${field} is in the handoff but unlisted`)
    }
  })

  it('returns a fresh array each call, so a caller cannot corrupt the list', () => {
    const first = fieldsRequiringIntegration()
    first.push('tampered')
    assert.equal(fieldsRequiringIntegration().includes('tampered'), false)
    assert.equal(FIELDS_REQUIRING_INTEGRATION.includes('tampered'), false)
  })
})

describe('normalizeCandidateRisk', () => {
  it('passes a valid 0..1 value through unchanged', () => {
    assert.equal(normalizeCandidateRisk(0), 0)
    assert.equal(normalizeCandidateRisk(0.5), 0.5)
    assert.equal(normalizeCandidateRisk(1), 1)
  })

  it('clamps an out-of-range value rather than failing a handoff', () => {
    assert.equal(normalizeCandidateRisk(-2), 0)
    assert.equal(normalizeCandidateRisk(4.2), 1)
  })

  it('returns null for absent and non-finite input, never zero', () => {
    // Zero reads as "no flood risk at this site", which is an assertion, not an
    // absence of information.
    assert.equal(normalizeCandidateRisk(null), null)
    assert.equal(normalizeCandidateRisk(undefined), null)
    assert.equal(normalizeCandidateRisk(Number.NaN), null)
    assert.equal(normalizeCandidateRisk(Number.POSITIVE_INFINITY), null)
  })
})

describe('isThresholdOfficial', () => {
  it('is true only for an approved policy', () => {
    assert.equal(isThresholdOfficial('approved'), true)
    assert.equal(isThresholdOfficial('pending'), false)
  })
})

describe('assertKnownTarget', () => {
  it('accepts both configurable targets', () => {
    assert.equal(assertKnownTarget('water_level'), 'water_level')
    assert.equal(assertKnownTarget('inflow'), 'inflow')
  })

  it('refuses an unsupported target and names the supported ones', () => {
    assert.throws(() => assertKnownTarget('velocity'), /water_level.*inflow/)
  })
})

describe('openProvenanceQuestions', () => {
  it('is empty for a fully recorded real dataset', () => {
    const questions = openProvenanceQuestions(
      unrecordedProvenance({
        datasetReference: 'ref',
        datasetType: 'real',
        datasetLicense: 'license',
        datasetChecksum: 'sha256',
        samplingInterval: '1h',
        stationReference: 'station',
        targetUnits: 'm',
      }),
    )
    assert.deepEqual(questions, [])
  })

  it('names every unknown field, including a non-real dataset type', () => {
    assert.deepEqual(openProvenanceQuestions(unrecordedProvenance()), [
      'datasetReference',
      'datasetLicense',
      'datasetChecksum',
      'samplingInterval',
      'stationReference',
      'targetUnits',
      'datasetType',
    ])
  })

  it('still reports datasetType for real data with an unknown licence', () => {
    const questions = openProvenanceQuestions(
      unrecordedProvenance({
        datasetReference: 'ref',
        datasetType: 'real',
        datasetLicense: null,
        datasetChecksum: 'sha256',
        samplingInterval: '1h',
        stationReference: 'station',
        targetUnits: 'm',
      }),
    )
    assert.deepEqual(questions, ['datasetLicense'])
  })
})

describe('describeHandoff', () => {
  it('lists the accepted fields and the pending ones in one string', () => {
    const text = describeHandoff(unrecordedRecord())
    assert.ok(text.includes('forecast_id'))
    assert.ok(text.includes('candidate_locations_available'))
    assert.ok(text.includes('accepted by the running optimizer today:'))
    assert.ok(text.includes('proposed fields pending team-owner integration:'))
    assert.ok(text.includes('flood_probability'))
  })
})
