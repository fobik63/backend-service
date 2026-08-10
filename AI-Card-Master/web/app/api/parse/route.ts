import { NextResponse } from "next/server"

import {
  ANTIBOT_ERROR_CODE,
  ANTIBOT_USER_MESSAGE,
  isAntibotScrapeError,
} from "@/lib/parser/antibot"
import {
  parsedProductFromHtmlMeta,
  scrapeHtmlMeta,
} from "@/lib/parser/html-meta"
import { MarketplaceHttpClient } from "@/lib/parser/http-client"
import { ProxyPool } from "@/lib/parser/proxy-pool"
import {
  ParserValidationError,
  resolveParserInput,
} from "@/lib/parser/resolve-input"
import { parseRequestSchema } from "@/lib/parser/schema"
import {
  createScraperRouter,
  ParserScrapeError,
} from "@/lib/parser/scrapers"

export const runtime = "nodejs"

/**
 * Local BFF for WB/Ozon product parsing (avoids browser CORS).
 *
 * Temporary stub path: when marketplace scrapers are unavailable, falls back
 * to cheerio (`<title>` + `<meta name="description">` / Open Graph).
 * Antibot / Cloudflare challenge pages are never treated as product data.
 *
 * POST /api/parse
 * Body: `{ input | url | article, platform?: "auto"|"wb"|"ozon" }`
 */
export async function POST(request: Request) {
  let json: unknown
  try {
    json = await request.json()
  } catch {
    return NextResponse.json(
      { error: "Request body must be JSON.", code: "INVALID_JSON" },
      { status: 400 },
    )
  }

  const parsed = parseRequestSchema.safeParse(json)
  if (!parsed.success) {
    return NextResponse.json(
      {
        error: "Invalid parse request.",
        code: "VALIDATION_ERROR",
        details: parsed.error.flatten(),
      },
      { status: 400 },
    )
  }

  const { input, platform } = parsed.data

  try {
    return NextResponse.json(await parseProduct(input, platform), {
      status: 200,
    })
  } catch (error) {
    if (isAntibotScrapeError(error)) {
      return antibotJsonResponse()
    }

    if (error instanceof ParserValidationError) {
      return NextResponse.json(
        { error: error.message, code: error.code },
        { status: 400 },
      )
    }

    if (error instanceof ParserScrapeError) {
      const status =
        error.code === "NOT_FOUND"
          ? 404
          : error.code === "NOT_IMPLEMENTED"
            ? 501
            : 503
      return NextResponse.json(
        { error: error.message, code: error.code },
        { status },
      )
    }

    const message =
      error instanceof Error && error.message.trim()
        ? error.message.trim()
        : "Failed to parse marketplace product."

    console.error("[api/parse] unexpected error", error)
    return NextResponse.json(
      { error: message, code: "INTERNAL_ERROR" },
      { status: 500 },
    )
  }
}

function antibotJsonResponse() {
  return NextResponse.json(
    {
      error: ANTIBOT_ERROR_CODE,
      message: ANTIBOT_USER_MESSAGE,
    },
    { status: 403 },
  )
}

async function parseProduct(
  input: string,
  platform: "auto" | "wb" | "ozon",
) {
  const httpUrl = asHttpUrl(input)

  // Generic (or blocked marketplace) URL → cheerio meta stub.
  if (httpUrl && !looksLikeMarketplaceUrl(httpUrl)) {
    const meta = await scrapeHtmlMeta(httpUrl)
    return parsedProductFromHtmlMeta({ url: httpUrl, meta })
  }

  try {
    const target = resolveParserInput(input, platform)
    try {
      const http = new MarketplaceHttpClient({
        proxyPool: ProxyPool.fromEnv(),
      })
      const router = createScraperRouter({ http })
      return await router.scrape(target)
    } catch (scrapeError) {
      // Antibot: do not parse empty / challenge HTML as a product card.
      if (isAntibotScrapeError(scrapeError)) {
        throw scrapeError
      }

      // Temporary fallback while FastAPI / MP APIs are unstable.
      console.warn(
        "[api/parse] marketplace scraper failed, falling back to cheerio",
        scrapeError,
      )
      try {
        const meta = await scrapeHtmlMeta(target.productUrl)
        return parsedProductFromHtmlMeta({
          url: target.productUrl,
          meta,
          marketplace: target.marketplace,
          sku: target.sku,
        })
      } catch (fallbackError) {
        if (isAntibotScrapeError(fallbackError)) {
          throw fallbackError
        }
        throw scrapeError
      }
    }
  } catch (resolveError) {
    if (isAntibotScrapeError(resolveError)) {
      throw resolveError
    }
    if (httpUrl) {
      const meta = await scrapeHtmlMeta(httpUrl)
      return parsedProductFromHtmlMeta({ url: httpUrl, meta })
    }
    throw resolveError
  }
}

function asHttpUrl(raw: string): string | null {
  const trimmed = raw.trim()
  if (!trimmed) return null
  const withScheme = /^https?:\/\//i.test(trimmed)
    ? trimmed
    : trimmed.includes(".") && !/^\d{5,15}$/.test(trimmed)
      ? `https://${trimmed}`
      : null
  if (!withScheme) return null
  try {
    const url = new URL(withScheme)
    if (url.protocol !== "http:" && url.protocol !== "https:") return null
    return url.toString()
  } catch {
    return null
  }
}

function looksLikeMarketplaceUrl(url: string): boolean {
  try {
    const host = new URL(url).hostname.toLowerCase()
    return (
      host.includes("wildberries.") ||
      host === "wb.ru" ||
      host.endsWith(".wb.ru") ||
      host.includes("ozon.")
    )
  } catch {
    return false
  }
}
