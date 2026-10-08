/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform. It is honest by construction,
 * per the platform README: no fabricated data, no invented metrics, every surrogate or
 * fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * IoT Sensor Telemetry dashboard page.
 *
 * Fetches live readings from /api/iot and renders a real-time telemetry
 * table and simulation controls. Values come from the backend; no readings
 * are fabricated here.
 */

import { useEffect, useState } from 'react'
import { Activity, AlertCircle, Play, Square, Wifi } from 'lucide-react'

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:3001'

interface SensorReading {
  sensorId: string
  type: string
  value: number
  unit: string
  timestamp: string
  status?: string
}

interface DashboardSummary {
  activeSensors: number
  totalReadings: number
  alertCount: number
  lastUpdated: string
}

interface SimStatus {
  running: boolean
  scenario?: string
  startedAt?: string
}

function authHeaders(): HeadersInit {
  const token = sessionStorage.getItem('qflare_token') ?? localStorage.getItem('qflare_token') ?? ''
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export function IoTDashboard() {
  const [readings, setReadings] = useState<SensorReading[]>([])
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [sim, setSim] = useState<SimStatus>({ running: false })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    const h = authHeaders()
    Promise.all([
      fetch(`${API}/api/iot/latest-data`, { headers: h }).then((r) => r.json()),
      fetch(`${API}/api/iot/dashboard`, { headers: h }).then((r) => r.json()),
      fetch(`${API}/api/iot/simulation/status`, { headers: h }).then((r) => r.json()),
    ])
      .then(([data, dash, simData]) => {
        setReadings(data.data ?? [])
        setSummary(dash.data ?? null)
        setSim(simData.data ?? { running: false })
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    const interval = setInterval(load, 10_000)
    return () => clearInterval(interval)
  }, [])

  const startSim = async (scenario: string) => {
    await fetch(`${API}/api/iot/simulation/start`, {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario }),
    })
    load()
  }

  const stopSim = async () => {
    await fetch(`${API}/api/iot/simulation/stop`, { method: 'POST', headers: authHeaders() })
    load()
  }

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center text-mist-400 text-sm">
        Loading IoT telemetry…
      </div>
    )
  }

  return (
    <main className="mx-auto max-w-[1440px] px-4 py-8 sm:px-6 lg:px-10" id="iot-dashboard">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-mist-50 flex items-center gap-2">
          <Wifi className="text-emerald-400" size={22} aria-hidden />
          IoT Sensor Telemetry
        </h1>
        <p className="mt-1 text-sm text-mist-400">
          Live sensor readings and simulation engine for hydrological monitoring.
        </p>
      </div>

      {error && (
        <div className="mb-6 rounded-xl border border-amber-500/30 bg-amber-500/10 px-5 py-4 text-sm text-amber-300">
          <AlertCircle className="mr-2 inline-block" size={14} />
          Partial data: {error}
        </div>
      )}

      {/* Summary KPIs */}
      {summary && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 mb-8">
          {[
            { label: 'Active Sensors', value: summary.activeSensors },
            { label: 'Total Readings', value: summary.totalReadings },
            { label: 'Active Alerts', value: summary.alertCount },
            { label: 'Last Updated', value: new Date(summary.lastUpdated).toLocaleTimeString() },
          ].map(({ label, value }) => (
            <div key={label} className="rounded-xl border border-forest-700/60 bg-forest-800/40 p-4">
              <div className="text-xs text-mist-400 mb-1">{label}</div>
              <div className="text-2xl font-bold text-mist-50">{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Simulation controls */}
      <section aria-labelledby="sim-heading" className="mb-8 rounded-xl border border-forest-700/60 bg-forest-800/30 p-5">
        <h2 id="sim-heading" className="mb-4 flex items-center gap-2 text-sm font-semibold text-mist-200">
          <Activity size={14} className="text-blue-400" aria-hidden />
          Simulation Engine
          {sim.running && (
            <span className="ml-2 rounded-full bg-emerald-500/15 border border-emerald-500/30 px-2 py-0.5 text-[10px] font-semibold uppercase text-emerald-300">
              Running · {sim.scenario}
            </span>
          )}
        </h2>
        <div className="flex flex-wrap gap-3">
          {['HEAVY_RAIN', 'FLASH_FLOOD', 'DROUGHT', 'NORMAL'].map((scenario) => (
            <button
              key={scenario}
              id={`sim-start-${scenario.toLowerCase()}`}
              type="button"
              disabled={sim.running}
              onClick={() => startSim(scenario)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-forest-600 px-3 py-2 text-xs font-semibold text-mist-300 transition-colors hover:border-emerald-500/50 hover:text-emerald-300 disabled:opacity-50"
            >
              <Play size={12} aria-hidden />
              {scenario.replace('_', ' ')}
            </button>
          ))}
          <button
            id="sim-stop"
            type="button"
            disabled={!sim.running}
            onClick={stopSim}
            className="inline-flex items-center gap-1.5 rounded-lg border border-forest-600 px-3 py-2 text-xs font-semibold text-mist-300 transition-colors hover:border-critical-500/60 hover:text-critical-400 disabled:opacity-50"
          >
            <Square size={12} aria-hidden />
            Stop
          </button>
        </div>
        <p className="mt-3 text-[11px] text-mist-600">
          Simulation produces labelled synthetic readings — all outputs are marked SYNTHETIC/DEMO.
        </p>
      </section>

      {/* Readings table */}
      <section aria-labelledby="readings-heading" className="rounded-xl border border-forest-700/60 bg-forest-800/30 p-5">
        <h2 id="readings-heading" className="mb-4 flex items-center gap-2 text-sm font-semibold text-mist-200">
          <Wifi size={14} className="text-emerald-400" aria-hidden />
          Latest Sensor Readings
        </h2>
        {readings.length === 0 ? (
          <p className="text-xs text-mist-500">
            No readings yet. Start the simulation or connect physical sensors to begin receiving data.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-forest-700/50 text-left text-mist-500">
                  <th className="pb-2 pr-4 font-medium">Sensor</th>
                  <th className="pb-2 pr-4 font-medium">Type</th>
                  <th className="pb-2 pr-4 font-medium">Value</th>
                  <th className="pb-2 pr-4 font-medium">Unit</th>
                  <th className="pb-2 font-medium">Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-forest-700/30">
                {readings.map((r, idx) => (
                  <tr key={`${r.sensorId}-${idx}`}>
                    <td className="py-2 pr-4 font-mono text-mist-400">{r.sensorId}</td>
                    <td className="py-2 pr-4 text-mist-300">{r.type}</td>
                    <td className="py-2 pr-4 font-semibold text-mist-200">{r.value}</td>
                    <td className="py-2 pr-4 text-mist-500">{r.unit}</td>
                    <td className="py-2 text-mist-500 font-mono">{new Date(r.timestamp).toLocaleTimeString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  )
}
