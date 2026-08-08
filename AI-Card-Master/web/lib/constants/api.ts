export const API_BASE_URL = (() => {
  const raw =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1"
  const trimmed = raw.replace(/\/+$/, "")
  // Ensure /api/v1 suffix so /auth/register resolves correctly.
  if (trimmed.endsWith("/api/v1")) return trimmed
  if (trimmed.endsWith("/api")) return `${trimmed}/v1`
  return `${trimmed}/api/v1`
})()

export const APP_NAME = "AI Card Master"

