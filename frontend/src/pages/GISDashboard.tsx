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
 * Fetches live data from /api/gis and renders sensor locations,
 * flood zones, river networks, and hydrological basin summaries.
 * All displayed values come from the backend; nothing is invented here.
 */

import { useEffect, useState } from 'react'
import { Activity, AlertTriangle, Droplets, Globe, MapPin, Waves } from 'lucide-react'

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:3001'

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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const token = sessionStorage.getItem('qflare_token') ?? localStorage.getItem('qflare_token') ?? ''
    const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {}

    Promise.all([
      fetch(`${API}/api/gis/sensors`, { headers }).then((r) => r.json()),
      fetch(`${API}/api/gis/flood-zones`, { headers }).then((r) => r.json()),
      fetch(`${API}/api/gis/rivers`, { headers }).then((r) => r.json()),
      fetch(`${API}/api/gis/basins`, { headers }).then((r) => r.json()),
    ])
      .then(([sensors, zones, rivers, basins]) => {
        setData({
          sensors: sensors.data ?? [],
          floodZones: zones.data ?? [],
          rivers: rivers.data ?? [],
          basins: basins.data ?? [],
        })
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center text-mist-400 text-sm">
        Loading GIS spatial data…
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-10">
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-5 py-4 text-sm text-amber-300">
          <AlertTriangle className="mr-2 inline-block" size={14} />
          GIS data could not be loaded: {error ?? 'unknown error'}. The backend GIS service may be offline.
        </div>
      </div>
    )
  }

  return (
    <main className="mx-auto max-w-[1440px] px-4 py-8 sm:px-6 lg:px-10" id="gis-dashboard">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-mist-50 flex items-center gap-2">
          <Globe className="text-emerald-400" size={22} aria-hidden />
          GIS Spatial Intelligence
        </h1>
        <p className="mt-1 text-sm text-mist-400">
          Regional hydrological network — sensor locations, flood zones, rivers, and basin summaries.
        </p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 mb-8">
        <KPI icon={Activity} label="Monitoring Sensors" value={data.sensors.length} />
        <KPI icon={AlertTriangle} label="Flood Zones" value={data.floodZones.length} />
        <KPI icon={Waves} label="River Networks" value={data.rivers.length} />
        <KPI icon={Droplets} label="Hydrological Basins" value={data.basins.length} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Sensor table */}
        <section aria-labelledby="sensors-heading" className="rounded-xl border border-forest-700/60 bg-forest-800/30 p-5">
          <h2 id="sensors-heading" className="mb-4 flex items-center gap-2 text-sm font-semibold text-mist-200">
            <Activity size={14} className="text-emerald-400" aria-hidden />
            Monitoring Sensors
          </h2>
          {data.sensors.length === 0 ? (
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
          {data.floodZones.length === 0 ? (
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
          {data.rivers.length === 0 ? (
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
          {data.basins.length === 0 ? (
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
    </main>
  )
}
