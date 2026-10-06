/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import {
  Atom,
  Binary,
  Boxes,
  Clock,
  Cpu,
  ShieldCheck,
  Target,
  Timer,
  type LucideIcon,
} from 'lucide-react'
import type { BenchmarkDocument } from '../../types/benchmark'
import { benchmarkSummaryStats } from '../../lib/benchmark'

interface BenchmarkSummaryProps {
  document: BenchmarkDocument
}

const CARD_META: { icon: LucideIcon; key: keyof ReturnType<typeof benchmarkSummaryStats>; hint: string }[] = [
  { icon: Binary, key: 'problemSize', hint: 'Instance size both solvers ran' },
  { icon: Cpu, key: 'classicalSolver', hint: 'Persisted classical reference solver' },
  { icon: Atom, key: 'quantumAlgorithm', hint: 'Algorithm executed on the quantum path' },
  { icon: Boxes, key: 'classicalObjective', hint: 'Weighted utility fraction captured by the reference (higher is better)' },
  { icon: Target, key: 'quantumObjective', hint: 'Weighted utility fraction captured by QAOA (higher is better)' },
  { icon: Timer, key: 'classicalRuntime', hint: 'Stored reference wall time' },
  { icon: Clock, key: 'quantumRuntime', hint: 'Stored QAOA executor wall time (pipeline total when not persisted)' },
  { icon: ShieldCheck, key: 'constraintViolations', hint: 'Constraint violations in the QAOA decode' },
]

export function BenchmarkSummary({ document }: BenchmarkSummaryProps) {
  const stats = benchmarkSummaryStats(document)
  return (
    <section className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="Benchmark summary">
      {CARD_META.map(({ icon: Icon, key, hint }) => (
        <div key={key} className="rounded-lg border border-forest-700/60 bg-forest-800/40 px-3 py-2.5" title={hint}>
          <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-mist-500">
            <Icon size={12} className="text-forest-400" aria-hidden="true" />
            {METRIC_LABEL[key]}
          </div>
          <p className="mt-1 truncate font-mono text-sm text-mist-100" title={stats[key]}>
            {stats[key]}
          </p>
        </div>
      ))}
    </section>
  )
}

const METRIC_LABEL: Record<keyof ReturnType<typeof benchmarkSummaryStats>, string> = {
  problemSize: 'Problem Size',
  classicalSolver: 'Classical Solver',
  quantumAlgorithm: 'Quantum Algorithm',
  classicalObjective: 'Classical Objective',
  quantumObjective: 'Quantum Objective',
  classicalRuntime: 'Classical Runtime',
  quantumRuntime: 'Quantum Runtime',
  constraintViolations: 'Constraint Violations',
}