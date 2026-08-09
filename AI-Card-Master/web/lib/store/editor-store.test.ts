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
      packSize: current.packSize,
    })

    expect(useEditorStore.getState().projectId).toBe("another-project")
    expect(useEditorStore.getState().canUndo).toBe(false)
    expect(useEditorStore.getState().history.past).toHaveLength(0)
  })
})
