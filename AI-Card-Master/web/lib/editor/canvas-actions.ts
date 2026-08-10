import {
  BADGE_PRESETS,
  TEXT_PRESETS,
  nextBadgePosition,
} from "@/lib/constants/mock-editor"
import { DEFAULT_CHIP_AUTO_APPEARANCE } from "@/lib/editor/extract-bg-colors"
import {
  useEditorStore,
  type EditorProductMeta,
} from "@/lib/store/editor-store"
import {
  DEFAULT_TEXT_STYLE,
  type CanvasLayer,
  type FeatureChipVariant,
} from "@/types/canvas"

const AI_PRODUCT_CONTEXT_MARKER = "--- Контекст товара ---"

/** Glass badge defaults — uses palette from current background when available. */
function glassBadgeAppearance() {
  return (
    useEditorStore.getState().chipAutoAppearance ?? DEFAULT_CHIP_AUTO_APPEARANCE
  )
}

/** Build an AI-infographic prompt from marketplace product fields. */
export function buildProductInfographicPrompt(
  meta: Pick<EditorProductMeta, "title" | "brand" | "category" | "description">
): string {
  const title = meta.title.trim()
  const brand = meta.brand.trim()
  const category = meta.category.trim()
  const description = meta.description.trim()
  if (!title && !brand && !description) return ""

  const lines: string[] = [
    "Создай инфографику для карточки маркетплейса.",
  ]
  if (brand) lines.push(`Бренд: ${brand}`)
  if (title) lines.push(`Товар: ${title}`)
  if (category) lines.push(`Категория: ${category}`)
  if (description) {
    lines.push("", "Описание и ключевые свойства:", description)
  }
  return lines.join("\n").trim()
}

/** Seed PromptBar with product context after a successful parse. */
export function seedAiPromptFromProduct(
  meta: Pick<EditorProductMeta, "title" | "brand" | "category" | "description">
): void {
  const prompt = buildProductInfographicPrompt(meta)
  if (!prompt || typeof window === "undefined") return
  window.dispatchEvent(
    new CustomEvent("editor:seed-prompt", { detail: prompt }),
  )
}

/**
 * Ensure generate requests always carry product description as AI context,
 * even if the user shortened the visible prompt after seeding.
 */
export function enrichPromptWithProductContext(
  prompt: string,
  meta: Pick<EditorProductMeta, "title" | "brand" | "category" | "description">
): string {
  const trimmed = prompt.trim()
  const description = meta.description.trim()
  if (!description) return trimmed
  if (trimmed.includes(description)) return trimmed

  const brand = meta.brand.trim()
  const title = meta.title.trim()
  const category = meta.category.trim()
  const contextLines = [
    AI_PRODUCT_CONTEXT_MARKER,
    brand ? `Бренд: ${brand}` : null,
    title ? `Товар: ${title}` : null,
    category ? `Категория: ${category}` : null,
    "Описание:",
    description,
  ].filter((line): line is string => Boolean(line))

  if (!trimmed) return contextLines.join("\n")
  return `${trimmed}\n\n${contextLines.join("\n")}`
}

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
  variant?: FeatureChipVariant
  subtitle?: string
  textColor?: string
  blur?: number
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
  const variant = opts.variant ?? "solid"
  const blur = opts.blur ?? (variant === "glass" ? 12 : 0)

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
      borderRadius: opts.borderRadius ?? (variant === "glass" ? 14 : 10),
      iconId: opts.iconId,
      variant,
      subtitle: opts.subtitle,
      textColor: opts.textColor,
      blur,
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
  const isSubtitle = preset.id === "txt_subtitle"
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
    textStyle: {
      ...DEFAULT_TEXT_STYLE,
      ...(isSubtitle
        ? {
            fontSize: 26,
            fontWeight: 500,
            color: "#D4A574",
            shadowEnabled: false,
          }
        : {}),
    },
  })
  return preset.label
}

export function addQuickBadgeById(
  badgeId: (typeof BADGE_PRESETS)[number]["id"]
): { label: string; created: boolean } | null {
  const badge = BADGE_PRESETS.find((b) => b.id === badgeId)
  if (!badge) return null
  const isGlass = badge.variant === "glass"
  const auto = isGlass ? glassBadgeAppearance() : null
  return addBadgeToCanvas({
    label: badge.label,
    bgColor: auto?.bgColor ?? badge.bgColor,
    iconId: badge.iconId,
    variant: badge.variant,
    subtitle: "subtitle" in badge ? badge.subtitle : undefined,
    blur: isGlass ? 12 : 0,
    textColor: isGlass ? auto?.textColor ?? "#FFFFFF" : undefined,
  })
}

export function addCustomBadge(label: string): {
  label: string
  created: boolean
} | null {
  const trimmed = label.trim()
  if (!trimmed) return null
  const auto = glassBadgeAppearance()
  return addBadgeToCanvas({
    label: trimmed,
    bgColor: auto.bgColor,
    iconId: "icon_spark",
    variant: "glass",
    blur: 12,
    textColor: auto.textColor,
    borderRadius: 14,
  })
}

/** Seed AI prompt + push top badge/trigger suggestions onto the canvas. */
export function applyEyeInsightsToProject(opts: {
  generatorPrompt?: string | null
  badgeLabels?: string[]
  description?: string | null
  title?: string | null
}): { badgesCreated: number } {
  const prompt = opts.generatorPrompt?.trim()
  if (prompt) {
    window.dispatchEvent(
      new CustomEvent("editor:seed-prompt", { detail: prompt }),
    )
  }

  const labels = (opts.badgeLabels ?? [])
    .map((label) => label.trim())
    .filter(Boolean)
  const seen = new Set<string>()
  let badgesCreated = 0
  const auto = glassBadgeAppearance()

  for (const label of labels) {
    const key = normalizeBadgeLabel(label)
    if (seen.has(key)) continue
    seen.add(key)
    const result = addBadgeToCanvas({
      label: label.slice(0, 48),
      bgColor: auto.bgColor,
      iconId: "icon_spark",
      variant: "glass",
      blur: 12,
      textColor: auto.textColor,
      borderRadius: 14,
    })
    if (result.created) badgesCreated += 1
    if (seen.size >= 6) break
  }

  const metaPatch: { description?: string; title?: string } = {}
  const description = opts.description?.trim()
  if (description) metaPatch.description = description
  const title = opts.title?.trim()
  if (title) metaPatch.title = title
  if (Object.keys(metaPatch).length > 0) {
    useEditorStore.getState().setProductMeta(metaPatch)
  }

  return { badgesCreated }
}
