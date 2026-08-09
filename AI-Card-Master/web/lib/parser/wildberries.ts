import type { MarketplaceHttpClient } from "@/lib/parser/http-client"
import {
  brandFromCharacteristics,
  buildParsedProduct,
  categoryFromCharacteristics,
  cleanText,
} from "@/lib/parser/normalize"
import { ParserScrapeError } from "@/lib/parser/errors"
import type {
  ParsedCharacteristic,
  ParsedProduct,
  ResolvedProductTarget,
} from "@/lib/parser/types"

const WB_CARD_BASE =
  process.env.PARSER_WB_CARD_BASE_URL?.replace(/\/+$/, "") ||
  "https://card.wb.ru"

const WB_CONTENT_BASE =
  process.env.PARSER_WB_CONTENT_BASE_URL?.replace(/\/+$/, "") ||
  "https://wbx-content-v2.wbstatic.net"

const WB_DEST = Number(process.env.PARSER_WB_DEST ?? "-1257786")

/** Marketplace headers without a fixed UA — http-client rotates User-Agent. */
const WB_HEADERS: Record<string, string> = {
  Accept: "application/json",
  Origin: "https://www.wildberries.ru",
  Referer: "https://www.wildberries.ru/",
}

type JsonRecord = Record<string, unknown>

/**
 * Wildberries card scraper via public (unofficial) mobile JSON API.
 * Primary: `https://card.wb.ru/cards/v1/detail?nm={article}`
 * Enrichment: content CDN for description / category when card payload is sparse.
 */
export async function scrapeWildberriesProduct(
  http: MarketplaceHttpClient,
  target: ResolvedProductTarget,
): Promise<ParsedProduct> {
  const nm = target.sku
  const cardUrl =
    `${WB_CARD_BASE}/cards/v1/detail` +
    `?appType=1&curr=rub&dest=${WB_DEST}&nm=${encodeURIComponent(nm)}`

  let cardPayload: unknown
  try {
    const response = await http.get<unknown>(cardUrl, {
      headers: WB_HEADERS,
      timeoutMs: 25_000,
      userAgentProfile: "mobile",
    })
    cardPayload = response.data
  } catch (error) {
    throw new ParserScrapeError(
      `Wildberries card API request failed: ${errorMessage(error)}`,
      "TRANSPORT",
    )
  }

  const product = extractWbProduct(cardPayload)
  if (!product) {
    throw new ParserScrapeError(
      `Wildberries product nm=${nm} was not found.`,
      "NOT_FOUND",
    )
  }

  let name = pickString(product, ["name", "imt_name", "goods_name"])
  let brand = extractWbBrand(product)
  let category = ""
  let description = pickString(product, [
    "description",
    "imt_description",
    "full_description",
  ])
  let characteristics = extractWbCharacteristics(product)
  const pics = Math.max(1, toPositiveInt(product.pics) ?? 1)
  const cardCategory = pickString(product, [
    "entity",
    "subj_name",
    "subjectName",
    "subject_name",
    "category",
  ])

  const content = await fetchWbContent(http, nm)
  if (content) {
    name =
      name ||
      pickString(content, ["imt_name", "name", "goods_name", "title"])
    brand = brand || extractWbBrand(content)
    // Content `subj_name` is usually more precise than card `entity`.
    category = pickString(content, [
      "subj_name",
      "subjectname",
      "subjectName",
      "subject_name",
      "entity",
      "category",
    ])
    const contentDescription = pickString(content, [
      "description",
      "imt_description",
      "full_description",
    ])
    // Prefer the richer content description when the card one is short/empty.
    if (
      contentDescription &&
      (!description || contentDescription.length > description.length)
    ) {
      description = contentDescription
    }
    characteristics = mergeCharacteristics(
      characteristics,
      extractWbCharacteristics(content),
    )
  }

  if (!category) {
    category = cardCategory
  }

  if (!category) {
    category = categoryFromCharacteristics(characteristics, "Товары")
  }
  if (!brand) {
    brand = brandFromCharacteristics(characteristics)
  }

  if (!name) {
    throw new ParserScrapeError(
      `Wildberries product nm=${nm} has no title.`,
      "NOT_FOUND",
    )
  }

  return buildParsedProduct({
    marketplace: "wildberries",
    sku: nm,
    productUrl: target.productUrl,
    fields: { name, brand, category, description },
    characteristics,
    imageUrls: buildWbImageUrls(Number(nm), pics),
  })
}

async function fetchWbContent(
  http: MarketplaceHttpClient,
  nm: string,
): Promise<JsonRecord | null> {
  const url = `${WB_CONTENT_BASE}/ru/${encodeURIComponent(nm)}.json`
  try {
    const response = await http.get<unknown>(url, {
      headers: WB_HEADERS,
      timeoutMs: 20_000,
      bypassProxy: false,
      userAgentProfile: "mobile",
    })
    if (response.data && typeof response.data === "object") {
      return response.data as JsonRecord
    }
  } catch {
    // Description/category enrichment is best-effort.
  }
  return null
}

export function extractWbProduct(payload: unknown): JsonRecord | null {
  if (!payload || typeof payload !== "object") return null
  const root = payload as JsonRecord
  const data = root.data
  if (data && typeof data === "object") {
    const products = (data as JsonRecord).products
    if (Array.isArray(products)) {
      if (products.length === 0) return null
      const first = products[0]
      if (first && typeof first === "object") return first as JsonRecord
    }
  }
  const products = root.products
  if (Array.isArray(products) && products[0] && typeof products[0] === "object") {
    return products[0] as JsonRecord
  }
  if ("name" in root || "salePriceU" in root || "id" in root) {
    return root
  }
  return null
}

export function extractWbBrand(payload: JsonRecord): string {
  for (const key of ["brand", "brandName", "sellingBrand", "trademark"]) {
    const value = payload[key]
    if (typeof value === "string" && value.trim()) return value.trim()
    if (value && typeof value === "object") {
      const nested = value as JsonRecord
      const name = nested.name ?? nested.title
      if (typeof name === "string" && name.trim()) return name.trim()
    }
  }
  const selling = payload.selling
  if (selling && typeof selling === "object") {
    const row = selling as JsonRecord
    const brand = row.brandName ?? row.brand
    if (typeof brand === "string" && brand.trim()) return brand.trim()
  }
  return ""
}

export function extractWbCharacteristics(
  payload: JsonRecord,
): ParsedCharacteristic[] {
  const rows: ParsedCharacteristic[] = []
  const seen = new Set<string>()

  const push = (name: unknown, value: unknown) => {
    const n = cleanText(name)
    let v = value
    if (Array.isArray(v)) {
      v = v
        .map((item) =>
          typeof item === "object" && item
            ? String(
                (item as JsonRecord).name ??
                  (item as JsonRecord).value ??
                  (item as JsonRecord).text ??
                  "",
              )
            : String(item ?? ""),
        )
        .filter(Boolean)
        .join(", ")
    }
    const valueStr = cleanText(v)
    if (!n || !valueStr) return
    const key = n.toLowerCase()
    if (seen.has(key)) return
    seen.add(key)
    rows.push({ name: n.slice(0, 256), value: valueStr.slice(0, 2000) })
  }

  const options = payload.options ?? payload.characteristics
  if (Array.isArray(options)) {
    for (const item of options) {
      if (!item || typeof item !== "object") continue
      const row = item as JsonRecord
      push(row.name ?? row.key, row.value ?? row.values ?? row.val)
    }
  }

  const grouped = payload.grouped_options
  if (Array.isArray(grouped)) {
    for (const group of grouped) {
      if (!group || typeof group !== "object") continue
      const opts = (group as JsonRecord).options
      if (!Array.isArray(opts)) continue
      for (const item of opts) {
        if (!item || typeof item !== "object") continue
        const row = item as JsonRecord
        push(row.name, row.value)
      }
    }
  }

  return rows
}

export function buildWbImageUrls(nmId: number, count: number): string[] {
  if (!Number.isFinite(nmId) || nmId <= 0) return []
  const vol = Math.floor(nmId / 100_000)
  const part = Math.floor(nmId / 1_000)
  const host = wbBasketHost(vol)
  const total = Math.max(1, Math.min(count, 30))
  const urls: string[] = []
  for (let index = 1; index <= total; index += 1) {
    urls.push(`${host}/vol${vol}/part${part}/${nmId}/images/big/${index}.webp`)
  }
  return urls
}

function wbBasketHost(vol: number): string {
  const ranges: Array<[number, number]> = [
    [143, 1],
    [287, 2],
    [431, 3],
    [719, 4],
    [1007, 5],
    [1061, 6],
    [1115, 7],
    [1169, 8],
    [1313, 9],
    [1601, 10],
    [1655, 11],
    [1919, 12],
    [2045, 13],
    [2189, 14],
    [2405, 15],
    [2621, 16],
    [2837, 17],
    [3053, 18],
    [3269, 19],
    [3485, 20],
    [3701, 21],
    [3917, 22],
    [4133, 23],
    [4349, 24],
    [4565, 25],
    [4781, 26],
    [4997, 27],
    [5213, 28],
    [5429, 29],
    [5645, 30],
  ]
  for (const [maxVol, basket] of ranges) {
    if (vol <= maxVol) {
      return `https://basket-${String(basket).padStart(2, "0")}.wbbasket.ru`
    }
  }
  return "https://basket-31.wbbasket.ru"
}

function mergeCharacteristics(
  primary: ParsedCharacteristic[],
  secondary: ParsedCharacteristic[],
): ParsedCharacteristic[] {
  const seen = new Set(primary.map((row) => row.name.toLowerCase()))
  const merged = [...primary]
  for (const row of secondary) {
    const key = row.name.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(row)
  }
  return merged
}

function pickString(payload: JsonRecord, keys: string[]): string {
  for (const key of keys) {
    const value = payload[key]
    if (typeof value === "string" && value.trim()) return value.trim()
  }
  return ""
}

function toPositiveInt(value: unknown): number | null {
  const n = typeof value === "number" ? value : Number(value)
  if (!Number.isFinite(n) || n <= 0) return null
  return Math.floor(n)
}

function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message)
  }
  return String(error)
}
