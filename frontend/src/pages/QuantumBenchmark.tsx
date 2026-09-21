/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Quantum vs Classical Benchmark — the researcher's comparison page
 * (route `/quantum-benchmark`).
 *
 * Reads the persisted experiment ledger through the optimization gateway:
 *   GET /api/optimization/jobs            → all visible jobs (summaries)
 *   GET /api/optimization/jobs/:id/result → the selected run's full document
 *
 * Everything rendered — objective, runtime, violations, approximation ratio,
 * configuration — is stored data served verbatim by the backend. The
 * interpretation panel follows strict honesty rules (equal → "equal", worse →
 * "worse", violations → invalid for comparison) and never claims a universal
 * quantum advantage.
 */

import { Link } from 'react-router-dom'
import { FlaskConical, Rocket } from 'lucide-react'
import { QuantumCircuitBackground } from '../components/quantum/QuantumCircuitBackground'
import { StateBanner } from '../components/ui/StateBanner'
import { Skeleton } from '../components/ui/Skeleton'
import { BenchmarkHeader } from '../components/benchmark/BenchmarkHeader'
import { BenchmarkHistory } from '../components/benchmark/BenchmarkHistory'
import { BenchmarkSummary } from '../components/benchmark/BenchmarkSummary'
import { BenchmarkTable } from '../components/benchmark/BenchmarkTable'
import { BenchmarkCharts } from '../components/benchmark/BenchmarkCharts'
import { BenchmarkInterpretation } from '../components/benchmark/BenchmarkInterpretation'
import { ExperimentConfig } from '../components/benchmark/ExperimentConfig'
import { BenchmarkExport } from '../components/benchmark/BenchmarkExport'
import { useQuantumBenchmark } from '../hooks/useQuantumBenchmark'

export function QuantumBenchmark() {
  const {
    ledger,
    completedRuns,
    sampleMode,
    loading,
    error,
    selectedJobId,
    selectedSummary,
    result,
    resultLoading,
    resultError,
    refresh,
    selectRun,
  } = useQuantumBenchmark()

  const newestCompletedAt =
    completedRuns.length > 0 ? completedRuns[completedRuns.length - 1].completedAt ?? completedRuns[0].createdAt : null

  return (
    <div className="min-h-screen px-4 pb-16 pt-6 sm:px-6 lg:px-10">
      <QuantumCircuitBackground />
      <div className="mx-auto max-w-[1440px] space-y-5">
        <BenchmarkHeader
          experimentCount={completedRuns.length}
          newestCompletedAt={newestCompletedAt}
          refreshing={loading}
          onRefresh={refresh}
        />

        {sampleMode && (
          <StateBanner
            kind="demo"
            title="Sample data mode is active"
            message="VITE_USE_MOCK_DATA routes the Optimization console to the development simulator. Those runs are session-local and never reach the gateway, so the ledger below shows only real persisted experiments."
          />
        )}

        {loading && <BenchmarkLoading />}

        {!loading && error && (
          <StateBanner
            kind="error"
            title="Could not load the experiment ledger"
            message={`${error} — the gateway was unreachable, so no benchmark was shown (no fabricated history is ever rendered).`}
            onRetry={refresh}
          />
        )}

        {!loading && !error && completedRuns.length === 0 && (
          <StateBanner
            kind="empty"
            title="No completed experiments to compare yet"
            message="Run an optimization from the execution console; completed runs with a stored result will appear here, newest first."
          >
            <Link
              to="/quantum-optimization"
              className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
            >
              <Rocket size={15} className="text-ai-300" aria-hidden="true" />
              Open the Quantum Optimization console
            </Link>
          </StateBanner>
        )}

        {!loading && !error && completedRuns.length > 0 && (
          <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,4fr)_minmax(0,8fr)]">
            <BenchmarkHistory ledger={ledger ?? []} selectedJobId={selectedJobId} onSelect={selectRun} />

            <div className="min-w-0 space-y-5">
              {selectedSummary === null && !resultLoading && (
                <StateBanner
                  kind="empty"
                  title="Nothing selected"
                  message="Pick an experiment from the history list to see its comparison."
                />
              )}

              {selectedSummary && resultLoading && (
                <div className="space-y-5">
                  <Skeleton className="h-20 w-full" />
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    {Array.from({ length: 8 }).map((_, index) => (
                      <Skeleton key={index} className="h-16 w-full" />
                    ))}
                  </div>
                  <Skeleton className="h-40 w-full" />
                </div>
              )}

              {selectedSummary && !resultLoading && !result && resultError && (
                <StateBanner
                  kind="error"
                  title="Could not load the selected run"
                  message={resultError}
                  onRetry={refresh}
                />
              )}

              {selectedSummary && !resultLoading && result && (
                <>
                  <BenchmarkInterpretation summary={selectedSummary} result={result} />
                  <BenchmarkSummary summary={selectedSummary} result={result} />
                  <BenchmarkTable summary={selectedSummary} result={result} />
                  <BenchmarkCharts result={result} />
                  <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
                    <ExperimentConfig summary={selectedSummary} result={result} />
                    <BenchmarkExport summary={selectedSummary} result={result} />
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        <p className="flex items-center justify-center gap-1.5 text-center text-[11px] text-mist-600">
          <FlaskConical size={12} aria-hidden="true" />
          Every figure on this page is data stored with the experiment — nothing is computed or claimed by the UI.
        </p>
      </div>
    </div>
  )
}

function BenchmarkLoading() {
  return (
    <div role="status" aria-label="Loading the experiment ledger" className="space-y-5">
      <span className="sr-only">Loading benchmark experiments…</span>
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,4fr)_minmax(0,8fr)]">
        <div className="space-y-2 rounded-xl border border-forest-700/50 p-3">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-14 w-full" />
          ))}
        </div>
        <div className="space-y-5">
          <Skeleton className="h-24 w-full" />
          {Array.from({ length: 8 }).map((_, index) => (
            <Skeleton key={index} className="h-12 w-full rounded-none" />
          ))}
        </div>
      </div>
    </div>
  )
}