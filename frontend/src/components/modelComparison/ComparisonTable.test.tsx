/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These are component tests over the comparison table. The table only
 * renders registry-stored values (including the dataset provenance column) and
 * never derives metrics of its own.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ComparisonTable } from './ComparisonTable'
import { buildComparisonRows } from '../../test/fixtures'
import type { ModelComparisonRow } from '../../types/ai'

const ROWS: ModelComparisonRow[] = [
  buildComparisonRows({
    name: 'QEnhanced-LSTM',
    modelId: '1',
    version: 'v1.1-dev',
    status: 'development',
    metrics: { rmse: 0.14, mae: 0.1, r2: 0.97 },
    trainingTimeMs: 5400000,
    inferenceTimeMs: 10,
    evaluatedAt: '2026-09-10T10:00:00.000Z',
  }),
  buildComparisonRows({
    name: 'Unscored',
    modelId: '2',
    metrics: {},
    evaluatedAt: '',
  }),
]

const onSelectModel = vi.fn()
const onSort = vi.fn()

function renderTable() {
  return render(
    <ComparisonTable
      rows={ROWS}
      sort="evaluatedAt"
      direction="desc"
      selectedModelId={null}
      onSelectModel={onSelectModel}
      onSort={onSort}
    />,
  )
}

describe('ComparisonTable', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders every registry column including dataset provenance', () => {
    renderTable()

    const headers = screen.getAllByRole('columnheader').map((cell) => cell.textContent)
    expect(headers).toContain('Model')
    expect(headers).toContain('Version')
    expect(headers).toContain('Dataset')
    expect(headers).toContain('Algorithm')
    expect(headers).toContain('MAE')
    expect(headers).toContain('RMSE')
    expect(headers).toContain('R²')
    expect(headers).toContain('Training Time')
    expect(headers).toContain('Inference')
    expect(headers).toContain('Status')
    expect(headers).toContain('Evaluated At')

    expect(screen.getByText('v1.1-dev')).toBeInTheDocument()
    expect(screen.getAllByText('dev://comparison/training/panama-basin-2026').length).toBeGreaterThan(0)
    expect(screen.getByText('Not evaluated')).toBeInTheDocument()
  })

  it('displays exactly the metric values stored in the registry', () => {
    renderTable()
    expect(screen.getByText('0.100')).toBeInTheDocument() // MAE
    expect(screen.getByText('0.970')).toBeInTheDocument() // R²
  })

  it('sorts via the column header buttons', () => {
    renderTable()
    screen.getByRole('button', { name: 'Sort by RMSE' }).click()
    expect(onSort).toHaveBeenCalledWith('rmse')
  })

  it('marks the active sort column and the Details action', () => {
    renderTable()
    expect(screen.getByRole('columnheader', { name: /Evaluated At/ })).toHaveAttribute('aria-sort', 'descending')
    expect(screen.getAllByRole('button', { name: 'Details' })).toHaveLength(ROWS.length)
  })

  it('shows a placeholder row when the selection is empty', () => {
    render(
      <ComparisonTable
        rows={[]}
        sort="evaluatedAt"
        direction="desc"
        selectedModelId={null}
        onSelectModel={onSelectModel}
        onSort={onSort}
      />,
    )
    expect(screen.getByText('Nothing to compare in the current selection.')).toBeInTheDocument()
  })
})