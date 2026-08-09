import { create } from "zustand"

import {
  clearSession,
  getAccessToken,
  getStoredUser,
  persistSession,
  type AuthTokens,
  type AuthUser,
} from "@/lib/auth/session"

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
    const accessToken = getAccessToken()
    const user = getStoredUser()
    set({ accessToken, user, hydrated: true })
  },
  clearAuth: () => {
    clearSession()
    set({ accessToken: null, user: null })
  },
}))
