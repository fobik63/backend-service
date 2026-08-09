import Link from "next/link"
import { ArrowLeft } from "lucide-react"

import { buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export default function EditorLoading() {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="relative z-20 flex h-12 shrink-0 items-center gap-3 border-b border-white/8 px-3 sm:px-4">
        <Link
          href="/projects"
          className={cn(
            buttonVariants({ size: "sm", variant: "ghost" }),
            "shrink-0 gap-1.5 px-2 text-muted-foreground hover:text-foreground"
          )}
        >
          <ArrowLeft className="size-4 shrink-0" aria-hidden />
          <span>Назад в проекты</span>
        </Link>
        <Skeleton className="ml-1 h-4 w-40" />
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
