import type {
  ParserMarketplace,
  ParserPlatformHint,
  ResolvedProductTarget,
} from "@/lib/parser/types"

const ARTICLE_RE = /^\d{5,15}$/
const WB_CATALOG_PATH = /\/catalog\/(\d{5,})/i
const OZON_PRODUCT_PATH = /\/product\/[^/]*?(\d{6,})/i

const WB_HOSTS = new Set([
  "www.wildberries.ru",
  "wildberries.ru",
  "global.wildberries.ru",
  "www.wb.ru",
  "wb.ru",
])

const OZON_HOSTS = new Set(["www.ozon.ru", "ozon.ru", "m.ozon.ru"])

const WB_ARTICLE_URL = (sku: string) =>
  `https://www.wildberries.ru/catalog/${sku}/detail.aspx`

const OZON_ARTICLE_URL = (sku: string) => `https://www.ozon.ru/product/${sku}/`

export class ParserValidationError extends Error {
  readonly code = "VALIDATION_ERROR" as const

  constructor(message: string) {
    super(message)
    this.name = "ParserValidationError"
  }
}

/** Resolve a URL or bare article into a marketplace scrape target. */
export function resolveParserInput(
  rawInput: string,
  platform: ParserPlatformHint = "auto",
): ResolvedProductTarget {
  const cleaned = rawInput.trim()
  if (!cleaned) {
    throw new ParserValidationError("input must not be empty.")
  }
  if (cleaned.length > 2048) {
    throw new ParserValidationError("input exceeds maximum length of 2048.")
  }

  if (looksLikeUrl(cleaned)) {
    const url = cleaned.includes("://") ? cleaned : `https://${cleaned}`
    const link = parseMarketplaceUrl(url)
    assertPlatformMatches(link.marketplace, platform)
    return {
      marketplace: link.marketplace,
      sku: link.sku,
      productUrl: link.productUrl,
      rawInput: cleaned,
    }
  }

  const sku = extractArticleDigits(cleaned)
  if (!sku) {
    throw new ParserValidationError(
      "input must be a Wildberries/Ozon product URL or a numeric article.",
    )
  }

  if (platform === "auto") {
    throw new ParserValidationError(
      "Bare article requires platform 'wb' or 'ozon' (auto only works with URLs).",
    )
  }

  const marketplace: ParserMarketplace =
    platform === "wb" ? "wildberries" : "ozon"

  return {
    marketplace,
    sku,
    productUrl:
      marketplace === "wildberries"
        ? WB_ARTICLE_URL(sku)
        : OZON_ARTICLE_URL(sku),
    rawInput: cleaned,
  }
}

export function parseMarketplaceUrl(rawUrl: string): {
  marketplace: ParserMarketplace
  sku: string
  productUrl: string
} {
  let parsed: URL
  try {
    parsed = new URL(rawUrl.trim())
  } catch {
    throw new ParserValidationError("Link must be a valid URL.")
  }

  const scheme = parsed.protocol.replace(":", "").toLowerCase()
  if (scheme !== "http" && scheme !== "https") {
    throw new ParserValidationError("Link must use http or https scheme.")
  }

  const host = (parsed.hostname || "").toLowerCase()
  if (!host) {
    throw new ParserValidationError("Link must include a hostname.")
  }

  const path = parsed.pathname || ""

  if (WB_HOSTS.has(host) || host.endsWith(".wildberries.ru")) {
    const match = WB_CATALOG_PATH.exec(path)
    const sku = match?.[1] ?? trailingDigits(path)
    if (!sku) {
      throw new ParserValidationError(
        "Wildberries link must contain /catalog/<nmId> product path.",
      )
    }
    return {
      marketplace: "wildberries",
      sku,
      productUrl: rawUrl.trim(),
    }
  }

  if (OZON_HOSTS.has(host) || host.endsWith(".ozon.ru")) {
    const match = OZON_PRODUCT_PATH.exec(path)
    const sku = match?.[1] ?? trailingDigits(path, 6)
    if (!sku) {
      throw new ParserValidationError(
        "Ozon link must contain /product/...<sku> product path.",
      )
    }
    return {
      marketplace: "ozon",
      sku,
      productUrl: rawUrl.trim(),
    }
  }

  throw new ParserValidationError(
    "Only wildberries.ru / wb.ru and ozon.ru product links are supported.",
  )
}

function looksLikeUrl(value: string): boolean {
  const lowered = value.toLowerCase()
  if (lowered.startsWith("http://") || lowered.startsWith("https://")) {
    return true
  }
  try {
    const host = new URL(
      value.includes("://") ? value : `https://${value}`,
    ).hostname.toLowerCase()
    return Boolean(
      host &&
        (host.includes("wildberries.ru") ||
          host.endsWith("wb.ru") ||
          host === "wb.ru" ||
          host.includes("ozon.ru")),
    )
  } catch {
    return false
  }
}

function extractArticleDigits(value: string): string | null {
  const digitsOnly = value.replace(/\D/g, "")
  if (ARTICLE_RE.test(digitsOnly)) return digitsOnly
  const match = /(\d{5,15})/.exec(value)
  if (match && ARTICLE_RE.test(match[1])) return match[1]
  return null
}

function trailingDigits(path: string, minLength = 5): string | null {
  for (const part of path.replace(/\/+$/, "").split("/").reverse()) {
    if (/^\d+$/.test(part) && part.length >= minLength) return part
    const slug = /(\d{6,})$/.exec(part)
    if (slug) return slug[1]
  }
  return null
}

function assertPlatformMatches(
  marketplace: ParserMarketplace,
  platform: ParserPlatformHint,
): void {
  if (platform === "auto") return
  const expected: ParserMarketplace =
    platform === "wb" ? "wildberries" : "ozon"
  if (marketplace !== expected) {
    throw new ParserValidationError(
      `platform '${platform}' does not match URL marketplace '${marketplace}'.`,
    )
  }
}
