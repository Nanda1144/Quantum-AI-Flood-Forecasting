/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: Panel-level coverage for the QUBO visualization building blocks.
 * Each panel renders only what the backend payload serves, including the
 * empty states (no constraints / no coefficients / no variables).
 */

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QuboSummaryCards } from './QuboSummaryCards'
import { QuboObjectivePanel } from './QuboObjectivePanel'
import { QuboConstraintPanel } from './QuboConstraintPanel'
import { QuboVariablePanel } from './QuboVariablePanel'
import { QuboTermPanels } from './QuboTermPanels'
import { buildQuboFormulation } from '../../test/fixtures'

describe('QuboSummaryCards', () => {
  it('renders served summary metrics per card', () => {
    const { summary } = buildQuboFormulation()
    render(<QuboSummaryCards summary={summary} />)
    expect(screen.getByText('Variables')).toBeInTheDocument()
    expect(screen.getByText('Linear terms')).toBeInTheDocument()
    expect(screen.getByText('Quadratic terms')).toBeInTheDocument()
    expect(screen.getByText('Penalty strength (P)')).toBeInTheDocument()
    expect(screen.getAllByText(String(summary.variables)).length).toBeGreaterThan(0)
    expect(screen.getByText(String(summary.quadraticTerms))).toBeInTheDocument()
  })

  it('renders a dash for absent metric values', () => {
    render(
      <QuboSummaryCards
        summary={{ variables: null, linearTerms: null, quadraticTerms: null, constraints: null, penaltyStrength: null }}
      />,
    )
    expect(screen.getAllByText('—').length).toBe(5)
  })
})

describe('QuboObjectivePanel', () => {
  it('renders the served objective expression and explanation', () => {
    const { objective } = buildQuboFormulation()
    render(<QuboObjectivePanel objective={objective} />)
    expect(screen.getByText(`Objective · ${objective.target}`)).toBeInTheDocument()
    expect(screen.getByText(objective.expression)).toBeInTheDocument()
    expect(screen.getByText(objective.explanation)).toBeInTheDocument()
  })
})

describe('QuboConstraintPanel', () => {
  it('renders constraint rows served by the backend', () => {
    const formulation = buildQuboFormulation()
    render(<QuboConstraintPanel constraints={formulation.constraints} penaltyScale={4.0} />)
    expect(screen.getByText('Constraint enforcement')).toBeInTheDocument()
    expect(screen.getByText('Sensor budget')).toBeInTheDocument()
    expect(screen.getByText(/P = 4/)).toBeInTheDocument()
    expect(screen.getByText('satisfied')).toBeInTheDocument()
  })

  it('shows the empty state when no constraints were configured', () => {
    render(<QuboConstraintPanel constraints={[]} penaltyScale={null} />)
    expect(screen.getByText('No operator constraints were configured for this run.')).toBeInTheDocument()
  })
})

describe('QuboVariablePanel', () => {
  it('renders variable detail rows with selection flags', () => {
    const { variablesDetail } = buildQuboFormulation()
    render(<QuboVariablePanel variablesDetail={variablesDetail} />)
    expect(screen.getByText('SIT-002')).toBeInTheDocument()
    expect(screen.getAllByText('1').length).toBe(3)
    expect(screen.getAllByText('0').length).toBe(1)
  })

  it('shows the empty state when no variable details are served', () => {
    render(<QuboVariablePanel variablesDetail={[]} />)
    expect(screen.getByText('No variable details were served.')).toBeInTheDocument()
  })
})

describe('QuboTermPanels', () => {
  it('renders linear, quadratic and penalty terms exactly as served', () => {
    const formulation = buildQuboFormulation()
    render(<QuboTermPanels formulation={formulation} />)
    expect(screen.getByText('Linear terms (β)')).toBeInTheDocument()
    expect(screen.getByText('-0.4')).toBeInTheDocument()
    expect(screen.getByText('-0.25')).toBeInTheDocument()
    expect(screen.getByText('Cardinality')).toBeInTheDocument()
    expect(screen.getByText('P·(Σxᵢ − M)²')).toBeInTheDocument()
  })

  it('shows empty states for missing term groups', () => {
    const formulation = buildQuboFormulation({
      linear: null,
      quadratic: null,
      penalties: [],
    })
    render(<QuboTermPanels formulation={formulation} />)
    expect(screen.getByText('No stored linear coefficients.')).toBeInTheDocument()
    expect(screen.getByText('No stored quadratic coefficients.')).toBeInTheDocument()
  })
})