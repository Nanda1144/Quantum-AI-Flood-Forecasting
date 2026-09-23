/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * QUBO Visualization — the auditable view of a job's stored QUBO formulation.
 *
 * Every value rendered here is served by GET /api/optimization/jobs/:id/qubo
 * (or the pipeline/result endpoints for the audit actions). The backend is the
 * single source of truth — no QUBO coefficient is rederived in React.
 *
 * Page states:
 *   loading     → initial fetch in flight
 *   unavailable → the job never produced a QUBO (queued / failed early)
 *   invalid     → the stored matrix is malformed
 *   error       → the gateway rejected the request
 *   valid       → full visualization
 */

import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, Atom, ClipboardList, Download, FileJson, GitCompareArrows, Unplug } from 'lucide-react'
import { QuantumCircuitBackground } from '../components/quantum/QuantumCircuitBackground'
import { QuantumModal } from '../components/quantum/QuantumModal'
import { QuantumSkeleton } from '../components/quantum/QuantumSkeleton'
import { QuboSummaryCards } from '../components/qubo/QuboSummaryCards'
import { QuboMatrixHeatmap } from '../components/qubo/QuboMatrixHeatmap'
import { QuboTermPanels } from '../components/qubo/QuboTermPanels'
import { QuboObjectivePanel } from '../components/qubo/QuboObjectivePanel'
import { QuboConstraintPanel } from '../components/qubo/QuboConstraintPanel'
import { QuboVariablePanel } from '../components/qubo/QuboVariablePanel'
import { fetchQuboFormulation, fetchQuboPipeline, fetchQuboResult } from '../services/optimization/quboService'
import type { OptimizationResult, PipelineStage, QuboFormulation } from '../types/optimization'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'unavailable'; formulation: QuboFormulation }
  | { kind: 'invalid'; formulation: QuboFormulation }
  | { kind: 'valid'; formulation: QuboFormulation }

type ModalKind = 'pipeline' | 'result' | null

function download(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export function QuboVisualization() {
  const { jobId = '' } = useParams()
  const navigate = useNavigate()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [modal, setModal] = useState<ModalKind>(null)
  const [pipeline, setPipeline] = useState<PipelineStage[] | null>(null)
  const [result, setResult] = useState<OptimizationResult | null>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchQuboFormulation(jobId)
      .then((formulation) => {
        if (cancelled) return
        if (formulation.available === 'valid') setState({ kind: 'valid', formulation })
        else if (formulation.available === 'invalid') setState({ kind: 'invalid', formulation })
        else setState({ kind: 'unavailable', formulation })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        const message = error instanceof Error ? error.message : 'Failed to load the QUBO formulation'
        setState({ kind: 'error', message })
      })
    return () => {
      cancelled = true
    }
  }, [jobId])

  const openPipeline = async () => {
    setBusyAction('pipeline')
    try {
      const stages = await fetchQuboPipeline(jobId)
      setPipeline(stages)
      setModal('pipeline')
    } catch {
      setPipeline([])
      setModal('pipeline')
    } finally {
      setBusyAction(null)
    }
  }

  const openResult = async () => {
    setBusyAction('result')
    try {
      const loaded = await fetchQuboResult(jobId)
      setResult(loaded)
      setModal('result')
    } catch {
      setResult(null)
      setModal('result')
    } finally {
      setBusyAction(null)
    }
  }

  const exportQubo = (formulation: QuboFormulation) => {
    download(`qubo-${jobId}.json`, JSON.stringify(formulation, null, 2), 'application/json')
  }

  const exportMatrix = (formulation: QuboFormulation) => {
    const rows = (formulation.quadratic ?? formulation.matrix).map((row) => row.map(String).join(','))
    download(`qubo-${jobId}-matrix.csv`, rows.join('\n'), 'text/csv')
  }

  /* ---- Non-valid states ------------------------------------------------- */

  if (state.kind === 'loading') {
    return (
      <div className="min-h-screen px-4 pb-16 pt-6 sm:px-6 lg:px-10">
        <QuantumCircuitBackground />
        <div className="mx-auto max-w-[1440px] space-y-5">
          <BackLink />
          <QuantumSkeleton />
        </div>
      </div>
    )
  }

  if (state.kind === 'error') {
    return (
      <div className="min-h-screen px-4 pb-16 pt-6 sm:px-6 lg:px-10">
        <QuantumCircuitBackground />
        <div className="mx-auto max-w-[1440px] space-y-5">
          <BackLink />
          <div className="glass-card flex items-start gap-3 rounded-xl border border-critical-500/60 bg-critical-500/15 p-5">
            <Unplug size={20} className="mt-0.5 shrink-0 text-critical-400" aria-hidden="true" />
            <div>
              <p className="text-sm font-bold text-critical-400">Could not load the QUBO formulation</p>
              <p className="mt-1 text-xs text-mist-300">{state.message}</p>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const formulation = state.formulation
  const unavailable = state.kind === 'unavailable'
  const invalid = state.kind === 'invalid'

  const bitstring = formulation.bitstring
  const selectedCount = formulation.selectedVariableIds.length

  return (
    <div className="min-h-screen px-4 pb-16 pt-6 sm:px-6 lg:px-10">
      <QuantumCircuitBackground />
      <div className="mx-auto max-w-[1440px] space-y-5">
        <BackLink />

        {/* ---- Header ---- */}
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="glass-card flex size-12 shrink-0 items-center justify-center text-ai-300">
              <Atom size={24} aria-hidden="true" />
            </span>
            <div>
              <h1 className="text-xl font-semibold tracking-tight text-mist-50">QUBO Visualization</h1>
              <p className="text-sm text-mist-500">Auditable formulation served by the optimization gateway</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-forest-600/70 bg-forest-800/70 px-2.5 py-1 font-mono text-xs text-mist-300">
              {formulation.jobId}
            </span>
            <span className="rounded-lg border border-forest-600/70 bg-forest-800/70 px-2.5 py-1 text-xs text-mist-300">
              {formulation.problemType.replace('_', ' ')}
            </span>
            <span className="rounded-lg border border-forest-600/70 bg-forest-800/70 px-2.5 py-1 font-mono text-xs text-mist-300">
              {formulation.algorithm}
            </span>
            <span className="rounded-lg border border-forest-600/70 bg-forest-800/70 px-2.5 py-1 text-xs text-mist-300">
              {new Date(formulation.createdAt).toLocaleString()}
            </span>
            <span
              className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium ${
                formulation.storage === 'artifact'
                  ? 'border-amber-500/40 bg-amber-500/10 text-amber-300'
                  : 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
              }`}
            >
              {formulation.inline ? 'inline' : 'artifact stored'}
            </span>
            {formulation.validationStatus && (
              <span
                className={`rounded-lg border px-2.5 py-1 text-xs font-medium ${
                  formulation.validationStatus === 'valid'
                    ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                    : 'border-critical-500/60 bg-critical-500/15 text-critical-400'
                }`}
              >
                {formulation.validationStatus}
              </span>
            )}
          </div>
        </header>

        {/* ---- Unavailable / invalid notice ---- */}
        {(unavailable || invalid) && (
          <div className="glass-card flex items-start gap-3 rounded-xl border p-5 border-amber-500/40 bg-amber-500/5">
            <AlertTriangle size={20} className="mt-0.5 shrink-0 text-amber-400" aria-hidden="true" />
            <div>
              <p className="text-sm font-bold text-amber-300">
                {unavailable ? 'QUBO formulation unavailable' : 'Stored QUBO is invalid'}
              </p>
              <p className="mt-1 text-xs text-mist-300">
                {unavailable
                  ? `Job ${formulation.jobId} has status "${formulation.status}" and never produced a stored QUBO matrix.`
                  : `Job ${formulation.jobId} reported a malformed matrix that cannot be visualised safely.`}
              </p>
            </div>
          </div>
        )}

        {!unavailable && !invalid && (
          <>
            {/* ---- Summary cards ---- */}
            <QuboSummaryCards summary={formulation.summary} />

            {/* ---- Objective + expression ---- */}
            <QuboObjectivePanel objective={formulation.objective} />

            <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
              {/* ---- Heatmap ---- */}
              <div className="glass-card">
                <QuboMatrixHeatmap quadratic={formulation.quadratic} variables={formulation.variables} />
              </div>

              {/* ---- Constraint + variable panels ---- */}
              <div className="space-y-5">
                <QuboConstraintPanel constraints={formulation.constraints} penaltyScale={formulation.penaltyScale} />
                <QuboVariablePanel variablesDetail={formulation.variablesDetail} />

                {/* ---- Bitstring readout ---- */}
                <div className="rounded-lg border border-forest-600 bg-forest-800/40 p-4">
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-mist-500">Measured bitstring</p>
                  {bitstring ? (
                    <>
                      <code className="break-all rounded-md border border-forest-600 bg-forest-900 px-2.5 py-1 font-mono text-xs text-ai-300">
                        {bitstring}
                      </code>
                      <p className="mt-2 text-[11px] text-mist-500">
                        {selectedCount} of {formulation.variables.length} variable
                        {formulation.variables.length === 1 ? '' : 's'} selected.
                      </p>
                    </>
                  ) : (
                    <p className="text-xs text-mist-500">No measurement outcome recorded for this job.</p>
                  )}
                </div>
              </div>
            </div>

            {/* ---- Term panels ---- */}
            <QuboTermPanels formulation={formulation} />

            {/* ---- Actions ---- */}
            <div className="glass-card">
              <p className="mb-3 text-xs font-medium uppercase tracking-wide text-mist-500">Actions</p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => navigate('/quantum-optimization')}
                  className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
                >
                  <ArrowLeft size={15} className="text-ai-300" aria-hidden="true" />
                  Return to optimization
                </button>
                <button
                  type="button"
                  onClick={openPipeline}
                  disabled={busyAction !== null}
                  className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300 disabled:opacity-40"
                >
                  <GitCompareArrows size={15} className="text-ai-300" aria-hidden="true" />
                  {busyAction === 'pipeline' ? 'Loading…' : 'View execution'}
                </button>
                <button
                  type="button"
                  onClick={openResult}
                  disabled={busyAction !== null}
                  className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300 disabled:opacity-40"
                >
                  <ClipboardList size={15} className="text-ai-300" aria-hidden="true" />
                  {busyAction === 'result' ? 'Loading…' : 'View result'}
                </button>
                <button
                  type="button"
                  onClick={() => exportQubo(formulation)}
                  className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
                >
                  <FileJson size={15} className="text-ai-300" aria-hidden="true" />
                  Export QUBO JSON
                </button>
                <button
                  type="button"
                  onClick={() => exportMatrix(formulation)}
                  className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
                >
                  <Download size={15} className="text-ai-300" aria-hidden="true" />
                  Export matrix
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* ---- Audit modals ---- */}
      {modal === 'pipeline' && (
        <QuantumModal title="Execution pipeline" subtitle={jobId} onClose={() => setModal(null)} wide>
          {pipeline === null ? (
            <p className="text-sm text-mist-500">Pipeline data could not be loaded.</p>
          ) : pipeline.length === 0 ? (
            <p className="text-sm text-mist-500">No pipeline stages recorded for this job.</p>
          ) : (
            <ol className="space-y-1.5">
              {pipeline.map((stage) => (
                <li
                  key={stage.id}
                  className={`flex items-start gap-3 rounded-lg border px-3 py-2 ${
                    stage.status === 'done'
                      ? 'border-emerald-500/40 bg-emerald-500/5'
                      : stage.status === 'failed'
                        ? 'border-critical-500/60 bg-critical-500/10'
                        : 'border-forest-600 bg-forest-800/40'
                  }`}
                >
                  <span
                    className={`mt-1 size-2 shrink-0 rounded-full ${
                      stage.status === 'done'
                        ? 'bg-emerald-400'
                        : stage.status === 'failed'
                          ? 'bg-critical-400'
                          : stage.status === 'running'
                            ? 'animate-pulse bg-ai-400'
                            : 'bg-forest-500'
                    }`}
                  />
                  <div>
                    <p className="text-xs font-semibold text-mist-100">{stage.label}</p>
                    <p className="text-[11px] text-mist-400">{stage.detail}</p>
                    {stage.error && <p className="text-[11px] text-critical-400">{stage.error}</p>}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </QuantumModal>
      )}

      {modal === 'result' && (
        <QuantumModal title="Signed result document" subtitle={jobId} onClose={() => setModal(null)} wide>
          {result === null ? (
            <p className="text-sm text-mist-500">The result document could not be loaded.</p>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <KPI label="Objective" value={`${Math.round(result.objectiveValue * 100)}%`} />
                <KPI label="Selected" value={`${result.selectedLocations.length} sensors`} />
                <KPI label="Constraints" value={String(result.constraintViolations.length)} />
                <KPI label="Wall time" value={`${result.executionTimeMs.toFixed(0)} ms`} />
              </div>
              <div
                className={`rounded-lg border px-3 py-2 text-xs ${
                  result.validationStatus === 'valid'
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                    : 'border-critical-500/60 bg-critical-500/15 text-critical-400'
                }`}
              >
                {result.validationSummary} ({result.validationStatus})
              </div>
              {result.selectedLocations.length > 0 ? (
                <ul className="space-y-1">
                  {result.selectedLocations.map((site) => (
                    <li key={site.id} className="flex items-center justify-between text-xs">
                      <span className="font-mono text-ai-300">{site.id}</span>
                      <span className="text-mist-400">{site.zone}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-mist-500">No decoded selection.</p>
              )}
            </div>
          )}
        </QuantumModal>
      )}
    </div>
  )
}

function KPI({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-forest-600 bg-forest-800/50 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-mist-500">{label}</p>
      <p className="mt-0.5 truncate font-mono text-sm text-mist-100">{value}</p>
    </div>
  )
}

function BackLink() {
  return (
    <Link
      to="/quantum-optimization"
      className="inline-flex items-center gap-2 text-xs font-semibold text-emerald-300 transition-colors hover:text-emerald-400"
      aria-label="Back to Quantum Optimization"
    >
      <ArrowLeft size={16} aria-hidden="true" />
      Back to Quantum Optimization
    </Link>
  )
}