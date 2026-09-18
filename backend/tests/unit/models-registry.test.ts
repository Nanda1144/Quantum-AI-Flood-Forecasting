/**
 * ModelsRegistryService unit tests — focus on the documented, configurable
 * best-model selection policy and the compare payload contract.
 */

import '../helpers/env.js'
import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import type { CompareModelsResult, ModelComparisonRow, SelectionMetric } from '../../src/types/domain.ts'
import { MemoryModelComparisonRepository } from '../../src/repositories/memory/repositories.ts'
import { ModelsRegistryService, SELECTION_TIE_BREAKERS } from '../../src/services/models-registry.service.ts'
import { AppError } from '../../src/envelope.ts'

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

function makeService(rows: ModelComparisonRow[], primary: SelectionMetric = 'r2'): ModelsRegistryService {
  return new ModelsRegistryService(new MemoryModelComparisonRepository(rows), primary)
}

const CANDIDATES: ModelComparisonRow[] = [
  row({ modelId: '1', name: 'Alpha', metrics: { rmse: 0.5, mae: 0.4, r2: 0.8, nse: 0.7 } }),
  row({ modelId: '2', name: 'Beta', version: 'v2.0', metrics: { rmse: 0.2, mae: 0.15, r2: 0.95, nse: 0.9 } }),
  row({ modelId: '3', name: 'Gamma', status: 'development', metrics: { rmse: 0.31, mae: 0.24, r2: 0.91, nse: 0.85 } }),
  row({ modelId: '4', name: 'Delta', status: 'retired', metrics: { rmse: 0.45, mae: 0.33, r2: 0.84, nse: 0.6 } }),
  row({ modelId: '5', name: 'Echo', metrics: {}, evaluatedAt: '', evaluationDataset: '' }),
]

describe('ModelsRegistryService selection policy', () => {
  it('exposes the effective policy for the configured primary metric', () => {
    const policy = makeService(CANDIDATES).policy
    assert.equal(policy.primaryMetric, 'r2')
    assert.equal(policy.higherIsBetter, true)
    assert.deepEqual(policy.tieBreakers, SELECTION_TIE_BREAKERS.filter((m) => m !== 'r2'))
    assert.equal(policy.minCandidates, 2)
  })

  it('marks lower-is-better metrics correctly', () => {
    assert.equal(makeService(CANDIDATES, 'mae').policy.higherIsBetter, false)
    assert.equal(makeService(CANDIDATES, 'rmse').policy.higherIsBetter, false)
    assert.equal(makeService(CANDIDATES, 'inferenceTime').policy.higherIsBetter, false)
    assert.equal(makeService(CANDIDATES, 'nse').policy.higherIsBetter, true)
  })

  it('picks the highest R² and excludes unscored candidates', () => {
    const best = makeService(CANDIDATES).selectBest(CANDIDATES)
    assert.ok(best)
    assert.equal(best!.modelId, '2')
    assert.equal(best!.metric, 'r2')
    assert.equal(best!.score, 0.95)
    assert.match(best!.rationale, /R²/i)
    assert.match(best!.rationale, /0\.950/)
  })

  it('picks the lowest MAE when configured as the primary metric', () => {
    const best = makeService(CANDIDATES, 'mae').selectBest(CANDIDATES)
    assert.ok(best)
    assert.equal(best!.modelId, '2')
    assert.equal(best!.metric, 'mae')
    assert.equal(best!.score, 0.15)
  })

  it('returns null when fewer than minCandidates are scored on the policy metric', () => {
    const service = makeService([
      row({ modelId: '1', name: 'Only scored', metrics: { r2: 0.8 } }),
      row({ modelId: '5', name: 'Unscored', metrics: {}, evaluatedAt: '' }),
    ])
    assert.equal(service.selectBest([CANDIDATES[0], CANDIDATES[4]]), null)
  })

  it('breaks R² ties by RMSE (lower is better) and documents it', () => {
    const tied = [
      row({ modelId: '2', name: 'Beta', metrics: { rmse: 0.2, r2: 0.95 } }),
      row({ modelId: '3', name: 'Gamma', metrics: { rmse: 0.31, r2: 0.95 } }),
    ]
    const best = makeService(tied).selectBest(tied)
    assert.ok(best)
    assert.equal(best!.modelId, '2')
    assert.match(best!.rationale, /tied/)
    assert.match(best!.rationale, /RMSE/)
  })

  it('falls back to model name for full ties', () => {
    const fullTie = [
      row({ modelId: '2', name: 'Beta', metrics: { r2: 0.95 } }),
      row({ modelId: '3', name: 'Gamma', metrics: { r2: 0.95 } }),
    ]
    const best = makeService(fullTie).selectBest(fullTie)
    assert.ok(best)
    assert.equal(best!.name, 'Beta')
  })

  it('compare() returns models in request order, dedupes ids, and rejects unknown ids', async () => {
    const service = makeService(CANDIDATES)
    const ordered: CompareModelsResult = await service.compare(['3', '1', '3'])
    assert.deepEqual(ordered.models.map((m) => m.modelId), ['3', '1'])
    assert.equal(ordered.models[0].name, 'Gamma')
    assert.equal(ordered.bestModel!.modelId, '3') // only 3 and 1 requested; Gamma has the higher r2

    await assert.rejects(() => service.compare(['1', '99']), (error: unknown) => {
      assert.ok(error instanceof AppError)
      assert.equal(error.status, 404)
      assert.deepEqual(error.details, { missingModelIds: ['99'] })
      return true
    })
  })
})