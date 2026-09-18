import type { CSSProperties } from 'react'

interface SkeletonProps {
  className?: string
  style?: CSSProperties
  role?: string
}

/** Animated loading placeholder. Always paired with text for screen readers. */
export function Skeleton({ className = '', style, role = 'status' }: SkeletonProps) {
  return (
    <div
      role={role}
      aria-label="Loading"
      style={style}
      className={`animate-pulse rounded-lg bg-forest-700/60 ${className}`}
    />
  )
}

export function SkeletonText({ width = 'w-full', role }: { width?: string; role?: string }) {
  return <Skeleton className={`h-3 ${width}`} role={role} />
}

export function KPISkeleton() {
  return (
    <div className="glass-card p-5" role="status" aria-label="Loading KPI">
      <div className="space-y-3">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-2.5 w-40" />
      </div>
    </div>
  )
}

export function ChartSkeleton({ height = 300 }: { height?: number }) {
  return (
    <div className="glass-card p-5" role="status" aria-label="Loading chart">
      <div className="space-y-4">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="w-full" style={{ height }} />
        <div className="flex gap-3">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-3 w-24" />
        </div>
      </div>
    </div>
  )
}