/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Page tests: the routed host of the dashboard.
 *
 * The page owns `useNavyaForecast`, so these tests mock the *service* — the
 * last real line before the network — not the record. The loading, error and
 * loaded states are each asserted, and the loaded state proves the selection
 * scope receives the record's station reference.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { NavyaForecastRecord } from './types'
import { realForecastRecord } from './fixtures'

const mocks = vi.hoisted(() => ({
  loadNavyaForecast: vi.fn(),
  loadNavyaComparison: vi.fn(),
}))

vi.mock('./navyaForecastService', () => ({
  loadNavyaForecast: mocks.loadNavyaForecast,
  loadNavyaComparison: mocks.loadNavyaComparison,
}))

import { NavyaForecastPage } from './NavyaForecastPage'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/forecast']}>
      <Routes>
        <Route path="/forecast" element={<NavyaForecastPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mocks.loadNavyaForecast.mockReset()
  mocks.loadNavyaForecast.mockResolvedValue(realForecastRecord())
  mocks.loadNavyaComparison.mockReset()
  mocks.loadNavyaComparison.mockResolvedValue(null)
})

describe('NavyaForecastPage', () => {
  it('shows a skeleton while the forecast is loading', async () => {
    let resolveLoad!: (value: NavyaForecastRecord) => void
    mocks.loadNavyaForecast.mockImplementation(
      () => new Promise<NavyaForecastRecord>((resolve) => {
        resolveLoad = resolve
      }),
    )
    renderPage()
    expect(screen.getByTestId('navya-forecast-loading')).toBeInTheDocument()
    resolveLoad(realForecastRecord())
    expect(await screen.findByTestId('navya-forecast-dashboard')).toBeInTheDocument()
  })

  it('renders the scope and the dashboard once the forecast loads', async () => {
    mocks.loadNavyaForecast.mockResolvedValue(realForecastRecord())
    renderPage()
    expect(await screen.findByTestId('navya-forecast-dashboard')).toBeInTheDocument()
    // The scope derives the only selectable station from the loaded record.
    expect(screen.getByRole('option', { name: /STN-0001/ })).toBeInTheDocument()
    expect(screen.getByText('No river identity in the contract')).toBeInTheDocument()
  })

  it('renders an honest error state when the forecast fails', async () => {
    mocks.loadNavyaForecast.mockRejectedValue(new Error('upstream 503'))
    renderPage()
    expect(await screen.findByText('Forecast unavailable')).toBeInTheDocument()
    expect(screen.getByText(/upstream 503/)).toBeInTheDocument()
    expect(screen.queryByTestId('navya-forecast-dashboard')).not.toBeInTheDocument()
  })

  it('retries the load from the error state', async () => {
    mocks.loadNavyaForecast.mockRejectedValueOnce(new Error('upstream 503'))
    mocks.loadNavyaForecast.mockResolvedValueOnce(realForecastRecord())
    renderPage()
    await screen.findByText('Forecast unavailable')
    screen.getByRole('button', { name: /retry/i }).click()
    expect(await screen.findByTestId('navya-forecast-dashboard')).toBeInTheDocument()
  })
})