import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
} from "axios"

import { ProxyPool } from "@/lib/parser/proxy-pool"
import { ParserRequestThrottle } from "@/lib/parser/throttle"
import type { ProxyEndpoint } from "@/lib/parser/types"
import {
  nextUserAgent,
  type UserAgentProfile,
} from "@/lib/parser/user-agents"

export type MarketplaceHttpRequest = {
  url: string
  method?: "GET" | "POST"
  headers?: Record<string, string>
  data?: unknown
  timeoutMs?: number
  /** Force axios responseType (useful for HTML pages). */
  responseType?: "json" | "text" | "arraybuffer"
  /**
   * Force a specific proxy for this call.
   * When omitted, the pool rotates automatically (if configured).
   */
  proxy?: ProxyEndpoint | null
  /** Skip proxy for this request even if the pool has endpoints. */
  bypassProxy?: boolean
  /** Prefer desktop / mobile / mixed UA profile for this call. */
  userAgentProfile?: UserAgentProfile
  /** Skip inter-request delay for this call. */
  bypassThrottle?: boolean
}

const DEFAULT_TIMEOUT_MS = 30_000

/** Browser-like defaults; User-Agent is rotated per request. */
export const DEFAULT_MARKETPLACE_HEADERS: Record<string, string> = {
  Accept: "application/json, text/plain, */*",
  "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

/**
 * Axios-backed HTTP helper with proxy rotation, UA rotation, and request delays.
 *
 * Proxy wiring notes for later hardening:
 * - Axios `proxy` covers classic HTTP(S) forward proxies.
 * - SOCKS / authenticated fleets can swap in `HttpsProxyAgent` /
 *   `SocksProxyAgent` via `config.httpAgent` / `httpsAgent` without
 *   changing scraper call sites.
 * - Configure `PARSER_PROXY_URLS` and `PARSER_REQUEST_DELAY_MS_*` in `.env`.
 */
export class MarketplaceHttpClient {
  private readonly axios: AxiosInstance
  private readonly proxyPool: ProxyPool
  private readonly throttle: ParserRequestThrottle

  constructor(options?: {
    proxyPool?: ProxyPool
    axiosInstance?: AxiosInstance
    defaultHeaders?: Record<string, string>
    throttle?: ParserRequestThrottle
  }) {
    this.proxyPool = options?.proxyPool ?? ProxyPool.fromEnv()
    this.throttle = options?.throttle ?? new ParserRequestThrottle()
    this.axios =
      options?.axiosInstance ??
      axios.create({
        timeout: DEFAULT_TIMEOUT_MS,
        headers: {
          ...DEFAULT_MARKETPLACE_HEADERS,
          ...(options?.defaultHeaders ?? {}),
        },
        // Marketplace CDNs often redirect; follow by default.
        maxRedirects: 5,
        validateStatus: (status) => status >= 200 && status < 400,
      })
  }

  get proxiesEnabled(): boolean {
    return this.proxyPool.enabled
  }

  async request<T = unknown>(
    req: MarketplaceHttpRequest,
  ): Promise<AxiosResponse<T>> {
    if (!req.bypassThrottle) {
      await this.throttle.waitBeforeRequest()
    }
    const config = this.buildAxiosConfig(req)
    return this.axios.request<T>(config)
  }

  async get<T = unknown>(
    url: string,
    init?: Omit<MarketplaceHttpRequest, "url" | "method" | "data">,
  ): Promise<AxiosResponse<T>> {
    return this.request<T>({ ...init, url, method: "GET" })
  }

  async post<T = unknown>(
    url: string,
    data?: unknown,
    init?: Omit<MarketplaceHttpRequest, "url" | "method" | "data">,
  ): Promise<AxiosResponse<T>> {
    return this.request<T>({ ...init, url, method: "POST", data })
  }

  /** Build axios config — kept public for unit tests / future agents. */
  buildAxiosConfig(req: MarketplaceHttpRequest): AxiosRequestConfig {
    const method = req.method ?? "GET"
    const selectedProxy = req.bypassProxy
      ? null
      : (req.proxy ?? this.proxyPool.next())

    const callerHeaders = req.headers ?? {}
    const hasExplicitUa = Object.keys(callerHeaders).some(
      (key) => key.toLowerCase() === "user-agent",
    )

    const config: AxiosRequestConfig = {
      url: req.url,
      method,
      headers: {
        ...DEFAULT_MARKETPLACE_HEADERS,
        ...callerHeaders,
        ...(hasExplicitUa
          ? {}
          : { "User-Agent": nextUserAgent(req.userAgentProfile ?? "auto") }),
        ...(selectedProxy?.label
          ? { "X-Proxy-Label": selectedProxy.label }
          : {}),
      },
      data: req.data,
      timeout: req.timeoutMs ?? DEFAULT_TIMEOUT_MS,
      responseType: req.responseType,
    }

    if (selectedProxy) {
      config.proxy = toAxiosProxy(selectedProxy.url)
    }

    return config
  }
}

/** Parse `http://user:pass@host:port` into axios proxy config. */
export function toAxiosProxy(proxyUrl: string): AxiosRequestConfig["proxy"] {
  const parsed = new URL(proxyUrl)
  const port = parsed.port
    ? Number(parsed.port)
    : parsed.protocol === "https:"
      ? 443
      : 80

  return {
    protocol: parsed.protocol.replace(":", ""),
    host: parsed.hostname,
    port,
    auth:
      parsed.username || parsed.password
        ? {
            username: decodeURIComponent(parsed.username),
            password: decodeURIComponent(parsed.password),
          }
        : undefined,
  }
}
