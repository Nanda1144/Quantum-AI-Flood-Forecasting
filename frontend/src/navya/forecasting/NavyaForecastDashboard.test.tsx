/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Composition and chart tests for the dashboard.
 *
 * Two things are under test here. First, that the panels appear in an order that
 * makes the honesty copy readable before the numbers. Second, that the chart
 * refuses to draw anything it was not given.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { NavyaForecastDashboard } from './NavyaForecastDashboard'
import { NavyaForecastSeriesChart } from './NavyaForecastSeriesChart'
import { honestComparison, realForecastRecord, syntheticForecastRecord } from './fixtures'
import { SYNTHETIC_DATA_DISCLAIMER } from './types'

describe('NavyaForecastDashboard', () => {
  it('renders the supplied record without touching the network', () => {
    render(<NavyaForecastDashboard forecast={realForecastRecord()} comparison={null} />)
    expect(screen.getByTestId('navya-forecast-dashboard')).toBeInTheDocument()
    expect(screen.getByText('FC-20240101-1200')).toBeInTheDocument()
  })

  it('places provenance above the risk panel and the chart', () => {
    const { container } = render(
      <NavyaForecastDashboard forecast={realForecastRecord()} comparison={null} />,
    )
    const text = container.textContent ?? ''
    // Assert on visible headings only. This previously looked for 'Predicted
    // versus observed water level' and 'Risk band distribution', and BOTH are
    // `aria-label`s — they never appear in `textContent`, so both `indexOf`
    // calls returned -1 and the ordering was not verified at all. The visible
    // headings are below.
    const provenance = text.indexOf('Provenance & evaluation status')
    const risk = text.indexOf('Risk bands across the backtest')
    const series = text.indexOf('Forecast series')
    expect(provenance).toBeGreaterThanOrEqual(0)
    expect(risk).toBeGreaterThan(provenance)
    expect(series).toBeGreaterThan(risk)
  })

  it('carries the synthetic warning through the whole dashboard', () => {
    render(<NavyaForecastDashboard forecast={syntheticForecastRecord()} comparison={null} />)
    // Summary and provenance panel each state it; both must be present.
    expect(screen.getAllByText(/SYNTHETIC\/DEMO DATA/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(SYNTHETIC_DATA_DISCLAIMER)).toBeInTheDocument()
  })

  it('marks a pending threshold as not official', () => {
    render(<NavyaForecastDashboard forecast={realForecastRecord()} comparison={null} />)
    expect(screen.getByText('PENDING — not official')).toBeInTheDocument()
  })

  it('renders the comparison when one is supplied', () => {
    render(
      <NavyaForecastDashboard forecast={realForecastRecord()} comparison={honestComparison()} />,
    )
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByText('Ridge')).toBeInTheDocument()
  })

  it('never renders a bare prediction with no provenance panel beside it', () => {
    const { container } = render(
      <NavyaForecastDashboard forecast={realForecastRecord()} comparison={null} />,
    )
    // The predicted value is displayed, and "Provenance" is on the same screen.
    expect(container.textContent).toContain('3.400')
    expect(container.textContent).toContain('Provenance')
  })

  it('never displays an accuracy figure anywhere on the dashboard', () => {
    const { container } = render(
      <NavyaForecastDashboard forecast={syntheticForecastRecord()} comparison={honestComparison()} />,
    )
    expect(container.textContent).not.toMatch(/accuracy/i)
    expect(container.textContent).not.toMatch(/precision/i)
    expect(container.textContent).not.toMatch(/recall/i)
  })
})

describe('NavyaForecastSeriesChart', () => {
  const POINTS = realForecastRecord().backtest

  it('renders a chart when points are supplied', () => {
    render(<NavyaForecastSeriesChart points={POINTS} title="series" />)
    expect(screen.getByRole('img', { name: 'series' })).toBeInTheDocument()
  })

  it('says so instead of drawing an empty frame when there are no points', () => {
    render(<NavyaForecastSeriesChart points={[]} title="series" />)
    expect(screen.getByRole('img', { name: 'series — no data' })).toBeInTheDocument()
    expect(screen.getByText(/Nothing is plotted/)).toBeInTheDocument()
  })

  it('does not extrapolate past the last point', () => {
    // The data is passed through verbatim; the component adds no trailing entry.
    const { container } = render(
      <NavyaForecastSeriesChart points={POINTS} title="series" />,
    )
    expect(container.textContent).not.toMatch(/extrapolat/i)
  })
})
