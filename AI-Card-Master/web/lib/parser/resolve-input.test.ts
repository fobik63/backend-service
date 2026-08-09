import { describe, expect, it } from "vitest"

import {
  ParserValidationError,
  resolveParserInput,
} from "@/lib/parser/resolve-input"
import { parseRequestSchema } from "@/lib/parser/schema"
import { ProxyPool } from "@/lib/parser/proxy-pool"
import { MarketplaceHttpClient, toAxiosProxy } from "@/lib/parser/http-client"
import { ParserRequestThrottle } from "@/lib/parser/throttle"
import {
  nextUserAgent,
  resetUserAgentRotation,
} from "@/lib/parser/user-agents"

describe("resolveParserInput", () => {
  it("detects Wildberries from catalog URL", () => {
    const target = resolveParserInput(
      "https://www.wildberries.ru/catalog/178902345/detail.aspx",
    )
    expect(target.marketplace).toBe("wildberries")
    expect(target.sku).toBe("178902345")
  })

  it("detects Ozon from product URL", () => {
    const target = resolveParserInput(
      "https://www.ozon.ru/product/krem-123456789/",
    )
    expect(target.marketplace).toBe("ozon")
    expect(target.sku).toBe("123456789")
  })

  it("resolves bare article with explicit platform", () => {
    const wb = resolveParserInput("178902345", "wb")
    expect(wb.marketplace).toBe("wildberries")
    expect(wb.productUrl).toContain("/catalog/178902345/")

    const ozon = resolveParserInput("123456789", "ozon")
    expect(ozon.marketplace).toBe("ozon")
    expect(ozon.productUrl).toContain("ozon.ru/product/123456789")
  })

  it("rejects bare article in auto mode", () => {
    expect(() => resolveParserInput("178902345", "auto")).toThrow(
      ParserValidationError,
    )
  })

  it("rejects non-marketplace hosts", () => {
    expect(() =>
      resolveParserInput("https://example.com/product/123456"),
    ).toThrow(/wildberries\.ru/)
  })

  it("rejects platform mismatch", () => {
    expect(() =>
      resolveParserInput(
        "https://www.ozon.ru/product/krem-123456789/",
        "wb",
      ),
    ).toThrow(/does not match/)
  })
})

describe("parseRequestSchema", () => {
  it("accepts input alias fields", () => {
    expect(parseRequestSchema.parse({ url: "https://wb.ru/catalog/1" })).toEqual(
      {
        input: "https://wb.ru/catalog/1",
        platform: "auto",
      },
    )
    expect(parseRequestSchema.parse({ article: "123456", platform: "wb" })).toEqual(
      {
        input: "123456",
        platform: "wb",
      },
    )
  })

  it("requires at least one identifier", () => {
    expect(parseRequestSchema.safeParse({}).success).toBe(false)
  })
})

describe("proxy helpers", () => {
  it("rotates proxies round-robin", () => {
    const pool = new ProxyPool([
      { url: "http://a:1" },
      { url: "http://b:2" },
    ])
    expect(pool.next()?.url).toBe("http://a:1")
    expect(pool.next()?.url).toBe("http://b:2")
    expect(pool.next()?.url).toBe("http://a:1")
  })

  it("maps proxy URL into axios proxy config", () => {
    expect(toAxiosProxy("http://user:pass@10.0.0.1:8080")).toEqual({
      protocol: "http",
      host: "10.0.0.1",
      port: 8080,
      auth: { username: "user", password: "pass" },
    })
  })

  it("attaches rotating proxy and User-Agent to axios request config", () => {
    resetUserAgentRotation()
    const client = new MarketplaceHttpClient({
      proxyPool: new ProxyPool([{ url: "http://10.0.0.2:3128" }]),
      throttle: new ParserRequestThrottle({ disabled: true }),
    })
    const config = client.buildAxiosConfig({
      url: "https://www.wildberries.ru/catalog/1/detail.aspx",
    })
    expect(config.proxy).toEqual({
      protocol: "http",
      host: "10.0.0.2",
      port: 3128,
      auth: undefined,
    })
    expect(String(config.headers?.["User-Agent"] ?? "")).toMatch(/Mozilla/)
  })

  it("rotates User-Agent across consecutive builds", () => {
    resetUserAgentRotation()
    const first = nextUserAgent("desktop")
    const second = nextUserAgent("desktop")
    expect(first).not.toBe(second)
  })
})
