/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Guard tests for the client-side honesty contract.
 *
 * These are the tests that matter most in this module. Every one of them asserts
 * that something is REFUSED — a synthetic forecast presented as real, a
 * validation score presented as held out, a threshold presented as official. A
 * guard suite that only tests the happy path proves nothing.
 */

import { describe, expect, it } from 'vitest'
import {
  assertComparisonIsHonest,
  bannerSeverity,
  describeDatasetType,
  describeThreshold,
  humanInputRequired,
  integrationStatement,
  isPresentableAsRealResult,
  mandatoryForecastLabel,
  mandatoryMetricLabel,
  metricPresentation,
  openQuestions,
  rowIsScored,
  rowUnavailableReason,
  summariseProvenance,
  thresholdIsOfficial,
} from './contract'
import {
  contradictorySplitRecord,
  executedRowWithNoScore,
  executedWithNoSelection,
  honestComparison,
  REAL_PROVENANCE,
  realForecastRecord,
  syntheticForecastRecord,
  testSplitRanking,
  trainSplitRecord,
  unknownProvenanceRecord,
  validationSplitRecord,
} from './fixtures'
import {
  HUMAN_INPUT_REQUIRED,
  INTEGRATION_STATEMENT,
  SYNTHETIC_DATA_DISCLAIMER,
  SYNTHETIC_METRIC_LABEL,
} from './types'

describe('required statements', () => {
  it('pins the integration statement verbatim', () => {
    expect(INTEGRATION_STATEMENT).toBe(
      'Existing optimization currently requires forecast_id. ' +
        'Additional forecast-derived risk fields require team-owner integration.',
    )
  })

  it('pins the synthetic-data warning verbatim', () => {
    expect(SYNTHETIC_DATA_DISCLAIMER).toBe(
      'THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION DATA.',
    )
  })

  it('serves the integration statement from the guard layer too', () => {
    expect(integrationStatement()).toBe(INTEGRATION_STATEMENT)
  })

  it('serves the unresolved-dependency convention', () => {
    expect(humanInputRequired()).toBe('NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED')
    expect(HUMAN_INPUT_REQUIRED).toBe(humanInputRequired())
  })
})

describe('isPresentableAsRealResult', () => {
  it('accepts real data with no disclaimer', () => {
    expect(isPresentableAsRealResult(realForecastRecord())).toBe(true)
  })

  it('refuses synthetic data even when every metric is present and held out', () => {
    // The counterfactual matters: a complete, valid, held-out metric set on
    // synthetic data is still not a hydrological result.
    const record = syntheticForecastRecord()
    expect(record.metrics).not.toBeNull()
    expect(record.metricProvenance).toEqual({ split: 'test', isSelectionStatistic: false })
    expect(isPresentableAsRealResult(record)).toBe(false)
  })

  it('refuses real data that still carries a disclaimer', () => {
    const record = realForecastRecord({
      provenance: { ...realForecastRecord().provenance, disclaimer: 'provisional run' },
    })
    expect(isPresentableAsRealResult(record)).toBe(false)
  })
})

describe('mandatoryForecastLabel', () => {
  it('returns null for a genuinely presentable forecast', () => {
    expect(mandatoryForecastLabel(realForecastRecord())).toBeNull()
  })

  it('returns the exact synthetic warning for synthetic data', () => {
    expect(mandatoryForecastLabel(syntheticForecastRecord())).toBe(SYNTHETIC_DATA_DISCLAIMER)
  })

  it('does NOT call unknown-provenance data synthetic', () => {
    // Calling undocumented data fake would be its own lie, and would teach a
    // reader to discount the synthetic label.
    const label = mandatoryForecastLabel(unknownProvenanceRecord())
    expect(label).not.toBeNull()
    expect(label).not.toBe(SYNTHETIC_DATA_DISCLAIMER)
    expect(label).toContain('UNVERIFIED PROVENANCE')
  })

  it('never returns both null and a synthetic label for the same record', () => {
    for (const record of [realForecastRecord(), syntheticForecastRecord(), unknownProvenanceRecord()]) {
      const label = mandatoryForecastLabel(record)
      if (label === null) {
        expect(record.provenance.datasetType).toBe('real')
      } else {
        expect(record.provenance.datasetType).not.toBe('real')
      }
    }
  })
})

describe('metricPresentation', () => {
  it('accepts a held-out test score on real data', () => {
    const { presentable, reasons } = metricPresentation(realForecastRecord())
    expect(presentable).toBe(true)
    expect(reasons).toEqual([])
  })

  it('refuses a train-split score and says why', () => {
    const { presentable, reasons } = metricPresentation(trainSplitRecord())
    expect(presentable).toBe(false)
    expect(reasons.join(' ')).toContain('train split')
  })

  it('refuses a validation-split score and says it was optimised against', () => {
    const { presentable, reasons } = metricPresentation(validationSplitRecord())
    expect(presentable).toBe(false)
    expect(reasons.join(' ')).toContain('validation split')
  })

  it('refuses the self-contradictory validation/not-selection record', () => {
    // `{ split: 'validation', isSelectionStatistic: false }` is incoherent. The
    // guard reads the split directly, so it is still refused.
    const { presentable, reasons } = metricPresentation(contradictorySplitRecord())
    expect(presentable).toBe(false)
    expect(reasons.join(' ')).toContain('validation split')
  })

  it('checks the selection flag independently of the split', () => {
    // A test-split score that nevertheless declares itself a selection statistic
    // is refused on the flag alone.
    const record = realForecastRecord({
      metricProvenance: { split: 'test', isSelectionStatistic: true },
    })
    const { presentable, reasons } = metricPresentation(record)
    expect(presentable).toBe(false)
    expect(reasons.join(' ')).toContain('selection statistic')
  })

  it('refuses when no metrics were measured', () => {
    const { presentable, reasons } = metricPresentation(realForecastRecord({ metrics: null }))
    expect(presentable).toBe(false)
    expect(reasons.join(' ')).toContain('no metrics were measured')
  })

  it('refuses when the split is unrecorded', () => {
    const { presentable, reasons } = metricPresentation(
      realForecastRecord({ metricProvenance: null }),
    )
    expect(presentable).toBe(false)
    expect(reasons.join(' ')).toContain('split is unknown')
  })

  it('refuses synthetic metrics however well-formed the split is', () => {
    const { presentable, reasons } = metricPresentation(syntheticForecastRecord())
    expect(presentable).toBe(false)
    expect(reasons.join(' ')).toContain('synthetic/demo')
  })

  it('gives distinct messages for a train score and a validation score', () => {
    const train = metricPresentation(trainSplitRecord()).reasons.join(' ')
    const validation = metricPresentation(validationSplitRecord()).reasons.join(' ')
    expect(train).not.toBe(validation)
  })
})

describe('mandatoryMetricLabel', () => {
  it('returns null only for a presentable held-out real result', () => {
    expect(mandatoryMetricLabel(realForecastRecord())).toBeNull()
  })

  it('uses the short canonical phrase for synthetic metrics', () => {
    expect(mandatoryMetricLabel(syntheticForecastRecord())).toBe(SYNTHETIC_METRIC_LABEL)
  })

  it('uses the specific reasons for a real-data train score', () => {
    const label = mandatoryMetricLabel(trainSplitRecord())
    expect(label).toContain('NOT A HELD-OUT RESULT')
    expect(label).toContain('train split')
    expect(label).not.toBe(SYNTHETIC_METRIC_LABEL)
  })
})

describe('describeDatasetType', () => {
  it('never turns unknown into a real claim', () => {
    expect(describeDatasetType('real')).toBe('real')
    expect(describeDatasetType('synthetic')).toBe('synthetic/demo')
    expect(describeDatasetType('unknown')).toBe('of unknown provenance')
  })
})

describe('openQuestions', () => {
  it('is empty for a fully-specified real record', () => {
    expect(openQuestions(realForecastRecord().provenance)).toEqual([])
  })

  it('lists every missing field plus the declared ones, without duplicates', () => {
    const questions = openQuestions(syntheticForecastRecord().provenance)
    expect(questions).toContain('dataset reference')
    expect(questions).toContain('station reference')
    expect(questions).toContain('dataset type')
    expect(new Set(questions).size).toBe(questions.length)
  })

  it('recomputes rather than trusting a payload that under-declares', () => {
    // A payload claiming nothing is missing is still reported as missing.
    const record = realForecastRecord()
    const lying = { ...record.provenance, datasetReference: null, missingFields: [] }
    expect(openQuestions(lying)).toContain('dataset reference')
  })
})

describe('thresholdIsOfficial / describeThreshold', () => {
  it('is official only when the policy is approved', () => {
    expect(thresholdIsOfficial(realForecastRecord())).toBe(false)
    expect(
      thresholdIsOfficial(realForecastRecord({ thresholdPolicy: 'approved' })),
    ).toBe(true)
  })

  it('never renders a bare number for a pending threshold', () => {
    const text = describeThreshold(realForecastRecord())
    expect(text).toContain('PENDING')
    expect(text).toContain('NOT an official flood stage')
    expect(text).toContain('DEMO value')
  })

  it('never hard-codes the reference engine placeholder 8.0', () => {
    const text = describeThreshold(realForecastRecord())
    expect(text).not.toContain('8.0')
    expect(describeThreshold(syntheticForecastRecord())).not.toContain('8.0')
  })

  it('says so plainly when no threshold is configured', () => {
    const text = describeThreshold(realForecastRecord({ threshold: null }))
    expect(text).toContain('No flood threshold is configured')
  })

  it('reports unknown units rather than assuming metres', () => {
    // Units are set on `provenance`, which is the single authority. This test
    // used to set a record-level `targetUnits` that no guard ever read, so it
    // passed only by accident: `describeThreshold` was still seeing the
    // fixture's default of 'm'. It was a test of nothing.
    const record = realForecastRecord({
      provenance: { ...REAL_PROVENANCE, targetUnits: null },
      threshold: 2,
    })
    expect(describeThreshold(record)).toContain('units unknown')
  })
})

describe('summariseProvenance', () => {
  it('says unrecorded rather than omitting the field', () => {
    const line = summariseProvenance(syntheticForecastRecord())
    expect(line).toContain('dataset=unrecorded')
    expect(line).toContain('station=unrecorded')
    expect(line).toContain('type=synthetic')
    expect(line).toContain('threshold_policy=pending')
  })
})

describe('bannerSeverity', () => {
  it('is none for a presentable record', () => {
    expect(bannerSeverity(realForecastRecord())).toBe('none')
  })

  it('is advisory for unknown provenance — displayable, not a demo', () => {
    expect(bannerSeverity(unknownProvenanceRecord())).toBe('advisory')
  })

  it('is blocking for synthetic data', () => {
    expect(bannerSeverity(syntheticForecastRecord())).toBe('blocking')
  })
})

describe('rowIsScored / rowUnavailableReason', () => {
  it('treats an unexecuted row as unscored', () => {
    const row = honestComparison().rows[1]
    expect(rowIsScored(row)).toBe(false)
  })

  it('gives the real reason a row has no score', () => {
    const row = honestComparison().rows[1]
    expect(rowUnavailableReason(row)).toBe('xgboost.XGBRegressor is not installed')
  })

  it('falls back to the platform convention rather than silence', () => {
    const row = { ...honestComparison().rows[1], unavailableReason: null }
    expect(rowUnavailableReason(row)).toContain(HUMAN_INPUT_REQUIRED)
  })

  it('returns null for a scored row', () => {
    expect(rowUnavailableReason(honestComparison().rows[0])).toBeNull()
  })
})

describe('assertComparisonIsHonest', () => {
  it('accepts an honest comparison', () => {
    expect(() => assertComparisonIsHonest(honestComparison())).not.toThrow()
  })

  it('refuses a comparison that ranked on the test split', () => {
    expect(() => assertComparisonIsHonest(testSplitRanking())).toThrow(/test split/)
  })

  it('refuses an executed row that carries no score', () => {
    expect(() => assertComparisonIsHonest(executedRowWithNoScore())).toThrow(
      /carries no score/,
    )
  })

  it('refuses executed candidates with no selected model', () => {
    expect(() => assertComparisonIsHonest(executedWithNoSelection())).toThrow(
      /no selected model/,
    )
  })

  it('accepts a comparison where nothing executed and nothing was selected', () => {
    const comparison = honestComparison({
      selectedKey: '',
      rows: [
        {
          ...honestComparison().rows[1],
          unavailableReason: 'dependency missing',
        },
      ],
    })
    expect(() => assertComparisonIsHonest(comparison)).not.toThrow()
  })
})
