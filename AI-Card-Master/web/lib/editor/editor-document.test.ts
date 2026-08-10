import { describe, expect, it } from "vitest"

import {
  createEditorDocument,
  editorDocumentToState,
  layersToCanvasState,
  tryEditorDocumentToState,
  tryParseEditorDocument,
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
      colorGrade: state.colorGrade,
      backgroundColorGrade: state.backgroundColorGrade,
    })

    const restored = editorDocumentToState(document)

    expect(restored.pages).toHaveLength(state.pages.length)
    expect(
      restored.pages[0]?.filter((layer) => layer.type === "background")
    ).toHaveLength(1)
    expect(
      restored.pages[0]?.filter((layer) => layer.type === "image")
    ).toHaveLength(1)
    expect(
      restored.pages[0]?.some(
        (layer) => layer.type === "text" || layer.type === "shape"
      )
    ).toBe(false)
    expect(restored.softbox).toEqual(state.softbox)
    expect(restored.colorGrade).toEqual(state.colorGrade)
    expect(restored.backgroundColorGrade).toEqual(state.backgroundColorGrade)
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

  it("tryParse / tryEditorDocumentToState return null on garbage", () => {
    expect(tryParseEditorDocument({ version: 99 })).toBeNull()
    expect(tryEditorDocumentToState({ broken: true })).toBeNull()
  })
})
