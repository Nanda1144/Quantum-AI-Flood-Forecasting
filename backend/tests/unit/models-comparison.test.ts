/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * ModelsComparisonService unit tests.
 *
 * In-memory comparison repo is seeded directly; the service must filter/sort
 * rows exactly as returned by the repo candidate set (never deriving metrics).
 */

import '../helpers/env.js'
import { describe, it, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import type { ModelComparisonRow } from '../../src/types/domain.ts'
import { MemoryModelComparisonRepository } from '../../src/repositories/memory/repositories.ts'
import { ModelsComparisonService } from '../../src/services/models-comparison.service.ts'

function row(overrides: Partial<ModelComparisonRow> & { name: string }): ModelComparisonRow {
  return {
    modelId: overrides.modelId ?? `id-${overrides.name}`,
    name: overrides.name,
    version: overrides.version ?? 'v1.0',
    algorithm: overrides.algorithm ?? 'GRU',
    status: overrides.status ?? 'active',
    dataset: overrides.dataset ?? 'dev://comparison/training/a',
    artifactReference: overrides.artifactReference ?? '',
    metrics: overrides.metrics ?? { rmse: 0.4, mae: 0.3, r2: 0.9 },
    evaluatedAt: overrides.evaluatedAt ?? '2026-08-01T10:00:00.000Z',
    evaluationDataset: overrides.evaluationDataset ?? 'eval/a',
    ...(overrides.trainingTimeMs !== undefined && { trainingTimeMs: overrides.trainingTimeMs }),
    ...(overrides.inferenceTimeMs !== undefined && { inferenceTimeMs: overrides.inferenceTimeMs }),
  }
}

const BASELINE: ModelComparisonRow[] = [
  row({ name: 'Alpha', metrics: { rmse: 0.5, mae: 0.4, r2: 0.8 }, inferenceTimeMs: 9, evaluatedAt: '2026-08-20T10:00:00.000Z' }),
  row({ name: 'Beta', version: 'v2.0', metrics: { rmse: 0.2, mae: 0.15, r2: 0.95 }, inferenceTimeMs: 3, evaluatedAt: '2026-09-01T10:00:00.000Z' }),
  row({ name: 'Gamma', status: 'development', metrics: { rmse: 0.31, mae: 0.24, r2: 0.91 }, inferenceTimeMs: 5, evaluatedAt: '2026-08-30T10:00:00.000Z' }),
  row({ name: 'Delta', status: 'retired', metrics: { rmse: 0.45, mae: 0.33, r2: 0.84 }, inferenceTimeMs: 12, evaluatedAt: '2026-08-10T10:00:00.000Z' }),
  row({ name: 'Echo', metrics: {}, evaluatedAt: '', evaluationDataset: '' }),
]

function makeService(rows: ModelComparisonRow[] = BASELINE): ModelsComparisonService {
  return new ModelsComparisonService(new MemoryModelComparisonRepository(rows))
}

describe('ModelsComparisonService', () => {
  let service: ModelsComparisonService

  beforeEach(() => {
    service = makeService()
  })

  it('returns every row with evaluated range and evaluation datasets', async () => {
    const result = await service.compare()
    assert.equal(result.items.length, 5)
    assert.equal(result.evaluatedRange.from, '2026-08-10T10:00:00.000Z')
    assert.equal(result.evaluatedRange.to, '2026-09-01T10:00:00.000Z')
    assert.deepEqual(result.evaluationDatasets, ['eval/a'])
  })

  it('defaults to newest evaluation first', async () => {
    const { items } = await service.compare()
    assert.deepEqual(items.map((r) => r.name), ['Beta', 'Gamma', 'Alpha', 'Delta', 'Echo'])
  })

  it('sorts by rmse ascending (best first) and treats unscored rows as last', async () => {
    const { items } = await service.compare({ sort: 'rmse' })
    assert.deepEqual(items.map((r) => r.name), ['Beta', 'Gamma', 'Delta', 'Alpha', 'Echo'])
  })

  it('respects explicit descending direction for rmse', async () => {
    const { items } = await service.compare({ sort: 'rmse', direction: 'desc' })
    assert.deepEqual(items.map((r) => r.name), ['Alpha', 'Delta', 'Gamma', 'Beta', 'Echo'])
  })

  it('defaults r2 to descending and inferenceTime to ascending', async () => {
    const byR2 = await service.compare({ sort: 'r2' })
    assert.deepEqual(byR2.items.map((r) => r.name), ['Beta', 'Gamma', 'Delta', 'Alpha', 'Echo'])
    const byInference = await service.compare({ sort: 'inferenceTime' })
    assert.deepEqual(byInference.items.map((r) => r.name), ['Beta', 'Gamma', 'Alpha', 'Delta', 'Echo'])
  })

  it('sorts by name alphabetically ascending by default', async () => {
    const { items } = await service.compare({ sort: 'name' })
    assert.deepEqual(items.map((r) => r.name), ['Alpha', 'Beta', 'Delta', 'Echo', 'Gamma'])
  })

  it('filters by status', async () => {
    const { items } = await service.compare({ status: 'development' })
    assert.deepEqual(items.map((r) => r.name), ['Gamma'])
  })

  it('filters by evaluation window', async () => {
    const { items } = await service.compare({ from: '2026-08-25T00:00:00.000Z', to: '2026-08-31T00:00:00.000Z' })
    assert.deepEqual(items.map((r) => r.name), ['Gamma'])
  })

  it('never evaluates rows that carry no metrics in the range', async () => {
    const result = await service.compare({ from: '2026-09-05T00:00:00.000Z' })
    assert.equal(result.items.length, 0)
    assert.equal(result.evaluatedRange.from, null)
    assert.deepEqual(result.evaluationDatasets, [])
  })

  it('keeps unscored versions out of the evaluated range and dataset list', async () => {
    const result = await service.compare()
    assert.ok(!result.evaluationDatasets.includes(''))
  })
})