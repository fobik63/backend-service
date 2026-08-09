import type { MarketplaceHttpClient } from "@/lib/parser/http-client"
import { ParserScrapeError } from "@/lib/parser/errors"
import { scrapeOzonProduct } from "@/lib/parser/ozon"
import type { ParsedProduct, ResolvedProductTarget } from "@/lib/parser/types"
import { scrapeWildberriesProduct } from "@/lib/parser/wildberries"

export { ParserScrapeError } from "@/lib/parser/errors"

export type MarketplaceScraper = {
  marketplace: ParsedProduct["marketplace"]
  scrape(target: ResolvedProductTarget): Promise<ParsedProduct>
}

type ScraperDeps = {
  http: MarketplaceHttpClient
}

/** Wildberries scraper — card.wb.ru detail API + content enrichment. */
export function createWildberriesScraper(
  deps: ScraperDeps,
): MarketplaceScraper {
  return {
    marketplace: "wildberries",
    async scrape(target) {
      return scrapeWildberriesProduct(deps.http, target)
    },
  }
}

/**
 * Ozon scraper — `__NUXT__` HTML state first, Puppeteer+stealth fallback.
 */
export function createOzonScraper(deps: ScraperDeps): MarketplaceScraper {
  return {
    marketplace: "ozon",
    async scrape(target) {
      return scrapeOzonProduct(deps.http, target)
    },
  }
}

export function createScraperRouter(deps: ScraperDeps): {
  scrape(target: ResolvedProductTarget): Promise<ParsedProduct>
} {
  const scrapers: Record<
    ResolvedProductTarget["marketplace"],
    MarketplaceScraper
  > = {
    wildberries: createWildberriesScraper(deps),
    ozon: createOzonScraper(deps),
  }

  return {
    async scrape(target) {
      return scrapers[target.marketplace].scrape(target)
    },
  }
}
