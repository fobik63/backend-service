import { apiClient } from "@/lib/api/client"
import { DEFAULT_API_BASE_URL } from "@/lib/constants/api"

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
  title: string
  brand?: string | null
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

/** Article / URL → structured card (S3-backed images when available). */
export async function fetchProductByArticle(
  input: string,
  platform: "auto" | "wb" | "ozon" = "auto",
): Promise<FetchProductResponse> {
  const { data } = await apiClient.post<FetchProductResponse>(
    "/parser/fetch",
    { input, platform },
    { timeout: 120_000, skipErrorToast: true },
  )
  return data
}

export async function generateSeoDescription(
  payload: SeoGenerateRequest,
  idempotencyKey?: string,
): Promise<SeoGenerateResponse> {
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
