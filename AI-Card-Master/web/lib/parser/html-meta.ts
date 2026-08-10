import * as cheerio from "cheerio"

import {
  antibotScrapeError,
  isAntibotChallengeText,
  isAntibotHtml,
  isAntibotHttpStatus,
  isAntibotResponseHeaders,
  isAntibotScrapeError,
} from "@/lib/parser/antibot"
import { nextDesktopUserAgent } from "@/lib/parser/user-agents"
import type { ParsedProduct, ParserMarketplace } from "@/lib/parser/types"
import { buildParsedProduct } from "@/lib/parser/normalize"

export type HtmlMetaFields = {
  title: string
  description: string
  ogImage: string | null
  canonicalUrl: string | null
}

const FETCH_TIMEOUT_MS = 25_000

/** Temporary stub: fetch HTML and read `<title>` + meta description. */
export async function scrapeHtmlMeta(url: string): Promise<HtmlMetaFields> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)

  try {
    const response = await fetch(url, {
      method: "GET",
      redirect: "follow",
      signal: controller.signal,
      headers: {
        Accept: "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "User-Agent": nextDesktopUserAgent(),
      },
    })

    if (
      isAntibotHttpStatus(response.status) ||
      isAntibotResponseHeaders(response.headers)
    ) {
      throw antibotScrapeError(`HTTP ${response.status}`)
    }

    if (!response.ok) {
      throw new Error(
        `Не удалось загрузить страницу (HTTP ${response.status}).`,
      )
    }

    const html = await response.text()
    if (isAntibotHtml(html)) {
      throw antibotScrapeError("HTML title/body")
    }
    return extractHtmlMeta(html, url)
  } catch (error) {
    if (isAntibotScrapeError(error)) throw error
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("Превышено время ожидания загрузки страницы.")
    }
    throw error
  } finally {
    clearTimeout(timer)
  }
}

export function extractHtmlMeta(html: string, fallbackUrl: string): HtmlMetaFields {
  if (isAntibotHtml(html)) {
    throw antibotScrapeError("HTML title/body")
  }

  const $ = cheerio.load(html)

  const title =
    clean(
      $('meta[property="og:title"]').attr("content") ||
        $('meta[name="twitter:title"]').attr("content") ||
        $("title").first().text(),
    ) || fallbackUrl

  if (isAntibotChallengeText(title)) {
    throw antibotScrapeError("parsed title")
  }

  const description = clean(
    $('meta[name="description"]').attr("content") ||
      $('meta[property="og:description"]').attr("content") ||
      $('meta[name="twitter:description"]').attr("content") ||
      "",
  )

  const ogImageRaw = clean(
    $('meta[property="og:image"]').attr("content") ||
      $('meta[name="twitter:image"]').attr("content") ||
      "",
  )
  const ogImage = ogImageRaw ? absolutize(ogImageRaw, fallbackUrl) : null

  const canonical =
    clean($('link[rel="canonical"]').attr("href") || "") ||
    clean($('meta[property="og:url"]').attr("content") || "") ||
    null

  return {
    title,
    description,
    ogImage,
    canonicalUrl: canonical ? absolutize(canonical, fallbackUrl) : null,
  }
}

/** Map cheerio meta fields into the editor parser payload shape. */
export function parsedProductFromHtmlMeta(options: {
  url: string
  meta: HtmlMetaFields
  marketplace?: ParserMarketplace
  sku?: string
}): ParsedProduct {
  const productUrl = options.meta.canonicalUrl || options.url
  const sku = options.sku || skuFromUrl(productUrl) || "html-meta"
  const marketplace = options.marketplace ?? guessMarketplace(productUrl)
  const images = options.meta.ogImage ? [options.meta.ogImage] : []

  return buildParsedProduct({
    marketplace,
    sku,
    productUrl,
    fields: {
      name: options.meta.title,
      description: options.meta.description,
      brand: "",
      category: "",
    },
    imageUrls: images,
    cached: false,
  })
}

function clean(value: string | undefined | null): string {
  return (value ?? "").replace(/\s+/g, " ").trim()
}

function absolutize(href: string, base: string): string {
  try {
    return new URL(href, base).toString()
  } catch {
    return href
  }
}

function skuFromUrl(url: string): string | null {
  try {
    const path = new URL(url).pathname
    const wb = /\/catalog\/(\d{5,})/i.exec(path)
    if (wb?.[1]) return wb[1]
    const ozon = /\/product\/[^/]*?(\d{6,})/i.exec(path)
    if (ozon?.[1]) return ozon[1]
    const digits = path.match(/(\d{5,15})/g)
    return digits?.[digits.length - 1] ?? null
  } catch {
    return null
  }
}

function guessMarketplace(url: string): ParserMarketplace {
  try {
    const host = new URL(url).hostname.toLowerCase()
    if (host.includes("ozon.")) return "ozon"
  } catch {
    /* ignore */
  }
  return "wildberries"
}
