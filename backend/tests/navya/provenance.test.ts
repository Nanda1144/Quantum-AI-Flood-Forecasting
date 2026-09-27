/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Tests for the provenance guards.
 *
 * The hazard these guards exist for: a synthetic or unlabelled forecast is
 * cached, replayed and displayed weeks later by code that has no idea where it
 * came from. By then the disclaimer is gone and the number reads as real.
 *
 * So the assertions are mostly about `null` vs. a label. A guard that returned
 * `null` too eagerly would be the more dangerous bug, which is why
 * `realRecord()` — the counterfactual that *should* pass — is exercised too.
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  areMetricsPresentableAsResult,
  assertForecastMayBeStored,
  assertMetricsMayBeReported,
  describeThreshold,
  isPresentableAsRealResult,
  mandatoryForecastLabel,
  mandatoryMetricLabel,
  openQuestions,
  summariseProvenance,
  thresholdIsOfficial,
} from '../../src/navya/forecasting/provenance.ts'
import {
  SYNTHETIC_DATA_DISCLAIMER,
  SYNTHETIC_METRIC_LABEL,
} from '../../src/navya/forecasting/types.ts'
import {
  heldOutProvenance,
  placeholderMetrics,
  realRecord,
  unrecordedRecord,
  unrecordedProvenance,
} from './helpers/fixtures.ts'

/** A synthetic record carrying the label it is required to carry. */
function syntheticRecord() {
  return unrecordedRecord({
    provenance: unrecordedProvenance({
      datasetType: 'synthetic',
      disclaimer: SYNTHETIC_DATA_DISCLAIMER,
    }),
  })
}

describe('SYNTHETIC_DATA_DISCLAIMER', () => {
  it('is the exact required warning', () => {
    assert.equal(
      SYNTHETIC_DATA_DISCLAIMER,
      'THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION DATA.',
    )
  })
})

describe('SYNTHETIC_METRIC_LABEL', () => {
  it('marks a score as synthetic/demo evaluation only', () => {
    assert.equal(SYNTHETIC_METRIC_LABEL, 'synthetic/demo evaluation only')
  })
})

describe('isPresentableAsRealResult', () => {
  it('is true only for real data carrying no disclaimer', () => {
    assert.equal(isPresentableAsRealResult(realRecord()), true)
  })

  it('is false for synthetic, unknown, and a contradictory real+disclaimer record', () => {
    assert.equal(isPresentableAsRealResult(syntheticRecord()), false)
    assert.equal(isPresentableAsRealResult(unrecordedRecord()), false)
    // 'real' with a disclaimer is self-contradictory; refuse to present it.
    assert.equal(
      isPresentableAsRealResult(
        unrecordedRecord({
          provenance: unrecordedProvenance({ datasetType: 'real', disclaimer: 'demo' }),
        }),
      ),
      false,
    )
  })
})

describe('mandatoryForecastLabel', () => {
  it('returns null only for a genuinely presentable forecast', () => {
    assert.equal(mandatoryForecastLabel(realRecord()), null)
  })

  it('is never null for any unverified record — absence of a label is never absence of a caveat', () => {
    const cases = [
      unrecordedRecord(),
      syntheticRecord(),
      unrecordedRecord({
        provenance: unrecordedProvenance({
          datasetType: 'real',
          disclaimer: 'source pending',
        }),
      }),
    ]
    for (const record of cases) {
      const label = mandatoryForecastLabel(record)
      assert.notEqual(label, null, `no label for datasetType=${record.provenance.datasetType}`)
      assert.ok((label as string).length > 0)
    }
  })

  it('uses the exact synthetic disclaimer for synthetic data', () => {
    assert.equal(mandatoryForecastLabel(syntheticRecord()), SYNTHETIC_DATA_DISCLAIMER)
  })

  it('distinguishes unverified provenance from synthetic data', () => {
    // "Unknown" is not an accusation of fakery. The data may well be genuine but
    // undocumented, and calling it synthetic would be its own kind of lie.
    const label = mandatoryForecastLabel(unrecordedRecord()) as string
    assert.notEqual(label, SYNTHETIC_DATA_DISCLAIMER)
    assert.match(label, /UNVERIFIED PROVENANCE/)
  })

  it("surfaces a real record's own disclaimer rather than inventing one", () => {
    const label = mandatoryForecastLabel(
      unrecordedRecord({
        provenance: unrecordedProvenance({ datasetType: 'real', disclaimer: 'source pending' }),
      }),
    )
    assert.equal(label, 'source pending')
  })
})

describe('areMetricsPresentableAsResult', () => {
  it('is presentable for a held-out score on real data', () => {
    const { presentable, reasons } = areMetricsPresentableAsResult(realRecord())
    assert.equal(presentable, true)
    assert.deepEqual(reasons, [])
  })

  it('refuses a validation score, and says why', () => {
    const { presentable, reasons } = areMetricsPresentableAsResult(
      realRecord({ metricProvenance: heldOutProvenance({ split: 'validation' }) }),
    )
    assert.equal(presentable, false)
    assert.match(reasons.join(' '), /optimistic by construction/)
  })

  /**
   * Regression guard for a real hole.
   *
   * The guard used to trust `isSelectionStatistic` alone, so a record claiming
   * `{ split: 'validation', isSelectionStatistic: false }` was reported as a
   * held-out result. The split is the fact that matters; the flag is a summary of
   * it and cannot be used to overrule it.
   */
  it('refuses a self-contradictory record that denies being a selection statistic', () => {
    const { presentable } = areMetricsPresentableAsResult(
      realRecord({
        metricProvenance: { split: 'validation', isSelectionStatistic: false },
      }),
    )
    assert.equal(presentable, false)
  })

  /**
   * The same hole, worse: a *training* score is not the selection statistic, so
   * it cleared the old guard entirely and would have been shown as the model's
   * performance. It is a fit statistic.
   */
  it('refuses a training score, which is a fit statistic rather than an estimate', () => {
    const { presentable, reasons } = areMetricsPresentableAsResult(
      realRecord({
        metricProvenance: { split: 'train', isSelectionStatistic: false },
      }),
    )
    assert.equal(presentable, false)
    assert.match(reasons.join(' '), /fit statistic/)
  })

  it('refuses a record explicitly flagged as a selection statistic on any split', () => {
    const { presentable, reasons } = areMetricsPresentableAsResult(
      realRecord({
        metricProvenance: { split: 'test', isSelectionStatistic: true },
      }),
    )
    assert.equal(presentable, false)
    assert.match(reasons.join(' '), /selection statistic/)
  })

  it('reports both reasons when a validation score is also flagged as selected on', () => {
    const { reasons } = areMetricsPresentableAsResult(
      realRecord({
        metricProvenance: { split: 'validation', isSelectionStatistic: true },
      }),
    )
    assert.equal(reasons.length, 2)
  })

  it('refuses a score with no recorded split', () => {
    const { presentable, reasons } = areMetricsPresentableAsResult(
      realRecord({ metricProvenance: null }),
    )
    assert.equal(presentable, false)
    assert.match(reasons.join(' '), /split is unknown/)
  })

  it('refuses a record carrying no metrics at all', () => {
    const { presentable, reasons } = areMetricsPresentableAsResult(realRecord({ metrics: null }))
    assert.equal(presentable, false)
    assert.match(reasons.join(' '), /no metrics/)
  })

  it('refuses a score computed on synthetic data even when held out', () => {
    const { presentable, reasons } = areMetricsPresentableAsResult(
      syntheticRecord({ metrics: placeholderMetrics(), metricProvenance: heldOutProvenance() }),
    )
    assert.equal(presentable, false)
    assert.match(reasons.join(' '), /not 'real'/)
  })

  it('reports every independent reason, not just the first', () => {
    const { reasons } = areMetricsPresentableAsResult(
      unrecordedRecord({ metrics: null, metricProvenance: null }),
    )
    assert.equal(reasons.length, 3)
  })
})

describe('mandatoryMetricLabel', () => {
  it('returns null only when the metrics are genuinely presentable', () => {
    assert.equal(mandatoryMetricLabel(realRecord()), null)
  })

  it('labels a synthetic score as synthetic/demo evaluation only', () => {
    assert.equal(
      mandatoryMetricLabel(
        syntheticRecord({ metrics: placeholderMetrics(), metricProvenance: heldOutProvenance() }),
      ),
      SYNTHETIC_METRIC_LABEL,
    )
  })

  it('explains a non-synthetic but non-presentable score rather than labelling it synthetic', () => {
    const label = mandatoryMetricLabel(
      realRecord({ metricProvenance: heldOutProvenance({ split: 'validation' }) }),
    ) as string
    assert.notEqual(label, SYNTHETIC_METRIC_LABEL)
    assert.match(label, /NOT A HELD-OUT RESULT/)
    assert.match(label, /optimistic by construction/)
  })

  it('is never null when the dataset is unverified', () => {
    assert.notEqual(mandatoryMetricLabel(unrecordedRecord()), null)
  })
})

describe('assertForecastMayBeStored', () => {
  it('accepts a synthetic forecast that carries its disclaimer', () => {
    assertForecastMayBeStored(syntheticRecord())
  })

  it('refuses a synthetic forecast stripped of its disclaimer', () => {
    // The cached-synthetic-outlives-the-session hazard, in one assertion.
    assert.throws(
      () => assertForecastMayBeStored(unrecordedRecord({ provenance: unrecordedProvenance({ datasetType: 'synthetic', disclaimer: null }) })),
      /Refusing to store a synthetic forecast without its disclaimer/,
    )
  })

  it('accepts an unknown-provenance forecast, which is a different situation', () => {
    // Not a fabrication guard: unknown data may be real. It still cannot be
    // *presented* as real, which mandatoryForecastLabel handles.
    assertForecastMayBeStored(unrecordedRecord())
  })

  it('accepts a fully presentable record', () => {
    assertForecastMayBeStored(realRecord())
  })
})

describe('assertMetricsMayBeReported', () => {
  it('accepts a held-out score on real data', () => {
    assertMetricsMayBeReported(realRecord())
  })

  it('refuses a selection statistic', () => {
    assert.throws(
      () => assertMetricsMayBeReported(realRecord({ metricProvenance: heldOutProvenance({ split: 'validation' }) })),
      /Refusing to report these metrics as a result/,
    )
  })

  it('refuses a training score', () => {
    assert.throws(
      () => assertMetricsMayBeReported(realRecord({ metricProvenance: { split: 'train', isSelectionStatistic: false } })),
      /fit statistic/,
    )
  })

  it('refuses a score on synthetic data', () => {
    assert.throws(
      () =>
        assertMetricsMayBeReported(
          syntheticRecord({ metrics: placeholderMetrics(), metricProvenance: heldOutProvenance() }),
        ),
      /Refusing to report these metrics as a result/,
    )
  })
})

describe('openQuestions', () => {
  it('merges computed gaps with declared ones, de-duplicated and sorted', () => {
    const questions = openQuestions(
      unrecordedRecord({
        provenance: unrecordedProvenance({ missingFields: ['datasetLicense', 'extraThing'] }),
      }),
    )
    assert.equal(questions.filter((q) => q === 'datasetLicense').length, 1)
    assert.ok(questions.includes('extraThing'))
    assert.ok(questions.includes('datasetType'))
    assert.deepEqual(questions, [...questions].sort())
  })

  it('is empty for a complete real record', () => {
    assert.deepEqual(openQuestions(realRecord()), [])
  })
})

describe('thresholdIsOfficial', () => {
  it('is true only for an approved policy', () => {
    assert.equal(thresholdIsOfficial(unrecordedRecord({ thresholdPolicy: 'approved' })), true)
    assert.equal(thresholdIsOfficial(unrecordedRecord({ thresholdPolicy: 'pending' })), false)
  })
})

describe('describeThreshold', () => {
  it('never renders a bare number for an unapproved threshold', () => {
    const text = describeThreshold(
      unrecordedRecord({ threshold: 5, thresholdPolicy: 'pending', thresholdSource: 'DEMO' }),
    )
    assert.match(text, /PENDING approval, NOT an official flood stage/)
    assert.match(text, /DEMO/)
  })

  it('says so explicitly when no threshold is configured', () => {
    const text = describeThreshold(unrecordedRecord({ threshold: null }))
    assert.match(text, /No flood threshold is configured/)
    assert.ok(!text.includes('undefined'))
  })

  it('names unknown units rather than dropping them', () => {
    const text = describeThreshold(
      unrecordedRecord({ threshold: 5, thresholdPolicy: 'approved', targetUnits: null }),
    )
    assert.match(text, /units unknown/)
  })

  it('records when the source of an unapproved threshold is unknown', () => {
    const text = describeThreshold(
      unrecordedRecord({ threshold: 5, thresholdPolicy: 'pending', thresholdSource: null }),
    )
    assert.match(text, /source not recorded/)
  })

  it('is the only shape that says "approved"', () => {
    const approved = describeThreshold(
      realRecord({ thresholdPolicy: 'approved', threshold: 5 }),
    )
    assert.match(approved, /Flood threshold 5 m \(approved\)/)
    assert.ok(!describeThreshold(unrecordedRecord({ threshold: 5, thresholdPolicy: 'pending' })).includes('(approved)'))
  })
})

describe('summariseProvenance', () => {
  it('substitutes "unrecorded" for every unknown, never a placeholder value', () => {
    const text = summariseProvenance(unrecordedRecord())
    assert.match(text, /dataset=unrecorded/)
    assert.match(text, /station=unrecorded/)
    assert.match(text, /type=unknown/)
    assert.match(text, /threshold_policy=pending/)
    assert.ok(!text.includes('undefined'))
  })

  it('allows an explicit dataset type override', () => {
    const text = summariseProvenance(unrecordedRecord(), 'synthetic')
    assert.match(text, /type=synthetic/)
  })
})
