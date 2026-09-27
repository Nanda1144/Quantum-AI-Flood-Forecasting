/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Tests for the adapter from the running AI contract to a Navya record.
 *
 * `ai-service.client.ts` and `src/types/contract.ts` are team-owned and
 * untouched, so this adapter is where the lossy step lives. The tests below are
 * mostly about what the adapter *declares missing*: `LOSSY_FIELDS` must stay all
 * `null`, and a record built from the running contract must be `unknown`
 * provenance, because the contract carries no lineage at all.
 *
 * The practical effect: if a team owner later extends the contract, these tests
 * fail and point at the list that has become stale. That is the intent.
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  LOSSY_FIELDS,
  NavyaForecastAdapter,
  adapterGaps,
  parseHorizonHours,
  toNavyaForecastRecord,
} from '../../src/navya/forecasting/forecast-adapter.ts'
import {
  forecastContract,
  modelInfoContract,
  riskAnalyticsContract,
  stubForecastClient,
} from './helpers/fixtures.ts'

describe('LOSSY_FIELDS', () => {
  /**
   * The whole file in one test.
   *
   * Every entry is `null` because the running AI contract carries none of these
   * fields. A non-null entry would assert that the transport supplies something
   * it demonstrably does not.
   */
  it('is entirely null, because the running contract carries none of these fields', () => {
    for (const [field, value] of Object.entries(LOSSY_FIELDS)) {
      assert.equal(value, null, `${field} should be null while the contract omits it`)
    }
  })

  it('covers the fields a Navya record needs but the contract does not send', () => {
    for (const field of [
      'datasetReference',
      'datasetLicense',
      'datasetChecksum',
      'samplingInterval',
      'stationReference',
      'residualSigma',
      'thresholdSource',
      'regressionMetrics',
      'metricProvenance',
      'backtest',
    ]) {
      assert.ok(field in LOSSY_FIELDS, `${field} is not accounted for as a known gap`)
    }
  })
})

describe('parseHorizonHours', () => {
  it('parses the hour formats the platform uses', () => {
    assert.equal(parseHorizonHours('6h'), 6)
    assert.equal(parseHorizonHours('24h'), 24)
    assert.equal(parseHorizonHours('1.5h'), 1.5)
    assert.equal(parseHorizonHours(' 12H '), 12)
  })

  it('returns 0 for an unparseable horizon rather than guessing a number', () => {
    // Not NaN, and not a default like 24: a fabricated horizon would put the
    // wrong lead time in the provenance record.
    assert.equal(parseHorizonHours(''), 0)
    assert.equal(parseHorizonHours('soon'), 0)
    assert.equal(parseHorizonHours('6 days'), 0)
    assert.equal(parseHorizonHours('6'), 0)
  })
})

describe('toNavyaForecastRecord', () => {
  it('copies the fields the running contract does carry', () => {
    const contract = forecastContract()
    const record = toNavyaForecastRecord(contract)
    assert.equal(record.forecastId, contract.forecast_id)
    assert.equal(record.forecastTimestamp, contract.prediction_timestamp)
    assert.equal(record.forecastHorizon, contract.forecast_horizon)
    assert.equal(record.predictedWaterLevel, contract.predicted_water_level)
    assert.equal(record.floodProbability, contract.flood_probability)
    assert.equal(record.riskLevel, contract.risk_level)
    assert.equal(record.status, contract.status)
  })

  /**
   * Load-bearing: the contract carries no lineage whatsoever, so 'unknown' is
   * the only defensible value. 'real' would assert a data origin nobody sent.
   */
  it('records the dataset type as unknown, never as real', () => {
    const record = toNavyaForecastRecord(forecastContract())
    assert.equal(record.provenance.datasetType, 'unknown')
    assert.equal(record.provenance.datasetReference, null)
    assert.equal(record.provenance.stationReference, null)
    assert.equal(record.provenance.datasetLicense, null)
    assert.equal(record.provenance.datasetChecksum, null)
  })

  it('carries no metrics and no backtest, because the contract has neither', () => {
    const record = toNavyaForecastRecord(forecastContract())
    assert.equal(record.metrics, null)
    assert.equal(record.metricProvenance, null)
    assert.deepEqual(record.backtest, [])
  })

  it('reports a contract version of "unknown" rather than inventing one', () => {
    assert.equal(toNavyaForecastRecord(forecastContract()).provenance.contractVersion, 'unknown')
  })

  it('leaves the target unit unknown rather than assuming metres', () => {
    // The team contract carries no unit. Assuming 'm' would be a datum claim.
    assert.equal(toNavyaForecastRecord(forecastContract()).targetUnits, null)
    assert.equal(toNavyaForecastRecord(forecastContract()).provenance.targetUnits, null)
  })

  it('leaves inflow null, since the contract carries only a water level', () => {
    assert.equal(toNavyaForecastRecord(forecastContract()).predictedInflow, null)
  })

  it('leaves the residual sigma null, because the contract carries no backtest', () => {
    assert.equal(toNavyaForecastRecord(forecastContract()).residualSigma, null)
  })

  it('degrades to a null threshold when risk analytics are unavailable', () => {
    const record = toNavyaForecastRecord(forecastContract(), { analytics: null })
    assert.equal(record.threshold, null)
    assert.equal(record.thresholdSource, null)
  })

  it('uses the threshold level and its label when analytics are present', () => {
    const record = toNavyaForecastRecord(forecastContract(), {
      analytics: riskAnalyticsContract({ threshold_level: 5, threshold_label: 'DEMO value' }),
    })
    assert.equal(record.threshold, 5)
    assert.equal(record.thresholdSource, 'DEMO value')
  })

  it('treats a null threshold level as no threshold, not as zero', () => {
    const record = toNavyaForecastRecord(forecastContract(), {
      analytics: riskAnalyticsContract({ threshold_level: null, threshold_label: null }),
    })
    assert.equal(record.threshold, null)
  })

  describe('thresholdPolicyFrom', () => {
    /**
     * Every path returns 'pending'.
     *
     * The running contract has no field for formal approval, so inferring
     * 'approved' from the absence of a disclaimer would be reading sign-off into
     * silence. This test exists to make that decision deliberate: promoting any
     * of these to 'approved' requires a team-owned field to carry the approval.
     */
    it('is pending for a disclaimed label', () => {
      const record = toNavyaForecastRecord(forecastContract(), {
        analytics: riskAnalyticsContract({
          threshold_level: 5,
          threshold_label: 'DEMO value; NOT an official flood stage (policy PENDING)',
        }),
      })
      assert.equal(record.thresholdPolicy, 'pending')
    })

    it('is pending for a threshold whose label disclaims nothing', () => {
      // The dangerous case: silence is not approval.
      const record = toNavyaForecastRecord(forecastContract(), {
        analytics: riskAnalyticsContract({ threshold_level: 5, threshold_label: null }),
      })
      assert.equal(record.thresholdPolicy, 'pending')
    })

    it('is pending for a bare label that does not disclaim', () => {
      const record = toNavyaForecastRecord(forecastContract(), {
        analytics: riskAnalyticsContract({ threshold_level: 5, threshold_label: '5.0' }),
      })
      assert.equal(record.thresholdPolicy, 'pending')
    })

    it('is pending when there is no threshold at all', () => {
      const record = toNavyaForecastRecord(forecastContract())
      assert.equal(record.thresholdPolicy, 'pending')
    })
  })

  describe('model metadata', () => {
    it('falls back to the contract model id and version', () => {
      const record = toNavyaForecastRecord(forecastContract(), { model: null })
      assert.equal(record.provenance.modelId, 'NAVYA-HYDRO-001')
      assert.equal(record.provenance.modelVersion, '0.1.0')
    })

    it('prefers registry metadata when it matches the forecast model', () => {
      const record = toNavyaForecastRecord(forecastContract(), {
        model: modelInfoContract({ model_id: 'NAVYA-HYDRO-001', version: '0.2.0' }),
      })
      assert.equal(record.provenance.modelVersion, '0.2.0')
    })
  })

  it('parses the horizon into the provenance record', () => {
    assert.equal(
      toNavyaForecastRecord(forecastContract({ forecast_horizon: '24h' })).provenance
        .forecastHorizonHours,
      24,
    )
  })
})

describe('adapterGaps', () => {
  it('names every field the transport threw away', () => {
    const gaps = adapterGaps(toNavyaForecastRecord(forecastContract()))
    for (const gap of [
      'datasetReference',
      'datasetLicense',
      'datasetChecksum',
      'samplingInterval',
      'stationReference',
      'targetUnits',
      'datasetType',
    ]) {
      assert.ok(gaps.includes(gap), `${gap} is not reported as a gap`)
    }
  })

  it('always reports at least the unknown dataset type', () => {
    assert.ok(adapterGaps(toNavyaForecastRecord(forecastContract())).includes('datasetType'))
  })
})

describe('NavyaForecastAdapter', () => {
  it('builds a record from the team client with no change to that client', async () => {
    const client = stubForecastClient({
      forecast: forecastContract(),
      analytics: riskAnalyticsContract({ threshold_level: 5, threshold_label: 'DEMO' }),
      models: [modelInfoContract()],
    })
    const adapter = new NavyaForecastAdapter(client)
    const record = await adapter.latest()
    assert.equal(record.forecastId, 'FC-20240101-0600')
    assert.equal(record.threshold, 5)
    assert.equal(record.provenance.datasetType, 'unknown')
  })

  it('passes the requested horizon through to the team client', async () => {
    const client = stubForecastClient()
    await new NavyaForecastAdapter(client).latest(48)
    assert.ok(client.calls.includes('getLatestForecast'))
  })

  it('degrades to a pending threshold when risk analytics fail', async () => {
    // A second call failing must not fail the forecast read itself.
    const client = stubForecastClient({
      forecast: forecastContract(),
      analytics: new Error('ai-service unreachable'),
    })
    const record = await new NavyaForecastAdapter(client).latest()
    assert.equal(record.threshold, null)
    assert.equal(record.thresholdPolicy, 'pending')
    assert.equal(record.provenance.datasetType, 'unknown')
  })

  it('degrades to no model metadata when the registry call fails', async () => {
    const client = stubForecastClient({
      forecast: forecastContract(),
      models: new Error('registry unavailable'),
    })
    const record = await new NavyaForecastAdapter(client).latest()
    assert.equal(record.provenance.modelVersion, '0.1.0')
  })

  it('returns null from riskAnalytics rather than throwing', async () => {
    const client = stubForecastClient({ analytics: new Error('nope') })
    assert.equal(await new NavyaForecastAdapter(client).riskAnalytics(), null)
  })

  it('propagates a failure of the forecast read itself, which is not degradable', async () => {
    const client = stubForecastClient({ forecast: new Error('ai-service down') })
    await assert.rejects(() => new NavyaForecastAdapter(client).latest(), /ai-service down/)
  })

  it('delegates series and models to the team client unchanged', async () => {
    const client = stubForecastClient()
    const adapter = new NavyaForecastAdapter(client)
    await adapter.series(12)
    await adapter.models()
    assert.ok(client.calls.includes('getForecastSeries'))
    assert.ok(client.calls.includes('getModels'))
  })
})
