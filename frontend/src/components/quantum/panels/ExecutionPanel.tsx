/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Cpu, Play, Square } from 'lucide-react'
import { QUANTUM_BACKENDS } from '../../../lib/quantum'
import type { ExecutionMode, QuantumBackend } from '../../../types/optimization'
import type { QuantumConfig, RunState } from '../../../hooks/useQuantumOptimization'
import { QuantumPanel } from '../QuantumPanel'
import { QuantumNumberInput, QuantumSelect, QuantumToggle } from '../QuantumControls'

interface ExecutionPanelProps {
  config: QuantumConfig
  updateConfig: (patch: Partial<QuantumConfig>) => void
  runState: RunState
  canRun: boolean
  runError: string | null
  onRun: () => void
  onCancel: () => void
}

export function ExecutionPanel({
  config,
  updateConfig,
  runState,
  canRun,
  runError,
  onRun,
  onCancel,
}: ExecutionPanelProps) {
  const running = runState === 'running'
  const backendOptions = Object.entries(QUANTUM_BACKENDS)
    .filter(([, info]) => (config.executionMode === 'hardware' ? info.hardware : !info.hardware))
    .map(([value, info]) => ({ value, label: info.label }))

  const selectBackend = (value: string) => updateConfig({ backend: value as QuantumBackend })

  return (
    <QuantumPanel
      step={4}
      icon={Cpu}
      title="Execution"
      description="QAOA parameterisation and the run trigger"
      status={running ? 'running' : runState === 'done' ? 'done' : runState === 'error' ? 'running' : 'idle'}
      actions={
        running ? (
          <button
            type="button"
            onClick={onCancel}
            className="inline-flex items-center gap-1.5 rounded-lg border border-critical-500/50 bg-critical-500/15 px-3 py-1.5 text-xs font-medium text-critical-400 transition-colors hover:bg-critical-500/25"
          >
            <Square size={13} aria-hidden="true" />
            Cancel
          </button>
        ) : (
          <button
            type="button"
            onClick={onRun}
            disabled={!canRun}
            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/60 bg-emerald-500/25 px-3 py-1.5 text-xs font-semibold text-emerald-300 transition-colors hover:bg-emerald-500/35 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Play size={13} aria-hidden="true" />
            Run Optimization
          </button>
        )
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <QuantumSelect
            label="Execution mode"
            value={config.executionMode}
            onChange={(value) => updateConfig({ executionMode: value as ExecutionMode })}
            options={[
              { value: 'simulator', label: 'QAOA · Aer simulator' },
              { value: 'hardware', label: 'QAOA · IBM Quantum hardware' },
            ]}
          />
          <QuantumSelect
            label="Backend"
            value={config.backend}
            onChange={selectBackend}
            options={backendOptions}
          />
        </div>

        {config.executionMode === 'hardware' && (
          <QuantumToggle
            label="Enable IBM Quantum hardware"
            hint="Submit real jobs to the provider — requires credentials on the gateway"
            checked={config.hardwareEnabled}
            onChange={(value) => updateConfig({ hardwareEnabled: value })}
          />
        )}

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div className="rounded-lg border border-forest-600 bg-forest-800/50 px-3 py-2">
            <p className="text-[11px] uppercase tracking-wide text-mist-500">Qubits</p>
            <p className="font-mono text-lg text-ai-300">{config.candidateCount}</p>
          </div>
          <QuantumNumberInput
            label="Shots"
            min={256}
            max={65536}
            step={256}
            value={config.shots}
            onChange={(value) => updateConfig({ shots: Number.isFinite(value) ? Math.min(65536, Math.max(256, value)) : config.shots })}
          />
          <QuantumNumberInput
            label="QAOA layers"
            hint="p"
            min={1}
            max={8}
            step={1}
            value={config.layers}
            onChange={(value) => updateConfig({ layers: Number.isFinite(value) ? Math.min(8, Math.max(1, value)) : config.layers })}
          />
          <div className="rounded-lg border border-forest-600 bg-forest-800/50 px-3 py-2">
            <p className="text-[11px] uppercase tracking-wide text-mist-500">Objective</p>
            <p className="font-mono text-lg text-emerald-300">{config.hardwareEnabled ? 'hardware' : 'simulator'}</p>
          </div>
        </div>

        {runError && (
          <p role="alert" className="rounded-lg border border-critical-500/40 bg-critical-500/10 px-3 py-2 text-xs text-critical-400">
            {runError}
          </p>
        )}
      </div>
    </QuantumPanel>
  )
}