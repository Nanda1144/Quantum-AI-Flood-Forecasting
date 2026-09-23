/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These are hook tests over the model-comparison loader wiring. The
 * loader is mocked; the hook must manage loading/error/data transitions and
 * query coalescing without inventing metrics.
 */

import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useModelComparison } from './useModelComparison'
import { buildComparisonResult, buildComparisonRows } from '../test/fixtures'

const loadModelComparisonMock = vi.fn()

vi.mock('../services/aiService', () => ({
  loadModelComparison: (...args: unknown[]) => loadModelComparisonMock(...args),
}))

const rows = [
  buildComparisonRows({ name: 'Alpha', metrics: { rmse: 0.5, mae: 0.4, r2: 0.8 }, evaluatedAt: '2026-08-20T10:00:00.000Z' }),
  buildComparisonRows({ name: 'Beta', metrics: { rmse: 0.2, mae: 0.15, r2: 0.95 }, evaluatedAt: '2026-09-01T10:00:00.000Z' }),
]

describe('useModelComparison', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    loadModelComparisonMock.mockResolvedValue(buildComparisonResult(rows))
  })

  it('loads the comparison on mount and exposes the data', async () => {
    const { result } = renderHook(() => useModelComparison())

    expect(result.current.loading).toBe(true)
    expect(result.current.data).toBeNull()

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.error).toBeNull()
    expect(result.current.data?.items).toHaveLength(2)
    expect(loadModelComparisonMock).toHaveBeenCalledWith({})
  })

  it('surfaces the failure message when the load rejects', async () => {
    loadModelComparisonMock.mockRejectedValue(new Error('registry offline'))

    const { result } = renderHook(() => useModelComparison())

    await waitFor(() => expect(result.current.error).toBe('registry offline'))
    expect(result.current.loading).toBe(false)
    expect(result.current.data).toBeNull()
  })

  it('merges query patches and refetches with the combined server-side filter', async () => {
    const { result } = renderHook(() => useModelComparison())

    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => {
      result.current.updateQuery({ sort: 'mae' })
      result.current.updateQuery({ direction: 'asc' })
      result.current.updateQuery({ from: '2026-09-01T00:00:00.000Z' })
    })

    await waitFor(() => expect(loadModelComparisonMock).toHaveBeenLastCalledWith({
      sort: 'mae',
      direction: 'asc',
      from: '2026-09-01T00:00:00.000Z',
    }))
  })

  it('keeps cached rows visible while a refetch is in flight', async () => {
    const { result } = renderHook(() => useModelComparison())

    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => {
      result.current.refetch()
    })

    await waitFor(() => expect(loadModelComparisonMock).toHaveBeenCalledTimes(2))
    expect(result.current.data?.items).toHaveLength(2)
  })

  it('resets the query to defaults', async () => {
    const { result } = renderHook(() => useModelComparison())

    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => {
      result.current.updateQuery({ sort: 'name', status: 'development' })
      result.current.reset()
    })

    await waitFor(() => expect(loadModelComparisonMock).toHaveBeenLastCalledWith({}))
    expect(result.current.query).toEqual({})
  })
})