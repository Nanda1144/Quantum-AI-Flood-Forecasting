/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * The single most important element on the result page: an explicit operational
 * verdict. A valid result is labelled as validated; an infeasible result is
 * labelled as NOT operationally recommended and must never read like a
 * recommendation.
 */

import { BadgeCheck, Ban, CircleDashed } from 'lucide-react'

interface ValidationBannerProps {
  validationStatus: 'valid' | 'invalid' | null
  validationSummary: string | null
  violationCount: number
}

export function ValidationBanner({ validationStatus, validationSummary, violationCount }: ValidationBannerProps) {
  if (validationStatus === null) {
    return (
      <div role="status" className="flex items-start gap-3 rounded-xl border border-forest-600 bg-forest-800/60 px-4 py-3.5">
        <CircleDashed size={20} className="mt-0.5 shrink-0 text-mist-500" aria-hidden="true" />
        <div>
          <p className="text-sm font-bold text-mist-300">VALIDATION PENDING</p>
          <p className="mt-0.5 text-xs text-mist-300">
            This job has not produced a validated result yet — no operational recommendation is available.
          </p>
        </div>
      </div>
    )
  }

  const valid = validationStatus === 'valid' && violationCount === 0

  if (valid) {
    return (
      <div role="status" className="flex items-start gap-3 rounded-xl border border-emerald-500/50 bg-emerald-500/10 px-4 py-3.5">
        <BadgeCheck size={20} className="mt-0.5 shrink-0 text-emerald-300" aria-hidden="true" />
        <div>
          <p className="text-sm font-bold text-emerald-300">VALIDATED OPTIMIZATION RESULT</p>
          <p className="mt-0.5 text-xs text-mist-300">
            {validationSummary || 'Constraint validation passed for the decoded selection.'} Decision support only — the operator
            confirms any deployment.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border border-critical-500/60 bg-critical-500/15 px-4 py-3.5">
      <Ban size={20} className="mt-0.5 shrink-0 text-critical-400" aria-hidden="true" />
      <div>
        <p className="text-sm font-bold text-critical-400">INVALID SOLUTION — NOT OPERATIONALLY RECOMMENDED</p>
        <p className="mt-0.5 text-xs text-mist-300">
          {validationSummary ||
            `The decoded selection recorded ${violationCount} constraint violation${violationCount === 1 ? '' : 's'}.`}{' '}
          This result is shown for transparency only and must not be treated as a deployment recommendation.
        </p>
      </div>
    </div>
  )
}
