/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These tests verify the optimization hook wiring: the execution-mode
 * selector value is honored verbatim, risk-profile changes re-fetch inputs, and
 * the budget gate exposes the cheapest candidate cost so the page can block
 * infeasible runs before they reach the backend.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useQuantumOptimization } from './useQuantumOptimization'
import type { OptimizationAdapter, OptimizationInputs, ProblemInputsRequest } from '../services/optimization/adapter'
import type { OptimizeRequest, OptimizationResult } from '../types/optimization'

const capturedRequests: ProblemInputsRequest[] = []
const capturedRuns: OptimizeRequest[] = []

function inputsFixture(request: ProblemInputsRequest): OptimizationInputs {
  return {
    candidates: [
      { id: 'SIT-1', name: 'Site 1', zone: 'A', latitude: 12, longitude: 77, floodRisk: 0.9, populationExposure: 0.8, infrastructureCriticality: 0.5, communicationScore: 0.7, sensorCostK: 30, coverageRadiusKm: 2 },
      { id: 'SIT-2', name: 'Site 2', zone: 'B', latitude: 12.1, longitude: 77.1, floodRisk: 0.4, populationExposure: 0.3, infrastructureCriticality: 0.6, communicationScore: 0.4, sensorCostK: 45, coverageRadiusKm: 2 },
      { id: 'SIT-3', name: 'Site 3', zone: 'A', latitude: 12.2, longitude: 77.2, floodRisk: 0.7, populationExposure: 0.9, infrastructureCriticality: 0.8, communicationScore: 0.9, sensorCostK: 60, coverageRadiusKm: 3 },
    ],
    constraints: { maxSensors: 3, budgetK: null, coverageRequirements: [], notes: ['test'] },
    forecastRef: request.forecastReference || null,
    providedBy: { candidateLocations: 'GIS module (test)', resourceConstraints: 'Planning module (test)', forecast: 'AI forecasting (test)' },
  }
}

const resultFixture: OptimizationResult = {
  jobId: 'QOP-TEST-001',
  simulated: true,
  backend: 'aer_simulator_statevector',
  qubits: 3,
  shots: 1024,
  layers: 2,
  startedAt: '2026-09-22T00:00:00.000Z',
  endedAt: '2026-09-22T00:00:01.000Z',
  executionTimeMs: 42,
  objectiveValue: 0.75,
  objectiveBreakdown: [{ key: 'risk', label: 'Risk', value: 0.75 }],
  selectedLocations: [{ id: 'SIT-1', name: 'Site 1', zone: 'A', sensorCostK: 30, floodRisk: 0.9, populationCovered: 0.8, infrastructureCovered: 0.5 }],
  coverage: { populationCovered: 0.8, populationTotal: 2, infrastructureCovered: 0.5, infrastructureTotal: 1.9 },
  constraintViolations: [],
  validationStatus: 'valid',
  validationSummary: 'All constraints satisfied',
  bitstring: '100',
  qubo: { variableCount: 3, variables: ['SIT-1', 'SIT-2', 'SIT-3'], expression: '0.5·SIT-1', matrix: [[0]], offset: 0 },
  measurementCounts: [{ bitstring: '100', count: 512 }],
  energyHistory: [{ iteration: 1, energy: -0.5 }],
  classicalComparison: { method: 'exhaustive', objectiveValue: 0.7, selectedCount: 1, executionTimeMs: 2, gapVsQuantum: 0 },
}

const getInputsMock = vi.fn(async (request: ProblemInputsRequest): Promise<OptimizationInputs> => {
  capturedRequests.push(request)
  return inputsFixture(request)
})

const runMock = vi.fn(async (request: OptimizeRequest): Promise<OptimizationResult> => {
  capturedRuns.push(request)
  return resultFixture
})

const fakeAdapter: OptimizationAdapter = {
  mode: 'mock',
  getInputs: getInputsMock,
  run: runMock,
}

vi.mock('../services/optimization/adapter', () => ({
  getOptimizationAdapter: vi.fn(async () => fakeAdapter),
  adapterModeAvailable: () => 'mock',
}))

beforeEach(() => {
  capturedRequests.length = 0
  capturedRuns.length = 0
  vi.clearAllMocks()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useQuantumOptimization', () => {
  it('loads inputs on mount, clamps maxSensors to the provider limit, and exposes the cheapest candidate cost', async () => {
    const { result } = renderHook(() => useQuantumOptimization())

    await waitFor(() => expect(result.current.inputs).not.toBeNull())
    expect(result.current.inputsLoading).toBe(false)
    expect(result.current.config.maxSensors).toBe(3)
    expect(result.current.minCandidateCostK).toBe(30)
  })

  it('re-fetches inputs when the risk profile changes', async () => {
    const { result } = renderHook(() => useQuantumOptimization())

    await waitFor(() => expect(capturedRequests.length).toBeGreaterThan(0))
    act(() => result.current.updateConfig({ riskProfile: 'HIGH' }))

    await waitFor(() =>
      expect(capturedRequests.some((request) => request.riskProfile === 'HIGH')).toBe(true),
    )
  })

  it('forwards the operator execution mode verbatim (selector, not the hardware toggle)', async () => {
    const { result } = renderHook(() => useQuantumOptimization())

    await waitFor(() => expect(result.current.inputs).not.toBeNull())
    act(() => {
      result.current.updateConfig({ executionMode: 'hardware' })
      result.current.updateConfig({ backend: 'ibm_brisbane' })
    })
    await act(async () => {
      await result.current.startRun()
    })

    expect(capturedRuns).toHaveLength(1)
    expect(capturedRuns[0].executionMode).toBe('hardware')
    expect(capturedRuns[0].hardwareEnabled).toBe(false)
    expect(capturedRuns[0].backend).toBe('ibm_brisbane')
    expect(result.current.runState).toBe('done')
  })

  it('reports errors without advancing to a done result', async () => {
    runMock.mockRejectedValueOnce(new Error('backend unreachable'))
    const { result } = renderHook(() => useQuantumOptimization())

    await waitFor(() => expect(result.current.inputs).not.toBeNull())
    await act(async () => {
      await result.current.startRun()
    })

    expect(result.current.runState).toBe('error')
    expect(result.current.runError).toBe('backend unreachable')
    expect(result.current.result).toBeNull()
  })
})