import { ParserScrapeError } from "@/lib/parser/errors"

/** Machine-readable code returned by POST /api/parse. */
export const ANTIBOT_ERROR_CODE = "antibot_detected" as const

/** User-facing RU message when marketplace Cloudflare / antibot blocks scraping. */
export const ANTIBOT_USER_MESSAGE =
  "Сработала защита маркетплейса от ботов. Временно введите данные вручную." as const

export function isAntibotChallengeText(
  value: string | null | undefined,
): boolean {
  if (!value) return false
  return /antibot\s*challenge/i.test(value)
}

/** Detect Cloudflare / marketplace antibot HTML pages by title or body markers. */
export function isAntibotHtml(html: string | null | undefined): boolean {
  if (!html) return false
  if (isAntibotChallengeText(html)) return true
  const title = /<title[^>]*>([^<]*)<\/title>/i.exec(html)?.[1]
  return isAntibotChallengeText(title)
}

export function isAntibotHttpStatus(status: number): boolean {
  return status === 403
}

/**
 * Cloudflare often sets `cf-mitigated: challenge` (or similar) on blocked pages.
 * Accepts Fetch `Headers`, axios header maps, or plain records.
 */
export function isAntibotResponseHeaders(
  headers: Headers | Record<string, unknown> | null | undefined,
): boolean {
  if (!headers) return false

  const value = headerValue(headers, "cf-mitigated")
  if (value && /challenge/i.test(value)) return true

  const server = headerValue(headers, "server")
  const location = headerValue(headers, "location")
  if (
    server &&
    /cloudflare/i.test(server) &&
    location &&
    /challenge|cdn-cgi/i.test(location)
  ) {
    return true
  }

  return false
}

export function antibotScrapeError(
  detail?: string,
): ParserScrapeError {
  const suffix = detail?.trim() ? ` (${detail.trim()})` : ""
  return new ParserScrapeError(
    `${ANTIBOT_USER_MESSAGE}${suffix}`,
    "ANTIBOT",
  )
}

export function isAntibotScrapeError(error: unknown): boolean {
  return error instanceof ParserScrapeError && error.code === "ANTIBOT"
}

function headerValue(
  headers: Headers | Record<string, unknown>,
  name: string,
): string | null {
  if (typeof (headers as Headers).get === "function") {
    const raw = (headers as Headers).get(name)
    return raw?.trim() || null
  }

  const record = headers as Record<string, unknown>
  const lower = name.toLowerCase()
  for (const [key, raw] of Object.entries(record)) {
    if (key.toLowerCase() !== lower) continue
    if (typeof raw === "string") return raw.trim() || null
    if (Array.isArray(raw) && typeof raw[0] === "string") {
      return raw[0].trim() || null
    }
  }
  return null
}
