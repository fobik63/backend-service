import { apiClient } from "@/lib/api/client"
import { DEFAULT_API_BASE_URL } from "@/lib/constants/api"
import {
  delay,
  IS_MOCK,
  MOCK_GENERATE_DELAY_MS,
  MOCK_SEO_RESULT,
} from "@/lib/constants/mock"

function apiOrigin(): string {
  const base = (apiClient.defaults.baseURL || DEFAULT_API_BASE_URL).replace(
    /\/+$/,
    "",
  )
  return base.replace(/\/api\/v1$/i, "") || "http://localhost:8000"
}

export type SeoTargetPlatform = "wb" | "ozon"

export type SeoGenerateRequest = {
  title: string
  category: string
  features?: Record<string, string | number | boolean>
  targetPlatform: SeoTargetPlatform
}

export type SeoGenerateResponse = {
  success: boolean
  optimized_title: string
  benefits: string[]
  description: string
  coins_charged: number
  new_balance: number
  cost_coins: number
  targetPlatform: SeoTargetPlatform
}

export type FetchProductResponse = {
  marketplace: "wildberries" | "ozon"
  sku: string
  product_url: string
  /** Normalized name from marketplace parsers. */
  name?: string
  title: string
  brand?: string | null
  category?: string | null
  description?: string | null
  characteristics?: { name: string; value: string }[]
  source_image_urls?: string[]
  image_urls?: string[]
  cached?: boolean
}

export type SellerProductDTO = {
  platform: "wb" | "ozon"
  product_id: string
  title: string
  vendor_code?: string | null
  brand?: string | null
}

export type PublishStatusDTO = {
  id: string
  platform: string
  product_id: string
  status: "Success" | "Pending" | "Failed"
  message: string
  external_task_id?: string | null
  error_logs?: string[]
  created_at?: string | null
}

/** Prefer «Категория» / category / предмет from marketplace characteristics. */
export function categoryFromCharacteristics(
  characteristics?: { name: string; value: string }[] | null,
  fallback = "Товары",
): string {
  const found = characteristics?.find((c) =>
    /категор|category|предмет/i.test(c.name),
  )?.value
  return found?.trim() || fallback
}

/**
 * Bare numeric articles cannot be marketplace-detected from the string alone.
 * Default to WB so the editor «артикул» flow works with `platform: auto`.
 */
function resolveParsePlatform(
  input: string,
  platform: "auto" | "wb" | "ozon",
): "auto" | "wb" | "ozon" {
  if (platform !== "auto") return platform
  return /^\d{5,15}$/.test(input.trim()) ? "wb" : "auto"
}

function localParseUrl(): string {
  if (typeof window !== "undefined" && window.location?.origin) {
    return `${window.location.origin}/api/parse`
  }
  return "/api/parse"
}

/**
 * Article / URL → structured card via Next.js BFF ``POST /api/parse``
 * (cheerio meta stub + marketplace scrapers). Avoids browser CORS and
 * does not require the FastAPI parser while that backend is incomplete.
 */
export async function fetchProductByArticle(
  input: string,
  platform: "auto" | "wb" | "ozon" = "auto",
): Promise<FetchProductResponse> {
  const trimmed = input.trim()
  const resolvedPlatform = resolveParsePlatform(trimmed, platform)

  try {
    const { data } = await apiClient.post<FetchProductResponse>(
      localParseUrl(),
      { input: trimmed, platform: resolvedPlatform },
      { timeout: 120_000, skipErrorToast: true },
    )
    return data
  } catch (error) {
    // Caller (parser UI) maps this via getApiErrorMessage → sonner toast.
    throw error
  }
}

export async function generateSeoDescription(
  payload: SeoGenerateRequest,
  idempotencyKey?: string,
): Promise<SeoGenerateResponse> {
  if (IS_MOCK) {
    await delay(MOCK_GENERATE_DELAY_MS)
    void idempotencyKey
    return {
      success: true,
      optimized_title: MOCK_SEO_RESULT.optimized_title,
      benefits: [...MOCK_SEO_RESULT.benefits],
      description: MOCK_SEO_RESULT.description,
      coins_charged: 0,
      new_balance: 999,
      cost_coins: 0,
      targetPlatform: payload.targetPlatform,
    }
  }

  const headers: Record<string, string> = {}
  if (idempotencyKey) {
    headers["X-Idempotency-Key"] = idempotencyKey
  }
  const { data } = await apiClient.post<SeoGenerateResponse>(
    `${apiOrigin()}/api/ai/generate-description`,
    {
      title: payload.title,
      category: payload.category,
      features: payload.features ?? {},
      targetPlatform: payload.targetPlatform,
    },
    { headers, timeout: 120_000, skipErrorToast: true },
  )
  return data
}

export async function listSellerProducts(
  platform: "wb" | "ozon",
  limit = 50,
): Promise<SellerProductDTO[]> {
  const { data } = await apiClient.get<{ items: SellerProductDTO[] }>(
    `${apiOrigin()}/api/marketplaces/publish/products`,
    {
      params: { platform, limit },
      skipErrorToast: true,
    },
  )
  return data.items ?? []
}

export async function publishToWildberries(payload: {
  nm_id: number
  image_urls: string[]
  seo_text: string
  title?: string
  vendor_code?: string
}): Promise<PublishStatusDTO> {
  const { data } = await apiClient.post<PublishStatusDTO>(
    `${apiOrigin()}/api/marketplaces/publish/wb`,
    payload,
    { timeout: 120_000, skipErrorToast: true },
  )
  return data
}

export async function publishToOzon(payload: {
  product_id: number
  image_urls: string[]
  description: string
  offer_id?: string
}): Promise<PublishStatusDTO> {
  const { data } = await apiClient.post<PublishStatusDTO>(
    `${apiOrigin()}/api/marketplaces/publish/ozon`,
    payload,
    { timeout: 120_000, skipErrorToast: true },
  )
  return data
}
