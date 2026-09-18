import { ChartSkeleton, KPISkeleton, Skeleton } from '../ui/Skeleton'

export function ComparisonSkeleton() {
  return (
    <div role="status" aria-label="Loading model comparison" className="space-y-5">
      <span className="sr-only">Loading model comparison data…</span>
      <div className="space-y-2">
        <Skeleton className="h-7 w-52" />
        <Skeleton className="h-4 w-72" />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {Array.from({ length: 5 }).map((_, index) => (
          <KPISkeleton key={index} />
        ))}
      </div>
      <Skeleton className="h-14 w-full" />
      <div className="overflow-hidden rounded-xl border border-forest-700/50">
        <Skeleton className="h-10 w-full" />
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-12 w-full rounded-none" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartSkeleton height={320} />
        <ChartSkeleton height={320} />
        <ChartSkeleton height={320} />
        <ChartSkeleton height={320} />
      </div>
    </div>
  )
}