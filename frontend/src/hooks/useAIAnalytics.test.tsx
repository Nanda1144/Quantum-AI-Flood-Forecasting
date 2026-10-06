/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These tests verify the useAIAnalytics hook state transitions
 * (loading → data / error) against a mocked service boundary. No test claims a
 * production prediction accuracy.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useAIAnalytics } from './useAIAnalytics'
import { buildSnapshot } from '../test/fixtures'

vi.mock('../services/aiService', () => ({
  loadAIAnalytics: vi.fn(),
}))

import { loadAIAnalytics } from '../services/aiService'

const loadSpy = vi.mocked(loadAIAnalytics)

describe('useAIAnalytics', () => {
  beforeEach(() => {
    loadSpy.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('starts loading and resolves to the backend snapshot', async () => {
    loadSpy.mockResolvedValueOnce({ snapshot: buildSnapshot(), isMock: false })

    const { result } = renderHook(() => useAIAnalytics())

    expect(result.current.loading).toBe(true)

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.snapshot).not.toBeNull()
    expect(result.current.error).toBeNull()
    expect(result.current.stale).toBe(false)
  })

  it('records an error message and clears loading when the request fails', async () => {
    loadSpy.mockRejectedValueOnce(new Error('boom'))

    const { result } = renderHook(() => useAIAnalytics())

    await waitFor(() => expect(result.current.error).toBe('boom'))
    expect(result.current.loading).toBe(false)
    expect(result.current.snapshot).toBeNull()
  })

  it('marks data as stale without dropping the snapshot', async () => {
    loadSpy.mockResolvedValueOnce({ snapshot: buildSnapshot(), isMock: false })

    const { result } = renderHook(() => useAIAnalytics())

    await waitFor(() => expect(result.current.snapshot).not.toBeNull())

    result.current.markStale()
    await waitFor(() => expect(result.current.stale).toBe(true))
    expect(result.current.snapshot).not.toBeNull()
  })

  it('refetch reloads from the service', async () => {
    loadSpy.mockResolvedValueOnce({ snapshot: buildSnapshot(), isMock: false })

    const { result } = renderHook(() => useAIAnalytics())
    await waitFor(() => expect(result.current.snapshot).not.toBeNull())

    loadSpy.mockResolvedValueOnce({ snapshot: buildSnapshot(), isMock: false })
    result.current.refetch(true)

    await waitFor(() => expect(loadSpy).toHaveBeenCalledTimes(2))
    expect(result.current.loading).toBe(false)
  })
})