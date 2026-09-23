/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: Verifies the heatmap renders the backend-served quadratic half
 * exactly as given (no re-mirroring of the lower triangle), exposes cell
 * readouts, windows large matrices, and shows a proper empty state.
 */

import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { QuboMatrixHeatmap } from './QuboMatrixHeatmap'
import { buildQuboFormulation } from '../../test/fixtures'

describe('QuboMatrixHeatmap', () => {
  const { variables, quadratic } = buildQuboFormulation()

  it('renders every cell with a served-coefficient tooltip', () => {
    render(<QuboMatrixHeatmap quadratic={quadratic} variables={variables} />)
    expect(screen.getByTitle(`Q[${variables[0]}, ${variables[1]}] = -0.4`)).toBeInTheDocument()
    expect(screen.getByTitle(`Q[${variables[1]}, ${variables[2]}] = -0.25`)).toBeInTheDocument()
    expect(screen.getByTitle(`Q[${variables[0]}, ${variables[0]}] = 0`)).toBeInTheDocument()
  })

  it('shows the hover readout for the inspected coefficient', () => {
    render(<QuboMatrixHeatmap quadratic={quadratic} variables={variables} />)
    const cell = screen.getByTitle(`Q[${variables[0]}, ${variables[1]}] = -0.4`)
    fireEvent.mouseEnter(cell)
    expect(screen.getByText(`${variables[0]} × ${variables[1]} → -0.4`)).toBeInTheDocument()
  })

  it('windows matrices above the threshold so only visible rows mount', () => {
    const n = 60
    const bigVariables = Array.from({ length: n }, (_, i) => `SIT-${String(i + 1).padStart(3, '0')}`)
    const bigQuadratic = Array.from({ length: n }, (_, r) =>
      Array.from({ length: n }, (_, c) => (r === 0 && c === 1 ? -0.5 : 0)),
    )
    render(<QuboMatrixHeatmap quadratic={bigQuadratic} variables={bigVariables} />)

    expect(screen.getByText(`${n} × ${n} quadratic · upper-triangle convention · variables as row/column labels`)).toBeInTheDocument()
    const cells = screen.getAllByTitle(/^Q\[/)
    expect(cells.length).toBeGreaterThan(0)
    expect(cells.length).toBeLessThan(n * n)
  })

  it('shows an empty state when no quadratic coefficients are served', () => {
    render(<QuboMatrixHeatmap quadratic={null} variables={[]} />)
    expect(screen.getByText('No stored quadratic coefficients to display.')).toBeInTheDocument()
  })
})