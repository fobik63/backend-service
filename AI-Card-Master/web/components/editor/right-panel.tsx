"use client"

import { Lamp, Lock, Unlock } from "lucide-react"
import type { ReactNode } from "react"

import { StudioLightControl } from "@/components/editor/studio-light-control"
import { TextLayerControl } from "@/components/editor/text-layer-control"
import { Input } from "@/components/ui/input"
import { Slider } from "@/components/ui/slider"
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"

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

function SoftboxPanel() {
  const softbox = useEditorStore((s) => s.softbox)
  const setSoftbox = useEditorStore((s) => s.setSoftbox)

  return (
    <section className="space-y-4 border-t border-white/8 pt-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Lamp className="size-4 text-amber" aria-hidden />
          <h3 className="font-heading text-sm font-semibold tracking-tight">
            Студийный свет
          </h3>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={softbox.enabled}
          onClick={() => setSoftbox({ enabled: !softbox.enabled })}
          className={cn(
            "relative h-5 w-9 rounded-full transition-colors",
            softbox.enabled ? "bg-emerald" : "bg-white/15"
          )}
        >
          <span
            className={cn(
              "absolute top-0.5 left-0.5 size-4 rounded-full bg-white transition-transform",
              softbox.enabled && "translate-x-4"
            )}
          />
          <span className="sr-only">Софтбокс</span>
        </button>
      </div>
      <p className="text-[11px] text-muted-foreground">
        Софтбокс — угол, высота, температура и диффузия
      </p>

      <div
        className={cn(
          "transition-opacity",
          !softbox.enabled && "opacity-40"
        )}
      >
        <StudioLightControl />
      </div>
    </section>
  )
}

function ElementSettings() {
  const layers = useEditorStore((s) => s.layers)
  const selectedLayerId = useEditorStore((s) => s.selectedLayerId)
  const updateLayer = useEditorStore((s) => s.updateLayer)

  const layer = layers.find((l) => l.id === selectedLayerId)

  if (!layer) {
    return (
      <div className="rounded-lg border border-dashed border-white/12 bg-white/[0.02] px-3 py-6 text-center text-xs text-muted-foreground">
        Выберите элемент на холсте или в списке слоёв
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <FieldLabel htmlFor="layer-name">Имя слоя</FieldLabel>
        <Input
          id="layer-name"
          value={layer.name}
          disabled={layer.locked}
          onChange={(e) => updateLayer(layer.id, { name: e.target.value })}
        />
      </div>

      <div className="flex items-center gap-2">
        <span className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] text-muted-foreground capitalize">
          {layer.type}
        </span>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
          onClick={() => updateLayer(layer.id, { locked: !layer.locked })}
        >
          {layer.locked ? (
            <Lock className="size-3" aria-hidden />
          ) : (
            <Unlock className="size-3" aria-hidden />
          )}
          {layer.locked ? "Заблокирован" : "Разблокирован"}
        </button>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <FieldLabel>Прозрачность</FieldLabel>
          <span className="font-mono text-[11px] text-foreground/80">
            {Math.round(layer.opacity * 100)}%
          </span>
        </div>
        <Slider
          min={0}
          max={100}
          disabled={layer.locked}
          value={[Math.round(layer.opacity * 100)]}
          onValueChange={(v) => {
            const next = Array.isArray(v) ? v[0] : v
            if (typeof next === "number") {
              updateLayer(layer.id, { opacity: next / 100 })
            }
          }}
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1.5">
          <FieldLabel htmlFor="layer-z">Z-index</FieldLabel>
          <Input
            id="layer-z"
            type="number"
            value={layer.zIndex}
            disabled={layer.locked}
            onChange={(e) =>
              updateLayer(layer.id, {
                zIndex: Number.parseInt(e.target.value, 10) || 0,
              })
            }
          />
        </div>
        <div className="space-y-1.5">
          <FieldLabel>Видимость</FieldLabel>
          <button
            type="button"
            disabled={layer.locked}
            onClick={() =>
              updateLayer(layer.id, { visible: !layer.visible })
            }
            className={cn(
              "flex h-8 w-full items-center justify-center rounded-lg border text-xs transition-colors disabled:opacity-50",
              layer.visible
                ? "border-emerald/35 bg-emerald/15 text-emerald"
                : "border-white/10 bg-white/[0.04] text-muted-foreground"
            )}
          >
            {layer.visible ? "Видим" : "Скрыт"}
          </button>
        </div>
      </div>
    </div>
  )
}

function EditorRightPanel() {
  return (
    <aside
      className="flex h-full w-[320px] shrink-0 flex-col border-l border-white/8 bg-loft-surface/90"
      aria-label="Настройки элемента"
    >
      <div className="border-b border-white/8 px-4 py-3">
        <h2 className="font-heading text-sm font-semibold tracking-tight">
          Свойства
        </h2>
        <p className="text-[11px] text-muted-foreground">
          Элемент, типографика и студийный софтбокс
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
        <section className="space-y-3">
          <h3 className="font-heading text-sm font-semibold tracking-tight">
            Выбранный элемент
          </h3>
          <ElementSettings />
        </section>

        <section className="space-y-3 border-t border-white/8 pt-4">
          <TextLayerControl />
        </section>

        <SoftboxPanel />
      </div>
    </aside>
  )
}

export { EditorRightPanel }
