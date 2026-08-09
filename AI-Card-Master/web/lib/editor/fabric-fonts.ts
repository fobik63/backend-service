import type { EditorFontFamily } from "@/types/canvas"

const FONT_CSS_VARS: Record<EditorFontFamily, string> = {
  Inter: "--font-inter",
  Montserrat: "--font-montserrat",
  Roboto: "--font-roboto",
  "Space Grotesk": "--font-space-grotesk",
}

/**
 * Resolve next/font CSS variables to a canvas-safe `font-family` string.
 * Canvas 2D cannot use `var(--…)`; we read the computed token from the document.
 */
export function resolveFabricFontFamily(name: EditorFontFamily): string {
  if (typeof document === "undefined") {
    return `"${name}", sans-serif`
  }
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(FONT_CSS_VARS[name])
    .trim()
  if (raw) {
    return `${raw}, "${name}", sans-serif`
  }
  return `"${name}", sans-serif`
}
