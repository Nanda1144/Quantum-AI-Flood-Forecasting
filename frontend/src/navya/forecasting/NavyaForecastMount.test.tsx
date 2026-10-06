/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Full-app mount tests for the Navya forecast route.
 *
 * Renders the real `App` shell — auth provider, layout, navigation and routes —
 * with a seeded session and a mocked forecast service. This proves the two
 * integration facts the task asks for: the Navya dashboard is reachable through
 * the application UI at `/forecast`, and the existing navigation entries and
 * routes are untouched.
 */

import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { realForecastRecord } from './fixtures'

const mocks = vi.hoisted(() => ({
  getStoredSession: vi.fn(),
  clearSession: vi.fn(),
  storeSession: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
  apiLogin: vi.fn(),
  loadNavyaForecast: vi.fn(),
  loadNavyaComparison: vi.fn(),
}))

vi.mock('../../services/authService', () => ({
  getStoredSession: mocks.getStoredSession,
  clearSession: mocks.clearSession,
  storeSession: mocks.storeSession,
  setUnauthorizedHandler: mocks.setUnauthorizedHandler,
  apiLogin: mocks.apiLogin,
}))

vi.mock('./navyaForecastService', () => ({
  loadNavyaForecast: mocks.loadNavyaForecast,
  loadNavyaComparison: mocks.loadNavyaComparison,
}))

import { App } from '../../App'

function seedSession() {
  mocks.getStoredSession.mockReturnValue({
    token: 'test-token',
    user: { username: 'navya', role: 'operator' as const },
  })
}

beforeEach(() => {
  seedSession()
  mocks.loadNavyaForecast.mockReset()
  mocks.loadNavyaForecast.mockResolvedValue(realForecastRecord())
  mocks.loadNavyaComparison.mockReset()
  mocks.loadNavyaComparison.mockResolvedValue(null)
  window.history.pushState({}, '', '/forecast')
})

afterEach(() => {
  window.history.pushState({}, '', '/')
})

describe('App integration', () => {
  it('reaches the Navya forecast dashboard at /forecast through the app shell', async () => {
    render(<App />)
    expect(await screen.findByTestId('navya-forecast-dashboard')).toBeInTheDocument()
    expect(screen.getByText('FC-20240101-1200')).toBeInTheDocument()
  })

  it('adds a Forecast navigation entry pointing at /forecast', async () => {
    render(<App />)
    const link = await screen.findByRole('link', { name: 'Forecast' })
    expect(link.getAttribute('href')).toBe('/forecast')
  })

  it('keeps every existing navigation entry', async () => {
    render(<App />)
    await screen.findByTestId('navya-forecast-dashboard')
    const expectations: Array<[string, string]> = [
      ['AI Analytics', '/'],
      ['Model Comparison', '/model-comparison'],
      ['Quantum Optimization', '/quantum-optimization'],
      ['Quantum Benchmark', '/quantum-benchmark'],
    ]
    for (const [name, href] of expectations) {
      const link = screen.getByRole('link', { name })
      expect(link.getAttribute('href')).toBe(href)
    }
  })
})