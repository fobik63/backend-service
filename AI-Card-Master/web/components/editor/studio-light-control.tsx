"use client"

import { useRef, useState, type PointerEvent, type ReactNode } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Slider } from "@/components/ui/slider"
import { useEditorStore } from "@/lib/store/editor-store"
import { parseStudioLightInstruction } from "@/lib/utils/parse-studio-light"
import { cn } from "@/lib/utils"

const ANGLE_PICKER_SIZE = 168
const ANGLE_TRACK_RADIUS = 62
const ANGLE_MARKER_SIZE = 18

function FieldLabel({
  children,
  htmlFor,
}: {
  children: ReactNode
  htmlFor?: string
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase"
    >
      {children}
    </label>
  )
}

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n))
}

function angleFromPointer(
  clientX: number,
  clientY: number,
  rect: DOMRect
): number {
  const cx = rect.left + rect.width / 2
  const cy = rect.top + rect.height / 2
  const dx = clientX - cx
  const dy = clientY - cy
  // 0° = right, 90° = top (screen), counterclockwise — matches StudioLightDTO azimuth.
  let deg = (Math.atan2(-dy, dx) * 180) / Math.PI
  if (deg < 0) deg += 360
  return Math.round(deg) % 360
}

function AnglePicker({
  angle,
  disabled,
  onChange,
}: {
  angle: number
  disabled?: boolean
  onChange: (angle: number) => void
}) {
  const padRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  const updateFromEvent = (e: PointerEvent<HTMLDivElement>) => {
    const el = padRef.current
    if (!el) return
    onChange(angleFromPointer(e.clientX, e.clientY, el.getBoundingClientRect()))
  }

  const rad = (angle * Math.PI) / 180
  const markerX = Math.cos(rad) * ANGLE_TRACK_RADIUS
  const markerY = -Math.sin(rad) * ANGLE_TRACK_RADIUS

  return (
    <div className="flex flex-col items-center gap-2">
      <div
        ref={padRef}
        role="slider"
        tabIndex={disabled ? -1 : 0}
        aria-valuemin={0}
        aria-valuemax={360}
        aria-valuenow={angle}
        aria-valuetext={`${angle}°`}
        aria-label="Угол света"
        aria-disabled={disabled}
        onPointerDown={(e) => {
          if (disabled) return
          dragging.current = true
          e.currentTarget.setPointerCapture(e.pointerId)
          updateFromEvent(e)
        }}
        onPointerMove={(e) => {
          if (!dragging.current || disabled) return
          updateFromEvent(e)
        }}
        onPointerUp={() => {
          dragging.current = false
        }}
        onPointerCancel={() => {
          dragging.current = false
        }}
        onKeyDown={(e) => {
          if (disabled) return
          const step = e.shiftKey ? 15 : 5
          if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
            e.preventDefault()
            onChange((angle - step + 360) % 360)
          } else if (e.key === "ArrowRight" || e.key === "ArrowUp") {
            e.preventDefault()
            onChange((angle + step) % 360)
          } else if (e.key === "Home") {
            e.preventDefault()
            onChange(0)
          }
        }}
        className={cn(
          "relative touch-none select-none rounded-full outline-none",
          "bg-[radial-gradient(circle_at_center,rgba(255,255,255,0.08)_0%,rgba(255,255,255,0.02)_55%,transparent_70%)]",
          "ring-1 ring-white/12",
          "focus-visible:ring-2 focus-visible:ring-emerald/50",
          disabled && "pointer-events-none opacity-50"
        )}
        style={{ width: ANGLE_PICKER_SIZE, height: ANGLE_PICKER_SIZE }}
      >
        {/* Cardinal guides */}
        <span className="pointer-events-none absolute top-2 left-1/2 -translate-x-1/2 text-[9px] text-muted-foreground">
          90°
        </span>
        <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[9px] text-muted-foreground">
          0°
        </span>
        <span className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2 text-[9px] text-muted-foreground">
          270°
        </span>
        <span className="pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-[9px] text-muted-foreground">
          180°
        </span>

        {/* Orbit ring */}
        <span
          className="pointer-events-none absolute top-1/2 left-1/2 rounded-full border border-dashed border-white/20"
          style={{
            width: ANGLE_TRACK_RADIUS * 2,
            height: ANGLE_TRACK_RADIUS * 2,
            transform: "translate(-50%, -50%)",
          }}
        />

        {/* Beam from center to marker */}
        <span
          className="pointer-events-none absolute top-1/2 left-1/2 origin-left bg-gradient-to-r from-amber/70 to-amber/20"
          style={{
            width: ANGLE_TRACK_RADIUS,
            height: 2,
            transform: `rotate(${-angle}deg)`,
          }}
        />

        {/* Center product stand-in */}
        <span className="pointer-events-none absolute top-1/2 left-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white/35 ring-1 ring-white/20" />

        {/* Light marker */}
        <span
          className="pointer-events-none absolute top-1/2 left-1/2 rounded-full bg-amber shadow-[0_0_12px_rgba(245,158,11,0.55)] ring-2 ring-amber/40"
          style={{
            width: ANGLE_MARKER_SIZE,
            height: ANGLE_MARKER_SIZE,
            transform: `translate(calc(-50% + ${markerX}px), calc(-50% + ${markerY}px))`,
          }}
        />
      </div>
      <p className="font-mono text-[11px] text-foreground/80">
        light_angle {angle}°
      </p>
    </div>
  )
}

function ColorTempSlider({
  value,
  disabled,
  onChange,
}: {
  value: number
  disabled?: boolean
  onChange: (k: number) => void
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <FieldLabel>Color Temp</FieldLabel>
        <span className="font-mono text-[11px] text-foreground/80">
          {value}K {value <= 4000 ? "Warm" : value >= 5600 ? "Cold" : "Neutral"}
        </span>
      </div>
      <Slider
        min={2700}
        max={6500}
        step={50}
        disabled={disabled}
        value={[value]}
        onValueChange={(v) => {
          const next = Array.isArray(v) ? v[0] : v
          if (typeof next === "number") onChange(next)
        }}
      />
      <div
        className="h-1.5 rounded-full"
        style={{
          background:
            "linear-gradient(90deg, #ffb347 0%, #ffe8c7 35%, #f8fafc 55%, #c7e0ff 80%, #9ec5ff 100%)",
        }}
        aria-hidden
      />
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>2700K Warm</span>
        <span>6500K Cold</span>
      </div>
    </div>
  )
}

function StudioLightControl({ className }: { className?: string }) {
  const softbox = useEditorStore((s) => s.softbox)
  const setSoftbox = useEditorStore((s) => s.setSoftbox)
  const [prompt, setPrompt] = useState("")
  const disabled = !softbox.enabled

  const applyPrompt = () => {
    const trimmed = prompt.trim()
    if (!trimmed) {
      toast.error("Введите описание света")
      return
    }
    try {
      const parsed = parseStudioLightInstruction(trimmed)
      setSoftbox(parsed)
      toast.success("Свет применён по описанию")
    } catch {
      toast.error("Не удалось разобрать описание")
    }
  }

  return (
    <div className={cn("space-y-5", className)}>
      <AnglePicker
        angle={softbox.lightAngle}
        disabled={disabled}
        onChange={(lightAngle) => setSoftbox({ lightAngle })}
      />

      <div className="space-y-4">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <FieldLabel>Elevation</FieldLabel>
            <span className="font-mono text-[11px] text-foreground/80">
              {softbox.lightElevation}°
            </span>
          </div>
          <Slider
            min={10}
            max={90}
            step={1}
            disabled={disabled}
            value={[softbox.lightElevation]}
            onValueChange={(v) => {
              const next = Array.isArray(v) ? v[0] : v
              if (typeof next === "number") {
                setSoftbox({ lightElevation: clamp(next, 10, 90) })
              }
            }}
          />
          <div className="flex justify-between text-[10px] text-muted-foreground">
            <span>10° боковой</span>
            <span>90° сверху</span>
          </div>
        </div>

        <ColorTempSlider
          value={softbox.colorTempK}
          disabled={disabled}
          onChange={(colorTempK) => setSoftbox({ colorTempK })}
        />

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <FieldLabel>Интенсивность</FieldLabel>
            <span className="font-mono text-[11px] text-foreground/80">
              {softbox.intensity}%
            </span>
          </div>
          <Slider
            min={0}
            max={200}
            step={1}
            disabled={disabled}
            value={[softbox.intensity]}
            onValueChange={(v) => {
              const next = Array.isArray(v) ? v[0] : v
              if (typeof next === "number") {
                setSoftbox({ intensity: clamp(next, 0, 200) })
              }
            }}
          />
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <FieldLabel>Diffusion</FieldLabel>
            <span className="font-mono text-[11px] text-foreground/80">
              {softbox.softboxDiffusion}%
            </span>
          </div>
          <Slider
            min={0}
            max={100}
            step={1}
            disabled={disabled}
            value={[softbox.softboxDiffusion]}
            onValueChange={(v) => {
              const next = Array.isArray(v) ? v[0] : v
              if (typeof next === "number") {
                setSoftbox({ softboxDiffusion: clamp(next, 0, 100) })
              }
            }}
          />
          <div className="flex justify-between text-[10px] text-muted-foreground">
            <span>Жёсткая тень</span>
            <span>Мягкая</span>
          </div>
        </div>
      </div>

      <div className="space-y-2 border-t border-white/8 pt-4">
        <FieldLabel htmlFor="studio-light-prompt">Опишите свет…</FieldLabel>
        <div className="flex gap-2">
          <Input
            id="studio-light-prompt"
            value={prompt}
            disabled={disabled}
            placeholder="мягкий тёплый свет слева сверху"
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault()
                applyPrompt()
              }
            }}
          />
          <Button
            type="button"
            size="sm"
            disabled={disabled || !prompt.trim()}
            onClick={applyPrompt}
          >
            Применить
          </Button>
        </div>
      </div>
    </div>
  )
}

export { StudioLightControl }
