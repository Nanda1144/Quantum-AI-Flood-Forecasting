/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Rendering tests for the model-comparison table.
 *
 * The table's job is to show *why* each score is or is not a result. So the tests
 * are about refusal: a candidate that did not run must say so, a comparison that
 * ranked on the test split must not render at all, and the table must never
 * compute a score of its own.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { NavyaModelComparison } from './NavyaModelComparison'
import { executedRowWithNoScore, executedWithNoSelection, honestComparison, testSplitRanking } from './fixtures'
import { HUMAN_INPUT_REQUIRED } from './types'

describe('NavyaModelComparison', () => {
  it('states the ranking split in the heading', () => {
    render(<NavyaModelComparison comparison={honestComparison()} />)
    expect(screen.getByText(/ranked on the validation split by rmse/)).toBeInTheDocument()
  })

  it('warns that ranking-split scores are optimistic, not held out', () => {
    render(<NavyaModelComparison comparison={honestComparison()} />)
    expect(screen.getByText(/optimistic by construction/i)).toBeInTheDocument()
  })

  it('renders the comparison label', () => {
    render(<NavyaModelComparison comparison={honestComparison()} />)
    expect(screen.getAllByText('measured evaluation').length).toBeGreaterThan(0)
  })

  it('marks the selected row', () => {
    const { container } = render(<NavyaModelComparison comparison={honestComparison()} />)
    expect(screen.getByText('SELECTED')).toBeInTheDocument()
    expect(container.querySelector('[data-selected="true"]')).not.toBeNull()
  })

  it('gives the real reason an unexecuted candidate has no score', () => {
    render(<NavyaModelComparison comparison={honestComparison()} />)
    expect(screen.getByText(/xgboost\.XGBRegressor is not installed/)).toBeInTheDocument()
    expect(screen.getByText(/no rmse recorded/)).toBeInTheDocument()
  })

  it('counts executed against total candidates', () => {
    render(<NavyaModelComparison comparison={honestComparison()} />)
    expect(screen.getByText(/1 of 2 candidates executed/)).toBeInTheDocument()
  })

  it('throws rather than rendering a comparison that ranked on the test split', () => {
    expect(() => render(<NavyaModelComparison comparison={testSplitRanking()} />)).toThrow(
      /test split/,
    )
  })

  it('throws on an executed row carrying no score', () => {
    expect(() => render(<NavyaModelComparison comparison={executedRowWithNoScore()} />)).toThrow(
      /carries no score/,
    )
  })

  it('throws when executed candidates have no selection', () => {
    expect(() => render(<NavyaModelComparison comparison={executedWithNoSelection()} />)).toThrow(
      /no selected model/,
    )
  })

  it('renders no table when there is no comparison at all', () => {
    render(<NavyaModelComparison comparison={null} />)
    // Substring match, not exact. The note reads "No model comparison is
    // available. NOT FOUND IN REPOSITORY — …", so an exact-string query for
    // the bare marker can never match the element that carries it. What matters
    // is that the convention marker is on screen — not that it stands alone.
    expect(screen.getByText(HUMAN_INPUT_REQUIRED, { exact: false })).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('reports a comparison failure without inventing a table', () => {
    render(<NavyaModelComparison comparison={null} error="upstream 503" />)
    expect(screen.getByText(/upstream 503/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('says when the held-out split has not been scored', () => {
    render(<NavyaModelComparison comparison={honestComparison({ heldOutScored: false })} />)
    expect(screen.getByText(/has not been scored/)).toBeInTheDocument()
  })

  it('renders an empty candidate list without a ranking', () => {
    render(<NavyaModelComparison comparison={honestComparison({ rows: [] })} />)
    expect(screen.getByText(/carries no candidates/)).toBeInTheDocument()
  })

  it('renders a dash, not a zero, for a missing score', () => {
    const { container } = render(<NavyaModelComparison comparison={honestComparison()} />)
    expect(container.textContent).not.toContain('0.0000')
  })

  it('never displays an accuracy figure for a regression model', () => {
    const { container } = render(<NavyaModelComparison comparison={honestComparison()} />)
    expect(container.textContent).not.toMatch(/accuracy/i)
    expect(container.textContent).not.toMatch(/\bF1\b/)
  })
})
