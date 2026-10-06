/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These are component tests over the comparison charts. The charts
 * render stored values only (a data-bound label names the best-scoring model)
 * and expose keyboard access to each bar; no metric is computed here.
 */

import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ComparisonCharts } from './ComparisonCharts'
import { buildComparisonRows } from '../../test/fixtures'
import type { ModelComparisonRow } from '../../types/ai'

const ROWS: ModelComparisonRow[] = [
  buildComparisonRows({
    name: 'QEnhanced-LSTM',
    modelId: '1',
    metrics: { rmse: 0.14, mae: 0.1, r2: 0.97 },
    inferenceTimeMs: 10,
  }),
  buildComparisonRows({
    name: 'Deep-Transformer',
    modelId: '2',
    metrics: { rmse: 0.17, mae: 0.13, r2: 0.95 },
    inferenceTimeMs: 4,
  }),
]

const onSelectModel = vi.fn()

function renderCharts() {
  return render(<ComparisonCharts rows={ROWS} selectedModelId={null} onSelectModel={onSelectModel} />)
}

describe('ComparisonCharts', () => {
  it('renders a chart per requested metric', () => {
    renderCharts()
    expect(screen.getByText('MAE comparison')).toBeInTheDocument()
    expect(screen.getByText('RMSE comparison')).toBeInTheDocument()
    expect(screen.getByText('R² comparison')).toBeInTheDocument()
    expect(screen.getByText('Inference-time comparison')).toBeInTheDocument()
    expect(screen.getAllByText('2 of 2 scored')).toHaveLength(4)
  })

  it('labels each chart with the best-scoring model from the stored values', () => {
    renderCharts()
    // MAE: lower is better → Deep-Transformer's 4 ms / QEnhanced-LSTM's 0.10 m.
    const mae = screen.getByRole('img', { name: /MAE comparison chart/ })
    expect(mae).toHaveAccessibleName(/QEnhanced-LSTM.*0\.100/)
  })

  it('keeps the no-data message for a metric the selection does not store', () => {
    render(<ComparisonCharts rows={[{ ...ROWS[0], metrics: {} }]} selectedModelId={null} onSelectModel={onSelectModel} />)
    expect(screen.getByText(/No 'MAE' values stored/)).toBeInTheDocument()
  })

  it('exposes keyboard-activatable bars', () => {
    renderCharts()
    const bars = screen.getAllByRole('button', { name: /^Select / })
    expect(bars.length).toBeGreaterThan(0)
    expect(screen.getAllByRole('img').some((el) => el.getAttribute('aria-label')?.includes('keyboard-accessible'))).toBe(true)
  })

  it('activates a model selection from the keyboard-accessible list', () => {
    renderCharts()
    screen.getAllByRole('button', { name: /Select Deep-Transformer/ })[0].click()
    expect(onSelectModel).toHaveBeenCalledWith('2')
  })
})