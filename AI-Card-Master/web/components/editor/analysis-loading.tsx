"use client"

import { AnimatePresence, motion, type HTMLMotionProps } from "framer-motion"
import { Loader2 } from "lucide-react"
import type { ReactNode } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

type AnalysisAccent = "emerald" | "amber"

type AnalysisStatusBarProps = {
  label: string
  accent?: AnalysisAccent
  /** 1-based step for determinate progress. */
  step?: number
  totalSteps?: number
  className?: string
}

const ACCENT: Record<
  AnalysisAccent,
  { shell: string; text: string; bar: string; track: string }
> = {
  emerald: {
    shell: "border-emerald/25 bg-emerald/10",
    text: "text-emerald",
    bar: "bg-emerald",
    track: "bg-emerald/20",
  },
  amber: {
    shell: "border-amber/25 bg-amber/10",
    text: "text-amber",
    bar: "bg-amber",
    track: "bg-amber/20",
  },
}

function AnalysisStatusBar({
  label,
  accent = "emerald",
  step,
  totalSteps,
  className,
}: AnalysisStatusBarProps) {
  const styles = ACCENT[accent]
  const determinate =
    typeof step === "number" &&
    typeof totalSteps === "number" &&
    totalSteps > 0 &&
    step > 0
  const pct = determinate
    ? Math.min(96, Math.max(12, (step / totalSteps) * 100))
    : null

  return (
    <motion.div
      role="status"
      aria-live="polite"
      aria-busy="true"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -6 }}
      transition={{ duration: 0.28, ease: "easeOut" }}
      className={cn(
        "space-y-2 rounded-md border px-2.5 py-2.5",
        styles.shell,
        className,
      )}
    >
      <div
        className={cn(
          "flex items-center gap-2 text-[11px] leading-relaxed font-medium",
          styles.text,
        )}
      >
        <Loader2 className="size-3.5 shrink-0 animate-spin" aria-hidden />
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={label}
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -5 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="min-w-0"
          >
            {label}
          </motion.span>
        </AnimatePresence>
      </div>

      <div
        className={cn("h-1 w-full overflow-hidden rounded-full", styles.track)}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct != null ? Math.round(pct) : undefined}
        aria-label={label}
      >
        {pct != null ? (
          <motion.div
            className={cn("gpu-anim h-full w-full origin-left rounded-full", styles.bar)}
            initial={false}
            animate={{ scaleX: Math.min(1, Math.max(0, pct / 100)) }}
            style={{ transformOrigin: "left center" }}
            transition={{ duration: 0.45, ease: "easeOut" }}
          />
        ) : (
          <div
            className={cn(
              "h-full w-1/3 animate-[progress-indeterminate_1.2s_ease-in-out_infinite] rounded-full",
              styles.bar,
            )}
          />
        )}
      </div>
    </motion.div>
  )
}

type FadeInBlockProps = HTMLMotionProps<"div"> & {
  children: ReactNode
}

function FadeInBlock({ children, className, ...props }: FadeInBlockProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 6 }}
      transition={{ duration: 0.32, ease: "easeOut" }}
      className={className}
      {...props}
    >
      {children}
    </motion.div>
  )
}

type StaggerItemProps = {
  children: ReactNode
  index?: number
  className?: string
}

function StaggerItem({ children, index = 0, className }: StaggerItemProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.3,
        delay: 0.05 + index * 0.07,
        ease: "easeOut",
      }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

function ProductMetaSkeleton() {
  return (
    <div className="space-y-2 border-t border-white/8 pt-2.5">
      <StaggerItem index={0} className="space-y-1">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-8 w-full" />
      </StaggerItem>
      <div className="grid grid-cols-2 gap-2">
        <StaggerItem index={1} className="space-y-1">
          <Skeleton className="h-3 w-14" />
          <Skeleton className="h-8 w-full" />
        </StaggerItem>
        <StaggerItem index={2} className="space-y-1">
          <Skeleton className="h-3 w-12" />
          <Skeleton className="h-8 w-full" />
        </StaggerItem>
      </div>
      <StaggerItem index={3} className="space-y-1">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="min-h-[5.5rem] w-full" />
      </StaggerItem>
    </div>
  )
}

function EyeCompetitorsSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-2">
      <Skeleton className="h-3 w-36" />
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
        {Array.from({ length: count }, (_, index) => (
          <StaggerItem key={index} index={index}>
            <div className="overflow-hidden rounded-lg border border-white/8 bg-white/[0.03]">
              <Skeleton className="aspect-[3/4] w-full rounded-none" />
              <div className="space-y-1.5 p-1.5">
                <Skeleton className="h-2.5 w-full" />
                <Skeleton className="h-2.5 w-2/3" />
              </div>
            </div>
          </StaggerItem>
        ))}
      </div>
    </div>
  )
}

function EyeInsightsSkeleton() {
  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Skeleton className="h-3 w-28" />
        {[0, 1, 2].map((index) => (
          <StaggerItem key={index} index={index}>
            <div className="space-y-1.5 rounded-md border border-white/8 bg-white/[0.03] px-2.5 py-2">
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-2.5 w-full" />
              <Skeleton className="h-2.5 w-5/6" />
            </div>
          </StaggerItem>
        ))}
      </div>
      <div className="space-y-1.5">
        <Skeleton className="h-3 w-40" />
        {[0, 1].map((index) => (
          <StaggerItem key={`rec-${index}`} index={index + 3}>
            <Skeleton className="h-10 w-full rounded-md" />
          </StaggerItem>
        ))}
      </div>
    </div>
  )
}

export {
  AnalysisStatusBar,
  EyeCompetitorsSkeleton,
  EyeInsightsSkeleton,
  FadeInBlock,
  ProductMetaSkeleton,
  StaggerItem,
}
export type { AnalysisAccent, AnalysisStatusBarProps }
