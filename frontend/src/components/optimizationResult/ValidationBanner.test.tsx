/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: Coverage for the most important element on the Optimization Result
 * page — the explicit operational verdict. The three states are pinned down so
 * an infeasible solution is never rendered (or mistakable for) a recommendation.
 */

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ValidationBanner } from './ValidationBanner'

describe('ValidationBanner', () => {
  it('renders VALIDATION PENDING while no verdict has been produced', () => {
    render(<ValidationBanner validationStatus={null} validationSummary={null} violationCount={0} />)
    expect(screen.getByText('VALIDATION PENDING')).toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('renders the validated verdict for a valid result with zero violations', () => {
    render(
      <ValidationBanner
        validationStatus="valid"
        validationSummary="QUBO constraints satisfied by the selected solution."
        violationCount={0}
      />,
    )
    expect(screen.getByText('VALIDATED OPTIMIZATION RESULT')).toBeInTheDocument()
    expect(screen.getByText(/QUBO constraints satisfied by the selected solution\./)).toBeInTheDocument()
  })

  it('falls back to the recorded validator detail when no summary text is stored', () => {
    render(<ValidationBanner validationStatus="valid" validationSummary={null} violationCount={0} />)
    expect(screen.getByText(/Constraint validation passed for the decoded selection\./)).toBeInTheDocument()
  })

  it('shows the critical banner for a result the validator did not pass', () => {
    render(
      <ValidationBanner
        validationStatus="invalid"
        validationSummary="Sensor budget exceeded the configured limit of 3."
        violationCount={1}
      />,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('INVALID SOLUTION — NOT OPERATIONALLY RECOMMENDED')).toBeInTheDocument()
    expect(
      screen.getByText(/This result is shown for transparency only and must not be treated as a deployment recommendation\./),
    ).toBeInTheDocument()
  })

  it('never recommends when validation passed but violations were recorded (defence in depth)', () => {
    render(
      <ValidationBanner
        validationStatus="valid"
        validationSummary={null}
        violationCount={2}
      />,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('INVALID SOLUTION — NOT OPERATIONALLY RECOMMENDED')).toBeInTheDocument()
  })
})