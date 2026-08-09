/**
 * Rotating browser / mobile User-Agents for WB / Ozon scrapes.
 * Keeps egress fingerprints from looking like a single static bot.
 */

const DESKTOP_CHROME_USER_AGENTS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
] as const

const MOBILE_SAFARI_USER_AGENTS = [
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
  "Mozilla/5.0 (Linux; Android 13; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
] as const

export type UserAgentProfile = "desktop" | "mobile" | "auto"

let desktopCursor = 0
let mobileCursor = 0

function nextFromPool(pool: readonly string[], cursor: number): [string, number] {
  const ua = pool[cursor % pool.length]
  return [ua, (cursor + 1) % pool.length]
}

/** Round-robin desktop browser UA. */
export function nextDesktopUserAgent(): string {
  const [ua, next] = nextFromPool(DESKTOP_CHROME_USER_AGENTS, desktopCursor)
  desktopCursor = next
  return ua
}

/** Round-robin mobile browser UA (useful for WB card API). */
export function nextMobileUserAgent(): string {
  const [ua, next] = nextFromPool(MOBILE_SAFARI_USER_AGENTS, mobileCursor)
  mobileCursor = next
  return ua
}

/**
 * Pick the next rotating User-Agent.
 * `auto` alternates desktop/mobile so consecutive calls look less scripted.
 */
export function nextUserAgent(profile: UserAgentProfile = "auto"): string {
  if (profile === "desktop") return nextDesktopUserAgent()
  if (profile === "mobile") return nextMobileUserAgent()
  return Math.random() < 0.55
    ? nextDesktopUserAgent()
    : nextMobileUserAgent()
}

/** Test helper — reset rotation cursors. */
export function resetUserAgentRotation(): void {
  desktopCursor = 0
  mobileCursor = 0
}
