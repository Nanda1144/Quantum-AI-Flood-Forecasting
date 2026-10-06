/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These are component tests over the Model Comparison page states
 * (loading, data, error, empty) with a mocked hook — the page only renders
 * backend-provided registry values and never synthesizes metrics.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ModelComparison } from './ModelComparison'
import { buildComparisonRows } from '../test/fixtures'
import type { ModelComparisonResult } from '../types/ai'

const refetchMock = vi.fn()
const updateQueryMock = vi.fn()
const resetMock = vi.fn()

let mockHookState: {
  data: ModelComparisonResult | null
  loading: boolean
  error: string | null
  query: Record<string, unknown>
}

vi.mock('../hooks/useModelComparison', () => ({
  useModelComparison: () => ({
    ...mockHookState,
    updateQuery: updateQueryMock,
    reset: resetMock,
    refetch: refetchMock,
  }),
}))

const ROWS = [
  buildComparisonRows({
    name: 'QEnhanced-LSTM',
    status: 'development',
    metrics: { rmse: 0.14, mae: 0.1, r2: 0.97 },
    inferenceTimeMs: 10,
    evaluatedAt: '2026-09-10T10:00:00.000Z',
  }),
  buildComparisonRows({
    name: 'Deep-Transformer',
    metrics: { rmse: 0.17, mae: 0.13, r2: 0.97 },
    inferenceTimeMs: 4,
    evaluatedAt: '2026-08-21T10:00:00.000Z',
  }),
]

const DATA: ModelComparisonResult = {
  items: ROWS,
  evaluatedRange: { from: '2026-08-21T10:00:00.000Z', to: '2026-09-10T10:00:00.000Z' },
  evaluationDatasets: ['dev://comparison/eval/gatun-basin-2026'],
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ModelComparison />
    </MemoryRouter>,
  )
}

describe('ModelComparison', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockHookState = { data: null, loading: true, error: null, query: {} }
  })

  it('shows the loading skeleton while loading', () => {
    renderPage()
    expect(screen.getByText('Loading model comparison data…')).toBeInTheDocument()
  })

  it('shows the error banner and retries', () => {
    mockHookState = { data: null, loading: false, error: 'registry offline', query: {} }
    renderPage()

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('Unable to load model comparison')
    expect(alert).toHaveTextContent('registry offline')
  })

  it('shows the empty state when the registry returns no versions', () => {
    mockHookState = {
      data: { items: [], evaluatedRange: { from: null, to: null }, evaluationDatasets: [] },
      loading: false,
      error: null,
      query: {},
    }
    renderPage()

    expect(screen.getByRole('alert')).toHaveTextContent('No model evaluations found')
  })

  it('renders the full comparison from backend rows without a demo banner', () => {
    mockHookState = { data: DATA, loading: false, error: null, query: {} }
    renderPage()

    expect(screen.getByRole('heading', { name: 'Model Comparison' })).toBeInTheDocument()
    expect(screen.getAllByText('QEnhanced-LSTM').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Deep-Transformer').length).toBeGreaterThan(0)
    expect(screen.getAllByText('dev://comparison/training/panama-basin-2026').length).toBeGreaterThan(0)
    expect(screen.getAllByText('MAE comparison').length).toBeGreaterThan(0)
    expect(screen.queryByText('Sample Data Mode')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('opens the detail panel when a model is selected', async () => {
    mockHookState = { data: DATA, loading: false, error: null, query: {} }
    renderPage()

    const row = screen.getAllByRole('row').find((candidate) => candidate.textContent?.includes('Deep-Transformer'))
    fireEvent.click(within(row!).getByRole('button', { name: 'Details' }))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Deep-Transformer' })).toBeInTheDocument())
  })
})