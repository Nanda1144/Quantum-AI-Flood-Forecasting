/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Interactive heatmap over the served Q-matrix (N×N quadratic part).
 *
 * The backend stores the quadratic half as upper-triangular: Q[i][j] for i<j is
 * authoritative and the lower mirror Q[j][i] is served as 0 by the symmetric
 * QUBO convention (x_i·x_j = x_j·x_i). Values are rendered exactly as served —
 * colors only encode sign and magnitude, nothing is rederived, so the dark
 * lower triangle is an honest reflection of the stored convention, not a bug.
 * Large matrices are windowed (only visible rows are mounted) so candidate
 * counts up to the platform's maximum stay responsive. Row/column labels are
 * the variable (candidate) ids.
 */

import { useMemo, useState } from 'react'
import { Minus, Plus, Table2 } from 'lucide-react'

const CELL_SIZES = [16, 22, 30, 40] as const
const DEFAULT_CELL = 22
/** Above this many variables the heatmap switches to windowed rendering. */
const WINDOW_THRESHOLD = 40
/** Row overscan above/below the visible window. */
const OVERSCAN = 6
const HUE_GREEN = [16, 185, 129]
const HUE_AMBER = [245, 158, 11]
function cellColor(value: number, maxAbs: number, zero: boolean): string {
  if (zero) return 'rgba(15, 32, 27, 0.9)'
  const intensity = Math.min(1, Math.abs(value) / Math.max(maxAbs, 1e-9))
  const base = value > 0 ? HUE_GREEN : HUE_AMBER
  const alpha = 0.16 + intensity * 0.8
  return `rgba(${base[0]}, ${base[1]}, ${base[2]}, ${alpha.toFixed(3)})`
}

interface QuboMatrixHeatmapProps {
  /** Served quadratic part (N×N) — upper-triangular by stored convention, authoritative. */
  quadratic: number[][] | null
  /** Variable labels (ids) — length N. */
  variables: string[]
}

interface HoverState {
  row: number
  col: number
  value: number
}

export function QuboMatrixHeatmap({ quadratic, variables }: QuboMatrixHeatmapProps) {
  const [cellSize, setCellSize] = useState<number>(DEFAULT_CELL)
  const [hover, setHover] = useState<HoverState | null>(null)

  const n = variables.length
  const maxAbs = useMemo(() => {
    if (!quadratic) return 0
    let max = 0
    for (const row of quadratic) for (const value of row) max = Math.max(max, Math.abs(value) || 0)
    return max
  }, [quadratic])

  const windowed = n > WINDOW_THRESHOLD
  const [rowStart, setRowStart] = useState(0)

  const rowHeight = cellSize
  const visibleCount = Math.ceil((window.innerHeight * 0.6) / rowHeight)
  const windowedRows = useMemo(() => {
    if (!windowed) return null
    const start = Math.max(0, rowStart - OVERSCAN)
    const end = Math.min(n, rowStart + visibleCount + OVERSCAN)
    const rows: number[] = []
    for (let i = start; i < end; i += 1) rows.push(i)
    return { start, rows }
  }, [windowed, rowStart, visibleCount, n])

  const onScroll = (event: React.UIEvent<HTMLDivElement>) => {
    if (!windowed) return
    setRowStart(Math.floor(event.currentTarget.scrollTop / rowHeight))
  }

  const zoomIn = () => {
    const index = CELL_SIZES.indexOf(cellSize as (typeof CELL_SIZES)[number])
    if (index < CELL_SIZES.length - 1) setCellSize(CELL_SIZES[index + 1])
  }
  const zoomOut = () => {
    const index = CELL_SIZES.indexOf(cellSize as (typeof CELL_SIZES)[number])
    if (index > 0) setCellSize(CELL_SIZES[index - 1])
  }

  const trimmed = (id: string) => (id.length > 7 ? `${id.slice(0, 6)}…` : id)

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-mist-500">
          <Table2 size={14} className="text-ai-300" aria-hidden="true" />
          Q matrix coefficient heatmap
          <span className="rounded border border-forest-600 bg-forest-800/70 px-1.5 py-0.5 font-mono text-[11px] normal-case text-mist-300">
            {n} × {n} quadratic · upper-triangle convention · variables as row/column labels
          </span>
        </p>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={zoomOut}
            disabled={cellSize === CELL_SIZES[0]}
            aria-label="Zoom out"
            className="rounded border border-forest-600 bg-forest-800 p-1 text-mist-300 transition-colors hover:border-emerald-500/60 hover:text-emerald-300 disabled:opacity-40"
          >
            <Minus size={13} aria-hidden="true" />
          </button>
          <span className="rounded border border-forest-600 bg-forest-800/70 px-2 py-1 font-mono text-[11px] text-mist-300">
            {cellSize}px
          </span>
          <button
            type="button"
            onClick={zoomIn}
            disabled={cellSize === CELL_SIZES[CELL_SIZES.length - 1]}
            aria-label="Zoom in"
            className="rounded border border-forest-600 bg-forest-800 p-1 text-mist-300 transition-colors hover:border-emerald-500/60 hover:text-emerald-300 disabled:opacity-40"
          >
            <Plus size={13} aria-hidden="true" />
          </button>
        </div>
      </div>

      {!quadratic || quadratic.length === 0 ? (
        <p className="rounded-lg border border-dashed border-forest-600 px-3 py-6 text-center text-xs text-mist-500">
          No stored quadratic coefficients to display.
        </p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-forest-600">
          <div
            className="overflow-auto"
            style={{ maxHeight: 'min(60vh, 640px)' }}
            onScroll={onScroll}
          >
            {windowed && windowedRows ? (
              <div className="relative" style={{ height: n * rowHeight }}>
                {/* column labels (sticky vertically) */}
                <div
                  className="sticky top-0 z-20 flex"
                  style={{ height: rowHeight }}
                >
                  <div style={{ width: 64 }} className="flex-none bg-forest-900" />
                  {variables.map((id) => (
                    <div
                      key={id}
                      title={id}
                      style={{ width: cellSize }}
                      className="flex-none bg-forest-900 px-0.5 text-center font-mono text-[10px] leading-none text-mist-500"
                    >
                      {trimmed(id)}
                    </div>
                  ))}
                </div>
                <div
                  className="absolute left-0 right-0"
                  style={{ transform: `translateY(${windowedRows.start * rowHeight}px)` }}
                >
                  {windowedRows.rows.map((rowIndex) => (
                    <div key={rowIndex} className="flex" style={{ height: rowHeight }}>
                      <div
                        title={variables[rowIndex]}
                        style={{ width: 64 }}
                        className="flex-none bg-forest-900 px-1 text-right font-mono text-[10px] leading-none text-mist-400"
                      >
                        {trimmed(variables[rowIndex])}
                      </div>
                      {quadratic[rowIndex].map((value, colIndex) => {
                        const zero = Math.abs(value) < 1e-9
                        return (
                          <div
                            key={colIndex}
                            title={`Q[${variables[rowIndex]}, ${variables[colIndex]}] = ${value}`}
                            onMouseEnter={() => setHover({ row: rowIndex, col: colIndex, value })}
                            style={{
                              width: cellSize,
                              backgroundColor: cellColor(value, maxAbs, zero),
                            }}
                            className="flex-none cursor-default border-b border-r border-forest-700/40 last:border-r-0"
                          />
                        )
                      })}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="inline-block min-w-full">
                {/* column labels */}
                <div className="sticky top-0 z-20 flex bg-forest-900">
                  <div style={{ width: 64 }} className="flex-none" />
                  {variables.map((id) => (
                    <div
                      key={id}
                      title={id}
                      style={{ width: cellSize }}
                      className="px-0.5 text-center font-mono text-[10px] leading-none text-mist-500"
                    >
                      {trimmed(id)}
                    </div>
                  ))}
                </div>
                {quadratic.map((row, rowIndex) => (
                  <div key={rowIndex} className="flex" style={{ height: rowHeight }}>
                    <div
                      title={variables[rowIndex]}
                      style={{ width: 64 }}
                      className="sticky left-0 z-10 flex-none bg-forest-900 px-1 text-right font-mono text-[10px] leading-none text-mist-400"
                    >
                      {trimmed(variables[rowIndex])}
                    </div>
                    {row.map((value, colIndex) => {
                      const zero = Math.abs(value) < 1e-9
                      return (
                        <div
                          key={colIndex}
                          title={`Q[${variables[rowIndex]}, ${variables[colIndex]}] = ${value}`}
                          onMouseEnter={() => setHover({ row: rowIndex, col: colIndex, value })}
                          style={{
                            width: cellSize,
                            backgroundColor: cellColor(value, maxAbs, zero),
                          }}
                          className="cursor-default border-b border-r border-forest-700/40 last:border-r-0"
                        />
                      )
                    })}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* hover readout + legend */}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-[11px] text-mist-300">
          {hover
            ? `${variables[hover.row]} × ${variables[hover.col]} → ${hover.value}`
            : 'Hover a cell to inspect its coefficient'}
        </p>
        <div className="flex items-center gap-3 text-[11px] text-mist-500">
          <span>+ positive</span>
          <span className="flex items-center gap-1">
            <span className="h-2.5 w-6 rounded-sm" style={{ backgroundColor: cellColor(1, 1, false) }} />
          </span>
          <span>− negative</span>
          <span className="flex items-center gap-1">
            <span className="h-2.5 w-6 rounded-sm" style={{ backgroundColor: cellColor(-1, 1, false) }} />
          </span>
          <span>0</span>
          <span className="flex items-center gap-1">
            <span className="h-2.5 w-6 rounded-sm" style={{ backgroundColor: cellColor(0, 1, true) }} />
          </span>
        </div>
      </div>
    </div>
  )
}