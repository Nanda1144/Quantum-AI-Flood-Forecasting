import { CheckCircle2, Info, RotateCcw, Scale } from 'lucide-react'
import { normalizeWeights as normalizeToUnit, problemWeights, weightMeta } from '../../../lib/quantum'
import type { ObjectiveKey, ObjectiveWeights } from '../../../types/optimization'
import { QuantumPanel } from '../QuantumPanel'
import { QuantumSlider, QuantumToggle } from '../QuantumControls'

interface ObjectiveWeightsPanelProps {
  problemType: string
  weights: ObjectiveWeights
  normalizeWeights: boolean
  onUpdateWeight: (key: ObjectiveKey, value: number) => void
  onToggleNormalize: (value: boolean) => void
  onReset: () => void
}

export function ObjectiveWeightsPanel({
  problemType,
  weights,
  normalizeWeights,
  onUpdateWeight,
  onToggleNormalize,
  onReset,
}: ObjectiveWeightsPanelProps) {
  const keys = problemWeights(problemType)
  const anyWeight = Object.values(weights).some((value) => value > 0)
  const normalized = normalizeWeights ? normalizeToUnit(weights) : weights

  return (
    <QuantumPanel
      step={2}
      icon={Scale}
      title="Objective weights"
      description="Tune what 'good' means before execution"
      status={anyWeight ? 'ready' : 'running'}
      actions={
        <button
          type="button"
          onClick={onReset}
          className="inline-flex items-center gap-1.5 rounded-lg border border-forest-600 bg-forest-800 px-2.5 py-1.5 text-xs text-mist-300 transition-colors hover:border-ai-500/60 hover:text-ai-300"
        >
          <RotateCcw size={13} aria-hidden="true" />
          Balanced
        </button>
      }
    >
      <div className="space-y-4">
        {keys.map((key) => {
          const meta = weightMeta(key)
          const share = normalized[key]
          const pct = Math.round(share * 100)
          return (
            <QuantumSlider
              key={key}
              label={meta.label}
              hint={meta.description}
              value={weights[key]}
              display={normalizeWeights ? `${pct}%` : weights[key].toFixed(2)}
              onChange={(value) => onUpdateWeight(key, value)}
            />
          )
        })}

        {!anyWeight && (
          <p className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-400">
            <Info size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
            At least one weight must be &gt; 0 before an execution can run.
          </p>
        )}

        <div className="space-y-2">
          <QuantumToggle
            label="Normalize weights"
            hint="Rescale so the objective is a weighted share of the achievable utility"
            checked={normalizeWeights}
            onChange={onToggleNormalize}
          />
          {normalizeWeights && (
            <p className="flex items-start gap-2 text-[11px] text-mist-500">
              <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-emerald-400" aria-hidden="true" />
              Weights sum to 1 → objective value on [0, 1].
            </p>
          )}
        </div>
      </div>
    </QuantumPanel>
  )
}