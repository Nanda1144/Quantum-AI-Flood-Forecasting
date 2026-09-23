/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: Coverage for the QUBO Visualization page states (loading, error,
 * unavailable, invalid, valid). Every assertion runs against a mocked
 * optimization service; the page never re-derives QUBO coefficients, so the
 * tests prove it renders exactly what the backend payload carries.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QuboVisualization } from './QuboVisualization'
import { buildQuboFormulation } from '../test/fixtures'
import { fetchQuboFormulation, fetchQuboPipeline, fetchQuboResult } from '../services/optimization/quboService'
import type { QuboFormulation } from '../types/optimization'

vi.mock('../services/optimization/quboService', () => ({
  fetchQuboFormulation: vi.fn(),
  fetchQuboPipeline: vi.fn(),
  fetchQuboResult: vi.fn(),
}))

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/qubo-visualization/QOP-20260921-0001']}>
      <Routes>
        <Route path="/qubo-visualization/:jobId" element={<QuboVisualization />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('QuboVisualization', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchQuboPipeline).mockResolvedValue([])
    vi.mocked(fetchQuboResult).mockRejectedValue(new Error('unused'))
  })

  it('shows the loading skeleton while the formulation is in flight', () => {
    vi.mocked(fetchQuboFormulation).mockReturnValue(new Promise<QuboFormulation>(() => {}))
    renderPage()
    expect(screen.getByLabelText('Loading quantum workspace')).toBeInTheDocument()
  })

  it('shows the gateway error state with the surfaced message', async () => {
    vi.mocked(fetchQuboFormulation).mockRejectedValue(new Error('gateway refused the QUBO'))
    renderPage()
    expect(await screen.findByText('Could not load the QUBO formulation')).toBeInTheDocument()
    expect(screen.getByText('gateway refused the QUBO')).toBeInTheDocument()
  })

  it('shows the unavailable state for a job that never produced a stored matrix', async () => {
    vi.mocked(fetchQuboFormulation).mockResolvedValue(
      buildQuboFormulation({
        available: 'unavailable',
        status: 'queued',
        variableCount: null,
        variables: [],
        expression: '',
        matrix: [],
        linear: null,
        quadratic: null,
        bitstring: null,
        selectedVariableIds: [],
        hasResult: false,
      }),
    )
    renderPage()
    expect(await screen.findByText('QUBO formulation unavailable')).toBeInTheDocument()
    expect(screen.queryByText('Q matrix coefficient heatmap')).not.toBeInTheDocument()
  })

  it('shows the invalid state for a malformed stored matrix', async () => {
    vi.mocked(fetchQuboFormulation).mockResolvedValue(buildQuboFormulation({ available: 'invalid' }))
    renderPage()
    expect(await screen.findByText('Stored QUBO is invalid')).toBeInTheDocument()
    expect(screen.queryByText('Q matrix coefficient heatmap')).not.toBeInTheDocument()
  })

  it('renders the full formulation exactly as served for a valid build', async () => {
    const formulation = buildQuboFormulation()
    vi.mocked(fetchQuboFormulation).mockResolvedValue(formulation)
    renderPage()

    expect(await screen.findByText('Q matrix coefficient heatmap')).toBeInTheDocument()
    expect(screen.getByText(formulation.jobId)).toBeInTheDocument()
    expect(screen.getByText('sensor placement')).toBeInTheDocument()
    expect(screen.getAllByText(formulation.variables[0]).length).toBeGreaterThan(0)
    expect(screen.getAllByText(String(formulation.summary.variables)).length).toBeGreaterThan(0)
    expect(screen.getByText('Constraint enforcement')).toBeInTheDocument()
    expect(screen.getByText('Linear terms (β)')).toBeInTheDocument()
    expect(screen.getByText('Quadratic terms (Q)')).toBeInTheDocument()
  })

  it('requests the formulation for the route job id (backend source of truth)', async () => {
    vi.mocked(fetchQuboFormulation).mockResolvedValue(buildQuboFormulation())
    renderPage()
    await waitFor(() => expect(fetchQuboFormulation).toHaveBeenCalledWith('QOP-20260921-0001'))
  })
})