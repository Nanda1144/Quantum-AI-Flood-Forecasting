/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform. It is honest by construction,
 * per the platform README: no fabricated data, no invented metrics, every surrogate or
 * fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * GIS Spatial Intelligence dashboard page.
 *
 * Fetches live data from /api/gis (via Vite proxy → :3000) and renders
 * sensor locations, flood zones, river networks, and basin summaries.
 * All displayed values come from the backend; nothing is invented here.
 */

import { useEffect, useState } from 'react'
import { Activity, AlertTriangle, CheckCircle, Database, Droplets, Globe, MapPin, ServerCrash, Waves, XCircle } from 'lucide-react'
import { authHeaders } from '../services/authService'

/** Use Vite dev-server proxy (/api → localhost:3000). Empty = same origin. */
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''

interface SensorRow {
  id: string
  name: string
  type: string
  lat?: number
  lon?: number
  status: string
}

interface FloodZone {
  id: string
  name: string
  riskLevel: string
  areaSqKm?: number
}

interface River {
  id: string
  name: string
  lengthKm?: number
  basinName?: string
}

interface Basin {
  name: string
  areaSqKm: number
  majorRivers: string[]
  monitoringSensors: number
}

interface GISData {
  sensors: SensorRow[]
  floodZones: FloodZone[]
  rivers: River[]
  basins: Basin[]
}

type ConnState = 'loading' | 'connected' | 'error'

function ConnectionBanner({ state, error }: { state: ConnState; error?: string | null }) {
  if (state === 'loading') {
    return (
      <div className="mb-6 flex items-center gap-3 rounded-xl border border-blue-400/20 bg-blue-400/5 px-5 py-3 text-xs text-blue-300">
        <Database size={14} className="animate-pulse shrink-0" />
        <span>Connecting to backend API (Node.js :3000) and database (Supabase/PostgreSQL)…</span>
      </div>
    )
  }
  if (state === 'connected') {
    return (
      <div className="mb-6 flex items-center gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-5 py-3 text-xs text-emerald-300">
        <CheckCircle size={14} className="shrink-0" />
        <span>
          <strong>Backend connected</strong> — API Gateway (:3000) &amp; Database online. GIS data loaded successfully.
        </span>
      </div>
    )
  }
  return (
    <div className="mb-6 flex items-start gap-3 rounded-xl border border-critical-500/30 bg-critical-500/10 px-5 py-4 text-xs text-critical-400">
      <ServerCrash size={14} className="mt-0.5 shrink-0" />
      <div>
        <p className="font-semibold mb-1">Backend / Database not reachable</p>
        <p className="text-[11px] opacity-80">{error ?? 'Connection refused'}</p>
        <p className="mt-1 text-[11px] opacity-70">
          Ensure the Node.js backend is running: <code className="font-mono bg-black/20 px-1 rounded">cd backend &amp;&amp; npm run dev</code>
        </p>
      </div>
    </div>
  )
}

function StatusPill({ status }: { status: string }) {
  const colour =
    status === 'ACTIVE' || status === 'active'
      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
      : status === 'WARN' || status === 'warning'
        ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
        : 'bg-mist-700/20 text-mist-400 border-mist-600/30'
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${colour}`}>
      {status}
    </span>
  )
}

function KPI({ icon: Icon, label, value, sub }: { icon: typeof Globe; label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-xl border border-forest-700/60 bg-forest-800/40 p-4">
      <div className="flex items-center gap-2 text-mist-400 text-xs mb-1">
        <Icon size={13} aria-hidden />
        {label}
      </div>
      <div className="text-2xl font-bold text-mist-50">{value}</div>
      {sub && <div className="text-[11px] text-mist-500 mt-0.5">{sub}</div>}
    </div>
  )
}

export function GISDashboard() {
  const [data, setData] = useState<GISData | null>(null)
  const [connState, setConnState] = useState<ConnState>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const h = { ...authHeaders(), Accept: 'application/json' }

    Promise.all([
      fetch(`${API_BASE}/api/gis/sensors`, { headers: h }).then((r) => r.json()),
      fetch(`${API_BASE}/api/gis/flood-zones`, { headers: h }).then((r) => r.json()),
      fetch(`${API_BASE}/api/gis/rivers`, { headers: h }).then((r) => r.json()),
      fetch(`${API_BASE}/api/gis/basins`, { headers: h }).then((r) => r.json()),
    ])
      .then(([sensors, zones, rivers, basins]) => {
        setData({
          sensors: sensors.data ?? [],
          floodZones: zones.data ?? [],
          rivers: rivers.data ?? [],
          basins: basins.data ?? [],
        })
        setConnState('connected')
      })
      .catch((e: unknown) => {
        setError(String(e))
        setConnState('error')
      })
  }, [])

  return (
    <main className="mx-auto max-w-[1440px] px-4 py-8 sm:px-6 lg:px-10" id="gis-dashboard">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-mist-50 flex items-center gap-2">
          <Globe className="text-emerald-400" size={22} aria-hidden />
          GIS Spatial Intelligence
        </h1>
        <p className="mt-1 text-sm text-mist-400">
          Regional hydrological network — sensor locations, flood zones, rivers, and basin summaries.
        </p>
      </div>

      {/* Connection Status Banner */}
      <ConnectionBanner state={connState} error={error} />

      {connState === 'error' ? null : (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 mb-8">
            <KPI icon={Activity} label="Monitoring Sensors" value={data?.sensors.length ?? '—'} />
            <KPI icon={AlertTriangle} label="Flood Zones" value={data?.floodZones.length ?? '—'} />
            <KPI icon={Waves} label="River Networks" value={data?.rivers.length ?? '—'} />
            <KPI icon={Droplets} label="Hydrological Basins" value={data?.basins.length ?? '—'} />
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* Sensor table */}
            <section aria-labelledby="sensors-heading" className="rounded-xl border border-forest-700/60 bg-forest-800/30 p-5">
              <h2 id="sensors-heading" className="mb-4 flex items-center gap-2 text-sm font-semibold text-mist-200">
                <Activity size={14} className="text-emerald-400" aria-hidden />
                Monitoring Sensors
              </h2>
              {!data || data.sensors.length === 0 ? (
                <p className="text-xs text-mist-500">No sensor data available from the backend.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-forest-700/50 text-left text-mist-500">
                        <th className="pb-2 pr-3 font-medium">ID</th>
                        <th className="pb-2 pr-3 font-medium">Name</th>
                        <th className="pb-2 pr-3 font-medium">Type</th>
                        <th className="pb-2 font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-forest-700/30">
                      {data.sensors.map((s) => (
                        <tr key={s.id}>
                          <td className="py-2 pr-3 font-mono text-mist-400">{s.id}</td>
                          <td className="py-2 pr-3 text-mist-300">{s.name}</td>
                          <td className="py-2 pr-3 text-mist-400">{s.type}</td>
                          <td className="py-2"><StatusPill status={s.status} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* Flood zones */}
            <section aria-labelledby="zones-heading" className="rounded-xl border border-forest-700/60 bg-forest-800/30 p-5">
              <h2 id="zones-heading" className="mb-4 flex items-center gap-2 text-sm font-semibold text-mist-200">
                <AlertTriangle size={14} className="text-amber-400" aria-hidden />
                Flood Zones
              </h2>
              {!data || data.floodZones.length === 0 ? (
                <p className="text-xs text-mist-500">No flood zone records available.</p>
              ) : (
                <ul className="space-y-2">
                  {data.floodZones.map((z) => (
                    <li key={z.id} className="flex items-center justify-between rounded-lg border border-forest-700/40 bg-forest-900/40 px-3 py-2">
                      <span className="text-xs text-mist-300">{z.name}</span>
                      <StatusPill status={z.riskLevel} />
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Rivers */}
            <section aria-labelledby="rivers-heading" className="rounded-xl border border-forest-700/60 bg-forest-800/30 p-5">
              <h2 id="rivers-heading" className="mb-4 flex items-center gap-2 text-sm font-semibold text-mist-200">
                <Waves size={14} className="text-blue-400" aria-hidden />
                River Networks
              </h2>
              {!data || data.rivers.length === 0 ? (
                <p className="text-xs text-mist-500">No river data available.</p>
              ) : (
                <ul className="space-y-2">
                  {data.rivers.map((r) => (
                    <li key={r.id} className="flex items-center justify-between rounded-lg border border-forest-700/40 bg-forest-900/40 px-3 py-2">
                      <span className="text-xs text-mist-300">{r.name}</span>
                      {r.basinName && <span className="text-[11px] text-mist-500">{r.basinName}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Basins */}
            <section aria-labelledby="basins-heading" className="rounded-xl border border-forest-700/60 bg-forest-800/30 p-5">
              <h2 id="basins-heading" className="mb-4 flex items-center gap-2 text-sm font-semibold text-mist-200">
                <MapPin size={14} className="text-purple-400" aria-hidden />
                Hydrological Basins
              </h2>
              {!data || data.basins.length === 0 ? (
                <p className="text-xs text-mist-500">No basin summary available.</p>
              ) : (
                <ul className="space-y-3">
                  {data.basins.map((b) => (
                    <li key={b.name} className="rounded-xl border border-forest-700/40 bg-forest-900/40 px-4 py-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm font-semibold text-mist-200">{b.name}</span>
                        <span className="text-[11px] text-mist-500">{b.areaSqKm.toLocaleString()} km²</span>
                      </div>
                      <div className="text-[11px] text-mist-400">
                        Rivers: {b.majorRivers.join(', ')} · {b.monitoringSensors} sensors
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </main>
  )
}
