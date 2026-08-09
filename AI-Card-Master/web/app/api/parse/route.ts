import { NextResponse } from "next/server"

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
    const target = resolveParserInput(input, platform)
    const http = new MarketplaceHttpClient({
      proxyPool: ProxyPool.fromEnv(),
    })
    const router = createScraperRouter({ http })
    const product = await router.scrape(target)

    return NextResponse.json(product, { status: 200 })
  } catch (error) {
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

    console.error("[api/parse] unexpected error", error)
    return NextResponse.json(
      {
        error: "Failed to parse marketplace product.",
        code: "INTERNAL_ERROR",
      },
      { status: 500 },
    )
  }
}
