/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These are component tests over the AI Analytics dashboard UI states
 * (loading, data, error, empty, stale, unavailable, retry). They exercise the
 * page with mocked hook state — no production prediction is claimed.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AIAnalyticsDashboard } from './AIAnalyticsDashboard'
import type { AISnapshot } from '../types/ai'
import { buildSnapshot, buildSystemHealth } from '../test/fixtures'

const refetchMock = vi.fn()
const markStaleMock = vi.fn()

let mockHookState: {
  snapshot: AISnapshot | null
  isMock: boolean
  loading: boolean
  error: string | null
  stale: boolean
}

vi.mock('../hooks/useAIAnalytics', () => ({
  useAIAnalytics: () => ({
    ...mockHookState,
    refetch: refetchMock,
    markStale: markStaleMock,
  }),
}))

function renderPage() {
  return render(
    <MemoryRouter>
      <AIAnalyticsDashboard />
    </MemoryRouter>,
  )
}

describe('AIAnalyticsDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockHookState = { snapshot: null, isMock: false, loading: true, error: null, stale: false }
  })

  it('shows the loading skeleton while loading', () => {
    renderPage()
    expect(screen.getByRole('status', { name: 'Loading AI analytics' })).toBeInTheDocument()
  })

  it('renders the full dashboard from a backend snapshot', () => {
    mockHookState = { snapshot: buildSnapshot(), isMock: false, loading: false, error: null, stale: false }
    renderPage()

    expect(screen.getByRole('heading', { name: 'AI Analytics' })).toBeInTheDocument()
    expect(screen.getByText('Flood Probability')).toBeInTheDocument()
    expect(screen.getByText('Forecast Time-Series')).toBeInTheDocument()
    expect(screen.getByText('Recent Predictions')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows the unavailable banner and retries when the AI service is degraded', () => {
    mockHookState = {
      snapshot: buildSnapshot({ systemHealth: buildSystemHealth({ status: 'degraded', apiLatencyMs: null }) }),
      isMock: false,
      loading: false,
      error: null,
      stale: false,
    }
    renderPage()

    expect(screen.getByRole('alert')).toHaveTextContent('AI service is unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(refetchMock).toHaveBeenCalledWith(true)
  })

  it('shows the demo banner when serving clearly-flagged sample data', () => {
    mockHookState = { snapshot: buildSnapshot(), isMock: true, loading: false, error: null, stale: false }
    renderPage()

    expect(screen.getByRole('alert')).toHaveTextContent('Sample Data Mode')
  })

  it('shows the error banner and prompts retry', () => {
    mockHookState = { snapshot: null, isMock: false, loading: false, error: 'Server exploded', stale: false }
    renderPage()

    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load AI analytics')
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(refetchMock).toHaveBeenCalledWith(true)
  })

  it('shows the empty state when the load returns nothing', () => {
    mockHookState = { snapshot: null, isMock: false, loading: false, error: null, stale: false }
    renderPage()

    expect(screen.getByRole('alert')).toHaveTextContent('No analytics data available')
  })

  it('shows the stale warning over existing data and retries', () => {
    mockHookState = { snapshot: buildSnapshot(), isMock: false, loading: false, error: null, stale: true }
    renderPage()

    expect(screen.getByRole('alert')).toHaveTextContent('Data may be outdated')
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(refetchMock).toHaveBeenCalledWith(true)
  })
})