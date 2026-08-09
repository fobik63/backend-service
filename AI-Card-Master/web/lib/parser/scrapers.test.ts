import { describe, expect, it, vi } from "vitest"

import { MarketplaceHttpClient } from "@/lib/parser/http-client"
import {
  extractNuxtState,
  extractOzonCategory,
  extractOzonCharacteristics,
  extractOzonDescription,
} from "@/lib/parser/ozon"
import { createScraperRouter } from "@/lib/parser/scrapers"
import {
  buildWbImageUrls,
  extractWbBrand,
  extractWbProduct,
} from "@/lib/parser/wildberries"

describe("Wildberries card extraction", () => {
  const cardFixture = {
    data: {
      products: [
        {
          id: 178902345,
          name: "Крем для рук Sage Mist 75 мл",
          brand: "Sage Mist",
          entity: "Кремы",
          pics: 2,
          description: "Питательный крем для рук.",
        },
      ],
    },
  }

  it("extracts product from card.wb.ru payload", () => {
    const product = extractWbProduct(cardFixture)
    expect(product?.name).toBe("Крем для рук Sage Mist 75 мл")
    expect(extractWbBrand(product!)).toBe("Sage Mist")
  })

  it("builds basket CDN image urls", () => {
    const urls = buildWbImageUrls(178902345, 2)
    expect(urls).toHaveLength(2)
    expect(urls[0]).toMatch(/\/178902345\/images\/big\/1\.webp$/)
  })

  it("scrapes normalized name/brand/category/description via http mock", async () => {
    const get = vi.fn(async (url: string) => {
      if (url.includes("card.wb.ru")) {
        return { data: cardFixture, status: 200 }
      }
      if (url.includes("wbx-content")) {
        return {
          data: {
            description: "Полное описание из content API.",
            subj_name: "Кремы для рук",
            options: [{ name: "Объём", value: "75 мл" }],
          },
          status: 200,
        }
      }
      throw new Error(`unexpected url ${url}`)
    })

    const http = {
      get,
    } as unknown as MarketplaceHttpClient

    const router = createScraperRouter({ http })
    const product = await router.scrape({
      marketplace: "wildberries",
      sku: "178902345",
      productUrl: "https://www.wildberries.ru/catalog/178902345/detail.aspx",
      rawInput: "178902345",
    })

    expect(product.name).toBe("Крем для рук Sage Mist 75 мл")
    expect(product.title).toBe(product.name)
    expect(product.brand).toBe("Sage Mist")
    expect(product.category).toBe("Кремы для рук")
    expect(product.description).toContain("Полное описание")
    expect(product.characteristics.some((c) => c.name === "Категория")).toBe(
      true,
    )
  })
})

describe("Ozon __NUXT__ extraction", () => {
  const nuxtFixture = {
    state: {
      product: {
        title: "Фен профессиональный ProDry 2000",
        brandName: "ProDry",
        category: { name: "Фены" },
        description: "Мощный фен для ежедневной укладки волос. ".repeat(3),
        characteristics: [
          { name: "Бренд", values: [{ text: "ProDry" }] },
          { name: "Категория", value: "Фены" },
        ],
        images: ["https://cdn1.ozon.ru/s3/cover/wc1200/1.jpg"],
      },
    },
  }

  it("parses window.__NUXT__ assignment from HTML", () => {
    const html = `<html><script>window.__NUXT__=${JSON.stringify(nuxtFixture)};</script></html>`
    const state = extractNuxtState(html)
    expect(state).toEqual(nuxtFixture)
  })

  it("extracts brand/category/description from nuxt state", () => {
    const characteristics = extractOzonCharacteristics(nuxtFixture)
    expect(extractOzonCategory(nuxtFixture, characteristics)).toBe("Фены")
    expect(extractOzonDescription(nuxtFixture).length).toBeGreaterThan(40)
    expect(characteristics.find((c) => c.name === "Бренд")?.value).toBe(
      "ProDry",
    )
  })

  it("scrapes normalized fields via http mock returning __NUXT__ html", async () => {
    const html = `<!doctype html><html><head>
      <title>Фен профессиональный ProDry 2000 — Ozon</title>
      </head><body>
      <script>window.__NUXT__=${JSON.stringify(nuxtFixture)};</script>
      </body></html>`

    const http = {
      get: vi.fn(async () => ({ data: html, status: 200 })),
    } as unknown as MarketplaceHttpClient

    const router = createScraperRouter({ http })
    const product = await router.scrape({
      marketplace: "ozon",
      sku: "123456789",
      productUrl: "https://www.ozon.ru/product/fen-123456789/",
      rawInput: "https://www.ozon.ru/product/fen-123456789/",
    })

    expect(product.name).toContain("ProDry")
    expect(product.brand).toBe("ProDry")
    expect(product.category).toBe("Фены")
    expect(product.description?.length ?? 0).toBeGreaterThan(20)
  })
})
