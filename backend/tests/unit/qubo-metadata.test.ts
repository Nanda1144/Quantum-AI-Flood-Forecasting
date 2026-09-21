/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Unit tests for the QUBO metadata persistence record (migration 005).
 *
 * Verifies the two persistence shapes — inline (small problems, full plain-JSON
 * representation) and artifact (large problems, reference + sha-256 checksum +
 * dimensions only, never the matrix cells) — and the reproducibility/audit
 * guarantees they encode. These are pure functions; no database is required.
 */

import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { describe, it } from 'node:test'
import { deriveQuboMetadata, quboIdFor, sha256Hex } from '../../src/lib/optimization/qubo-metadata.ts'
import type {
  OptimizationJob,
  QuboBuild,
  QuboDocument,
} from '../../src/types/optimization.ts'

function buildJob(overrides: {
  id?: string
  qubo?: QuboBuild | null
  storage?: 'inline' | 'artifact'
  reference?: string | null
  completedAt?: string | null
}): OptimizationJob {
  return {
    id: overrides.id ?? 'JOB-9',
    owner: 'admin',
    status: 'completed',
    problemType: 'sensor_placement',
    request: {} as OptimizationJob['request'],
    fallbackPolicy: 'retry_simulator',
    algorithm: 'qaoa',
    executionMode: 'simulator',
    executionModeUsed: 'simulator',
    backend: 'qflare_simulator_statevector',
    backendUsed: 'qflare_simulator_statevector',
    fallbackApplied: false,
    fallbackReason: null,
    qubitCount: 3,
    steps: [],
    qubo: overrides.qubo ?? null,
    classical: null,
    result: null,
    validationStatus: null,
    validationSummary: null,
    error: null,
    createdAt: '2026-09-21T10:00:00.000Z',
    startedAt: '2026-09-21T10:00:01.000Z',
    completedAt: overrides.completedAt ?? '2026-09-21T10:00:05.000Z',
    forecastReference: 'fc://2026-09-21/001',
    candidateReference: 'gis://candidates/3',
    inputReference: 'ai://forecasts/fc://2026-09-21/001',
    variablesCount: null,
    constraints: null,
    objectiveConfiguration: null,
    errorMessage: null,
    quboStorage: overrides.storage ?? 'inline',
    quboArtifactReference: overrides.reference ?? null,
    deletedAt: null,
    deletedBy: null,
    deleteReason: null,
  }
}

function sampleQubo(variableCount = 3): QuboBuild {
  const matrix = Array.from({ length: variableCount }, (_, i) =>
    Array.from({ length: variableCount + 1 }, (__, j) => (i === j ? 1 : 0)),
  )
  const doc: QuboDocument = {
    variableCount,
    variables: Array.from({ length: variableCount }, (_, i) => `SIT-${i + 1}`),
    expression: '1.000 SIT-1 + 1.000 SIT-2',
    matrix,
    offset: 12,
  }
  return {
    doc,
    linear: Array(variableCount).fill(2),
    quadratic: Array.from({ length: variableCount }, () => Array(variableCount).fill(0)),
    penaltyScale: 7,
  }
}

const sha256 = (value: string): string => createHash('sha256').update(value).digest('hex')

describe('QUBO metadata derivation (migration 005)', () => {
  it('inline jobs inline the full plain-JSON representation with a stable audit id', () => {
    const job = buildJob({ qubo: sampleQubo() })
    const metadata = deriveQuboMetadata(job)

    assert.equal(metadata.quboId, 'JOB-9-Q1')
    assert.equal(quboIdFor(job.id), 'JOB-9-Q1')
    assert.equal(metadata.optimizationJobId, 'JOB-9')
    assert.equal(metadata.storageMode, 'inline')
    assert.equal(metadata.variableCount, 3)
    assert.deepEqual(metadata.matrix, sampleQubo().doc.matrix)
    assert.deepEqual(metadata.linearTerms, [2, 2, 2])
    assert.deepEqual(metadata.quadraticTerms, [
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
    ])
    assert.deepEqual(metadata.penaltyConfiguration, { penaltyScale: 7, offset: 12 })
    assert.ok(metadata.objectiveExpression?.includes('SIT-1'))
    assert.equal(metadata.createdAt, '2026-09-21T10:00:05.000Z')
    assert.equal(metadata.artifactReference, undefined)
    assert.equal(metadata.checksum, undefined)
  })

  it('artifact jobs store reference + sha-256 checksum + dimensions only — never the matrix', () => {
    const qubo = sampleQubo()
    const job = buildJob({ qubo, storage: 'artifact', reference: 'qflare://qubo/JOB-9' })
    const metadata = deriveQuboMetadata(job)

    assert.equal(metadata.storageMode, 'artifact')
    assert.equal(metadata.artifactReference, 'qflare://qubo/JOB-9')
    assert.equal(metadata.storageLocation, 'qflare://qubo/JOB-9')
    assert.equal(metadata.checksum, sha256(JSON.stringify(qubo)))
    assert.deepEqual(metadata.matrixDimensions, { variables: 3, rowCount: 3, columnCount: 4 })
    assert.deepEqual(metadata.metadata, {
      problemType: 'sensor_placement',
      algorithm: 'qaoa',
      penaltyScale: 7,
      offset: 12,
    })
    assert.equal(metadata.matrix, undefined, 'artifact metadata must never carry matrix cells')
    assert.equal(metadata.linearTerms, undefined)
    assert.equal(metadata.objectiveExpression, undefined)
  })

  it('the checksum is deterministic — the same QUBO fingerprints identically', () => {
    const first = deriveQuboMetadata(buildJob({ qubo: sampleQubo(), storage: 'artifact' }))
    const second = deriveQuboMetadata(buildJob({ qubo: sampleQubo(), storage: 'artifact' }))
    assert.equal(first.checksum, second.checksum)
    assert.match(first.checksum!, /^[0-9a-f]{64}$/)
  })

  it('an artifact job with no reference falls back to the canonical storage URI', () => {
    const metadata = deriveQuboMetadata(buildJob({ qubo: sampleQubo(), storage: 'artifact' }))
    assert.equal(metadata.artifactReference, 'qflare://qubo/JOB-9')
    assert.equal(metadata.storageLocation, 'qflare://qubo/JOB-9')
  })

  it('a job without a QUBO build has no metadata to record', () => {
    assert.throws(() => deriveQuboMetadata(buildJob({ qubo: null })), /no QUBO build stored/)
  })

  it('sha256Hex is the documented node crypto digest', () => {
    assert.equal(sha256Hex('reproduce-and-audit'), sha256('reproduce-and-audit'))
  })
})