export type {
  ParsedCharacteristic,
  ParsedProduct,
  ParserMarketplace,
  ParserPlatformHint,
  ProxyEndpoint,
  ResolvedProductTarget,
} from "@/lib/parser/types"
export type { NormalizedProductFields } from "@/lib/parser/normalize"
export {
  ParserValidationError,
  parseMarketplaceUrl,
  resolveParserInput,
} from "@/lib/parser/resolve-input"
export { parseRequestSchema, parseErrorSchema } from "@/lib/parser/schema"
export { ProxyPool } from "@/lib/parser/proxy-pool"
export {
  MarketplaceHttpClient,
  DEFAULT_MARKETPLACE_HEADERS,
  toAxiosProxy,
} from "@/lib/parser/http-client"
export { ParserRequestThrottle, sleep as parserSleep } from "@/lib/parser/throttle"
export {
  nextDesktopUserAgent,
  nextMobileUserAgent,
  nextUserAgent,
  resetUserAgentRotation,
} from "@/lib/parser/user-agents"
export {
  createOzonScraper,
  createScraperRouter,
  createWildberriesScraper,
  ParserScrapeError,
} from "@/lib/parser/scrapers"
export {
  buildParsedProduct,
  normalizeProductFields,
} from "@/lib/parser/normalize"
