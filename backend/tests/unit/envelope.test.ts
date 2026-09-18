import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { AppError, ErrorCodes, success } from '../../src/envelope.ts'

describe('envelope', () => {
  it('success() wraps data in the envelope shape', () => {
    const body = success({ foo: 'bar' })
    assert.equal(body.success, true)
    assert.deepEqual(body.data, { foo: 'bar' })
    assert.ok(typeof body.timestamp === 'string')
    // Timestamp is valid ISO-8601.
    assert.ok(!isNaN(Date.parse(body.timestamp)))
  })

  it('AppError carries status, code, message, and optional details', () => {
    const err = new AppError(404, ErrorCodes.MODEL_NOT_FOUND, 'No model', { hint: 'seed first' })
    assert.equal(err.status, 404)
    assert.equal(err.code, 'MODEL_NOT_FOUND')
    assert.equal(err.message, 'No model')
    assert.deepEqual(err.details, { hint: 'seed first' })
    assert.equal(err.name, 'AppError')
    assert.ok(err instanceof Error)
  })

  it('ErrorCodes object contains every required code', () => {
    const required = [
      'VALIDATION_ERROR',
      'UNAUTHORIZED',
      'FORBIDDEN',
      'AI_SERVICE_UNAVAILABLE',
      'FORECAST_NOT_FOUND',
      'MODEL_NOT_FOUND',
      'STALE_DATA',
      'RATE_LIMITED',
      'OPTIMIZATION_CONFLICT',
      'INTERNAL_ERROR',
    ] as const
    for (const key of required) {
      assert.equal(ErrorCodes[key], key, `${key} missing or mismatched`)
    }
  })
})