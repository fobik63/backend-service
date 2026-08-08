import { Skeleton } from "@/components/ui/skeleton"

type ProjectsGridSkeletonProps = {
  count?: number
}

function ProjectsGridSkeleton({ count = 6 }: ProjectsGridSkeletonProps) {
  return (
    <div
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3"
      aria-busy="true"
      aria-label="Загрузка проектов"
    >
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className="overflow-hidden rounded-xl border border-white/10 bg-white/[0.03]"
        >
          <Skeleton className="aspect-[3/4] w-full rounded-none" />
          <div className="space-y-3 p-4">
            <Skeleton className="h-5 w-[80%]" />
            <Skeleton className="h-3 w-[33%]" />
            <div className="flex gap-2 pt-2">
              <Skeleton className="h-8 w-24" />
              <Skeleton className="h-8 w-28" />
              <Skeleton className="h-8 w-20" />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

export { ProjectsGridSkeleton }
export type { ProjectsGridSkeletonProps }
