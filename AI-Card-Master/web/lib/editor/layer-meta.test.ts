import { describe, expect, it } from "vitest"

import {
  applyTreeOrder,
  classifyLayer,
  layersForTree,
  layerTreeLabel,
} from "@/lib/editor/layer-meta"
import type { CanvasLayer } from "@/types/canvas"

const sample: CanvasLayer[] = [
  {
    id: "layer_bg",
    type: "background",
    name: "Фон",
    visible: true,
    locked: true,
    opacity: 1,
    zIndex: 0,
  },
  {
    id: "layer_product",
    type: "image",
    name: "Товар",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 1,
  },
  {
    id: "layer_title",
    type: "text",
    name: "Название",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 2,
    text: "Hello",
  },
  {
    id: "chip_1",
    type: "shape",
    name: "Плашка «Eco»",
    visible: true,
    locked: false,
    opacity: 1,
    zIndex: 3,
    chip: {
      label: "Eco",
      bgColor: "#000",
      borderRadius: 12,
      iconId: "icon_leaf",
    },
  },
]

describe("layer-meta", () => {
  it("classifies store types into tree kinds", () => {
    expect(classifyLayer(sample[0]!)).toBe("background")
    expect(classifyLayer(sample[1]!)).toBe("product")
    expect(classifyLayer(sample[2]!)).toBe("text")
    expect(classifyLayer(sample[3]!)).toBe("badge")
  })

  it("lists top layers first and background last", () => {
    const tree = layersForTree(sample)
    expect(tree.map((l) => l.id)).toEqual([
      "chip_1",
      "layer_title",
      "layer_product",
      "layer_bg",
    ])
  })

  it("forces background to zIndex 0 when applying tree order", () => {
    const next = applyTreeOrder(sample, [
      "layer_product",
      "chip_1",
      "layer_title",
      "layer_bg",
    ])
    expect(next.find((l) => l.id === "layer_bg")?.zIndex).toBe(0)
    expect(next.find((l) => l.id === "layer_product")?.zIndex).toBe(3)
    expect(next.find((l) => l.id === "chip_1")?.zIndex).toBe(2)
    expect(next.find((l) => l.id === "layer_title")?.zIndex).toBe(1)
  })

  it("prefers readable labels for tree rows", () => {
    expect(layerTreeLabel(sample[2]!)).toBe("Название")
    expect(layerTreeLabel(sample[3]!)).toContain("Плашка")
  })
})
