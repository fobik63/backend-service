import { apiClient } from "@/lib/api/client"
import {
  delay,
  IS_MOCK,
  MOCK_EYE_OF_GOD_DASHBOARD,
  MOCK_EYE_OF_GOD_DELAY_MS,
} from "@/lib/constants/mock"

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

export async function enqueueEyeOfGodSpy(
  request: EyeOfGodEnqueueRequest,
): Promise<EyeOfGodEnqueueResponse> {
  if (IS_MOCK) {
    await delay(MOCK_EYE_OF_GOD_DELAY_MS)
    return {
      task_id: "mock-eye-of-god-task",
      status: "queued",
      status_url: "/api/v1/analytics/eye-of-god/mock-eye-of-god-task",
      competitors_count: MOCK_EYE_OF_GOD_DASHBOARD.competitors_analyzed,
      seed_title: MOCK_EYE_OF_GOD_DASHBOARD.seed_title,
      discovery: MOCK_EYE_OF_GOD_DASHBOARD.competitors.map((c) => ({
        rank: c.rank,
        article: c.article,
        url: c.url ?? `https://www.wildberries.ru/catalog/${c.article}/detail.aspx`,
        marketplace: c.marketplace,
        title: c.title,
        brand: c.brand,
        price_rub: c.price_rub,
      })),
    }
  }

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
}

export async function getEyeOfGodSpyJob(
  taskId: string,
): Promise<EyeOfGodJobResponse> {
  if (IS_MOCK) {
    await delay(900)
    return {
      task_id: taskId,
      status: "completed",
      status_url: `/api/v1/analytics/eye-of-god/${taskId}`,
      links: MOCK_EYE_OF_GOD_DASHBOARD.competitors.map(
        (c) =>
          c.url ??
          `https://www.wildberries.ru/catalog/${c.article}/detail.aspx`,
      ),
      dashboard: MOCK_EYE_OF_GOD_DASHBOARD,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: new Date().toISOString(),
    }
  }

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
