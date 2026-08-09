/** Simple SVG icons for Fabric chip badges (no Lucide DOM dependency). */

const ICON_PATHS: Record<string, string> = {
  icon_check:
    "M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  icon_drop:
    "M12 2.69l5.66 5.66a8 8 0 11-11.31 0L12 2.69z",
  icon_leaf:
    "M11 20A7 7 0 019.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10z M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12",
  icon_shield:
    "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  icon_star:
    "M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z",
  icon_spark:
    "M12 3l1.5 5.5L19 10l-5.5 1.5L12 17l-1.5-5.5L5 10l5.5-1.5L12 3z M19 15l.75 2.25L22 18l-2.25.75L19 21l-.75-2.25L16 18l2.25-.75L19 15z",
  icon_box:
    "M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z M3.27 6.96L12 12.01l8.73-5.05 M12 22.08V12",
  icon_flask:
    "M9 3h6M10 9V3m4 6V3M8 14.5A4.5 4.5 0 0012.5 19h0A4.5 4.5 0 0017 14.5V9H8v5.5z",
}

export function chipIconDataUrl(
  iconId: string,
  color: string,
  size = 64
): string {
  const path = ICON_PATHS[iconId] ?? ICON_PATHS.icon_check
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${path}"/></svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

export function chipTextColor(bg: string): string {
  const hex = bg.toLowerCase()
  if (hex === "#ffffff" || hex === "#fff" || hex === "#f59e0b") {
    return "#0d0f12"
  }
  return "#FFFFFF"
}
