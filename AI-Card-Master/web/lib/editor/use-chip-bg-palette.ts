"use client"

import { useEffect, useRef } from "react"

import { FEATURE_CHIP_BG_PRESETS } from "@/lib/constants/mock-editor"
import {
  DEFAULT_CHIP_AUTO_APPEARANCE,
  extractDominantColors,
  pickHarmoniousBadgeColors,
} from "@/lib/editor/extract-bg-colors"
import { useEditorStore } from "@/lib/store/editor-store"

/**
 * When the card background image changes, extract dominant colors and push
 * them into chip sidebar presets + default glass badge appearance.
 */
export function useChipColorsFromBackground() {
  const backgroundPreviewUrl = useEditorStore((s) => s.backgroundPreviewUrl)
  const setChipBgPalette = useEditorStore((s) => s.setChipBgPalette)
  const resetChipBgPalette = useEditorStore((s) => s.resetChipBgPalette)
  const requestIdRef = useRef(0)

  useEffect(() => {
    const requestId = ++requestIdRef.current

    if (!backgroundPreviewUrl) {
      resetChipBgPalette()
      return
    }

    let cancelled = false

    void (async () => {
      try {
        const colors = await extractDominantColors(backgroundPreviewUrl, 5)
        if (cancelled || requestId !== requestIdRef.current) return
        if (colors.length === 0) {
          resetChipBgPalette()
          return
        }
        const presets =
          colors.length >= 5
            ? colors
            : [
                ...colors,
                ...FEATURE_CHIP_BG_PRESETS.filter(
                  (hex) =>
                    !colors.some((c) => c.toLowerCase() === hex.toLowerCase())
                ),
              ].slice(0, 5)
        setChipBgPalette(presets, pickHarmoniousBadgeColors(colors))
      } catch {
        if (cancelled || requestId !== requestIdRef.current) return
        resetChipBgPalette()
      }
    })()

    return () => {
      cancelled = true
    }
  }, [backgroundPreviewUrl, setChipBgPalette, resetChipBgPalette])
}

export { DEFAULT_CHIP_AUTO_APPEARANCE }
