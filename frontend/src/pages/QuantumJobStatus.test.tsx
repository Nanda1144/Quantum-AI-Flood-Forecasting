/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: Coverage for the Quantum Job Status page lifecycle — the polling
 * contract is the point: the page polls while a job is live (queued / running)
 * and stops at the first terminal state (completed / failed / cancelled /
 * invalid). Everything rendered is the gateway payload verbatim; these tests
 * prove the page never polls a terminal job and starts reading the result only
 * once the job reports `completed`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QuantumJobStatus } from './QuantumJobStatus'
import { buildQuantumJobSummary } from '../test/fixtures'
import { fetchJobSummary, fetchQuboPipeline, fetchQuboResult } from '../services/optimization/quboService'
import type { QuantumJobStatus as JobStatus } from '../types/optimization'
import type { OptimizationResult } from '../types/optimization'

vi.mock('../services/optimization/quboService', () => ({
  fetchJobSummary: vi.fn(),
  fetchQuboPipeline: vi.fn(),
  fetchQuboResult: vi.fn(),
}))

const POLL_MS = 2500
const JOB_ID = 'QOP-20260921-0001'

const SUMMARY_STATUSES: JobStatus[] = ['queued', 'running', 'completed', 'failed', 'timed_out', 'cancelled', 'invalid']

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/quantum/jobs/${JOB_ID}`]}>
      <Routes>
        <Route path="/quantum/jobs/:jobId" element={<QuantumJobStatus />} />
      </Routes>
    </MemoryRouter>,
  )
}

const resultFixture: OptimizationResult = {
  jobId: JOB_ID,
  simulated: true,
  backend: 'aer_simulator_statevector',
  qubits: 4,
  shots: 1024,
  layers: 2,
  startedAt: '2026-09-21T08:00:01.000Z',
  endedAt: '2026-09-21T08:00:05.000Z',
  executionTimeMs: 3.5,
  objectiveValue: 0.61,
  objectiveBreakdown: [{ key: 'risk', label: 'Risk', value: 0.35 }],
  selectedLocations: [],
  coverage: null,
  constraintViolations: [],
  validationStatus: 'valid',
  validationSummary: 'QUBO constraints satisfied by the selected solution.',
  bitstring: '1110',
  qubo: {
    variableCount: 4,
    variables: ['SIT-001', 'SIT-002', 'SIT-003', 'SIT-004'],
    expression: 'Σcᵢxᵢ − ΣQᵢⱼxᵢxⱼ',
    matrix: [],
    offset: 0,
  },
  measurementCounts: [{ bitstring: '1110', count: 728 }],
  energyHistory: [],
  classicalComparison: {
    method: 'exhaustive',
    objectiveValue: 0.7,
    selectedCount: 3,
    executionTimeMs: 12,
    gapVsQuantum: 0,
  },
}

describe('QuantumJobStatus', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchQuboPipeline).mockResolvedValue([])
    vi.mocked(fetchQuboResult).mockResolvedValue(resultFixture)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  /** Flush microtasks (mock-resolved fetches) and any pending timers under fake timers. */
  async function flush(ms = 0): Promise<void> {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms)
    })
  }

  it('shows the loading skeleton while the summary is in flight', () => {
    vi.mocked(fetchJobSummary).mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByLabelText('Loading quantum workspace')).toBeInTheDocument()
  })

  it('renders the gateway payload verbatim for a completed job and never polls again', async () => {
    vi.useFakeTimers()
    const summary = buildQuantumJobSummary({ status: 'completed' })
    vi.mocked(fetchJobSummary).mockResolvedValue(summary)
    renderPage()

    await flush()
    expect(screen.getAllByText('Completed').length).toBeGreaterThan(0)
    expect(screen.getByText(summary.jobId)).toBeInTheDocument()
    expect(screen.getAllByText('Q-Flare · statevector').length).toBeGreaterThan(0)
    // The result document is read exactly once, only for the completed job.
    await flush()
    expect(fetchQuboResult).toHaveBeenCalledTimes(1)
    expect(fetchQuboResult).toHaveBeenCalledWith(JOB_ID)

    // Polling must stay stopped after a terminal state — no more summary reads.
    await flush(POLL_MS * 5)
    expect(fetchJobSummary).toHaveBeenCalledTimes(1)
  })

  it('polls while running and stops immediately when the job reaches a terminal state', async () => {
    vi.useFakeTimers()
    vi.mocked(fetchJobSummary)
      .mockResolvedValueOnce(buildQuantumJobSummary({ status: 'running' }))
      .mockResolvedValueOnce(buildQuantumJobSummary({ status: 'completed' }))
    renderPage()

    await flush()
    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(fetchJobSummary).toHaveBeenCalledTimes(1)
    expect(fetchQuboResult).not.toHaveBeenCalled()

    // One poll interval → the second read observes the completed terminal state.
    await flush(POLL_MS)
    expect(screen.getAllByText('Completed').length).toBeGreaterThan(0)
    expect(fetchJobSummary).toHaveBeenCalledTimes(2)

    // Advancing well past several intervals proves no further polls are scheduled.
    await flush(POLL_MS * 5)
    expect(fetchJobSummary).toHaveBeenCalledTimes(2)
  })

  it('stops polling on a failed terminal and never reads a result', async () => {
    vi.useFakeTimers()
    vi.mocked(fetchJobSummary)
      .mockResolvedValueOnce(buildQuantumJobSummary({ status: 'running' }))
      .mockResolvedValueOnce(buildQuantumJobSummary({ status: 'failed', errorMessage: 'AER_EXECUTION_FAILED' }))
    renderPage()

    await flush()
    expect(screen.getByText('Running')).toBeInTheDocument()

    await flush(POLL_MS)
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(screen.getByText('AER_EXECUTION_FAILED')).toBeInTheDocument()
    expect(fetchQuboResult).not.toHaveBeenCalled()

    await flush(POLL_MS * 5)
    expect(fetchJobSummary).toHaveBeenCalledTimes(2)
  })

  it.each(SUMMARY_STATUSES.filter((status) => status !== 'queued' && status !== 'running'))(
    'treats %s as terminal — a single read, then no polling and no result read',
    async (status) => {
      vi.useFakeTimers()
      vi.mocked(fetchJobSummary).mockResolvedValue(buildQuantumJobSummary({ status }))
      renderPage()

      await flush()
      await flush(POLL_MS * 3)

      expect(fetchJobSummary).toHaveBeenCalledTimes(1)
      if (status === 'completed') {
        expect(fetchQuboResult).toHaveBeenCalledTimes(1)
      } else {
        expect(fetchQuboResult).not.toHaveBeenCalled()
      }
    },
  )

  it('requests the summary and pipeline for the route job id (backend source of truth)', async () => {
    vi.useFakeTimers()
    vi.mocked(fetchJobSummary).mockResolvedValue(buildQuantumJobSummary({ status: 'queued' }))
    renderPage()
    await flush()
    expect(fetchJobSummary).toHaveBeenCalledWith(JOB_ID)
    expect(fetchQuboPipeline).toHaveBeenCalledWith(JOB_ID)
  })

  it('shows the job-not-found state when the gateway reports JOB_NOT_FOUND', async () => {
    vi.mocked(fetchJobSummary).mockRejectedValue({ code: 'JOB_NOT_FOUND', message: `No optimization job with id '${JOB_ID}'` })
    renderPage()
    expect(await screen.findByText('Job not found')).toBeInTheDocument()
  })

  it('shows the gateway error state with the surfaced message and a reload action', async () => {
    vi.mocked(fetchJobSummary).mockRejectedValue(new Error('gateway refused the request'))
    renderPage()
    expect(await screen.findByText('Could not load the job status')).toBeInTheDocument()
    expect(screen.getByText('gateway refused the request')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry load' })).toBeInTheDocument()
  })
})