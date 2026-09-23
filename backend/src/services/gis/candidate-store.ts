/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * GIS candidate + planning-constraint sources consumed by the optimization
 * orchestrator.
 *
 * In the platform these arrive from the GIS module (candidate sites and
 * coverage) and the planning module (resource constraints). The seam below is
 * the only coupling point; the deterministic generator is a stand-in so the
 * pipeline is runnable without those services — its provenance is labelled
 * `GIS module (server)` so a generated stand-in is never presented as real
 * survey data.
 */

import { hashString, mulberry32, type Rng } from '../deterministic.ts'
import type {
  CandidateLocation,
  CoverageRequirement,
  ResourceConstraintsInput,
} from '../../types/optimization.ts'

export interface CandidateStore {
  /** Federated candidate sites for a candidate-location reference + count. */
  getCandidates(request: { reference: string; count: number }): Promise<CandidateLocation[]>
}

export interface ConstraintsSource {
  getConstraints(request: {
    maxSensors: number
    budgetK: number | null
    coverageRequirements: CoverageRequirement[]
    candidateCount: number
  }): Promise<ResourceConstraintsInput>
}

const ZONES = ['Delta North', 'Delta South', 'Estuary West', 'Estuary East', 'Urban Belt', 'Reservoir Ridge']

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}

/**
 * Deterministic generator mirroring the frontend simulator
 * (`frontend/src/services/optimization/simulate.ts`). Seeded by the
 * candidate-location reference so identical input always reproduces identical
 * candidate geometry.
 */
export function generateCandidates(count: number, reference: string): CandidateLocation[] {
  const rng: Rng = mulberry32(hashString(reference) ^ Math.imul(count, 2654435761))
  const hotspots = Array.from({ length: Math.max(1, Math.round(count / 5)) }, () => Math.floor(rng() * count))
  return Array.from({ length: count }, (_, i) => {
    const cluster = i % ZONES.length
    const nearHot = hotspots.some((h) => Math.abs(h - i) <= 1)
    const heat = clamp01(0.28 + (nearHot ? 0.5 : 0) + rng() * 0.22)
    const population = clamp01((cluster === 4 ? 0.7 : 0.3) + (nearHot ? 0.35 : 0) + rng() * 0.15)
    const infra = clamp01((cluster === 5 ? 0.65 : 0.35) + (nearHot ? 0.25 : 0) + rng() * 0.2)
    const comm = clamp01(0.5 + (cluster === 4 ? 0.2 : 0) + (rng() - 0.5) * 0.3)
    return {
      id: `SIT-${String(i + 1).padStart(3, '0')}`,
      name: `Sensor ${String(i + 1).padStart(3, '0')}`,
      zone: ZONES[cluster],
      latitude: 8.9 + rng() * 0.5,
      longitude: -79.8 + rng() * 0.4,
      floodRisk: heat,
      populationExposure: population,
      infrastructureCriticality: infra,
      communicationScore: comm,
      sensorCostK: Math.round(22 + rng() * 46),
      coverageRadiusKm: Math.round(8 + rng() * 14),
    }
  })
}

/** Default planner constraints (mirrors the frontend `baseConstraints`). */
export function defaultConstraints(count: number): ResourceConstraintsInput {
  return {
    maxSensors: Math.max(3, Math.round(count / 4)),
    budgetK: null,
    coverageRequirements: [],
  }
}

export class ServerCandidateStore implements CandidateStore {
  async getCandidates(request: { reference: string; count: number }): Promise<CandidateLocation[]> {
    return generateCandidates(request.count, request.reference)
  }
}

export class ServerConstraintsSource implements ConstraintsSource {
  async getConstraints(request: {
    maxSensors: number
    budgetK: number | null
    coverageRequirements: CoverageRequirement[]
    candidateCount: number
  }): Promise<ResourceConstraintsInput> {
    // Only the planning module's OWN coverage floors belong here. The
    // orchestrator merges the operator-specified requirements separately
    // (`[...resolved.coverageRequirements, ...request.coverageRequirements]`),
    // so echoing `request.coverageRequirements` back would duplicate every
    // operator floor and every derived violation.
    return {
      maxSensors: request.maxSensors,
      budgetK: request.budgetK,
      coverageRequirements: [],
    }
  }
}