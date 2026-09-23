/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These tests verify the production HTTP optimization adapter against
 * the backend wire contract: the snake_case run body, early-termination of the
 * polling loop on a failed pipeline, and the explicit RUN_TIMEOUT surface.
 * No test fabricates a successful quantum run.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MockInstance } from 'vitest'
import { HttpOptimizationAdapter } from './httpAdapter'
import type { OptimizeRequest, OptimizationResult, PipelineStage } from '../../types/optimization'

function envelope<T>(data: T): Response {
  return {
    ok: true,
    status: 200,
    json: async () => ({ success: true, data, timestamp: '2026-09-22T00:00:00.000Z' }),
  } as unknown as Response
}

function pipelineResponse(
  stages: Pick<PipelineStage, 'id' | 'label' | 'detail' | 'status' | 'error'>[],
  completed: boolean,
): Response {
  return envelope({ stages, completed })
}

function makeRequest(overrides: Partial<OptimizeRequest> = {}): OptimizeRequest {
  return {
    problemType: 'sensor_placement',
    candidateCount: 6,
    maxSensors: 3,
    budgetK: null,
    forecastReference: 'FC-20260916-0001',
    riskProfile: 'HIGH',
    executionMode: 'simulator',
    hardwareEnabled: false,
    backend: 'aer_simulator_statevector',
    shots: 1024,
    layers: 2,
    weights: { risk: 1, populationCoverage: 0, infrastructureCoverage: 0, communication: 0, cost: 0, redundancy: 0 },
    normalizeWeights: true,
    coverageRequirements: [],
    ...overrides,
  }
}

function makeResult(overrides: Partial<OptimizationResult> = {}): OptimizationResult {
  return {
    jobId: 'QOP-TEST-001',
    simulated: true,
    backend: 'aer_simulator_statevector',
    qubits: 6,
    shots: 1024,
    layers: 2,
    startedAt: '2026-09-22T00:00:00.000Z',
    endedAt: '2026-09-22T00:00:01.000Z',
    executionTimeMs: 42,
    objectiveValue: 0.75,
    objectiveBreakdown: [{ key: 'risk', label: 'Risk', value: 0.75 }],
    selectedLocations: [{ id: 'SIT-1', name: 'Site 1', zone: 'A', sensorCostK: 40, floodRisk: 0.9, populationCovered: 0.5, infrastructureCovered: 0.5 }],
    coverage: { populationCovered: 0.5, populationTotal: 1, infrastructureCovered: 0.5, infrastructureTotal: 1 },
    constraintViolations: [],
    validationStatus: 'valid',
    validationSummary: 'All constraints satisfied',
    bitstring: '101000',
    qubo: { variableCount: 6, variables: ['SIT-1', 'SIT-2'], expression: '0.5·SIT-1', matrix: [[0, 0.1]], offset: 0 },
    measurementCounts: [{ bitstring: '101000', count: 512 }],
    energyHistory: [{ iteration: 1, energy: -0.5 }],
    classicalComparison: { method: 'exhaustive', objectiveValue: 0.7, selectedCount: 3, executionTimeMs: 2, gapVsQuantum: 0 },
    ...overrides,
  }
}

let fetchSpy: MockInstance

beforeEach(() => {
  fetchSpy?.mockRestore()
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('no network in tests'))
})

afterEach(() => {
  vi.useRealTimers()
})

describe('HttpOptimizationAdapter.run', () => {
  it('posts the snake_case wire body expected by POST /api/optimization/run', async () => {
    fetchSpy
      .mockResolvedValueOnce(envelope({ jobId: 'QOP-TEST-001' }))
      .mockResolvedValueOnce(pipelineResponse([], true))
      .mockResolvedValueOnce(envelope(makeResult()))

    const adapter = new HttpOptimizationAdapter()
    await adapter.run(makeRequest(), () => {}, new AbortController().signal)

    const runCall = fetchSpy.mock.calls.find(([url]) => url === '/api/optimization/run') as [string, RequestInit]
    expect(runCall).toBeDefined()
    const body = JSON.parse(runCall[1].body as string) as Record<string, unknown>
    expect(body.problem_type).toBe('sensor_placement')
    expect(body.candidate_count).toBe(6)
    expect(body.max_sensors).toBe(3)
    expect(body.budget_k).toBeNull()
    expect(body.forecast_reference).toBe('FC-20260916-0001')
    expect(body.risk_profile).toBe('HIGH')
    expect(body.execution_mode).toBe('simulator')
    expect(body.hardware_enabled).toBe(false)
    expect(body.backend).toBe('aer_simulator_statevector')
    expect(body.normalize_weights).toBe(true)
  })

  it('terminates early with RUN_FAILED (and never fetches /result) when a pipeline stage fails', async () => {
    fetchSpy
      .mockResolvedValueOnce(envelope({ jobId: 'QOP-TEST-002' }))
      .mockResolvedValueOnce(
        pipelineResponse(
          [
            { id: 'input', label: 'Input', detail: 'x', status: 'done' },
            { id: 'qaoa', label: 'QAOA', detail: 'x', status: 'failed', error: 'backend ibm_brisbane unreachable' },
          ],
          true,
        ),
      )

    const adapter = new HttpOptimizationAdapter()
    const updates: string[][] = []
    await expect(
      adapter.run(makeRequest(), (update) => updates.push([update.stageId, update.status]), new AbortController().signal),
    ).rejects.toMatchObject({ code: 'RUN_FAILED', message: 'backend ibm_brisbane unreachable' })

    const resultCalled = fetchSpy.mock.calls.some(([url]) => String(url).includes('/result'))
    expect(resultCalled).toBe(false)
    expect(updates).toContainEqual(['qaoa', 'failed'])
  })

  it('throws RUN_TIMEOUT instead of reading a partial result when the 90s deadline passes', async () => {
    vi.useFakeTimers()
    fetchSpy
      .mockResolvedValueOnce(envelope({ jobId: 'QOP-TEST-003' }))
      .mockResolvedValue(pipelineResponse([{ id: 'qaoa', label: 'QAOA', detail: 'x', status: 'running' }], false))

    const adapter = new HttpOptimizationAdapter()
    const promise = adapter.run(makeRequest(), () => {}, new AbortController().signal)
    const assertion = expect(promise).rejects.toMatchObject({ code: 'RUN_TIMEOUT' })
    await vi.advanceTimersByTimeAsync(95_000)

    await assertion
    const resultCalled = fetchSpy.mock.calls.some(([url]) => String(url).includes('/result'))
    expect(resultCalled).toBe(false)
  })

  it('normalizes missing optional arrays on a healthy completed run', async () => {
    const raw = makeResult({ measurementCounts: [] as never, energyHistory: [] as never, qubo: null as never, classicalComparison: null as never })
    fetchSpy
      .mockResolvedValueOnce(envelope({ jobId: 'QOP-TEST-004' }))
      .mockResolvedValueOnce(pipelineResponse([], true))
      .mockResolvedValueOnce(envelope(raw))

    const adapter = new HttpOptimizationAdapter()
    const result = await adapter.run(makeRequest(), () => {}, new AbortController().signal)

    expect(result.measurementCounts).toEqual([])
    expect(result.energyHistory).toEqual([])
    expect(result.qubo.variableCount).toBe(0)
    expect(result.classicalComparison.method).toBe('unavailable')
  })
})