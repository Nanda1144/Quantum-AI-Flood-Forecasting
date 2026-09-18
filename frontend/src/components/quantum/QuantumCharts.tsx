import type { EnergyPoint, MeasurementCount } from '../../types/optimization'

/** Horizontal top-bits histogram from a measurement outcome set. */
export function MeasurementHistogram({ data }: { data: MeasurementCount[] }) {
  if (data.length === 0) return <p className="text-xs text-mist-500">No measurement data yet.</p>
  const maxCount = Math.max(...data.map((entry) => entry.count), 1)
  const total = data.reduce((sum, entry) => sum + entry.count, 0)
  return (
    <div className="space-y-1.5">
      {data.map((entry) => (
        <div key={entry.bitstring} className="flex items-center gap-2 text-xs">
          <span className="w-16 shrink-0 font-mono text-ai-300">{entry.bitstring.slice(0, 8)}…</span>
          <div className="h-4 flex-1 overflow-hidden rounded bg-forest-700/50">
            <div
              className="h-full rounded bg-gradient-to-r from-emerald-600/70 to-ai-500/70"
              style={{ width: `${(entry.count / maxCount) * 100}%` }}
            />
          </div>
          <span className="w-16 shrink-0 text-right font-mono text-mist-300">
            {entry.count}
            <span className="text-mist-500"> · {Math.round((entry.count / Math.max(total, 1)) * 100)}%</span>
          </span>
        </div>
      ))}
    </div>
  )
}

/** Converging QAOA energy curve (SVG). */
export function EnergySparkline({ data }: { data: EnergyPoint[] }) {
  if (data.length < 2) return <p className="text-xs text-mist-500">No energy history yet.</p>
  const width = 320
  const height = 72
  const min = Math.min(...data.map((point) => point.energy))
  const max = Math.max(...data.map((point) => point.energy))
  const span = Math.max(max - min, 1e-9)
  const pointsData = data.map((point, index) => {
    const x = (index / (data.length - 1)) * (width - 8) + 4
    const y = height - 6 - ((point.energy - min) / span) * (height - 12)
    return { ...point, x, y }
  })
  const line = pointsData.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ')
  const last = pointsData[pointsData.length - 1]
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="QAOA energy convergence">
      <line x1="4" x2={width - 4} y1={last.y} y2={last.y} stroke="#0c1a15" strokeWidth="1" strokeDasharray="3 3" />
      <polyline points={line} fill="none" stroke="#34d399" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last.x} cy={last.y} r="3" fill="#a5f3fc" />
    </svg>
  )
}