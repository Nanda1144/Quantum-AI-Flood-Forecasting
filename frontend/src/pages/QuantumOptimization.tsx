/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { ArrowLeft } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import { QuantumCircuitBackground } from '../components/quantum/QuantumCircuitBackground'
import { QuantumHeader } from '../components/quantum/QuantumHeader'
import { QuantumSkeleton } from '../components/quantum/QuantumSkeleton'
import { QuantumModals } from '../components/quantum/QuantumModals'
import { ProblemConfigPanel } from '../components/quantum/panels/ProblemConfigPanel'
import { ObjectiveWeightsPanel } from '../components/quantum/panels/ObjectiveWeightsPanel'
import { ConstraintsPanel } from '../components/quantum/panels/ConstraintsPanel'
import { ExecutionPanel } from '../components/quantum/panels/ExecutionPanel'
import { PipelinePanel } from '../components/quantum/panels/PipelinePanel'
import { ResultSummaryPanel } from '../components/quantum/panels/ResultSummaryPanel'
import { ActionsPanel } from '../components/quantum/panels/ActionsPanel'
import { useQuantumOptimization } from '../hooks/useQuantumOptimization'
import { RISK_PROFILES } from '../lib/quantum'
import type { RiskProfile } from '../types/optimization'

interface LocationState {
  forecastId?: string
  priority?: string
}

export function QuantumOptimization() {
  const location = useLocation()
  const state = (location.state ?? {}) as LocationState
  const suggestedPriority = state.priority?.toUpperCase()
  const initialRisk: RiskProfile | undefined = RISK_PROFILES.includes(suggestedPriority as RiskProfile)
    ? (suggestedPriority as RiskProfile)
    : undefined

  const q = useQuantumOptimization({
    forecastReference: state.forecastId || undefined,
    riskProfile: initialRisk,
  })

  const anyWeight = Object.values(q.weights).some((value) => value > 0)
  const budgetBlocked =
    q.config.budgetK !== null &&
    q.minCandidateCostK !== null &&
    q.config.budgetK < q.minCandidateCostK
  const budgetNote = budgetBlocked
    ? `Budget $${q.config.budgetK}k is below the cheapest candidate site cost ($${Math.ceil(q.minCandidateCostK ?? 0)}k) — raise the budget or clear it to run.`
    : null
  const canRun =
    q.runState !== 'running' &&
    anyWeight &&
    !budgetBlocked &&
    q.config.maxSensors > 0 &&
    q.config.maxSensors <= q.config.candidateCount

  return (
    <div className="min-h-screen px-4 pb-16 pt-6 sm:px-6 lg:px-10">
      <QuantumCircuitBackground />
      <div className="mx-auto max-w-[1440px] space-y-5">
        <LinkToAnalytics />

        <QuantumHeader
          adapterMode={q.adapterMode}
          inputs={q.inputs}
          forecastReference={q.config.forecastReference}
          riskProfile={q.config.riskProfile}
        />

        {q.adapterMode === null ? (
          <QuantumSkeleton />
        ) : (
          <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
            <div className="space-y-5">
              <ProblemConfigPanel
                config={q.config}
                updateConfig={q.updateConfig}
                candidateCount={q.config.candidateCount}
                budgetK={q.config.budgetK}
                maxSensors={q.config.maxSensors}
                inputsLoading={q.inputsLoading}
              />
              <ObjectiveWeightsPanel
                problemType={q.config.problemType}
                weights={q.weights}
                normalizeWeights={q.normalizeWeights}
                onUpdateWeight={q.updateWeights}
                onToggleNormalize={q.toggleNormalize}
                onReset={q.resetWeights}
              />
              <ConstraintsPanel
                config={q.config}
                updateConfig={q.updateConfig}
                coverageRequirements={q.coverageRequirements}
                onAdd={q.addCoverageRequirement}
                onRemove={q.removeCoverageRequirement}
                inputs={q.inputs}
              />
            </div>

            <div className="space-y-5">
              <ExecutionPanel
                config={q.config}
                updateConfig={q.updateConfig}
                runState={q.runState}
                canRun={canRun}
                runError={q.runError}
                runNote={budgetNote}
                onRun={q.startRun}
                onCancel={q.cancelRun}
              />
              <PipelinePanel stages={q.stages} runState={q.runState} />
              <ResultSummaryPanel result={q.result} runState={q.runState} />
              <ActionsPanel hasResult={q.result !== null} adapterMode={q.adapterMode} onOpen={q.openModal} jobId={q.result?.jobId} />
            </div>
          </div>
        )}
      </div>

      <QuantumModals active={q.activeModal} result={q.result} onClose={q.closeModal} />
    </div>
  )
}

function LinkToAnalytics() {
  return (
    <Link
      to="/"
      className="inline-flex items-center gap-2 text-xs font-semibold text-emerald-300 transition-colors hover:text-emerald-400"
      aria-label="Back to AI Analytics"
    >
      <ArrowLeft size={16} aria-hidden="true" />
      Back to AI Analytics
    </Link>
  )
}