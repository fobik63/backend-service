import type { EditorFontFamily } from "@/types/canvas"
import { EDITOR_FONT_FAMILIES } from "@/types/canvas"

const FONT_CSS_VARS: Record<EditorFontFamily, string> = {
  Inter: "--font-inter",
  Montserrat: "--font-montserrat",
  Unbounded: "--font-unbounded",
  "Cera Pro": "--font-cera-pro",
  Oswald: "--font-oswald",
  "Russo One": "--font-russo-one",
}

/** Legacy picker values still present in saved documents. */
const LEGACY_FONT_CSS_VARS: Record<string, string> = {
  Roboto: "--font-roboto",
  "Space Grotesk": "--font-space-grotesk",
}

const loadedFonts = new Set<string>()

/**
 * Resolve next/font CSS variables to a canvas-safe `font-family` string.
 * Canvas 2D cannot use `var(--…)`; we read the computed token from the document.
 */
export function resolveFabricFontFamily(
  name: EditorFontFamily | string
): string {
  if (typeof document === "undefined") {
    return `"${name}", sans-serif`
  }
  const cssVar =
    FONT_CSS_VARS[name as EditorFontFamily] ?? LEGACY_FONT_CSS_VARS[name]
  if (!cssVar) {
    return `"${name}", sans-serif`
  }
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(cssVar)
    .trim()
  if (raw) {
    return `${raw}, "${name}", sans-serif`
  }
  return `"${name}", sans-serif`
}

export function isEditorFontFamily(value: string): value is EditorFontFamily {
  return (EDITOR_FONT_FAMILIES as readonly string[]).includes(value)
}

/** Map legacy / unknown families onto the marketplace picker set. */
export function normalizeEditorFontFamily(value: string): EditorFontFamily {
  if (isEditorFontFamily(value)) return value
  return "Inter"
}

/**
 * FontFaceObserver-style gate: wait until `document.fonts.load` succeeds
 * for the family (avoids Fabric measuring fallback glyphs → layout jump).
 */
export async function ensureEditorFontLoaded(
  family: EditorFontFamily | string,
  opts?: { sizePx?: number; weight?: number | string }
): Promise<string> {
  const resolved = resolveFabricFontFamily(family)
  const sizePx = opts?.sizePx ?? 48
  const weight = opts?.weight ?? 400
  const cacheKey = `${resolved}::${weight}::${sizePx}`

  if (typeof document === "undefined" || !document.fonts?.load) {
    return resolved
  }

  if (loadedFonts.has(cacheKey)) {
    return resolved
  }

  try {
    await document.fonts.ready
    // Explicit load — next/font faces can stay idle until requested.
    await document.fonts.load(`${weight} ${sizePx}px ${resolved}`)
    // Probe Cyrillic so WB/Ozon copy does not fall back mid-edit.
    await document.fonts.load(`${weight} ${sizePx}px ${resolved}`, "АаБбВв")
    loadedFonts.add(cacheKey)
  } catch {
    // Soft-fail: Fabric will use the CSS fallback stack.
  }

  return resolved
}

/** Preload the marketplace font set used by the editor sidebar picker. */
export async function preloadEditorFonts(
  families: readonly EditorFontFamily[] = EDITOR_FONT_FAMILIES
): Promise<void> {
  if (typeof document === "undefined") return
  await Promise.all(
    families.map((family) =>
      ensureEditorFontLoaded(family, { sizePx: 48, weight: 600 })
    )
  )
}
