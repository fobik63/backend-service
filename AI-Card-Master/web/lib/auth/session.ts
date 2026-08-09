/** Client-side session: localStorage + cookies (JWT access/refresh + user profile). */

export type AuthUser = {
  id: string
  email: string
  ai_coins: number
  subscription_status: string
  is_admin: boolean
  created_at?: string | null
}

export type AuthTokens = {
  access_token: string
  refresh_token: string
  token_type?: string
}

const ACCESS_KEY = "access_token"
const REFRESH_KEY = "refresh_token"
const USER_KEY = "auth_user"

/** ~30 days — aligns with typical refresh JWT TTL. */
const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30

function setCookie(name: string, value: string, maxAge = COOKIE_MAX_AGE_SECONDS) {
  if (typeof document === "undefined") return
  const secure =
    typeof window !== "undefined" && window.location.protocol === "https:"
      ? "; Secure"
      : ""
  document.cookie = `${encodeURIComponent(name)}=${encodeURIComponent(value)}; Path=/; Max-Age=${maxAge}; SameSite=Lax${secure}`
}

function deleteCookie(name: string) {
  if (typeof document === "undefined") return
  document.cookie = `${encodeURIComponent(name)}=; Path=/; Max-Age=0; SameSite=Lax`
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null
  const prefix = `${encodeURIComponent(name)}=`
  const parts = document.cookie.split("; ")
  for (const part of parts) {
    if (part.startsWith(prefix)) {
      return decodeURIComponent(part.slice(prefix.length))
    }
  }
  return null
}

export function persistSession(tokens: AuthTokens, user?: AuthUser | null) {
  if (typeof window === "undefined") return

  window.localStorage.setItem(ACCESS_KEY, tokens.access_token)
  window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token)
  setCookie(ACCESS_KEY, tokens.access_token)
  setCookie(REFRESH_KEY, tokens.refresh_token)

  if (user) {
    window.localStorage.setItem(USER_KEY, JSON.stringify(user))
  }
}

export function clearSession() {
  if (typeof window === "undefined") return
  window.localStorage.removeItem(ACCESS_KEY)
  window.localStorage.removeItem(REFRESH_KEY)
  window.localStorage.removeItem(USER_KEY)
  deleteCookie(ACCESS_KEY)
  deleteCookie(REFRESH_KEY)
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null
  return (
    window.localStorage.getItem(ACCESS_KEY) ||
    readCookie(ACCESS_KEY)
  )
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null
  return (
    window.localStorage.getItem(REFRESH_KEY) ||
    readCookie(REFRESH_KEY)
  )
}

export function getStoredUser(): AuthUser | null {
  if (typeof window === "undefined") return null
  const raw = window.localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as AuthUser
    if (!parsed?.id || !parsed?.email) return null
    return parsed
  } catch {
    return null
  }
}

export function displayNameFromEmail(email: string): string {
  const local = email.split("@")[0]?.trim() || "User"
  return local
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

export function subscriptionLabel(status: string | undefined | null): string {
  const normalized = (status || "").toLowerCase()
  if (!normalized || normalized === "none" || normalized === "free") return "FREE"
  if (normalized.includes("pro")) return "PRO"
  if (normalized.includes("half")) return "HALF"
  if (normalized.includes("year")) return "YEAR"
  return normalized.toUpperCase().slice(0, 12)
}
