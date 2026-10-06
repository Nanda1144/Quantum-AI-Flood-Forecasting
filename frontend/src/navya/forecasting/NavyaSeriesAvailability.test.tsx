/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Rainfall and inflow panel tests.
 *
 * The required graphs for rainfall and inflow cannot be drawn: neither has a
 * data source in the contract. The tests pin the honest absence — stated aloud
 * with a reason, never replaced with an invented curve — and the one case where
 * a number may legitimately appear: a record that actually carries a
 * `predictedInflow`.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { realForecastRecord } from './fixtures'
import { NavyaSeriesAvailability } from './NavyaSeriesAvailability'

describe('NavyaSeriesAvailability', () => {
  it('states that no rainfall series exists', () => {
    render(<NavyaSeriesAvailability forecast={realForecastRecord()} />)
    expect(screen.getByText('Rainfall & inflow')).toBeInTheDocument()
    expect(screen.getByText('Rainfall')).toBeInTheDocument()
    expect(screen.getByText(/No rainfall series is carried by the forecast contract/)).toBeInTheDocument()
  })

  it('distinguishes a rainfall feature name from a rainfall measurement', () => {
    const { container } = render(<NavyaSeriesAvailability forecast={realForecastRecord()} />)
    const text = container.textContent ?? ''
    // The fixture feature list contains 'rainfall_24h'; the panel must not present it as data.
    expect(text).toContain('input feature name')
    expect(text).toContain('not a measurement')
  })

  it('states that no inflow series exists when predictedInflow is null', () => {
    render(<NavyaSeriesAvailability forecast={realForecastRecord()} />)
    expect(screen.getByText('Inflow')).toBeInTheDocument()
    expect(screen.getByText(/no inflow prediction or series/)).toBeInTheDocument()
  })

  it('renders an inflow value only when the record actually carries one', () => {
    const forecast = realForecastRecord({ predictedInflow: 12.5 })
    render(<NavyaSeriesAvailability forecast={forecast} />)
    expect(screen.getByText('12.500 m')).toBeInTheDocument()
  })

  it('repeats the observed-versus-predicted distinction next to the panels', () => {
    const { container } = render(<NavyaSeriesAvailability forecast={realForecastRecord()} />)
    const text = container.textContent ?? ''
    // The words are split across <strong> elements, so the parent's text content
    // is the only reliable place to look for the full sentence.
    expect(text).toMatch(/observed[\s\S]*historical/)
    expect(text).toMatch(/predicted[\s\S]*model output/)
  })

  it('never introduces classification vocabulary', () => {
    const { container } = render(<NavyaSeriesAvailability forecast={realForecastRecord()} />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/accuracy/i)
    expect(text).not.toMatch(/precision/i)
    expect(text).not.toMatch(/recall/i)
  })
})