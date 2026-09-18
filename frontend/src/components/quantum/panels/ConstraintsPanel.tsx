import { useState } from 'react'
import { ListChecks, Plus, Trash2, Info } from 'lucide-react'
import type { CoverageRequirement, OptimizationInputsResult } from '../../../types/optimization'
import type { QuantumConfig } from '../../../hooks/useQuantumOptimization'
import { QuantumPanel } from '../QuantumPanel'
import { QuantumNumberInput, QuantumSelect } from '../QuantumControls'

interface ConstraintsPanelProps {
  config: QuantumConfig
  updateConfig: (patch: Partial<QuantumConfig>) => void
  coverageRequirements: CoverageRequirement[]
  onAdd: (requirement: CoverageRequirement) => void
  onRemove: (origin: string) => void
  inputs: OptimizationInputsResult | null
}

type Metric = CoverageRequirement['metric']

const ORIGINS = ['Operator', 'Planning module', 'GIS module']

export function ConstraintsPanel({
  config,
  updateConfig,
  coverageRequirements,
  onAdd,
  onRemove,
  inputs,
}: ConstraintsPanelProps) {
  const [metric, setMetric] = useState<Metric>('population')
  const [minFraction, setMinFraction] = useState(0.6)
  const [origin, setOrigin] = useState(ORIGINS[0])

  const addRequirement = () => {
    onAdd({ metric, minFraction, origin })
  }

  return (
    <QuantumPanel
      step={3}
      icon={ListChecks}
      title="Constraints"
      description="Feasibility gates the decoded solution must pass"
      status={coverageRequirements.length > 0 ? 'ready' : 'idle'}
    >
      <div className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <QuantumNumberInput
            label="Max sensors"
            hint="Hard cardinality limit"
            min={1}
            max={Math.max(config.maxSensors, inputs?.constraints.maxSensors ?? 64)}
            step={1}
            value={config.maxSensors}
            onChange={(value) =>
              updateConfig({ maxSensors: Number.isFinite(value) ? Math.max(1, Math.round(value)) : config.maxSensors })
            }
          />
          <QuantumNumberInput
            label="Budget"
            hint="0 = unconstrained"
            min={0}
            step={25}
            unit="$k"
            value={config.budgetK ?? 0}
            onChange={(value) => updateConfig({ budgetK: Number.isFinite(value) && value > 0 ? value : null })}
          />
        </div>

        <div className="space-y-3">
          <p className="text-xs font-medium uppercase tracking-wide text-mist-500">Coverage requirements</p>

          {coverageRequirements.length === 0 && (
            <p className="rounded-lg border border-dashed border-forest-600 px-3 py-2 text-xs text-mist-500">
              No extra coverage floors. Add one to force an infeasibility test — the pipeline will surface it as an invalid
              solution.
            </p>
          )}

          {coverageRequirements.map((requirement) => (
            <div
              key={`${requirement.metric}-${requirement.origin}`}
              className="flex items-center justify-between gap-3 rounded-lg border border-forest-600 bg-forest-800/60 px-3 py-2 text-sm"
            >
              <span className="text-mist-100">
                {requirement.metric === 'population' ? 'Population' : 'Infrastructure'} coverage{' '}
                <span className="font-mono text-ai-300">≥ {Math.round(requirement.minFraction * 100)}%</span>
              </span>
              <span className="flex items-center gap-2">
                <span className="hidden rounded-md bg-ai-500/15 px-2 py-0.5 text-[11px] text-ai-300 sm:inline">
                  {requirement.origin}
                </span>
                <button
                  type="button"
                  onClick={() => onRemove(requirement.origin)}
                  aria-label={`Remove ${requirement.metric} coverage requirement`}
                  className="rounded-lg p-1.5 text-mist-500 transition-colors hover:bg-critical-500/15 hover:text-critical-400"
                >
                  <Trash2 size={14} aria-hidden="true" />
                </button>
              </span>
            </div>
          ))}

          <div className="flex flex-wrap items-end gap-3 rounded-lg border border-forest-600 bg-forest-800/40 p-3">
            <div className="min-w-36 flex-1">
              <QuantumSelect
                label="Metric"
                value={metric}
                onChange={(value) => setMetric(value as Metric)}
                options={[
                  { value: 'population', label: 'Population coverage' },
                  { value: 'infrastructure', label: 'Infrastructure coverage' },
                ]}
              />
            </div>
            <div className="min-w-28 flex-1">
              <QuantumNumberInput
                label="Minimum"
                unit="%"
                min={0}
                max={100}
                step={5}
                value={Math.round(minFraction * 100)}
                onChange={(value) => setMinFraction(Number.isFinite(value) ? Math.min(1, Math.max(0, value / 100)) : 0)}
              />
            </div>
            <div className="min-w-36 flex-1">
              <QuantumSelect
                label="Origin"
                value={origin}
                onChange={(value) => setOrigin(value)}
                options={ORIGINS.map((name) => ({ value: name, label: name }))}
              />
            </div>
            <button
              type="button"
              onClick={addRequirement}
              className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/50 bg-emerald-500/15 px-3 py-2 text-sm font-medium text-emerald-300 transition-colors hover:bg-emerald-500/25"
            >
              <Plus size={15} aria-hidden="true" />
              Add
            </button>
          </div>
        </div>

        {(inputs?.constraints.notes.length ?? 0) > 0 && (
          <div className="space-y-1.5">
            <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-mist-500">
              <Info size={12} aria-hidden="true" />
              Provider notes
            </p>
            <ul className="space-y-1 text-xs text-mist-500">
              {inputs?.constraints.notes.map((note) => (
                <li key={note} className="flex items-start gap-2">
                  <span className="mt-1.5 size-1 shrink-0 rounded-full bg-emerald-500/60" />
                  {note}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </QuantumPanel>
  )
}