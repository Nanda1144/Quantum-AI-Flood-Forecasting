/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Rendering tests for the provenance / evaluation-status panel.
 *
 * The theme: what the screen is REQUIRED to say. Each test pins a piece of
 * honesty copy that must survive a future refactor of the layout.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { NavyaProvenancePanel } from './NavyaProvenancePanel'
import {
  realForecastRecord,
  syntheticForecastRecord,
  trainSplitRecord,
  unknownProvenanceRecord,
  validationSplitRecord,
} from './fixtures'
import {
  INTEGRATION_STATEMENT,
  SYNTHETIC_DATA_DISCLAIMER,
  SYNTHETIC_METRIC_LABEL,
} from './types'

describe('NavyaProvenancePanel', () => {
  it('renders the integration statement verbatim', () => {
    render(<NavyaProvenancePanel forecast={realForecastRecord()} />)
    expect(screen.getByText(INTEGRATION_STATEMENT)).toBeInTheDocument()
  })

  it('shows the synthetic warning verbatim on synthetic data', () => {
    render(<NavyaProvenancePanel forecast={syntheticForecastRecord()} />)
    expect(screen.getByText(SYNTHETIC_DATA_DISCLAIMER)).toBeInTheDocument()
  })

  it('labels synthetic metrics with the canonical phrase', () => {
    render(<NavyaProvenancePanel forecast={syntheticForecastRecord()} />)
    expect(screen.getByText(SYNTHETIC_METRIC_LABEL)).toBeInTheDocument()
  })

  it('shows no data warning for a fully presentable record', () => {
    render(<NavyaProvenancePanel forecast={realForecastRecord()} />)
    expect(screen.queryByText(SYNTHETIC_DATA_DISCLAIMER)).not.toBeInTheDocument()
    expect(screen.queryByText(SYNTHETIC_METRIC_LABEL)).not.toBeInTheDocument()
  })

  it('says the held-out split was scored once, on a presentable record', () => {
    render(<NavyaProvenancePanel forecast={realForecastRecord()} />)
    expect(screen.getByText(/scored exactly once/i)).toBeInTheDocument()
  })

  it('names the split a score was measured on', () => {
    render(<NavyaProvenancePanel forecast={realForecastRecord()} />)
    expect(screen.getByText(/split: test/)).toBeInTheDocument()
  })

  it('refuses a train-split score and says it is a fit statistic', () => {
    render(<NavyaProvenancePanel forecast={trainSplitRecord()} />)
    expect(screen.getByText(/NOT A HELD-OUT RESULT/)).toBeInTheDocument()
    expect(screen.getByText(/train split/)).toBeInTheDocument()
  })

  it('refuses a validation-split score and says it was optimised against', () => {
    render(<NavyaProvenancePanel forecast={validationSplitRecord()} />)
    expect(screen.getByText(/validation split/)).toBeInTheDocument()
  })

  it('never renders a metric when none were measured', () => {
    render(<NavyaProvenancePanel forecast={realForecastRecord({ metrics: null })} />)
    expect(screen.getByText(/No metrics were measured/i)).toBeInTheDocument()
    expect(screen.queryByText('RMSE')).not.toBeInTheDocument()
  })

  it('renders measured metrics with their values when present', () => {
    render(<NavyaProvenancePanel forecast={realForecastRecord()} />)
    expect(screen.getByText('RMSE')).toBeInTheDocument()
    // 0.16 is the fixture value; this asserts transparency, not performance.
    expect(screen.getByText('0.1600')).toBeInTheDocument()
  })

  it('marks an unapproved threshold as pending and not official', () => {
    render(<NavyaProvenancePanel forecast={realForecastRecord()} />)
    expect(screen.getByText(/NOT an official flood stage/)).toBeInTheDocument()
    expect(screen.getByText(/no approved policy/i)).toBeInTheDocument()
  })

  it('never renders the reference engine placeholder 8.0', () => {
    const { container } = render(<NavyaProvenancePanel forecast={realForecastRecord()} />)
    expect(container.textContent).not.toContain('8.0')
  })

  it('records unknown provenance as not recorded rather than omitting it', () => {
    const { container } = render(<NavyaProvenancePanel forecast={unknownProvenanceRecord()} />)
    expect(container.textContent).toContain('not recorded')
  })

  it('lists the unresolved inputs rather than hiding them', () => {
    render(<NavyaProvenancePanel forecast={syntheticForecastRecord()} />)
    expect(screen.getByText('Unresolved inputs')).toBeInTheDocument()
    expect(screen.getByText('dataset reference')).toBeInTheDocument()
  })

  it('omits the unresolved-inputs section when nothing is missing', () => {
    render(<NavyaProvenancePanel forecast={realForecastRecord()} />)
    expect(screen.queryByText('Unresolved inputs')).not.toBeInTheDocument()
  })

  it('says the split is unrecorded when provenance is missing', () => {
    render(
      <NavyaProvenancePanel forecast={realForecastRecord({ metricProvenance: null })} />,
    )
    expect(screen.getByText(/split not recorded/)).toBeInTheDocument()
  })

  it('shortens a long checksum instead of filling the panel', () => {
    const { container } = render(<NavyaProvenancePanel forecast={realForecastRecord()} />)
    expect(container.textContent).toContain('a1b2c3d4e5f60718…')
  })
})
