/** Default FastAPI prefix used when env is missing or empty. */
export const DEFAULT_API_BASE_URL = "http://localhost:8000/api/v1"

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]", "::1"])

function isLoopbackHost(hostname: string): boolean {
  return LOOPBACK_HOSTS.has(hostname.trim().toLowerCase())
}

/**
 * When the page is opened via a LAN IP but the API base points at localhost,
 * rewrite the API host to the page hostname so a phone on Wi-Fi can reach
 * the PC backend (localhost on the phone is not the PC).
 */
export function rewriteLoopbackApiHost(
  baseUrl: string,
  pageHostname:
    | string
    | null
    | undefined = typeof window !== "undefined"
      ? window.location.hostname
      : undefined,
): string {
  if (!pageHostname || isLoopbackHost(pageHostname)) return baseUrl

  try {
    const url = new URL(baseUrl)
    if (!isLoopbackHost(url.hostname)) return baseUrl
    url.hostname = pageHostname
    return url.href.replace(/\/+$/, "")
  } catch {
    return baseUrl
  }
}

/**
 * Resolve public API base URL.
 * Always ends with `/api/v1` so paths like `/auth/login` hit the correct router.
 */
export function resolveApiBaseUrl(
  raw: string | undefined | null = process.env.NEXT_PUBLIC_API_BASE_URL,
  pageHostname?: string | null,
): string {
  const trimmed = (raw ?? "").trim().replace(/\/+$/, "")
  const base = trimmed || DEFAULT_API_BASE_URL

  let normalized: string
  if (base.endsWith("/api/v1")) normalized = base
  else if (base.endsWith("/api")) normalized = `${base}/v1`
  else normalized = `${base}/api/v1`

  return rewriteLoopbackApiHost(normalized, pageHostname)
}

export const API_BASE_URL = resolveApiBaseUrl()

export const APP_NAME = "AI Card Master"

/** Re-export mock flag for convenient imports next to API config. */
export { IS_MOCK } from "@/lib/constants/mock"
