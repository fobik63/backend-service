/** Client-side session: access token in localStorage; refresh is HttpOnly cookie. */

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
  refresh_token?: string
  token_type?: string
}

const ACCESS_KEY = "access_token"
const REFRESH_KEY = "refresh_token"
const USER_KEY = "auth_user"

function deleteLegacyCookie(name: string) {
  if (typeof document === "undefined") return
  document.cookie = `${encodeURIComponent(name)}=; Path=/; Max-Age=0; SameSite=Lax`
}

export function persistSession(tokens: AuthTokens, user?: AuthUser | null) {
  if (typeof window === "undefined") return

  window.localStorage.setItem(ACCESS_KEY, tokens.access_token)
  window.localStorage.removeItem(REFRESH_KEY)
  deleteLegacyCookie(ACCESS_KEY)
  deleteLegacyCookie(REFRESH_KEY)

  if (user) {
    persistUser(user)
  }
}

export function persistUser(user: AuthUser) {
  if (typeof window === "undefined") return
  window.localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearSession() {
  if (typeof window === "undefined") return
  window.localStorage.removeItem(ACCESS_KEY)
  window.localStorage.removeItem(REFRESH_KEY)
  window.localStorage.removeItem(USER_KEY)
  deleteLegacyCookie(ACCESS_KEY)
  deleteLegacyCookie(REFRESH_KEY)
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null
  return window.localStorage.getItem(ACCESS_KEY)
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
