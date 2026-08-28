import { apiClient } from "@/lib/api/client"
import type { AuthTokens, AuthUser } from "@/lib/auth/session"
import { IS_MOCK } from "@/lib/constants/mock"

export type AuthSessionResponse = {
  user: AuthUser
  tokens: AuthTokens
}

export type OtpRequestResponse = {
  ok: boolean
  expires_in: number
  message: string
}

export async function sendOtp(email: string): Promise<OtpRequestResponse> {
  const { data } = await apiClient.post<OtpRequestResponse>(
    "/auth/send-otp",
    { email },
    { skipErrorToast: true },
  )
  return data
}

export async function verifyOtp(
  email: string,
  code: string,
): Promise<AuthSessionResponse> {
  const { data } = await apiClient.post<AuthSessionResponse>(
    "/auth/verify-otp",
    { email, code },
    { skipErrorToast: true },
  )
  return data
}

export async function loginWithPassword(
  email: string,
  password: string,
): Promise<AuthSessionResponse> {
  const { data } = await apiClient.post<AuthSessionResponse>(
    "/auth/login",
    { email, password },
    { skipErrorToast: true },
  )
  return data
}

export async function registerWithPassword(
  email: string,
  password: string,
): Promise<AuthSessionResponse> {
  const { data } = await apiClient.post<AuthSessionResponse>(
    "/auth/register",
    { email, password },
    { skipErrorToast: true },
  )
  return data
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  if (IS_MOCK) {
    const { MOCK_AUTH_USER } = await import("@/lib/constants/mock")
    return MOCK_AUTH_USER
  }
  const { data } = await apiClient.get<AuthUser>("/auth/me", {
    skipErrorToast: true,
  })
  return data
}

export async function loginWithTelegram(
  payload: Record<string, unknown>,
): Promise<AuthSessionResponse> {
  const { data } = await apiClient.post<AuthSessionResponse>(
    "/auth/telegram",
    payload,
    { skipErrorToast: true },
  )
  return data
}

export async function logoutSession(): Promise<void> {
  await apiClient.post("/auth/logout", {}, { skipErrorToast: true })
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<{ ok: boolean; message: string }> {
  const { data } = await apiClient.post<{ ok: boolean; message: string }>(
    "/auth/change-password",
    {
      current_password: currentPassword,
      new_password: newPassword,
    },
    { skipErrorToast: true },
  )
  return data
}
