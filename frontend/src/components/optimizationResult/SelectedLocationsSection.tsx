/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { MapPinned } from 'lucide-react'
import { GlassCard } from '../ui/GlassCard'
import { SectionHeader } from '../ui/SectionHeader'
import { CandidateMap } from '../gis/CandidateMap'
import { buildLocationRows } from '../../lib/decision'
import { formatScore } from '../../lib/quantum'
import type { CandidateLocation, OptimizationResult } from '../../types/optimization'

interface SelectedLocationsSectionProps {
  candidates: CandidateLocation[] | null
  result: OptimizationResult
}

function coordinate(value: number | null): string {
  return value === null || !Number.isFinite(value) ? '—' : value.toFixed(4)
}

export function SelectedLocationsSection({ candidates, result }: SelectedLocationsSectionProps) {
  const rows = buildLocationRows(candidates, result)
  const validation = result.validationStatus
  const selectionLabel = result.selectedLocations.length

  return (
    <GlassCard>
      <SectionHeader
        icon={MapPinned}
        title="Selected locations"
        description={`${selectionLabel} site${selectionLabel === 1 ? '' : 's'} decoded from the stored solution, plotted against the federated candidate set`}
      />

      <div className="mt-4">
        <CandidateMap rows={rows} />
      </div>

      <div className="mt-4 overflow-x-auto rounded-lg border border-forest-600">
        <table className="w-full min-w-[720px] text-left text-xs">
          <thead>
            <tr className="border-b border-forest-600 bg-forest-800/60 text-mist-500">
              <th className="px-3 py-2 font-medium">Candidate ID</th>
              <th className="px-3 py-2 font-medium">Zone</th>
              <th className="px-3 py-2 text-right font-medium">Latitude</th>
              <th className="px-3 py-2 text-right font-medium">Longitude</th>
              <th className="px-3 py-2 text-right font-medium">Risk</th>
              <th className="px-3 py-2 text-right font-medium">Coverage</th>
              <th className="px-3 py-2 font-medium">Selection</th>
              <th className="px-3 py-2 font-medium">Validation</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.id}
                className={`border-b border-forest-700/50 last:border-0 ${row.selected ? 'bg-emerald-500/5' : ''}`}
              >
                <td className="px-3 py-1.5 font-mono text-ai-300">{row.id}</td>
                <td className="px-3 py-1.5 text-mist-400">{row.zone}</td>
                <td className="px-3 py-1.5 text-right font-mono text-mist-300">{coordinate(row.latitude)}</td>
                <td className="px-3 py-1.5 text-right font-mono text-mist-300">{coordinate(row.longitude)}</td>
                <td className="px-3 py-1.5 text-right font-mono text-mist-300">{formatScore(row.floodRisk)}</td>
                <td className="px-3 py-1.5 text-right font-mono text-mist-300">
                  <span title="Population exposure">pop {formatScore(row.populationExposure)}</span>
                  <span className="mx-1 text-forest-500">·</span>
                  <span title="Infrastructure criticality">infra {formatScore(row.infrastructureCriticality)}</span>
                </td>
                <td className="px-3 py-1.5">
                  {row.selected ? (
                    <span className="rounded border border-emerald-500/50 bg-emerald-500/10 px-1.5 py-0.5 text-[11px] font-medium text-emerald-300">
                      Selected
                    </span>
                  ) : (
                    <span className="text-[11px] text-mist-500">Not selected</span>
                  )}
                </td>
                <td className="px-3 py-1.5">
                  {!row.selected ? (
                    <span className="text-mist-600">—</span>
                  ) : validation === 'valid' ? (
                    <span className="text-emerald-300">Valid</span>
                  ) : validation === 'invalid' ? (
                    <span className="text-critical-400">Invalid</span>
                  ) : (
                    <span className="text-mist-500">Pending</span>
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-4 text-center text-mist-500">
                  No candidate locations are available for this job.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-2 text-[11px] text-mist-600">
        Validation is reported per job (constraint checks apply to the decoded set as a whole); coordinates and risk scores
        are served by the GIS module.
      </p>
    </GlassCard>
  )
}
