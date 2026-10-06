/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import type {
  ObjectiveKey,
  ObjectiveMeta,
  PipelineStageId,
  ProblemTypeSpec,
  QuantumBackend,
  RiskProfile,
} from '../types/optimization'

/**
 * Problem/objective/stage catalog.
 *
 * Adding a second supported problem (e.g. `resource_allocation`) later means
 * extending `PROBLEM_TYPES` and `WEIGHT_META` here — the panels only consume
 * these tables, so the page itself does not need restructuring.
 */

export const PROBLEM_TYPES: Record<string, ProblemTypeSpec> = {
  sensor_placement: {
    id: 'sensor_placement',
    label: 'Sensor Placement',
    description: 'Choose where to deploy flood sensors from validated candidate sites.',
    enabled: true,
    objectiveWeights: [
      'risk',
      'populationCoverage',
      'infrastructureCoverage',
      'communication',
      'cost',
      'redundancy',
    ],
  },
  resource_allocation: {
    id: 'resource_allocation',
    label: 'Resource Allocation',
    description: 'Allocate response teams / equipment to threatened zones.',
    enabled: false,
    planned: 'Planned — objective set and constraints are staged once the executor lands.',
    objectiveWeights: [],
  },
}

const WEIGHTS: Record<ObjectiveKey, ObjectiveMeta> = {
  risk: {
    key: 'risk',
    label: 'Risk',
    description: 'Prioritise sites facing the highest modelled flood risk.',
    min: 0,
    max: 1,
  },
  populationCoverage: {
    key: 'populationCoverage',
    label: 'Population coverage',
    description: 'Prefer sensors that protect the most exposed population.',
    min: 0,
    max: 1,
  },
  infrastructureCoverage: {
    key: 'infrastructureCoverage',
    label: 'Infrastructure coverage',
    description: 'Safeguard critical infrastructure (power, water, transport).',
    min: 0,
    max: 1,
  },
  communication: {
    key: 'communication',
    label: 'Communication',
    description: 'Prefer sites with strong telemetry backhaul to the command center.',
    min: 0,
    max: 1,
  },
  cost: {
    key: 'cost',
    label: 'Cost',
    description: 'Penalise expensive deployments — keeps the solution within budget.',
    min: 0,
    max: 1,
  },
  redundancy: {
    key: 'redundancy',
    label: 'Redundancy',
    description: 'Reward overlapping coverage for resilience against sensor loss.',
    min: 0,
    max: 1,
  },
}

export function weightMeta(key: ObjectiveKey): ObjectiveMeta {
  return WEIGHTS[key]
}

export function problemWeights(problemType: string): ObjectiveKey[] {
  return PROBLEM_TYPES[problemType]?.objectiveWeights ?? []
}

/** Renders a stored score as 3-significant-digit %, '—' when absent. */
export function formatScore(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

export const RISK_PROFILES: RiskProfile[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

export function riskProfileLabel(profile: RiskProfile): string {
  return profile.charAt(0) + profile.slice(1).toLowerCase()
}

export const QUANTUM_BACKENDS: Record<QuantumBackend, { label: string; provider: string; hardware: boolean }> = {
  aer_simulator_statevector: {
    label: 'Aer · statevector',
    provider: 'Qiskit Aer (simulator)',
    hardware: false,
  },
  aer_simulator_matrix_product_state: {
    label: 'Aer · MPS',
    provider: 'Qiskit Aer (simulator)',
    hardware: false,
  },
  ibm_brisbane: { label: 'ibm_brisbane', provider: 'IBM Quantum', hardware: true },
  ibm_kyiv: { label: 'ibm_kyiv', provider: 'IBM Quantum', hardware: true },
}

export interface StageDef {
  id: PipelineStageId
  label: string
  detail: string
}

export const PIPELINE_STAGES: StageDef[] = [
  { id: 'input', label: 'Input', detail: 'Federated problem inputs' },
  { id: 'validation', label: 'Validation', detail: 'Weights, ranges, feasibility' },
  { id: 'qubo', label: 'QUBO', detail: 'Quadratic unconstrained binary optimisation' },
  { id: 'hamiltonian', label: 'Hamiltonian', detail: 'QUBO → cost Hamiltonian' },
  { id: 'qaoa', label: 'QAOA', detail: 'Alternating ansatz layers' },
  { id: 'measurement', label: 'Measurement', detail: 'Shot sampling & counts' },
  { id: 'decode', label: 'Decode', detail: 'Bitstring → location set' },
  { id: 'constraintValidation', label: 'Constraint validation', detail: 'Budget, sensor limit, coverage' },
  { id: 'benchmark', label: 'Benchmark', detail: 'Objective value, wall time' },
  { id: 'final', label: 'Final result', detail: 'Signed result document' },
]

export function stageDef(stageId: PipelineStageId): StageDef {
  return PIPELINE_STAGES.find((stage) => stage.id === stageId) ?? PIPELINE_STAGES[0]
}

/** Normalized weights (sum → 1) are what the executor consumes. */
export function normalizeWeights(weights: Record<ObjectiveKey, number>): Record<ObjectiveKey, number> {
  const total = Object.values(weights).reduce((sum, value) => sum + value, 0)
  if (!Number.isFinite(total) || total <= 0) return weights
  const out = {} as Record<ObjectiveKey, number>
  for (const key of Object.keys(weights) as ObjectiveKey[]) {
    out[key] = weights[key] / total
  }
  return out
}