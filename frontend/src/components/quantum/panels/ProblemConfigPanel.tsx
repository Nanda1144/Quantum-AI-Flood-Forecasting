import { SlidersHorizontal } from 'lucide-react'
import { PROBLEM_TYPES, RISK_PROFILES, riskProfileLabel } from '../../../lib/quantum'
import type { QuantumConfig } from '../../../hooks/useQuantumOptimization'
import type { RiskProfile } from '../../../types/optimization'
import { QuantumPanel } from '../QuantumPanel'
import { QuantumNumberInput, QuantumSelect, QuantumTextInput } from '../QuantumControls'
import { Skeleton } from '../../../components/ui/Skeleton'

interface ProblemConfigPanelProps {
  config: QuantumConfig
  updateConfig: (patch: Partial<QuantumConfig>) => void
  candidateCount: number
  budgetK: number | null
  maxSensors: number
  inputsLoading: boolean
}

export function ProblemConfigPanel({
  config,
  updateConfig,
  candidateCount,
  budgetK,
  maxSensors,
  inputsLoading,
}: ProblemConfigPanelProps) {
  const problem = PROBLEM_TYPES[config.problemType] ?? PROBLEM_TYPES.sensor_placement

  const setBudget = (value: number) => {
    updateConfig({ budgetK: Number.isFinite(value) && value > 0 ? value : null })
  }

  return (
    <QuantumPanel
      step={1}
      icon={SlidersHorizontal}
      title="Problem configuration"
      description="What to optimise and for whom"
      status={inputsLoading ? 'running' : 'ready'}
    >
      <div className="space-y-4">
        <QuantumSelect
          label="Optimization type"
          value={config.problemType}
          onChange={(value) => updateConfig({ problemType: value as QuantumConfig['problemType'] })}
          options={Object.values(PROBLEM_TYPES).map((spec) => ({
            value: spec.id,
            label: spec.label,
            disabled: !spec.enabled,
          }))}
        />
        {!problem.enabled && problem.planned && (
          <p className="rounded-lg border border-ai-500/30 bg-ai-500/10 px-3 py-2 text-xs text-ai-300">{problem.planned}</p>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {inputsLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-9" />
            </div>
          ) : (
            <QuantumNumberInput
              label="Candidate locations"
              hint="Sites from the GIS module"
              min={8}
              max={64}
              step={4}
              value={candidateCount}
              onChange={(value) =>
                updateConfig({ candidateCount: Number.isFinite(value) ? Math.min(64, Math.max(8, value)) : candidateCount })
              }
            />
          )}
          <QuantumNumberInput
            label="Sensor budget"
            hint="Max sensors to place"
            min={1}
            max={64}
            step={1}
            value={maxSensors}
            onChange={(value) =>
              updateConfig({ maxSensors: Number.isFinite(value) ? Math.min(64, Math.max(1, value)) : maxSensors })
            }
          />
        </div>

        <QuantumNumberInput
          label="Capital budget"
          hint="Leave 0 for no budget"
          min={0}
          step={10}
          unit="$k"
          value={budgetK ?? 0}
          onChange={setBudget}
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <QuantumTextInput
            label="Forecast reference"
            hint="Pre-filled from the AI console"
            value={config.forecastReference}
            onChange={(value) => updateConfig({ forecastReference: value })}
          />
          <QuantumSelect
            label="Risk profile"
            hint="Threat posture to optimise for"
            value={config.riskProfile}
            onChange={(value) => updateConfig({ riskProfile: value as RiskProfile })}
            options={RISK_PROFILES.map((profile) => ({ value: profile, label: riskProfileLabel(profile) }))}
          />
        </div>
      </div>
    </QuantumPanel>
  )
}