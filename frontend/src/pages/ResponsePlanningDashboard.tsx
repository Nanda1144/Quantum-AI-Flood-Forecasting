/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform. It is honest by construction,
 * per the platform README: no fabricated data, no invented metrics, every surrogate or
 * fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Disaster Response Planning dashboard page.
 *
 * Fetches response plans, active plan, and evacuation zones from /api/response
 * (via Vite proxy → :3000) and renders planning status. Values come from the
 * backend; no decisions are fabricated here. Emergency-level decisions
 * (EVACUATE / EMERGENCY_DECLARED) require human authority and are never
 * issued automatically.
 */

import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle, Clock, Database, ServerCrash, Shield, Users } from 'lucide-react'
import { authHeaders } from '../services/authService'

/** Use Vite dev-server proxy (/api → localhost:3000). Empty = same origin. */
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''

interface EvacZone {
  id: string
  name: string
  priority: string
  estimatedPopulation?: number
}

interface ResponsePlan {
  id: string
  name: string
  status: string
  riskLevel?: string
  allocatedRescueBoats?: number
  allocatedMedicalTeams?: number
  allocatedShelters?: number
  totalEvacuees?: number
  zones?: EvacZone[]
  createdAt?: string
}

interface ResourceDeployment {
  allocatedRescueBoats: number
  allocatedMedicalTeams: number
  allocatedShelters: number
  totalEvacuees: number
}

type ConnState = 'loading' | 'connected' | 'error'

function ConnectionBanner({ state, error }: { state: ConnState; error?: string | null }) {
  if (state === 'loading') {
    return (
      <div className="mb-6 flex items-center gap-3 rounded-xl border border-blue-400/20 bg-blue-400/5 px-5 py-3 text-xs text-blue-300">
        <Database size={14} className="animate-pulse shrink-0" />
        <span>Connecting to backend API (Node.js :3000) and response planning service…</span>
      </div>
    )
  }
  if (state === 'connected') {
    return (
      <div className="mb-6 flex items-center gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-5 py-3 text-xs text-emerald-300">
        <CheckCircle size={14} className="shrink-0" />
        <span>
          <strong>Backend connected</strong> — API Gateway (:3000) &amp; Database online. Response plan data loaded.
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

function StatusBadge({ status }: { status: string }) {
  const s = status.toUpperCase()
  const colour =
    s === 'ACTIVE'
      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
      : s === 'DRAFT'
        ? 'bg-blue-500/15 text-blue-300 border-blue-500/30'
        : s === 'WITHHELD'
          ? 'bg-mist-600/20 text-mist-400 border-mist-600/30'
          : 'bg-amber-500/15 text-amber-300 border-amber-500/30'
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${colour}`}>
      {status}
    </span>
  )
}

export function ResponsePlanningDashboard() {
  const [active, setActive] = useState<ResponsePlan | null>(null)
  const [plans, setPlans] = useState<ResponsePlan[]>([])
  const [resources, setResources] = useState<ResourceDeployment | null>(null)
  const [connState, setConnState] = useState<ConnState>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const h = { ...authHeaders(), Accept: 'application/json' }
    Promise.all([
      fetch(`${API_BASE}/api/response/active`, { headers: h }).then((r) => r.json()),
      fetch(`${API_BASE}/api/response/plans`, { headers: h }).then((r) => r.json()),
      fetch(`${API_BASE}/api/response/resource-deployment`, { headers: h }).then((r) => r.json()),
    ])
      .then(([activePlan, allPlans, res]) => {
        setActive(activePlan.data ?? null)
        setPlans(allPlans.data ?? [])
        setResources(res.data ?? null)
        setConnState('connected')
      })
      .catch((e: unknown) => {
        setError(String(e))
        setConnState('error')
      })
  }, [])

  return (
    <main className="mx-auto max-w-[1440px] px-4 py-8 sm:px-6 lg:px-10" id="response-planning-dashboard">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-mist-50 flex items-center gap-2">
          <Shield className="text-emerald-400" size={22} aria-hidden />
          Disaster Response Planning
        </h1>
        <p className="mt-1 text-sm text-mist-400">
          Evacuation coordination, resource deployment, and response plan management.
        </p>
      </div>

      {/* Connection Status Banner */}
      <ConnectionBanner state={connState} error={error} />

      {/* Human authority notice — always shown */}
      <div className="mb-6 rounded-xl border border-amber-500/20 bg-amber-500/5 px-5 py-3 text-xs text-amber-300 flex items-start gap-2">
        <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />
        <span>
          Emergency-level decisions (EVACUATE, MANDATORY_EVACUATION, EMERGENCY_DECLARED) require human authority
          and are never issued automatically by this system. All displayed decisions are advisory only.
        </span>
      </div>

      {connState !== 'error' && (
        <>
          {/* Active plan + resources */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 mb-8">
            {/* Active plan */}
            <section aria-labelledby="active-plan-heading" className="rounded-xl border border-forest-700/60 bg-forest-800/30 p-5">
              <h2 id="active-plan-heading" className="mb-4 flex items-center gap-2 text-sm font-semibold text-mist-200">
                <CheckCircle size={14} className="text-emerald-400" aria-hidden />
                Active Response Plan
              </h2>
              {!active ? (
                <div className="rounded-lg border border-dashed border-forest-600 py-8 text-center text-xs text-mist-500">
                  No active response plan. Create a plan to initiate coordinated response.
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-mist-200">{active.name}</span>
                    <StatusBadge status={active.status} />
                  </div>
                  {active.riskLevel && (
                    <div className="text-xs text-mist-400">
                      Risk level: <span className="text-mist-300 font-semibold">{active.riskLevel}</span>
                    </div>
                  )}
                  {active.zones && active.zones.length > 0 && (
                    <div>
                      <div className="text-xs text-mist-500 mb-2">Evacuation zones ({active.zones.length})</div>
                      <ul className="space-y-1">
                        {active.zones.slice(0, 5).map((z) => (
                          <li key={z.id} className="flex items-center justify-between rounded-lg border border-forest-700/40 bg-forest-900/40 px-3 py-1.5">
                            <span className="text-xs text-mist-300">{z.name}</span>
                            <StatusBadge status={z.priority} />
                          </li>
                        ))}
                        {active.zones.length > 5 && (
                          <li className="text-[11px] text-mist-500 pl-1">+{active.zones.length - 5} more zones</li>
                        )}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </section>

            {/* Resource deployment */}
            <section aria-labelledby="resources-heading" className="rounded-xl border border-forest-700/60 bg-forest-800/30 p-5">
              <h2 id="resources-heading" className="mb-4 flex items-center gap-2 text-sm font-semibold text-mist-200">
                <Users size={14} className="text-blue-400" aria-hidden />
                Resource Deployment
              </h2>
              {!resources ? (
                <p className="text-xs text-mist-500">No resource deployment data.</p>
              ) : (
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { label: 'Rescue Boats', value: resources.allocatedRescueBoats },
                    { label: 'Medical Teams', value: resources.allocatedMedicalTeams },
                    { label: 'Emergency Shelters', value: resources.allocatedShelters },
                    { label: 'Total Evacuees', value: resources.totalEvacuees.toLocaleString() },
                  ].map(({ label, value }) => (
                    <div key={label} className="rounded-xl border border-forest-700/40 bg-forest-900/40 p-3">
                      <div className="text-[11px] text-mist-500 mb-1">{label}</div>
                      <div className="text-xl font-bold text-mist-100">{value}</div>
                    </div>
                  ))}
                </div>
              )}
              <p className="mt-3 text-[11px] text-mist-600">
                Resource figures are advisory allocations based on the active plan — not live deployment status.
              </p>
            </section>
          </div>

          {/* All plans list */}
          <section aria-labelledby="all-plans-heading" className="rounded-xl border border-forest-700/60 bg-forest-800/30 p-5">
            <h2 id="all-plans-heading" className="mb-4 flex items-center gap-2 text-sm font-semibold text-mist-200">
              <Clock size={14} className="text-purple-400" aria-hidden />
              Response Plans
            </h2>
            {plans.length === 0 ? (
              <p className="text-xs text-mist-500">No response plans on record.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-forest-700/50 text-left text-mist-500">
                      <th className="pb-2 pr-4 font-medium">Name</th>
                      <th className="pb-2 pr-4 font-medium">Status</th>
                      <th className="pb-2 pr-4 font-medium">Risk Level</th>
                      <th className="pb-2 font-medium">Zones</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-forest-700/30">
                    {plans.map((p) => (
                      <tr key={p.id}>
                        <td className="py-2 pr-4 text-mist-300 font-medium">{p.name}</td>
                        <td className="py-2 pr-4"><StatusBadge status={p.status} /></td>
                        <td className="py-2 pr-4 text-mist-400">{p.riskLevel ?? '—'}</td>
                        <td className="py-2 text-mist-400">{p.zones?.length ?? 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </main>
  )
}
