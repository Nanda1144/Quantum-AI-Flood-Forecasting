/**
 * Model registry APIs for the Model Comparison page.
 *
 * Reads the Nanda-owned `model_versions`/`model_metrics` registry (see
 * database/migrations/002) — it NEVER computes or invents metrics, only
 * aggregates what was stored. Exposes the list, compare, detail and
 * metric-history contracts consumed by the comparison page.
 *
 * --- Model selection policy -------------------------------------------------
 *
 * `POST /api/ai/models/compare` returns a `bestModel` computed by a
 * documented, configurable policy:
 *
 *  1. Primary metric  — `MODEL_SELECTION_METRIC` env (default `r2`). A model
 *     is a candidate only if it has a finite value for that metric. Lower is
 *     better for `mae`/`rmse`/`inferenceTime`; higher is better for `r2`/`nse`.
 *  2. Minimum size    — at least `minCandidates` (2) scored candidates are
 *     required; otherwise `bestModel` is null (no basis for a decision).
 *  3. Tie-breaking    — candidates equal on the primary metric fall back to
 *     the predefined exclusively-regression chain (documented constant
 *     `SELECTION_TIE_BREAKERS`), then model name for determinism.
 *  4. Traceability    — `bestModel.rationale` states the deciding metric,
 *     score, tie count, and any tie-break used.
 */

import { config } from '../config.ts'
import { AppError, ErrorCodes } from '../envelope.ts'
import type {
  BestModelSelection,
  CompareModelsResult,
  ModelMetricsHistoryItem,
  ModelRegistryQuery,
  ModelComparisonRow,
  SelectionMetric,
  SelectionPolicy,
  Paginated,
} from '../types/domain.ts'
import type { ModelComparisonRepository } from '../repositories/repositories.ts'

interface MetricSemantics {
  label: string
  higherIsBetter: boolean
  pick: (row: ModelComparisonRow) => number | undefined
}

/** Stored-score semantics. Direction mirrors the registry CHECK bounds. */
const METRIC_SEMANTICS: Record<SelectionMetric, MetricSemantics> = {
  mae: { label: 'MAE', higherIsBetter: false, pick: (row) => row.metrics.mae },
  rmse: { label: 'RMSE', higherIsBetter: false, pick: (row) => row.metrics.rmse },
  r2: { label: 'R²', higherIsBetter: true, pick: (row) => row.metrics.r2 },
  nse: { label: 'NSE', higherIsBetter: true, pick: (row) => row.metrics.nse },
  inferenceTime: {
    label: 'inference time',
    higherIsBetter: false,
    pick: (row) => row.inferenceTimeMs,
  },
}

/**
 * Tie-break order when the primary metric is equal: the closest lower-is-better
 * precision metric first, then latency, then the primary is never included.
 */
export const SELECTION_TIE_BREAKERS: SelectionMetric[] = ['rmse', 'mae', 'inferenceTime']

function isFiniteNumber(value: number | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

interface Decision {
  scored: ModelComparisonRow[]
  equalOnPrimary: ModelComparisonRow[]
  primaryValue: number | undefined
}

export class ModelsRegistryService {
  constructor(
    private readonly repo: ModelComparisonRepository,
    private readonly primaryMetric: SelectionMetric = config.MODEL_SELECTION_METRIC,
  ) {}

  get policy(): SelectionPolicy {
    return {
      primaryMetric: this.primaryMetric,
      higherIsBetter: METRIC_SEMANTICS[this.primaryMetric].higherIsBetter,
      tieBreakers: SELECTION_TIE_BREAKERS.filter((metric) => metric !== this.primaryMetric),
      minCandidates: 2,
    }
  }

  /** GET /api/ai/models — filtered, paginated registry listing. */
  async list(query: ModelRegistryQuery): Promise<Paginated<ModelComparisonRow>> {
    return this.repo.listVersions(query)
  }

  /**
   * POST /api/ai/models/compare — aggregate the requested versions' latest
   * stored metrics and apply the selection policy. Duplicate ids are
   * deduplicated (in request order); unknown ids reject the whole request.
   */
  async compare(modelIds: string[]): Promise<CompareModelsResult> {
    const unique = [...new Set(modelIds)]
    const rows = await this.repo.getVersionsByIds(unique)
    const byId = new Map(rows.map((row) => [row.modelId, row]))
    const missing = unique.filter((id) => !byId.has(id))
    if (missing.length > 0) {
      const listed = missing.map((id) => `'${id}'`).join(', ')
      throw new AppError(
        404,
        ErrorCodes.MODEL_NOT_FOUND,
        `No model version matches id${missing.length > 1 ? 's' : ''} ${listed}`,
        { missingModelIds: missing },
      )
    }
    const ordered = unique.map((id) => byId.get(id)!)
    return {
      models: ordered,
      bestModel: this.selectBest(ordered),
      policy: this.policy,
    }
  }

  /** GET /api/ai/models/:id — complete metadata for one registry version. */
  async getModel(id: string): Promise<ModelComparisonRow> {
    const row = await this.repo.getVersionById(id)
    if (!row) {
      throw new AppError(404, ErrorCodes.MODEL_NOT_FOUND, `No model version found with id '${id}'`)
    }
    return row
  }

  /** GET /api/ai/models/:id/metrics — historical evaluation runs (newest first). */
  async getMetricHistory(id: string): Promise<ModelMetricsHistoryItem[]> {
    await this.getModel(id) // 404 when the version does not exist
    return this.repo.listMetricHistory(id)
  }

  /** Policy selection. Returns null when too few candidates are scored. */
  selectBest(candidates: ModelComparisonRow[]): BestModelSelection | null {
    const semantics = METRIC_SEMANTICS[this.primaryMetric]
    const scored = candidates.filter((row) => isFiniteNumber(semantics.pick(row)))
    if (scored.length < this.policy.minCandidates) return null

    const best = [...scored].sort((a, b) => this.compareByChain(a, b))[0]
    const score = semantics.pick(best)!
    const equalOnPrimary = scored.filter((row) => semantics.pick(row) === score)
    const reachedTieBreak = equalOnPrimary.length > 1
    const decision: Decision = { scored, equalOnPrimary, primaryValue: score }

    return {
      modelId: best.modelId,
      name: best.name,
      version: best.version,
      metric: this.primaryMetric,
      score,
      rationale: this.buildRationale(best, decision, reachedTieBreak),
    }
  }

  /** Rank by primary metric, then each tie-breaker, then name (deterministic). */
  private compareByChain(a: ModelComparisonRow, b: ModelComparisonRow): number {
    for (const metric of [this.primaryMetric, ...this.policy.tieBreakers]) {
      const result = compareByMetric(a, b, metric)
      if (result !== 0) return result
    }
    return a.name.localeCompare(b.name)
  }

  private buildRationale(best: ModelComparisonRow, decision: Decision, reachedTieBreak: boolean): string {
    const semantics = METRIC_SEMANTICS[this.primaryMetric]
    const direction = semantics.higherIsBetter ? 'higher is better' : 'lower is better'
    const parts = [
      `selected by policy metric '${semantics.label}' (${direction}) with score ${formatScore(decision.primaryValue!)}`,
      `from ${decision.scored.length} scored candidate${decision.scored.length === 1 ? '' : 's'}`,
    ]
    const tied = decision.equalOnPrimary.filter((row) => row.modelId !== best.modelId)
    if (reachedTieBreak && tied.length > 0) {
      const names = tied.map((row) => `'${row.name}'`).join(', ')
      const tieBreak = this.policy.tieBreakers.find((metric) => {
        const self = METRIC_SEMANTICS[metric].pick(best)
        const other = METRIC_SEMANTICS[metric].pick(tied[0])
        return isFiniteNumber(self) && isFiniteNumber(other) && self !== other
      })
      if (tieBreak) {
        const bSemantics = METRIC_SEMANTICS[tieBreak]
        const selfValue = bSemantics.pick(best)!
        const otherValue = bSemantics.pick(tied[0])!
        parts.push(
          `tied on '${semantics.label}' with ${names}; resolved by '${bSemantics.label}' (${formatScore(selfValue)} vs ${formatScore(otherValue)})`,
        )
      } else {
        parts.push(`tied on '${semantics.label}' with ${names}; no tie-breaker value differs; resolved by model name`)
      }
    } else {
      parts.push('no score ties')
    }
    return `${parts.join('; ')}.`
  }
}

function compareByMetric(a: ModelComparisonRow, b: ModelComparisonRow, metric: SelectionMetric): number {
  const semantics = METRIC_SEMANTICS[metric]
  const av = semantics.pick(a)
  const bv = semantics.pick(b)
  const an = !isFiniteNumber(av)
  const bn = !isFiniteNumber(bv)
  if (an && bn) return 0
  if (an) return 1
  if (bn) return -1
  if (av === bv) return 0
  const ordered = av < bv ? -1 : 1
  return semantics.higherIsBetter ? -ordered : ordered
}

function formatScore(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(3)
}