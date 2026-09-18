import { Ban, CheckCircle2, Gauge, ShieldCheck, XCircle } from 'lucide-react'
import { QUANTUM_BACKENDS, formatScore } from '../../../lib/quantum'
import type { OptimizationResult } from '../../../types/optimization'
import type { RunState } from '../../../hooks/useQuantumOptimization'
import { QuantumPanel } from '../QuantumPanel'
import { MeasurementHistogram, EnergySparkline } from '../QuantumCharts'

interface ResultSummaryPanelProps {
  result: OptimizationResult | null
  runState: RunState
}

function KPI({ label, value, accent = 'text-mist-100' }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-lg border border-forest-600 bg-forest-800/50 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-mist-500">{label}</p>
      <p className={`mt-0.5 truncate font-mono text-sm ${accent}`}>{value}</p>
    </div>
  )
}

export function ResultSummaryPanel({ result, runState }: ResultSummaryPanelProps) {
  if (!result) {
    return (
      <QuantumPanel
        step={6}
        icon={Gauge}
        title="Result summary"
        description="The signed outcome of the run"
        status="idle"
      >
        <div className="rounded-lg border border-dashed border-forest-600 px-3 py-4 text-center text-xs text-mist-500">
          {runState === 'running' ? 'Waiting for the pipeline to finish…' : 'Summary appears once a run completes.'}
        </div>
      </QuantumPanel>
    )
  }

  const valid = result.validationStatus === 'valid'
  const backendLabel = QUANTUM_BACKENDS[result.backend]?.label ?? result.backend
  const backendHardware = QUANTUM_BACKENDS[result.backend]?.hardware ?? false

  return (
    <QuantumPanel step={6} icon={Gauge} title="Result summary" description="Signed decision document" status="done">
      <div className="space-y-4">
        {/* ---- Operational verdict — never recommend an invalid solution ---- */}
        <div
          role="status"
          className={`flex items-start gap-3 rounded-xl border px-4 py-3 ${
            valid ? 'border-emerald-500/50 bg-emerald-500/10' : 'border-critical-500/60 bg-critical-500/15'
          }`}
        >
          {valid ? (
            <CheckCircle2 size={20} className="mt-0.5 shrink-0 text-emerald-300" aria-hidden="true" />
          ) : (
            <Ban size={20} className="mt-0.5 shrink-0 text-critical-400" aria-hidden="true" />
          )}
          <div>
            <p className={`text-sm font-bold ${valid ? 'text-emerald-300' : 'text-critical-400'}`}>
              {valid ? 'OPERATIONALLY RECOMMENDED' : 'INVALID SOLUTION — NOT OPERATIONALLY RECOMMENDED'}
            </p>
            <p className="mt-0.5 text-xs text-mist-300">{result.validationSummary}</p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <KPI label="Job" value={result.jobId} />
          <KPI label="Objective value" value={`${Math.round(result.objectiveValue * 100)}%`} accent="text-emerald-300" />
          <KPI label="Selected" value={`${result.selectedLocations.length} sensors`} />
          <KPI
            label="Violations"
            value={String(result.constraintViolations.length)}
            accent={result.constraintViolations.length > 0 ? 'text-critical-400' : 'text-emerald-300'}
          />
          <KPI label="Wall time" value={`${result.executionTimeMs.toFixed(0)} ms`} />
          <KPI label="Backend" value={backendLabel} accent="text-ai-300" />
          <KPI label="Qubits" value={`${result.qubits}${result.simulated ? ' · sim' : ' · real'}`} />
          <KPI label="Sampling" value={`${result.shots} shots`} />
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* ---- Coverage ---- */}
          <div className="space-y-3 rounded-lg border border-forest-600 bg-forest-800/40 p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-mist-500">Coverage of exposed assets</p>
            <CoverageBar
              label="Population"
              covered={result.coverage?.populationCovered ?? 0}
              total={result.coverage?.populationTotal ?? 0}
            />
            <CoverageBar
              label="Infrastructure"
              covered={result.coverage?.infrastructureCovered ?? 0}
              total={result.coverage?.infrastructureTotal ?? 0}
            />
          </div>

          {/* ---- Objective breakdown ---- */}
          <div className="space-y-2 rounded-lg border border-forest-600 bg-forest-800/40 p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-mist-500">Weighted objective breakdown</p>
            {result.objectiveBreakdown.length === 0 ? (
              <p className="text-xs text-mist-500">No weighted axes contributed.</p>
            ) : (
              result.objectiveBreakdown.map((entry) => (
                <div key={entry.key} className="flex items-center justify-between text-xs">
                  <span className="text-mist-300">{entry.label}</span>
                  <span className="font-mono text-ai-300">{formatScore(entry.value)}</span>
                </div>
              ))
            )}
          </div>
        </div>

        {result.constraintViolations.length > 0 && (
          <div className="space-y-1.5 rounded-lg border border-critical-500/40 bg-critical-500/10 p-3">
            <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-critical-400">
              <XCircle size={13} aria-hidden="true" />
              Constraint violations
            </p>
            <ul className="space-y-1 text-xs text-mist-300">
              {result.constraintViolations.map((violation) => (
                <li key={violation.code} className="flex items-start gap-2">
                  <span className="mt-1 size-1 shrink-0 rounded-full bg-critical-400" />
                  {violation.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* ---- Selected locations ---- */}
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-mist-500">Decoded selection</p>
          <div className="overflow-x-auto rounded-lg border border-forest-600">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-forest-600 bg-forest-800/60 text-mist-500">
                  <th className="px-3 py-2 font-medium">Site</th>
                  <th className="px-3 py-2 font-medium">Zone</th>
                  <th className="px-3 py-2 text-right font-medium">Cost</th>
                  <th className="px-3 py-2 text-right font-medium">Risk</th>
                  <th className="px-3 py-2 text-right font-medium">Population</th>
                  <th className="px-3 py-2 text-right font-medium">Infrastructure</th>
                </tr>
              </thead>
              <tbody>
                {result.selectedLocations.map((site) => (
                  <tr key={site.id} className="border-b border-forest-700/50 last:border-0">
                    <td className="px-3 py-1.5 font-mono text-ai-300">{site.id}</td>
                    <td className="px-3 py-1.5 text-mist-300">{site.zone}</td>
                    <td className="px-3 py-1.5 text-right font-mono text-mist-300">${site.sensorCostK}k</td>
                    <td className="px-3 py-1.5 text-right font-mono text-mist-300">{formatScore(site.floodRisk)}</td>
                    <td className="px-3 py-1.5 text-right font-mono text-mist-300">{formatScore(site.populationCovered)}</td>
                    <td className="px-3 py-1.5 text-right font-mono text-mist-300">{formatScore(site.infrastructureCovered)}</td>
                  </tr>
                ))}
                {result.selectedLocations.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-3 py-4 text-center text-mist-500">
                      No feasible selection in the decoded outcome.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="space-y-2 rounded-lg border border-forest-600 bg-forest-800/40 p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-mist-500">Measurement outcome</p>
            <MeasurementHistogram data={result.measurementCounts} />
          </div>
          <div className="space-y-2 rounded-lg border border-forest-600 bg-forest-800/40 p-3">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium uppercase tracking-wide text-mist-500">QAOA energy convergence</p>
              {backendHardware && (
                <span className="flex items-center gap-1 text-[11px] text-ai-300">
                  <ShieldCheck size={12} aria-hidden="true" />
                  certified run
                </span>
              )}
            </div>
            <EnergySparkline data={result.energyHistory} />
          </div>
        </div>
      </div>
    </QuantumPanel>
  )
}

function CoverageBar({ label, covered, total }: { label: string; covered: number; total: number }) {
  const fraction = total > 0 ? covered / total : 0
  const pct = Math.round(fraction * 100)
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-mist-300">{label}</span>
        <span className="font-mono text-mist-300">
          {formatScore(covered)} <span className="text-mist-500">/ {total.toFixed(1)}</span>
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-forest-700/60">
        <div
          className={`h-full rounded-full ${pct >= 95 ? 'bg-emerald-400' : pct >= 60 ? 'bg-emerald-500' : 'bg-amber-400'}`}
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
    </div>
  )
}