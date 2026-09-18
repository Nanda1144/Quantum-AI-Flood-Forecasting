import { Download, ClipboardList, FileJson } from 'lucide-react'
import type { ReactNode } from 'react'
import { QUANTUM_BACKENDS, formatScore } from '../../lib/quantum'
import type { OptimizationResult, QuantumModalKind } from '../../types/optimization'
import { QuantumModal } from './QuantumModal'
import { MeasurementHistogram, EnergySparkline } from './QuantumCharts'

interface QuantumModalsProps {
  active: QuantumModalKind | null
  result: OptimizationResult | null
  onClose: () => void
}

function KeyValue({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-lg border border-forest-600 bg-forest-800/50 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-mist-500">{label}</p>
      <p className="mt-0.5 text-sm text-mist-100">{value}</p>
    </div>
  )
}

export function QuantumModals({ active, result, onClose }: QuantumModalsProps) {
  if (!active || !result) return null
  const jobMeta: { label: string; value: ReactNode }[] = [
    { label: 'Job', value: result.jobId },
    { label: 'Qubits', value: result.qubits },
    { label: 'Shots', value: result.shots },
    { label: 'QAOA layers', value: result.layers },
    { label: 'Backend', value: QUANTUM_BACKENDS[result.backend]?.label ?? result.backend },
    { label: 'Mode', value: result.simulated ? 'simulated' : 'real hardware' },
    { label: 'Wall time', value: `${result.executionTimeMs.toFixed(0)} ms` },
    { label: 'Objective', value: `${Math.round(result.objectiveValue * 100)}%` },
  ]

  return (
    <>
      {active === 'qubo' && (
        <QuantumModal title="QUBO formulation" subtitle={`${result.jobId} · quadratic unconstrained binary optimisation`} onClose={onClose} wide>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <KeyValue label="Variables" value={result.qubo.variableCount} />
              <KeyValue label="Offset" value={result.qubo.offset} />
              <KeyValue label="Dimension" value={`${result.qubo.variableCount}×${result.qubo.variableCount}`} />
              <KeyValue label="Backend" value={result.backend} />
            </div>
            <div>
              <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-mist-500">Expression</p>
              <pre className="overflow-x-auto rounded-lg border border-forest-600 bg-forest-900/70 px-3 py-2 font-mono text-xs text-ai-300">
                {result.qubo.expression}
              </pre>
            </div>
            <div>
              <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-mist-500">
                Q-matrix <span className="font-normal normal-case text-mist-600">(last row = linear term)</span>
              </p>
              <div className="max-h-64 overflow-auto rounded-lg border border-forest-600">
                <table className="w-full text-right font-mono text-[11px]">
                  <tbody>
                    {result.qubo.matrix.map((row, index) => (
                      <tr key={index} className="border-b border-forest-700/50 last:border-0">
                        {row.slice(0, 12).map((value, col) => (
                          <td key={col} className={`px-2 py-1 ${col === index ? 'text-emerald-300' : 'text-mist-400'}`}>
                            {value.toFixed(2)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </QuantumModal>
      )}

      {active === 'qaoa-job' && (
        <QuantumModal title="QAOA job detail" subtitle={`${result.jobId} · certified run record`} onClose={onClose} wide>
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {jobMeta.map((meta) => (
                <KeyValue key={meta.label} label={meta.label} value={meta.value} />
              ))}
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wide text-mist-500">Measurement counts</p>
                <MeasurementHistogram data={result.measurementCounts} />
              </div>
              <div className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wide text-mist-500">Energy convergence</p>
                <EnergySparkline data={result.energyHistory} />
                <p className="text-[11px] text-mist-600">
                  Final energy {result.energyHistory.at(-1)?.energy.toFixed(5)} on the cost Hamiltonian.
                </p>
              </div>
            </div>
          </div>
        </QuantumModal>
      )}

      {active === 'classical' && (
        <QuantumModal title="Classical comparison" subtitle="Greedy heuristic baseline against the QAOA decision" onClose={onClose}>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <KeyValue label="Basis" value={result.classicalComparison.method} />
              <KeyValue label="Executed in" value={`${result.classicalComparison.executionTimeMs} ms`} />
            </div>
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-forest-600 text-mist-500">
                  <th className="px-2 py-1.5 font-medium">Metric</th>
                  <th className="px-2 py-1.5 text-right font-medium">Quantum (QAOA)</th>
                  <th className="px-2 py-1.5 text-right font-medium">Classical</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                <tr className="border-b border-forest-700/50">
                  <td className="px-2 py-1.5 text-mist-300">Objective value</td>
                  <td className="px-2 py-1.5 text-right text-emerald-300">{Math.round(result.objectiveValue * 100)}%</td>
                  <td className="px-2 py-1.5 text-right text-mist-300">{Math.round(result.classicalComparison.objectiveValue * 100)}%</td>
                </tr>
                <tr className="border-b border-forest-700/50">
                  <td className="px-2 py-1.5 text-mist-300">Selected sensors</td>
                  <td className="px-2 py-1.5 text-right text-mist-100">{result.selectedLocations.length}</td>
                  <td className="px-2 py-1.5 text-right text-mist-300">{result.classicalComparison.selectedCount}</td>
                </tr>
                <tr>
                  <td className="px-2 py-1.5 text-mist-300">Gap (QAOA vs classical)</td>
                  <td className="px-2 py-1.5 text-right text-ai-300" colSpan={1}>
                    {formatScore(result.classicalComparison.gapVsQuantum)}
                  </td>
                  <td className="px-2 py-1.5 text-right text-mist-500">baseline</td>
                </tr>
              </tbody>
            </table>
            <p className="text-[11px] text-mist-600">
              A positive gap means the QAOA objective captured a larger share of achievable weighted utility than the greedy
              baseline.
            </p>
          </div>
        </QuantumModal>
      )}

      {active === 'final-result' && (
        <QuantumModal title="Final result" subtitle="The signed decision document for this run" onClose={onClose} wide>
          <div className="flex items-start gap-3 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3">
            <ClipboardList size={18} className="mt-0.5 shrink-0 text-emerald-300" aria-hidden="true" />
            <div>
              <p className="text-sm font-semibold text-emerald-300">
                {result.validationStatus === 'valid' ? 'OPERATIONALLY RECOMMENDED' : 'INVALID SOLUTION — NOT OPERATIONALLY RECOMMENDED'}
              </p>
              <p className="mt-0.5 text-xs text-mist-300">{result.validationSummary}</p>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {jobMeta.slice(0, 4).map((meta) => (
              <KeyValue key={meta.label} label={meta.label} value={meta.value} />
            ))}
          </div>
          <ul className="mt-4 space-y-1.5">
            {result.selectedLocations.map((site) => (
              <li key={site.id} className="flex items-center justify-between rounded-lg border border-forest-600 bg-forest-800/40 px-3 py-2 text-sm">
                <span className="font-mono text-ai-300">{site.id}</span>
                <span className="text-mist-300">{site.zone}</span>
                <span className="font-mono text-mist-300">risk {formatScore(site.floodRisk)}</span>
              </li>
            ))}
            {result.selectedLocations.length === 0 && (
              <li className="px-3 text-xs text-mist-500">No feasible selection present.</li>
            )}
          </ul>
          {result.constraintViolations.length > 0 && (
            <ul className="mt-4 space-y-1">
              {result.constraintViolations.map((violation) => (
                <li key={violation.code} className="rounded-lg border border-critical-500/40 bg-critical-500/10 px-3 py-2 text-xs text-critical-400">
                  {violation.message}
                </li>
              ))}
            </ul>
          )}
        </QuantumModal>
      )}

      {active === 'export' && (
        <QuantumModal title="Export result" subtitle="Portable JSON artifact for downstream planning tools" onClose={onClose} wide>
          <div className="space-y-4">
            <div className="flex items-center gap-3 rounded-lg border border-forest-600 bg-forest-800/40 px-4 py-3">
              <FileJson size={20} className="shrink-0 text-ai-300" aria-hidden="true" />
              <div className="min-w-0 flex-1 text-xs text-mist-300">
                <p className="font-medium text-mist-100">qflare-optimization-{result.jobId}.json</p>
                <p className="mt-0.5 text-mist-500">
                  {result.selectedLocations.length} sensors · {result.qubo.variableCount} variables ·{' '}
                  {result.validationStatus === 'valid' ? 'valid' : 'invalid'}
                </p>
              </div>
              <ExportButton result={result} />
            </div>
            <p className="text-[11px] text-mist-600">
              In production the gateway countersigns the artifact with a proof-of-execution stamp; this export mirrors the live
              schema.
            </p>
          </div>
        </QuantumModal>
      )}
    </>
  )
}

function ExportButton({ result }: { result: OptimizationResult }) {
  const download = () => {
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `qflare-optimization-${result.jobId}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  }
  return (
    <button
      type="button"
      onClick={download}
      className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/50 bg-emerald-500/15 px-3 py-2 text-sm font-medium text-emerald-300 transition-colors hover:bg-emerald-500/25"
    >
      <Download size={15} aria-hidden="true" />
      Download
    </button>
  )
}