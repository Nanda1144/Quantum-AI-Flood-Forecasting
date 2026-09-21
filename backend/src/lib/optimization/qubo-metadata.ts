/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * QUBO metadata derivation (migration 005).
 *
 * Turns a job's stored QuboBuild into the `optimization_qubo_metadata` audit
 * record. Small problems inline the full plain-JSON representation; larger
 * problems are recorded by reference with a sha-256 checksum and matrix
 * dimensions — the cells themselves are never stored in the database.
 * The payload is always plain JSON, never raw Python/Qiskit objects.
 */

import { createHash } from 'node:crypto'
import type { OptimizationJob, QuboMetadata } from '../../types/optimization.ts'

/** Canonical QUBO audit id — one metadata row per job. */
export function quboIdFor(jobId: string): string {
  return `${jobId}-Q1`
}

/** sha-256 hex digest used to fingerprint a persisted QUBO build. */
export function sha256Hex(value: string): string {
  return createHash('sha256').update(value).digest('hex')
}

/** Reference + storage location for artifact-mode QUBOs. */
export function quboStorageReference(jobId: string, reference: string | null): string {
  return reference ?? `qflare://qubo/${jobId}`
}

/**
 * Derive the QUBO metadata audit record for a job whose QUBO build exists.
 * Throws when `job.qubo` is null (a queued job carries no matrix yet).
 */
export function deriveQuboMetadata(job: OptimizationJob): QuboMetadata {
  const qubo = job.qubo
  if (qubo === null) {
    throw new Error(`cannot derive QUBO metadata for job '${job.id}': no QUBO build stored`)
  }
  const { doc } = qubo
  const penaltyConfiguration = { penaltyScale: qubo.penaltyScale, offset: doc.offset }
  const createdAt = job.completedAt ?? new Date().toISOString()

  if (job.quboStorage === 'artifact') {
    const reference = quboStorageReference(job.id, job.quboArtifactReference)
    return {
      quboId: quboIdFor(job.id),
      optimizationJobId: job.id,
      storageMode: 'artifact',
      variableCount: doc.variableCount,
      artifactReference: reference,
      checksum: sha256Hex(JSON.stringify(qubo)),
      matrixDimensions: {
        variables: doc.variableCount,
        rowCount: doc.matrix.length,
        columnCount: doc.matrix.length > 0 ? doc.matrix[0].length : 0,
      },
      storageLocation: reference,
      metadata: {
        problemType: job.problemType,
        algorithm: job.algorithm,
        penaltyScale: penaltyConfiguration.penaltyScale,
        offset: penaltyConfiguration.offset,
      },
      createdAt,
    }
  }

  return {
    quboId: quboIdFor(job.id),
    optimizationJobId: job.id,
    storageMode: 'inline',
    variableCount: doc.variableCount,
    matrix: doc.matrix,
    linearTerms: qubo.linear,
    quadraticTerms: qubo.quadratic,
    penaltyConfiguration,
    objectiveExpression: doc.expression,
    createdAt,
  }
}