/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: Verifies the per-section empty states render honest messages instead
 * of empty charts or tables when the backend returns no series/predictions.
 */

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ForecastSection } from './ForecastSection'
import { PredictionsTable } from './PredictionsTable'
import { RiskAnalyticsSection } from './RiskAnalyticsSection'
import { buildRiskAnalytics } from '../../test/fixtures'

describe('empty states', () => {
  it('ForecastSection shows an empty state instead of a bare chart', () => {
    render(<ForecastSection data={[]} threshold={8.0} thresholdLabel="Flood stage reference" />)
    expect(screen.getByText('No forecast series data')).toBeInTheDocument()
  })

  it('PredictionsTable shows an empty state instead of a bare table', () => {
    render(<PredictionsTable predictions={[]} />)
    expect(screen.getByText('No recent predictions')).toBeInTheDocument()
  })

  it('RiskAnalyticsSection shows an empty state when all series are empty', () => {
    render(
      <RiskAnalyticsSection
        analytics={buildRiskAnalytics({
          riskTrend: [],
          probabilityTrend: [],
          distribution: [],
        })}
      />,
    )
    expect(screen.getByText('No risk analytics data')).toBeInTheDocument()
  })
})