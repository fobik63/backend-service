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
      colorGrade: current.colorGrade,
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
      layer.id === "p0_product" ? { ...layer, scale: 1.25 } : layer
    )

    useEditorStore.getState().applyGenerationResult({
      layers: nextLayers,
      productPreviewUrl: "/projects/cream-sage-mist-product.png",
      backgroundPreviewUrl: "/projects/cream-sage-mist.png",
    })

    expect(useEditorStore.getState().history.past).toHaveLength(1)
    expect(
      useEditorStore.getState().layers.find((l) => l.id === "p0_product")?.scale
    ).toBe(1.25)
    expect(useEditorStore.getState().backgroundPreviewUrl).toBe(
      "/projects/cream-sage-mist.png"
    )

    useEditorStore.getState().undo()
    expect(
      useEditorStore.getState().layers.find((l) => l.id === "p0_product")?.scale
    ).toBe(before.layers.find((l) => l.id === "p0_product")?.scale)
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
    // Clean templates have no default title text — meta only until user adds one.
    expect(
      state.layers.some((layer) => layer.type === "text" || layer.type === "shape")
    ).toBe(false)
  })

  it("updates product meta from parse even without images", () => {
    useEditorStore.getState().applyParsedProduct({
      images: [],
      title: "Long marketplace title",
      category: "Уход",
      brand: "Aura",
      description: "Hydrating cream for dry skin",
    })

    const state = useEditorStore.getState()
    expect(state.productMeta.title).toBe("Long marketplace title")
    expect(state.productMeta.brand).toBe("Aura")
    expect(state.productMeta.description).toBe(
      "Hydrating cream for dry skin"
    )
    // No title layer on clean pack → meta-only update, no history push.
    expect(state.canUndo).toBe(false)
  })

  it("stores product title in meta when brand is empty", () => {
    useEditorStore.getState().applyParsedProduct({
      images: [],
      title: "Sage Mist Cream",
      category: "Кремы",
      brand: "",
      description: "",
    })

    expect(useEditorStore.getState().productMeta.title).toBe("Sage Mist Cream")
    expect(useEditorStore.getState().productMeta.brand).toBe("")
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

  it("reorders layers from top→bottom list and keeps background at zIndex 0", () => {
    useEditorStore.getState().addLayer({
      id: "p0_extra_text",
      type: "text",
      name: "Текст",
      visible: true,
      locked: false,
      opacity: 1,
      zIndex: 2,
      x: 10,
      y: 10,
      width: 40,
      scale: 1,
      rotation: 0,
      text: "Sample",
    })

    const before = useEditorStore.getState().layers
    const bg = before.find((l) => l.type === "background")
    const interactive = before
      .filter((l) => l.type !== "background")
      .sort((a, b) => b.zIndex - a.zIndex)
    expect(bg).toBeDefined()
    expect(interactive.length).toBeGreaterThan(1)

    // Move former top layer to the bottom of the interactive stack.
    const reordered = [
      ...interactive.slice(1).map((l) => l.id),
      interactive[0]!.id,
      bg!.id,
    ]
    useEditorStore.getState().reorderLayers(reordered)

    const after = useEditorStore.getState().layers
    const bgAfter = after.find((l) => l.type === "background")
    expect(bgAfter?.zIndex).toBe(0)
    expect(bgAfter?.locked).toBe(true)

    const topId = interactive[1]?.id ?? interactive[0]!.id
    const bottomId = interactive[0]!.id
    const topZ = after.find((l) => l.id === topId)?.zIndex ?? -1
    const bottomZ = after.find((l) => l.id === bottomId)?.zIndex ?? -1
    expect(topZ).toBeGreaterThan(bottomZ)
    expect(bottomZ).toBeGreaterThan(0)
    expect(useEditorStore.getState().canUndo).toBe(true)
  })
})
