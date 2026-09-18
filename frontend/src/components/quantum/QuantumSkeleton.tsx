import { Skeleton, SkeletonText } from '../ui/Skeleton'

export function QuantumSkeleton() {
  return (
    <div className="space-y-5" role="status" aria-label="Loading quantum workspace">
      <div className="glass-card p-5">
        <div className="flex items-center gap-3">
          <Skeleton className="size-12 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-3 w-1/2" />
          </div>
        </div>
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <div className="glass-card space-y-4 p-5">
          <Skeleton className="h-4 w-40" />
          <div className="grid grid-cols-2 gap-4">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
          <SkeletonText width="w-1/3" />
        </div>
        <div className="glass-card space-y-4 p-5">
          <Skeleton className="h-4 w-40" />
          <div className="space-y-3">
            <Skeleton className="h-5" />
            <Skeleton className="h-5" />
            <Skeleton className="h-5" />
            <Skeleton className="h-5" />
          </div>
          <SkeletonText width="w-1/2" />
        </div>
      </div>
    </div>
  )
}