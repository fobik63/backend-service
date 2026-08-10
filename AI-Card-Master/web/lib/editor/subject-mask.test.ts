import { describe, expect, it } from "vitest"

import { imageHasTransparency } from "@/lib/editor/subject-mask"

function makeImageData(
  width: number,
  height: number,
  fillAlpha: (x: number, y: number) => number,
): ImageData {
  const data = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = (y * width + x) * 4
      data[i] = 200
      data[i + 1] = 40
      data[i + 2] = 40
      data[i + 3] = fillAlpha(x, y)
    }
  }
  return { data, width, height, colorSpace: "srgb" } as ImageData
}

describe("subject-mask helpers", () => {
  it("detects opaque images as no transparency", () => {
    const image = makeImageData(8, 8, () => 255)
    expect(imageHasTransparency(image)).toBe(false)
  })

  it("detects cutouts with transparent pixels", () => {
    const image = makeImageData(8, 8, (x, y) => (x > 3 && y > 3 ? 255 : 0))
    expect(imageHasTransparency(image)).toBe(true)
  })
})
