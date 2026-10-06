/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These tests verify the benchmark page's wiring: the ledger loads
 * newest-first and the hook selects the most recent completed experiment by
 * default, the selected experiment's stored document is fetched on demand,
 * an explicit selection is honoured and survives a refresh, and gateway errors
 * are surfaced without fabricating history.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useQuantumBenchmark } from './useQuantumBenchmark'
import { fetchBenchmarkDocument, fetchBenchmarkLedger } from '../services/optimization/quboService'
import type { BenchmarkDocument, BenchmarkListEntry } from '../types/benchmark'

const newer: BenchmarkListEntry = {
  jobId: 'QOP-NEW-002',
  problemType: 'sensor_placement',
  algorithm: 'QAOA',
  executionMode: 'aer',
  backend: 'aer_simulator_statevector',
  status: 'completed',
  createdAt: '2026-09-22T09:00:00.000Z',
  completedAt: '2026-09-22T09:10:00.000Z',
  classical: { solver: 'exhaustive', optimal: true, objectiveValue: 0.6, runtimeMs: 200 },
  quantum: { objectiveValue: 0.8, runtimeMs: null },
  approximationRatio: { value: 1.3333, basis: 'exact_optimal', invalidReason: null },
  constraintViolationCount: 0,
  validated: true,
}

const older: BenchmarkListEntry = {
  ...newer,
  jobId: 'QOP-OLD-001',
  completedAt: '2026-09-21T08:00:00.000Z',
}

const ledger = [newer, older]

function docFor(entry: BenchmarkListEntry): BenchmarkDocument {
  return {
    jobId: entry.jobId,
    status: 'completed',
    problem: { type: 'sensor_placement', size: { candidates: 4, variables: 4, selected: 2, constraints: 5 } },
    classical: {
      solver: 'exhaustive',
      method: 'exhaustive',
      optimal: true,
      objectiveValue: 0.6,
      runtimeMs: 200,
      selectedCount: 2,
      gapVsQuantum: null,
      missingReason: null,
    },
    quantum: {
      algorithm: 'QAOA',
      objectiveValue: 0.8,
      runtimeMs: 150,
      runtimeSource: 'quantum_results.runtime_ms',
      pipelineRuntimeMs: 400,
      backend: 'aer_simulator_statevector',
      executionMode: 'aer',
      simulated: true,
      qubits: 4,
      shots: 1024,
      layers: 2,
      bitstring: '1010',
      missingReason: null,
    },
    constraintViolations: [],
    validation: { status: 'valid', summary: 'All constraints satisfied' },
    approximationRatio: {
      value: 1.3333,
      basis: 'exact_optimal',
      direction: 'maximize',
      feasible: true,
      invalidReason: null,
      note: 'Ratio = quantum/optimal under MAXIMISATION.',
    },
    reproducibility: {
      seed: 424_242,
      seedNote: 'Stored write-once seed.',
      qaoa: { layers: 2, shots: 1024, backend: 'aer_simulator_statevector', angles: null, anglesNote: 'n/a' },
      problem: {
        type: 'sensor_placement',
        candidateCount: 4,
        maxSensors: 2,
        budgetK: null,
        weights: {
          risk: 0.3,
          populationCoverage: 0.2,
          infrastructureCoverage: 0.15,
          communication: 0.1,
          cost: 0.15,
          redundancy: 0.1,
        },
        normalizeWeights: true,
        coverageRequirements: [],
        forecastReference: 'FC-2026-09',
        candidateReference: null,
        variablesCount: 4,
      },
      solver: { fallbackPolicy: 'retry_simulator', fallbackApplied: false, fallbackReason: null, classicalSolver: 'exhaustive' },
    },
    completedAt: entry.completedAt,
    quantumAdvantageClaimed: false,
    disclaimer: 'No quantum speedup is claimed.',
  }
}

vi.mock('../services/optimization/quboService', () => ({
  fetchBenchmarkLedger: vi.fn(),
  fetchBenchmarkDocument: vi.fn(),
}))

vi.mock('../services/optimization/adapter', () => ({
  adapterModeAvailable: () => 'mock',
}))

const mockedLedger = vi.mocked(fetchBenchmarkLedger)
const mockedDocument = vi.mocked(fetchBenchmarkDocument)

beforeEach(() => {
  vi.clearAllMocks()
  mockedLedger.mockResolvedValue(ledger)
  mockedDocument.mockImplementation(async (jobId) => docFor(jobId === older.jobId ? older : newer))
})

describe('useQuantumBenchmark', () => {
  it('loads the ledger and selects the most recent completed experiment by default', async () => {
    const { result } = renderHook(() => useQuantumBenchmark())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.completedRuns).toHaveLength(2)
    expect(result.current.selectedJobId).toBe('QOP-NEW-002')
    expect(mockedDocument).toHaveBeenCalledWith('QOP-NEW-002')
    expect(result.current.sampleMode).toBe(true)
  })

  it('fetches and exposes the selected experiment storage document', async () => {
    const { result } = renderHook(() => useQuantumBenchmark())

    await waitFor(() => expect(result.current.document).not.toBeNull())
    expect(result.current.document!.jobId).toBe('QOP-NEW-002')
    expect(result.current.documentLoading).toBe(false)
  })

  it('honours an explicit selection; a manual refresh re-anchors to the newest experiment', async () => {
    const { result } = renderHook(() => useQuantumBenchmark())

    await waitFor(() => expect(result.current.selectedJobId).toBe('QOP-NEW-002'))
    act(() => result.current.selectRun('QOP-OLD-001'))
    await waitFor(() => expect(result.current.document?.jobId).toBe('QOP-OLD-001'))
    expect(mockedDocument).toHaveBeenCalledWith('QOP-OLD-001')

    act(() => result.current.refresh())
    await waitFor(() => expect(result.current.selectedJobId).toBe('QOP-NEW-002'))
    expect(result.current.document!.jobId).toBe('QOP-NEW-002')
  })

  it('surfaces a ledger load error without fabricating any history', async () => {
    mockedLedger.mockRejectedValueOnce(new Error('gateway unreachable'))
    const { result } = renderHook(() => useQuantumBenchmark())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.error).toBe('gateway unreachable')
    expect(result.current.ledger).toBeNull()
    expect(result.current.completedRuns).toEqual([])
    expect(result.current.selectedJobId).toBeNull()
  })

  it('surfaces a document load error while keeping the ledger intact', async () => {
    mockedDocument.mockRejectedValueOnce(new Error('stored data unavailable'))
    const { result } = renderHook(() => useQuantumBenchmark())

    await waitFor(() => expect(result.current.documentError).toBe('stored data unavailable'))
    expect(result.current.document).toBeNull()
    expect(result.current.documentLoading).toBe(false)
    expect(result.current.ledger).toHaveLength(2)
  })
})