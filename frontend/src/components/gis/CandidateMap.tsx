/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Reusable GIS plot of federated candidate sites (Jahnavi's coordinate model).
 *
 * The component is a plain, dependency-free SVG scatter: it projects the stored
 * latitude/longitude linearly onto a padded box and marks each site by its
 * decoded selection state and its served flood-risk score. It does not fetch or
 * invent geometry — the caller passes the joined rows, and a missing coordinate
 * is left out with an honest note.
 */

import { MapPin } from 'lucide-react'
import type { LocationRow } from '../../lib/decision'
import { HIGH_RISK_THRESHOLD } from '../../lib/decision'
import { formatScore } from '../../lib/quantum'

interface CandidateMapProps {
  rows: LocationRow[]
  /** Hidden when the page already explains the coordinate source elsewhere. */
  description?: string
}

interface Plotted {
  row: LocationRow
  x: number
  y: number
}

const PAD = 6
const SPAN = 100 - PAD * 2

function project(rows: LocationRow[]): Plotted[] {
  const located = rows.filter(
    (row) => typeof row.latitude === 'number' && Number.isFinite(row.latitude) && typeof row.longitude === 'number' && Number.isFinite(row.longitude),
  )
  if (located.length === 0) return []

  const lats = located.map((row) => row.latitude as number)
  const lons = located.map((row) => row.longitude as number)
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const minLon = Math.min(...lons)
  const maxLon = Math.max(...lons)
  const latSpan = maxLat - minLat
  const lonSpan = maxLon - minLon

  return located.map((row) => {
    const lat = row.latitude as number
    const lon = row.longitude as number
    const x = lonSpan > 0 ? PAD + ((lon - minLon) / lonSpan) * SPAN : 50
    const y = latSpan > 0 ? PAD + ((maxLat - lat) / latSpan) * SPAN : 50
    return { row, x, y }
  })
}

function pointColor(row: LocationRow): string {
  if (row.selected) return 'var(--color-emerald-400)'
  if (row.highRisk) return 'var(--color-amber-400)'
  return 'var(--color-mist-600)'
}

export function CandidateMap({ rows, description }: CandidateMapProps) {
  const plotted = project(rows)
  const selected = rows.filter((row) => row.selected).length
  const unlocated = rows.length - plotted.length

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-xs font-medium text-mist-300">
          <MapPin size={13} className="text-ai-300" aria-hidden="true" />
          Candidate sites and decoded selection
        </p>
        <p className="text-[11px] text-mist-500">
          {selected} selected / {rows.length} candidates
        </p>
      </div>

      {plotted.length === 0 ? (
        <div className="rounded-lg border border-dashed border-forest-600 px-3 py-8 text-center text-xs text-mist-500">
          Candidate coordinates are unavailable for this job — the GIS inputs could not be loaded. No geometry is fabricated.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-forest-600 bg-forest-900/60">
          <svg
            viewBox="0 0 100 100"
            role="img"
            aria-label={`Map of ${plotted.length} candidate sites with ${selected} selected`}
            className="h-72 w-full sm:h-80"
          >
            <defs>
              <pattern id="qflare-gis-grid" width="10" height="10" patternUnits="userSpaceOnUse">
                <path d="M 10 0 L 0 0 0 10" fill="none" stroke="var(--color-forest-700)" strokeWidth="0.25" />
              </pattern>
            </defs>
            <rect x="0" y="0" width="100" height="100" fill="url(#qflare-gis-grid)" opacity="0.6" />
            {plotted.map(({ row, x, y }) => (
              <g key={row.id}>
                {row.selected && (
                  <circle cx={x} cy={y} r={4.2} fill="none" stroke="var(--color-emerald-500)" strokeWidth="0.6" opacity="0.7" />
                )}
                <circle
                  cx={x}
                  cy={y}
                  r={row.selected ? 2.2 : 1.5}
                  fill={pointColor(row)}
                  stroke="var(--color-forest-950)"
                  strokeWidth="0.5"
                >
                  <title>
                    {`${row.id} · ${row.zone} · ${row.selected ? 'selected' : 'not selected'} · risk ${formatScore(row.floodRisk)}`}
                  </title>
                </circle>
              </g>
            ))}
          </svg>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-mist-500">
        <LegendItem color="var(--color-emerald-400)" label="Selected" />
        <LegendItem color="var(--color-mist-600)" label="Not selected" />
        <LegendItem color="var(--color-amber-400)" label={`High risk (floodRisk ≥ ${HIGH_RISK_THRESHOLD.toFixed(2)})`} />
        <span className="text-mist-600">Marker colour is a display aid; risk values come from the GIS module.</span>
      </div>

      {unlocated > 0 && (
        <p className="text-[11px] text-mist-500">
          {unlocated} selected site{unlocated === 1 ? '' : 's'} without coordinates {unlocated === 1 ? 'is' : 'are'} listed in the table only.
        </p>
      )}

      {description && <p className="text-[11px] text-mist-600">{description}</p>}
    </div>
  )
}

function LegendItem({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="size-2 rounded-full" style={{ backgroundColor: color }} aria-hidden="true" />
      {label}
    </span>
  )
}
