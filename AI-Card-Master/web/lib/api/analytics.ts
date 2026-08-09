import axios from "axios"

import { apiClient } from "@/lib/api/client"
import { isNetworkError } from "@/lib/api/errors"
import { fetchProductByArticle } from "@/lib/api/marketplace"
import { delay } from "@/lib/constants/mock"

export type EyeOfGodPlatform = "auto" | "wb" | "ozon"

export type EyeOfGodDiscoveryHit = {
  rank: number
  article: string
  url: string
  marketplace: "wildberries" | "ozon" | string
  title?: string | null
  brand?: string | null
  price_rub?: number | null
  rating?: number | null
  feedbacks?: number | null
}

export type EyeOfGodFrequencyItem = {
  text: string
  count: number
  share_percent: number
  examples?: string[]
}

export type EyeOfGodCompetitorSummary = {
  rank: number
  article: string
  marketplace: string
  title?: string | null
  brand?: string | null
  url?: string | null
  price_rub?: number | null
  feedbacks?: number | null
  /** Heuristic: feedbacks × ~12.5 until MPSTATS/MarketGuru. */
  estimated_purchases?: number | null
  /** Оценочная выручка: estimated_purchases × price_rub. */
  estimated_revenue_rub?: number | null
  is_niche_revenue_leader?: boolean
  conversion_triggers?: string[]
  weaknesses?: string[]
  advice_reliability_pct?: number
}

export type EyeOfGodDashboard = {
  schema_version?: string
  seed_article: string
  seed_marketplace: string
  seed_title?: string | null
  competitors_analyzed: number
  competitors: EyeOfGodCompetitorSummary[]
  badge_patterns: EyeOfGodFrequencyItem[]
  strong_triggers: EyeOfGodFrequencyItem[]
  frequent_keywords: EyeOfGodFrequencyItem[]
  visual_hooks: string[]
  ai_recommendation: string
  generator_prompt: string
  notes?: string[]
}

export type EyeOfGodJobStatus =
  | "queued"
  | "scraping"
  | "analyzing"
  | "completed"
  | "failed"

export type EyeOfGodEnqueueResponse = {
  task_id: string
  status: EyeOfGodJobStatus
  status_url: string
  celery_task_id?: string | null
  idempotent_replay?: boolean
  competitors_count: number
  seed_title?: string | null
  discovery: EyeOfGodDiscoveryHit[]
}

export type EyeOfGodJobResponse = {
  task_id: string
  status: EyeOfGodJobStatus
  status_url: string
  links: string[]
  celery_task_id?: string | null
  result?: Record<string, unknown> | null
  analysis?: Record<string, unknown> | null
  dashboard?: EyeOfGodDashboard | null
  model_name?: string | null
  input_tokens?: number
  output_tokens?: number
  error_message?: string | null
  created_at: string
  updated_at: string
  completed_at?: string | null
}

export type EyeOfGodEnqueueRequest = {
  input: string
  platform?: EyeOfGodPlatform
  limit?: number
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID()
  }
  return `eye-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function shouldUseParseStub(error: unknown): boolean {
  if (isNetworkError(error)) return true
  if (!axios.isAxiosError(error)) return false
  const status = error.response?.status
  return status !== undefined && status >= 500
}

/** Temporary: seed URL/article via Next `/api/parse` (cheerio) when FastAPI is down. */
async function enqueueViaParseStub(
  request: EyeOfGodEnqueueRequest,
): Promise<EyeOfGodEnqueueResponse> {
  const product = await fetchProductByArticle(
    request.input,
    request.platform === "ozon"
      ? "ozon"
      : request.platform === "wb"
        ? "wb"
        : "auto",
  )
  const hit: EyeOfGodDiscoveryHit = {
    rank: 1,
    article: product.sku,
    url: product.product_url,
    marketplace: product.marketplace,
    title: product.name || product.title,
    brand: product.brand ?? null,
  }
  const taskId = `parse-stub-${product.sku}`
  return {
    task_id: taskId,
    status: "completed",
    status_url: `/api/v1/analytics/eye-of-god/${taskId}`,
    competitors_count: 1,
    seed_title: hit.title,
    discovery: [hit],
  }
}

export async function enqueueEyeOfGodSpy(
  request: EyeOfGodEnqueueRequest,
): Promise<EyeOfGodEnqueueResponse> {
  try {
    const { data } = await apiClient.post<EyeOfGodEnqueueResponse>(
      "/analytics/eye-of-god",
      {
        input: request.input.trim(),
        platform: request.platform ?? "auto",
        limit: request.limit ?? 10,
      },
      {
        headers: { "Idempotency-Key": newIdempotencyKey() },
        timeout: 120_000,
        skipErrorToast: true,
      },
    )
    return data
  } catch (error) {
    if (shouldUseParseStub(error)) {
      return enqueueViaParseStub(request)
    }
    throw error
  }
}

export async function getEyeOfGodSpyJob(
  taskId: string,
): Promise<EyeOfGodJobResponse> {
  const { data } = await apiClient.get<EyeOfGodJobResponse>(
    `/analytics/eye-of-god/${taskId}`,
    { skipErrorToast: true, timeout: 60_000 },
  )
  return data
}

const TERMINAL: EyeOfGodJobStatus[] = ["completed", "failed"]

export async function pollEyeOfGodSpyJob(
  taskId: string,
  options?: {
    intervalMs?: number
    maxAttempts?: number
    signal?: AbortSignal
  },
): Promise<EyeOfGodJobResponse> {
  const intervalMs = options?.intervalMs ?? 2500
  const maxAttempts = options?.maxAttempts ?? 90

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (options?.signal?.aborted) {
      throw new DOMException("Aborted", "AbortError")
    }
    const job = await getEyeOfGodSpyJob(taskId)
    if (TERMINAL.includes(job.status)) {
      return job
    }
    await delay(intervalMs)
  }

  throw new Error("Таймаут ожидания анализа «Глаз Бога»")
}

/** Keyword TOP-N competitor card from WB search. */
export type NicheCompetitorCard = {
  rank: number
  article: string
  title?: string | null
  brand?: string | null
  price_rub?: number | null
  rating?: number | null
  feedbacks?: number | null
  url: string
  estimated_purchases?: number | null
  estimated_revenue_rub?: number | null
  /** Client-side WB CDN thumbnail (when article is numeric nm_id). */
  thumbnail_url?: string | null
}

export type CompetitorsSearchResponse = {
  query: string
  count: number
  competitors: NicheCompetitorCard[]
}

export type CompetitorReviewsCollectionResponse = {
  articles: string[]
  competitors_processed: number
  reviews_fetched: number
  complaint_texts: string[]
  by_article: Array<{
    article: string
    reviews_fetched: number
    complaint_texts: string[]
    warning?: string | null
  }>
  warnings: string[]
}

export type BuyerPain = {
  rank: number
  title: string
  summary: string
  evidence_quotes: string[]
}

export type InfographicOffer = {
  pain_rank: number
  offer_text: string
}

export type CompetitorPainsAnalysisResponse = {
  pains: BuyerPain[]
  recommendations: InfographicOffer[]
  provider: string
  model_name: string
  input_tokens: number
  output_tokens: number
}

export async function searchCompetitors(options: {
  query: string
  limit?: number
}): Promise<CompetitorsSearchResponse> {
  const { data } = await apiClient.post<CompetitorsSearchResponse>(
    "/analytics/competitors",
    {
      query: options.query.trim(),
      limit: options.limit ?? 5,
    },
    { skipErrorToast: true, timeout: 60_000 },
  )
  return data
}

export async function collectCompetitorReviews(options: {
  articles: string[]
  maxReviewsPerArticle?: number
}): Promise<CompetitorReviewsCollectionResponse> {
  try {
    const { data } = await apiClient.post<CompetitorReviewsCollectionResponse>(
      "/analytics/competitors/reviews",
      {
        articles: options.articles,
        max_reviews_per_article: options.maxReviewsPerArticle ?? 40,
      },
      { skipErrorToast: true, timeout: 120_000 },
    )
    return data
  } catch (error) {
    if (!shouldUseParseStub(error)) throw error

    // Temporary stub: no fabricated cream complaints — empty corpus + clear warning.
    const articles = options.articles.slice(0, 10)
    return {
      articles,
      competitors_processed: articles.length,
      reviews_fetched: 0,
      complaint_texts: [],
      by_article: articles.map((article) => ({
        article,
        reviews_fetched: 0,
        complaint_texts: [],
        warning: "Сбор отзывов временно недоступен (бэкенд offline).",
      })),
      warnings: [
        "Сбор отзывов временно недоступен — запустите FastAPI analytics или повторите позже.",
      ],
    }
  }
}

export async function analyzeCompetitorPains(options: {
  complaintTexts: string[]
  productContext?: string
}): Promise<CompetitorPainsAnalysisResponse> {
  const { data } = await apiClient.post<CompetitorPainsAnalysisResponse>(
    "/analytics/competitors/reviews/analyze",
    {
      complaint_texts: options.complaintTexts,
      product_context: options.productContext ?? "",
    },
    { skipErrorToast: true, timeout: 180_000 },
  )
  return data
}
