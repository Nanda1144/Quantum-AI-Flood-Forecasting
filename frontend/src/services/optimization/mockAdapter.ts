/**
 * Development-only optimization adapter.
 *
 * Instantiated exclusively by `getOptimizationAdapter()` when the
 * `VITE_USE_MOCK_DATA` flag permits it (see adapter.ts). It streams the same
 * pipeline stages a real executor would, driven by the deterministic simulator
 * in `simulate.ts`. Nothing here is reachable in a production build.
 */

import type {
  CandidateLocation,
  CoverageRequirement,
  ObjectiveWeights,
  OptimizeRequest,
  OptimizationResult,
  PipelineStage,
  PipelineStageId,
  PipelineUpdate,
  QuantumBackend,
} from '../../types/optimization'
import type { OptimizationAdapter, OptimizationInputs, ProblemInputsRequest } from './adapter'
import { stageDef, weightMeta, normalizeWeights } from '../../lib/quantum'
import {
  baseConstraints,
  buildQubo,
  decodeSelection,
  generateCandidates,
  mulberry32,
  sampleMeasurements,
  siteUtility,
  validateConstraints,
} from './simulate'

class AbortError extends Error {
  constructor() {
    super('Run aborted')
    this.name = 'AbortError'
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new AbortError())
      return
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      clearTimeout(timer)
      reject(new AbortError())
    }
    signal.addEventListener('abort', onAbort)
  })
}

function weightsValid(weights: ObjectiveWeights): boolean {
  return Object.values(weights).every((value) => Number.isFinite(value) && value >= 0) &&
    Object.values(weights).some((value) => value > 0)
}

export class MockOptimizationAdapter implements OptimizationAdapter {
  readonly mode = 'mock' as const

  async getInputs(request: ProblemInputsRequest): Promise<OptimizationInputs> {
    await sleep(420, new AbortController().signal)
    const candidates = generateCandidates(request.candidateCount, request.forecastReference)
    const constraints = baseConstraints(request.candidateCount)
    return {
      candidates,
      constraints,
      forecastRef: request.forecastReference || null,
      providedBy: {
        candidateLocations: 'GIS module (mock)',
        resourceConstraints: 'Planning module (mock)',
        forecast: 'AI forecasting (mock)',
      },
    }
  }

  async run(
    request: OptimizeRequest,
    onUpdate: (update: PipelineUpdate) => void,
    signal: AbortSignal,
  ): Promise<OptimizationResult> {
    const startedAt = new Date().toISOString()

    const inputs: OptimizationInputs = {
      candidates: generateCandidates(request.candidateCount, request.forecastReference),
      constraints: baseConstraints(request.candidateCount),
      forecastRef: request.forecastReference || null,
      providedBy: {
        candidateLocations: 'GIS module (mock)',
        resourceConstraints: 'Planning module (mock)',
        forecast: 'AI forecasting (mock)',
      },
    }
    const candidates = inputs.candidates

    const stageIds = ['input', 'validation', 'qubo', 'hamiltonian', 'qaoa', 'measurement', 'decode', 'constraintValidation', 'benchmark', 'final'] as const
    const stages = Object.fromEntries(
      stageIds.map((id) => [id, { id, label: stageDef(id).label, detail: stageDef(id).detail, status: 'pending' as const, meta: {} }]),
    ) as Record<PipelineStageId, PipelineStage>
    const update = (id: PipelineStageId, patch: Partial<PipelineStage>) => {
      Object.assign(stages[id], patch)
      onUpdate({ stageId: id, status: stages[id].status })
    }
    const set = async (id: PipelineStageId, attempt: () => void) => {
      update(id, { status: 'running' })
      await sleep(380 + Math.random() * 320, signal)
      try {
        attempt()
        update(id, { status: 'done' })
      } catch (error) {
        update(id, { status: 'failed', error: error instanceof Error ? error.message : String(error) })
        throw error
      }
    }

    const t0 = performance.now()

    try {
      update('input', {
        status: 'running',
        detail: `${candidates.length} candidate sites from ${inputs.providedBy.candidateLocations}`,
        meta: { candidates: String(candidates.length), zones: String(new Set(candidates.map((c) => c.zone)).size) },
      })
      await sleep(340, signal)
      update('input', { status: 'done' })

      await set(
        'validation',
        () => {
          if (!weightsValid(request.weights)) {
            throw new Error('Objective weights must be finite and at least one must be > 0.')
          }
          update('validation', {
            detail: 'Weights, ranges and feasibility passed',
            meta: { weights: request.normalizeWeights ? 'normalized' : 'raw (operator-scaled)' },
          })
        },
      )

      let qubo: ReturnType<typeof buildQubo> | null = null
      await set(
        'qubo',
        () => {
          qubo = buildQubo(request, { candidates })
          update('qubo', {
            detail: `QUBO over ${qubo.doc.variableCount} binary variables`,
            meta: { variables: String(qubo.doc.variableCount), penalty: qubo.penaltyScale.toFixed(2) },
          })
        },
      )

      await set(
        'hamiltonian',
        () => {
          const pairTerms = qubo!.doc.matrix.reduce((count, row) => count + row.filter((value, j) => j < qubo!.doc.variableCount && value !== 0).length, 0)
          update('hamiltonian', {
            detail: `Mapped to H = Σ h_i σᵢ + Σ Jᵢⱼ σᵢσⱼ (Ising)`,
            meta: { hTerms: String(qubo!.doc.variableCount), jTerms: String(Math.max(0, pairTerms - qubo!.doc.variableCount)) },
          })
        },
      )

      let measurementBitstrings: string[] = []
      let selected = decodeSelection(request, candidates)
      await set(
        'qaoa',
        () => {
          const rng = mulberry32(hashInt(JSON.stringify(request.weights) + request.shots))
          measurementBitstrings = sampleMeasurements(selected.bitstring, request.shots, request.layers, rng)
          update('qaoa', {
            detail: `QAOA p=${request.layers} on ${selected.bitstring.length} qubits (shots=${request.shots})`,
            meta: { qubits: String(selected.bitstring.length), layers: String(request.layers), shots: String(request.shots) },
          })
        },
      )

      const counts = countBitstrings(measurementBitstrings)
      await set(
        'measurement',
        () => {
          update('measurement', {
            detail: `${counts.length} distinct outcomes sampled`,
            meta: { topOutcome: counts[0]?.[0] ?? '—', topCount: String(counts[0]?.[1] ?? 0) },
          })
        },
      )

      await set(
        'decode',
        () => {
          selected = decodeSelection(request, candidates)
          update('decode', {
            detail: `Top-${selected.selected.length} sites decoded from measurement`,
            meta: { selected: String(selected.selected.length), maxSensors: String(request.maxSensors) },
          })
        },
      )

      const requirements: CoverageRequirement[] = [
        ...inputs.constraints.coverageRequirements,
        ...request.coverageRequirements,
      ]
      const verdict = validateConstraints(selected.selected, request, requirements)
      await set(
        'constraintValidation',
        () => {
          update('constraintValidation', {
            detail: verdict.summary,
            meta: { status: verdict.violations.length === 0 ? 'valid' : 'invalid', violations: String(verdict.violations.length) },
          })
        },
      )

      const classical = decodeSelection({ ...request, weights: { risk: 1, populationCoverage: 0, infrastructureCoverage: 0, communication: 0, cost: 0, redundancy: 0 } }, candidates)
      let finalResult: OptimizationResult
      await set(
        'benchmark',
        () => {
          const metrics = computeMetrics(request, candidates, selected.selected)
          const classicMetrics = computeMetrics(request, candidates, classical.selected)
          const gap = metrics.objectiveValue > 1e-9 ? Math.max(0, (metrics.objectiveValue - classicMetrics.objectiveValue) / metrics.objectiveValue) : 0
          const endedAt = new Date().toISOString()
          finalResult = {
            jobId: jobId(),
            simulated: true,
            backend: effectiveBackend(request),
            qubits: selected.bitstring.length,
            shots: request.shots,
            layers: request.layers,
            startedAt,
            endedAt,
            executionTimeMs: performance.now() - t0,
            objectiveValue: metrics.objectiveValue,
            objectiveBreakdown: metrics.breakdown,
            selectedLocations: toSelectedLocations(selected.selected),
            coverage: {
              populationCovered: metrics.populationCovered,
              populationTotal: metrics.populationTotal,
              infrastructureCovered: metrics.infrastructureCovered,
              infrastructureTotal: metrics.infrastructureTotal,
            },
            constraintViolations: verdict.violations,
            validationStatus: verdict.violations.length === 0 ? 'valid' : 'invalid',
            validationSummary: verdict.summary,
            qubo: qubo!.doc,
            measurementCounts: topCounts(counts, 8),
            energyHistory: energyCurve(metrics.objectiveValue, request.layers),
            classicalComparison: {
              method: 'Greedy (risk-only)',
              objectiveValue: classicMetrics.objectiveValue,
              selectedCount: classical.selected.length,
              executionTimeMs: Math.round(2 + Math.random() * 6),
              gapVsQuantum: Number(gap.toFixed(4)),
            },
          }
          update('benchmark', {
            detail: `Objective ${finalResult.objectiveValue.toFixed(3)} in ${finalResult.executionTimeMs.toFixed(0)} ms`,
            meta: { time: `${finalResult.executionTimeMs.toFixed(0)} ms`, objective: finalResult.objectiveValue.toFixed(4) },
          })
        },
      )

      await set(
        'final',
        () => {
          update('final', {
            detail: `Signed job ${finalResult!.jobId}`,
            meta: { signed: 'yes', adapter: 'mock (development)' },
          })
        },
      )

      return finalResult!
    } catch (error) {
      if (error instanceof AbortError) throw error
      throw error
    }
  }
}

function hashInt(value: string): number {
  let h = 5381
  for (let i = 0; i < value.length; i++) h = (Math.imul(h, 33) ^ value.charCodeAt(i)) >>> 0
  return h
}

function jobId(): string {
  const randPart = Math.random().toString(36).slice(2, 8).toUpperCase()
  return `QOP-${Date.now().toString(36).toUpperCase()}-${randPart}`
}

function effectiveBackend(request: OptimizeRequest): QuantumBackend {
  if (request.hardwareEnabled) return request.backend
  return 'aer_simulator_statevector'
}

function countBitstrings(samples: string[]): [string, number][] {
  const map = new Map<string, number>()
  for (const s of samples) map.set(s, (map.get(s) ?? 0) + 1)
  return [...map.entries()].sort((a, b) => b[1] - a[1])
}

function topCounts(sorted: [string, number][], limit: number): { bitstring: string; count: number }[] {
  return sorted.slice(0, limit).map(([bitstring, count]) => ({ bitstring, count }))
}

function toSelectedLocations(selected: CandidateLocation[]): OptimizationResult['selectedLocations'] {
  return selected.map((site) => ({
    id: site.id,
    name: site.name,
    zone: site.zone,
    sensorCostK: site.sensorCostK,
    floodRisk: site.floodRisk,
    populationCovered: site.populationExposure,
    infrastructureCovered: site.infrastructureCriticality,
  }))
}

interface Metrics {
  objectiveValue: number
  breakdown: OptimizationResult['objectiveBreakdown']
  populationCovered: number
  populationTotal: number
  infrastructureCovered: number
  infrastructureTotal: number
}

function computeMetrics(
  request: OptimizeRequest,
  candidates: CandidateLocation[],
  selected: CandidateLocation[],
): Metrics {
  const weights = request.normalizeWeights ? normalizeWeights(request.weights) : request.weights
  const totalPopulation = candidates.reduce((sum, c) => sum + c.populationExposure, 0)
  const totalInfra = candidates.reduce((sum, c) => sum + c.infrastructureCriticality, 0)
  const populationCovered = selected.reduce((sum, c) => sum + c.populationExposure, 0)
  const infrastructureCovered = selected.reduce((sum, c) => sum + c.infrastructureCriticality, 0)
  const allUtility = candidates.reduce((sum, c) => sum + siteUtility(c, weights), 0)
  const pickUtility = selected.reduce((sum, c) => sum + siteUtility(c, weights), 0)
  const objectiveValue = allUtility > 0 ? pickUtility / allUtility : 0

  const keys = Object.keys(weights) as (keyof ObjectiveWeights)[]
  const breakdown = keys
    .filter((key) => weights[key] > 0)
    .map((key) => {
      const metric = (c: CandidateLocation): number =>
        key === 'risk'
          ? c.floodRisk
          : key === 'populationCoverage'
            ? c.populationExposure
            : key === 'infrastructureCoverage'
              ? c.infrastructureCriticality
              : key === 'communication'
                ? c.communicationScore
                : key === 'cost'
                  ? Math.max(0, 1 - c.sensorCostK / 120)
                  : c.floodRisk
      const total = candidates.reduce((sum, c) => sum + (weights[key] > 0 ? metric(c) : 0), 0)
      const picked = selected.reduce((sum, c) => sum + (weights[key] > 0 ? metric(c) : 0), 0)
      return { key: key as OptimizationResult['objectiveBreakdown'][number]['key'], label: weightMeta(key).label, value: total > 0 ? picked / total : 0 }
    })

  return {
    objectiveValue,
    breakdown,
    populationCovered,
    populationTotal: totalPopulation,
    infrastructureCovered,
    infrastructureTotal: totalInfra,
  }
}

function energyCurve(finalValue: number, layers: number): { iteration: number; energy: number }[] {
  const iterations = 24 + layers * 4
  const start = -finalValue * 1.6 - 0.2
  const curve: { iteration: number; energy: number }[] = []
  for (let i = 0; i < iterations; i++) {
    const t = i / (iterations - 1)
    const decay = Math.pow(1 - t, 1.6)
    const energy = start * decay - finalValue * (1 - decay)
    curve.push({ iteration: i + 1, energy: Number(energy.toFixed(5)) })
  }
  return curve
}