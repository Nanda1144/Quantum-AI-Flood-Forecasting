/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Tests for candidate-level flood-risk attribution.
 *
 * The whole point of this module is that it refuses to guess. Almost every test
 * below therefore asserts an **absence**: a `null`, a `true` synthetic flag, a
 * blocker list. If a future change makes these pass a number, that is a
 * regression, and the test name says so.
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  HUMAN_INPUT_REQUIRED,
  MAPPING_BLOCKERS,
  buildCandidateRiskMapping,
  describeMappingLimitations,
  forecastLevelRisk,
  validateCandidateRiskMapping,
  withDerivedRisk,
} from '../../../src/features/forecasting/candidate-risk.ts'
import type { CandidateRiskMappingSpec } from '../../../src/features/forecasting/types.ts'
import { unrecordedRecord } from './helpers/fixtures.ts'

const CANDIDATES = ['cand-a', 'cand-b', 'cand-c'] as const

describe('HUMAN_INPUT_REQUIRED', () => {
  it('uses the platform convention verbatim', () => {
    assert.equal(HUMAN_INPUT_REQUIRED, 'NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED')
  })
})

describe('MAPPING_BLOCKERS', () => {
  it('is a non-empty list, so the unavailability has a stated cause', () => {
    assert.ok(MAPPING_BLOCKERS.length >= 4)
    for (const blocker of MAPPING_BLOCKERS) {
      assert.equal(typeof blocker, 'string')
      assert.ok(blocker.trim().length > 0)
    }
  })

  it('names the station register and the missing candidate join key', () => {
    const text = MAPPING_BLOCKERS.join(' ')
    assert.match(text, /station/i)
    assert.match(text, /no station key/i)
  })

  it('records that the floodRisk the QUBO builder consumes has unestablished provenance', () => {
    const text = MAPPING_BLOCKERS.join(' ')
    assert.match(text, /CandidateLocation\.floodRisk/)
    assert.match(text, /provenance/i)
  })
})

describe('buildCandidateRiskMapping', () => {
  it('marks the spec synthetic and un-attributed for every candidate', () => {
    const spec = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES)
    assert.equal(spec.synthetic, true)
    assert.equal(spec.attributions.length, 3)
    for (const attribution of spec.attributions) {
      assert.equal(attribution.isSynthetic, true)
    }
  })

  /**
   * The central honesty assertion for this module: never a number.
   *
   * Not `0` (which asserts no flood risk) and not `forecastRiskScore` (which
   * would assume every site shares the station stage).
   */
  it('leaves derivedFloodRisk null — not zero, not the station risk', () => {
    const spec = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES)
    for (const attribution of spec.attributions) {
      assert.equal(attribution.derivedFloodRisk, null)
    }
  })

  it('returns one attribution per requested candidate, in order', () => {
    const spec = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES)
    assert.deepEqual(
      spec.attributions.map((a) => a.candidateLocationId),
      [...CANDIDATES],
    )
  })

  it('handles an empty candidate list without fabricating an entry', () => {
    const spec = buildCandidateRiskMapping(unrecordedRecord(), [])
    assert.deepEqual(spec.attributions, [])
    assert.equal(spec.synthetic, true)
  })

  it('cites the blocker on every attribution, not just on the spec', () => {
    const spec = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES)
    for (const attribution of spec.attributions) {
      // The convention string belongs on mappingProvenance, which is the field a
      // consumer reads as "where did this number come from".
      assert.ok(attribution.mappingProvenance.includes(HUMAN_INPUT_REQUIRED))
      // The notes carry the reasons, so every blocker must appear there too.
      for (const blocker of MAPPING_BLOCKERS) {
        assert.ok(attribution.notes.includes(blocker), `blocker missing: ${blocker}`)
      }
    }
  })

  it('states the source of the unavailability on the spec', () => {
    const spec = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES)
    assert.ok(spec.source.includes(HUMAN_INPUT_REQUIRED))
  })

  it('explains why neither zero nor the station risk is acceptable', () => {
    const notes = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES).attributions[0].notes
    const text = notes.join(' ')
    assert.match(text, /zero would assert no flood risk/i)
    assert.match(text, /station stage/i)
  })

  it('passes its own validator', () => {
    validateCandidateRiskMapping(buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES))
  })
})

describe('withDerivedRisk', () => {
  const base = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES).attributions[0]

  it('refuses a derivation that cites no provenance', () => {
    // The team-owned side cannot be modified to enforce this, so the check is here.
    assert.throws(
      () => withDerivedRisk(base, 0.7, null),
      /must cite its mapping provenance/,
    )
    assert.throws(() => withDerivedRisk(base, 0.7, '   '), /must cite its mapping provenance/)
  })

  it('attaches a derived risk and clears the synthetic flag', () => {
    const attribution = withDerivedRisk(
      base,
      0.7,
      'Hypothetical reach-weighted attribution supplied by the test.',
    )
    assert.equal(attribution.derivedFloodRisk, 0.7)
    assert.equal(attribution.isSynthetic, false)
  })

  it('keeps the synthetic flag when the derived risk is still null', () => {
    // A provenance note is not a derivation. Crediting a candidate with a
    // citation but no risk must not make it look resolved.
    const attribution = withDerivedRisk(
      base,
      null,
      'Noted, but the value itself is unavailable.',
      ['still blocked'],
    )
    assert.equal(attribution.derivedFloodRisk, null)
    assert.equal(attribution.isSynthetic, true)
    assert.ok(attribution.notes.includes('still blocked'))
  })

  it('normalises an out-of-range derivation instead of rejecting it', () => {
    assert.equal(withDerivedRisk(base, 3, 'test').derivedFloodRisk, 1)
    assert.equal(withDerivedRisk(base, -3, 'test').derivedFloodRisk, 0)
  })

  it('appends notes rather than replacing the existing ones', () => {
    const attribution = withDerivedRisk(base, 0.5, 'test provenance', ['extra'])
    assert.equal(attribution.notes.length, base.notes.length + 1)
    assert.equal(attribution.notes.at(-1), 'extra')
  })

  it('does not mutate the input attribution', () => {
    const before = JSON.stringify(base)
    withDerivedRisk(base, 0.9, 'test provenance', ['appended'])
    assert.equal(JSON.stringify(base), before)
  })
})

describe('validateCandidateRiskMapping', () => {
  const forecastId = unrecordedRecord().forecastId

  function specWith(overrides: Partial<CandidateRiskMappingSpec>): CandidateRiskMappingSpec {
    const base = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES)
    return { ...base, ...overrides }
  }

  it('accepts the honest un-attributed spec', () => {
    validateCandidateRiskMapping(buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES))
  })

  it('rejects an attribution borrowed from a different forecast', () => {
    const base = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES)
    base.attributions[1].forecastId = 'FC-20240102-0600'
    assert.throws(() => validateCandidateRiskMapping(base), /references forecast/)
  })

  it('rejects a null risk that is not marked synthetic', () => {
    // The one way a mapping silently becomes a fabrication.
    const base = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES)
    base.attributions[0].isSynthetic = false
    assert.throws(() => validateCandidateRiskMapping(base), /no derived flood risk/)
  })

  it('rejects a real-marked attribution that cites no provenance', () => {
    const derived = withDerivedRisk(
      buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES).attributions[0],
      0.6,
      'cited',
    )
    derived.mappingProvenance = '   '
    const base = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES)
    base.attributions[0] = derived
    assert.throws(() => validateCandidateRiskMapping(base), /cites no mapping provenance/)
  })

  it('rejects a spec claiming to be real while any candidate is un-derived', () => {
    const base = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES)
    base.synthetic = false
    assert.throws(() => validateCandidateRiskMapping(base), /claims to be real but 3 candidate/)
  })

  it('rejects a real spec with zero candidates, which asserts nothing at all', () => {
    // Defensive: a vacuous "all candidates mapped" claim over an empty set is
    // the same fabrication as one over an un-derived set.
    validateCandidateRiskMapping(specWith({ synthetic: false, attributions: [] }))
    const base = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES)
    base.synthetic = false
    assert.throws(() => validateCandidateRiskMapping(base), /claims to be real/)
  })

  it('accepts a fully derived real spec', () => {
    const attributions = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES).attributions.map(
      (a) => withDerivedRisk(a, 0.4, 'Hypothetical reach-weighted attribution (test shape).'),
    )
    const spec = specWith({ synthetic: false, attributions })
    spec.forecastId = forecastId
    validateCandidateRiskMapping(spec)
  })
})

describe('forecastLevelRisk', () => {
  it('returns the forecast-wide score and nothing finer-grained', () => {
    assert.equal(forecastLevelRisk(unrecordedRecord({ riskScore: 0.62 })), 0.62)
  })

  it('is explicitly coarse: it cannot be mistaken for a per-site value', () => {
    // Same number for every candidate, by construction. Documented as a reach
    // statement, not a site statement.
    const spec = buildCandidateRiskMapping(unrecordedRecord(), CANDIDATES)
    const scores = new Set(spec.attributions.map((a) => a.forecastRiskScore))
    assert.equal(scores.size, 1)
    for (const attribution of spec.attributions) {
      assert.equal(attribution.forecastRiskScore, 0.62)
    }
  })
})

describe('describeMappingLimitations', () => {
  it('states unavailability, every blocker, and the resulting null risk', () => {
    const text = describeMappingLimitations()
    assert.match(text, /NOT AVAILABLE/)
    for (const blocker of MAPPING_BLOCKERS) {
      assert.ok(text.includes(blocker), `blocker missing from the summary: ${blocker}`)
    }
    assert.match(text, /derivedFloodRisk = null/)
    assert.ok(text.includes(HUMAN_INPUT_REQUIRED))
  })
})
