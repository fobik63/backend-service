"use client"

import {
  CircleCheck,
  Droplets,
  Leaf,
  Package,
  Shield,
  Sparkles,
  Star,
  type LucideIcon,
} from "lucide-react"
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type RefObject,
} from "react"

import { ImageWithSkeleton } from "@/components/ui/image-with-skeleton"
import { Skeleton } from "@/components/ui/skeleton"
import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "@/lib/constants/mock-editor"
import {
  useEditorStore,
  type SoftboxSettings,
} from "@/lib/store/editor-store"
import type { CanvasLayer } from "@/types/canvas"
import { cn } from "@/lib/utils"

const CHIP_ICON_MAP: Record<string, LucideIcon> = {
  icon_check: CircleCheck,
  icon_drop: Droplets,
  icon_leaf: Leaf,
  icon_shield: Shield,
  icon_star: Star,
  icon_spark: Sparkles,
  icon_box: Package,
}

type InteractMode = "drag" | "rotate" | "scale"

type DragSession = {
  mode: InteractMode
  layerId: string
  startClientX: number
  startClientY: number
  originX: number
  originY: number
  originScale: number
  originRotation: number
  centerX: number
  centerY: number
  startPointerAngle: number
  startPointerDist: number
}

function chipTextColor(bg: string): string {
  const hex = bg.toLowerCase()
  if (hex === "#ffffff" || hex === "#fff" || hex === "#f59e0b") {
    return "#0F1115"
  }
  return "#FFFFFF"
}

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n))
}

function clamp01(n: number) {
  return clamp(n, 0, 1)
}

function warmthFromKelvin(k: number): number {
  return clamp01((6500 - k) / (6500 - 2700))
}

/** Studio backdrop without a hard point light — wash comes from SoftboxLightOverlay. */
function softboxBackground(softbox: SoftboxSettings): string {
  if (!softbox.enabled) {
    return "linear-gradient(160deg, #1a1d24 0%, #0f1115 100%)"
  }

  const warmth = warmthFromKelvin(softbox.colorTempK)
  const coolLift = Math.round((1 - warmth) * 12)
  const warmLift = Math.round(warmth * 14)
  return `
    linear-gradient(
      155deg,
      color-mix(in srgb, #1e2430 ${100 - coolLift}%, #9ec5ff ${coolLift}%) 0%,
      #12151b 48%,
      color-mix(in srgb, #0f1115 ${100 - warmLift}%, #f59e0b ${warmLift}%) 100%
    )
  `
}

function softboxLightColor(colorTempK: number): string {
  const warmth = warmthFromKelvin(colorTempK)
  const cool = Math.round((1 - warmth) * 100)
  const warm = Math.round(warmth * 100)
  return `color-mix(in srgb, #f4f7fb ${cool}%, #ffb347 ${warm}%)`
}

function softboxKeyPosition(softbox: SoftboxSettings): { x: number; y: number } {
  const rad = (softbox.lightAngle * Math.PI) / 180
  const elevFactor = 0.55 + ((softbox.lightElevation - 10) / 80) * 0.45
  return {
    x: 50 + Math.cos(rad) * 38 * elevFactor,
    y: 50 - Math.sin(rad) * 38 * elevFactor,
  }
}

/** Multi-layer softbox: diffused radials + blur + soft-light / overlay. */
function SoftboxLightOverlay({ softbox }: { softbox: SoftboxSettings }) {
  if (!softbox.enabled) return null

  const lightColor = softboxLightColor(softbox.colorTempK)
  const intensity = clamp(softbox.intensity / 100, 0, 2)
  const diffusion = softbox.softboxDiffusion / 100
  const { x, y } = softboxKeyPosition(softbox)
  const fillX = 50 - (x - 50) * 0.35
  const fillY = 50 - (y - 50) * 0.25

  const coreSpread = 22 + diffusion * 38
  const panelSpread = 48 + diffusion * 42
  const ambientSpread = 70 + diffusion * 30
  const panelBlur = 28 + diffusion * 72
  const coreBlur = 12 + diffusion * 36
  const ambientBlur = 40 + diffusion * 90

  return (
    <div
      className="pointer-events-none absolute inset-0 z-0 overflow-hidden"
      aria-hidden
    >
      {/* Large softbox panel — soft-light wash across set */}
      <div
        className="absolute inset-[-30%]"
        style={{
          background: `radial-gradient(ellipse ${panelSpread * 1.15}% ${panelSpread}% at ${x}% ${y}%, ${lightColor} 0%, transparent 68%)`,
          opacity: 0.42 * intensity,
          filter: `blur(${panelBlur}px)`,
          mixBlendMode: "soft-light",
        }}
      />
      {/* Hotter key core — overlay for specular punch */}
      <div
        className="absolute inset-[-20%]"
        style={{
          background: `radial-gradient(circle at ${x}% ${y}%, color-mix(in srgb, ${lightColor} 85%, white) 0%, transparent ${coreSpread}%)`,
          opacity: 0.28 * intensity,
          filter: `blur(${coreBlur}px)`,
          mixBlendMode: "overlay",
        }}
      />
      {/* Fill / bounce from opposite side */}
      <div
        className="absolute inset-[-25%]"
        style={{
          background: `radial-gradient(ellipse ${ambientSpread}% ${ambientSpread * 0.85}% at ${fillX}% ${fillY}%, color-mix(in srgb, ${lightColor} 55%, transparent) 0%, transparent 72%)`,
          opacity: 0.22 * intensity * (0.55 + diffusion * 0.45),
          filter: `blur(${ambientBlur}px)`,
          mixBlendMode: "soft-light",
        }}
      />
      {/* Floor / base catch light */}
      <div
        className="absolute inset-x-[-10%] bottom-[-5%] h-[45%]"
        style={{
          background: `radial-gradient(ellipse 70% 55% at 50% 100%, color-mix(in srgb, ${lightColor} 40%, transparent) 0%, transparent 70%)`,
          opacity: 0.18 * intensity,
          filter: `blur(${24 + diffusion * 40}px)`,
          mixBlendMode: "soft-light",
        }}
      />
    </div>
  )
}

function normalizeAngle(deg: number): number {
  const mod = deg % 360
  return mod < 0 ? mod + 360 : mod
}

function angleDeg(cx: number, cy: number, x: number, y: number): number {
  return (Math.atan2(y - cy, x - cx) * 180) / Math.PI
}

function dist(cx: number, cy: number, x: number, y: number): number {
  return Math.hypot(x - cx, y - cy)
}

function layerDefaults(layer: CanvasLayer): {
  x: number
  y: number
  scale: number
  rotation: number
  width?: number
  height?: number
} {
  if (layer.type === "image") {
    return {
      x: layer.x ?? 27,
      y: layer.y ?? 23,
      width: layer.width ?? 46,
      height: layer.height ?? 38,
      scale: layer.scale ?? 1,
      rotation: layer.rotation ?? 0,
    }
  }
  if (layer.type === "text") {
    return {
      x: layer.x ?? 8,
      y: layer.y ?? 68,
      width: layer.width ?? 84,
      scale: layer.scale ?? 1,
      rotation: layer.rotation ?? 0,
    }
  }
  return {
    x: layer.x ?? 50,
    y: layer.y ?? 50,
    scale: layer.scale ?? 1,
    rotation: layer.rotation ?? 0,
  }
}

const CORNER_HANDLES = [
  { key: "nw", cursor: "nwse-resize", style: { left: 0, top: 0 } },
  { key: "ne", cursor: "nesw-resize", style: { left: "100%", top: 0 } },
  { key: "sw", cursor: "nesw-resize", style: { left: 0, top: "100%" } },
  { key: "se", cursor: "nwse-resize", style: { left: "100%", top: "100%" } },
] as const

function SelectionChrome({
  disabled,
  onRotatePointerDown,
  onScalePointerDown,
}: {
  disabled: boolean
  onRotatePointerDown: (e: ReactPointerEvent) => void
  onScalePointerDown: (e: ReactPointerEvent) => void
}) {
  return (
    <div className="pointer-events-none absolute inset-0 z-10" aria-hidden>
      <div className="absolute inset-0 border border-emerald/90" />

      <div className="absolute left-1/2 top-0 flex -translate-x-1/2 -translate-y-full flex-col items-center">
        <button
          type="button"
          disabled={disabled}
          className={cn(
            "pointer-events-auto mb-0 size-4 shrink-0 border border-emerald bg-loft-surface shadow-sm",
            "cursor-grab active:cursor-grabbing",
            "rounded-t-full rounded-b-sm",
            disabled && "pointer-events-none opacity-40"
          )}
          aria-label="Вращать"
          onPointerDown={onRotatePointerDown}
        />
        <span className="h-3 w-px bg-emerald/90" />
      </div>

      {CORNER_HANDLES.map((h) => (
        <button
          key={h.key}
          type="button"
          disabled={disabled}
          className={cn(
            "pointer-events-auto absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full",
            "border border-emerald bg-white shadow-sm",
            disabled && "pointer-events-none opacity-40"
          )}
          style={{ ...h.style, cursor: disabled ? "default" : h.cursor }}
          aria-label="Масштабировать"
          onPointerDown={onScalePointerDown}
        />
      ))}
    </div>
  )
}

function InteractiveLayer({
  layer,
  selected,
  flashing,
  canvasRef,
  children,
  className,
  style,
  editableText,
  onCommitText,
}: {
  layer: CanvasLayer
  selected: boolean
  flashing?: boolean
  canvasRef: RefObject<HTMLDivElement | null>
  children: ReactNode
  className?: string
  style?: CSSProperties
  editableText?: boolean
  onCommitText?: (text: string) => void
}) {
  const selectLayer = useEditorStore((s) => s.selectLayer)
  const updateLayer = useEditorStore((s) => s.updateLayer)

  const [editing, setEditing] = useState(false)
  const sessionRef = useRef<DragSession | null>(null)
  const nodeRef = useRef<HTMLDivElement>(null)
  const textRef = useRef<HTMLDivElement>(null)
  const defsRef = useRef(layerDefaults(layer))
  defsRef.current = layerDefaults(layer)

  const locked = layer.locked
  const defs = defsRef.current

  const beginSession = useCallback(
    (e: ReactPointerEvent, mode: InteractMode) => {
      if (locked || editing) return
      const canvas = canvasRef.current
      const node = nodeRef.current
      if (!canvas || !node) return

      e.preventDefault()
      e.stopPropagation()
      selectLayer(layer.id)

      const rect = node.getBoundingClientRect()
      const centerX = rect.left + rect.width / 2
      const centerY = rect.top + rect.height / 2
      const d = defsRef.current

      sessionRef.current = {
        mode,
        layerId: layer.id,
        startClientX: e.clientX,
        startClientY: e.clientY,
        originX: d.x,
        originY: d.y,
        originScale: d.scale,
        originRotation: d.rotation,
        centerX,
        centerY,
        startPointerAngle: angleDeg(centerX, centerY, e.clientX, e.clientY),
        startPointerDist: Math.max(8, dist(centerX, centerY, e.clientX, e.clientY)),
      }
    },
    [canvasRef, editing, layer.id, locked, selectLayer]
  )

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const session = sessionRef.current
      const canvas = canvasRef.current
      if (!session || !canvas || session.layerId !== layer.id) return

      if (session.mode === "drag") {
        const cw = canvas.clientWidth
        const ch = canvas.clientHeight
        if (cw <= 0 || ch <= 0) return
        const dxPct = ((e.clientX - session.startClientX) / cw) * 100
        const dyPct = ((e.clientY - session.startClientY) / ch) * 100
        updateLayer(layer.id, {
          x: clamp(session.originX + dxPct, -30, 110),
          y: clamp(session.originY + dyPct, -30, 110),
        })
        return
      }

      if (session.mode === "rotate") {
        const ang = angleDeg(
          session.centerX,
          session.centerY,
          e.clientX,
          e.clientY
        )
        updateLayer(layer.id, {
          rotation: normalizeAngle(
            session.originRotation + (ang - session.startPointerAngle)
          ),
        })
        return
      }

      if (session.mode === "scale") {
        const d = dist(session.centerX, session.centerY, e.clientX, e.clientY)
        const ratio = d / session.startPointerDist
        updateLayer(layer.id, {
          scale: clamp(session.originScale * ratio, 0.2, 4),
        })
      }
    }

    const onUp = () => {
      sessionRef.current = null
    }

    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", onUp)
    window.addEventListener("pointercancel", onUp)
    return () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", onUp)
      window.removeEventListener("pointercancel", onUp)
    }
  }, [canvasRef, layer.id, updateLayer])

  useEffect(() => {
    if (!editing || !textRef.current) return
    const el = textRef.current
    el.focus()
    const range = document.createRange()
    range.selectNodeContents(el)
    const sel = window.getSelection()
    sel?.removeAllRanges()
    sel?.addRange(range)
  }, [editing])

  const finishEditing = () => {
    if (!editing) return
    const raw = textRef.current?.innerText ?? ""
    const next = raw.replace(/\u00a0/g, " ").trimEnd()
    onCommitText?.(next)
    setEditing(false)
  }

  return (
    <div
      ref={nodeRef}
      role="button"
      tabIndex={0}
      aria-label={layer.name}
      aria-pressed={selected}
      data-layer-id={layer.id}
      className={cn(
        "absolute touch-none select-none outline-none",
        !locked && !editing && "cursor-grab active:cursor-grabbing",
        locked && "cursor-default",
        flashing && "animate-[layer-flash_0.9s_ease-out]"
      )}
      style={{
        left: `${defs.x}%`,
        top: `${defs.y}%`,
        width: defs.width != null ? `${defs.width}%` : undefined,
        height: defs.height != null ? `${defs.height}%` : undefined,
        opacity: layer.opacity,
        zIndex: layer.zIndex + (selected || flashing ? 100 : 0),
        transform: `rotate(${defs.rotation}deg) scale(${defs.scale})`,
        transformOrigin: "center center",
      }}
      onPointerDown={(e) => {
        if (e.button !== 0) return
        if (editing) {
          e.stopPropagation()
          return
        }
        beginSession(e, "drag")
      }}
      onClick={(e) => {
        e.stopPropagation()
        selectLayer(layer.id)
      }}
      onDoubleClick={(e) => {
        e.stopPropagation()
        if (!editableText || locked) return
        selectLayer(layer.id)
        setEditing(true)
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape" && editing) {
          e.preventDefault()
          finishEditing()
        }
      }}
    >
      <div
        className={cn(
          "relative",
          editing && "ring-1 ring-emerald/60",
          flashing && "ring-2 ring-amber shadow-[0_0_0_4px_rgba(245,158,11,0.35)]",
          className
        )}
        style={style}
      >
        {editableText && editing ? (
          <div
            ref={textRef}
            contentEditable
            suppressContentEditableWarning
            role="textbox"
            aria-label="Редактирование текста"
            className="min-w-[2ch] cursor-text whitespace-pre-wrap break-words outline-none"
            style={{
              fontSize: "inherit",
              fontFamily: "inherit",
              fontWeight: "inherit",
              color: "inherit",
            }}
            onBlur={finishEditing}
            onPointerDown={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                finishEditing()
              }
            }}
          >
            {layer.text ?? ""}
          </div>
        ) : (
          children
        )}

        {selected && !editing ? (
          <SelectionChrome
            disabled={locked}
            onRotatePointerDown={(e) => beginSession(e, "rotate")}
            onScalePointerDown={(e) => beginSession(e, "scale")}
          />
        ) : null}
      </div>
    </div>
  )
}

function ProductLayer({
  layer,
  selected,
  flashing,
  canvasScale,
  canvasRef,
  softbox,
  productPreviewUrl,
}: {
  layer: CanvasLayer
  selected: boolean
  flashing?: boolean
  canvasScale: number
  canvasRef: RefObject<HTMLDivElement | null>
  softbox: SoftboxSettings
  productPreviewUrl: string | null
}) {
  const rad = (softbox.lightAngle * Math.PI) / 180
  const cast = softbox.enabled
    ? 0.55 - ((softbox.lightElevation - 10) / 80) * 0.42
    : 0
  const shadowX = softbox.enabled ? -Math.cos(rad) * 28 * (0.7 + cast) : 0
  const shadowY = softbox.enabled ? 8 + Math.max(0.15, cast) * 28 : 8
  const shadowBlur = softbox.enabled
    ? 18 + (softbox.softboxDiffusion / 100) * 40
    : 24

  const lightColor = softboxLightColor(softbox.colorTempK)
  const intensity = softbox.intensity / 100
  const diffusion = softbox.softboxDiffusion / 100
  const { x: lx, y: ly } = softboxKeyPosition(softbox)
  // Map canvas light position into product-local highlight (relative wash)
  const localX = clamp(30 + (lx - 50) * 0.9, 5, 95)
  const localY = clamp(25 + (ly - 50) * 0.9, 5, 95)
  const sheenBlur = 8 + diffusion * 22

  return (
    <InteractiveLayer
      layer={layer}
      selected={selected}
      flashing={flashing}
      canvasRef={canvasRef}
      className="size-full"
      style={{
        boxShadow: `${shadowX * canvasScale}px ${shadowY * canvasScale}px ${shadowBlur * canvasScale}px rgba(0,0,0,0.55)`,
      }}
    >
      <div
        className={cn(
          "absolute inset-0 overflow-hidden rounded-[18%] border border-white/15",
          !productPreviewUrl && "bg-gradient-to-b from-copper/45 to-sage/55"
        )}
      >
        {productPreviewUrl ? (
          <ImageWithSkeleton
            src={productPreviewUrl}
            alt="Товар на холсте"
            className="pointer-events-none absolute inset-0 size-full"
            skeletonClassName="rounded-none"
            onLoad={() => {
              if (useEditorStore.getState().busyKind === "loading-image") {
                useEditorStore.getState().setBusyKind("idle")
              }
            }}
            onLoadError={() => {
              if (useEditorStore.getState().busyKind === "loading-image") {
                useEditorStore.getState().setBusyKind("idle")
              }
            }}
          />
        ) : (
          <span className="sr-only">Слой товара</span>
        )}
        {softbox.enabled ? (
          <>
            <div
              className="pointer-events-none absolute inset-0"
              style={{
                background: `radial-gradient(ellipse ${48 + diffusion * 30}% ${40 + diffusion * 28}% at ${localX}% ${localY}%, ${lightColor} 0%, transparent 70%)`,
                opacity: 0.35 * intensity,
                filter: `blur(${sheenBlur}px)`,
                mixBlendMode: "soft-light",
              }}
              aria-hidden
            />
            <div
              className="pointer-events-none absolute inset-0"
              style={{
                background: `radial-gradient(circle at ${localX}% ${localY}%, color-mix(in srgb, ${lightColor} 70%, white) 0%, transparent ${18 + diffusion * 20}%)`,
                opacity: 0.22 * intensity,
                filter: `blur(${4 + diffusion * 12}px)`,
                mixBlendMode: "overlay",
              }}
              aria-hidden
            />
          </>
        ) : null}
      </div>
    </InteractiveLayer>
  )
}

function TextLayerView({
  layer,
  selected,
  flashing,
  canvasScale,
  canvasRef,
  subtitle,
}: {
  layer: CanvasLayer
  selected: boolean
  flashing?: boolean
  canvasScale: number
  canvasRef: RefObject<HTMLDivElement | null>
  subtitle?: string
}) {
  const updateLayer = useEditorStore((s) => s.updateLayer)
  const ts = layer.textStyle
  const fontSize = Math.max(14, (ts?.fontSize ?? 42) * canvasScale * 0.85)

  return (
    <InteractiveLayer
      layer={layer}
      selected={selected}
      flashing={flashing}
      canvasRef={canvasRef}
      className="text-left"
      editableText
      onCommitText={(text) => updateLayer(layer.id, { text })}
      style={{
        fontSize,
        fontWeight: ts?.fontWeight ?? 600,
        color: ts?.color ?? "var(--foreground)",
        fontFamily: ts?.fontFamily,
      }}
    >
      <span
        className="block font-heading font-semibold tracking-tight"
        style={{
          textShadow: ts?.shadowEnabled
            ? `${ts.shadowOffsetX}px ${ts.shadowOffsetY}px ${ts.shadowBlur}px ${ts.shadowColor}`
            : undefined,
        }}
      >
        {layer.text ?? ""}
      </span>
      {subtitle ? (
        <span
          className="mt-1 block text-copper/90"
          style={{ fontSize: Math.max(10, 20 * canvasScale) }}
        >
          {subtitle}
        </span>
      ) : null}
    </InteractiveLayer>
  )
}

function ChipLayerView({
  layer,
  selected,
  flashing,
  canvasScale,
  canvasRef,
}: {
  layer: CanvasLayer & { chip: NonNullable<CanvasLayer["chip"]> }
  selected: boolean
  flashing?: boolean
  canvasScale: number
  canvasRef: RefObject<HTMLDivElement | null>
}) {
  const chip = layer.chip
  const Icon = CHIP_ICON_MAP[chip.iconId] ?? CircleCheck
  const fg = chipTextColor(chip.bgColor)

  return (
    <InteractiveLayer
      layer={layer}
      selected={selected}
      flashing={flashing}
      canvasRef={canvasRef}
      className="flex max-w-[42%] items-center gap-1.5 border border-black/10 px-2.5 py-1.5 font-heading font-semibold shadow-sm"
      style={{
        backgroundColor: chip.bgColor,
        color: fg,
        borderRadius: chip.borderRadius,
        fontSize: Math.max(10, 16 * canvasScale),
      }}
    >
      <Icon
        className="pointer-events-none shrink-0"
        style={{
          width: Math.max(12, 16 * canvasScale),
          height: Math.max(12, 16 * canvasScale),
        }}
        aria-hidden
      />
      <span className="pointer-events-none truncate">{chip.label}</span>
    </InteractiveLayer>
  )
}

function EditorCanvas({
  scale,
  softbox,
}: {
  scale: number
  softbox: SoftboxSettings
}) {
  const layers = useEditorStore((s) => s.layers)
  const selectedLayerId = useEditorStore((s) => s.selectedLayerId)
  const flashLayerId = useEditorStore((s) => s.flashLayerId)
  const selectLayer = useEditorStore((s) => s.selectLayer)
  const productPreviewUrl = useEditorStore((s) => s.productPreviewUrl)
  const busyKind = useEditorStore((s) => s.busyKind)
  const canvasRef = useRef<HTMLDivElement>(null)

  const showBusyOverlay =
    busyKind === "generating" ||
    busyKind === "removing-bg" ||
    busyKind === "loading-image"

  const interactiveLayers = layers
    .filter((l) => l.visible && l.type !== "background")
    .sort((a, b) => a.zIndex - b.zIndex)

  return (
    <div
      ref={canvasRef}
      id="editor-export-canvas"
      data-export-canvas="true"
      className="relative overflow-hidden bg-loft shadow-[0_24px_80px_rgba(0,0,0,0.55)] ring-1 ring-white/10"
      style={{
        width: CANVAS_WIDTH * scale,
        height: CANVAS_HEIGHT * scale,
        background: softboxBackground(softbox),
      }}
      role="img"
      aria-label={`Холст ${CANVAS_WIDTH}×${CANVAS_HEIGHT}`}
      aria-busy={showBusyOverlay}
      onPointerDown={() => selectLayer(null)}
    >
      <SoftboxLightOverlay softbox={softbox} />

      {interactiveLayers.map((layer) => {
        const selected = selectedLayerId === layer.id
        const flashing = flashLayerId === layer.id

        if (layer.type === "image" || layer.id === "layer_product") {
          return (
            <ProductLayer
              key={layer.id}
              layer={layer}
              selected={selected}
              flashing={flashing}
              canvasScale={scale}
              canvasRef={canvasRef}
              softbox={softbox}
              productPreviewUrl={productPreviewUrl}
            />
          )
        }

        if (layer.type === "text") {
          return (
            <TextLayerView
              key={layer.id}
              layer={layer}
              selected={selected}
              flashing={flashing}
              canvasScale={scale}
              canvasRef={canvasRef}
              subtitle={
                layer.id === "layer_title" ? "Крем для рук · 75 мл" : undefined
              }
            />
          )
        }

        if (layer.type === "shape" && layer.chip) {
          return (
            <ChipLayerView
              key={layer.id}
              layer={
                layer as CanvasLayer & {
                  chip: NonNullable<CanvasLayer["chip"]>
                }
              }
              selected={selected}
              flashing={flashing}
              canvasScale={scale}
              canvasRef={canvasRef}
            />
          )
        }

        return null
      })}

      {showBusyOverlay ? (
        <div className="pointer-events-none absolute inset-0 z-[200] flex flex-col items-center justify-center gap-3 bg-loft/55 backdrop-blur-[2px]">
          <Skeleton className="h-[38%] w-[46%] rounded-[18%]" />
          <p className="text-xs text-muted-foreground">
            {busyKind === "generating"
              ? "Генерация карточки…"
              : busyKind === "removing-bg"
                ? "Вырезаем фон…"
                : "Загрузка изображения…"}
          </p>
        </div>
      ) : null}

      <span className="pointer-events-none absolute bottom-2 right-3 z-[130] font-mono text-[10px] text-white/25">
        {CANVAS_WIDTH}×{CANVAS_HEIGHT}
      </span>
    </div>
  )
}

export { EditorCanvas, softboxBackground }
