/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * End-to-end tests for the five Navya endpoint surfaces (B3):
 *
 *   POST /api/forecast
 *   GET  /api/forecast/:id
 *   GET  /api/forecast/station/:id
 *   GET  /api/risk-map
 *   GET  /api/risk/:areaId
 *
 * Runs against the real Express app in memory mode (`../helpers/env.js`), with
 * a stubbed `ForecastClient` so no Python service and no PostgreSQL are ever
 * needed. The stub can throw the same `EnvelopeError`s the real client emits —
 * `FORECAST_ENGINE_ERROR` (engine refusal / dependency blocked / artifact
 * unavailable) and `AI_SERVICE_UNAVAILABLE` (unreachable) — so the honest
 * error states are reachable without a live engine.
 */

import '../helpers/env.js'
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import type { Express } from 'express'
import request from 'supertest'
import { createApp } from '../../src/app.ts'
import { buildContainer, type Container } from '../../src/container.ts'
import { EnvelopeError } from '../../src/utils/errors.ts'
import type { ForecastClient } from '../../src/clients/ai-service.client.ts'
import type { ForecastRepository } from '../../src/repositories/repositories.ts'
import { NavyaForecastService } from '../../src/navya/forecasting/forecast-service.ts'
import {
  STATION_MAPPING_UNAVAILABLE_MESSAGE,
} from '../../src/navya/forecasting/endpoint-states.ts'
import {
  forecastContract,
  riskAnalyticsContract,
  stubForecastClient,
} from './helpers/fixtures.ts'

type Stub = ReturnType<typeof stubForecastClient>

/** A stub whose horizon argument is recorded, so defaulting is observable. */
function horizonRecordingClient(base: Stub): ForecastClient & { horizons: (number | undefined)[] } {
  const horizons: (number | undefined)[] = []
  return {
    ...base,
    async getLatestForecast(horizonHours?: number) {
      horizons.push(horizonHours)
      return base.getLatestForecast(horizonHours)
    },
    horizons,
  }
}

async function setup(client: ForecastClient): Promise<{ app: Express; container: Container; token: string }> {
  const container = await buildContainer({ aiClient: client })
  const app = await createApp(container)
  const login = await request(app).post('/api/auth/login').send({ username: 'admin', password: 'qflare-admin' })
  const token: string = login.body.data.token
  return { app, container, token }
}

const withAuth = (token: string) => ({ Authorization: `Bearer ${token}` })

/** The exact key set of the forecast surface — pinned so it cannot drift. */
const FORECAST_SURFACE_KEYS = [
  'flood_probability',
  'forecast_horizon',
  'forecast_id',
  'model_id',
  'model_version',
  'predicted_water_level',
  'prediction_timestamp',
  'risk_level',
  'status',
  'threshold_label',
  'threshold_level',
]

describe('POST /api/forecast', () => {
  it('201 + canonical payload for a valid request; persists the row; GET round-trips', async () => {
    const stub = stubForecastClient()
    const { app, container, token } = await setup(stub)
    const res = await request(app).post('/api/forecast').set(withAuth(token)).send({ horizon_hours: 24 })
    assert.equal(res.status, 201)
    assert.equal(res.body.success, true)
    assert.equal(typeof res.body.timestamp, 'string')

    const data = res.body.data
    // Provenance/model-identity preservation straight from the served contract.
    assert.equal(data.forecast_id, forecastContract().forecast_id)
    assert.equal(data.model_id, forecastContract().model_id)
    assert.equal(data.model_version, forecastContract().model_version)
    assert.equal(data.forecast_horizon, forecastContract().forecast_horizon)
    assert.equal(data.prediction_timestamp, forecastContract().prediction_timestamp)
    assert.equal(data.status, forecastContract().status)
    assert.equal(data.risk_level, forecastContract().risk_level)
    assert.equal(data.threshold_level, null)
    assert.equal(data.threshold_label, null)
    assert.deepEqual(Object.keys(data).sort(), [...FORECAST_SURFACE_KEYS].sort())

    // Persisted through the existing repository abstraction.
    const saved = await container.forecastRepo.findByForecastId(data.forecast_id)
    assert.ok(saved !== null)
    assert.equal(saved.modelId, 'NAVYA-HYDRO-001')

    // GET round-trips the same payload.
    const read = await request(app).get(`/api/forecast/${data.forecast_id}`).set(withAuth(token))
    assert.equal(read.status, 200)
    assert.deepEqual(read.body.data, data)
    assert.deepEqual(Object.keys(read.body.data).sort(), [...FORECAST_SURFACE_KEYS].sort())
  })

  it('preserves threshold values and the demo/synthetic threshold label verbatim', async () => {
    const stub = stubForecastClient({
      analytics: riskAnalyticsContract({
        threshold_level: 5.2,
        threshold_label: 'demo — not official: synthetic flood stage for testing',
      }),
    })
    const { app, token } = await setup(stub)
    const res = await request(app).post('/api/forecast').set(withAuth(token)).send({ horizon_hours: 6 })
    assert.equal(res.status, 201)
    assert.equal(res.body.data.threshold_level, 5.2)
    assert.equal(res.body.data.threshold_label, 'demo — not official: synthetic flood stage for testing')
    // The engine remains the risk authority — no level invented here.
    assert.equal(res.body.data.risk_level, forecastContract().risk_level)
  })

  it('defaults the horizon to 24 when the body omits it', async () => {
    const client = horizonRecordingClient(stubForecastClient())
    const { app, token } = await setup(client)
    const res = await request(app).post('/api/forecast').set(withAuth(token)).send({})
    assert.equal(res.status, 201)
    assert.equal(client.horizons[0], 24)
  })

  it('rejects invalid horizons with 422 VALIDATION_ERROR, never coercing', async () => {
    const { app, token } = await setup(stubForecastClient())
    for (const invalid of [0, -1, 73, 1000, 2.5, '24', null, true]) {
      const res = await request(app).post('/api/forecast').set(withAuth(token)).send({ horizon_hours: invalid })
      assert.equal(res.status, 422, `horizon ${String(invalid)} must be rejected`)
      assert.equal(res.body.success, false)
      assert.equal(res.body.error.code, 'VALIDATION_ERROR')
    }
  })

  it('502 FORECAST_ENGINE_ERROR when the hydro engine is dependency blocked; message preserved', async () => {
    const stub = stubForecastClient({
      forecast: new EnvelopeError(
        'FORECAST_ENGINE_ERROR',
        'Engine failed to produce a forecast: refusing to serve: HYDRO_ENABLED=false — the engine is switched off',
      ),
    })
    const { app, container, token } = await setup(stub)
    const res = await request(app).post('/api/forecast').set(withAuth(token)).send({})
    assert.equal(res.status, 502)
    assert.equal(res.body.success, false)
    assert.equal(res.body.error.code, 'FORECAST_ENGINE_ERROR')
    assert.match(res.body.error.message, /refusing to serve/)
    assert.ok(!('data' in res.body))
    assert.equal(await container.forecastRepo.getLatest(), null)
  })

  it('502 FORECAST_ENGINE_ERROR when artifacts are unavailable — never a baseline fallback', async () => {
    const stub = stubForecastClient({
      forecast: new EnvelopeError(
        'FORECAST_ENGINE_ERROR',
        'refusing to serve: training artifacts are unavailable (HYDRO_MODEL_ARTIFACT_MISSING)',
      ),
    })
    const { app, container, token } = await setup(stub)
    const res = await request(app).post('/api/forecast').set(withAuth(token)).send({})
    assert.equal(res.status, 502)
    assert.equal(res.body.error.code, 'FORECAST_ENGINE_ERROR')
    assert.match(res.body.error.message, /HYDRO_MODEL_ARTIFACT_MISSING/)
    // No silent baseline: nothing was persisted, no success was fabricated.
    assert.equal(await container.forecastRepo.getLatest(), null)
    assert.equal(res.body.success, false)
  })

  it('B4: surfaces the configured hydro engine verbatim when it is dependency blocked (no dataset configured)', async () => {
    // The exact message the configured HydroForecastEngine emits when no
    // HYDRO_DATASET_PATH is set ("forecasting pipeline could not start: no
    // dataset configured. ..."), wrapped by the AI-service routing layer
    // ("Engine failed to produce a forecast: ..."). Pinned byte-for-byte so the
    // backend contract is tied to the real engine refusal, not a canned example.
    const realEngineMessage =
      'Engine failed to produce a forecast: forecasting pipeline could not start: no dataset configured. Set HYDRO_DATASET_PATH to a real hydrological CSV, or run the synthetic demo writer (training.py --write-synthetic <path>) which labels the output as SYNTHETIC/DEMO DATA.'
    const stub = stubForecastClient({ forecast: new EnvelopeError('FORECAST_ENGINE_ERROR', realEngineMessage) })
    const { app, container, token } = await setup(stub)
    const res = await request(app).post('/api/forecast').set(withAuth(token)).send({})
    assert.equal(res.status, 502)
    assert.equal(res.body.success, false)
    assert.equal(res.body.error.code, 'FORECAST_ENGINE_ERROR')
    // Byte-for-byte message fidelity: the engine's honest refusal survives the
    // backend envelope — no baseline, no fabricated data, nothing persisted.
    assert.equal(res.body.error.message, realEngineMessage)
    assert.ok(!('data' in res.body))
    assert.equal(await container.forecastRepo.getLatest(), null)
  })

  it('503 AI_SERVICE_UNAVAILABLE when the service is unreachable', async () => {
    const stub = stubForecastClient({
      forecast: new EnvelopeError('AI_SERVICE_UNAVAILABLE', 'AI service is currently unavailable'),
    })
    const { app, token } = await setup(stub)
    const res = await request(app).post('/api/forecast').set(withAuth(token)).send({})
    assert.equal(res.status, 503)
    assert.equal(res.body.error.code, 'AI_SERVICE_UNAVAILABLE')
    assert.equal(res.body.success, false)
  })

  it('503 for an unexpected client failure — never HTTP 200 with fake data', async () => {
    const stub = stubForecastClient({ forecast: new Error('network exploded') })
    const { app, container, token } = await setup(stub)
    const res = await request(app).post('/api/forecast').set(withAuth(token)).send({})
    assert.equal(res.status, 503)
    assert.equal(res.body.success, false)
    assert.equal(res.body.error.code, 'AI_SERVICE_UNAVAILABLE')
    assert.equal(await container.forecastRepo.getLatest(), null)
  })
})

describe('GET /api/forecast/:id', () => {
  it('200 + the persisted payload for a created forecast', async () => {
    const { app, container, token } = await setup(stubForecastClient())
    await request(app).post('/api/forecast').set(withAuth(token)).send({})
    const saved = await container.forecastRepo.getLatest()
    assert.ok(saved !== null)
    const res = await request(app).get(`/api/forecast/${saved.forecastId}`).set(withAuth(token))
    assert.equal(res.status, 200)
    assert.equal(res.body.data.forecast_id, saved.forecastId)
  })

  it('404 FORECAST_NOT_FOUND canonical envelope for a missing forecast', async () => {
    const { app, token } = await setup(stubForecastClient())
    const res = await request(app).get('/api/forecast/FC-20991231-0001').set(withAuth(token))
    assert.equal(res.status, 404)
    assert.equal(res.body.success, false)
    assert.equal(res.body.error.code, 'FORECAST_NOT_FOUND')
    assert.equal(typeof res.body.timestamp, 'string')
  })

  it('422 for a malformed forecast id', async () => {
    const { app, token } = await setup(stubForecastClient())
    const res = await request(app).get('/api/forecast/not-an-id').set(withAuth(token))
    assert.equal(res.status, 422)
    assert.equal(res.body.error.code, 'VALIDATION_ERROR')
  })
})

describe('GET /api/forecast/station/:id', () => {
  it('200 typed NOT_EVALUABLE state with the required explanation; no forecast data', async () => {
    const { app, token } = await setup(stubForecastClient())
    const res = await request(app).get('/api/forecast/station/gauge-01').set(withAuth(token))
    assert.equal(res.status, 200)
    assert.equal(res.body.success, true)
    const data = res.body.data
    assert.equal(data.status, 'NOT_EVALUABLE')
    assert.equal(data.code, 'FORECAST_TO_STATION_MAPPING_UNAVAILABLE')
    assert.equal(data.message, STATION_MAPPING_UNAVAILABLE_MESSAGE)
    assert.equal(data.stationId, 'gauge-01')
    assert.ok(!('forecast_id' in data), 'a station state must never carry a forecast')
    assert.ok(!('flood_probability' in data))
    assert.equal(typeof data.reasons, 'object')
    assert.ok(data.reasons.length >= 3)
  })

  it('returns the same structural state for any station — never nearest-station inference', async () => {
    const { app, token } = await setup(stubForecastClient())
    const a = (await request(app).get('/api/forecast/station/gauge-a').set(withAuth(token))).body.data
    const b = (await request(app).get('/api/forecast/station/gauge-b').set(withAuth(token))).body.data
    assert.equal(a.status, b.status)
    assert.equal(a.code, b.code)
    assert.equal(a.message, b.message)
    assert.deepEqual(a.reasons, b.reasons)
    assert.equal(a.stationId, 'gauge-a')
    assert.equal(b.stationId, 'gauge-b')
  })
})

describe('GET /api/risk-map', () => {
  it('200 typed NOT_EVALUABLE; exposure readings value null; priority WITHHELD', async () => {
    const { app, token } = await setup(stubForecastClient())
    const res = await request(app).get('/api/risk-map').set(withAuth(token))
    assert.equal(res.status, 200)
    const data = res.body.data
    assert.equal(data.status, 'NOT_EVALUABLE')
    assert.equal(data.code, 'RISK_MAP_NOT_EVALUABLE')
    assert.ok(data.reasons.length > 0)
    for (const reading of data.exposure.readings) {
      assert.equal(reading.availability, 'NOT_EVALUABLE')
      assert.equal(reading.value, null)
    }
    assert.equal(data.exposure.responsePriority.decision, 'WITHHELD')
    assert.equal(data.exposure.responsePriority.value, null)
    assert.equal(data.exposure.responsePriority.availability, 'NOT_EVALUABLE')
  })

  it('carries no fabricated GIS/exposure/risk numbers anywhere', async () => {
    const { app, token } = await setup(stubForecastClient())
    const res = await request(app).get('/api/risk-map').set(withAuth(token))
    const data = res.body.data
    assert.ok(!('coordinates' in data))
    assert.ok(!('population' in data))
    assert.ok(!('infrastructure' in data))
    assert.ok(!('priorityScore' in data))
    assert.ok(!('riskScore' in data))
    const serialised = JSON.stringify(data)
    assert.ok(!/["']value["']\s*:\s*\d/.test(serialised), 'no exposure value may be a number')
    assert.ok(!/["'](population|infrastructure)["']\s*:\s*\d/.test(serialised))
  })
})

describe('GET /api/risk/:areaId', () => {
  it('200 typed NOT_EVALUABLE with the area echoed; exposure stays null', async () => {
    const { app, token } = await setup(stubForecastClient())
    const res = await request(app).get('/api/risk/zone-7').set(withAuth(token))
    assert.equal(res.status, 200)
    const data = res.body.data
    assert.equal(data.status, 'NOT_EVALUABLE')
    assert.equal(data.code, 'AREA_RISK_NOT_EVALUABLE')
    assert.equal(data.areaId, 'zone-7')
    assert.ok(!('coordinates' in data))
    assert.ok(!('population' in data))
    assert.equal(data.exposure.responsePriority.decision, 'WITHHELD')
  })

  it('422 for an overlong area id', async () => {
    const { app, token } = await setup(stubForecastClient())
    const res = await request(app).get(`/api/risk/${'a'.repeat(129)}`).set(withAuth(token))
    assert.equal(res.status, 422)
    assert.equal(res.body.error.code, 'VALIDATION_ERROR')
  })
})

describe('error-envelope compatibility', () => {
  it('401 UNAUTHORIZED canonical envelope when auth is enabled and no token is sent', async () => {
    const { app } = await setup(stubForecastClient())
    const res = await request(app).post('/api/forecast').send({})
    assert.equal(res.status, 401)
    assert.equal(res.body.success, false)
    assert.equal(res.body.error.code, 'UNAUTHORIZED')
    assert.equal(typeof res.body.timestamp, 'string')
  })

  it('404 NOT_FOUND canonical envelope for an unknown route on the same prefix', async () => {
    const { app, token } = await setup(stubForecastClient())
    const res = await request(app).get('/api/forecast').set(withAuth(token))
    assert.equal(res.status, 404)
    assert.equal(res.body.success, false)
    assert.equal(res.body.error.code, 'NOT_FOUND')
  })

  it('service-level: an unexpected repository failure rejects and is never swallowed into success', async () => {
    const okClient = stubForecastClient()
    const throwingRepo = {
      save: async () => {
        throw new Error('repo exploded')
      },
    } as unknown as ForecastRepository
    const service = new NavyaForecastService(okClient, throwingRepo)
    await assert.rejects(() => service.createForecast(24), /repo exploded/)
  })
})