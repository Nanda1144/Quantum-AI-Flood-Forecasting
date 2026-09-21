/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Factual interpretation panel. The narrative is derived by
 * `interpretBenchmark` under strict honesty rules: it never claims a universal
 * quantum advantage, it says "equal" when outcomes are equal, it says "worse"
 * when QAOA came out below the reference, it calls out longer wall times, and
 * it marks constraint-violating results invalid for comparison.
 */

import { AlertTriangle, CheckCircle2, MinusCircle, Scale, Server, ShieldCheck } from 'lucide-react'
import type { OptimizationResult, QuantumJobSummary } from '../../types/optimization'
import { interpretBenchmark, type BenchmarkInterpretation, type BenchmarkVerdict } from '../../lib/benchmark'

interface BenchmarkInterpretationProps {
  summary: QuantumJobSummary
  result: OptimizationResult
}

const TONES: Record<BenchmarkInterpretation['tone'], { wrap: string; icon: string; title: string; text: string }> = {
  emerald: {
    wrap: 'border-emerald-500/40 bg-emerald-500/10',
    icon: 'text-emerald-400',
    title: 'text-emerald-300',
    text: 'text-emerald-200/80',
  },
  amber: {
    wrap: 'border-amber-500/40 bg-amber-500/5',
    icon: 'text-amber-400',
    title: 'text-amber-300',
    text: 'text-amber-200/80',
  },
  forest: {
    wrap: 'border-forest-600 bg-forest-800/40',
    icon: 'text-forest-400',
    title: 'text-mist-100',
    text: 'text-mist-400',
  },
  critical: {
    wrap: 'border-critical-500/60 bg-critical-500/10',
    icon: 'text-critical-400',
    title: 'text-critical-400',
    text: 'text-mist-300',
  },
}

const VERDICT_ICON: Record<BenchmarkVerdict, typeof Scale> = {
  no_result: Server,
  no_quantum: Server,
  invalid: AlertTriangle,
  quantum_better: CheckCircle2,
  equal: MinusCircle,
  classical_better: MinusCircle,
}

export function BenchmarkInterpretation({ summary, result }: BenchmarkInterpretationProps) {
  const insight = interpretBenchmark(summary, result)
  const tone = TONES[insight.tone]
  const Icon = VERDICT_ICON[insight.verdict]

  return (
    <section
      className={`flex items-start gap-3 rounded-xl border p-4 ${tone.wrap}`}
      aria-label="Interpretation"
      aria-live="polite"
    >
      <Icon size={18} className={`mt-0.5 shrink-0 ${tone.icon}`} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className={`text-sm font-bold ${tone.title}`}>{insight.headline}</p>
        <ul className="mt-1.5 space-y-1">
          {insight.lines.map((line) => (
            <li key={line} className={`text-xs leading-relaxed ${tone.text}`}>
              {line}
            </li>
          ))}
        </ul>
        <p className="mt-2 flex items-center gap-1.5 text-[11px] text-mist-500">
          <ShieldCheck size={12} aria-hidden="true" />
          No universal quantum advantage is claimed — this is one experiment against the run's stored classical reference.
        </p>
      </div>
    </section>
  )
}