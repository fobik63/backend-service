import type { SoftboxSettings } from "@/lib/store/editor-store"

export type StudioLightParams = Omit<SoftboxSettings, "enabled">

/**
 * Client-side mirror of backend `parse_studio_light_instruction`
 * (RU/EN phrases → softbox knobs).
 */
export function parseStudioLightInstruction(
  instruction: string
): StudioLightParams {
  const text = instruction.trim().toLowerCase()
  if (!text) {
    throw new Error("instruction must not be empty.")
  }

  const normalized = text
    .replaceAll("ё", "е")
    .replace(/[,.;]/g, " ")
    .replace(/\s+/g, " ")
    .trim()

  return {
    lightAngle: parseAngle(normalized),
    lightElevation: parseElevation(normalized),
    colorTempK: parseColorTemp(normalized),
    intensity: Math.round(parseIntensity(normalized) * 100),
    softboxDiffusion: Math.round(parseDiffusion(normalized) * 100),
  }
}

function parseAngle(text: string): number {
  const match = text.match(/(?:angle|азимут|угол)\s*[:=]?\s*(\d{1,3})/)
  if (match) return Number.parseInt(match[1]!, 10) % 360

  const left = /\b(left|слева|левы\w*|налево)\b/.test(text)
  const right = /\b(right|справа|правы\w*|направо)\b/.test(text)
  const front = /\b(front|frontal|спереди|фронтальн\w*)\b/.test(text)
  const back = /\b(back|behind|сзади|с тыла)\b/.test(text)

  if (left && !right) return front ? 135 : 180
  if (right && !left) return front ? 45 : 0
  if (front && !back) return 90
  if (back && !front) return 270
  if (/\b(top|overhead|сверху|над|потолок)\b/.test(text)) return 90
  return 45
}

function parseElevation(text: string): number {
  const match = text.match(/(?:elevation|высота|elev)\s*[:=]?\s*(\d{1,2})/)
  if (match) {
    return Math.max(10, Math.min(90, Number.parseInt(match[1]!, 10)))
  }

  if (/\b(overhead|zenith|прямо сверху|над головой|потолок)\b/.test(text)) {
    return 85
  }
  if (/\b(сверху|top|high|высоко|верхн\w*)\b/.test(text)) return 65
  if (/\b(снизу|bottom|low|низк\w*|нижн\w*)\b/.test(text)) return 18
  if (/\b(side|боков\w*|сбоку|lateral)\b/.test(text)) return 35
  return 55
}

function parseColorTemp(text: string): number {
  const match = text.match(/(\d{4})\s*k\b/)
  if (match) {
    return Math.max(2700, Math.min(6500, Number.parseInt(match[1]!, 10)))
  }

  if (/\b(warm|тепл\w*|золотист\w*|sunset|golden)\b/.test(text)) return 3200
  if (/\b(cool|холодн\w*|син\w*|blueish|bluish|daylight)\b/.test(text)) {
    return 6500
  }
  if (/\b(нейтральн\w*|neutral|white)\b/.test(text)) return 5500
  return 5500
}

function parseIntensity(text: string): number {
  const match = text.match(/(?:intensity|яркост\w*|сила)\s*[:=]?\s*(\d+(?:\.\d+)?)/)
  if (match) {
    return Math.max(0, Math.min(2, Number.parseFloat(match[1]!)))
  }

  if (/\b(very bright|очень яркий|мощн\w*)\b/.test(text)) return 1.7
  if (/\b(bright|яркий|яркая|strong|сильн\w*)\b/.test(text)) return 1.35
  if (/\b(dim|слабый|слабая|тускл\w*|мягко приглуш\w*)\b/.test(text)) {
    return 0.55
  }
  return 1
}

function parseDiffusion(text: string): number {
  const match = text.match(
    /(?:diffusion|softbox_diffusion|диффуз\w*)\s*[:=]?\s*(\d+(?:\.\d+)?)/
  )
  if (match) {
    let value = Number.parseFloat(match[1]!)
    if (value > 1) value /= 100
    return Math.max(0, Math.min(1, value))
  }

  if (/\b(ultra soft|очень мягк\w*|максимально мягк\w*)\b/.test(text)) {
    return 0.95
  }
  if (/\b(soft|мягк\w*|diffused|рассеянн\w*)\b/.test(text)) return 0.85
  if (/\b(hard|жестк\w*|жёстк\w*|sharp|резк\w*|spot)\b/.test(text)) return 0.15
  return 0.65
}
