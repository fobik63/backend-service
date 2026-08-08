import {
  BADGE_PRESETS,
  TEXT_PRESETS,
  nextBadgePosition,
} from "@/lib/constants/mock-editor"
import { useEditorStore } from "@/lib/store/editor-store"
import {
  DEFAULT_TEXT_STYLE,
  type CanvasLayer,
} from "@/types/canvas"

function normalizeBadgeLabel(label: string): string {
  return label.trim().toLocaleLowerCase("ru-RU").replace(/\s+/g, " ")
}

function findExistingBadge(label: string): CanvasLayer | undefined {
  const key = normalizeBadgeLabel(label)
  return useEditorStore
    .getState()
    .layers.find(
      (l) => l.chip && normalizeBadgeLabel(l.chip.label) === key
    )
}

export function addBadgeToCanvas(opts: {
  label: string
  bgColor: string
  iconId: string
  borderRadius?: number
}): { label: string; created: boolean } {
  const existing = findExistingBadge(opts.label)
  if (existing) {
    useEditorStore.getState().flashLayer(existing.id)
    return { label: opts.label, created: false }
  }

  const { layers, addLayer } = useEditorStore.getState()
  const chipCount = layers.filter((l) => l.chip).length
  const pos = nextBadgePosition(chipCount)
  const maxZ = layers.reduce((m, l) => Math.max(m, l.zIndex), 0)
  const id = `chip_${Date.now()}`

  addLayer({
    id,
    type: "shape",
    name: `Плашка «${opts.label}»`,
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: maxZ + 1,
    x: pos.x,
    y: pos.y,
    scale: 1,
    rotation: 0,
    chip: {
      label: opts.label,
      bgColor: opts.bgColor,
      borderRadius: opts.borderRadius ?? 10,
      iconId: opts.iconId,
    },
  })

  return { label: opts.label, created: true }
}

export function addTextPresetToCanvas(
  preset: (typeof TEXT_PRESETS)[number]
): string {
  const { layers, addLayer } = useEditorStore.getState()
  const maxZ = layers.reduce((m, l) => Math.max(m, l.zIndex), 0)
  const id = `text_${Date.now()}`
  addLayer({
    id,
    type: "text",
    name: preset.label,
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: maxZ + 1,
    x: 8,
    y: 62 + layers.filter((l) => l.type === "text").length * 6,
    width: 84,
    scale: 1,
    rotation: 0,
    text: preset.sample,
    textStyle: { ...DEFAULT_TEXT_STYLE },
  })
  return preset.label
}

export function addQuickBadgeById(
  badgeId: (typeof BADGE_PRESETS)[number]["id"]
): { label: string; created: boolean } | null {
  const badge = BADGE_PRESETS.find((b) => b.id === badgeId)
  if (!badge) return null
  return addBadgeToCanvas({
    label: badge.label,
    bgColor: badge.bgColor,
    iconId: badge.iconId,
  })
}
