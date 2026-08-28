import { create } from "zustand"

import {
  clearSession,
  getAccessToken,
  getStoredUser,
  persistSession,
  persistUser,
  type AuthTokens,
  type AuthUser,
} from "@/lib/auth/session"
import { logoutSession } from "@/lib/api/auth"
import {
  IS_MOCK,
  MOCK_AUTH_TOKENS,
  MOCK_AUTH_USER,
} from "@/lib/constants/mock"

type AuthState = {
  accessToken: string | null
  user: AuthUser | null
  hydrated: boolean
  setAccessToken: (token: string | null) => void
  setUser: (user: AuthUser | null) => void
  setSession: (tokens: AuthTokens, user: AuthUser) => void
  /** Local-first coin credit while YooKassa webhook may still be in flight. */
  creditAiCoins: (delta: number) => void
  hydrateFromStorage: () => void
  clearAuth: () => void
}

function applyMockSession(
  set: (partial: Partial<AuthState>) => void,
) {
  persistSession(MOCK_AUTH_TOKENS, MOCK_AUTH_USER)
  set({
    accessToken: MOCK_AUTH_TOKENS.access_token,
    user: MOCK_AUTH_USER,
    hydrated: true,
  })
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  hydrated: false,
  setAccessToken: (accessToken) => set({ accessToken }),
  setUser: (user) => set({ user }),
  setSession: (tokens, user) => {
    persistSession(tokens, user)
    set({ accessToken: tokens.access_token, user })
  },
  creditAiCoins: (delta) =>
    set((state) => {
      if (!state.user || !Number.isFinite(delta) || delta <= 0) return state
      const user = {
        ...state.user,
        ai_coins: state.user.ai_coins + Math.trunc(delta),
      }
      persistUser(user)
      return { user }
    }),
  hydrateFromStorage: () => {
    if (IS_MOCK) {
      applyMockSession(set)
      return
    }
    const accessToken = getAccessToken()
    const user = getStoredUser()
    set({ accessToken, user, hydrated: true })
  },
  clearAuth: () => {
    if (IS_MOCK) {
      // Stay signed in as mock user — auth screens are fully bypassed.
      applyMockSession(set)
      return
    }
    clearSession()
    void logoutSession().catch(() => undefined)
    set({ accessToken: null, user: null })
  },
}))
