/** Default FastAPI prefix used when env is missing or empty. */
export const DEFAULT_API_BASE_URL = "http://localhost:8000/api/v1"

/**
 * Resolve public API base URL.
 * Always ends with `/api/v1` so paths like `/auth/login` hit the correct router.
 */
export function resolveApiBaseUrl(
  raw: string | undefined | null = process.env.NEXT_PUBLIC_API_BASE_URL,
): string {
  const trimmed = (raw ?? "").trim().replace(/\/+$/, "")
  const base = trimmed || DEFAULT_API_BASE_URL

  if (base.endsWith("/api/v1")) return base
  if (base.endsWith("/api")) return `${base}/v1`
  return `${base}/api/v1`
}

export const API_BASE_URL = resolveApiBaseUrl()

export const APP_NAME = "AI Card Master"
