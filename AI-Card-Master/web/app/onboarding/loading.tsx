import { Skeleton } from "@/components/ui/skeleton"

export default function OnboardingLoading() {
  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-4 px-4 py-16">
      <Skeleton className="mx-auto h-6 w-48" />
      <Skeleton className="h-4 w-full max-w-sm self-center" />
      <Skeleton className="mt-4 h-28 w-full rounded-xl" />
      <Skeleton className="h-28 w-full rounded-xl" />
      <Skeleton className="mt-2 h-10 w-full rounded-lg" />
    </div>
  )
}
