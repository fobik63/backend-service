import { describe, expect, it } from "vitest"

import {
  buildProductInfographicPrompt,
  enrichPromptWithProductContext,
} from "@/lib/editor/canvas-actions"

describe("product → AI infographic prompt", () => {
  const meta = {
    title: "Крем для рук Sage Mist",
    brand: "Aura Lab",
    category: "Кремы",
    description: "Интенсивное увлажнение 24 часа. Без парабенов.",
  }

  it("builds a seed prompt from parsed product fields", () => {
    const prompt = buildProductInfographicPrompt(meta)
    expect(prompt).toContain("Aura Lab")
    expect(prompt).toContain("Крем для рук Sage Mist")
    expect(prompt).toContain("Интенсивное увлажнение 24 часа")
    expect(prompt).toContain("Кремы")
  })

  it("returns empty prompt when meta has no useful fields", () => {
    expect(
      buildProductInfographicPrompt({
        title: "",
        brand: "",
        category: "Товары",
        description: "",
      })
    ).toBe("")
  })

  it("appends product description as generate context when missing", () => {
    const enriched = enrichPromptWithProductContext(
      "Сделай минималистичную карточку",
      meta
    )
    expect(enriched).toContain("Сделай минималистичную карточку")
    expect(enriched).toContain("--- Контекст товара ---")
    expect(enriched).toContain(meta.description)
  })

  it("does not duplicate description already present in the prompt", () => {
    const seeded = buildProductInfographicPrompt(meta)
    expect(enrichPromptWithProductContext(seeded, meta)).toBe(seeded)
  })
})
