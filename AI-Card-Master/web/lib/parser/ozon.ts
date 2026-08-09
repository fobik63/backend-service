import type { MarketplaceHttpClient } from "@/lib/parser/http-client"
import {
  brandFromCharacteristics,
  buildParsedProduct,
  categoryFromCharacteristics,
  cleanText,
  stripHtml,
} from "@/lib/parser/normalize"
import { ParserScrapeError } from "@/lib/parser/errors"
import type {
  ParsedCharacteristic,
  ParsedProduct,
  ResolvedProductTarget,
} from "@/lib/parser/types"

type JsonRecord = Record<string, unknown>

/** Marketplace headers without a fixed UA — http-client rotates User-Agent. */
const OZON_HEADERS: Record<string, string> = {
  Accept:
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
  "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
  "Cache-Control": "no-cache",
}

/**
 * Ozon product scraper.
 * 1) Fetch HTML and parse embedded `__NUXT__` state.
 * 2) Fall back to Puppeteer (headless + stealth) when HTML/state is blocked.
 */
export async function scrapeOzonProduct(
  http: MarketplaceHttpClient,
  target: ResolvedProductTarget,
): Promise<ParsedProduct> {
  let nuxtState: unknown | null = null
  let html = ""

  try {
    const response = await http.get<string>(target.productUrl, {
      headers: OZON_HEADERS,
      timeoutMs: 35_000,
      responseType: "text",
      userAgentProfile: "desktop",
    })
    html = typeof response.data === "string" ? response.data : ""
    nuxtState = extractNuxtState(html)
  } catch (error) {
    // Continue to Puppeteer fallback below.
    void error
  }

  if (!nuxtState || !hasUsableProductSignals(nuxtState)) {
    try {
      const puppeteerResult = await scrapeOzonWithPuppeteer(target.productUrl)
      if (puppeteerResult.nuxtState) {
        nuxtState = puppeteerResult.nuxtState
      }
      if (puppeteerResult.html) {
        html = puppeteerResult.html
        if (!nuxtState) {
          nuxtState = extractNuxtState(html)
        }
      }
      if (!nuxtState && puppeteerResult.title) {
        return buildParsedProduct({
          marketplace: "ozon",
          sku: target.sku,
          productUrl: target.productUrl,
          fields: {
            name: cleanText(puppeteerResult.title).replace(
              /\s*[—|-]\s*Ozon.*$/i,
              "",
            ),
            brand: "",
            category: "",
            description: cleanText(puppeteerResult.description),
          },
          imageUrls: [],
        })
      }
    } catch (error) {
      if (!nuxtState) {
        throw new ParserScrapeError(
          `Ozon scrape failed: ${errorMessage(error)}`,
          "TRANSPORT",
        )
      }
    }
  }

  if (!nuxtState) {
    // Last resort: meta tags from raw HTML (if any).
    const meta = extractFromHtmlMeta(html)
    if (meta.name) {
      return buildParsedProduct({
        marketplace: "ozon",
        sku: target.sku,
        productUrl: target.productUrl,
        fields: meta,
        imageUrls: [],
      })
    }
    throw new ParserScrapeError(
      `Ozon product sku=${target.sku} could not be parsed (__NUXT__ missing).`,
      "NOT_FOUND",
    )
  }

  const characteristics = extractOzonCharacteristics(nuxtState)
  let name =
    findFirstString(nuxtState, [
      "title",
      "seoTitle",
      "name",
      "cellTrackingInfo",
    ]) || extractFromHtmlMeta(html).name
  // Prefer product-looking titles over tracking blobs.
  name = preferProductTitle(nuxtState, name)

  let brand =
    findFirstString(nuxtState, ["brandName", "brand", "brandTitle", "trademark"]) ||
    brandFromCharacteristics(characteristics)

  let category =
    extractOzonCategory(nuxtState, characteristics) ||
    categoryFromCharacteristics(characteristics, "")

  let description =
    extractOzonDescription(nuxtState) || extractFromHtmlMeta(html).description

  if (!name) {
    throw new ParserScrapeError(
      `Ozon product sku=${target.sku} has no title.`,
      "NOT_FOUND",
    )
  }

  if (!category) category = "Товары"

  const imageUrls = extractOzonImageUrls(nuxtState)

  return buildParsedProduct({
    marketplace: "ozon",
    sku: target.sku,
    productUrl: target.productUrl,
    fields: { name, brand, category, description },
    characteristics,
    imageUrls,
  })
}

export function extractNuxtState(html: string): unknown | null {
  if (!html) return null

  const patterns = [
    /window\.__NUXT__\s*=\s*(\{[\s\S]*?\});\s*<\/script>/i,
    /window\.__NUXT__\s*=\s*(\{[\s\S]*?\})\s*;?\s*(?:<\/script>|$)/i,
    /<script[^>]*>\s*window\.__NUXT__\s*=\s*(\{[\s\S]*?\})\s*;?\s*<\/script>/i,
  ]

  for (const pattern of patterns) {
    const match = pattern.exec(html)
    if (!match?.[1]) continue
    const parsed = safeJsonParse(match[1])
    if (parsed != null) return parsed
  }

  // Some builds embed serialized state without assignment sugar.
  const dataScript = /<script[^>]*id=["']__NUXT_DATA__["'][^>]*>([\s\S]*?)<\/script>/i.exec(
    html,
  )
  if (dataScript?.[1]) {
    const parsed = safeJsonParse(dataScript[1].trim())
    if (parsed != null) return parsed
  }

  return null
}

export function extractOzonCharacteristics(
  payload: unknown,
): ParsedCharacteristic[] {
  const rows: ParsedCharacteristic[] = []
  const seen = new Set<string>()

  for (const node of walkObjects(payload)) {
    for (const key of [
      "characteristics",
      "shortCharacteristics",
      "attrs",
      "attributes",
    ]) {
      const list = node[key]
      if (!Array.isArray(list)) continue
      for (const item of list) {
        if (!item || typeof item !== "object") continue
        const row = item as JsonRecord
        const name = cleanText(
          row.name ?? row.key ?? row.title ?? row.property ?? "",
        )
        let values = row.values ?? row.value ?? row.text
        let valueStr = ""
        if (Array.isArray(values)) {
          valueStr = values
            .map((v) =>
              typeof v === "object" && v
                ? String(
                    (v as JsonRecord).text ??
                      (v as JsonRecord).value ??
                      (v as JsonRecord).name ??
                      "",
                  )
                : String(v ?? ""),
            )
            .map(cleanText)
            .filter(Boolean)
            .join(", ")
        } else {
          valueStr = cleanText(values)
        }
        if (!name || !valueStr) continue
        const dedupe = name.toLowerCase()
        if (seen.has(dedupe)) continue
        seen.add(dedupe)
        rows.push({ name: name.slice(0, 256), value: valueStr.slice(0, 2000) })
      }
    }

    if ("key" in node && "value" in node) {
      const name = cleanText(node.key)
      const value = cleanText(node.value)
      if (name && value && !seen.has(name.toLowerCase())) {
        seen.add(name.toLowerCase())
        rows.push({ name: name.slice(0, 256), value: value.slice(0, 2000) })
      }
    }
  }

  return rows
}

export function extractOzonDescription(payload: unknown): string {
  const candidates: string[] = []

  for (const node of walkObjects(payload)) {
    for (const key of ["description", "richAnnotation", "html"]) {
      const value = node[key]
      if (typeof value === "string") {
        const text = stripHtml(value)
        if (text.length >= 40) candidates.push(text)
      }
    }

    const sections = node.sections
    if (Array.isArray(sections)) {
      for (const section of sections) {
        if (!section || typeof section !== "object") continue
        const row = section as JsonRecord
        const title = cleanText(row.title).toLowerCase()
        if (!title.includes("описан") && !title.includes("description")) {
          continue
        }
        const body = row.text ?? row.description
        if (typeof body === "string" && body.trim()) {
          candidates.push(stripHtml(body))
        }
      }
    }
  }

  if (!candidates.length) return ""
  return candidates.reduce((a, b) => (a.length >= b.length ? a : b))
}

export function extractOzonCategory(
  payload: unknown,
  characteristics: ParsedCharacteristic[],
): string {
  const fromChars = categoryFromCharacteristics(characteristics, "")
  if (fromChars) return fromChars

  for (const node of walkObjects(payload)) {
    const breadcrumbs = node.breadcrumbs ?? node.breadCrumbs ?? node.categoryPath
    if (Array.isArray(breadcrumbs) && breadcrumbs.length) {
      const labels = breadcrumbs
        .map((item) => {
          if (typeof item === "string") return cleanText(item)
          if (item && typeof item === "object") {
            const row = item as JsonRecord
            return cleanText(row.text ?? row.title ?? row.name ?? row.label)
          }
          return ""
        })
        .filter(Boolean)
      if (labels.length) {
        // Last crumb is usually the leaf category.
        return labels[labels.length - 1]
      }
    }

    const category = node.category ?? node.categoryName ?? node.category_name
    if (typeof category === "string" && category.trim()) {
      return category.trim()
    }
    if (category && typeof category === "object") {
      const row = category as JsonRecord
      const name = cleanText(row.name ?? row.title ?? row.text)
      if (name) return name
    }
  }

  return ""
}

export function extractOzonImageUrls(payload: unknown): string[] {
  const urls: string[] = []
  const seen = new Set<string>()

  for (const node of walkObjects(payload)) {
    for (const key of ["images", "gallery", "photos", "coverImageItems", "items"]) {
      const items = node[key]
      if (!Array.isArray(items)) continue
      for (const item of items) {
        const candidates: string[] = []
        if (typeof item === "string") candidates.push(item)
        else if (item && typeof item === "object") {
          const row = item as JsonRecord
          for (const imgKey of ["url", "src", "image", "imageUrl", "link"]) {
            const value = row[imgKey]
            if (typeof value === "string") candidates.push(value)
          }
        }
        for (const raw of candidates) {
          const url = normalizeImageUrl(raw)
          if (!url || seen.has(url)) continue
          if (!/ozon|cdn|ir\.|io\./i.test(url)) continue
          seen.add(url)
          urls.push(url)
        }
      }
    }
  }

  return preferLargerOzonImages(urls).slice(0, 30)
}

function preferProductTitle(payload: unknown, fallback: string): string {
  const seo = findFirstString(payload, ["seoTitle"])
  if (seo && seo.length >= 8 && seo.length <= 300) return seo

  for (const node of walkObjects(payload)) {
    if (typeof node.title === "string") {
      const title = cleanText(node.title)
      if (
        title.length >= 8 &&
        title.length <= 300 &&
        !/cellTrackingInfo|widget/i.test(title)
      ) {
        // Prefer nodes that look like a product card.
        const widgetType = String(node.widgetType ?? node.type ?? "")
        if (
          "sku" in node ||
          "brand" in node ||
          "brandName" in node ||
          "price" in node ||
          "coverImage" in node ||
          widgetType.toLowerCase().includes("webproduct")
        ) {
          return title
        }
      }
    }
  }

  return cleanText(fallback)
}

function extractFromHtmlMeta(html: string): {
  name: string
  brand: string
  category: string
  description: string
} {
  if (!html) {
    return { name: "", brand: "", category: "", description: "" }
  }
  const ogTitle =
    /property=["']og:title["'][^>]*content=["']([^"']+)["']/i.exec(html)?.[1] ||
    /content=["']([^"']+)["'][^>]*property=["']og:title["']/i.exec(html)?.[1] ||
    /<title[^>]*>([^<]+)<\/title>/i.exec(html)?.[1] ||
    ""
  const ogDescription =
    /property=["']og:description["'][^>]*content=["']([^"']+)["']/i.exec(
      html,
    )?.[1] ||
    /name=["']description["'][^>]*content=["']([^"']+)["']/i.exec(html)?.[1] ||
    ""

  return {
    name: cleanText(decodeHtmlEntities(ogTitle)).replace(/\s*[—|-]\s*Ozon.*$/i, ""),
    brand: "",
    category: "",
    description: cleanText(decodeHtmlEntities(ogDescription)),
  }
}

function hasUsableProductSignals(payload: unknown): boolean {
  const title = preferProductTitle(payload, findFirstString(payload, ["title", "name"]))
  return Boolean(title && title.length >= 3)
}

async function scrapeOzonWithPuppeteer(productUrl: string): Promise<{
  nuxtState: unknown | null
  html: string
  title: string
  description: string
}> {
  // Dynamic import keeps Next.js from bundling Chromium into client graphs.
  const { launchOzonBrowserPage } = await import("@/lib/parser/ozon-puppeteer")
  return launchOzonBrowserPage(productUrl)
}

function* walkObjects(value: unknown, depth = 0): Generator<JsonRecord> {
  if (depth > 25 || value == null) return
  if (Array.isArray(value)) {
    for (const item of value) yield* walkObjects(item, depth + 1)
    return
  }
  if (typeof value !== "object") return
  const obj = value as JsonRecord
  yield obj
  for (const child of Object.values(obj)) {
    yield* walkObjects(child, depth + 1)
  }
}

function findFirstString(payload: unknown, keys: string[]): string {
  for (const node of walkObjects(payload)) {
    for (const key of keys) {
      if (!(key in node)) continue
      if (key === "cellTrackingInfo") continue
      const value = node[key]
      if (typeof value === "string" && value.trim()) return value.trim()
      if (value && typeof value === "object") {
        const nested = value as JsonRecord
        const title = nested.title ?? nested.name ?? nested.text
        if (typeof title === "string" && title.trim()) return title.trim()
      }
    }
  }
  return ""
}

function preferLargerOzonImages(urls: string[]): string[] {
  const scored = urls.map((url, index) => {
    const lowered = url.toLowerCase()
    let score = 0
    for (const [token, weight] of [
      ["wc2000", 2000],
      ["wc1200", 1200],
      ["wc1000", 1000],
      ["wc800", 800],
      ["original", 3000],
      ["/video/", -5000],
    ] as const) {
      if (lowered.includes(token)) score = Math.max(score, weight)
    }
    return { url, score, index }
  })
  scored.sort((a, b) => b.score - a.score || a.index - b.index)
  return scored.map((row) => row.url)
}

function normalizeImageUrl(raw: string): string {
  const value = raw.trim()
  if (!value) return ""
  if (value.startsWith("//")) return `https:${value}`
  if (value.startsWith("http://") || value.startsWith("https://")) return value
  return ""
}

function safeJsonParse(raw: string): unknown | null {
  try {
    return JSON.parse(raw)
  } catch {
    // __NUXT__ sometimes contains `undefined` literals — normalize them.
    try {
      const normalized = raw
        .replace(/\bundefined\b/g, "null")
        .replace(/,\s*([}\]])/g, "$1")
      return JSON.parse(normalized)
    } catch {
      return null
    }
  }
}

function decodeHtmlEntities(value: string): string {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
}

function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message)
  }
  return String(error)
}
