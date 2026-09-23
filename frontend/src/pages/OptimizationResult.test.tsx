/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: Coverage for the Optimization Result page (`/optimization/:id/result`).
 * The page renders the gateway payload verbatim and must never present an
 * infeasible selection as a recommendation: loading, empty, error, not-found,
 * validated, invalid, classical-only fallback and export are all pinned down.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { OptimizationResult } from './OptimizationResult'
import {
  buildCandidateLocations,
  buildOptimizationResult,
  buildQuantumJobSummary,
} from '../test/fixtures'
import {
  fetchJobSummary,
  fetchOptimizationExport,
  fetchOptimizationInputs,
  fetchQuboResult,
} from '../services/optimization/quboService'
import { downloadFile } from '../lib/benchmark'

vi.mock('../services/optimization/quboService', () => ({
  fetchJobSummary: vi.fn(),
  fetchQuboResult: vi.fn(),
  fetchOptimizationInputs: vi.fn(),
  fetchOptimizationExport: vi.fn(),
}))

vi.mock('../lib/benchmark', () => ({
  downloadFile: vi.fn(),
}))

const JOB_ID = 'QOP-20260921-0001'

const INPUTS = {
  candidates: buildCandidateLocations(),
  constraints: { maxSensors: 3, budgetK: null, coverageRequirements: [], notes: [] },
  providedBy: { candidateLocations: 'gis://candidates/4', resourceConstraints: 'plan://constraints/4', forecast: 'ai://forecasts/FC-20260921-0001' },
}

interface RenderOptions {
  summaryOverrides?: Parameters<typeof buildQuantumJobSummary>[0]
  resultOverrides?: Parameters<typeof buildOptimizationResult>[0]
  inputsBehavior?: 'resolve' | 'reject'
}

function renderPage(id = JOB_ID) {
  return render(
    <MemoryRouter initialEntries={[`/optimization/${id}/result`]}>
      <Routes>
        <Route path="/optimization/:id/result" element={<OptimizationResult />} />
      </Routes>
    </MemoryRouter>,
  )
}

/**
 * Value shown inside a result KPI card, located by its label. The KPI is the
 * only `p` carrying the exact label — section headers and benchmark rows use
 * `h2`/`td` — so the selector disambiguates those colliding labels.
 */
function kpiValue(label: string): HTMLElement {
  const labelElement = screen.getByText(label, { selector: 'p' })
  const card = labelElement.closest('div') as HTMLElement
  return card.querySelector('p:last-child') as HTMLElement
}

/** Pins the gateway mocks, renders the page and waits for the header. */
async function renderJob({ summaryOverrides = {}, resultOverrides = {}, inputsBehavior = 'resolve' }: RenderOptions = {}) {
  const summary = buildQuantumJobSummary({ status: 'completed', ...summaryOverrides })
  vi.mocked(fetchJobSummary).mockResolvedValue(summary)
  vi.mocked(fetchQuboResult).mockResolvedValue(buildOptimizationResult(resultOverrides))
  if (inputsBehavior === 'reject') {
    vi.mocked(fetchOptimizationInputs).mockRejectedValue(new Error('gis: candidate set unavailable'))
  } else {
    vi.mocked(fetchOptimizationInputs).mockResolvedValue(INPUTS)
  }
  renderPage()
  await screen.findByText('Optimization Result')
  return summary
}

describe('OptimizationResult', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.mocked(downloadFile).mockClear()
  })

  it('shows the loading skeleton while the summary is in flight', () => {
    vi.mocked(fetchJobSummary).mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByLabelText('Loading quantum workspace')).toBeInTheDocument()
  })

  it('renders an honest not-found state for an unknown / foreign job', async () => {
    vi.mocked(fetchJobSummary).mockRejectedValue(
      Object.assign(new Error('Job not visible'), { code: 'JOB_NOT_FOUND' }),
    )
    renderPage()
    expect(await screen.findByText('Optimization result not found')).toBeInTheDocument()
    expect(screen.getByText(/No optimization job with id “QOP-20260921-0001” is visible to your account\./)).toBeInTheDocument()
  })

  it('renders the error state when the gateway is unreachable and recovers on retry', async () => {
    const user = userEvent.setup()
    vi.mocked(fetchJobSummary)
      .mockRejectedValueOnce(new Error('gateway refused'))
      .mockResolvedValueOnce(buildQuantumJobSummary({ status: 'completed' }))
    vi.mocked(fetchQuboResult).mockResolvedValue(buildOptimizationResult())
    vi.mocked(fetchOptimizationInputs).mockResolvedValue(INPUTS)
    renderPage()

    expect(await screen.findByText('Could not load the optimization result')).toBeInTheDocument()
    expect(screen.getByText(/gateway refused/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('VALIDATED OPTIMIZATION RESULT')).toBeInTheDocument()
    expect(fetchJobSummary).toHaveBeenCalledTimes(2)
  })

  it('shows the pending verdict and the job-status link while the pipeline is still running', async () => {
    vi.mocked(fetchJobSummary).mockResolvedValue(buildQuantumJobSummary({ status: 'running' }))
    renderPage()

    expect(await screen.findByText('VALIDATION PENDING')).toBeInTheDocument()
    expect(screen.getByText('No completed result document')).toBeInTheDocument()
    const jobLink = screen.getByRole('link', { name: 'Open the quantum job status' })
    expect(jobLink).toHaveAttribute('href', `/quantum/jobs/${JOB_ID}`)
    expect(fetchQuboResult).not.toHaveBeenCalled()
  })

  it('renders the full validated decision document for a completed job', async () => {
    const summary = await renderJob()

    // Header chips + payload verbatim.
    expect(screen.getByText('Sensor Placement')).toBeInTheDocument()
    expect(screen.getByText('Q-Flare · statevector')).toBeInTheDocument()
    expect(screen.getByText('Simulator')).toBeInTheDocument()
    expect(screen.getByText('VALIDATED OPTIMIZATION RESULT')).toBeInTheDocument()

    // Summary KPIs.
    expect(kpiValue('Selected locations')).toHaveTextContent('3')
    expect(kpiValue('Objective value')).toHaveTextContent('61.0%')
    expect(kpiValue('Constraint violations')).toHaveTextContent('0')
    expect(kpiValue('Quantum objective')).toHaveTextContent('61.0%')
    expect(kpiValue('Classical objective')).toHaveTextContent('70.0%')
    expect(kpiValue('Solution bitstring')).toHaveTextContent('1110')
    expect(kpiValue('Qubits')).toHaveTextContent('4')

    // Selected locations table + map (real geometry from the GIS inputs).
    expect(screen.getByRole('img', { name: 'Map of 4 candidate sites with 3 selected' })).toBeInTheDocument()
    expect(screen.getByText('SIT-001')).toBeInTheDocument()
    expect(screen.getByText('SIT-004')).toBeInTheDocument()
    // The map legend repeats "Selected"/"Not selected", so count within the table.
    const locationTable = screen.getByText('Candidate ID').closest('table') as HTMLElement
    expect(within(locationTable).getAllByText('Selected')).toHaveLength(3)
    expect(within(locationTable).getByText('Not selected')).toBeInTheDocument()
    expect(within(locationTable).getAllByText('Valid')).toHaveLength(3)

    // Decision narrative + benchmark.
    expect(screen.getByText('Why these locations were selected')).toBeInTheDocument()
    expect(screen.getByText(/Every configured constraint validated with no recorded violations/)).toBeInTheDocument()
    expect(screen.getByText('Quantum vs classical benchmark')).toBeInTheDocument()

    // Navigation and export actions.
    expect(screen.getByRole('link', { name: 'View QUBO' })).toHaveAttribute('href', `/qubo-visualization/${JOB_ID}`)
    expect(screen.getByRole('link', { name: 'View Quantum Job' })).toHaveAttribute('href', `/quantum/jobs/${JOB_ID}`)
    expect(screen.getByRole('link', { name: 'View Benchmark' })).toHaveAttribute('href', '/quantum-benchmark')
    expect(screen.getByRole('link', { name: 'Return to Optimization' })).toHaveAttribute('href', '/quantum-optimization')
    expect(screen.getByRole('link', { name: 'Back to Quantum Optimization' })).toHaveAttribute('href', '/quantum-optimization')
    expect(screen.getByRole('button', { name: 'Export Result' })).toBeInTheDocument()
    expect(summary).toBeDefined()
  })

  it('labels an invalid result as NOT operationally recommended', async () => {
    await renderJob({
      resultOverrides: {
        validationStatus: 'invalid',
        validationSummary: null,
        constraintViolations: [
          { code: 'sensor_limit', message: 'Sensor budget exceeded the configured limit of 3.' },
        ],
      },
    })

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('INVALID SOLUTION — NOT OPERATIONALLY RECOMMENDED')).toBeInTheDocument()
    expect(screen.getByText(/1 constraint violation/)).toBeInTheDocument()
    expect(screen.getByText('Why this result is shown but not recommended')).toBeInTheDocument()
    expect(screen.getByText(/Constraint validation failed: Sensor budget exceeded/)).toBeInTheDocument()
    // Selected rows carry the Invalid validation cell, never Valid.
    expect(screen.getAllByText('Invalid').length).toBe(3)
    expect(screen.queryByText('Valid')).not.toBeInTheDocument()
  })

  it('flags a classical-only fallback honestly and blanks the quantum objective', async () => {
    await renderJob({
      summaryOverrides: {
        backendUsed: 'classical',
        backend: 'classical',
        executionModeUsed: 'classical',
        fallbackApplied: true,
        fallbackReason: 'configured backend unavailable — completed on the stored classical reference',
      },
      resultOverrides: { measurementCounts: [] },
    })

    expect(screen.getByText('Execution fallback applied')).toBeInTheDocument()
    expect(
      screen.getByText(/configured backend unavailable — completed on the stored classical reference/),
    ).toBeInTheDocument()
    expect(kpiValue('Solution bitstring')).toHaveTextContent('1110')
    expect(kpiValue('Quantum objective')).toHaveTextContent('—')
  })

  it('downloads the backend-gated export document verbatim', async () => {
    const user = userEvent.setup()
    const summary = await renderJob()
    vi.mocked(fetchOptimizationExport).mockResolvedValue({
      jobId: summary.jobId,
      exportedAt: '2026-09-21T08:06:00.000Z',
      status: 'completed',
      summary,
      result: buildOptimizationResult(),
      quantumAdvantageClaimed: false,
      benchmarkDisclaimer: 'No quantum advantage is claimed.',
    })

    await user.click(screen.getByRole('button', { name: 'Export Result' }))
    await waitFor(() => {
      expect(downloadFile).toHaveBeenCalledTimes(1)
    })
    expect(downloadFile).toHaveBeenCalledWith(
      `qflare-optimization-${summary.jobId}.json`,
      expect.any(String),
      'application/json',
    )
  })

  it('shows an honest empty state when the GIS geometry cannot be reproduced', async () => {
    await renderJob({ inputsBehavior: 'reject' })

    expect(screen.getByText('Candidate geometry unavailable')).toBeInTheDocument()
    expect(screen.getByText(/the location table falls back to the decoded selection without coordinates/)).toBeInTheDocument()
    // The decoded selection alone still renders (table without coordinates).
    expect(screen.getByText('SIT-001')).toBeInTheDocument()
  })
})