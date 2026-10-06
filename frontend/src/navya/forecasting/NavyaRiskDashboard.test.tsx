/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Risk dashboard render tests (F5).
 *
 * Composes the whole dashboard and pins the risk section: the risk score and
 * risk level from the record, the exceedance probability labelled with its real
 * meaning, and the exposure/response statuses shown as statuses — `NOT_EVALUABLE`
 * with no value — for both real and synthetic records.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { honestComparison, realForecastRecord, syntheticForecastRecord } from './fixtures'
import { NavyaForecastDashboard } from './NavyaForecastDashboard'

describe('risk dashboard', () => {
  it('renders the risk score from the record, not computed', () => {
    render(<NavyaForecastDashboard forecast={realForecastRecord()} comparison={honestComparison()} />)
    expect(screen.getByText('Risk score')).toBeInTheDocument()
    expect(screen.getByText('0.90')).toBeInTheDocument()
  })

  it('renders the risk level from the record', () => {
    render(<NavyaForecastDashboard forecast={realForecastRecord()} comparison={null} />)
    expect(screen.getAllByText('CRITICAL').length).toBeGreaterThan(0)
  })

  it('renders the exceedance probability and its real meaning', () => {
    render(<NavyaForecastDashboard forecast={realForecastRecord()} comparison={null} />)
    expect(screen.getByText('Exceedance probability')).toBeInTheDocument()
    expect(screen.getAllByText('90.0%').length).toBeGreaterThan(0)
    expect(screen.getByText(/probability that the predicted target exceeds the configured threshold/)).toBeInTheDocument()
  })

  it('shows population and infrastructure exposure as NOT_EVALUABLE with no value', () => {
    render(<NavyaForecastDashboard forecast={realForecastRecord()} comparison={null} />)
    expect(screen.getByText('Population exposure')).toBeInTheDocument()
    expect(screen.getByText('Infrastructure exposure')).toBeInTheDocument()
    // Three status badges: population, infrastructure and response priority.
    expect(screen.getAllByText('NOT_EVALUABLE').length).toBe(3)
  })

  it('shows the Q-FLARE response priority as NOT_EVALUABLE, never a score', () => {
    render(<NavyaForecastDashboard forecast={realForecastRecord()} comparison={null} />)
    expect(screen.getByText('Q-FLARE response priority')).toBeInTheDocument()
    expect(screen.getByText(/No response-priority contract reaches the frontend/)).toBeInTheDocument()
  })

  it('refuses to invent exposure numbers for a synthetic record too', () => {
    render(<NavyaForecastDashboard forecast={syntheticForecastRecord()} comparison={null} />)
    expect(screen.getAllByText('NOT_EVALUABLE').length).toBe(3)
  })
})