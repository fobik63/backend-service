/** Marketplace identifiers returned by the local parse BFF. */
export type ParserMarketplace = "wildberries" | "ozon"

/** Client platform hint (matches FastAPI `/parser/fetch`). */
export type ParserPlatformHint = "auto" | "wb" | "ozon"

export type ParsedCharacteristic = {
  name: string
  value: string
}

/** Canonical product-card payload for the editor parser. */
export type ParsedProduct = {
  marketplace: ParserMarketplace
  sku: string
  product_url: string
  /** Normalized product name (preferred by the editor). */
  name: string
  /** Alias of `name` for older clients. */
  title: string
  brand?: string | null
  /** Top-level category when known (also mirrored in characteristics). */
  category?: string | null
  description?: string | null
  characteristics: ParsedCharacteristic[]
  image_urls: string[]
  source_image_urls: string[]
  cached?: boolean
}

/** Resolved, validated marketplace target ready for scraping. */
export type ResolvedProductTarget = {
  marketplace: ParserMarketplace
  sku: string
  productUrl: string
  /** Original user input after trim. */
  rawInput: string
}

export type ProxyEndpoint = {
  /** Full proxy URL, e.g. `http://user:pass@host:8080`. */
  url: string
  /** Optional label for logs / metrics. */
  label?: string
}
