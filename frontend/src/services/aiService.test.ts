/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These tests verify the AI analytics service client: real backend
 * success, real auth rejection, and the clearly-flagged dev-only sample-data
 * fallback gating. No test fabricates a production prediction.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MockInstance } from 'vitest'
import { loadAIAnalytics, loadModelComparison, shouldAllowMockData } from './aiService'
import { buildComparisonResult, buildComparisonRows, buildSnapshot } from '../test/fixtures'

function okResponse(data: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => ({ success: true, data }),
  } as unknown as Response
}

let fetchSpy: MockInstance

describe('loadAIAnalytics', () => {
  beforeEach(() => {
    // Restore any previous spy, then replace fetch with a controlled mock that
    // rejects by default so tests must opt into a network result.
    fetchSpy?.mockRestore()
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('no network in tests'))
    vi.unstubAllEnvs()
    vi.useRealTimers()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.useRealTimers()
  })

  it('returns the backend snapshot on success and reports isMock=false', async () => {
    const snapshot = buildSnapshot()
    fetchSpy.mockResolvedValueOnce(okResponse(snapshot))

    const result = await loadAIAnalytics()

    expect(result.isMock).toBe(false)
    expect(result.snapshot.forecast.forecastId).toBe(snapshot.forecast.forecastId)
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/ai/analytics',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('surfaces UNAUTHORIZED when the backend returns 401 (no sample fallback)', async () => {
    fetchSpy.mockResolvedValueOnce({ ok: false, status: 401 } as unknown as Response)

    await expect(loadAIAnalytics()).rejects.toMatchObject({ code: 'UNAUTHORIZED' })
  })

  it('throws instead of serving sample data when the fallback is disabled', async () => {
    vi.stubEnv('VITE_USE_MOCK_DATA', 'false')
    fetchSpy.mockRejectedValueOnce(new TypeError('network down'))

    await expect(loadAIAnalytics()).rejects.toMatchObject({ code: 'API_ERROR' })
  })

  it('falls back to clearly-flagged sample data only when enabled', async () => {
    vi.useFakeTimers()
    vi.stubEnv('VITE_USE_MOCK_DATA', 'true')
    fetchSpy.mockRejectedValueOnce(new TypeError('network down'))

    const promise = loadAIAnalytics()
    await vi.advanceTimersByTimeAsync(700)
    const result = await promise

    expect(result.isMock).toBe(true)
    expect(result.snapshot.forecast).toBeDefined()
  })

  it('keeps the fallback disabled in production semantics via the flag helper', () => {
    // DEV is always true under vitest, so forcing VITE_USE_MOCK_DATA off is the
    // only way to express "production-like" — exactly what the config does.
    vi.stubEnv('VITE_USE_MOCK_DATA', 'false')
    expect(shouldAllowMockData()).toBe(false)
  })
})

describe('loadModelComparison', () => {
  beforeEach(() => {
    fetchSpy?.mockRestore()
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('no network in tests'))
    vi.unstubAllEnvs()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('surfaces UNAUTHORIZED without falling back to sample rows', async () => {
    fetchSpy.mockResolvedValueOnce({ ok: false, status: 401 } as unknown as Response)

    await expect(loadModelComparison({})).rejects.toMatchObject({ code: 'UNAUTHORIZED' })
  })

  it('returns the registry rows straight from the backend (no wrapper, no mock)', async () => {
    const rows = [
      buildComparisonRows({ name: 'QEnhanced-LSTM', status: 'development', metrics: { rmse: 0.14, mae: 0.1, r2: 0.97 }, inferenceTimeMs: 10, evaluatedAt: '2026-09-10T10:00:00.000Z' }),
      buildComparisonRows({ name: 'Deep-Transformer', metrics: { rmse: 0.17, mae: 0.13, r2: 0.97 }, inferenceTimeMs: 4, evaluatedAt: '2026-08-21T10:00:00.000Z' }),
    ]
    fetchSpy.mockResolvedValueOnce(okResponse(buildComparisonResult(rows)))

    const result = await loadModelComparison({ sort: 'rmse', direction: 'asc' })

    expect(result.items).toHaveLength(2)
    expect(result.items[0].name).toBe('QEnhanced-LSTM')
    expect(result.items[0].metrics.mae).toBe(0.1)
    expect(result.evaluatedRange.to).toBe('2026-09-10T10:00:00.000Z')
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/ai/models/comparison?sort=rmse&direction=asc',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('rejects with the server error instead of substituting sample rows, whatever the mock flag', async () => {
    vi.stubEnv('VITE_USE_MOCK_DATA', 'true')
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({ success: false, error: { code: 'SERVICE_UNAVAILABLE', message: 'registry down' } }),
    } as unknown as Response)

    await expect(loadModelComparison({})).rejects.toMatchObject({
      code: 'SERVICE_UNAVAILABLE',
      message: 'registry down',
    })
  })
})