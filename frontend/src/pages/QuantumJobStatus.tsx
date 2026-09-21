/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Quantum Job Status — the operator's view of a single optimization job
 * (route `/quantum/jobs/:jobId`).
 *
 * Everything rendered here is served by the optimization gateway:
 *   GET /api/optimization/:id                     → job summary (header, cards)
 *   GET /api/optimization/jobs/:id/pipeline       → execution pipeline stages
 *   GET /api/optimization/jobs/:id/result         → measurement counts + outcome
 *
 * The page polls while the job is live (`queued` / `running`) and stops at the
 * first terminal state (completed / failed / timed_out / cancelled / invalid).
 * No progress percentage is ever estimated — stages are surfaced exactly as the
 * gateway reports them, and the hardware/simulator label is derived strictly
 * from the job's stored `backendUsed` / `executionModeUsed` fields, so a
 * simulator run is never presented as hardware.
 */

import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Atom,
  Check,
  CheckCircle2,
  CircleDashed,
  ClipboardCheck,
  Clock,
  Cpu,
  Database,
  Download,
  Layers,
  Loader2,
  RefreshCw,
  Server,
  ShieldAlert,
  Target,
  Timer,
  Unplug,
  X,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { QuantumCircuitBackground } from '../components/quantum/QuantumCircuitBackground'
import { QuantumSkeleton } from '../components/quantum/QuantumSkeleton'
import { fetchJobSummary, fetchQuboPipeline, fetchQuboResult } from '../services/optimization/quboService'
import type { OptimizationResult, PipelineStage, QuantumJobSummary } from '../types/optimization'

const POLL_MS = 2500

const TERMINAL_STATUSES: ReadonlySet<string> = new Set(['completed', 'failed', 'timed_out', 'cancelled', 'invalid'])

function isTerminal(status: string): boolean {
  return TERMINAL_STATUSES.has(status)
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'notFound' }
  | { kind: 'ready'; summary: QuantumJobSummary }

/** Narrative label per gateway stage bucket — statuses are always the gateway's. */
const STAGE_NARRATIVE: Record<string, string> = {
  input: 'Request received',
  validation: 'Input validated',
  qubo: 'QUBO generated',
  hamiltonian: 'Hamiltonian created',
  qaoa: 'QAOA execution',
  measurement: 'Measurement',
  decode: 'Decode outcome',
  constraintValidation: 'Constraint validation',
  benchmark: 'Benchmark',
  final: 'Finalize',
}

const STATUS_META: Record<string, { label: string; className: string; live?: boolean }> = {
  queued: { label: 'Queued', className: 'border-amber-500/40 bg-amber-500/10 text-amber-300' },
  running: { label: 'Running', className: 'border-emerald-500/60 bg-emerald-500/15 text-emerald-300', live: true },
  completed: { label: 'Completed', className: 'border-emerald-500/60 bg-emerald-500/15 text-emerald-300' },
  failed: { label: 'Failed', className: 'border-critical-500/60 bg-critical-500/15 text-critical-400' },
  timed_out: { label: 'Timed out', className: 'border-critical-500/60 bg-critical-500/15 text-critical-400' },
  cancelled: { label: 'Cancelled', className: 'border-forest-600 bg-forest-800/70 text-mist-300' },
  invalid: { label: 'Invalid', className: 'border-critical-500/60 bg-critical-500/15 text-critical-400' },
}

function statusMeta(status: string): { label: string; className: string; live?: boolean } {
  return STATUS_META[status] ?? { label: status, className: 'border-forest-600 bg-forest-800/70 text-mist-300' }
}

const BACKEND_META: Record<string, { label: string; provider: string; hardware: boolean }> = {
  qflare_simulator_statevector: { label: 'Q-Flare · statevector', provider: 'Qiskit Aer (simulator)', hardware: false },
  aer_simulator_statevector: { label: 'Aer · statevector', provider: 'Qiskit Aer (simulator)', hardware: false },
  aer_simulator_matrix_product_state: { label: 'Aer · MPS', provider: 'Qiskit Aer (simulator)', hardware: false },
  ibm_brisbane: { label: 'ibm_brisbane', provider: 'IBM Quantum', hardware: true },
  ibm_kyiv: { label: 'ibm_kyiv', provider: 'IBM Quantum', hardware: true },
  classical: { label: 'Classical reference', provider: 'Classical reference solver', hardware: false },
}

function backendMeta(backend: string): { label: string; provider: string; hardware: boolean } {
  return BACKEND_META[backend] ?? { label: backend, provider: 'Executor backend', hardware: /^ibm_/.test(backend) }
}

const EXECUTION_MODE_LABEL: Record<string, string> = {
  simulator: 'Simulator',
  aer: 'Aer simulator',
  ibm_hardware: 'IBM Quantum hardware',
  classical: 'Classical',
}

function executionModeLabel(mode: string): string {
  return EXECUTION_MODE_LABEL[mode] ?? mode
}

interface RuntimeMeta {
  icon: LucideIcon
  tone: 'emerald' | 'amber' | 'forest'
  title: string
  text: string
}

const RUNTIME_TONE: Record<RuntimeMeta['tone'], { wrap: string; title: string; text: string; icon: string }> = {
  emerald: { wrap: 'border-emerald-500/40 bg-emerald-500/10', title: 'text-emerald-300', text: 'text-emerald-200/80', icon: 'text-emerald-400' },
  amber: { wrap: 'border-amber-500/40 bg-amber-500/5', title: 'text-amber-300', text: 'text-amber-200/80', icon: 'text-amber-400' },
  forest: { wrap: 'border-forest-600 bg-forest-800/40', title: 'text-mist-100', text: 'text-mist-400', icon: 'text-forest-400' },
}

function whereItRan(summary: QuantumJobSummary): RuntimeMeta {
  const { backendUsed, executionModeUsed, status } = summary
  if (status === 'queued' || (status === 'running' && !summary.startedAt)) {
    return { icon: Clock, tone: 'forest', title: 'Awaiting execution', text: 'The request is queued. The runtime backend and mode are reported once the job starts.' }
  }
  if (backendUsed === 'classical' || executionModeUsed === 'classical') {
    return {
      icon: Server,
      tone: 'amber',
      title: 'Ran on the classical reference solver',
      text: 'The quantum path was not used for this job — the outcome comes from the stored classical benchmark.',
    }
  }
  if (backendUsed.startsWith('ibm_') || executionModeUsed === 'ibm_hardware') {
    return {
      icon: Zap,
      tone: 'emerald',
      title: `Executed on ${backendMeta(backendUsed).label}`,
      text: 'IBM Quantum hardware recorded the shots for this result — physical device outcomes below.',
    }
  }
  return {
    icon: Server,
    tone: 'forest',
    title: `Executed on ${backendMeta(backendUsed).label}`,
    text: 'Qiskit Aer simulator — no physical quantum hardware was touched for this job.',
  }
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : '—'
}

function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return '—'
  return `${ms.toFixed(0)} ms`
}

function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

function isNotFoundError(error: unknown): boolean {
  if (typeof error === 'object' && error !== null) {
    const code = (error as { code?: unknown }).code
    if (code === 'JOB_NOT_FOUND') return true
  }
  return false
}

function toMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'message' in error) {
    return String((error as { message: unknown }).message)
  }
  return error instanceof Error ? error.message : String(error)
}

export function QuantumJobStatus() {
  const { jobId = '' } = useParams()
  const navigate = useNavigate()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [stages, setStages] = useState<PipelineStage[] | null>(null)
  const [result, setResult] = useState<OptimizationResult | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined

    const loadOnce = async (): Promise<string | null> => {
      try {
        const [summary, loadedStages] = await Promise.all([
          fetchJobSummary(jobId),
          fetchQuboPipeline(jobId).catch(() => null),
        ])
        if (cancelled) return null
        setState({ kind: 'ready', summary })
        setStages(loadedStages && loadedStages.length > 0 ? loadedStages : null)
        if (summary.status === 'completed') {
          fetchQuboResult(jobId)
            .then((loaded) => {
              if (!cancelled) setResult(loaded)
            })
            .catch(() => undefined)
        }
        return summary.status
      } catch (error) {
        if (cancelled) return null
        setState((previous) => {
          if (previous.kind === 'ready') return previous
          if (isNotFoundError(error)) return { kind: 'notFound' }
          return { kind: 'error', message: toMessage(error) }
        })
        return null
      }
    }

    const poll = async () => {
      const status = await loadOnce()
      if (cancelled) return
      if (status !== null && !isTerminal(status)) {
        timer = window.setTimeout(() => void poll(), POLL_MS)
      }
    }

    void poll()
    return () => {
      cancelled = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [jobId, refreshKey])

  /* ---- Non-ready states ------------------------------------------------- */

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

  if (state.kind === 'notFound') {
    return (
      <div className="min-h-screen px-4 pb-16 pt-6 sm:px-6 lg:px-10">
        <QuantumCircuitBackground />
        <div className="mx-auto max-w-[1440px] space-y-5">
          <BackLink />
          <div className="glass-card flex items-start gap-3 rounded-xl border border-critical-500/60 bg-critical-500/15 p-5">
            <Unplug size={20} className="mt-0.5 shrink-0 text-critical-400" aria-hidden="true" />
            <div>
              <p className="text-sm font-bold text-critical-400">Job not found</p>
              <p className="mt-1 text-xs text-mist-300">
                No optimization job with id “{jobId}” is visible to your account. Jobs are scoped to their owner.
              </p>
            </div>
          </div>
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
              <p className="text-sm font-bold text-critical-400">Could not load the job status</p>
              <p className="mt-1 text-xs text-mist-300">{state.message}</p>
            </div>
          </div>
          <RefreshButton onClick={() => setRefreshKey((key) => key + 1)} />
        </div>
      </div>
    )
  }

  const { summary } = state
  const meta = statusMeta(summary.status)
  const runtime = whereItRan(summary)
  const tone = RUNTIME_TONE[runtime.tone]
  const backend = backendMeta(summary.backendUsed)
  const failedStage = stages?.find((stage) => stage.status === 'failed') ?? null
  const showErrorPanel = summary.status === 'failed' || summary.status === 'timed_out' || summary.status === 'invalid'
  const retrySafe = summary.status === 'failed' || summary.status === 'timed_out'
  const jobCompleted = summary.status === 'completed'
  const storage = summary.quboStorage

  const cards: { icon: LucideIcon; label: string; value: string; hint?: string }[] = [
    { icon: Atom, label: 'Algorithm', value: summary.algorithm },
    { icon: Cpu, label: 'Backend', value: backend.label, hint: backend.provider },
    { icon: Layers, label: 'Qubits', value: summary.qubitCount !== null && summary.qubitCount !== undefined ? String(summary.qubitCount) : '—' },
    { icon: Zap, label: 'Shots', value: summary.objectiveConfiguration?.shots != null ? String(summary.objectiveConfiguration.shots) : '—' },
    { icon: Layers, label: 'QAOA layers', value: summary.objectiveConfiguration?.layers != null ? String(summary.objectiveConfiguration.layers) : '—' },
    { icon: Timer, label: 'Runtime', value: formatMs(summary.resultSummary?.executionTimeMs) },
    { icon: Clock, label: 'Started', value: formatDateTime(summary.startedAt) },
    { icon: CheckCircle2, label: 'Completed', value: formatDateTime(summary.completedAt) },
  ]

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
              <h1 className="text-xl font-semibold tracking-tight text-mist-50">Quantum Job Status</h1>
              <p className="text-sm text-mist-500">Live execution pipeline, measurement and job record — nothing hidden</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span
              className="inline-flex items-center gap-2 rounded-lg border border-forest-600/70 bg-forest-800/70 px-2.5 py-1 text-xs"
              title="Optimization job identity"
            >
              <span className="uppercase tracking-wide text-mist-600">Optimization job</span>
              <span className="font-mono text-mist-300">{summary.jobId}</span>
            </span>
            <span
              className="inline-flex items-center gap-2 rounded-lg border border-forest-600/70 bg-forest-800/70 px-2.5 py-1 text-xs"
              title="QUBO artifact reference registered with the quantum service"
            >
              <span className="uppercase tracking-wide text-mist-600">Quantum job</span>
              <span className="font-mono text-mist-300">{summary.quboArtifactReference ?? 'pending'}</span>
            </span>
            <span className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium ${meta.className}`}>
              {meta.live && <span className="size-1.5 animate-pulse rounded-full bg-emerald-400" aria-hidden="true" />}
              {meta.label}
            </span>
            <span className="rounded-lg border border-forest-600/70 bg-forest-800/70 px-2.5 py-1 text-xs text-mist-300">
              {executionModeLabel(summary.executionModeUsed)}
            </span>
            <span
              className="rounded-lg border border-forest-600/70 bg-forest-800/70 px-2.5 py-1 text-xs text-mist-300"
              title={backend.provider}
            >
              {backend.label}
            </span>
            {storage && (
              <span
                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium ${
                  storage === 'artifact'
                    ? 'border-amber-500/40 bg-amber-500/10 text-amber-300'
                    : 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                }`}
              >
                <Database size={12} aria-hidden="true" />
                {storage} QUBO
              </span>
            )}
          </div>
        </header>

        {/* ---- Where it ran + fallback notices ---- */}
        <div className={`flex items-start gap-3 rounded-xl border p-4 ${tone.wrap}`}>
          <runtime.icon size={18} className={`mt-0.5 shrink-0 ${tone.icon}`} aria-hidden="true" />
          <div>
            <p className={`text-sm font-bold ${tone.title}`}>{runtime.title}</p>
            <p className={`mt-0.5 text-xs ${tone.text}`}>{runtime.text}</p>
          </div>
        </div>

        {summary.fallbackApplied && (
          <div className="glass-card flex items-start gap-3 rounded-xl border border-amber-500/40 bg-amber-500/5 p-4">
            <ShieldAlert size={18} className="mt-0.5 shrink-0 text-amber-400" aria-hidden="true" />
            <div>
              <p className="text-sm font-bold text-amber-300">Fallback applied</p>
              <p className="mt-0.5 text-xs text-mist-300">
                {summary.executionMode} → {executionModeLabel(summary.executionModeUsed)} (policy: {summary.fallbackPolicy}).
                {summary.fallbackReason ? ` ${summary.fallbackReason}` : ''}
              </p>
            </div>
          </div>
        )}

        {summary.deletedAt && (
          <div className="glass-card flex items-start gap-3 rounded-xl border border-forest-600 bg-forest-800/40 p-4">
            <AlertTriangle size={18} className="mt-0.5 shrink-0 text-forest-400" aria-hidden="true" />
            <div>
              <p className="text-sm font-bold text-mist-100">Job soft-deleted</p>
              <p className="mt-0.5 text-xs text-mist-400">
                Deleted by {summary.deletedBy ?? 'unknown'} on {formatDateTime(summary.deletedAt)}
                {summary.deleteReason ? ` — ${summary.deleteReason}` : ''}.
              </p>
            </div>
          </div>
        )}

        {summary.validationStatus === 'invalid' && (
          <div className="glass-card flex items-start gap-3 rounded-xl border border-critical-500/60 bg-critical-500/10 p-4">
            <AlertTriangle size={18} className="mt-0.5 shrink-0 text-critical-400" aria-hidden="true" />
            <div>
              <p className="text-sm font-bold text-critical-400">Invalid result</p>
              <p className="mt-0.5 text-xs text-mist-300">{summary.validationSummary ?? 'Constraint validation failed for this job.'}</p>
            </div>
          </div>
        )}

        {/* ---- Info cards ---- */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {cards.map((card) => (
            <InfoCard key={card.label} icon={card.icon} label={card.label} value={card.value} hint={card.hint} />
          ))}
        </div>

        {/* ---- Pipeline + measurement ---- */}
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          {/* ---- Pipeline ---- */}
          <section
            className="glass-card"
            aria-label="Execution pipeline"
          >
            <div className="flex items-center gap-2">
              <Activity size={16} className="text-ai-300" aria-hidden="true" />
              <div>
                <h2 className="text-sm font-semibold text-mist-100">Execution pipeline</h2>
                <p className="text-[11px] text-mist-500">Stages reported verbatim by the gateway — no progress is estimated</p>
              </div>
            </div>
            <div className="mt-4">
              {stages === null || stages.length === 0 ? (
                <div className="rounded-lg border border-dashed border-forest-600 px-3 py-5 text-center text-xs text-mist-500">
                  {summary.status === 'queued' || summary.status === 'running'
                    ? 'Pipeline has not started — the request is still being processed.'
                    : 'No pipeline stages were recorded for this job.'}
                </div>
              ) : (
                <ol className="space-y-1.5">
                  {stages.map((stage, index) => (
                    <StageRow key={stage.id} index={index + 1} stage={stage} />
                  ))}
                </ol>
              )}
            </div>
          </section>

          {/* ---- Measurement ---- */}
          <section
            className="glass-card"
            aria-label="Measurement outcomes"
          >
            <div className="flex items-center gap-2">
              <Target size={16} className="text-ai-300" aria-hidden="true" />
              <div>
                <h2 className="text-sm font-semibold text-mist-100">Measurement</h2>
                <p className="text-[11px] text-mist-500">Top candidate bitstrings by observed count</p>
              </div>
            </div>
            <div className="mt-4 space-y-3">
              {jobCompleted && result === null && (
                <p className="text-xs text-mist-500">The result document could not be loaded — retry with the refresh action.</p>
              )}
              {!jobCompleted && (
                <div className="rounded-lg border border-dashed border-forest-600 px-3 py-5 text-center text-xs text-mist-500">
                  Measurements appear here once the job completes.
                </div>
              )}
              {result !== null && (
                <>
                  <div className="grid grid-cols-2 gap-2">
                    <MiniStat label="Objective" value={formatPercent(result.objectiveValue)} />
                    <MiniStat label="Selected" value={`${result.selectedLocations.length} sensors`} />
                    <MiniStat label="Violations" value={String(result.constraintViolations.length)} />
                    <MiniStat label="Wall time" value={formatMs(result.executionTimeMs)} />
                  </div>

                  {result.measurementCounts.length === 0 ? (
                    <p className="text-xs text-mist-500">No measurement outcomes were recorded for this job.</p>
                  ) : (
                    <>
                      <div className="grid gap-3 sm:grid-cols-2">
                        {result.measurementCounts.map((entry) => {
                          const decoded = result.bitstring === entry.bitstring
                          const probability = result.shots > 0 ? entry.count / result.shots : 0
                          const width = `width: ${(entry.count / Math.max(1, ...result.measurementCounts.map((item) => item.count))) * 100}%`
                          return (
                            <div
                              key={entry.bitstring}
                              className={`rounded-lg border px-3 py-2 ${
                                decoded
                                  ? 'border-emerald-500/50 bg-emerald-500/10'
                                  : 'border-forest-600 bg-forest-800/40'
                              }`}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <code className={`truncate font-mono text-[11px] ${decoded ? 'text-emerald-300' : 'text-ai-300'}`}>
                                  {entry.bitstring}
                                </code>
                                <span className="font-mono text-[11px] text-mist-500">
                                  {entry.count}/{result.shots} · {formatPercent(probability)}
                                </span>
                              </div>
                              <div className="mt-1.5 h-1.5 rounded-full bg-forest-900">
                                <div
                                  className={`h-full rounded-full ${decoded ? 'bg-emerald-400' : 'bg-ai-400'}`}
                                  style={{ width }}
                                />
                              </div>
                              {decoded && (
                                <p className="mt-1.5 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-emerald-300">
                                  <CheckCircle2 size={11} aria-hidden="true" />
                                  Decoded solution · objective {formatPercent(result.objectiveValue)}
                                </p>
                              )}
                            </div>
                          )
                        })}
                      </div>
                      <p className="text-[11px] text-mist-600">
                        Objective value is only reported for the decoded solution; the remaining bitstrings are shown by observed
                        count alone.
                      </p>
                    </>
                  )}
                </>
              )}
            </div>
          </section>
        </div>

        {/* ---- Error panel ---- */}
        {showErrorPanel && (
          <div className="glass-card flex items-start gap-3 rounded-xl border border-critical-500/60 bg-critical-500/10 p-4">
            <AlertTriangle size={18} className="mt-0.5 shrink-0 text-critical-400" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-bold text-critical-400">
                {summary.status === 'timed_out' ? 'Job timed out' : summary.status === 'invalid' ? 'Job failed validation' : 'Job failed'}
              </p>
              <p className="mt-0.5 text-xs text-mist-300">
                {summary.errorMessage ??
                  failedStage?.error ??
                  'The gateway recorded a failure without further detail. Check the pipeline for the failing stage.'}
              </p>
              {failedStage && (
                <p className="mt-1.5 text-[11px] text-mist-500">
                  Failing stage: <span className="text-critical-300">{STAGE_NARRATIVE[failedStage.id] ?? failedStage.label}</span>
                  {failedStage.error ? ` — ${failedStage.error}` : ''}
                </p>
              )}
              {retrySafe && (
                <button
                  type="button"
                  onClick={() => navigate('/quantum-optimization')}
                  className="mt-3 inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
                >
                  <RefreshCw size={14} className="text-ai-300" aria-hidden="true" />
                  Re-run from the execution console
                </button>
              )}
              {retrySafe && (
                <p className="mt-1.5 text-[11px] text-mist-600">
                  Runs are write-once — the request is re-submitted from the console. A completed result is never rewritten.
                </p>
              )}
            </div>
          </div>
        )}

        {/* ---- Actions ---- */}
        <div className="glass-card flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => navigate('/quantum-optimization')}
            className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
          >
            <ArrowLeft size={15} className="text-ai-300" aria-hidden="true" />
            Quantum Optimization
          </button>
          <button
            type="button"
            onClick={() => setRefreshKey((key) => key + 1)}
            className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
          >
            <RefreshCw size={15} className="text-ai-300" aria-hidden="true" />
            Refresh
          </button>
          <Link
            to={`/qubo-visualization/${summary.jobId}`}
            className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
          >
            <Database size={15} className="text-ai-300" aria-hidden="true" />
            Open QUBO formulation
          </Link>
          {jobCompleted && (
            <Link
              to={`/optimization/${encodeURIComponent(summary.jobId)}/result`}
              className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/50 bg-emerald-500/10 px-3 py-2 text-sm font-semibold text-emerald-300 transition-colors hover:border-emerald-400 hover:text-emerald-200"
            >
              <ClipboardCheck size={15} aria-hidden="true" />
              Open decision result
            </Link>
          )}
          {jobCompleted && result && (
            <a
              href={`data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(result, null, 2))}`}
              download={`result-${summary.jobId}.json`}
              className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
            >
              <Download size={15} className="text-ai-300" aria-hidden="true" />
              Export result
            </a>
          )}
        </div>

        <p className="text-center text-[11px] text-mist-600">
          {backend.provider} · {executionModeLabel(summary.executionModeUsed)} · auto-refresh {isTerminal(summary.status) ? 'paused (terminal state)' : `every ${POLL_MS / 1000}s`}
        </p>
      </div>
    </div>
  )
}

function StageRow({ index, stage }: { index: number; stage: PipelineStage }) {
  const icon =
    stage.status === 'running' ? (
      <Loader2 size={15} className="animate-spin" aria-hidden="true" />
    ) : stage.status === 'done' ? (
      <Check size={15} aria-hidden="true" />
    ) : stage.status === 'failed' ? (
      <X size={15} aria-hidden="true" />
    ) : (
      <CircleDashed size={15} aria-hidden="true" />
    )

  const iconStyle =
    stage.status === 'pending'
      ? 'border-forest-600 text-forest-500'
      : stage.status === 'running'
        ? 'border-emerald-500/60 bg-emerald-500/15 text-emerald-300'
        : stage.status === 'done'
          ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
          : 'border-critical-500/60 bg-critical-500/15 text-critical-400'

  const narrative =
    stage.id === 'final' ? (stage.status === 'done' ? 'Completed' : STAGE_NARRATIVE[stage.id]) : STAGE_NARRATIVE[stage.id] ?? stage.label

  return (
    <li
      className={`flex items-start gap-3 rounded-lg border px-3 py-2 transition-colors ${
        stage.status === 'failed'
          ? 'border-critical-500/40 bg-critical-500/10'
          : stage.status === 'running'
            ? 'border-emerald-500/40 bg-emerald-500/10'
            : 'border-forest-700/60 bg-forest-800/40'
      }`}
    >
      <span className={`mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md border ${iconStyle}`}>{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <p className="text-sm font-medium text-mist-100">
            <span className="mr-2 font-mono text-[11px] text-mist-500">{index}</span>
            {narrative}
          </p>
          <span className="text-[11px] uppercase tracking-wide text-mist-500">{stage.status}</span>
        </div>
        <p className="mt-0.5 text-xs text-mist-300">
          <span className="text-mist-500">{stage.label}:</span> {stage.detail}
        </p>
        {stage.error && <p className="mt-0.5 text-xs text-critical-400">{stage.error}</p>}
      </div>
    </li>
  )
}

function InfoCard({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof Atom
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="rounded-lg border border-forest-700/60 bg-forest-800/40 px-3 py-2.5" title={hint}>
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-mist-500">
        <Icon size={12} className="text-forest-400" aria-hidden="true" />
        {label}
      </div>
      <p className="mt-1 truncate font-mono text-sm text-mist-100">{value}</p>
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-forest-600 bg-forest-800/50 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-mist-500">{label}</p>
      <p className="mt-0.5 truncate font-mono text-sm text-mist-100">{value}</p>
    </div>
  )
}

function RefreshButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
    >
      <RefreshCw size={15} className="text-ai-300" aria-hidden="true" />
      Retry load
    </button>
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