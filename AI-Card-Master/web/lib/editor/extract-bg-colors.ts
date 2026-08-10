/** Dominant-color extraction from card background images (Canvas getImageData). */

export type Rgb = { r: number; g: number; b: number }

export type ChipAutoAppearance = {
  bgColor: string
  textColor: string
}

export const DEFAULT_CHIP_AUTO_APPEARANCE: ChipAutoAppearance = {
  bgColor: "rgba(15,17,21,0.55)",
  textColor: "#FFFFFF",
}

const SAMPLE_SIZE = 64
const BUCKET_STEP = 24

function clampByte(n: number): number {
  return Math.min(255, Math.max(0, Math.round(n)))
}

export function rgbToHex({ r, g, b }: Rgb): string {
  return (
    "#" +
    [r, g, b]
      .map((c) => clampByte(c).toString(16).padStart(2, "0"))
      .join("")
      .toUpperCase()
  )
}

export function parseCssColor(input: string): Rgb | null {
  const raw = input.trim()
  if (raw.startsWith("#")) {
    const hex = raw.slice(1)
    if (hex.length === 3) {
      return {
        r: parseInt(hex[0]! + hex[0]!, 16),
        g: parseInt(hex[1]! + hex[1]!, 16),
        b: parseInt(hex[2]! + hex[2]!, 16),
      }
    }
    if (hex.length >= 6) {
      return {
        r: parseInt(hex.slice(0, 2), 16),
        g: parseInt(hex.slice(2, 4), 16),
        b: parseInt(hex.slice(4, 6), 16),
      }
    }
    return null
  }
  const rgba = raw.match(
    /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*[\d.]+)?\s*\)$/i
  )
  if (!rgba) return null
  return {
    r: clampByte(Number(rgba[1])),
    g: clampByte(Number(rgba[2])),
    b: clampByte(Number(rgba[3])),
  }
}

/** Relative luminance (0–1), sRGB. */
export function relativeLuminance({ r, g, b }: Rgb): number {
  const toLinear = (c: number) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b)
}

/** White or near-black text for readable contrast on `bg`. */
export function contrastTextForBg(bg: string): string {
  const rgb = parseCssColor(bg)
  if (!rgb) return "#FFFFFF"
  return relativeLuminance(rgb) > 0.45 ? "#0F1115" : "#FFFFFF"
}

function saturation({ r, g, b }: Rgb): number {
  const max = Math.max(r, g, b) / 255
  const min = Math.min(r, g, b) / 255
  if (max === min) return 0
  const l = (max + min) / 2
  const d = max - min
  return l > 0.5 ? d / (2 - max - min) : d / (max + min)
}

function bucketKey({ r, g, b }: Rgb): string {
  const q = (c: number) => Math.round(c / BUCKET_STEP) * BUCKET_STEP
  return `${q(r)},${q(g)},${q(b)}`
}

function loadHtmlImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = "anonymous"
    img.decoding = "async"
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error(`Failed to load image: ${url}`))
    img.src = url
  })
}

/**
 * Extract up to `count` dominant hex colors from an image URL.
 * Downsamples via canvas, then frequency-buckets quantized RGB.
 */
export async function extractDominantColors(
  imageUrl: string,
  count = 5
): Promise<string[]> {
  if (!imageUrl || typeof document === "undefined") return []

  const img = await loadHtmlImage(imageUrl)
  const canvas = document.createElement("canvas")
  canvas.width = SAMPLE_SIZE
  canvas.height = SAMPLE_SIZE
  const ctx = canvas.getContext("2d", { willReadFrequently: true })
  if (!ctx) return []

  ctx.drawImage(img, 0, 0, SAMPLE_SIZE, SAMPLE_SIZE)
  let data: ImageData
  try {
    data = ctx.getImageData(0, 0, SAMPLE_SIZE, SAMPLE_SIZE)
  } catch {
    // Tainted canvas (CORS) — caller should keep default presets.
    return []
  }

  const buckets = new Map<string, { rgb: Rgb; weight: number }>()
  const { data: pixels } = data
  for (let i = 0; i < pixels.length; i += 4) {
    const a = pixels[i + 3] ?? 0
    if (a < 200) continue
    const rgb: Rgb = {
      r: pixels[i] ?? 0,
      g: pixels[i + 1] ?? 0,
      b: pixels[i + 2] ?? 0,
    }
    const key = bucketKey(rgb)
    const prev = buckets.get(key)
    if (prev) {
      const w = prev.weight + 1
      prev.rgb = {
        r: (prev.rgb.r * prev.weight + rgb.r) / w,
        g: (prev.rgb.g * prev.weight + rgb.g) / w,
        b: (prev.rgb.b * prev.weight + rgb.b) / w,
      }
      prev.weight = w
    } else {
      buckets.set(key, { rgb, weight: 1 })
    }
  }

  const ranked = [...buckets.values()].sort((a, b) => b.weight - a.weight)
  const picked: string[] = []
  const seen = new Set<string>()

  for (const entry of ranked) {
    const hex = rgbToHex(entry.rgb)
    if (seen.has(hex)) continue
    // Skip near-duplicates (same bucket family already covered by hex).
    const tooClose = picked.some((other) => {
      const a = parseCssColor(other)
      const b = parseCssColor(hex)
      if (!a || !b) return false
      const dr = a.r - b.r
      const dg = a.g - b.g
      const db = a.b - b.b
      return dr * dr + dg * dg + db * db < 40 * 40
    })
    if (tooClose) continue
    seen.add(hex)
    picked.push(hex)
    if (picked.length >= count) break
  }

  return picked
}

/**
 * Build a glass-style chip fill from palette: darken an accent tone and
 * apply semi-transparency so the badge sits on the product photo cleanly.
 */
export function pickHarmoniousBadgeColors(
  palette: readonly string[]
): ChipAutoAppearance {
  if (palette.length === 0) return { ...DEFAULT_CHIP_AUTO_APPEARANCE }

  const parsed = palette
    .map((hex) => {
      const rgb = parseCssColor(hex)
      if (!rgb) return null
      return { hex, rgb, sat: saturation(rgb), lum: relativeLuminance(rgb) }
    })
    .filter((x): x is NonNullable<typeof x> => x !== null)

  if (parsed.length === 0) return { ...DEFAULT_CHIP_AUTO_APPEARANCE }

  // Prefer saturated mid tones; fall back to darkest color.
  const accentScore = (c: (typeof parsed)[number]) =>
    c.sat * 0.7 + (1 - Math.abs(c.lum - 0.4)) * 0.3
  const accent =
    [...parsed]
      .filter((c) => c.lum > 0.08 && c.lum < 0.85)
      .sort((a, b) => accentScore(b) - accentScore(a))[0] ??
    [...parsed].sort((a, b) => a.lum - b.lum)[0]!

  // Dark translucent plate tinted by the accent.
  const plate: Rgb = {
    r: accent.rgb.r * 0.22,
    g: accent.rgb.g * 0.22,
    b: accent.rgb.b * 0.22,
  }
  const bgColor = `rgba(${clampByte(plate.r)},${clampByte(plate.g)},${clampByte(plate.b)},0.55)`
  return {
    bgColor,
    textColor: contrastTextForBg(bgColor),
  }
}
