/**
 * Instant badge style presets for marketplace chips (WB/Ozon).
 * Applied in-place onto the selected FeatureChipDraft + Fabric plate.
 */

import type { FeatureChipDraft, FeatureChipVariant } from "@/types/canvas"

export type BadgeStylePresetId =
  | "glassmorphism"
  | "solidAccent"
  | "darkMinimal"
  | "bordered"

export type BadgeStylePreset = {
  id: BadgeStylePresetId
  label: string
  variant: FeatureChipVariant
  bgColor: string
  textColor: string
  blur: number
  borderRadius: number
  /** Plate stroke (glass rim / bordered outline). */
  strokeColor: string
  strokeWidth: number
  /** Optional linear gradient stops for dark minimal. */
  gradient?: readonly [string, string]
}

export const BADGE_STYLE_PRESETS: readonly BadgeStylePreset[] = [
  {
    id: "glassmorphism",
    label: "Glassmorphism",
    variant: "glass",
    bgColor: "rgba(255,255,255,0.16)",
    textColor: "#FFFFFF",
    blur: 16,
    borderRadius: 16,
    strokeColor: "rgba(255,255,255,0.45)",
    strokeWidth: 1.25,
  },
  {
    id: "solidAccent",
    label: "Solid Accent",
    variant: "solid",
    bgColor: "#059669",
    textColor: "#FFFFFF",
    blur: 0,
    borderRadius: 12,
    strokeColor: "rgba(0,0,0,0)",
    strokeWidth: 0,
  },
  {
    id: "darkMinimal",
    label: "Dark Minimal",
    variant: "dark",
    bgColor: "#2A2D35",
    textColor: "#F4F4F5",
    blur: 0,
    borderRadius: 12,
    strokeColor: "rgba(255,255,255,0.08)",
    strokeWidth: 1,
    gradient: ["#3A3E48", "#1A1C22"] as const,
  },
  {
    id: "bordered",
    label: "Bordered",
    variant: "bordered",
    bgColor: "rgba(0,0,0,0)",
    textColor: "#FFFFFF",
    blur: 0,
    borderRadius: 14,
    strokeColor: "#34D399",
    strokeWidth: 3,
  },
] as const

export function badgeStylePresetById(
  id: BadgeStylePresetId
): BadgeStylePreset | undefined {
  return BADGE_STYLE_PRESETS.find((p) => p.id === id)
}

export function badgeStylePresetByVariant(
  variant: FeatureChipVariant | undefined
): BadgeStylePreset {
  const hit = BADGE_STYLE_PRESETS.find((p) => p.variant === variant)
  return hit ?? BADGE_STYLE_PRESETS[0]!
}

/** Merge a style preset into an existing chip (keeps label / icon / subtitle). */
export function applyBadgeStylePreset(
  chip: FeatureChipDraft,
  presetId: BadgeStylePresetId,
  opts?: { accentColor?: string }
): FeatureChipDraft {
  const preset = badgeStylePresetById(presetId)
  if (!preset) return chip

  const accent = opts?.accentColor
  const isSolid = preset.id === "solidAccent"
  const isBordered = preset.id === "bordered"

  return {
    ...chip,
    variant: preset.variant,
    bgColor:
      isSolid && accent
        ? accent
        : isBordered
          ? "rgba(0,0,0,0)"
          : preset.bgColor,
    textColor: preset.textColor,
    blur: preset.blur,
    borderRadius: preset.borderRadius,
    strokeColor:
      isBordered && accent ? accent : preset.strokeColor,
    strokeWidth: preset.strokeWidth,
  }
}

export function resolveChipStrokeColor(chip: FeatureChipDraft): string {
  if (chip.strokeColor) return chip.strokeColor
  return badgeStylePresetByVariant(chip.variant).strokeColor
}

export function resolveChipStrokeWidth(chip: FeatureChipDraft): number {
  if (chip.strokeWidth != null) return chip.strokeWidth
  return badgeStylePresetByVariant(chip.variant).strokeWidth
}

export function resolveChipGradient(
  chip: FeatureChipDraft
): readonly [string, string] | undefined {
  if (chip.variant !== "dark") return undefined
  return badgeStylePresetByVariant("dark").gradient
}
