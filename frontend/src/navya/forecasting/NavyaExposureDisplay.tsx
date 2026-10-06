/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Exposure and response-priority panel for the risk dashboard.
 *
 * Renders the *availability* of population exposure, infrastructure exposure and
 * the Q-FLARE response priority — never a value, because no value is sent. See
 * `exposure.ts` for the evidence and the status vocabulary.
 *
 * ## What a reader must be able to tell at a glance
 *
 * A green number next to "Population exposure" is the fastest way to imply an
 * operational fact that does not exist. This panel is built so that cannot
 * happen: each row is a status badge, a dash in the value slot, and the reason.
 * The statuses are the Phase 8 vocabulary mirrored verbatim, and the note states
 * that nothing is overridden in the frontend — a `WITHHELD` sent by the backend
 * would render as `WITHHELD`.
 */

import { Building2, Users, Siren } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { GlassCard } from '../../components/ui/GlassCard'
import { SectionHeader } from '../../components/ui/SectionHeader'
import { HumanInputNote } from './NavyaProvenancePanel'
import {
  exposureReadings,
  type NavyaExposureKind,
  type NavyaExposureReading,
} from './exposure'
import type { NavyaForecastRecord } from './types'

const KIND_META: Record<NavyaExposureKind, { label: string; icon: LucideIcon }> = {
  population_exposure: { label: 'Population exposure', icon: Users },
  infrastructure_exposure: { label: 'Infrastructure exposure', icon: Building2 },
  response_priority: { label: 'Q-FLARE response priority', icon: Siren },
}

/** Status badge colours: `NOT_EVALUABLE` and `WITHHELD` are neutral/amber. */
function badgeClass(availability: string): string {
  if (availability === 'COMPLETE') return 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
  if (availability === 'PARTIAL') return 'border-ai-500/50 bg-ai-500/10 text-ai-300'
  if (availability === 'WITHHELD') return 'border-amber-500/50 bg-amber-500/10 text-amber-300'
  return 'border-mist-600/50 bg-forest-800/60 text-mist-300'
}

interface Props {
  forecast: NavyaForecastRecord
}

export function NavyaExposureDisplay({ forecast }: Props) {
  const readings = exposureReadings(forecast)

  return (
    <GlassCard className="space-y-4">
      <SectionHeader
        icon={Users}
        title="Exposure & response"
        description="What the risk dashboard can and cannot be told about exposure."
      />

      <ul className="divide-y divide-forest-600/40">
        {readings.map((reading) => (
          <ReadingRow key={reading.kind} reading={reading} />
        ))}
      </ul>

      <HumanInputNote tone="info">
        These statuses mirror the Phase 8 boundary vocabulary (
        {readings[0]?.availability ?? 'NOT_EVALUABLE'} / COMPLETE / PARTIAL / WITHHELD). This
        frontend never upgrades, downgrades or overrides a status it is sent.
      </HumanInputNote>
    </GlassCard>
  )
}

function ReadingRow({ reading }: { reading: NavyaExposureReading }) {
  const meta = KIND_META[reading.kind]
  const Icon = meta.icon
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">
          <Icon size={12} aria-hidden="true" />
          {meta.label}
        </h3>
        <span
          className={`rounded-md border px-2 py-0.5 text-[10px] font-semibold ${badgeClass(reading.availability)}`}
        >
          {reading.availability}
        </span>
      </div>
      <p className="mt-1 text-xs text-mist-300">
        Value: <span className="text-mist-500">—</span>
      </p>
      <p className="mt-1 text-[11px] text-mist-500">{reading.reason}</p>
    </li>
  )
}