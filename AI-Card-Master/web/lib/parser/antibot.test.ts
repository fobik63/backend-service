import { describe, expect, it } from "vitest"

import {
  ANTIBOT_ERROR_CODE,
  ANTIBOT_USER_MESSAGE,
  antibotScrapeError,
  isAntibotChallengeText,
  isAntibotHtml,
  isAntibotHttpStatus,
  isAntibotResponseHeaders,
  isAntibotScrapeError,
} from "@/lib/parser/antibot"
import { extractHtmlMeta } from "@/lib/parser/html-meta"

describe("antibot detection", () => {
  it("detects Antibot Challenge title text", () => {
    expect(isAntibotChallengeText("Antibot Challenge Page")).toBe(true)
    expect(isAntibotChallengeText("  antibot challenge  ")).toBe(true)
    expect(isAntibotChallengeText("SIM-карта МТС")).toBe(false)
  })

  it("detects antibot HTML by title tag", () => {
    const html = `<!doctype html><html><head><title>Antibot Challenge Page</title></head><body></body></html>`
    expect(isAntibotHtml(html)).toBe(true)
  })

  it("treats HTTP 403 as antibot status", () => {
    expect(isAntibotHttpStatus(403)).toBe(true)
    expect(isAntibotHttpStatus(404)).toBe(false)
  })

  it("detects Cloudflare cf-mitigated challenge header", () => {
    expect(
      isAntibotResponseHeaders({ "cf-mitigated": "challenge" }),
    ).toBe(true)
    expect(isAntibotResponseHeaders({ server: "cloudflare" })).toBe(false)
  })

  it("builds ParserScrapeError with ANTIBOT code", () => {
    const error = antibotScrapeError()
    expect(isAntibotScrapeError(error)).toBe(true)
    expect(error.code).toBe("ANTIBOT")
    expect(error.message).toContain(ANTIBOT_USER_MESSAGE)
    expect(ANTIBOT_ERROR_CODE).toBe("antibot_detected")
  })

  it("refuses to extract product meta from antibot HTML", () => {
    const html = `
      <html><head>
        <title>Antibot Challenge Page</title>
        <meta name="description" content="bot check" />
      </head><body></body></html>
    `
    expect(() => extractHtmlMeta(html, "https://www.ozon.ru/product/1/")).toThrow(
      /защит|antibot|ботов/i,
    )
  })
})
