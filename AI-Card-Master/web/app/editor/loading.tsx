import { Skeleton } from "@/components/ui/skeleton"

export default function EditorLoading() {
  return (
    <div className="flex h-svh flex-col overflow-hidden">
      <div className="flex h-12 shrink-0 items-center gap-3 border-b border-white/8 px-4">
        <Skeleton className="size-8 rounded-lg" />
        <Skeleton className="h-4 w-40" />
        <div className="ml-auto flex gap-2">
          <Skeleton className="h-8 w-20 rounded-lg" />
          <Skeleton className="h-8 w-24 rounded-lg" />
        </div>
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="flex flex-1 items-center justify-center p-6">
          <Skeleton className="h-[min(60vh,520px)] w-[min(45vw,360px)] rounded-xl" />
        </div>
        <div className="hidden w-[340px] shrink-0 border-l border-white/8 p-4 lg:block">
          <Skeleton className="mb-3 h-4 w-24" />
          <Skeleton className="mb-2 h-20 w-full rounded-lg" />
          <Skeleton className="mb-2 h-20 w-full rounded-lg" />
          <Skeleton className="h-10 w-full rounded-lg" />
        </div>
      </div>
    </div>
  )
}
