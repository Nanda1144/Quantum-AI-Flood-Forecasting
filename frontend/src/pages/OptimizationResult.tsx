/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Optimization Result — the operator's decision document
 * (route `/optimization/:id/result`).
 *
 * Everything rendered is served verbatim by the optimization gateway:
 *   GET /api/optimization/:id              → verdict, configuration, timestamps
 *   GET /api/optimization/jobs/:id/result  → the stored result document
 *   GET /api/optimization/inputs           → GIS candidates for the map/table
 *
 * The page never recommends an infeasible selection: a validation banner makes
 * the operational verdict explicit, invalid results are labelled as such, and
 * the decision explanation is assembled only from the stored inputs. Export
 * downloads the backend-generated document — it is never rebuilt in React.
 */

import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, ClipboardCheck, RefreshCw, Unplug } from 'lucide-react'
import { QuantumCircuitBackground } from '../components/quantum/QuantumCircuitBackground'
import { QuantumSkeleton } from '../components/quantum/QuantumSkeleton'
import { StateBanner } from '../components/ui/StateBanner'
import { OptimizationResultHeader } from '../components/optimizationResult/OptimizationResultHeader'
import { ValidationBanner } from '../components/optimizationResult/ValidationBanner'
import { ResultSummaryCards } from '../components/optimizationResult/ResultSummaryCards'
import { SelectedLocationsSection } from '../components/optimizationResult/SelectedLocationsSection'
import { DecisionExplanation } from '../components/optimizationResult/DecisionExplanation'
import { BenchmarkComparison } from '../components/optimizationResult/BenchmarkComparison'
import { ResultActions } from '../components/optimizationResult/ResultActions'
import { useOptimizationResult } from '../hooks/useOptimizationResult'

export function OptimizationResult() {
  const { id = '' } = useParams()
  const {
    summary,
    result,
    candidates,
    candidatesError,
    loading,
    error,
    notFound,
    exportState,
    exportError,
    refresh,
    downloadExport,
  } = useOptimizationResult(id)

  if (loading) {
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

  if (notFound) {
    return (
      <div className="min-h-screen px-4 pb-16 pt-6 sm:px-6 lg:px-10">
        <QuantumCircuitBackground />
        <div className="mx-auto max-w-[1440px] space-y-5">
          <BackLink />
          <div className="glass-card flex items-start gap-3 rounded-xl border border-critical-500/60 bg-critical-500/15 p-5">
            <Unplug size={20} className="mt-0.5 shrink-0 text-critical-400" aria-hidden="true" />
            <div>
              <p className="text-sm font-bold text-critical-400">Optimization result not found</p>
              <p className="mt-1 text-xs text-mist-300">
                No optimization job with id “{id}” is visible to your account. Jobs are scoped to their owner.
              </p>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (error || !summary) {
    return (
      <div className="min-h-screen px-4 pb-16 pt-6 sm:px-6 lg:px-10">
        <QuantumCircuitBackground />
        <div className="mx-auto max-w-[1440px] space-y-5">
          <BackLink />
          <StateBanner
            kind="error"
            title="Could not load the optimization result"
            message={`${error ?? 'The gateway returned no summary for this job'} — no document is fabricated when the gateway is unreachable.`}
            onRetry={refresh}
          />
        </div>
      </div>
    )
  }

  const validationStatus = summary.validationStatus ?? result?.validationStatus ?? null
  const violationCount = result?.constraintViolations.length ?? summary.resultSummary.constraintViolationCount ?? 0
  const hasResult = summary.status === 'completed' && result !== null

  return (
    <div className="min-h-screen px-4 pb-16 pt-6 sm:px-6 lg:px-10">
      <QuantumCircuitBackground />
      <div className="mx-auto max-w-[1440px] space-y-5">
        <BackLink />

        <OptimizationResultHeader summary={summary} />

        <ValidationBanner
          validationStatus={validationStatus}
          validationSummary={summary.validationSummary ?? result?.validationSummary ?? null}
          violationCount={violationCount}
        />

        {summary.fallbackApplied && (
          <StateBanner
            kind="stale"
            title="Execution fallback applied"
            message={`${summary.fallbackReason ?? 'The configured quantum path did not execute and the pipeline completed through the stored default path.'} The backend and mode chips above report where this job actually ran.`}
          />
        )}

        {!hasResult && (
          <StateBanner
            kind="empty"
            title="No completed result document"
            message={`This job is '${summary.status}' — the decision document appears once the pipeline reaches a completed state.`}
          >
            <Link
              to={`/quantum/jobs/${encodeURIComponent(summary.jobId)}`}
              className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
            >
              <ClipboardCheck size={15} className="text-ai-300" aria-hidden="true" />
              Open the quantum job status
            </Link>
          </StateBanner>
        )}

        {hasResult && result && (
          <>
            <ResultSummaryCards summary={summary} result={result} />

            {candidatesError && (
              <StateBanner
                kind="unavailable"
                title="Candidate geometry unavailable"
                message={`${candidatesError} — the location table falls back to the decoded selection without coordinates; no geometry is invented.`}
                onRetry={refresh}
              />
            )}

            <SelectedLocationsSection candidates={candidates} result={result} />

            <DecisionExplanation summary={summary} result={result} />

            <BenchmarkComparison summary={summary} result={result} />

            <ResultActions
              jobId={summary.jobId}
              exportState={exportState}
              exportError={exportError}
              onExport={downloadExport}
            />
          </>
        )}

        <p className="flex items-center justify-center gap-1.5 text-center text-[11px] text-mist-600">
          <RefreshCw size={12} aria-hidden="true" />
          Decision support only — every figure is stored with the job and no autonomous action is taken.
        </p>
      </div>
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
