import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { ZodError } from 'zod'
import {
  forecastIdSchema,
  listPredictionsQuerySchema,
  loginSchema,
  modelDetailParamsSchema,
  optimizationBodySchema,
  probabilitySchema,
  riskLevelSchema,
} from '../../src/middleware/schemas.ts'

function parseOrThrow(schema: unknown, value: unknown) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (schema as any).parse(value)
}

describe('validation schemas', () => {
  describe('forecastIdSchema', () => {
    it('accepts a valid FC-YYYYMMDD-NNNN id', () => {
      assert.equal(forecastIdSchema.parse('FC-20260916-0001'), 'FC-20260916-0001')
    })

    it('rejects ids that do not match the pattern', () => {
      for (const bad of ['bad-id', 'fc-20260916-0001', 'FC-20260916', 'FC-20260916-', 'FC-20260916-0000000000']) {
        assert.throws(() => forecastIdSchema.parse(bad), ZodError, `expected reject: ${bad}`)
      }
    })
  })

  describe('probabilitySchema', () => {
    it('accepts values in [0,1]', () => {
      assert.equal(probabilitySchema.parse(0), 0)
      assert.equal(probabilitySchema.parse(0.5), 0.5)
      assert.equal(probabilitySchema.parse(1), 1)
    })

    it('rejects out-of-range, NaN, and Infinity', () => {
      for (const bad of [-0.1, 1.01, NaN, Infinity, -Infinity]) {
        assert.throws(() => probabilitySchema.parse(bad), ZodError, `expected reject: ${bad}`)
      }
    })

    it('rejects non-number types instead of coercing', () => {
      assert.throws(() => probabilitySchema.parse('0.5'), ZodError)
    })
  })

  describe('riskLevelSchema', () => {
    it('accepts the four documented risk levels', () => {
      for (const risk of ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']) {
        assert.equal(riskLevelSchema.parse(risk), risk)
      }
    })

    it('rejects unknown or lowercase values', () => {
      for (const bad of ['high', 'EXTREME', '']) {
        assert.throws(() => riskLevelSchema.parse(bad), ZodError, `expected reject: ${bad}`)
      }
    })
  })

  describe('loginSchema', () => {
    it('accepts username/password strings', () => {
      assert.deepEqual(loginSchema.parse({ username: 'admin', password: 's3cret' }), { username: 'admin', password: 's3cret' })
    })

    it('rejects missing fields and empty values', () => {
      assert.throws(() => loginSchema.parse({ username: 'admin' }), ZodError)
      assert.throws(() => loginSchema.parse({ username: '', password: 'x' }), ZodError)
      assert.throws(() => loginSchema.parse({ username: 1, password: 'x' }), ZodError)
    })
  })

  describe('listPredictionsQuerySchema', () => {
    it('coerces and defaults page/limit', () => {
      const parsed = listPredictionsQuerySchema.parse({})
      assert.equal(parsed.page, 1)
      assert.equal(parsed.limit, 10)
    })

    it('rejects page=0 and limit>100', () => {
      assert.throws(() => listPredictionsQuerySchema.parse({ page: 0 }), ZodError)
      assert.throws(() => listPredictionsQuerySchema.parse({ limit: 101 }), ZodError)
    })

    it('rejects invalid datetime filters', () => {
      assert.throws(() => listPredictionsQuerySchema.parse({ from: 'not-a-date' }), ZodError)
    })

    it('accepts valid risk filter', () => {
      const parsed = listPredictionsQuerySchema.parse({ risk: 'HIGH', page: '2', limit: '25' })
      assert.equal(parsed.risk, 'HIGH')
      assert.equal(parsed.page, 2)
      assert.equal(parsed.limit, 25)
    })
  })

  describe('optimizationBodySchema', () => {
    it('requires a valid forecast_id', () => {
      assert.throws(() => optimizationBodySchema.parse({}), ZodError)
      assert.throws(() => optimizationBodySchema.parse({ forecast_id: 'nope' }), ZodError)
      assert.deepEqual(optimizationBodySchema.parse({ forecast_id: 'FC-20260916-0001' }), { forecast_id: 'FC-20260916-0001' })
    })

    it('rejects out-of-range risk_score and bad priority', () => {
      assert.throws(() => optimizationBodySchema.parse({ forecast_id: 'FC-20260916-0001', risk_score: 2 }), ZodError)
      assert.throws(() => optimizationBodySchema.parse({ forecast_id: 'FC-20260916-0001', priority: 'urgent' }), ZodError)
    })
  })

  describe('modelDetailParamsSchema', () => {
    it('accepts a positive numeric id', () => {
      assert.deepEqual(modelDetailParamsSchema.parse({ id: '7' }), { id: '7' })
    })

    it('rejects empty, zero, and non-numeric ids', () => {
      for (const bad of ['', '0', 'abc', '-1', '1.5']) {
        assert.throws(() => modelDetailParamsSchema.parse({ id: bad }), ZodError, `expected reject: ${bad}`)
      }
    })
  })

  it('all schemas are available for use', () => {
    // Just confirms exports resolve (schemas are imported at module scope above).
    assert.ok(parseOrThrow(forecastIdSchema, 'FC-20260916-0001'))
  })
})