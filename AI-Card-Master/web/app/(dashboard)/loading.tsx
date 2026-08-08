import { ProjectsGridSkeleton } from "@/components/dashboard/projects/projects-skeleton"

export default function DashboardLoading() {
  return (
    <section className="mx-auto w-full max-w-7xl space-y-6">
      <div className="space-y-2">
        <div className="h-8 w-48 animate-pulse rounded-md bg-white/10" />
        <div className="h-4 w-96 max-w-full animate-pulse rounded-md bg-white/10" />
      </div>
      <div className="h-10 w-full max-w-xl animate-pulse rounded-lg bg-white/10" />
      <ProjectsGridSkeleton />
    </section>
  )
}
