"use client"

import dynamic from "next/dynamic"

/**
 * Editor paint surface — Fabric.js interactive canvas with a 3-layer stack:
 * 1) Background (AI scene / softbox)
 * 2) Product cutout (PNG, drag / scale / rotate)
 * 3) Infographics (text + chips: drag / scale / rotate / click-to-edit / fonts)
 * Export: PNG 1080×1440 via fabric-export.
 *
 * Loaded client-only (`ssr: false`) so Fabric never touches `window`/`canvas`
 * during Next.js server/prerender.
 */
export const EditorCanvas = dynamic(
  () =>
    import("@/components/editor/fabric-canvas").then(
      (mod) => mod.EditorFabricCanvas
    ),
  {
    ssr: false,
    loading: () => (
      <div
        className="size-full min-h-[240px] animate-pulse rounded-md bg-zinc-900/80"
        aria-hidden
      />
    ),
  }
)
