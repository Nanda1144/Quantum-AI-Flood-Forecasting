/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: Verifies KPI trends are derived from the real forecast series rather
 * than hardcoded, and that model status labels come from the registered model
 * status — no fabricated movement here.
 */

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { KPIRow } from './KPIRow'
import type { AISnapshot } from '../../types/ai'
import { buildRiskAnalytics, buildSnapshot } from '../../test/fixtures'

describe('KPIRow', () => {
  it('labels a falling series as Falling and never Rising', () => {
    const snapshot: AISnapshot = buildSnapshot({
      forecastSeries: [
        { timestamp: 't1', predictedWaterLevel: 8.0, observedWaterLevel: 7.9, floodProbability: 0.8 },
        { timestamp: 't2', predictedWaterLevel: 7.5, observedWaterLevel: 7.6, floodProbability: 0.6 },
        { timestamp: 't3', predictedWaterLevel: 7.0, observedWaterLevel: 7.2, floodProbability: 0.45 },
      ],
      riskAnalytics: buildRiskAnalytics({
        probabilityTrend: [
          { timestamp: 't1', value: 0.8 },
          { timestamp: 't2', value: 0.6 },
          { timestamp: 't3', value: 0.4 },
        ],
      }),
    })

    render(<KPIRow snapshot={snapshot} />)

    expect(screen.getAllByText('Falling').length).toBeGreaterThanOrEqual(2)
    expect(screen.queryByText('Rising')).not.toBeInTheDocument()
  })

  it('labels a rising series as Rising and never Falling', () => {
    const snapshot: AISnapshot = buildSnapshot({
      forecastSeries: [
        { timestamp: 't1', predictedWaterLevel: 6.5, observedWaterLevel: 6.6, floodProbability: 0.4 },
        { timestamp: 't2', predictedWaterLevel: 7.0, observedWaterLevel: 6.9, floodProbability: 0.6 },
        { timestamp: 't3', predictedWaterLevel: 7.6, observedWaterLevel: 7.4, floodProbability: 0.75 },
      ],
      riskAnalytics: buildRiskAnalytics({
        probabilityTrend: [
          { timestamp: 't1', value: 0.4 },
          { timestamp: 't2', value: 0.6 },
          { timestamp: 't3', value: 0.75 },
        ],
      }),
    })

    render(<KPIRow snapshot={snapshot} />)

    expect(screen.getAllByText('Rising').length).toBeGreaterThanOrEqual(2)
    expect(screen.queryByText('Falling')).not.toBeInTheDocument()
  })

  it('shows the real model status instead of a placeholder version-diff', () => {
    const snapshot: AISnapshot = buildSnapshot({
      activeModel: {
        ...buildSnapshot().activeModel!,
        status: 'training',
        version: 'v1.14.0',
      },
    })

    render(<KPIRow snapshot={snapshot} />)

    expect(screen.getByText('Training')).toBeInTheDocument()
    expect(screen.queryByText('v-diff')).not.toBeInTheDocument()
  })
})