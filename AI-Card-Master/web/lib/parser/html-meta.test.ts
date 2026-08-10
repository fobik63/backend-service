import { describe, expect, it } from "vitest"

import {
  extractHtmlMeta,
  parsedProductFromHtmlMeta,
} from "@/lib/parser/html-meta"

describe("extractHtmlMeta", () => {
  it("reads title and meta description", () => {
    const html = `
      <html><head>
        <title>  SIM-карта МТС  </title>
        <meta name="description" content="Тариф для смартфона, без роуминга." />
      </head><body></body></html>
    `
    const meta = extractHtmlMeta(html, "https://example.com/sim")
    expect(meta.title).toBe("SIM-карта МТС")
    expect(meta.description).toBe("Тариф для смартфона, без роуминга.")
  })

  it("prefers Open Graph title and description", () => {
    const html = `
      <html><head>
        <title>Fallback</title>
        <meta property="og:title" content="Озон симка" />
        <meta property="og:description" content="OG desc" />
        <meta property="og:image" content="/img.webp" />
        <link rel="canonical" href="https://www.ozon.ru/product/123456/" />
      </head></html>
    `
    const meta = extractHtmlMeta(html, "https://www.ozon.ru/product/123456/")
    expect(meta.title).toBe("Озон симка")
    expect(meta.description).toBe("OG desc")
    expect(meta.ogImage).toBe("https://www.ozon.ru/img.webp")
    expect(meta.canonicalUrl).toBe("https://www.ozon.ru/product/123456/")
  })

  it("maps meta into ParsedProduct shape", () => {
    const product = parsedProductFromHtmlMeta({
      url: "https://www.wildberries.ru/catalog/99900111/detail.aspx",
      meta: {
        title: "Сим-карта Билайн",
        description: "Безлимит внутри сети",
        ogImage: null,
        canonicalUrl: null,
      },
    })
    expect(product.name).toBe("Сим-карта Билайн")
    expect(product.title).toBe("Сим-карта Билайн")
    expect(product.description).toBe("Безлимит внутри сети")
    expect(product.sku).toBe("99900111")
    expect(product.marketplace).toBe("wildberries")
  })

  it("throws on Antibot Challenge title instead of returning garbage", () => {
    const html = `
      <html><head>
        <title>Antibot Challenge Page</title>
      </head><body></body></html>
    `
    expect(() =>
      extractHtmlMeta(html, "https://www.wildberries.ru/catalog/1/detail.aspx"),
    ).toThrow()
  })
})
