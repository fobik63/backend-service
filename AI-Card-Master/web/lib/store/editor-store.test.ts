import { beforeEach, describe, expect, it } from "vitest"

import { useEditorStore } from "@/lib/store/editor-store"

describe("editor history", () => {
  beforeEach(() => {
    useEditorStore.getState().reset()
  })

  it("undoes and redoes a discrete layer update", () => {
    const initial = useEditorStore
      .getState()
      .layers.find((layer) => layer.id === "p0_product")
    expect(initial).toBeDefined()

    useEditorStore.getState().updateLayer("p0_product", { x: 42 })
    expect(
      useEditorStore
        .getState()
        .layers.find((layer) => layer.id === "p0_product")?.x
    ).toBe(42)
    expect(useEditorStore.getState().canUndo).toBe(true)

    useEditorStore.getState().undo()
    expect(
      useEditorStore
        .getState()
        .layers.find((layer) => layer.id === "p0_product")?.x
    ).toBe(initial?.x)

    useEditorStore.getState().redo()
    expect(
      useEditorStore
        .getState()
        .layers.find((layer) => layer.id === "p0_product")?.x
    ).toBe(42)
  })

  it("coalesces pointer-move updates into one history entry", () => {
    const store = useEditorStore.getState()
    const initialX = store.layers.find(
      (layer) => layer.id === "p0_product"
    )?.x

    store.beginHistoryTransaction()
    useEditorStore.getState().updateLayer("p0_product", { x: 35 })
    useEditorStore.getState().updateLayer("p0_product", { x: 36 })
    useEditorStore.getState().updateLayer("p0_product", { x: 37 })
    useEditorStore.getState().commitHistoryTransaction()

    expect(useEditorStore.getState().history.past).toHaveLength(1)
    useEditorStore.getState().undo()
    expect(
      useEditorStore
        .getState()
        .layers.find((layer) => layer.id === "p0_product")?.x
    ).toBe(initialX)
  })

  it("clears history when another project is loaded", () => {
    useEditorStore.getState().updateLayer("p0_product", { x: 40 })
    const current = useEditorStore.getState()

    useEditorStore.getState().loadProject({
      projectId: "another-project",
      pages: current.pages,
      activePageIndex: 0,
      softbox: current.softbox,
      productPreviewUrl: current.productPreviewUrl,
      backgroundPreviewUrl: current.backgroundPreviewUrl,
      packSize: current.packSize,
    })

    expect(useEditorStore.getState().projectId).toBe("another-project")
    expect(useEditorStore.getState().canUndo).toBe(false)
    expect(useEditorStore.getState().history.past).toHaveLength(0)
  })

  it("applies generation result as a single undo step", () => {
    const before = useEditorStore.getState()
    const nextLayers = before.layers.map((layer) =>
      layer.id === "p0_title" ? { ...layer, text: "Generated" } : layer
    )

    useEditorStore.getState().applyGenerationResult({
      layers: nextLayers,
      productPreviewUrl: "/projects/cream-sage-mist-product.png",
      backgroundPreviewUrl: "/projects/cream-sage-mist.png",
    })

    expect(useEditorStore.getState().history.past).toHaveLength(1)
    expect(
      useEditorStore.getState().layers.find((l) => l.id === "p0_title")?.text
    ).toBe("Generated")
    expect(useEditorStore.getState().backgroundPreviewUrl).toBe(
      "/projects/cream-sage-mist.png"
    )

    useEditorStore.getState().undo()
    expect(
      useEditorStore.getState().layers.find((l) => l.id === "p0_title")?.text
    ).toBe(before.layers.find((l) => l.id === "p0_title")?.text)
    expect(useEditorStore.getState().backgroundPreviewUrl).toBe(
      before.backgroundPreviewUrl
    )
  })

  it("applies parsed product cutout and meta fields", () => {
    useEditorStore.getState().applyParsedProduct({
      images: ["/cutout-a.png", "/cutout-b.png"],
      title: "Test Cream",
      category: "Кремы",
      brand: "BrandX",
      description: "Source description",
    })

    const state = useEditorStore.getState()
    expect(state.productPreviewUrl).toBe("/cutout-a.png")
    expect(state.importGalleryUrls).toEqual([
      "/cutout-a.png",
      "/cutout-b.png",
    ])
    expect(state.productMeta).toEqual({
      title: "Test Cream",
      category: "Кремы",
      brand: "BrandX",
      description: "Source description",
    })
    // Canvas headline prefers brand over full product title.
    expect(
      state.layers.find((layer) => layer.id === "p0_title")?.text
    ).toBe("BrandX")
  })

  it("updates canvas title from parse even without images", () => {
    useEditorStore.getState().applyParsedProduct({
      images: [],
      title: "Long marketplace title",
      category: "Уход",
      brand: "Aura",
      description: "Hydrating cream for dry skin",
    })

    const state = useEditorStore.getState()
    expect(state.productMeta.title).toBe("Long marketplace title")
    expect(state.productMeta.description).toBe(
      "Hydrating cream for dry skin"
    )
    expect(
      state.layers.find((layer) => layer.id === "p0_title")?.text
    ).toBe("Aura")
    expect(state.canUndo).toBe(true)
  })

  it("falls back to product title when brand is empty", () => {
    useEditorStore.getState().applyParsedProduct({
      images: [],
      title: "Sage Mist Cream",
      category: "Кремы",
      brand: "",
      description: "",
    })

    expect(
      useEditorStore
        .getState()
        .layers.find((layer) => layer.id === "p0_title")?.text
    ).toBe("Sage Mist Cream")
  })

  it("blank reset clears layers and history", () => {
    useEditorStore.getState().updateLayer("p0_product", { x: 40 })
    expect(useEditorStore.getState().canUndo).toBe(true)
    expect(useEditorStore.getState().layers.length).toBeGreaterThan(0)

    useEditorStore.getState().reset({ blank: true })

    const state = useEditorStore.getState()
    expect(state.layers).toEqual([])
    expect(state.pages.every((page) => page.length === 0)).toBe(true)
    expect(state.selectedLayerId).toBeNull()
    expect(state.productPreviewUrl).toBeNull()
    expect(state.backgroundPreviewUrl).toBeNull()
    expect(state.history.past).toHaveLength(0)
    expect(state.history.future).toHaveLength(0)
    expect(state.canUndo).toBe(false)
    expect(state.canRedo).toBe(false)
  })
})
