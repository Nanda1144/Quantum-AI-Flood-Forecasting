/**
 * Model comparison for the evaluation page.
 *
 * Backed by the Nanda-owned `model_versions` / `model_metrics` registry (see
 * database/migrations/002). The service never computes metrics — it reads the
 * latest stored evaluation per version, optionally filters, and sorts. The
 * comparison page renders exactly the values returned here.
 */

import type {
  ComparisonSortKey,
  ModelComparisonQuery,
  RegistryStatus,
} from '../types/contract.ts'
import type { ModelComparisonResult, ModelComparisonRow } from '../types/domain.ts'
import type { ModelComparisonRepository } from '../repositories/repositories.ts'

type Direction = 'asc' | 'desc'

/** Default direction chosen so "best first" is intuitive for each key. */
const DEFAULT_DIRECTION: Record<ComparisonSortKey, Direction> = {
  name: 'asc',
  evaluatedAt: 'desc',
  mae: 'asc',
  rmse: 'asc',
  r2: 'desc',
  inferenceTime: 'asc',
}

export class ModelsComparisonService {
  constructor(private readonly repo: ModelComparisonRepository) {}

  async compare(query: ModelComparisonQuery = {}): Promise<ModelComparisonResult> {
    const sort: ComparisonSortKey = query.sort ?? 'evaluatedAt'
    const direction: Direction = query.direction ?? DEFAULT_DIRECTION[sort]

    let items = await this.repo.listComparable()
    items = this.filter(items, query)
    const sorted = [...items].sort((a, b) => compareRows(a, b, sort, direction))

    const scored = sorted.filter((row) => row.evaluatedAt !== '' && Object.keys(row.metrics).length > 0)
    return {
      items: sorted,
      evaluatedRange: {
        from: scored.reduce<string | null>((min, row) => (min === null || row.evaluatedAt < min ? row.evaluatedAt : min), null),
        to: scored.reduce<string | null>((max, row) => (max === null || row.evaluatedAt > max ? row.evaluatedAt : max), null),
      },
      evaluationDatasets: [...new Set(sorted.map((row) => row.evaluationDataset).filter(Boolean))],
    }
  }

  private filter(items: ModelComparisonRow[], query: ModelComparisonQuery): ModelComparisonRow[] {
    let filtered = items
    if (query.status) {
      const status = query.status as RegistryStatus
      filtered = filtered.filter((row) => row.status === status)
    }
    if (query.from) filtered = filtered.filter((row) => row.evaluatedAt !== '' && row.evaluatedAt >= query.from!)
    if (query.to) filtered = filtered.filter((row) => row.evaluatedAt !== '' && row.evaluatedAt <= query.to!)
    return filtered
  }
}

/** ISO timestamps with identical offsets compare lexicographically. */
function valueFor(row: ModelComparisonRow, key: ComparisonSortKey): string | number | undefined {
  switch (key) {
    case 'name':
      return row.name
    case 'evaluatedAt':
      return row.evaluatedAt === '' ? undefined : row.evaluatedAt
    case 'mae':
      return row.metrics.mae
    case 'rmse':
      return row.metrics.rmse
    case 'r2':
      return row.metrics.r2
    case 'inferenceTime':
      return row.inferenceTimeMs
  }
}

/** Missing values always sort last, regardless of direction. */
function compareRows(a: ModelComparisonRow, b: ModelComparisonRow, key: ComparisonSortKey, direction: Direction): number {
  const av = valueFor(a, key)
  const bv = valueFor(b, key)
  const an = av === undefined
  const bn = bv === undefined
  if (an && bn) return 0
  if (an) return 1
  if (bn) return -1
  const result = av < bv ? -1 : av > bv ? 1 : 0
  return direction === 'asc' ? result : -result
}