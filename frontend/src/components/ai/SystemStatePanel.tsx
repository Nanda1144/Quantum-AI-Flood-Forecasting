import { Server, Signal, Clock, Database } from 'lucide-react'
import type { AIServiceHealth } from '../../types/ai'
import { StatusIndicator } from '../ui/StatusIndicator'
import { SectionHeader } from '../ui/SectionHeader'
import { formatRelative } from '../../lib/format'

interface SystemStatePanelProps {
  health: AIServiceHealth
}

export function SystemStatePanel({ health }: SystemStatePanelProps) {
  const items = [
    {
      icon: Server,
      label: 'AI Service',
      content: <StatusIndicator status={health.status} />,
    },
    {
      icon: Signal,
      label: 'API Latency',
      content: (
        <span className="text-xs font-semibold tabular-nums text-mist-100">
          {health.apiLatencyMs !== null ? `${health.apiLatencyMs}ms` : '—'}
        </span>
      ),
    },
    {
      icon: Clock,
      label: 'Last Successful Prediction',
      content: (
        <span className="text-xs text-mist-300">{formatRelative(health.lastSuccessfulPrediction)}</span>
      ),
    },
    {
      icon: Database,
      label: 'Data Freshness',
      content: (
        <span className="text-xs font-semibold tabular-nums text-mist-100">{health.dataFreshness ?? '—'}</span>
      ),
    },
  ]

  return (
    <div className="glass-card p-5">
      <SectionHeader icon={Server} title="System State" description="Service health and data freshness" />
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {items.map((item) => (
          <div
            key={item.label}
            className="flex items-center gap-3 rounded-xl border border-forest-600/70 bg-forest-800/60 px-4 py-3"
          >
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-forest-800 text-mist-500">
              <item.icon size={16} aria-hidden="true" />
            </span>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-mist-600">{item.label}</p>
              <div className="mt-0.5">{item.content}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}