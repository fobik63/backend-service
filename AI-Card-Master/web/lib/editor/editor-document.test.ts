import { describe, expect, it } from "vitest"

import {
  createEditorDocument,
  editorDocumentToState,
  layersToCanvasState,
} from "@/lib/editor/editor-document"
import { useEditorStore } from "@/lib/store/editor-store"

describe("editor document adapters", () => {
  it("round-trips every page without losing text or chip metadata", () => {
    const state = useEditorStore.getState()
    const document = createEditorDocument({
      pages: state.pages,
      activePageIndex: state.activePageIndex,
      productPreviewUrl: state.productPreviewUrl,
      softbox: state.softbox,
    })

    const restored = editorDocumentToState(document)

    expect(restored.pages).toHaveLength(state.pages.length)
    expect(
      restored.pages[0]?.find((layer) => layer.id === "layer_title")?.text
    ).toBe(
      state.pages[0]?.find((layer) => layer.id === "layer_title")?.text
    )
    expect(
      restored.pages[0]?.find((layer) => layer.id === "layer_badge_eco")?.chip
    ).toEqual(
      state.pages[0]?.find((layer) => layer.id === "layer_badge_eco")?.chip
    )
    expect(restored.softbox).toEqual(state.softbox)
    expect(restored.productPreviewUrl).toBe(state.productPreviewUrl)
  })

  it("maps percent coordinates to the 1080x1440 server canvas", () => {
    const state = useEditorStore.getState()
    const canvas = layersToCanvasState(
      state.layers,
      state.productPreviewUrl
    )
    const product = canvas.layers?.find(
      (layer) => layer.layer_type === "image"
    )

    expect(canvas.width).toBe(1080)
    expect(canvas.height).toBe(1440)
    expect(product?.x).toBeCloseTo(341.928, 2)
    expect(product?.y).toBeCloseTo(158.4, 2)
  })
})
