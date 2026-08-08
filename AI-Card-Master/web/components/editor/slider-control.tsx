"use client"

import type { ReactNode } from "react"

import { Slider } from "@/components/ui/slider"
import { cn } from "@/lib/utils"

type SliderControlProps = {
  label: string
  value: number
  min: number
  max: number
  step?: number
  unit?: string
  disabled?: boolean
  formatValue?: (value: number) => string
  onChange: (value: number) => void
  hint?: ReactNode
  className?: string
}

function SliderControl({
  label,
  value,
  min,
  max,
  step = 1,
  unit,
  disabled,
  formatValue,
  onChange,
  hint,
  className,
}: SliderControlProps) {
  const display =
    formatValue?.(value) ?? `${value}${unit ? ` ${unit}` : ""}`

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          {label}
        </span>
        <span className="font-mono text-[11px] tabular-nums text-foreground/80">
          {display}
        </span>
      </div>
      <Slider
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        value={[value]}
        onValueChange={(v) => {
          const next = Array.isArray(v) ? v[0] : v
          if (typeof next === "number") onChange(next)
        }}
      />
      {hint ? (
        <div className="text-[10px] text-muted-foreground">{hint}</div>
      ) : null}
    </div>
  )
}

export { SliderControl }
export type { SliderControlProps }
