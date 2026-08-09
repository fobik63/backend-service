import type { ReactNode } from "react"
import type { LucideIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type StatePanelProps = {
  icon?: LucideIcon
  title: string
  description?: string
  action?: ReactNode
  variant?: "empty" | "error" | "loading"
  className?: string
}

function StatePanel({
  icon: Icon,
  title,
  description,
  action,
  variant = "empty",
  className,
}: StatePanelProps) {
  return (
    <div
      role={variant === "error" ? "alert" : "status"}
      className={cn(
        "flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed px-6 py-12 text-center",
        variant === "error"
          ? "border-destructive/35 bg-destructive/5"
          : "border-white/12 bg-loft-surface",
        className
      )}
    >
      {Icon ? (
        <span
          className={cn(
            "flex size-12 items-center justify-center rounded-lg border",
            variant === "error"
              ? "border-destructive/30 text-destructive"
              : "border-white/12 text-muted-foreground"
          )}
        >
          <Icon className="size-5" strokeWidth={1.5} aria-hidden />
        </span>
      ) : null}
      <div className="max-w-sm space-y-1.5">
        <h2 className="font-heading text-lg font-semibold tracking-tight">
          {title}
        </h2>
        {description ? (
          <p className="text-sm leading-relaxed text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {action}
    </div>
  )
}

type InlineErrorProps = {
  message: string
  onRetry?: () => void
  retryLabel?: string
  className?: string
}

function InlineError({
  message,
  onRetry,
  retryLabel = "Повторить",
  className,
}: InlineErrorProps) {
  return (
    <div
      role="alert"
      className={cn(
        "rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-5 text-center",
        className
      )}
    >
      <p className="text-sm text-foreground">{message}</p>
      {onRetry ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-3"
          onClick={onRetry}
        >
          {retryLabel}
        </Button>
      ) : null}
    </div>
  )
}

export { StatePanel, InlineError }
export type { StatePanelProps, InlineErrorProps }
