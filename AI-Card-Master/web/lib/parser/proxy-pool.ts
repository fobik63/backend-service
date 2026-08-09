import type { ProxyEndpoint } from "@/lib/parser/types"

/**
 * Round-robin proxy pool for marketplace HTTP calls.
 *
 * Configure via `PARSER_PROXY_URLS` (comma / newline separated), e.g.:
 * `http://user:pass@1.2.3.4:8080,http://5.6.7.8:3128`
 */
export class ProxyPool {
  private readonly endpoints: ProxyEndpoint[]
  private cursor = 0

  constructor(endpoints: ProxyEndpoint[] = []) {
    this.endpoints = endpoints.filter((item) => item.url.trim().length > 0)
  }

  static fromEnv(
    raw: string | undefined = process.env.PARSER_PROXY_URLS,
  ): ProxyPool {
    if (!raw?.trim()) return new ProxyPool()
    const urls = raw
      .split(/[\n,]+/)
      .map((part) => part.trim())
      .filter(Boolean)
    return new ProxyPool(urls.map((url) => ({ url })))
  }

  get size(): number {
    return this.endpoints.length
  }

  get enabled(): boolean {
    return this.endpoints.length > 0
  }

  /** Next proxy in rotation, or `null` when the pool is empty. */
  next(): ProxyEndpoint | null {
    if (this.endpoints.length === 0) return null
    const endpoint = this.endpoints[this.cursor % this.endpoints.length]
    this.cursor = (this.cursor + 1) % this.endpoints.length
    return endpoint
  }

  peekAll(): readonly ProxyEndpoint[] {
    return this.endpoints
  }
}
