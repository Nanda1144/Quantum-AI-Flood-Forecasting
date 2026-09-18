import type { ComparisonSortKey } from '../types/ai'

export const SORT_OPTIONS: { value: ComparisonSortKey; label: string }[] = [
  { value: 'evaluatedAt', label: 'Evaluated At' },
  { value: 'name', label: 'Model name' },
  { value: 'mae', label: 'MAE' },
  { value: 'rmse', label: 'RMSE' },
  { value: 'r2', label: 'R²' },
  { value: 'inferenceTime', label: 'Inference time' },
]

/** Natural "best first" direction for each sort key (mirrors the backend). */
export const NATURAL_DIRECTION: Record<ComparisonSortKey, 'asc' | 'desc'> = {
  name: 'asc',
  evaluatedAt: 'desc',
  mae: 'asc',
  rmse: 'asc',
  r2: 'desc',
  inferenceTime: 'asc',
}