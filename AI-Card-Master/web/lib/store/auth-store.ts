import { create } from "zustand"

import {
  clearSession,
  getAccessToken,
  getStoredUser,
  persistSession,
  type AuthTokens,
  type AuthUser,
} from "@/lib/auth/session"
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
    set({ accessToken: null, user: null })
  },
}))
